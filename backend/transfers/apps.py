from django.apps import AppConfig


class TransfersConfig(AppConfig):
    name = "transfers"
    verbose_name = "Transfers"

    def ready(self) -> None:
        from common.integrity import register

        from .invariants import transit_problems

        register(transit_problems)
