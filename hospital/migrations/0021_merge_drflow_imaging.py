# Joins the two migrations that were both numbered 0020. Changes nothing in the database.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('hospital', '0020_drflow_ask'),
        ('hospital', '0020_imaging_ai_runs'),
    ]

    operations = []
