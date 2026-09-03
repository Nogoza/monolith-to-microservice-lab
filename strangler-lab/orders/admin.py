from django.contrib import admin

from .models import DailySalesSnapshot, Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "total", "created_at")
    list_filter = ("status",)
    search_fields = ("id", "user__username")
    inlines = [OrderItemInline]


@admin.register(DailySalesSnapshot)
class DailySalesSnapshotAdmin(admin.ModelAdmin):
    list_display = ("date", "total_orders", "total_items", "total_revenue", "computed_at")
