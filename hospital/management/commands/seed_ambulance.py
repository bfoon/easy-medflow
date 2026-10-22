"""Add FICTIONAL ambulance service demo data (hospital/demo_ambulance.py). Never use on real data."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = 'Add fictional ambulance demo data: stations, fleet, crews, live calls in every state and 30 days of history.'

    def add_arguments(self, parser):
        parser.add_argument('--password', default='medflow-demo-2026', help='Password for the demo dispatch and crew accounts')
        parser.add_argument('--days', type=int, default=30, help='Days of finished calls to create')
        parser.add_argument('--force', action='store_true', help='Allow running when DEBUG is False (never on real data)')

    def handle(self, *args, **o):
        if not settings.DEBUG and not o['force']:
            raise CommandError('Refusing to add demo data with DEBUG=False. Use --force only on a throwaway database.')
        from hospital.management.dbcheck import require_up_to_date_database
        require_up_to_date_database()
        from hospital.demo_ambulance import run
        with transaction.atomic():
            told = run(o['password'], o['days'])
        if told is None:
            self.stdout.write('Ambulance stations already exist; nothing added.')
            return
        self.stdout.write(self.style.SUCCESS('Ambulance demo data created:'))
        for line in told:
            self.stdout.write(f'  · {line}')
        self.stdout.write('Open /ambulance/ as dispatch.sanneh, and /ambulance/crew/ as medic.jobe (password medflow-demo-2026).')
