import base64
import io
from collections import defaultdict
from decimal import Decimal

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from orders.models import OrderItem

COMPLETED_STATUSES = ["paid", "shipped", "delivered"]


def build_sales_report():
    """
    Full sales-by-category-by-month breakdown, computed from the raw
    order line items rather than a precomputed rollup so the numbers
    always reflect exactly what's in the orders table right now.
    """
    items = (
        OrderItem.objects.select_related("order", "product", "product__category")
        .filter(order__status__in=COMPLETED_STATUSES)
        .order_by("order__created_at")
    )

    monthly_category_revenue = defaultdict(lambda: defaultdict(Decimal))
    category_totals = defaultdict(Decimal)
    monthly_totals = defaultdict(Decimal)
    monthly_order_ids = defaultdict(set)

    for item in items.iterator(chunk_size=2000):
        month_key = item.order.created_at.strftime("%Y-%m")
        category_name = item.product.category.name
        revenue = item.unit_price * item.quantity

        monthly_category_revenue[category_name][month_key] += revenue
        category_totals[category_name] += revenue
        monthly_totals[month_key] += revenue
        monthly_order_ids[month_key].add(item.order_id)

    top_categories = sorted(category_totals.items(), key=lambda kv: kv[1], reverse=True)[:5]
    months = sorted(monthly_totals.keys())

    monthly_rows = [
        {
            "month": month,
            "orders": len(monthly_order_ids[month]),
            "revenue": monthly_totals[month],
        }
        for month in months
    ]

    chart_png = _render_chart(months, monthly_totals, monthly_category_revenue, top_categories)

    return {
        "months": months,
        "monthly_rows": monthly_rows,
        "top_categories": top_categories,
        "chart_base64": chart_png,
    }


def _render_chart(months, monthly_totals, monthly_category_revenue, top_categories):
    fig, (ax_top, ax_bottom) = plt.subplots(2, 1, figsize=(10, 8))

    totals = [float(monthly_totals[m]) for m in months]
    ax_top.bar(months, totals, color="#2c5f8a")
    ax_top.set_title("Total revenue by month")
    ax_top.set_ylabel("Revenue")
    ax_top.tick_params(axis="x", rotation=90, labelsize=6)

    for category_name, _ in top_categories:
        series = [float(monthly_category_revenue[category_name].get(m, Decimal("0"))) for m in months]
        ax_bottom.plot(months, series, label=category_name)

    ax_bottom.set_title("Top 5 categories by month")
    ax_bottom.set_ylabel("Revenue")
    ax_bottom.tick_params(axis="x", rotation=90, labelsize=6)
    ax_bottom.legend(fontsize=7, loc="upper left")

    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    buf.seek(0)

    return base64.b64encode(buf.read()).decode("ascii")
