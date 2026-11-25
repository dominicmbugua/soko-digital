import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import payments
from .models import Checkout, ContactMessage, Listing, Order, Payment, Produce, Profile


def make_user(username, role, first="Test"):
    u = User.objects.create_user(username, password="pass12345", first_name=first, last_name=username.title())
    Profile.objects.create(user=u, role=role, phone="254711111111", location="Molo")
    return u


class Base(TestCase):
    def setUp(self):
        self.farmer = make_user("farmer1", "farmer")
        self.buyer = make_user("buyer1", "buyer")
        self.potatoes = Produce.objects.get(slug="potatoes")   # seeded by migration
        self.listing = Listing.objects.create(farmer=self.farmer, produce=self.potatoes, location="Molo",
                                              grade="A", qty_kg=100, price_per_kg=50)

    def post(self, url, data=None):
        return self.client.post(url, json.dumps(data or {}), content_type="application/json")


class SeedTests(Base):
    def test_produce_seeded(self):
        self.assertEqual(Produce.objects.count(), 8)


class AuthTests(Base):
    def test_register_creates_profile_and_logs_in(self):
        r = self.client.post(reverse("register"), {
            "role": "farmer", "first_name": "Amina", "last_name": "Otieno", "username": "amina",
            "email": "", "phone": "0712 345 678", "location": "Nakuru",
            "password1": "a-Strong-pass-77", "password2": "a-Strong-pass-77"})
        self.assertRedirects(r, reverse("home"))
        p = Profile.objects.get(user__username="amina")
        self.assertEqual((p.role, p.phone), ("farmer", "254712345678"))

    def test_register_rejects_bad_phone(self):
        r = self.client.post(reverse("register"), {
            "role": "buyer", "first_name": "A", "last_name": "B", "username": "ab", "phone": "123",
            "password1": "a-Strong-pass-77", "password2": "a-Strong-pass-77"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="ab").exists())

    def test_pages_render(self):
        for name in ("home", "login", "register"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)   # needs login


class ListingApiTests(Base):
    def test_anyone_can_read_listings(self):
        r = self.client.get("/api/listings/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()[0]["produce"], "potatoes")

    def test_anonymous_cannot_post(self):
        r = self.post("/api/listings/", {})
        self.assertEqual(r.status_code, 401)

    def test_buyer_cannot_post(self):
        self.client.login(username="buyer1", password="pass12345")
        self.assertEqual(self.post("/api/listings/", {}).status_code, 403)

    def test_farmer_creates_listing_saved_in_db(self):
        self.client.login(username="farmer1", password="pass12345")
        r = self.post("/api/listings/", {"produce": "maize", "location": "Njoro", "grade": "B", "qty": 200, "price": 60})
        self.assertEqual(r.status_code, 201)
        l = Listing.objects.get(pk=r.json()["id"])
        self.assertEqual((l.farmer, l.qty_kg, l.price_per_kg), (self.farmer, 200, 60))

    def test_validation(self):
        self.client.login(username="farmer1", password="pass12345")
        bad = [{"produce": "maize", "location": "x", "grade": "B", "qty": 5, "price": 60},
               {"produce": "nope", "location": "x", "grade": "B", "qty": 50, "price": 60},
               {"produce": "maize", "location": "x", "grade": "Z", "qty": 50, "price": 60},
               {"produce": "maize", "location": "x", "grade": "B", "qty": 50, "price": -3}]
        for body in bad:
            self.assertEqual(self.post("/api/listings/", body).status_code, 400, body)


class OrderFlowTests(Base):
    def setUp(self):
        super().setUp()
        self.client.login(username="buyer1", password="pass12345")

    def new_order(self, qty=40):
        return self.post("/api/orders/", {"listingId": self.listing.id, "qty": qty, "phone": "0712345678"})

    def test_full_happy_path_and_fee(self):
        r = self.new_order(40)
        self.assertEqual(r.status_code, 201)
        o = r.json()
        self.assertEqual((o["produceValue"], o["delivery"]), (2000, 240))   # server-side maths
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.qty_kg, 60)

        self.assertEqual(self.post("/api/payments/collect/", {"orderId": o["id"]}).json()["status"], "PAYMENT_HELD")
        self.assertEqual(self.post(f"/api/orders/{o['id']}/deliver/").json()["status"], "DELIVERED")
        done = self.post(f"/api/orders/{o['id']}/confirm/").json()
        self.assertEqual(done["status"], "SETTLED")
        self.assertEqual(done["settlement"], {"fee": 160, "farmerPayout": 1840})   # 8% of 2000

    def test_cannot_oversell(self):
        self.assertEqual(self.new_order(101).status_code, 409)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.qty_kg, 100)

    def test_cannot_skip_steps(self):
        oid = self.new_order().json()["id"]
        self.assertEqual(self.post(f"/api/orders/{oid}/confirm/").status_code, 409)   # not delivered yet
        self.post("/api/payments/collect/", {"orderId": oid})
        self.assertEqual(self.post("/api/payments/collect/", {"orderId": oid}).status_code, 409)  # no double payment

    def test_other_buyer_cannot_touch_order(self):
        oid = self.new_order().json()["id"]
        make_user("buyer2", "buyer")
        self.client.logout()
        self.client.login(username="buyer2", password="pass12345")
        self.assertEqual(self.post("/api/payments/collect/", {"orderId": oid}).status_code, 404)

    def test_farmer_cannot_order(self):
        self.client.logout()
        self.client.login(username="farmer1", password="pass12345")
        self.assertEqual(self.new_order().status_code, 403)

    def test_bad_phone(self):
        r = self.post("/api/orders/", {"listingId": self.listing.id, "qty": 5, "phone": "12"})
        self.assertEqual(r.status_code, 400)

    def test_report_problem_holds_money(self):
        oid = self.new_order().json()["id"]
        self.post("/api/payments/collect/", {"orderId": oid})
        self.post(f"/api/orders/{oid}/deliver/")
        r = self.post(f"/api/orders/{oid}/report/")
        self.assertEqual(r.json()["status"], "DISPUTED")
        self.assertEqual(Order.objects.get(pk=oid).farmer_payout, 0)

    @override_settings(DEMO_MODE=False)
    def test_website_cannot_mark_delivered_outside_demo(self):
        oid = self.new_order().json()["id"]
        self.post("/api/payments/collect/", {"orderId": oid})
        self.assertEqual(self.post(f"/api/orders/{oid}/deliver/").status_code, 403)


