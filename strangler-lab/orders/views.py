from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from cart.services import cart_total, get_cart_items

from . import services
from .models import Order


@login_required
def checkout(request):
    items = get_cart_items(request)
    total = cart_total(items)

    if request.method == "POST":
        shipping_address = request.POST.get("shipping_address", "").strip()
        payment_method = request.POST.get("payment_method", "card")

        if not shipping_address:
            messages.error(request, "A shipping address is required.")
            return render(request, "orders/checkout.html", {"items": items, "total": total})

        try:
            order = services.checkout(
                request,
                user=request.user,
                cart_items=items,
                shipping_address=shipping_address,
                payment_method=payment_method,
            )
        except services.EmptyCart:
            messages.error(request, "Your cart is empty.")
            return redirect("cart:view_cart")
        except services.OutOfStock as exc:
            messages.error(request, f"Only {exc.available} left of {exc.product.name}.")
            return redirect("cart:view_cart")

        messages.success(request, "Order placed. Thanks for shopping with us!")
        return redirect("orders:detail", order_id=order.id)

    return render(request, "orders/checkout.html", {"items": items, "total": total})


@login_required
def detail(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related("payment").prefetch_related("items__product"),
        pk=order_id,
        user=request.user,
    )
    return render(request, "orders/detail.html", {"order": order})


@login_required
def history(request):
    orders = Order.objects.filter(user=request.user).order_by("-created_at")
    return render(request, "orders/history.html", {"orders": orders})
