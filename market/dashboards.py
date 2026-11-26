"""Farmer, buyer and ops (staff) dashboards."""
from collections import defaultdict
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .forms import ListingEditForm
from .models import Listing, Order, Payment, Profile
from .utils import fee_for, role_of

S = Order.Status
PAID = (S.PAYMENT_HELD, S.DELIVERED, S.SETTLED, S.DISPUTED)   # statuses where the buyer's money was taken


def role_required(role):
    def deco(view):
        @wraps(view)
        @login_required
        def wrapper(request, *a, **kw):
            if role_of(request.user) != role:
                messages.info(request, f"That page is for {role} accounts.")
                return redirect("dashboard")
            return view(request, *a, **kw)
        return wrapper
    return deco


def staff_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *a, **kw):
        if not request.user.is_staff:
            raise PermissionDenied
        return view(request, *a, **kw)
    return wrapper


def daily_series(pairs, days=14):
    """[(date, value), ...] -> last `days` days as bar-chart data."""
    today = timezone.localdate()
    totals = defaultdict(int)
    for d, v in pairs:
        totals[d] += v
    out = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        out.append({"label": f"{d.day} {d:%b}", "value": totals.get(d, 0)})
    peak = max([x["value"] for x in out] + [1])
    for x in out:
        x["pct"] = round(x["value"] * 100 / peak)
    return out


def total(qs, field):
    return qs.aggregate(t=Sum(field))["t"] or 0


@login_required
def dashboard(request):
    """/dashboard/ sends each person to the right one."""
    if request.user.is_staff:
        return redirect("ops_dashboard")
    role = role_of(request.user)
    if role in ("farmer", "buyer"):
        return redirect(f"{role}_dashboard")
    return redirect("home")


# ---------------- Farmer ----------------
@role_required("farmer")
def farmer_dashboard(request):
    user = request.user
    listings = Listing.objects.filter(farmer=user).select_related("produce")
    orders = Order.objects.filter(listing__farmer=user).select_related("listing__produce", "buyer")
    settled = orders.filter(status=S.SETTLED)
    sent = settled.filter(paid_out_at__isnull=False)
    awaiting_payout = settled.filter(paid_out_at__isnull=True)
    in_progress = orders.filter(status__in=(S.PAYMENT_HELD, S.DELIVERED))
    since = timezone.now() - timedelta(days=14)
    chart = daily_series(((timezone.localtime(o.updated).date(), o.farmer_payout)
                          for o in settled.filter(updated__gte=since)))
    return render(request, "dashboard/farmer.html", {
        "listings": listings, "orders": orders[:25],
        "paid_out": total(sent, "farmer_payout"),
        "pending": sum(o.produce_value - fee_for(o.produce_value) for o in in_progress) + total(awaiting_payout, "farmer_payout"),
        "kg_sold": total(orders.filter(status__in=(S.PAYMENT_HELD, S.DELIVERED, S.SETTLED)), "qty_kg"),
        "live_count": listings.filter(is_active=True, qty_kg__gt=0).count(),
        "sold_out": [l for l in listings if l.is_active and l.qty_kg == 0],
        "disputed": orders.filter(status=S.DISPUTED).count(),
        "chart": chart, "chart_total": sum(x["value"] for x in chart),
    })


def _own_listing(request, pk):
    return get_object_or_404(Listing, pk=pk, farmer=request.user)


@role_required("farmer")
def listing_edit(request, pk):
    listing = _own_listing(request, pk)
    form = ListingEditForm(request.POST or None, instance=listing)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Listing updated.")
        return redirect("farmer_dashboard")
    return render(request, "dashboard/listing_form.html", {"form": form, "listing": listing})


@role_required("farmer")
@require_POST
def listing_toggle(request, pk):
    listing = _own_listing(request, pk)
    listing.is_active = not listing.is_active
    listing.save(update_fields=["is_active"])
    messages.success(request, "Listing is live again." if listing.is_active else "Listing paused. Buyers can't see it.")
    return redirect("farmer_dashboard")


@role_required("farmer")
@require_POST
def listing_delete(request, pk):
    listing = _own_listing(request, pk)
    if listing.orders.exists():
        listing.is_active = False
        listing.save(update_fields=["is_active"])
        messages.info(request, "This listing has orders, so it was paused instead of deleted.")
    else:
        listing.delete()
        messages.success(request, "Listing deleted.")
    return redirect("farmer_dashboard")


# ---------------- Buyer ----------------
@role_required("buyer")
def buyer_dashboard(request):
    orders = Order.objects.filter(buyer=request.user).select_related("listing__produce", "listing__farmer")
    active = (S.AWAITING_PAYMENT, S.PAYMENT_HELD, S.DELIVERED)
    return render(request, "dashboard/buyer.html", {
        "orders": orders,
        "active_count": orders.filter(status__in=active).count(),
        "needs_action": orders.filter(status__in=(S.AWAITING_PAYMENT, S.DELIVERED)).count(),
        "spent": total(orders.filter(status__in=(S.PAYMENT_HELD, S.DELIVERED, S.SETTLED)), "produce_value")
                 + total(orders.filter(status__in=(S.PAYMENT_HELD, S.DELIVERED, S.SETTLED)), "delivery_fee"),
        "order_count": orders.count(),
        "demo": settings.DEMO_MODE,
    })


