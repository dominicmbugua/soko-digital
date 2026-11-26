"""JSON API used by static/js/main.js.

Rules: the server decides every price, fee and status change. The browser only
asks; it never tells us what something costs.
Success -> the JSON object. Failure -> {"error": "message"} with a status code.
"""
import json

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST

from . import payments, services
from .models import Listing, Order, Produce
from .utils import fee_for, normalise_phone, role_of


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def json_body(request):
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        raise ApiError("Invalid request.")
    if not isinstance(data, dict):
        raise ApiError("Invalid request.")
    return data


def as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def need_role(request, role):
    if not request.user.is_authenticated:
        raise ApiError("Please log in first.", 401)
    if role_of(request.user) != role:
        raise ApiError(f"Only {role} accounts can do this.", 403)


def api_endpoint(view):
    """Turn ApiError exceptions into JSON error responses."""
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ApiError as e:
            return error(e.message, e.status)
    wrapper.__name__ = view.__name__
    return wrapper


# ---------- serialisers (same shape the front-end already used) ----------
def listing_json(l):
    return {
        "id": l.id, "farmer": l.farmer_name, "location": l.location,
        "produce": l.produce.slug, "price": l.price_per_kg, "qty": l.qty_kg, "grade": l.grade,
    }


def order_json(o):
    return {
        "id": o.id, "ref": o.ref, "listingId": o.listing_id, "qty": o.qty_kg, "phone": o.phone,
        "produceValue": o.produce_value, "delivery": o.delivery_fee, "status": o.status,
        "receipt": o.mpesa_receipt,
        "settlement": {"fee": o.fee, "farmerPayout": o.farmer_payout} if o.status == Order.Status.SETTLED else None,
    }


# ---------- listings ----------
@api_endpoint
@require_http_methods(["GET", "POST"])
def listings(request):
    if request.method == "GET":
        services.expire_unpaid_soon()
        qs = Listing.objects.filter(is_active=True).select_related("produce", "farmer")[:200]
        return JsonResponse([listing_json(l) for l in qs], safe=False)

    need_role(request, "farmer")
    data = json_body(request)
    produce = Produce.objects.filter(slug=str(data.get("produce", ""))).first()
    location = str(data.get("location", "")).strip()
    grade = str(data.get("grade", ""))
    qty, price = as_int(data.get("qty")), as_int(data.get("price"))

    if not produce:
        raise ApiError("Choose a produce type.")
    if not location or len(location) > 80:
        raise ApiError("Enter where the produce is (up to 80 characters).")
    if grade not in ("A", "B", "C"):
        raise ApiError("Choose a grade: A, B or C.")
    if qty is None or not (10 <= qty <= 100000):
        raise ApiError("Quantity must be between 10 and 100,000 kg.")
    if price is None or not (1 <= price <= 100000):
        raise ApiError("Enter a price per kg between 1 and 100,000.")

    listing = Listing.objects.create(
        farmer=request.user, produce=produce, location=location,
        grade=grade, qty_kg=qty, price_per_kg=price,
    )
    return JsonResponse(listing_json(listing), status=201)


# ---------- orders ----------
@api_endpoint
@require_POST
def create_order(request):
    need_role(request, "buyer")
    data = json_body(request)
    listing_id, qty = as_int(data.get("listingId")), as_int(data.get("qty"))
    phone = normalise_phone(str(data.get("phone", "")))
    if listing_id is None:
        raise ApiError("Choose a listing.")
    if qty is None or qty < 1:
        raise ApiError("Enter a quantity of at least 1 kg.")
    if not phone:
        raise ApiError("Enter a Safaricom number like 0712345678.")

    with transaction.atomic():
        # Lock the row so two buyers cannot take the same kilograms.
        listing = Listing.objects.select_for_update().filter(pk=listing_id, is_active=True).first()
        if not listing:
            raise ApiError("That listing is no longer available.", 404)
        if qty > listing.qty_kg:
            raise ApiError("Not enough produce left in this listing.", 409)
        listing.qty_kg -= qty
        listing.save(update_fields=["qty_kg"])
        order = Order.objects.create(
            listing=listing, buyer=request.user, qty_kg=qty, phone=phone,
            produce_value=listing.price_per_kg * qty,
            delivery_fee=settings.SOKO_DELIVERY_PER_KG * qty,
        )
    return JsonResponse(order_json(order), status=201)


def transition(request, order_id, expected, apply):
    """Move a buyer's own order from `expected` status onward, safely."""
    need_role(request, "buyer")
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(pk=order_id, buyer=request.user).first()
        if not order:
            raise ApiError("Order not found.", 404)
        if order.status != expected:
            raise ApiError(f"This order is '{order.get_status_display()}', so that step isn't allowed.", 409)
        apply(order)
        order.save()
    return JsonResponse(order_json(order))


@api_endpoint
@require_POST
def collect_payment(request):
    order_id = as_int(json_body(request).get("orderId"))

    def apply(order):
        ok, receipt = payments.collect_payment(order)
        if not ok:
            raise ApiError("Payment was not completed.", 402)
        order.mpesa_receipt = receipt
        order.status = Order.Status.PAYMENT_HELD

    return transition(request, order_id, Order.Status.AWAITING_PAYMENT, apply)


@api_endpoint
@require_POST
def deliver_order(request, order_id):
    if not settings.DEMO_MODE:
        raise ApiError("Delivery is confirmed by our team.", 403)

    def apply(order):
        order.status = Order.Status.DELIVERED

    return transition(request, order_id, Order.Status.PAYMENT_HELD, apply)


@api_endpoint
@require_POST
def confirm_order(request, order_id):
    def apply(order):
        order.fee = fee_for(order.produce_value)
        order.farmer_payout = order.produce_value - order.fee
        order.status = Order.Status.SETTLED

    return transition(request, order_id, Order.Status.DELIVERED, apply)


@api_endpoint
@require_POST
def report_order(request, order_id):
    def apply(order):
        order.status = Order.Status.DISPUTED

    return transition(request, order_id, Order.Status.DELIVERED, apply)
