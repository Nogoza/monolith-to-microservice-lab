import uuid

from .models import Payment


def charge(order, method, amount):
    """
    Runs the (simulated) card/PayPal charge for an order and records the
    result. Called from inside the checkout transaction so a declined
    charge rolls the whole order back with it.
    """
    transaction_ref = f"txn_{uuid.uuid4().hex[:20]}"

    payment = Payment.objects.create(
        order=order,
        amount=amount,
        method=method,
        status="approved",
        transaction_ref=transaction_ref,
    )
    return payment
