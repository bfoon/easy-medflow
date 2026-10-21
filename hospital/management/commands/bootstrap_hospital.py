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
        from hospital.evidence import seed_who_references
        seed_who_references()     # WHO reference values beside the hospital ranges; never overwrites lab edits
        layout = [('General Ward', 'GW', 10, 'general'), ('Maternity Ward', 'MW', 6, 'maternity'),
                  ('Pediatric Ward', 'PW', 6, 'pediatric'), ('Intensive Care', 'ICU', 4, 'icu')]
        details = {'GW': {'kind': 'general', 'age_group': 'adult', 'floor': 'Ground floor'},
                   'MW': {'kind': 'maternity', 'sex_policy': 'female', 'floor': 'Level 1', 'visiting_note': 'Partners welcome at any time'},
                   'PW': {'kind': 'paediatric', 'age_group': 'children', 'floor': 'Level 1', 'visiting_note': 'One parent may stay overnight'},
                   'ICU': {'kind': 'icu', 'floor': 'Ground floor', 'visiting_note': 'Two visitors at a time; ask at the desk first'}}
        from datetime import time as _t
        for i, (ward_name, prefix, n, kind) in enumerate(layout):
            ward, _ = Ward.objects.get_or_create(name=ward_name, defaults=dict(code=prefix, sort_order=i, visiting_from=_t(16), visiting_to=_t(18), **details[prefix]))
            for i in range(1, n + 1):
                Bed.objects.get_or_create(code=f'{prefix}-{i:02d}', defaults={'ward': ward, 'kind': kind})
        meds = [('Paracetamol', 'paracetamol', 'Tablet', '500 mg'), ('Amoxicillin', 'amoxicillin', 'Capsule', '500 mg'),
                ('Artemether/Lumefantrine', 'artemether-lumefantrine', 'Tablet', '20/120 mg'), ('ORS', 'oral rehydration salts', 'Sachet', '20.5 g'),
                ('Metformin', 'metformin', 'Tablet', '500 mg'), ('Amlodipine', 'amlodipine', 'Tablet', '5 mg'),
                ('Ibuprofen', 'ibuprofen', 'Tablet', '400 mg'), ('Ferrous sulfate', 'ferrous sulfate', 'Tablet', '200 mg'),
                ('Ceftriaxone', 'ceftriaxone', 'Injection', '1 g'), ('Zinc sulfate', 'zinc', 'Tablet', '20 mg')]
        for name, generic, form, strength in meds:
            # Names are not unique: Paracetamol 500 mg tablets and 120 mg/5 mL syrup are both stocked (seed_pharmacy adds
            # such pairs), so get_or_create(name=...) crashed on restart. Add a starter medicine only when no medicine of
            # that name exists; never duplicate or overwrite the hospital's own entries.
            if not Medication.objects.filter(name=name).exists():
                Medication.objects.create(name=name, generic_name=generic, form=form, strength=strength)
        self.load_locations()
        self.load_prices()   # after medicines and tests exist, so their prices are filled in
        self.load_theatre()
        if kwargs.get('verbosity', 1):
            self.stdout.write(self.style.SUCCESS('Seeded departments, standard lab catalogue, WHO reference values, 4 wards / 26 beds, 5 theatres with a procedure catalogue, and a medication catalog.'))

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

    def load_prices(self):
        """Illustrative prices in dalasi. Only fills in missing prices; never overwrites yours."""
        from decimal import Decimal
        from hospital.models import Tariff
        T = [('consultation', 'Outpatient consultation', 'consultation', 300), ('consultation-emergency', 'Emergency consultation', 'consultation', 600),
             ('consultation-specialist', 'Specialist consultation', 'consultation', 900),
             ('imaging-xray', 'X-ray', 'imaging', 750), ('imaging-ct', 'CT scan', 'imaging', 6500), ('imaging-mri', 'MRI scan', 'imaging', 12000),
             ('imaging-ultrasound', 'Ultrasound', 'imaging', 1200), ('imaging-ecg', 'ECG', 'imaging', 400), ('imaging-echo', 'Echocardiogram', 'imaging', 2500),
             ('imaging-mammogram', 'Mammogram', 'imaging', 3000), ('imaging-fluoro', 'Fluoroscopy', 'imaging', 3500),
             ('bed-general', 'General ward bed', 'bed', 800), ('bed-maternity', 'Maternity bed', 'bed', 900), ('bed-pediatric', 'Paediatric bed', 'bed', 700),
             ('bed-icu', 'ICU bed', 'bed', 4500), ('bed-isolation', 'Isolation bed', 'bed', 1500),
             ('dressing', 'Wound dressing', 'procedure', 250), ('suturing', 'Suturing', 'procedure', 600), ('iv-cannula', 'IV cannulation', 'procedure', 200),
             ('medical-report', 'Medical report', 'other', 500),
             ('anaesthesia-general', 'General anaesthetic', 'procedure', 2500), ('anaesthesia-spinal', 'Spinal anaesthetic', 'procedure', 1500),
             ('anaesthesia-epidural', 'Epidural anaesthetic', 'procedure', 1800), ('anaesthesia-regional', 'Regional nerve block', 'procedure', 1200),
             ('anaesthesia-local', 'Local anaesthetic', 'procedure', 300), ('anaesthesia-sedation', 'Procedural sedation', 'procedure', 800),
             ('theatre-hour', 'Theatre time (per hour)', 'procedure', 1500)]
        for code, name, cat, amt in T:
            Tariff.objects.get_or_create(code=code, defaults={'name': name, 'category': cat, 'amount': Decimal(amt)})
        lab = {'CBC': 450, 'HB': 150, 'ESR': 150, 'MAL': 200, 'MPS': 250, 'BGRP': 200, 'GLU': 150, 'HBA1C': 900, 'LFT': 900, 'RFT': 850, 'PANC': 1000,
               'CRP': 600, 'BONE': 900, 'TROP': 1500, 'CARD': 2200, 'LIPID': 900, 'TFT': 1500, 'HCG': 250, 'PSA': 1100, 'UA': 200, 'STL': 250,
               'AFB': 300, 'XPERT': 0, 'CSF': 1200, 'HIV': 0, 'HBSAG': 350, 'ABG': 1400}   # TB GeneXpert and HIV tests are free under national programmes
        for code, price in lab.items():
            LabTest.objects.filter(code=code, price=0).update(price=Decimal(price))
        meds = {'Paracetamol': '2.00', 'Amoxicillin': '6.00', 'Artemether/Lumefantrine': '9.00', 'ORS': '15.00', 'Metformin': '3.00', 'Amlodipine': '4.00',
                'Ibuprofen': '3.00', 'Ferrous sulfate': '1.50', 'Ceftriaxone': '120.00', 'Zinc sulfate': '2.50'}
        for name, price in meds.items():
            Medication.objects.filter(name=name, unit_price=0).update(unit_price=Decimal(price))

    def load_theatre(self):
        """Standard operating rooms and procedure catalogue. Adds missing entries only; never overwrites your edits."""
        from decimal import Decimal
        from datetime import time
        from hospital.models import OperatingRoom, ProcedureType
        rooms = [('Main Theatre 1', 'main', 0, time(8), time(17)), ('Main Theatre 2', 'main', 1, time(8), time(17)),
                 ('Obstetric Theatre', 'obstetric', 2, time(0), time(23, 59)), ('Eye & ENT Theatre', 'eye_ent', 3, time(8), time(14)),
                 ('Minor Procedures Room', 'minor', 4, time(8), time(16))]
        for name, kind, order, a, b in rooms:
            OperatingRoom.objects.get_or_create(name=name, defaults={'kind': kind, 'sort_order': order, 'session_start': a, 'session_end': b})
        # code, name, specialty, minutes, anaesthetic, needs side, minor, price (dalasi, illustrative)
        P = [('appendicectomy', 'Appendicectomy', 'general', 60, 'general', False, False, 6000),
             ('hernia-inguinal', 'Inguinal hernia repair', 'general', 60, 'spinal', True, False, 5000),
             ('laparotomy', 'Exploratory laparotomy', 'general', 120, 'general', False, False, 12000),
             ('cholecystectomy', 'Cholecystectomy', 'general', 90, 'general', False, False, 12000),
             ('thyroidectomy', 'Thyroidectomy', 'general', 120, 'general', False, False, 14000),
             ('incision-drainage', 'Incision and drainage of abscess', 'general', 20, 'local', False, True, 1200),
             ('debridement', 'Wound debridement', 'general', 45, 'general', False, False, 3000),
             ('circumcision', 'Circumcision', 'urology', 30, 'local', False, True, 1500),
             ('turp', 'Transurethral resection of the prostate (TURP)', 'urology', 90, 'spinal', False, False, 15000),
             ('caesarean', 'Caesarean section', 'obgyn', 60, 'spinal', False, False, 8000),
             ('evacuation', 'Evacuation of the uterus (MVA / D&C)', 'obgyn', 30, 'sedation', False, True, 2500),
             ('hysterectomy', 'Abdominal hysterectomy', 'obgyn', 150, 'general', False, False, 15000),
             ('orif-femur', 'Fixation of femur fracture (ORIF / nail)', 'orthopaedic', 150, 'spinal', True, False, 18000),
             ('orif-forearm', 'Fixation of forearm fracture (ORIF)', 'orthopaedic', 90, 'regional', True, False, 10000),
             ('amputation-bka', 'Below-knee amputation', 'orthopaedic', 90, 'spinal', True, False, 10000),
             ('skin-graft', 'Split-skin graft', 'plastic', 90, 'general', False, False, 9000),
             ('escharotomy', 'Escharotomy (burns)', 'plastic', 45, 'general', False, False, 4000),
             ('cataract', 'Cataract surgery (SICS / phaco) with lens implant', 'eye', 30, 'local', True, False, 4500),
             ('trabeculectomy', 'Trabeculectomy (glaucoma)', 'eye', 60, 'local', True, False, 6000),
             ('pterygium', 'Pterygium excision with graft', 'eye', 30, 'local', True, True, 2500),
             ('ear-microsuction', 'Ear microsuction (wax / foreign body removal)', 'ent', 15, 'local', True, True, 300),
             ('grommet', 'Myringotomy and grommet insertion', 'ent', 20, 'general', True, False, 3000),
             ('tympanoplasty', 'Tympanoplasty (repair of the ear drum)', 'ent', 120, 'general', True, False, 9000),
             ('mastoidectomy', 'Mastoidectomy (cholesteatoma)', 'ent', 150, 'general', True, False, 14000),
             ('tonsillectomy', 'Tonsillectomy', 'ent', 45, 'general', False, False, 5000)]
        for code, name, spec, mins, an, side, minor, price in P:
            ProcedureType.objects.get_or_create(code=code, defaults={'name': name, 'specialty': spec, 'default_minutes': mins, 'default_anaesthesia': an,
                                                                       'needs_side': side, 'minor': minor, 'price': Decimal(price)})

    def load_locations(self):
        """Add any missing standard Gambian towns and areas, then link patients to a location from their address.
        Never overwrites your edits."""
        from decimal import Decimal
        from hospital.gambia_locations import TOWNS, AREAS
        from hospital.models import Location, Patient
        towns = {}
        for name, region, lat, lon in TOWNS:
            towns[name], _ = Location.objects.get_or_create(name=name, parent=None, defaults={'region': region, 'latitude': Decimal(str(lat)), 'longitude': Decimal(str(lon))})
        for name, town, lat, lon in AREAS:
            t = towns.get(town)
            if t:
                Location.objects.get_or_create(name=name, parent=t, defaults={'kind': 'area', 'region': t.region, 'latitude': Decimal(str(lat)), 'longitude': Decimal(str(lon))})
        link_patient_locations()


def link_patient_locations():
    """Patients without a location: match the town written at the end of their address (e.g. '12 Main Road, Brikama')."""
    from hospital.models import Location, Patient
    by_name = {l.name.lower(): l for l in Location.objects.filter(active=True).order_by('-kind')}   # towns win over areas of the same name
    n = 0
    for p in Patient.objects.filter(location__isnull=True).exclude(address=''):
        parts = [x.strip().lower() for x in p.address.replace('\n', ',').split(',') if x.strip()]
        for part in reversed(parts):
            if part in by_name:
                p.location = by_name[part]; p.save(update_fields=['location']); n += 1; break
    return n
