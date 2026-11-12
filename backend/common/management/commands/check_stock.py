from typing import Any

from django.core.management.base import BaseCommand, CommandError

from common.integrity import all_problems


class Command(BaseCommand):
    help = "Checks that stock levels, SKU costs and open documents agree with the stock ledger."

    def handle(self, *args: Any, **options: Any) -> None:
        problems = all_problems()
        if problems:
            for problem in problems:
                self.stderr.write(problem)
            raise CommandError(f"{len(problems)} stock inconsistencies found")
        self.stdout.write(self.style.SUCCESS("Stock ledger, levels, costs and open documents agree."))
