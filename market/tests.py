import json

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Checkout, Listing, Order, Produce, Profile


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
