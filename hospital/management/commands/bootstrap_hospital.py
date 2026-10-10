from django.core.management.base import BaseCommand
from hospital.models import Department, LabTest, Ward, Bed, Medication


class Command(BaseCommand):
    help = 'Seed a safe empty hospital configuration (no patients or clinical events). Idempotent.'

    def handle(self, *args, **kwargs):
        for name in ['Emergency', 'Outpatient', 'General Medicine', 'Pediatrics', 'Maternity', 'Laboratory', 'Pharmacy', 'Radiology', 'Surgery']:
            Department.objects.get_or_create(name=name)
        tests = [('CBC', 'Complete Blood Count', 'Blood'), ('GLU', 'Blood Glucose', 'Blood'), ('UA', 'Urinalysis', 'Urine'),
                 ('MAL', 'Malaria RDT', 'Blood'), ('HB', 'Haemoglobin', 'Blood'), ('LFT', 'Liver Function Panel', 'Blood'),
                 ('RFT', 'Renal Function Panel', 'Blood'), ('STL', 'Stool Microscopy', 'Stool')]
        for code, name, sample in tests:
            LabTest.objects.get_or_create(code=code, defaults={'name': name, 'sample_type': sample})
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
            self.stdout.write(self.style.SUCCESS('Seeded departments, lab catalog, 4 wards / 26 beds, and a medication catalog.'))
