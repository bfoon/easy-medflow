"""Stop management commands early, with plain instructions, when the database is behind the code."""
from django.core.management.base import CommandError
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor


def pending_migrations():
    executor = MigrationExecutor(connections[DEFAULT_DB_ALIAS])
    return [f'{m.app_label}.{m.name}' for m, _ in executor.migration_plan(executor.loader.graph.leaf_nodes())]


def require_up_to_date_database():
    pending = pending_migrations()
    if pending:
        raise CommandError(
            f'The database is not up to date: {len(pending)} migration(s) not applied ({", ".join(pending[:4])}{"…" if len(pending) > 4 else ""}).\n'
            'Apply them first, then run this command again:\n'
            '  docker compose up -d --build        (rebuilds and restarts; migrations run on start)\n'
            '  or: docker compose exec web python manage.py migrate')
