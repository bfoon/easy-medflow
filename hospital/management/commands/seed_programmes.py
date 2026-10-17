"""Add the fictional care programme demo (hypertension, HIV treatment, childhood immunisation) to an existing demo
database. Runs once: it does nothing when programmes already exist."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = 'Add fictional care programmes, enrolments and visit history to the demo database.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Allow running when DEBUG is False (never on real data)')

    def handle(self, *args, **o):
        if not settings.DEBUG and not o['force']:
            raise CommandError('Refusing to add demo data with DEBUG=False. Use --force only on a throwaway database.')
        from hospital.demo_programmes import run
        with transaction.atomic():
            n = run()
        self.stdout.write(self.style.SUCCESS(f'{n} demo enrolments created.') if n else 'Programmes already exist (or demo staff are missing); nothing added.')
