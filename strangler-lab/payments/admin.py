from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("transaction_ref", "order", "amount", "method", "status", "created_at")
    list_filter = ("method", "status")
    search_fields = ("transaction_ref",)
