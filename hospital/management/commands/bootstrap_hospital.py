from django.core.management.base import BaseCommand
from decimal import Decimal
from hospital.models import Department, LabCategory, LabParameter, LabTest, Ward, Bed, Medication
from hospital.lab_catalog import CATALOG


class Command(BaseCommand):
    help = 'Seed a safe empty hospital configuration (no patients or clinical events). Idempotent.'

    def handle(self, *args, **kwargs):
        for name in ['Emergency', 'Outpatient', 'General Medicine', 'Pediatrics', 'Maternity', 'Laboratory', 'Pharmacy', 'Radiology', 'Surgery']:
            Department.objects.get_or_create(name=name)
        self.load_lab_catalog()
        layout = [('General Ward', 'GW', 10, 'general'), ('Maternity Ward', 'MW', 6, 'maternity'),
                  ('Pediatric Ward', 'PW', 6, 'pediatric'), ('Intensive Care', 'ICU', 4, 'icu')]
        for ward_name, prefix, n, kind in layout:
            ward, _ = Ward.objects.get_or_create(name=ward_name)
            for i in range(1, n + 1):
                Bed.objects.get_or_create(code=f'{prefix}-{i:02d}', defaults={'ward': ward, 'kind': kind})
        meds = [('Paracetamol', 'paracetamol', 'Tablet', '500 mg'), ('Amoxicillin', 'amoxicillin', 'Capsule', '500 mg'),
                ('Artemether/Lumefantrine', 'artemether-lumefantrine', 'Tablet', '20/120 mg'), ('ORS', 'oral rehydration salts', 'Sachet', '20.5 g'),
                ('Metformin', 'metformin', 'Tablet', '500 mg'), ('Amlodipine', 'amlodipine', 'Tablet', '5 mg'),
                ('Ibuprofen', 'ibuprofen', 'Tablet', '400 mg'), ('Ferrous sulfate', 'ferrous sulfate', 'Tablet', '200 mg'),
                ('Ceftriaxone', 'ceftriaxone', 'Injection', '1 g'), ('Zinc sulfate', 'zinc', 'Tablet', '20 mg')]
        for name, generic, form, strength in meds:
            Medication.objects.get_or_create(name=name, defaults={'generic_name': generic, 'form': form, 'strength': strength})
        if kwargs.get('verbosity', 1):
            self.stdout.write(self.style.SUCCESS('Seeded departments, standard lab catalogue, 4 wards / 26 beds, and a medication catalog.'))

    def load_lab_catalog(self):
        """Add any missing standard categories, tests and parameters. Never overwrites local edits (e.g. your own ranges)."""
        dec = lambda v: None if v is None else Decimal(str(v))
        for i, (ccode, cname, color, tests) in enumerate(CATALOG):
            cat, _ = LabCategory.objects.get_or_create(code=ccode, defaults={'name': cname, 'color': color, 'sort_order': i})
            for code, name, system, sample, container, tat, params in tests:
                test, created = LabTest.objects.get_or_create(code=code, defaults={
                    'name': name, 'category': cat, 'body_system': system, 'sample_type': sample, 'container': container, 'turnaround_hours': tat})
                if not created and test.category_id is None:  # upgrade a test from the original uncategorised catalogue
                    test.category, test.body_system, test.container, test.turnaround_hours = cat, system, container, tat
                    test.save(update_fields=['category', 'body_system', 'container', 'turnaround_hours', 'updated_at'])
                for j, prm in enumerate(params):
                    d = dict(prm); pcode = d.pop('code')
                    for k in ('ref_low', 'ref_high', 'critical_low', 'critical_high', 'female_ref_low', 'female_ref_high'):
                        if k in d: d[k] = dec(d[k])
                    d['sort_order'] = j
                    LabParameter.objects.get_or_create(test=test, code=pcode, defaults=d)
