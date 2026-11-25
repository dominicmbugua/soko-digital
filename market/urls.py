from django.contrib.auth import views as auth_views
from django.urls import path

from . import api, cart_api, dashboards, views
from .forms import LoginForm

urlpatterns = [
    # Pages
    path("", views.home, name="home"),
    path("market/", views.market, name="market"),
    path("sell/", views.sell, name="sell"),
    path("how-it-works/", views.how_it_works, name="how_it_works"),
    path("about/", views.about, name="about"),
    path("faq/", views.faq, name="faq"),
    path("contact/", views.contact, name="contact"),
    path("terms/", views.terms, name="terms"),
    path("privacy/", views.privacy, name="privacy"),
    path("dashboard/", dashboards.dashboard, name="dashboard"),
    path("dashboard/farmer/", dashboards.farmer_dashboard, name="farmer_dashboard"),
    path("dashboard/farmer/listings/<int:pk>/edit/", dashboards.listing_edit, name="listing_edit"),
    path("dashboard/farmer/listings/<int:pk>/toggle/", dashboards.listing_toggle, name="listing_toggle"),
    path("dashboard/farmer/listings/<int:pk>/delete/", dashboards.listing_delete, name="listing_delete"),
    path("dashboard/buyer/", dashboards.buyer_dashboard, name="buyer_dashboard"),
    path("dashboard/ops/", dashboards.ops_dashboard, name="ops_dashboard"),
    path("dashboard/ops/orders/<int:order_id>/", dashboards.ops_action, name="ops_action"),
    path("register/", views.register, name="register"),
    path("login/", auth_views.LoginView.as_view(authentication_form=LoginForm), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),

    # Cart and checkout
    path("checkout/", views.checkout, name="checkout"),
    path("checkout/<int:pk>/done/", views.checkout_done, name="checkout_done"),

    # JSON API
    path("api/cart/", cart_api.cart_get, name="api_cart"),
    path("api/cart/add/", cart_api.cart_add, name="api_cart_add"),
    path("api/cart/set/", cart_api.cart_set, name="api_cart_set"),
    path("api/checkout/", cart_api.checkout_create, name="api_checkout"),
    path("api/checkout/<int:checkout_id>/pay/", cart_api.checkout_pay, name="api_checkout_pay"),
    path("api/checkout/<int:checkout_id>/status/", cart_api.checkout_status, name="api_checkout_status"),
    path("api/mpesa/callback/<str:token>/", cart_api.mpesa_callback, name="api_mpesa_callback"),
    path("api/listings/", api.listings, name="api_listings"),
    path("api/orders/", api.create_order, name="api_create_order"),
    path("api/payments/collect/", api.collect_payment, name="api_collect_payment"),
    path("api/orders/<int:order_id>/deliver/", api.deliver_order, name="api_deliver_order"),
    path("api/orders/<int:order_id>/confirm/", api.confirm_order, name="api_confirm_order"),
    path("api/orders/<int:order_id>/report/", api.report_order, name="api_report_order"),
]
