"""Cart + checkout JSON API."""
from django.db import transaction
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import payments
from .api import ApiError, api_endpoint, as_int, json_body, need_role
from .cart import Cart
from .models import Checkout, Listing, Order
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


@api_endpoint
@require_POST
def checkout_pay(request, checkout_id):
    need_role(request, "buyer")
    with transaction.atomic():
        checkout = Checkout.objects.select_for_update().filter(pk=checkout_id, buyer=request.user).first()
        if not checkout:
            raise ApiError("Checkout not found.", 404)
        if checkout.is_paid:
            raise ApiError("This checkout is already paid.", 409)
        orders = list(checkout.orders.select_for_update().filter(status=Order.Status.AWAITING_PAYMENT))
        if not orders:
            raise ApiError("Nothing left to pay. These orders may have been cancelled.", 409)
        ok, receipt = payments.collect_payment(checkout)
        if not ok:
            raise ApiError("Payment was not completed. You can try again.", 402)
        for o in orders:
            o.status, o.mpesa_receipt = Order.Status.PAYMENT_HELD, receipt
            o.save()
        checkout.mpesa_receipt, checkout.paid_at = receipt, timezone.now()
        checkout.save()
    return JsonResponse({"ref": checkout.ref, "receipt": receipt, "done": reverse("checkout_done", args=[checkout.id])})
