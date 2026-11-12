from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("levels", views.StockLevelViewSet, basename="stock-level")
router.register("movements", views.MovementViewSet, basename="stock-movement")

urlpatterns = [
    path("grid", views.GridView.as_view(), name="stock-grid"),
    path("adjustments", views.AdjustmentView.as_view(), name="stock-adjustments"),
    *router.urls,
]
