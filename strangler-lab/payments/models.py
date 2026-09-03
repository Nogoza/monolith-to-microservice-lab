from django.db import models

from orders.models import Order


class Payment(models.Model):
    METHOD_CHOICES = [
        ("card", "Credit card"),
        ("paypal", "PayPal"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("declined", "Declined"),
        ("refunded", "Refunded"),
    ]

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="payment")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    transaction_ref = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment<{self.transaction_ref}> for order {self.order_id}"
