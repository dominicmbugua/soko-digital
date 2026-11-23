"""Money/stock actions run by staff (ops dashboard). All safe to repeat: they check status first."""
from django.db import transaction

from .models import Listing, Order
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
