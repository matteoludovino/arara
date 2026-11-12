from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("customers", views.CustomerViewSet, basename="customer")
router.register("registers", views.RegisterViewSet, basename="register")
router.register("sessions", views.SessionViewSet, basename="session")
router.register("sales", views.SaleViewSet, basename="sale")
router.register("returns", views.ReturnViewSet, basename="sale-return")

urlpatterns = [
    path("store-credits/<str:code>", views.StoreCreditView.as_view(), name="store-credit"),
    path("exchanges", views.ExchangeView.as_view(), name="exchange"),
    path("salespeople", views.SalespeopleView.as_view(), name="salespeople"),
    *router.urls,
]
