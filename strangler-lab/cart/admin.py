from django.contrib import admin

from .models import CartReservation


@admin.register(CartReservation)
class CartReservationAdmin(admin.ModelAdmin):
    list_display = ("session_key", "product", "quantity", "reserved_at")
    list_filter = ("reserved_at",)