class DashboardTests(Base):
    def login(self, name):
        self.client.login(username=name, password="pass12345")

    def test_dispatcher_sends_each_role_to_its_dashboard(self):
        self.login("farmer1")
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("farmer_dashboard"))
        self.client.logout(); self.login("buyer1")
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("buyer_dashboard"))
        staff = User.objects.create_user("ops", password="pass12345", is_staff=True)
        self.client.logout(); self.client.login(username="ops", password="pass12345")
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("ops_dashboard"))

    def test_roles_are_separated(self):
        self.login("buyer1")
        self.assertRedirects(self.client.get(reverse("farmer_dashboard")), reverse("dashboard"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("ops_dashboard")).status_code, 403)
        self.client.logout(); self.login("farmer1")
        self.assertEqual(self.client.get(reverse("ops_dashboard")).status_code, 403)

    def _settled_order(self):
        o = Order.objects.create(listing=self.listing, buyer=self.buyer, qty_kg=40, phone="254712345678",
                                 produce_value=2000, delivery_fee=240, status="SETTLED", fee=160, farmer_payout=1840)
        return o

    def test_farmer_dashboard_numbers(self):
        self._settled_order()
        self.login("farmer1")
        r = self.client.get(reverse("farmer_dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["paid_out"], 1840)
        self.assertEqual(r.context["kg_sold"], 40)
        self.assertEqual(r.context["chart_total"], 1840)

    def test_farmer_listing_controls(self):
        self.login("farmer1")
        self.client.post(reverse("listing_toggle", args=[self.listing.id]))
        self.listing.refresh_from_db(); self.assertFalse(self.listing.is_active)
        r = self.client.post(reverse("listing_edit", args=[self.listing.id]),
                             {"location": "Molo", "grade": "B", "qty_kg": 500, "price_per_kg": 55})
        self.assertEqual(r.status_code, 302)
        self.listing.refresh_from_db(); self.assertEqual((self.listing.qty_kg, self.listing.price_per_kg), (500, 55))

    def test_cannot_touch_other_farmers_listing(self):
        make_user("farmer2", "farmer")
        self.login("farmer2")
        self.assertEqual(self.client.post(reverse("listing_delete", args=[self.listing.id])).status_code, 404)
        self.assertTrue(Listing.objects.filter(pk=self.listing.id).exists())

    def test_delete_listing_with_orders_only_pauses(self):
        self._settled_order()
        self.login("farmer1")
        self.client.post(reverse("listing_delete", args=[self.listing.id]))
        self.listing.refresh_from_db(); self.assertFalse(self.listing.is_active)

    def test_delete_listing_without_orders(self):
        self.login("farmer1")
        self.client.post(reverse("listing_delete", args=[self.listing.id]))
        self.assertFalse(Listing.objects.filter(pk=self.listing.id).exists())

    def test_buyer_dashboard_only_shows_own_orders(self):
        self._settled_order()
        other = make_user("buyer2", "buyer")
        Order.objects.create(listing=self.listing, buyer=other, qty_kg=5, phone="254712345678", produce_value=250, delivery_fee=30)
        self.login("buyer1")
        r = self.client.get(reverse("buyer_dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["order_count"], 1)
        self.assertEqual(r.context["spent"], 2240)


class OpsTests(Base):
    def setUp(self):
        super().setUp()
        User.objects.create_user("ops", password="pass12345", is_staff=True)
        self.client.login(username="ops", password="pass12345")

    def order(self, status, qty=40):
        self.listing.qty_kg -= qty; self.listing.save()
        return Order.objects.create(listing=self.listing, buyer=self.buyer, qty_kg=qty, phone="254712345678",
                                    produce_value=50 * qty, delivery_fee=6 * qty, status=status)

    def act(self, o, action):
        return self.client.post(reverse("ops_action", args=[o.id]), {"action": action})

    def test_ops_page_renders_with_data(self):
        self.order("SETTLED"); self.order("DISPUTED", 10)
        self.assertEqual(self.client.get(reverse("ops_dashboard")).status_code, 200)

    def test_mark_delivered(self):
        o = self.order("PAYMENT_HELD"); self.act(o, "deliver"); o.refresh_from_db()
        self.assertEqual(o.status, "DELIVERED")

    def test_release_dispute_pays_farmer_with_fee(self):
        o = self.order("DISPUTED"); self.act(o, "release"); o.refresh_from_db()
        self.assertEqual((o.status, o.fee, o.farmer_payout), ("SETTLED", 160, 1840))

    def test_refund_returns_stock(self):
        o = self.order("DISPUTED"); self.assertEqual(Listing.objects.get(pk=self.listing.pk).qty_kg, 60)
        self.act(o, "refund"); o.refresh_from_db()
        self.assertEqual(o.status, "REFUNDED"); self.assertEqual(Listing.objects.get(pk=self.listing.pk).qty_kg, 100)

    def test_cancel_unpaid_returns_stock(self):
        o = self.order("AWAITING_PAYMENT"); self.act(o, "cancel"); o.refresh_from_db()
        self.assertEqual(o.status, "CANCELLED"); self.assertEqual(Listing.objects.get(pk=self.listing.pk).qty_kg, 100)

    def test_invalid_transitions_do_nothing(self):
        o = self.order("SETTLED")
        for action in ("deliver", "release", "refund", "cancel"):
            self.act(o, action)
        o.refresh_from_db(); self.assertEqual(o.status, "SETTLED")
        self.assertEqual(Listing.objects.get(pk=self.listing.pk).qty_kg, 60)

    def test_non_staff_cannot_act(self):
        o = self.order("PAYMENT_HELD")
        self.client.logout(); self.client.login(username="buyer1", password="pass12345")
        self.assertEqual(self.act(o, "deliver").status_code, 403)


class CartTests(Base):
    def add(self, qty, listing=None):
        return self.post("/api/cart/add/", {"listingId": (listing or self.listing).id, "qty": qty})

    def test_anonymous_can_build_a_cart(self):
        r = self.add(20)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual((data["count"], data["subtotal"], data["delivery"], data["total"]), (1, 1000, 120, 1120))

    def test_adding_twice_accumulates_and_caps_at_stock(self):
        self.add(60); r = self.add(60)
        self.assertEqual(r.json()["items"][0]["qty"], 100)           # only 100 kg exist
        self.assertTrue(r.json()["notes"])

    def test_set_and_remove(self):
        self.add(20)
        r = self.post("/api/cart/set/", {"listingId": self.listing.id, "qty": 35})
        self.assertEqual(r.json()["items"][0]["qty"], 35)
        r = self.post("/api/cart/set/", {"listingId": self.listing.id, "qty": 0})
        self.assertEqual(r.json()["count"], 0)

    def test_farmer_cannot_shop(self):
        self.client.login(username="farmer1", password="pass12345")
        self.assertEqual(self.add(10).status_code, 403)

    def test_bad_input(self):
        self.assertEqual(self.add(0).status_code, 400)
        self.assertEqual(self.post("/api/cart/add/", {"listingId": 99999, "qty": 5}).status_code, 404)

    def test_stale_item_is_dropped_from_cart(self):
        self.add(20)
        Listing.objects.filter(pk=self.listing.pk).update(is_active=False)
        data = self.client.get("/api/cart/").json()
        self.assertEqual(data["count"], 0)
        self.assertTrue(data["notes"])

    def test_cart_survives_login(self):
        self.add(15)
        self.client.login(username="buyer1", password="pass12345")
        self.assertEqual(self.client.get("/api/cart/").json()["items"][0]["qty"], 15)


class CheckoutTests(Base):
    def setUp(self):
        super().setUp()
        self.farmer2 = make_user("farmer2", "farmer")
        self.maize = Listing.objects.create(farmer=self.farmer2, produce=Produce.objects.get(slug="maize"),
                                            location="Njoro", grade="B", qty_kg=50, price_per_kg=60)

    def fill(self):
        self.post("/api/cart/add/", {"listingId": self.listing.id, "qty": 40})
        self.post("/api/cart/add/", {"listingId": self.maize.id, "qty": 10})

    def details(self, **kw):
        return {"phone": "0712345678", "address": "Kilimani, Argwings Kodhek Rd", "note": "", **kw}

    def test_checkout_page_requires_login_and_cart(self):
        self.assertEqual(self.client.get(reverse("checkout")).status_code, 302)
        self.client.login(username="buyer1", password="pass12345")
        self.assertRedirects(self.client.get(reverse("checkout")), reverse("home"), fetch_redirect_response=False)
        self.fill()
        self.assertEqual(self.client.get(reverse("checkout")).status_code, 200)

    def test_checkout_splits_into_orders_and_reduces_stock(self):
        self.client.login(username="buyer1", password="pass12345")
        self.fill()
        r = self.post("/api/checkout/", self.details())
        self.assertEqual(r.status_code, 201)
        c = Checkout.objects.get(pk=r.json()["id"])
        self.assertEqual(c.orders.count(), 2)
        self.assertEqual(c.total, 2000 + 240 + 600 + 60)            # produce + KES 6/kg delivery
        self.assertEqual(Listing.objects.get(pk=self.listing.pk).qty_kg, 60)
        self.assertEqual(Listing.objects.get(pk=self.maize.pk).qty_kg, 40)
        self.assertEqual(self.client.get("/api/cart/").json()["count"], 0)    # cart emptied
        self.assertEqual({o.status for o in c.orders.all()}, {"AWAITING_PAYMENT"})

    def test_one_payment_holds_every_order(self):
        self.client.login(username="buyer1", password="pass12345")
        self.fill()
        cid = self.post("/api/checkout/", self.details()).json()["id"]
        r = self.post(f"/api/checkout/{cid}/pay/")
        self.assertEqual(r.status_code, 200)
        orders = list(Order.objects.filter(checkout_id=cid))
        self.assertEqual({o.status for o in orders}, {"PAYMENT_HELD"})
        self.assertEqual(len({o.mpesa_receipt for o in orders}), 1)           # one shared receipt
        self.assertEqual(self.post(f"/api/checkout/{cid}/pay/").status_code, 409)   # no double payment

    def test_stock_taken_meanwhile_blocks_checkout_without_partial_orders(self):
        self.client.login(username="buyer1", password="pass12345")
        self.fill()
        Listing.objects.filter(pk=self.maize.pk).update(qty_kg=5)             # someone else bought it
        r = self.post("/api/checkout/", self.details())
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(Listing.objects.get(pk=self.listing.pk).qty_kg, 100)

    def test_validation(self):
        self.client.login(username="buyer1", password="pass12345")
        self.fill()
        self.assertEqual(self.post("/api/checkout/", self.details(phone="12")).status_code, 400)
        self.assertEqual(self.post("/api/checkout/", self.details(address="x")).status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_empty_cart(self):
        self.client.login(username="buyer1", password="pass12345")
        self.assertEqual(self.post("/api/checkout/", self.details()).status_code, 409)

    def test_other_buyers_cannot_pay_or_view(self):
        self.client.login(username="buyer1", password="pass12345")
        self.fill()
        cid = self.post("/api/checkout/", self.details()).json()["id"]
        make_user("buyer2", "buyer")
        self.client.logout(); self.client.login(username="buyer2", password="pass12345")
        self.assertEqual(self.post(f"/api/checkout/{cid}/pay/").status_code, 404)
        self.assertEqual(self.client.get(reverse("checkout_done", args=[cid])).status_code, 404)

    def test_done_page_paid_and_unpaid(self):
        self.client.login(username="buyer1", password="pass12345")
        self.fill()
        cid = self.post("/api/checkout/", self.details()).json()["id"]
        self.assertContains(self.client.get(reverse("checkout_done", args=[cid])), "One step left")
        self.post(f"/api/checkout/{cid}/pay/")
        self.assertContains(self.client.get(reverse("checkout_done", args=[cid])), "Order placed")

    def test_register_with_next_returns_to_checkout(self):
        r = self.client.post(reverse("register"), {
            "role": "buyer", "first_name": "Neo", "last_name": "B", "username": "neo", "phone": "0712345678",
            "password1": "a-Strong-pass-77", "password2": "a-Strong-pass-77", "next": reverse("checkout")})
        self.assertRedirects(r, reverse("checkout"), fetch_redirect_response=False)
        r = self.client.post(reverse("register"), {"next": "https://evil.example/"})     # open redirect refused
        self.assertEqual(r.status_code, 302)


class PublicPagesTests(Base):
    PAGES = ("home", "market", "sell", "how_it_works", "about", "faq", "contact", "terms", "privacy")

    def test_every_page_loads_for_a_guest(self):
        for name in self.PAGES:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)

    def test_every_page_loads_for_each_kind_of_user(self):
        for user in (self.farmer, self.buyer):
            self.client.force_login(user)
            for name in self.PAGES:
                self.assertEqual(self.client.get(reverse(name)).status_code, 200, f"{name} as {user.username}")

    def test_nav_links_to_every_page_and_marks_the_current_one(self):
        r = self.client.get(reverse("about"))
        for name in ("market", "how_it_works", "sell", "about", "contact"):
            self.assertContains(r, reverse(name))
        self.assertContains(r, 'class="nav-link active" href="/about/"')

    def test_sell_page_shows_form_to_farmers_only(self):
        self.assertNotContains(self.client.get(reverse("sell")), 'id="sell-form"')
        self.client.force_login(self.buyer)
        self.assertNotContains(self.client.get(reverse("sell")), 'id="sell-form"')
        self.client.force_login(self.farmer)
        self.assertContains(self.client.get(reverse("sell")), 'id="sell-form"')

    def test_how_it_works_example_uses_real_fee_and_delivery(self):
        r = self.client.get(reverse("how_it_works"))
        ex = r.context["example"]
        self.assertEqual(ex["value"], 5000)
        self.assertEqual(ex["delivery"], 100 * 6)
        self.assertEqual(ex["fee"], 400)                       # 8% of 5,000
        self.assertEqual(ex["payout"], 4600)
        self.assertEqual(ex["total"], 5600)

    def test_faq_quotes_the_configured_fee(self):
        with override_settings(SOKO_FEE_PERCENT=10):
            self.assertContains(self.client.get(reverse("faq")), "A 10% fee on your price")

    def test_contact_details_only_show_when_configured(self):
        self.assertNotContains(self.client.get(reverse("contact")), "mailto:")
        with override_settings(SOKO_CONTACT_EMAIL="hello@example.com", SOKO_WHATSAPP="+254 712 345 678"):
            r = self.client.get(reverse("contact"))
            self.assertContains(r, "mailto:hello@example.com")
            self.assertContains(r, "https://wa.me/254712345678")

    def test_old_single_page_anchors_are_gone(self):
        for name in self.PAGES:
            html = self.client.get(reverse(name)).content.decode()
            for old in ("/#buy", "/#sell", "/#how", "#buy\"", "#sell\""):
                self.assertNotIn(old, html, f"{name} still links to {old}")


class ContactFormTests(Base):
    GOOD = {"name": "Amina Otieno", "contact": "0712345678", "topic": "buyer",
            "message": "Do you deliver to Kilimani on Saturdays?", "website": ""}

    def test_message_is_saved_and_user_thanked(self):
        r = self.client.post(reverse("contact"), self.GOOD, follow=True)
        self.assertRedirects(r, reverse("contact"))
        self.assertContains(r, "We got your message")
        m = ContactMessage.objects.get()
        self.assertEqual((m.name, m.topic, m.handled), ("Amina Otieno", "buyer", False))

    def test_short_message_is_rejected_with_a_helpful_error(self):
        r = self.client.post(reverse("contact"), {**self.GOOD, "message": "hi"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "at least 10 characters")
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_required_fields(self):
        r = self.client.post(reverse("contact"), {"topic": "general"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_honeypot_bot_gets_a_thank_you_but_nothing_is_saved(self):
        r = self.client.post(reverse("contact"), {**self.GOOD, "website": "http://spam.example"}, follow=True)
        self.assertContains(r, "We got your message")
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_admin_can_list_messages(self):
        ContactMessage.objects.create(name="A", contact="b", message="A question about prices")
        admin = User.objects.create_superuser("root", "r@example.com", "pass12345")
        self.client.force_login(admin)
        self.assertContains(self.client.get("/admin/market/contactmessage/"), "A question about prices".split()[0])


class NotFoundTests(Base):
    @override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
    def test_friendly_404_page(self):
        r = self.client.get("/definitely-not-a-page/")
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, "We could not find that page", status_code=404)
        self.assertContains(r, reverse("market"), status_code=404)


LIVE = dict(MPESA_SIMULATE=False, MPESA_ENV="sandbox", MPESA_CONSUMER_KEY="key", MPESA_CONSUMER_SECRET="secret",
            MPESA_SHORTCODE="174379", MPESA_PARTY_B="174379", MPESA_PASSKEY="passkey",
            MPESA_TRANSACTION_TYPE="CustomerPayBillOnline", MPESA_CALLBACK_BASE_URL="https://soko.example",
            MPESA_CALLBACK_TOKEN="tok-123")
PUSH_OK = (200, {"ResponseCode": "0", "MerchantRequestID": "mr-1", "CheckoutRequestID": "ws_CO_1"})
STILL_OPEN = (500, {"errorCode": "500.001.1001", "errorMessage": "The transaction is being processed"})


def callback_body(code=0, amount=2900, receipt="NLJ7RT61SV", request_id="ws_CO_1"):
    cb = {"MerchantRequestID": "mr-1", "CheckoutRequestID": request_id, "ResultCode": code,
          "ResultDesc": "The service request is processed successfully." if code == 0 else "Request cancelled by user"}
    if code == 0:
        cb["CallbackMetadata"] = {"Item": [{"Name": "Amount", "Value": amount}, {"Name": "MpesaReceiptNumber", "Value": receipt},
                                           {"Name": "TransactionDate", "Value": 20261125101500},
                                           {"Name": "PhoneNumber", "Value": 254712345678}]}
    return {"Body": {"stkCallback": cb}}


@override_settings(**LIVE)
class MpesaLiveTests(Base):
    """Real M-Pesa mode with Safaricom mocked: prompt -> wait -> callback decides."""

    def setUp(self):
        super().setUp()
        self.client.login(username="buyer1", password="pass12345")
        self.post("/api/cart/add/", {"listingId": self.listing.id, "qty": 40})      # 2000 + 240 delivery = 2240
        self.cid = self.post("/api/checkout/", {"phone": "0712345678", "address": "Kilimani, Nairobi", "note": ""}).json()["id"]
        self.total = Checkout.objects.get(pk=self.cid).total
        self.push = mock.patch.object(payments, "_post", return_value=PUSH_OK)
        self.sent = self.push.start()
        self.addCleanup(self.push.stop)

    def pay(self, **data):
        return self.post(f"/api/checkout/{self.cid}/pay/", data)

    def status(self):
        return self.client.get(f"/api/checkout/{self.cid}/status/").json()

    def callback(self, body, token="tok-123"):
        return self.client.post(f"/api/mpesa/callback/{token}/", json.dumps(body), content_type="application/json")

    def statuses(self):
        return {o.status for o in Order.objects.filter(checkout_id=self.cid)}

    def test_pay_sends_prompt_and_waits_for_the_pin(self):
        r = self.pay()
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.json()["status"], "pending")
        self.assertEqual(r.json()["paidTo"], "Paybill 174379")
        path, payload = self.sent.call_args.args
        self.assertEqual(path, "/mpesa/stkpush/v1/processrequest")
        self.assertEqual((payload["PartyA"], payload["PhoneNumber"], payload["Amount"]), ("254712345678", "254712345678", self.total))
        self.assertEqual((payload["BusinessShortCode"], payload["PartyB"]), ("174379", "174379"))
        self.assertEqual(payload["CallBackURL"], "https://soko.example/api/mpesa/callback/tok-123/")
        self.assertEqual(self.statuses(), {"AWAITING_PAYMENT"})                     # nothing is held until the PIN is entered
        self.assertFalse(Checkout.objects.get(pk=self.cid).is_paid)
        p = Payment.objects.get()
        self.assertEqual((p.status, p.checkout_request_id, p.paid_to, p.simulated), ("PENDING", "ws_CO_1", "Paybill 174379", False))

    def test_second_click_reuses_the_open_prompt(self):
        self.pay()
        self.assertEqual(self.pay().status_code, 202)
        self.assertEqual(self.sent.call_count, 1)                                   # one prompt, never two charges
        self.assertEqual(Payment.objects.count(), 1)

    def test_callback_success_holds_every_order_once(self):
        self.pay()
        self.assertEqual(self.callback(callback_body(amount=self.total)).json()["ResultCode"], 0)
        self.assertEqual(self.statuses(), {"PAYMENT_HELD"})
        c = Checkout.objects.get(pk=self.cid)
        self.assertEqual((c.is_paid, c.mpesa_receipt), (True, "NLJ7RT61SV"))
        paid_at = c.paid_at
        self.callback(callback_body(amount=self.total))                             # Safaricom repeats itself
        self.assertEqual(Checkout.objects.get(pk=self.cid).paid_at, paid_at)
        self.assertEqual(Payment.objects.get().status, "SUCCESS")
        self.assertEqual(self.status()["status"], "success")
        self.assertContains(self.client.get(reverse("checkout_done", args=[self.cid])), "NLJ7RT61SV")
        self.assertEqual(self.pay().status_code, 409)                               # already paid

    def test_cancelled_prompt_can_be_retried(self):
        self.pay()
        self.callback(callback_body(code=1032))
        s = self.status()
        self.assertEqual((s["status"], s["message"]), ("cancelled", "You cancelled the payment prompt."))
        self.assertEqual(self.statuses(), {"AWAITING_PAYMENT"})
        self.sent.return_value = (200, {"ResponseCode": "0", "MerchantRequestID": "mr-2", "CheckoutRequestID": "ws_CO_2"})
        self.assertEqual(self.pay().status_code, 202)
        self.assertEqual(Payment.objects.count(), 2)
        self.callback(callback_body(amount=self.total, request_id="ws_CO_2", receipt="RETRY123"))
        self.assertEqual(self.statuses(), {"PAYMENT_HELD"})

    def test_callback_needs_the_secret_in_the_url(self):
        self.pay()
        r = self.callback(callback_body(amount=self.total), token="guess")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Payment.objects.get().status, "PENDING")
        self.assertEqual(self.statuses(), {"AWAITING_PAYMENT"})

    def test_callback_for_unknown_payment_or_garbage_is_harmless(self):
        self.assertEqual(self.callback(callback_body(request_id="nope")).status_code, 200)
        self.assertEqual(self.callback({"hello": "world"}).status_code, 200)
        self.assertEqual(self.client.post("/api/mpesa/callback/tok-123/", "not json", content_type="application/json").status_code, 200)
        self.assertEqual(self.statuses(), {"AWAITING_PAYMENT"})

    def test_wrong_amount_is_flagged_not_released(self):
        self.pay()
        self.callback(callback_body(amount=1))
        p = Payment.objects.get()
        self.assertEqual(p.status, "NEEDS_REVIEW")
        self.assertEqual(self.statuses(), {"AWAITING_PAYMENT"})
        self.assertEqual(self.pay().status_code, 409)                               # and the buyer is stopped from paying again
        self.assertContains(self.client.get(reverse("checkout_done", args=[self.cid])), "don't pay again")

    def test_money_arriving_after_ops_cancelled_the_orders_is_flagged(self):
        self.pay()
        Order.objects.filter(checkout_id=self.cid).update(status="CANCELLED")
        self.callback(callback_body(amount=self.total))
        self.assertEqual(Payment.objects.get().status, "NEEDS_REVIEW")

    def test_buyer_can_pay_with_another_number(self):
        self.assertEqual(self.pay(phone="0733 000 111").status_code, 202)
        self.assertEqual(self.sent.call_args.args[1]["PartyA"], "254733000111")
        self.assertEqual(Checkout.objects.get(pk=self.cid).phone, "254733000111")
        self.assertEqual(self.pay(phone="12").status_code, 400)

    def test_safaricom_refusing_the_prompt_is_reported_and_retryable(self):
        self.sent.return_value = (400, {"errorMessage": "Bad Request - Invalid PhoneNumber"})
        r = self.pay()
        self.assertEqual(r.status_code, 502)
        self.assertEqual(Payment.objects.get().status, "FAILED")
        self.sent.return_value = PUSH_OK
        self.assertEqual(self.pay().status_code, 202)

    def test_lost_callback_is_recovered_by_asking_safaricom(self):
        self.pay()
        Payment.objects.update(created=timezone.now() - timedelta(seconds=30))
        self.sent.return_value = (200, {"ResultCode": "1032", "ResultDesc": "Request cancelled by user"})
        self.assertEqual(self.status()["status"], "cancelled")
        self.assertEqual(self.sent.call_args.args[0], "/mpesa/stkpushquery/v1/query")

    def test_still_open_prompt_keeps_waiting_then_times_out_but_late_money_still_counts(self):
        self.pay()
        Payment.objects.update(created=timezone.now() - timedelta(seconds=30))
        self.sent.return_value = STILL_OPEN
        self.assertEqual(self.status()["status"], "pending")
        Payment.objects.update(created=timezone.now() - timedelta(seconds=500), last_query_at=None)
        self.assertEqual(self.status()["status"], "timeout")
        self.callback(callback_body(amount=self.total))                             # the PIN was entered after we gave up
        self.assertEqual(self.statuses(), {"PAYMENT_HELD"})

    def test_query_success_then_callback_fills_in_the_receipt(self):
        self.pay()
        Payment.objects.update(created=timezone.now() - timedelta(seconds=30))
        self.sent.return_value = (200, {"ResultCode": "0", "ResultDesc": "ok"})
        self.assertEqual(self.status()["status"], "success")
        self.assertEqual(Checkout.objects.get(pk=self.cid).mpesa_receipt, "")
        self.callback(callback_body(amount=self.total))
        self.assertEqual(Checkout.objects.get(pk=self.cid).mpesa_receipt, "NLJ7RT61SV")
        self.assertEqual({o.mpesa_receipt for o in Order.objects.filter(checkout_id=self.cid)}, {"NLJ7RT61SV"})

    def test_only_the_owner_can_poll(self):
        make_user("buyer2", "buyer")
        self.client.logout(); self.client.login(username="buyer2", password="pass12345")
        self.assertEqual(self.client.get(f"/api/checkout/{self.cid}/status/").status_code, 404)

    def test_old_one_shot_payment_cannot_fake_a_payment_in_live_mode(self):
        self.client.logout(); self.client.login(username="buyer1", password="pass12345")
        oid = self.post("/api/orders/", {"listingId": self.listing.id, "qty": 5, "phone": "0712345678"}).json()["id"]
        self.assertEqual(self.post("/api/payments/collect/", {"orderId": oid}).status_code, 402)
        self.assertEqual(Order.objects.get(pk=oid).status, "AWAITING_PAYMENT")

    def test_pages_show_where_the_money_goes(self):
        Payment.objects.create(checkout_id=self.cid, phone="254712345678", amount=self.total, paid_to="Paybill 174379")
        self.assertContains(self.client.get(reverse("checkout_done", args=[self.cid])), "Paybill 174379")
        staff = User.objects.create_user("ops", password="pass12345", is_staff=True)
        self.client.force_login(staff)
        r = self.client.get(reverse("ops_dashboard"))
        self.assertContains(r, "Paybill 174379")
        self.assertContains(r, "Waiting for the buyer")


class MpesaSimulatedTests(Base):
    def test_simulated_mode_still_pays_at_once_and_records_it(self):
        self.client.login(username="buyer1", password="pass12345")
        self.post("/api/cart/add/", {"listingId": self.listing.id, "qty": 10})
        cid = self.post("/api/checkout/", {"phone": "0712345678", "address": "Kilimani, Nairobi"}).json()["id"]
        r = self.post(f"/api/checkout/{cid}/pay/")
        self.assertEqual((r.status_code, r.json()["status"], r.json()["simulated"]), (200, "success", True))
        p = Payment.objects.get()
        self.assertEqual((p.status, p.simulated), ("SUCCESS", True))
        self.assertTrue(p.receipt.startswith("SIM"))

    def test_callback_url_is_closed_when_no_secret_is_configured(self):
        self.assertEqual(self.client.post("/api/mpesa/callback/anything/", "{}", content_type="application/json").status_code, 404)
