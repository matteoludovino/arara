from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = "common"
    verbose_name = "Common"

    def ready(self) -> None:
        # Serializers and views subscript DRF's generic classes (`ModelSerializer[User]`); they
        # are imported with the URLconf, after every app is ready.
        import django_stubs_ext
        from rest_framework import generics, serializers, viewsets

        django_stubs_ext.monkeypatch(
            extra_classes=[
                serializers.Serializer,
                serializers.ModelSerializer,
                generics.GenericAPIView,
                viewsets.GenericViewSet,
                viewsets.ModelViewSet,
            ]
        )
