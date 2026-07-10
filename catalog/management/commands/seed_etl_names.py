"""seeds the Etl table from a csv file of etl names.
"""

import csv

from django.core.management.base import BaseCommand, CommandError

from catalog.models import Etl


class Command(BaseCommand):
    help = "loads etl names from a csv file with a single 'name' column"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str)

    def handle(self, *args, **options):
        csv_path = options["csv_path"]

        try:
            handle = open(csv_path, newline="", encoding="utf-8-sig")
        except OSError as exc:
            raise CommandError(f"could not open {csv_path}: {exc}") from exc

        with handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or "name" not in reader.fieldnames:
                raise CommandError("csv file must have a 'name' column")

            created_count = 0
            for row in reader:
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                _, created = Etl.objects.get_or_create(name=name)
                created_count += int(created)

        self.stdout.write(self.style.SUCCESS(f"seeded {created_count} new etl name(s)"))
