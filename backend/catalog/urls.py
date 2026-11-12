from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("categories", views.CategoryViewSet, basename="category")
router.register("brands", views.BrandViewSet, basename="brand")
router.register("collections", views.CollectionViewSet, basename="collection")
router.register("colors", views.ColorViewSet, basename="color")
router.register("size-grids", views.SizeGridViewSet, basename="size-grid")
router.register("products", views.ProductViewSet, basename="product")
router.register("prices", views.PriceViewSet, basename="price")
router.register("variants", views.VariantViewSet, basename="variant")

urlpatterns = [path("lookup", views.LookupView.as_view(), name="catalog-lookup"), *router.urls]
