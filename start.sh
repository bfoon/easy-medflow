#!/bin/sh
set -eu
# Migrations are committed to the repository; never generate them at boot.
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py bootstrap_hospital
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --access-logfile -
