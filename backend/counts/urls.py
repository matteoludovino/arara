from rest_framework.routers import SimpleRouter

from .views import CountViewSet

router = SimpleRouter(trailing_slash=False)
router.register("counts", CountViewSet, basename="count")
urlpatterns = router.urls
