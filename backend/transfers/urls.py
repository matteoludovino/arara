from rest_framework.routers import SimpleRouter

from .views import TransferViewSet

router = SimpleRouter(trailing_slash=False)
router.register("transfers", TransferViewSet, basename="transfer")
urlpatterns = router.urls
