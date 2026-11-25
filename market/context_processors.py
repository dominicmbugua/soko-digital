def cart(request):
    """Number of different items in the cart, for the navbar badge (reads only, never creates a session)."""
    return {"cart_count": len(request.session.get("cart", {}))}


def site(request):
    """Fee, delivery rate and contact details for every template as {{ site.* }}."""
    from django.conf import settings

    from . import payments

    wa = "".join(ch for ch in settings.SOKO_WHATSAPP if ch.isdigit())
    return {"site": {"fee": settings.SOKO_FEE_PERCENT, "delivery": settings.SOKO_DELIVERY_PER_KG,
                     "email": settings.SOKO_CONTACT_EMAIL, "phone": settings.SOKO_CONTACT_PHONE,
                     "phone_href": "".join(ch for ch in settings.SOKO_CONTACT_PHONE if ch.isdigit() or ch == "+"),
                     "whatsapp": wa, "whatsapp_url": f"https://wa.me/{wa}" if wa else "",
                     "has_contact": bool(settings.SOKO_CONTACT_EMAIL or settings.SOKO_CONTACT_PHONE or wa),
                     "pay_to": payments.receiving_account(), "mpesa_simulated": payments.simulated()}}
