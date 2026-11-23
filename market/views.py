from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse

from .forms import ContactForm, RegisterForm
from .cart import Cart
from .models import Checkout, Produce
from .utils import emoji_for, fee_for, photo_url, role_of


def _boot(request, produce):
    """Handed to static/js/main.js through {{ boot|json_script }}."""
    role = role_of(request.user)
    return {
        "produce": [{"id": p.slug, "name": p.name, "emoji": emoji_for(p.slug), "photo": photo_url(p.slug), "ref": [p.ref_min, p.ref_max]} for p in produce],
        "config": {"feePercent": settings.SOKO_FEE_PERCENT, "deliveryPerKg": settings.SOKO_DELIVERY_PER_KG,
                   "demoMode": settings.DEMO_MODE},
        "user": {"name": request.user.get_full_name() or request.user.get_username(), "role": role}
        if request.user.is_authenticated else None,
        "loginUrl": reverse("login"),
        "urls": {"market": reverse("market"), "sell": reverse("sell"), "dashboard": reverse("dashboard")},
    }


def home(request):
    produce = list(Produce.objects.all())
    return render(request, "market/home.html", {"produce": produce, "boot": _boot(request, produce)})


def market(request):
    """All listings, with the produce filter."""
    produce = list(Produce.objects.all())
    return render(request, "pages/market.html", {"produce": produce, "boot": _boot(request, produce)})


def sell(request):
    """The farmer's page: how selling works, and the listing form for logged-in farmers."""
    produce = list(Produce.objects.all())
    profile = getattr(request.user, "profile", None) if request.user.is_authenticated else None
    return render(request, "pages/sell.html", {
        "produce": produce, "boot": _boot(request, produce), "role": role_of(request.user),
        "default_location": profile.location if profile else "",
    })


def how_it_works(request):
    # A worked example using the real fee and delivery rate, so the page never drifts from the settings.
    qty, price = 100, 50
    value = qty * price
    fee = fee_for(value)
    example = {"qty": qty, "price": price, "value": value, "delivery": qty * settings.SOKO_DELIVERY_PER_KG,
               "total": value + qty * settings.SOKO_DELIVERY_PER_KG, "fee": fee, "payout": value - fee}
    return render(request, "pages/how_it_works.html", {"example": example})


def about(request):
    return render(request, "pages/about.html", {"produce": Produce.objects.all()})


def faq(request):
    return render(request, "pages/faq.html")


def terms(request):
    return render(request, "pages/terms.html")


def privacy(request):
    return render(request, "pages/privacy.html")


def contact(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not form.cleaned_data.get("website"):          # filled in = a bot; pretend it worked
            form.save()
        messages.success(request, "Thank you. We got your message and will reply as soon as we can.")
        return redirect("contact")
    return render(request, "pages/contact.html", {"form": form})


def not_found(request, exception):
    return render(request, "404.html", status=404)


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = RegisterForm(request.POST or None)
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        nxt = ""
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)          # the cart lives in the session and survives this
        messages.success(request, f"Welcome, {user.first_name}! Your {form.cleaned_data['role']} account is ready.")
        return redirect(nxt or "home")
    return render(request, "registration/register.html", {"form": form, "next": nxt})


@login_required
def checkout(request):
    if role_of(request.user) != "buyer":
        messages.info(request, "Only buyer accounts can check out. Farmers list produce from their dashboard.")
        return redirect("home")
    cart = Cart(request).summary()
    if not cart["items"]:
        messages.info(request, "Your cart is empty. Add some produce first.")
        return redirect("home")
    profile = request.user.profile
    return render(request, "shop/checkout.html", {"cart": cart, "phone": "0" + profile.phone[3:] if profile.phone.startswith("254") else profile.phone, "address": profile.location})


@login_required
def checkout_done(request, pk):
    checkout = get_object_or_404(Checkout, pk=pk, buyer=request.user)
    orders = checkout.orders.select_related("listing__produce", "listing__farmer")
    return render(request, "shop/done.html", {"checkout": checkout, "orders": orders})
