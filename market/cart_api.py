"""Cart + checkout JSON API."""
import hmac
import json
from datetime import timedelta

from django.db import transaction
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import payments, services
from .api import ApiError, api_endpoint, as_int, json_body, need_role
from .cart import Cart
from .models import Checkout, Listing, Order, Payment
from .utils import normalise_phone, role_of
from django.conf import settings


def _buyers_only(request):
    if request.user.is_authenticated and role_of(request.user) != "buyer":
        raise ApiError("Only buyer accounts can order. Log out and register as a buyer to shop.", 403)


@api_endpoint
@require_GET
def cart_get(request):
    return JsonResponse(Cart(request).summary())


@api_endpoint
@require_POST
def cart_add(request):
    _buyers_only(request)
    data = json_body(request)
    listing_id, qty = as_int(data.get("listingId")), as_int(data.get("qty"))
    if listing_id is None or qty is None or qty < 1:
        raise ApiError("Choose a quantity of at least 1 kg.")
    listing = Listing.objects.filter(pk=listing_id, is_active=True, qty_kg__gt=0).first()
    if not listing:
        raise ApiError("That listing is no longer available.", 404)
    cart = Cart(request)
    before = cart.get(listing_id)
    cart.set(listing_id, min(before + qty, listing.qty_kg))
    out = cart.summary()
    out["added"] = cart.get(listing_id) - before
    if out["added"] < qty:
        out["notes"].append(f"Only {listing.qty_kg} kg of {listing.produce.name} is available, so your cart holds the maximum.")
    return JsonResponse(out)


@api_endpoint
@require_POST
def cart_set(request):
    _buyers_only(request)
    data = json_body(request)
    listing_id, qty = as_int(data.get("listingId")), as_int(data.get("qty"))
    if listing_id is None or qty is None or qty < 0:
        raise ApiError("Invalid quantity.")
    cart = Cart(request)
    if qty:
        listing = Listing.objects.filter(pk=listing_id, is_active=True).first()
        qty = min(qty, listing.qty_kg) if listing else 0
    cart.set(listing_id, qty)
    return JsonResponse(cart.summary())


@api_endpoint
@require_POST
def checkout_create(request):
    need_role(request, "buyer")
    services.expire_unpaid_soon()
    data = json_body(request)
    phone = normalise_phone(str(data.get("phone", "")))
    address = str(data.get("address", "")).strip()
    note = str(data.get("note", "")).strip()
    if not phone:
        raise ApiError("Enter a Safaricom number like 0712345678.")
    if not 5 <= len(address) <= 200:
        raise ApiError("Enter a delivery address (area, street or landmark).")
    if len(note) > 300:
        raise ApiError("Delivery notes can be up to 300 characters.")
    cart = Cart(request)
    if not cart.data:
        raise ApiError("Your cart is empty.", 409)

    with transaction.atomic():
        ids = sorted(int(k) for k in cart.data)                     # same lock order for everyone
        listings = {l.id: l for l in Listing.objects.select_for_update().filter(pk__in=ids, is_active=True)}
        for lid in ids:
            l = listings.get(lid)
            if not l or cart.data[str(lid)] > l.qty_kg:
                cart.lines()                                          # refresh the cart so the page shows the truth
                raise ApiError("Some items in your cart changed while you were checking out. Please review your cart.", 409)
        checkout = Checkout.objects.create(buyer=request.user, phone=phone, address=address, note=note)
        for lid in ids:
            l, qty = listings[lid], cart.data[str(lid)]
            Order.objects.create(
                checkout=checkout, listing=l, buyer=request.user, qty_kg=qty, phone=phone,
                produce_value=l.price_per_kg * qty, delivery_fee=settings.SOKO_DELIVERY_PER_KG * qty)
            l.qty_kg -= qty
            l.save(update_fields=["qty_kg"])
    cart.clear()
    return JsonResponse({"id": checkout.id, "ref": checkout.ref, "total": checkout.total,
                         "done": reverse("checkout_done", args=[checkout.id])}, status=201)


