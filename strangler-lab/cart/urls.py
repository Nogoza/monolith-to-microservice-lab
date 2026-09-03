from django.urls import path

from . import views

app_name = "cart"

urlpatterns = [
    path("", views.view_cart, name="view_cart"),
    path("add/<int:product_id>/", views.add, name="add"),
    path("remove/<int:product_id>/", views.remove, name="remove"),
    path("update/<int:product_id>/", views.update, name="update"),
]
