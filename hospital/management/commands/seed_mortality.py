"""Add FICTIONAL deaths, mortuary, autopsy, M&M and study-case data (hospital/demo_mortality.py). Never use on real data."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = 'Add fictional mortality demo data: deaths in every state, autopsies, M&M reviews and library study cases.'

    def add_arguments(self, parser):
        parser.add_argument('--password', default='medflow-demo-2026', help='Password for any demo staff accounts this creates')
        parser.add_argument('--force', action='store_true', help='Allow running when DEBUG is False (never on real data)')

    def handle(self, *args, **o):
        if not settings.DEBUG and not o['force']:
            raise CommandError('Refusing to add demo data with DEBUG=False. Use --force only on a throwaway database.')
        from hospital.demo_mortality import run
        with transaction.atomic():
            told = run(o['password'])
        if told is None:
            self.stdout.write('Deaths already exist; nothing added.')
            return
        self.stdout.write(self.style.SUCCESS(f'Mortality demo data created: {len(told)} stories plus a year of history.'))
        for line in told:
            self.stdout.write(f'  · {line}')
        self.stdout.write('Open /mortality/ as dr.jallow, /autopsies/ as lab.touray, and /library/cases/ for the study cases.')
