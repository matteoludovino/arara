from django.apps import AppConfig


class StockConfig(AppConfig):
    name = "stock"
    verbose_name = "Stock"

    def ready(self) -> None:
        from common.integrity import register

        from .invariants import stock_problems

        register(stock_problems)
