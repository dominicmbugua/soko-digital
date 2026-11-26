from django.contrib import admin, messages

from .models import Checkout, ContactMessage, Listing, Order, Payment, Produce, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "phone", "location")
    list_filter = ("role",)
    search_fields = ("user__username", "user__first_name", "user__last_name", "phone")


@admin.register(Produce)
class ProduceAdmin(admin.ModelAdmin):
    list_display = ("name", "ref_min", "ref_max")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("id", "produce", "farmer", "location", "grade", "qty_kg", "price_per_kg", "is_active", "created")
    list_filter = ("produce", "grade", "is_active")
    search_fields = ("farmer__username", "location")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("ref", "listing", "buyer", "qty_kg", "total", "status", "mpesa_receipt", "farmer_payout", "paid_out_at", "created")
    list_filter = ("status",)
    search_fields = ("buyer__username", "mpesa_receipt")
    actions = ["mark_delivered"]

    @admin.action(description="Mark selected orders as delivered (payment must be held)")
    def mark_delivered(self, request, queryset):
        n = queryset.filter(status=Order.Status.PAYMENT_HELD).update(status=Order.Status.DELIVERED)
        self.message_user(request, f"{n} order(s) marked delivered.", messages.SUCCESS)


@admin.register(Checkout)
class CheckoutAdmin(admin.ModelAdmin):
    list_display = ("ref", "buyer", "phone", "address", "paid_at", "mpesa_receipt", "created")
    search_fields = ("buyer__username", "address", "mpesa_receipt")


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("name", "contact", "topic", "handled", "created")
    list_filter = ("handled", "topic")
    search_fields = ("name", "contact", "message")
    list_editable = ("handled",)
    readonly_fields = ("name", "contact", "topic", "message", "created")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Every M-Pesa attempt: who was asked, how much, which Paybill/Till receives it, and how it ended.
    Filter by 'Money received, needs review' to find payments ops must look at by hand."""

    list_display = ("created", "checkout", "phone", "amount", "status", "receipt", "paid_to", "simulated")
    list_filter = ("status", "simulated", "paid_to")
    search_fields = ("receipt", "phone", "checkout_request_id", "checkout__buyer__username")
    date_hierarchy = "created"
    readonly_fields = [f.name for f in Payment._meta.fields]       # a payment record is evidence: view only

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

