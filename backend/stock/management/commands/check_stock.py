from typing import Any

from django.core.management.base import BaseCommand, CommandError

from stock.invariants import stock_problems


class Command(BaseCommand):
    help = "Checks that stock levels and SKU costs agree with the stock ledger."

    def handle(self, *args: Any, **options: Any) -> None:
        problems = stock_problems()
        if problems:
            for problem in problems:
                self.stderr.write(problem)
            raise CommandError(f"{len(problems)} stock inconsistencies found")
        self.stdout.write(self.style.SUCCESS("Stock ledger, levels and costs agree."))
