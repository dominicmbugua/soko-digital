"""Cancel orders that were never paid and give the produce back to the listings.

Run it every few minutes (Windows Task Scheduler, or cron on a server):
    python manage.py expire_unpaid
"""
from django.core.management.base import BaseCommand

from market import services


class Command(BaseCommand):
    help = "Cancel unpaid orders older than SOKO_UNPAID_EXPIRY_MINUTES and return their stock."

    def add_arguments(self, parser):
        parser.add_argument("--minutes", type=int, help="Override the age limit for this run.")

    def handle(self, *args, **opts):
        n = services.expire_unpaid(opts.get("minutes"))
        self.stdout.write(f"Cancelled {n} unpaid order(s).")
