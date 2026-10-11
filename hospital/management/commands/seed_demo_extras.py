"""Add the newer demo content to an existing demo database without wiping it:
brain cases and scans, imaging for the featured patient, four months of visits for the health dashboard,
and inpatient medication charts. Safe to run more than once."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Add newer fictional demo content to an existing demo database.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Allow when DEBUG is False (never on real patient data)')

    def handle(self, *args, force=False, **kw):
        if not settings.DEBUG and not force:
            raise CommandError('Refusing to add demo data with DEBUG=False.')
        from hospital.management.dbcheck import require_up_to_date_database
        require_up_to_date_database()
        from hospital.demo_extras import run_all
        res = run_all()
        if not res:
            raise CommandError('No doctor account found. Run seed_demo first.')
        self.stdout.write(self.style.SUCCESS('Added: ' + ', '.join(f'{k} {v}' for k, v in res.items())))
