from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from common import views as common

urlpatterns = [
    path("api/health", common.health, name="health"),
    path("api/ready", common.ready, name="ready"),
    path("api/", include("accounts.urls")),
    path("api/", include("locations.urls")),
    path("api/catalog/", include("catalog.urls")),
    path("api/stock/", include("stock.urls")),
    path("api/purchasing/", include("purchasing.urls")),
    path("api/", include("transfers.urls")),
    path("api/", include("counts.urls")),
    path("api/pos/", include("pos.urls")),
    path("api/reports/", include("reports.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("admin/", admin.site.urls),
]
