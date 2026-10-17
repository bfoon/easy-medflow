from django.db import migrations, models


class Migration(migrations.Migration):
    """The 3D body view on Lab insights (body3d.js) can be remembered as a clinician's preferred view."""

    dependencies = [
        ('hospital', '0027_clinical_notes_editing'),
    ]

    operations = [
        migrations.AlterField(
            model_name='staffprofile',
            name='lab_view',
            field=models.CharField(choices=[('body', 'Body map'), ('anatomy', 'Anatomy'), ('body3d', '3D body'), ('clean', 'Charts & lists')], default='body', help_text='Preferred way to review lab results', max_length=10),
        ),
    ]
