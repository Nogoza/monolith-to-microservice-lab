"""
Background maintenance jobs for the storefront, running inside the web
process itself via APScheduler. No separate worker to deploy or babysit.
"""

from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from django.conf import settings
from django.db import connection
from django.utils import timezone

_scheduler = None


def _log(message):
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(settings.SCHEDULER_LOG_FILE, "a") as fh:
        fh.write(f"{timezone.now().isoformat()} {message}\n")


def expire_abandoned_carts():
    """Release stock held by carts nobody has touched in a while."""
    from cart.models import CartReservation

    cutoff = timezone.now() - timedelta(minutes=settings.CART_RESERVATION_TIMEOUT_MINUTES)
    stale = CartReservation.objects.select_related("product").filter(reserved_at__lt=cutoff)

    released = 0
    for reservation in stale:
        product = reservation.product
        product.reserved_stock = max(0, product.reserved_stock - reservation.quantity)
        product.save(update_fields=["reserved_stock"])
        reservation.delete()
        released += 1

    _log(f"expire_abandoned_carts released={released}")
    connection.close()


def recalculate_daily_sales_snapshot():
    """Recompute today's rollup so /reports/ has a cheap fast path available."""
    from django.db.models import Sum

    from .models import DailySalesSnapshot, Order, OrderItem

    today = timezone.localdate()
    todays_orders = Order.objects.filter(created_at__date=today, status__in=["paid", "shipped", "delivered"])

    total_orders = todays_orders.count()
    total_revenue = todays_orders.aggregate(total=Sum("total"))["total"] or 0
    total_items = (
        OrderItem.objects.filter(order__in=todays_orders).aggregate(total=Sum("quantity"))["total"] or 0
    )

    DailySalesSnapshot.objects.update_or_create(
        date=today,
        defaults={
            "total_orders": total_orders,
            "total_items": total_items,
            "total_revenue": total_revenue,
        },
    )

    _log(f"recalculate_daily_sales_snapshot date={today} orders={total_orders} revenue={total_revenue}")
    connection.close()


def start():
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(expire_abandoned_carts, "interval", minutes=5, id="expire_abandoned_carts")
    _scheduler.add_job(
        recalculate_daily_sales_snapshot, "interval", minutes=15, id="recalculate_daily_sales_snapshot"
    )
    _scheduler.start()