# ---------------- Ops (staff) ----------------
def _phone_local(phone):
    return "0" + phone[3:] if phone.startswith("254") else phone


def _owed_to_farmers():
    """Settled orders we haven't sent the money for yet, grouped by farmer, ready for a manual M-Pesa transfer."""
    groups = {}
    qs = (Order.objects.filter(status=S.SETTLED, paid_out_at__isnull=True)
          .select_related("listing__farmer__profile").order_by("updated"))
    for o in qs:
        f = o.listing.farmer
        profile = getattr(f, "profile", None)
        g = groups.setdefault(f.id, {"id": f.id, "name": f.get_full_name() or f.get_username(), "orders": [], "total": 0,
                                     "phone": _phone_local(profile.phone) if profile else "(no phone on file)"})
        g["orders"].append(o)
        g["total"] += o.farmer_payout
    for g in groups.values():
        g["ids"] = ",".join(str(o.id) for o in g["orders"])
        g["refs"] = ", ".join(o.ref for o in g["orders"])
    return sorted(groups.values(), key=lambda g: -g["total"])


@staff_required
def ops_dashboard(request):
    services.expire_unpaid_soon()
    orders = Order.objects.select_related("listing__produce", "listing__farmer", "buyer", "checkout")
    since = timezone.now() - timedelta(days=14)
    recent = orders.filter(created__gte=since)
    paid = orders.filter(status__in=PAID)
    by = lambda status: orders.filter(status=status)
    top = (paid.values("listing__produce__name").annotate(value=Sum("produce_value"), kg=Sum("qty_kg"), n=Count("id"))
           .order_by("-value")[:5])
    held = orders.filter(status__in=(S.PAYMENT_HELD, S.DELIVERED, S.DISPUTED))
    received = Payment.objects.filter(status__in=(Payment.Status.SUCCESS, Payment.Status.NEEDS_REVIEW), simulated=False)
    return render(request, "dashboard/ops.html", {
        "order_count": orders.count(),
        "gmv": total(paid, "produce_value"),
        "fees": total(by(S.SETTLED), "fee"),
        "held": total(held, "produce_value") + total(held, "delivery_fee"),
        "paid_out": total(by(S.SETTLED).filter(paid_out_at__isnull=False), "farmer_payout"),
        "owed": total(by(S.SETTLED).filter(paid_out_at__isnull=True), "farmer_payout"),
        "payouts": _owed_to_farmers(),
        "recent_payouts": by(S.SETTLED).filter(paid_out_at__isnull=False).select_related("listing__farmer").order_by("-paid_out_at")[:8],
        "farmers": Profile.objects.filter(role="farmer").count(),
        "buyers": Profile.objects.filter(role="buyer").count(),
        "unpaid": by(S.AWAITING_PAYMENT), "ready": by(S.PAYMENT_HELD), "delivered": by(S.DELIVERED),
        "disputes": by(S.DISPUTED), "recent_settled": by(S.SETTLED)[:8],
        "orders_chart": daily_series(((timezone.localtime(o.created).date(), 1) for o in recent)),
        "sales_chart": daily_series(((timezone.localtime(o.created).date(), o.produce_value) for o in recent.filter(status__in=PAID))),
        "top": top,
        # Where the money was received: real M-Pesa payments only (simulated ones are not money).
        "mpesa_received": total(received, "amount"),
        "mpesa_review": Payment.objects.filter(status=Payment.Status.NEEDS_REVIEW).count(),
        "payments": Payment.objects.select_related("checkout__buyer")[:15],
    })


@staff_required
@require_POST
def ops_action(request, order_id):
    get_object_or_404(Order, pk=order_id)
    try:
        order = services.ops_action(order_id, request.POST.get("action", ""))
        messages.success(request, f"{order.ref} is now '{order.get_status_display()}'.")
    except services.ServiceError as e:
        messages.warning(request, str(e))
    return redirect("ops_dashboard")


@staff_required
@require_POST
def ops_payout(request, farmer_id):
    """Ops sent a farmer their money by M-Pesa and records the transfer code here."""
    ids = [int(x) for x in request.POST.get("orders", "").split(",") if x.isdigit()]
    amount = int(request.POST["amount"]) if request.POST.get("amount", "").isdigit() else -1
    try:
        orders = services.mark_payout(farmer_id, ids, amount, request.POST.get("reference", ""))
        messages.success(request, f"Recorded: KES {amount:,} sent for {len(orders)} order(s).")
    except services.ServiceError as e:
        messages.warning(request, str(e))
    return redirect("ops_dashboard")
