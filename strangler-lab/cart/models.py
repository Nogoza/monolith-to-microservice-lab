from django.db import models

from catalog.models import Product


class CartReservation(models.Model):
    """
    Tracks stock held against an in-progress cart so a product can't be
    oversold while it's sitting in someone's session. Reconciled against
    the session cart on every cart view and released by the abandoned
    cart cleanup job if the session goes quiet.
    """

    session_key = models.CharField(max_length=40, db_index=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reservations")
    quantity = models.PositiveIntegerField()
    reserved_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("session_key", "product")

    def __str__(self):
        return f"{self.quantity}x {self.product_id} held for {self.session_key}"
