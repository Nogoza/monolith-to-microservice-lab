from django.db import transaction

from catalog.models import Product

from .models import CartReservation

CART_SESSION_KEY = "cart"


class InsufficientStock(Exception):
    def __init__(self, product, available):
        self.product = product
        self.available = available
        super().__init__(f"Only {available} left of {product.name}")


def _ensure_session_key(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


def get_cart_items(request):
    """Resolve the session cart dict into (product, quantity, subtotal) tuples."""
    cart = request.session.get(CART_SESSION_KEY, {})
    if not cart:
        return []
    products = Product.objects.filter(id__in=cart.keys()).select_related("category")
    products_by_id = {str(p.id): p for p in products}

    items = []
    for product_id, quantity in cart.items():
        product = products_by_id.get(product_id)
        if product is None:
            continue
        items.append(
            {
                "product": product,
                "quantity": quantity,
                "subtotal": product.price * quantity,
            }
        )
    return items


def cart_total(items):
    return sum((item["subtotal"] for item in items), start=0)


@transaction.atomic
def add_to_cart(request, product_id, quantity):
    session_key = _ensure_session_key(request)
    product = Product.objects.select_for_update().get(pk=product_id)

    cart = request.session.get(CART_SESSION_KEY, {})
    key = str(product.id)
    current_qty = cart.get(key, 0)

    reservation = CartReservation.objects.filter(session_key=session_key, product=product).first()
    already_reserved = reservation.quantity if reservation else 0

    new_qty = current_qty + quantity
    available_for_this_session = product.available_stock + already_reserved

    if new_qty > available_for_this_session:
        raise InsufficientStock(product, available_for_this_session)

    delta = new_qty - already_reserved
    product.reserved_stock += delta
    product.save(update_fields=["reserved_stock"])

    CartReservation.objects.update_or_create(
        session_key=session_key,
        product=product,
        defaults={"quantity": new_qty},
    )

    cart[key] = new_qty
    request.session[CART_SESSION_KEY] = cart
    request.session.modified = True


@transaction.atomic
def remove_from_cart(request, product_id):
    session_key = _ensure_session_key(request)
    cart = request.session.get(CART_SESSION_KEY, {})
    key = str(product_id)

    if key in cart:
        del cart[key]
        request.session[CART_SESSION_KEY] = cart
        request.session.modified = True

    reservation = CartReservation.objects.filter(session_key=session_key, product_id=product_id).first()
    if reservation:
        product = Product.objects.select_for_update().get(pk=product_id)
        product.reserved_stock = max(0, product.reserved_stock - reservation.quantity)
        product.save(update_fields=["reserved_stock"])
        reservation.delete()


@transaction.atomic
def set_quantity(request, product_id, quantity):
    remove_from_cart(request, product_id)
    if quantity > 0:
        add_to_cart(request, product_id, quantity)


def release_all_reservations(request):
    """Called after checkout commits: the stock is no longer 'reserved', it's sold."""
    session_key = _ensure_session_key(request)
    CartReservation.objects.filter(session_key=session_key).delete()
    request.session[CART_SESSION_KEY] = {}
    request.session.modified = True
