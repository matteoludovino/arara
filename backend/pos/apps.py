from django.apps import AppConfig


class PosConfig(AppConfig):
    name = "pos"
    verbose_name = "Point of sale"

    def ready(self) -> None:
        from common.integrity import register

        from .invariants import pos_problems

        register(pos_problems)
