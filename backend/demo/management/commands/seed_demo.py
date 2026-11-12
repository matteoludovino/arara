from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from accounts.models import User
from demo.seed import PASSWORD, Seed, restart_sequences, summary


class Command(BaseCommand):
    help = "Fills an empty database with a demo shop and some weeks of history. --reset wipes it first."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--days", type=int, default=45)
        parser.add_argument("--reset", action="store_true", help="Erase everything first (DEMO_MODE or DEBUG only).")

    def handle(self, *args: Any, days: int, reset: bool, **options: Any) -> None:
        if reset:
            if not (settings.DEMO_MODE or settings.DEBUG):
                raise CommandError("--reset erases the database: only with DEMO_MODE=true (or DEBUG).")
            call_command("flush", interactive=False, verbosity=0)
            restart_sequences()
        elif User.objects.exists():
            raise CommandError("The database already has data. Use --reset to start over.")
        with transaction.atomic():
            Seed(days).run()
        self.stdout.write(f"Demo shop ready: {summary()}. Every account's password: {PASSWORD}")
