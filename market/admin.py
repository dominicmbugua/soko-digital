from django.contrib import admin, messages

from .models import Checkout, Listing, Order, Produce, Profile


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
    list_display = ("ref", "listing", "buyer", "qty_kg", "total", "status", "mpesa_receipt", "farmer_payout", "created")
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
