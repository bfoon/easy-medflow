#!/bin/sh
set -eu
# Initial migration is generated deterministically from the included model definitions.
# Commit the generated migration to version control for production upgrade management.
python manage.py makemigrations hospital --noinput
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py bootstrap_hospital
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --access-logfile -