def _pay_json(checkout, payment):
    """What the browser needs to know about one payment attempt."""
    return {"status": payment.status.lower(), "message": payments.message_for(payment), "paymentId": payment.id,
            "ref": checkout.ref, "receipt": payment.receipt, "paidTo": payment.paid_to,
            "simulated": payment.simulated, "done": reverse("checkout_done", args=[checkout.id])}


@api_endpoint
@require_POST
def checkout_pay(request, checkout_id):
    """Start paying. Real mode: send the M-Pesa PIN prompt to the buyer's phone and answer 202 (pending);
    the browser then polls checkout_status. Simulated mode: pay at once and answer 200."""
    need_role(request, "buyer")
    data = json_body(request)
    phone = None
    if data.get("phone"):
        phone = normalise_phone(str(data["phone"]))
        if not phone:
            raise ApiError("Enter a Safaricom number like 0712345678.")

    with transaction.atomic():
        checkout = Checkout.objects.select_for_update().filter(pk=checkout_id, buyer=request.user).first()
        if not checkout:
            raise ApiError("Checkout not found.", 404)
        if checkout.is_paid:
            raise ApiError("This checkout is already paid.", 409)
        if not checkout.orders.filter(status=Order.Status.AWAITING_PAYMENT).exists():
            raise ApiError("Nothing left to pay. These orders may have been cancelled.", 409)
        if checkout.payments.filter(status=Payment.Status.NEEDS_REVIEW).exists():
            raise ApiError("We already received a payment for this order and are checking it. Please don't pay again.", 409)
        # A prompt is already open on the buyer's phone: pick that one up instead of sending a second one.
        fresh = timezone.now() - timedelta(seconds=settings.MPESA_PROMPT_TIMEOUT)
        open_prompt = checkout.payments.filter(status=Payment.Status.PENDING, created__gte=fresh).first()
        if open_prompt:
            return JsonResponse(_pay_json(checkout, open_prompt), status=202)
        if phone and phone != checkout.phone:           # the buyer chose a different number to pay with
            checkout.phone = phone
            checkout.save(update_fields=["phone"])
            checkout.orders.update(phone=phone)
        payment = Payment.objects.create(checkout=checkout, phone=checkout.phone, amount=checkout.total,
                                         paid_to=payments.receiving_account(), simulated=payments.simulated())

    # Talk to M-Pesa outside the transaction so the database isn't locked while we wait on Safaricom.
    if payment.simulated:
        ok, receipt = payments.collect_payment(checkout)
        payment = payments.finish_payment(payment.pk, result_code=0 if ok else -1, receipt=receipt, desc="Simulated")
        return JsonResponse(_pay_json(checkout, payment))
    try:
        payments.send_stk_push(payment)
    except payments.PaymentError as e:
        payments.finish_payment(payment.pk, result_code=-1, desc=str(e))
        raise ApiError(str(e), 502)
    payment.refresh_from_db()
    return JsonResponse(_pay_json(checkout, payment), status=202)


@api_endpoint
@require_GET
def checkout_status(request, checkout_id):
    """The browser polls this while the PIN prompt is open."""
    need_role(request, "buyer")
    checkout = Checkout.objects.filter(pk=checkout_id, buyer=request.user).first()
    if not checkout:
        raise ApiError("Checkout not found.", 404)
    payment = checkout.payments.first()
    if not payment:
        return JsonResponse({"status": "none", "message": "", "done": reverse("checkout_done", args=[checkout.id])})
    return JsonResponse(_pay_json(checkout, payments.refresh_pending(payment)))


@csrf_exempt
@require_POST
def mpesa_callback(request, token):
    """Safaricom calls this when the buyer finishes (or abandons) the prompt. There is no login or CSRF here,
    so the secret in the URL is the lock, and the payment is matched by Safaricom's own request id."""
    if not settings.MPESA_CALLBACK_TOKEN or not hmac.compare_digest(token, settings.MPESA_CALLBACK_TOKEN):
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Rejected"}, status=404)
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        body = None
    payments.handle_callback(body)
    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})   # always thank Safaricom, so it stops retrying
