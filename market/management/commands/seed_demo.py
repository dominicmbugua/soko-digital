from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.management.base import BaseCommand

from market.models import Listing, Order, Produce, Profile
from market.utils import fee_for

PASSWORD = "soko12345"

FARMERS = [
    # username, first, last, location, phone, produce slug, price, qty, grade
    ("wanjiku", "Wanjiku", "Kamau", "Molo", "254711000001", "potatoes", 48, 800, "A"),
    ("peter", "Peter", "Kiprono", "Elburgon", "254711000002", "potatoes", 45, 1500, "B"),
    ("grace", "Grace", "Njeri", "Nakuru", "254711000003", "tomatoes", 82, 300, "A"),
    ("samuel", "Samuel", "Mwangi", "Njoro", "254711000004", "kale", 38, 250, "A"),
    ("faith", "Faith", "Chebet", "Molo", "254711000005", "onions", 98, 400, "B"),
    ("john", "John", "Ochieng", "Nakuru", "254711000006", "maize", 60, 2000, "B"),
    ("mary", "Mary", "Wambui", "Elburgon", "254711000007", "beans", 155, 180, "A"),
    ("david", "David", "Kariuki", "Njoro", "254711000008", "avocados", 125, 220, "A"),
]


class Command(BaseCommand):
    help = "Create demo farmers (with listings) and a demo buyer. Safe to run twice."

    def handle(self, *args, **options):
        for username, first, last, loc, phone, slug, price, qty, grade in FARMERS:
            user, created = User.objects.get_or_create(username=username, defaults={"first_name": first, "last_name": last})
            if created:
                user.set_password(PASSWORD)
                user.save()
            Profile.objects.get_or_create(user=user, defaults={"role": "farmer", "phone": phone, "location": loc})
            if not user.listings.exists():
                Listing.objects.create(farmer=user, produce=Produce.objects.get(slug=slug), location=loc,
                                       grade=grade, qty_kg=qty, price_per_kg=price)

        buyer, created = User.objects.get_or_create(username="buyer1", defaults={"first_name": "Demo", "last_name": "Restaurant"})
        if created:
            buyer.set_password(PASSWORD)
            buyer.save()
        Profile.objects.get_or_create(user=buyer, defaults={"role": "buyer", "phone": "254722000001", "location": "Nairobi"})

        ops, created = User.objects.get_or_create(username="ops1", defaults={"first_name": "Ops", "last_name": "Team", "is_staff": True})
        if created:
            ops.set_password(PASSWORD)
            ops.save()

        if not Order.objects.exists():
            self.make_orders(buyer)

        self.stdout.write(self.style.SUCCESS(
            f"Demo data ready. Farmers: {', '.join(f[0] for f in FARMERS)} | Buyer: buyer1 | Ops (staff): ops1 | password for all: {PASSWORD}"))

    def make_orders(self, buyer):
        """A spread of orders over the last 2 weeks so the dashboards have something to show."""
        S = Order.Status
        demo = [  # farmer, kg, status, days ago
            ("wanjiku", 100, S.SETTLED, 12), ("peter", 250, S.SETTLED, 10), ("grace", 40, S.SETTLED, 8),
            ("faith", 60, S.SETTLED, 5), ("wanjiku", 50, S.SETTLED, 3), ("john", 300, S.SETTLED, 3),
            ("samuel", 30, S.DELIVERED, 1), ("john", 200, S.PAYMENT_HELD, 0), ("mary", 20, S.DISPUTED, 2),
            ("david", 25, S.AWAITING_PAYMENT, 0), ("peter", 120, S.PAYMENT_HELD, 1),
        ]
        for username, kg, status, days_ago in demo:
            listing = Listing.objects.filter(farmer__username=username).first()
            value = listing.price_per_kg * kg
            order = Order.objects.create(
                listing=listing, buyer=buyer, qty_kg=kg, phone="254722000001", produce_value=value,
                delivery_fee=settings.SOKO_DELIVERY_PER_KG * kg, status=status,
                mpesa_receipt="" if status == S.AWAITING_PAYMENT else f"SIM{order_seed(listing.id, kg)}",
            )
            if status == S.SETTLED:
                order.fee = fee_for(value)
                order.farmer_payout = value - order.fee
                order.save(update_fields=["fee", "farmer_payout"])
            listing.qty_kg = max(0, listing.qty_kg - kg)
            listing.save(update_fields=["qty_kg"])
            when = timezone.now() - timedelta(days=days_ago, hours=2)
            Order.objects.filter(pk=order.pk).update(created=when - timedelta(hours=1), updated=when)


def order_seed(a, b):
    return f"{(a * 7919 + b * 104729) % 0xFFFFFF:06X}"
