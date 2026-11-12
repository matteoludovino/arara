from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("suppliers", views.SupplierViewSet, basename="supplier")
router.register("orders", views.OrderViewSet, basename="purchase-order")
router.register("receipts", views.ReceiptViewSet, basename="goods-receipt")
router.register("returns", views.PurchaseReturnViewSet, basename="purchase-return")

urlpatterns = [path("suggestions", views.SuggestionsView.as_view(), name="purchase-suggestions"), *router.urls]
