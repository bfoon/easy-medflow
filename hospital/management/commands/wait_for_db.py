"""Wait until the database accepts connections, then exit 0.

Docker restarts every container at once after a reboot or a Docker Desktop restart and ignores `depends_on`,
so the app can start before PostgreSQL. Waiting here turns that race into a short pause instead of a crash.
"""
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = 'Wait for the default database to accept connections.'

    def add_arguments(self, parser):
        parser.add_argument('--timeout', type=int, default=90, help='Seconds to keep trying (default 90)')

    def handle(self, *args, timeout, **opts):
        db = settings.DATABASES['default']
        if db['ENGINE'].endswith('sqlite3'):
            return
        host, port = db.get('HOST') or 'localhost', db.get('PORT') or '5432'
        deadline, attempt, last = time.monotonic() + timeout, 0, None
        while time.monotonic() < deadline:
            attempt += 1
            try:
                connections['default'].ensure_connection()
                connections['default'].close()
                self.stdout.write(self.style.SUCCESS(f'Database {host}:{port} is ready.'))
                return
            except OperationalError as exc:
                last = exc
                if attempt == 1 or attempt % 5 == 0:
                    self.stdout.write(f'Waiting for database {host}:{port}… ({str(exc).splitlines()[0]})')
                connections['default'].close()
                time.sleep(2)
        hint = (f"\nCould not reach the database at {host}:{port} after {timeout}s.\n"
                "  • Check the database container:   docker compose ps -a   and   docker compose logs db\n"
                "  • If you started this container from PyCharm or with `docker run`, it is not on the compose network.\n"
                "    Use `docker compose up -d` or `docker compose exec web …`, or a PyCharm *Docker Compose* interpreter (service: web).\n"
                "  • Running Django directly on your computer instead? Use POSTGRES_HOST=localhost and POSTGRES_PORT=5433,\n"
                "    or USE_SQLITE=True for a local file database.")
        raise CommandError(f'{last}{hint}' if last else hint)
