from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse

from .forms import RegisterForm
from .cart import Cart
from .models import Checkout, Produce
from .utils import emoji_for, role_of


def home(request):
    produce = list(Produce.objects.all())
    role = role_of(request.user)
    profile = getattr(request.user, "profile", None) if request.user.is_authenticated else None

    # Handed to static/js/main.js through {{ boot|json_script }}
    boot = {
        "produce": [{"id": p.slug, "name": p.name, "emoji": emoji_for(p.slug), "ref": [p.ref_min, p.ref_max]} for p in produce],
        "config": {"feePercent": settings.SOKO_FEE_PERCENT, "deliveryPerKg": settings.SOKO_DELIVERY_PER_KG,
                   "demoMode": settings.DEMO_MODE},
        "user": {"name": request.user.get_full_name() or request.user.get_username(), "role": role}
        if request.user.is_authenticated else None,
        "loginUrl": reverse("login"),
    }
    return render(request, "market/home.html", {
        "produce": produce, "boot": boot, "role": role,
        "default_location": profile.location if profile else "",
    })


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
