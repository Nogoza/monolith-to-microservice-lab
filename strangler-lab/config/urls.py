from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from config.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("", include("catalog.urls")),
    path("cart/", include("cart.urls")),
    path("orders/", include("orders.urls")),
    path("reports/", include("reports.urls")),
    path("accounts/", include("accounts.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
