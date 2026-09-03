from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalog.models import Product

from . import services


def view_cart(request):
    items = services.get_cart_items(request)
    total = services.cart_total(items)
    return render(request, "cart/cart.html", {"items": items, "total": total})


@require_POST
def add(request, product_id):
    get_object_or_404(Product, pk=product_id)
    quantity = int(request.POST.get("quantity", 1))
    try:
        services.add_to_cart(request, product_id, quantity)
        messages.success(request, "Added to your cart.")
    except services.InsufficientStock as exc:
        messages.error(request, f"Only {exc.available} left in stock.")
    return redirect(request.POST.get("next") or "cart:view_cart")


@require_POST
def remove(request, product_id):
    services.remove_from_cart(request, product_id)
    messages.info(request, "Removed from your cart.")
    return redirect("cart:view_cart")


@require_POST
def update(request, product_id):
    quantity = int(request.POST.get("quantity", 1))
    try:
        services.set_quantity(request, product_id, quantity)
    except services.InsufficientStock as exc:
        messages.error(request, f"Only {exc.available} left in stock.")
    return redirect("cart:view_cart")
