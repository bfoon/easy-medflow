#!/bin/sh
# Development entrypoint: the Docker equivalent of
#   pip install -r requirements.txt   (done at image build)
#   migrate → seed_demo → createsuperuser → runserver
set -eu

echo "→ Waiting for the database"
python manage.py wait_for_db

echo "→ Applying migrations"
python manage.py migrate --noinput

echo "→ Loading standard configuration and lab catalogue"
python manage.py bootstrap_hospital

echo "→ Seeding fictional demo data (first start only)"
python manage.py seed_demo --if-empty

echo "→ Ensuring admin account"
python manage.py shell -c "
import os
from django.contrib.auth import get_user_model
U = get_user_model()
name = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
if U.objects.filter(username=name).exists():
    print(f'   Admin \"{name}\" already exists')
else:
    U.objects.create_superuser(name, os.environ.get('DJANGO_SUPERUSER_EMAIL', ''), os.environ['DJANGO_SUPERUSER_PASSWORD'])
    print(f'   Created admin \"{name}\"')
"

echo "→ MedFlow is starting (open http://localhost:${MEDFLOW_PORT:-8000} on your machine)"
exec python manage.py runserver 0.0.0.0:8000
