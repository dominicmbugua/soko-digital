from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Profile(models.Model):
    """Extra info for every account: is this person a farmer or a buyer?"""

    FARMER = "farmer"
    BUYER = "buyer"
    ROLE_CHOICES = [(FARMER, "Farmer"), (BUYER, "Buyer")]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    phone = models.CharField(max_length=12, help_text="Format 2547XXXXXXXX")
    location = models.CharField(max_length=80, blank=True)

    def __str__(self):
        return f"{self.user.get_username()} ({self.role})"


class Produce(models.Model):
    """A type of produce plus its usual price range (the reference prices)."""

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=60)
    ref_min = models.PositiveIntegerField(help_text="Usual lowest price, KES per kg")
    ref_max = models.PositiveIntegerField(help_text="Usual highest price, KES per kg")

    class Meta:
        ordering = ["id"]
        verbose_name_plural = "produce"

    def __str__(self):
        return self.name


class Listing(models.Model):
    GRADES = [("A", "A"), ("B", "B"), ("C", "C")]

    farmer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="listings")
    produce = models.ForeignKey(Produce, on_delete=models.PROTECT, related_name="listings")
    location = models.CharField(max_length=80)
    grade = models.CharField(max_length=1, choices=GRADES)
    qty_kg = models.PositiveIntegerField(help_text="Kilograms still available")
    price_per_kg = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created", "-id"]

    def __str__(self):
        return f"{self.produce.name} - {self.qty_kg} kg @ KES {self.price_per_kg}"

    @property
    def farmer_name(self):
        return self.farmer.get_full_name() or self.farmer.get_username()


class Checkout(models.Model):
    """One checkout = one cart paid with one M-Pesa payment. It creates one Order per listing."""

    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="checkouts")
    phone = models.CharField(max_length=12)
    address = models.CharField(max_length=200, help_text="Where to deliver")
    note = models.CharField(max_length=300, blank=True)
    mpesa_receipt = models.CharField(max_length=30, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created", "-id"]

    def __str__(self):
        return self.ref

    @property
    def ref(self):
        return f"CHK-{self.pk:04d}"

    @property
    def is_paid(self):
        return self.paid_at is not None

    @property
    def produce_value(self):
        return sum(o.produce_value for o in self.orders.all())

    @property
    def delivery_fee(self):
        return sum(o.delivery_fee for o in self.orders.all())

    @property
    def total(self):
        return self.produce_value + self.delivery_fee


class Order(models.Model):
    class Status(models.TextChoices):
        AWAITING_PAYMENT = "AWAITING_PAYMENT", "Awaiting payment"
        PAYMENT_HELD = "PAYMENT_HELD", "Payment held"
        DELIVERED = "DELIVERED", "Delivered"
        SETTLED = "SETTLED", "Settled (farmer paid)"
        DISPUTED = "DISPUTED", "Disputed"
        REFUNDED = "REFUNDED", "Refunded"
        CANCELLED = "CANCELLED", "Cancelled"

    checkout = models.ForeignKey(Checkout, null=True, blank=True, on_delete=models.PROTECT, related_name="orders")
    listing = models.ForeignKey(Listing, on_delete=models.PROTECT, related_name="orders")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    qty_kg = models.PositiveIntegerField()
    phone = models.CharField(max_length=12)
    produce_value = models.PositiveIntegerField(help_text="price x kg, KES")
    delivery_fee = models.PositiveIntegerField(help_text="KES")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AWAITING_PAYMENT)
    mpesa_receipt = models.CharField(max_length=30, blank=True)
    fee = models.PositiveIntegerField(default=0, help_text="Our fee, KES (set when settled)")
    farmer_payout = models.PositiveIntegerField(default=0, help_text="KES (set when settled)")
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created", "-id"]

    def __str__(self):
        return self.ref

    @property
    def ref(self):
        return f"ORD-{self.pk:04d}"

    @property
    def step(self):
        """Position on the 4-step tracker (Ordered, Paid, Delivered, Confirmed); -1 if it left the normal path."""
        return {"AWAITING_PAYMENT": 0, "PAYMENT_HELD": 1, "DELIVERED": 2, "SETTLED": 3, "DISPUTED": 2}.get(self.status, -1)

    @property
    def total(self):
        return self.produce_value + self.delivery_fee
