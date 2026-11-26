"""Money/stock actions run by staff (ops dashboard). All safe to repeat: they check status first."""
import re
import time
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Listing, Order, Payment
from .utils import fee_for


class ServiceError(Exception):
    pass


def _return_stock(order):
    listing = Listing.objects.select_for_update().get(pk=order.listing_id)
    listing.qty_kg += order.qty_kg
    listing.save(update_fields=["qty_kg"])


def ops_action(order_id, action):
    """deliver: held -> delivered | release: dispute -> farmer paid | refund: held/dispute -> buyer refunded | cancel: unpaid -> cancelled"""
    S = Order.Status
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if action == "deliver" and order.status == S.PAYMENT_HELD:
            order.status = S.DELIVERED
        elif action == "release" and order.status == S.DISPUTED:
            order.fee = fee_for(order.produce_value)
            order.farmer_payout = order.produce_value - order.fee
            order.status = S.SETTLED
        elif action == "refund" and order.status in (S.PAYMENT_HELD, S.DISPUTED):
            order.status = S.REFUNDED
            _return_stock(order)
        elif action == "cancel" and order.status == S.AWAITING_PAYMENT:
            order.status = S.CANCELLED
            _return_stock(order)
        else:
            raise ServiceError(f"{order.ref} is '{order.get_status_display()}', so '{action}' isn't allowed.")
        order.save()
    return order


# ---------- Cancel orders nobody paid for ----------
_last_expiry = None            # monotonic time of the last busy-page run


def expire_unpaid(minutes=None):
    """Cancel orders that stayed unpaid too long and give the stock back. Returns how many were cancelled.

    Never touches a checkout that has an open M-Pesa prompt, or money that arrived and is waiting for review.
    Safe to run any time, as often as you like.
    """
    minutes = getattr(settings, "SOKO_UNPAID_EXPIRY_MINUTES", 30) if minutes is None else minutes
    now = timezone.now()
    protected = Payment.objects.filter(
        Q(status=Payment.Status.NEEDS_REVIEW)
        | Q(status=Payment.Status.PENDING, created__gte=now - timedelta(seconds=settings.MPESA_PROMPT_TIMEOUT))
    ).values("checkout_id")
    stale = (Order.objects.filter(status=Order.Status.AWAITING_PAYMENT, created__lt=now - timedelta(minutes=minutes))
             .exclude(checkout_id__in=protected).values_list("pk", flat=True))
    cancelled = 0
    for pk in list(stale):
        try:
            ops_action(pk, "cancel")
            cancelled += 1
        except (ServiceError, Order.DoesNotExist):
            pass                                    # it was paid or cancelled a moment ago
    return cancelled


def expire_unpaid_soon():
    """Same, but at most once a minute per server process. Called from busy pages so expiry still happens
    when no scheduled job is set up. (A scheduled `manage.py expire_unpaid` is still the tidy way.)"""
    global _last_expiry
    if _last_expiry is not None and time.monotonic() - _last_expiry < 60:
        return 0
    _last_expiry = time.monotonic()
    return expire_unpaid()


# ---------- Paying farmers (manual for now: ops sends the money, then records it here) ----------
def mark_payout(farmer_id, order_ids, amount, reference):
    """Record that we sent a farmer the money for these settled orders. Refuses if the list changed meanwhile."""
    reference = re.sub(r"\s", "", reference or "").upper()
    if not re.fullmatch(r"[A-Z0-9]{6,20}", reference):
        raise ServiceError("Enter the M-Pesa code of the transfer you sent (letters and numbers, e.g. UKPPH3K0GR).")
    with transaction.atomic():
        orders = list(Order.objects.select_for_update().filter(
            pk__in=order_ids, listing__farmer_id=farmer_id, status=Order.Status.SETTLED, paid_out_at__isnull=True))
        if not order_ids or len(orders) != len(set(order_ids)) or sum(o.farmer_payout for o in orders) != amount:
            raise ServiceError("That payout list changed (an order was paid or added). Reload the page and check the amount.")
        now = timezone.now()
        for o in orders:
            o.paid_out_at, o.payout_ref = now, reference
            o.save()
    return orders

