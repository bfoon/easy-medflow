"""Sample pharmacy data: about 85 essential medicines, suppliers, stores and ward cupboards, and 90 days of simulated
operations run through the real stock engine, so every balance, chart and report is internally consistent.

What the simulation does, day by day:
  * outpatient dispensing at the Main Pharmacy, with a rainy-season rise in antimalarials, ORS and zinc;
  * medicines used on the wards (controlled drugs always witnessed);
  * weekly ward requisitions, and twice-weekly top-ups of the pharmacy from the central store;
  * purchase orders raised when stock falls to the reorder level, delivered after each supplier's lead time;
  * a damaged write-off, an expiry write-off, a month-end stock take with differences, a recalled batch.
It ends with work in progress: deliveries due, a part delivery, an urgent requisition, an open stock take, near-expiry
and expired stock, and a couple of stockouts. All names are FICTIONAL.

    python manage.py seed_pharmacy            # needs DEBUG=True, or --force
"""
import random
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

D = Decimal
# name, generic, form, strength, category, unit, pack, price (GMD per unit), reorder level, base daily use, flags
# flags: C controlled · K cold chain · N not on the essential list · W ward stock · S rainy-season demand · P free national programme
MEDS = [
    ('Paracetamol', 'paracetamol', 'Tablet', '500 mg', 'analgesic', 'tablet', 1000, 2, 3000, 260, 'W'),
    ('Paracetamol', 'paracetamol', 'Syrup', '120 mg/5 mL', 'analgesic', 'bottle', 1, 45, 60, 6, 'W'),
    ('Ibuprofen', 'ibuprofen', 'Tablet', '400 mg', 'analgesic', 'tablet', 1000, 3, 1500, 90, ''),
    ('Diclofenac', 'diclofenac', 'Injection', '75 mg/3 mL', 'analgesic', 'ampoule', 10, 25, 100, 6, 'W'),
    ('Tramadol', 'tramadol', 'Capsule', '50 mg', 'analgesic', 'capsule', 100, 6, 300, 12, ''),
    ('Morphine', 'morphine sulfate', 'Injection', '10 mg/mL', 'analgesic', 'ampoule', 10, 85, 30, 1.2, 'CW'),
    ('Pethidine', 'pethidine', 'Injection', '50 mg/mL', 'analgesic', 'ampoule', 10, 70, 20, .6, 'CW'),
    ('Amoxicillin', 'amoxicillin', 'Capsule', '500 mg', 'antibiotic', 'capsule', 1000, 6, 2500, 160, ''),
    ('Amoxicillin', 'amoxicillin', 'Suspension', '125 mg/5 mL', 'antibiotic', 'bottle', 1, 55, 80, 7, 'W'),
    ('Co-amoxiclav', 'amoxicillin + clavulanic acid', 'Tablet', '625 mg', 'antibiotic', 'tablet', 100, 18, 400, 18, ''),
    ('Ceftriaxone', 'ceftriaxone', 'Injection', '1 g', 'antibiotic', 'vial', 50, 120, 150, 9, 'W'),
    ('Metronidazole', 'metronidazole', 'Tablet', '400 mg', 'antibiotic', 'tablet', 1000, 2, 1200, 60, ''),
    ('Metronidazole', 'metronidazole', 'IV infusion', '500 mg/100 mL', 'antibiotic', 'bag', 1, 90, 60, 4, 'W'),
    ('Ciprofloxacin', 'ciprofloxacin', 'Tablet', '500 mg', 'antibiotic', 'tablet', 100, 8, 500, 22, ''),
    ('Cotrimoxazole', 'sulfamethoxazole + trimethoprim', 'Tablet', '480 mg', 'antibiotic', 'tablet', 1000, 2, 1500, 70, ''),
    ('Gentamicin', 'gentamicin', 'Injection', '80 mg/2 mL', 'antibiotic', 'ampoule', 10, 20, 100, 6, 'W'),
    ('Benzylpenicillin', 'benzylpenicillin', 'Injection', '5 MU', 'antibiotic', 'vial', 50, 40, 60, 3, 'W'),
    ('Azithromycin', 'azithromycin', 'Tablet', '500 mg', 'antibiotic', 'tablet', 30, 25, 150, 6, ''),
    ('Doxycycline', 'doxycycline', 'Capsule', '100 mg', 'antibiotic', 'capsule', 100, 4, 300, 12, ''),
    ('Flucloxacillin', 'flucloxacillin', 'Capsule', '500 mg', 'antibiotic', 'capsule', 100, 9, 300, 10, ''),
    ('Nitrofurantoin', 'nitrofurantoin', 'Tablet', '100 mg', 'antibiotic', 'tablet', 100, 6, 200, 6, 'N'),
    ('Artemether/Lumefantrine', 'artemether-lumefantrine', 'Tablet', '20/120 mg', 'antimalarial', 'tablet', 720, 9, 4000, 220, 'SP'),
    ('Artesunate', 'artesunate', 'Injection', '60 mg', 'antimalarial', 'vial', 50, 150, 120, 6, 'SWP'),
    ('Quinine', 'quinine sulfate', 'Tablet', '300 mg', 'antimalarial', 'tablet', 1000, 5, 300, 8, 'S'),
    ('Sulfadoxine/Pyrimethamine', 'SP (IPTp)', 'Tablet', '500/25 mg', 'obstetric', 'tablet', 1000, 3, 400, 14, 'P'),
    ('TLD', 'tenofovir/lamivudine/dolutegravir', 'Tablet', '300/300/50 mg', 'antiretroviral', 'tablet', 30, 0, 1800, 60, 'P'),
    ('RHZE', 'rifampicin/isoniazid/pyrazinamide/ethambutol', 'Tablet', '150/75/400/275 mg', 'tb', 'tablet', 672, 0, 1500, 40, 'P'),
    ('RH', 'rifampicin/isoniazid', 'Tablet', '150/75 mg', 'tb', 'tablet', 672, 0, 1200, 30, 'P'),
    ('Amlodipine', 'amlodipine', 'Tablet', '5 mg', 'cardiovascular', 'tablet', 1000, 4, 1500, 70, ''),
    ('Lisinopril', 'lisinopril', 'Tablet', '10 mg', 'cardiovascular', 'tablet', 1000, 5, 800, 35, ''),
    ('Hydrochlorothiazide', 'hydrochlorothiazide', 'Tablet', '25 mg', 'cardiovascular', 'tablet', 1000, 2, 800, 30, ''),
    ('Atenolol', 'atenolol', 'Tablet', '50 mg', 'cardiovascular', 'tablet', 1000, 3, 400, 14, ''),
    ('Furosemide', 'furosemide', 'Tablet', '40 mg', 'cardiovascular', 'tablet', 1000, 2, 500, 18, ''),
    ('Furosemide', 'furosemide', 'Injection', '20 mg/2 mL', 'cardiovascular', 'ampoule', 10, 15, 80, 4, 'W'),
    ('Aspirin', 'acetylsalicylic acid', 'Tablet', '75 mg', 'cardiovascular', 'tablet', 1000, 1, 600, 22, ''),
    ('Atorvastatin', 'atorvastatin', 'Tablet', '20 mg', 'cardiovascular', 'tablet', 100, 8, 400, 14, ''),
    ('Hydralazine', 'hydralazine', 'Injection', '20 mg', 'cardiovascular', 'ampoule', 5, 95, 20, .6, 'W'),
    ('Metformin', 'metformin', 'Tablet', '500 mg', 'diabetes', 'tablet', 1000, 3, 2000, 110, ''),
    ('Glibenclamide', 'glibenclamide', 'Tablet', '5 mg', 'diabetes', 'tablet', 1000, 2, 500, 20, ''),
    ('Insulin soluble', 'human insulin, regular', 'Injection', '100 IU/mL, 10 mL', 'diabetes', 'vial', 1, 450, 30, 1.2, 'KW'),
    ('Insulin isophane', 'human insulin, NPH', 'Injection', '100 IU/mL, 10 mL', 'diabetes', 'vial', 1, 450, 30, 1.5, 'K'),
    ('Dextrose', 'glucose', 'Injection', '50%, 50 mL', 'emergency', 'vial', 1, 60, 30, 1.5, 'W'),
    ('Salbutamol', 'salbutamol', 'Inhaler', '100 mcg/dose', 'respiratory', 'inhaler', 1, 180, 40, 2.5, ''),
    ('Salbutamol', 'salbutamol', 'Nebuliser solution', '2.5 mg/2.5 mL', 'respiratory', 'piece', 20, 12, 100, 5, 'W'),
    ('Beclometasone', 'beclometasone', 'Inhaler', '100 mcg/dose', 'respiratory', 'inhaler', 1, 250, 20, .8, ''),
    ('Prednisolone', 'prednisolone', 'Tablet', '5 mg', 'respiratory', 'tablet', 1000, 1.5, 600, 20, ''),
    ('Hydrocortisone', 'hydrocortisone sodium succinate', 'Injection', '100 mg', 'emergency', 'vial', 1, 75, 40, 1.5, 'W'),
    ('ORS', 'oral rehydration salts', 'Sachet', '20.5 g', 'gi', 'sachet', 100, 15, 800, 45, 'S'),
    ('Zinc sulfate', 'zinc', 'Tablet', '20 mg', 'gi', 'tablet', 100, 2.5, 600, 35, 'S'),
    ('Omeprazole', 'omeprazole', 'Capsule', '20 mg', 'gi', 'capsule', 100, 4, 600, 25, ''),
    ('Metoclopramide', 'metoclopramide', 'Injection', '10 mg/2 mL', 'gi', 'ampoule', 10, 12, 60, 3, 'W'),
    ('Albendazole', 'albendazole', 'Tablet', '400 mg', 'gi', 'tablet', 100, 5, 300, 14, ''),
    ('Hyoscine butylbromide', 'hyoscine butylbromide', 'Injection', '20 mg/mL', 'gi', 'ampoule', 10, 18, 50, 2, 'W'),
    ('Oxytocin', 'oxytocin', 'Injection', '10 IU/mL', 'obstetric', 'ampoule', 10, 35, 150, 6, 'KW'),
    ('Misoprostol', 'misoprostol', 'Tablet', '200 mcg', 'obstetric', 'tablet', 100, 12, 200, 4, ''),
    ('Magnesium sulfate', 'magnesium sulfate', 'Injection', '50%, 10 mL', 'obstetric', 'ampoule', 10, 30, 100, 4, 'W'),
    ('Ergometrine', 'ergometrine', 'Injection', '0.5 mg/mL', 'obstetric', 'ampoule', 10, 40, 20, .5, 'KW'),
    ('Ferrous sulfate + folic acid', 'ferrous sulfate + folic acid', 'Tablet', '200 mg/0.4 mg', 'obstetric', 'tablet', 1000, 1.5, 2000, 90, ''),
    ('Ferrous sulfate', 'ferrous sulfate', 'Tablet', '200 mg', 'vitamin', 'tablet', 1000, 1.5, 800, 30, ''),
    ('Folic acid', 'folic acid', 'Tablet', '5 mg', 'vitamin', 'tablet', 1000, 1, 500, 18, ''),
    ('Vitamin A', 'retinol', 'Capsule', '200,000 IU', 'vitamin', 'capsule', 500, 3, 200, 6, 'P'),
    ('Multivitamin', 'multivitamins', 'Syrup', '100 mL', 'vitamin', 'bottle', 1, 40, 40, 3, 'N'),
    ('Sodium chloride', 'sodium chloride', 'IV infusion', '0.9%, 1 L', 'fluids', 'bag', 10, 65, 200, 18, 'W'),
    ("Ringer's lactate", 'compound sodium lactate', 'IV infusion', '1 L', 'fluids', 'bag', 10, 70, 200, 16, 'W'),
    ('Dextrose', 'glucose', 'IV infusion', '5%, 500 mL', 'fluids', 'bag', 20, 55, 120, 9, 'W'),
    ('Water for injection', 'water for injection', 'Injection', '10 mL', 'fluids', 'ampoule', 50, 5, 300, 20, 'W'),
    ('Ketamine', 'ketamine', 'Injection', '50 mg/mL, 10 mL', 'anaesthetic', 'vial', 1, 120, 20, .7, 'CW'),
    ('Lidocaine', 'lidocaine', 'Injection', '2%, 20 mL', 'anaesthetic', 'vial', 1, 45, 50, 3, 'W'),
    ('Bupivacaine heavy', 'bupivacaine + glucose', 'Injection', '0.5%, 4 mL', 'anaesthetic', 'ampoule', 5, 60, 30, 1.2, 'W'),
    ('Adrenaline', 'epinephrine', 'Injection', '1 mg/mL', 'emergency', 'ampoule', 10, 35, 40, 1, 'W'),
    ('Diazepam', 'diazepam', 'Injection', '10 mg/2 mL', 'emergency', 'ampoule', 10, 20, 40, 1.5, 'CW'),
    ('Phenobarbital', 'phenobarbital', 'Tablet', '30 mg', 'mental', 'tablet', 1000, 2, 200, 6, 'C'),
    ('Atropine', 'atropine', 'Injection', '1 mg/mL', 'emergency', 'ampoule', 10, 15, 30, .5, 'W'),
    ('Naloxone', 'naloxone', 'Injection', '0.4 mg/mL', 'emergency', 'ampoule', 10, 90, 10, .1, 'W'),
    ('Haloperidol', 'haloperidol', 'Tablet', '5 mg', 'mental', 'tablet', 1000, 3, 200, 6, ''),
    ('Amitriptyline', 'amitriptyline', 'Tablet', '25 mg', 'mental', 'tablet', 1000, 2, 300, 10, ''),
    ('Carbamazepine', 'carbamazepine', 'Tablet', '200 mg', 'mental', 'tablet', 1000, 4, 400, 14, ''),
    ('Fluoxetine', 'fluoxetine', 'Capsule', '20 mg', 'mental', 'capsule', 100, 5, 150, 4, ''),
    ('Silver sulfadiazine', 'silver sulfadiazine', 'Cream', '1%, 500 g', 'skin', 'tube', 1, 120, 20, .7, 'W'),
    ('Clotrimazole', 'clotrimazole', 'Cream', '1%, 20 g', 'skin', 'tube', 1, 35, 60, 3, ''),
    ('Povidone-iodine', 'povidone-iodine', 'Solution', '10%, 500 mL', 'skin', 'bottle', 1, 150, 20, 1, 'W'),
    ('Calamine', 'calamine', 'Lotion', '100 mL', 'skin', 'bottle', 1, 40, 20, .8, 'N'),
    ('Tetracycline', 'tetracycline', 'Eye ointment', '1%', 'eye', 'tube', 1, 25, 80, 4, ''),
    ('Chloramphenicol', 'chloramphenicol', 'Eye drops', '0.5%', 'eye', 'bottle', 1, 30, 50, 2, ''),
    ('Tetanus toxoid', 'tetanus toxoid vaccine', 'Injection', '0.5 mL dose', 'vaccine', 'dose', 10, 0, 100, 5, 'KP'),
    ('Rabies vaccine', 'inactivated rabies vaccine', 'Injection', '1 dose', 'vaccine', 'vial', 1, 950, 10, .3, 'K'),
]
PROGRAMME_COST = {'TLD': 4, 'RHZE': 3, 'RH': 2, 'Artemether/Lumefantrine': 5, 'Artesunate': 85, 'Sulfadoxine/Pyrimethamine': 2, 'Vitamin A': 1.5, 'Tetanus toxoid': 9}

SUPPLIERS = {   # key: (name, contact, phone, email, address, lead days)
    'kombo': ('Kombo Medical Supplies', 'Lamin Sanyang', '+220 439 1180', 'orders@kombomedical.example', 'Bakoteh Industrial Estate', 10),
    'atlantic': ('Atlantic Pharma Distributors', 'Fatou Gaye', '+220 446 2275', 'sales@atlanticpharma.example', 'Kanifing Layout', 14),
    'sahel': ('Sahel Health Logistics', 'Ousman Bah', '+220 449 7034', 'logistics@sahelhealth.example', 'Banjul port road', 21),
    'programme': ('National Programme Medical Stores (sample)', 'Programme logistics officer', '+220 422 6610', 'supply@programme-stores.example', 'Kotu', 30),
    'banjul': ('Banjul Surgical & Pharma', 'Haddy Jobe', '+220 422 9047', 'urgent@banjulsurgical.example', 'Liberation Avenue, Banjul', 7),
}

WARDS = {   # stock location: (kind, linked ward name, what it holds)
    'General Ward Stock': ('ward', 'General Ward', {'cats': {'analgesic', 'antibiotic', 'fluids', 'gi', 'cardiovascular', 'diabetes'}}),
    'Maternity Ward Stock': ('ward', 'Maternity Ward', {'cats': {'obstetric', 'fluids'}, 'names': {'Ceftriaxone', 'Paracetamol', 'Diclofenac', 'Gentamicin', 'Hydralazine'}}),
    'Pediatric Ward Stock': ('ward', 'Pediatric Ward', {'names': {'Paracetamol 120 mg/5 mL', 'Amoxicillin 125 mg/5 mL', 'ORS', 'Zinc sulfate', 'Artesunate', 'Ceftriaxone', 'Gentamicin',
                                                                   'Dextrose 5%, 500 mL', "Ringer's lactate", 'Water for injection', 'Salbutamol 2.5 mg/2.5 mL', 'Diazepam'}}),
    'ICU Stock': ('ward', 'Intensive Care', {'cats': {'emergency', 'fluids'}, 'names': {'Morphine', 'Ceftriaxone', 'Furosemide 20 mg/2 mL', 'Insulin soluble', 'Metronidazole 500 mg/100 mL'}}),
    'Theatre Stock': ('theatre', None, {'cats': {'anaesthetic'}, 'names': {'Morphine', 'Pethidine', 'Sodium chloride', "Ringer's lactate", 'Oxytocin', 'Ceftriaxone', 'Adrenaline', 'Atropine'}}),
    'Emergency Trolley': ('emergency', None, {'names': {'Adrenaline', 'Atropine', 'Diazepam', 'Dextrose 50%, 50 mL', 'Hydrocortisone', 'Naloxone', 'Salbutamol 2.5 mg/2.5 mL'}}),
}


class Command(BaseCommand):
    help = 'Sample pharmacy: medicines, suppliers, stores and 90 days of simulated stock operations (fictional).'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=90)
        parser.add_argument('--force', action='store_true', help='Allow when DEBUG is False (the data is fictional)')

    def handle(self, *args, days=90, force=False, **kw):
        if not settings.DEBUG and not force:
            raise CommandError('DEBUG is False. This creates FICTIONAL pharmacy history; run with --force only on a demo server.')
        from hospital.management.dbcheck import require_up_to_date_database
        require_up_to_date_database()
        from hospital.models import StockMovement
        if StockMovement.objects.filter(reference='OPENING').exists():
            self.stdout.write(self.style.WARNING('Sample pharmacy history already exists; nothing added.'))
            return
        self.rng = random.Random(2026)
        self.days = max(30, min(days, 180))
        with transaction.atomic():
            self.setup()
            self.simulate()
            self.finish_state()
        from hospital.models import PurchaseOrder, Requisition, StockBatch
        self.stdout.write(self.style.SUCCESS(
            f'Pharmacy sample ready: {len(self.meds)} medicines, {len(self.sups)} suppliers, {len(self.locs)} stock locations, '
            f'{StockMovement.objects.count()} ledger entries, {PurchaseOrder.objects.count()} purchase orders, {Requisition.objects.count()} requisitions, '
            f'{StockBatch.objects.filter(quantity__gt=0).count()} batches in stock. Stockouts on the way: {self.stockout_days} medicine-days.'))

    # ---------------------------------------------------------------- helpers
    def at(self, day, hour=None):
        h = hour if hour is not None else self.rng.uniform(8, 17)
        return timezone.make_aware(datetime.combine(day, time(int(h), int((h % 1) * 60))))

    def stamp(self, since, when, *objs):
        """Backdate everything created since ledger id `since` (and the given objects) to `when`."""
        from hospital.models import StockMovement
        StockMovement.objects.filter(pk__gt=since).update(created_at=when, updated_at=when)
        for o in objs:
            type(o).objects.filter(pk=o.pk).update(created_at=when, updated_at=when)

    def last_id(self):
        from hospital.models import StockMovement
        return StockMovement.objects.order_by('-pk').values_list('pk', flat=True).first() or 0

    def batch_no(self, sup_key):
        return f"{ {'kombo': 'KM', 'atlantic': 'AP', 'sahel': 'SH', 'programme': 'NP', 'banjul': 'BS'}[sup_key] }{self.rng.randint(10000, 99999)}"

    def witness_for(self, actor):
        pool = [u for u in self.nurses + self.pharmacists if u != actor]
        return self.rng.choice(pool)

    # ---------------------------------------------------------------- staff, places, suppliers, medicines
    def setup(self):
        from hospital.models import Medication, StaffProfile, StockLocation, Supplier, Ward
        User = get_user_model()

        def staff(username, first, last, role):
            u, created = User.objects.get_or_create(username=username, defaults={'first_name': first, 'last_name': last})
            if created:
                u.set_unusable_password(); u.save()
            StaffProfile.objects.get_or_create(user=u, defaults={'role': role})
            return u
        self.pharmacists = [p.user for p in StaffProfile.objects.filter(role='pharmacy', active=True).select_related('user')]
        self.pharmacists += [staff('pharm.sanneh', 'Haddy', 'Sanneh', 'pharmacy'), staff('store.jobe', 'Kebba', 'Jobe', 'pharmacy')]
        self.pharmacists = list(dict.fromkeys(self.pharmacists))
        self.nurses = [p.user for p in StaffProfile.objects.filter(role='nurse', active=True).select_related('user')]
        self.nurses += [staff('nurse.drammeh', 'Mariama', 'Drammeh', 'nurse'), staff('nurse.colley', 'Sainabou', 'Colley', 'nurse')]
        self.nurses = list(dict.fromkeys(self.nurses))
        self.storekeeper = User.objects.get(username='store.jobe')

        self.locs = {}
        self.store = StockLocation.objects.get_or_create(name='Central Medical Store', defaults={'kind': 'store'})[0]
        self.pharmacy = StockLocation.dispensing()
        self.quarantine = StockLocation.objects.get_or_create(name='Quarantine Shelf', defaults={'kind': 'quarantine'})[0]
        self.locs.update({'store': self.store, 'pharmacy': self.pharmacy, 'quarantine': self.quarantine})
        for name, (kind, ward, _) in WARDS.items():
            self.locs[name] = StockLocation.objects.get_or_create(name=name, defaults={'kind': kind, 'ward': Ward.objects.filter(name=ward).first() if ward else None})[0]

        self.sups = {}
        for key, (name, contact, phone, email, addr, lead) in SUPPLIERS.items():
            self.sups[key] = Supplier.objects.get_or_create(name=name, defaults={'contact_person': contact, 'phone': phone, 'email': email, 'address': addr, 'lead_time_days': lead})[0]

        self.meds = []
        for name, generic, form, strength, cat, unit, pack, price, reorder, daily, flags in MEDS:
            sup = 'programme' if 'P' in flags else 'sahel' if cat == 'fluids' else 'banjul' if (cat in ('anaesthetic', 'emergency') or 'C' in flags) \
                else 'atlantic' if cat in ('cardiovascular', 'diabetes', 'mental') else 'kombo'
            if name in ('Salbutamol', 'Beclometasone') and unit == 'inhaler':
                sup = 'sahel'                                  # long lead time: these will run out
            m = Medication.objects.filter(name=name, strength=strength).first() or Medication(name=name, strength=strength)
            m.generic_name, m.form, m.category, m.unit, m.pack_size = generic, form, cat, unit, pack
            m.unit_price = D(str(price)) if not m.unit_price or m.unit_price == 0 else m.unit_price
            m.reorder_level, m.max_level = reorder, reorder * 3
            m.controlled, m.cold_chain, m.essential, m.default_supplier, m.active = 'C' in flags, 'K' in flags, 'N' not in flags, self.sups[sup], True
            m.save()
            cost = D(str(PROGRAMME_COST.get(name, price * .6))).quantize(D('0.01')) if price or name in PROGRAMME_COST else D('0.50')
            self.meds.append({'m': m, 'daily': daily, 'flags': flags, 'sup': sup, 'cost': cost, 'label': f'{name} {strength}'})
        self.by_label = {x['label']: x for x in self.meds}
        # which medicines each ward keeps in its cupboard
        self.ward_items = {}
        for loc_name, (_, _, rule) in WARDS.items():
            items = []
            for x in self.meds:
                m = x['m']
                if 'W' not in x['flags']:
                    continue
                if m.category in rule.get('cats', set()) or m.name in rule.get('names', set()) or x['label'] in rule.get('names', set()) \
                        or any(x['label'].startswith(n) for n in rule.get('names', set())):
                    items.append(x)
            self.ward_items[loc_name] = items

    # ---------------------------------------------------------------- the simulation
    def season(self, day):
        """Rainy season (July to October) drives malaria and diarrhoea up."""
        return {7: 1.5, 8: 2.0, 9: 2.4, 10: 2.1, 11: 1.4}.get(day.month, 1.0)

    def simulate(self):
        from hospital import pharmacy as ph
        from hospital.models import Patient
        today = timezone.localdate()
        self.start = today - timedelta(days=self.days)
        self.pending_po = []          # (due day, order)
        self.on_order = defaultdict(int)
        self.stockout_days = 0
        self.patients = list(Patient.objects.order_by('?')[:60])
        self.opening()
        for i in range(self.days, 0, -1):
            day = today - timedelta(days=i)
            weekday = day.weekday()
            busy = 0.55 if weekday == 6 else 0.8 if weekday == 5 else 1.0
            # in clock order, so running balances on the stock card read correctly: 08:30 shelf top-up, 10:00 orders,
            # 11:00 ward requisitions, 13:00 deliveries, 15-17:00 write-offs and counts, 18:00 dispensing, evening ward use
            if weekday in (0, 3):
                self.restock_pharmacy(day)
            if i % 3 == 0:
                self.purchase(day)
            if weekday == 1:
                self.ward_requisitions(day)
            self.receive_due(day)
            if i == 62:
                self.damaged(day)
            if i == 47:
                self.expire_writeoff(day)
            if i == 31:
                self.month_end_count(day)
            self.dispense_day(day, busy)
            self.ward_use_day(day)

    def opening(self):
        """Opening balances at the start of the period, including some short-dated and soon-to-expire batches."""
        from hospital import pharmacy as ph
        actor, day = self.storekeeper, self.start
        since = self.last_id()
        from hospital.models import StockBatch, StockMovement
        for b in StockBatch.objects.filter(quantity__gt=0, movements__isnull=True):    # stock that predates the ledger (e.g. from seed_demo)
            StockMovement.objects.create(medication=b.medication, batch=b, location=b.store, kind='opening', quantity=b.quantity,
                                         balance_after=ph.location_balance(b.medication, b.store), unit_cost=b.unit_cost,
                                         reference='LEDGER-START', note='Balance when the stock ledger started', actor=actor)
        for x in self.meds:
            m, daily = x['m'], x['daily']
            short = self.rng.random() < .1                         # a few short-dated batches that will expire during the period
            store_qty = int(daily * self.rng.uniform(25, 45)) + m.reorder_level // 2
            pharm_qty = int(daily * self.rng.uniform(10, 20)) + 5
            if m.name in ('Salbutamol', 'Beclometasone') and m.unit == 'inhaler':
                store_qty, pharm_qty = int(daily * 12), int(daily * 8)    # will run out before the slow supplier delivers
            exp_store = day + timedelta(days=self.rng.randint(300, 720))
            exp_pharm = day + timedelta(days=self.rng.randint(40, 75)) if short else day + timedelta(days=self.rng.randint(180, 540))
            ph.put(self.store, m, self.batch_no(x['sup']), exp_store, store_qty, x['cost'], 'opening', actor, 'OPENING', 'Opening balance', self.sups[x['sup']])
            ph.put(self.pharmacy, m, self.batch_no(x['sup']), exp_pharm, pharm_qty, x['cost'], 'opening', actor, 'OPENING', 'Opening balance', self.sups[x['sup']])
            if self.rng.random() < .25:                            # a near-expiry batch that will still be around at the end
                ph.put(self.store, m, self.batch_no(x['sup']), timezone.localdate() + timedelta(days=self.rng.randint(12, 85)), int(daily * self.rng.uniform(4, 15)) + 2,
                       x['cost'], 'opening', actor, 'OPENING', 'Opening balance', self.sups[x['sup']])
        for loc_name, items in self.ward_items.items():
            for x in items:
                ph.put(self.locs[loc_name], x['m'], self.batch_no(x['sup']), day + timedelta(days=self.rng.randint(120, 400)),
                       max(2, int(x['daily'] * self.rng.uniform(1.5, 4))), x['cost'], 'opening', actor, 'OPENING', 'Opening balance', self.sups[x['sup']])
        self.stamp(since, self.at(day, 7.5))

    def dispense_day(self, day, busy):
        from hospital import pharmacy as ph
        actor = self.rng.choice(self.pharmacists)
        since = self.last_id()
        for x in self.meds:
            m = x['m']
            if m.controlled and m.unit != 'tablet':
                continue                                           # injectable controlled drugs are used on wards, not dispensed to outpatients
            mult = self.season(day) if 'S' in x['flags'] else 1.0
            lam = x['daily'] * busy * mult * .75                   # ~75 % of use is outpatient dispensing
            qty = max(0, int(self.rng.gauss(lam, lam ** .5 * .9)) if lam >= 1 else (1 if self.rng.random() < lam else 0))
            if not qty:
                continue
            have = ph.location_balance(m, self.pharmacy, usable_only=True)
            give = min(qty, have)
            if give < qty:
                self.stockout_days += 1
            if give:
                witness = self.witness_for(actor) if m.controlled else None
                ph.take(m, self.pharmacy, give, 'dispense', actor, 'OPD', f'Outpatient prescriptions ({max(1, give // 15)})', witness,
                        self.rng.choice(self.patients) if m.controlled and self.patients else None)
        self.stamp(since, self.at(day, 18))

    def ward_use_day(self, day):
        from hospital import pharmacy as ph
        for loc_name, items in self.ward_items.items():
            loc = self.locs[loc_name]
            actor = self.rng.choice(self.nurses)
            since = self.last_id()
            for x in items:
                if self.rng.random() > .65:
                    continue
                mult = self.season(day) if 'S' in x['flags'] else 1.0
                share = .25 / max(1, sum(1 for its in self.ward_items.values() if x in its))
                lam = x['daily'] * share * mult * 1.6
                qty = int(lam) + (1 if self.rng.random() < lam % 1 else 0)
                have = ph.location_balance(x['m'], loc, usable_only=True)
                qty = min(qty, have)
                if qty > 0:
                    w = self.witness_for(actor) if x['m'].controlled else None
                    ph.take(x['m'], loc, qty, 'ward_use', actor, loc_name[:12].upper(), 'Given to inpatients', w,
                            self.rng.choice(self.patients) if x['m'].controlled and self.patients else None)
            self.stamp(since, self.at(day, self.rng.uniform(19, 22)))

    def ward_requisitions(self, day):
        """Each ward tops its cupboard back up to about a week's worth."""
        from hospital import pharmacy as ph
        from hospital.models import Requisition, RequisitionLine
        for loc_name, items in self.ward_items.items():
            loc = self.locs[loc_name]
            lines = []
            for x in items:
                par = max(4, int(x['daily'] * .4 * 7))
                have = ph.location_balance(x['m'], loc, usable_only=True)
                if have < par * .6:
                    lines.append((x, par - have))
            if not lines:
                continue
            nurse, pharm = self.rng.choice(self.nurses), self.rng.choice(self.pharmacists)
            req = Requisition.objects.create(supply_from=self.pharmacy, deliver_to=loc, requested_by=nurse, status='approved', approved_by=pharm,
                                             priority='urgent' if self.rng.random() < .12 else 'routine')
            for x, q in lines:
                RequisitionLine.objects.create(requisition=req, medication=x['m'], requested=q, approved=q)
            since = self.last_id()
            qty = {}
            for l in req.lines.select_related('medication'):
                qty[l.pk] = min(l.approved, ph.location_balance(l.medication, self.pharmacy, usable_only=True))
            try:
                ph.issue_requisition(req, pharm, qty, self.witness_for(pharm))
                req.refresh_from_db()
            except ValidationError:
                pass
            if req.status != 'issued':     # what the pharmacy did not have is not carried over: the ward is told and asks again next week
                req.status = 'issued' if req.issued_by_id else 'rejected'
                req.notes = 'Part issued: the rest was out of stock' if req.issued_by_id else 'Rejected: out of stock at the pharmacy'
                req.save(update_fields=['status', 'notes'])
            self.stamp(since, self.at(day, 11), req)
            for l in req.lines.all():
                type(l).objects.filter(pk=l.pk).update(created_at=self.at(day, 9))

    def restock_pharmacy(self, day):
        """Move stock from the central store to the dispensing pharmacy: keep about two weeks of outpatient use on the shelf."""
        from hospital import pharmacy as ph
        from hospital.models import Requisition, RequisitionLine
        lines = []
        for x in self.meds:
            target = int(x['daily'] * .75 * 14 * (self.season(day) if 'S' in x['flags'] else 1)) + 3
            have = ph.location_balance(x['m'], self.pharmacy, usable_only=True)
            avail = ph.location_balance(x['m'], self.store, usable_only=True)
            if have < target * .5 and avail:
                lines.append((x, min(avail, target - have)))
        if not lines:
            return
        pharm = self.rng.choice(self.pharmacists)
        req = Requisition.objects.create(supply_from=self.store, deliver_to=self.pharmacy, requested_by=pharm, status='approved', approved_by=self.storekeeper,
                                         notes='Pharmacy shelf top-up')
        for x, q in lines:
            RequisitionLine.objects.create(requisition=req, medication=x['m'], requested=q, approved=q)
        since = self.last_id()
        ph.issue_requisition(req, self.storekeeper, {l.pk: l.approved for l in req.lines.all()}, self.witness_for(self.storekeeper))
        self.stamp(since, self.at(day, 8.5), req)

    def purchase(self, day):
        """Order what has fallen to its reorder level, one order per supplier; delivery arrives after the lead time."""
        from hospital import pharmacy as ph
        from hospital.models import PurchaseOrder, PurchaseOrderLine
        need = defaultdict(list)
        for x in self.meds:
            m = x['m']
            total = ph.location_balance(m, self.store, True) + ph.location_balance(m, self.pharmacy, True)
            if total + self.on_order[m.pk] <= m.reorder_level:
                qty = max(m.target_level - total, m.reorder_level)
                qty = -(-qty // m.pack_size) * m.pack_size if m.pack_size > 1 else qty
                need[x['sup']].append((x, qty))
        for sup_key, lines in need.items():
            sup = self.sups[sup_key]
            po = PurchaseOrder.objects.create(supplier=sup, status='sent', funding='programme' if sup_key == 'programme' else 'emergency' if sup_key == 'banjul' else 'budget',
                                              deliver_to=self.store, created_by=self.rng.choice(self.pharmacists), sent_at=self.at(day, 10),
                                              expected_date=day + timedelta(days=sup.lead_time_days))
            for x, q in lines:
                PurchaseOrderLine.objects.create(order=po, medication=x['m'], quantity=q, unit_cost=x['cost'])
                self.on_order[x['m'].pk] += q
            self.stamp(self.last_id(), self.at(day, 10), po)
            delay = sup.lead_time_days + self.rng.randint(-2, 6)
            self.pending_po.append((day + timedelta(days=delay), po))

    def receive_due(self, day):
        from hospital import pharmacy as ph
        today = timezone.localdate()
        for due, po in [p for p in self.pending_po if p[0] <= day]:
            self.pending_po.remove((due, po))
            lines = []
            partial = po.status == 'sent' and self.rng.random() < .15     # sometimes the supplier is short (first delivery only)
            for i, l in enumerate(po.lines.select_related('medication')):
                q = l.outstanding if not (partial and i % 2) else 0
                if not q:
                    continue
                exp = day + timedelta(days=self.rng.randint(360, 900))
                if self.rng.random() < .06:
                    exp = max(today + timedelta(days=self.rng.randint(20, 70)), day + timedelta(days=60))   # short-dated delivery
                lines.append({'line': l, 'quantity': q, 'batch_number': self.batch_no(next(k for k, s in self.sups.items() if s.pk == po.supplier_id)), 'expiry': exp})
                self.on_order[l.medication_id] -= q
            if not lines:
                continue
            since = self.last_id()
            ph.receive_order(po, self.storekeeper, lines)
            self.stamp(since, self.at(day, 13))
            if partial:                                              # the rest comes a week later
                self.pending_po.append((day + timedelta(days=7), po))

    def damaged(self, day):
        from hospital import pharmacy as ph
        from hospital.models import StockBatch
        b = StockBatch.objects.filter(store=self.pharmacy, medication__unit='bottle', quantity__gt=3).order_by('?').first()
        if b:
            since = self.last_id()
            ph.write_off(b, 2, 'damaged', self.rng.choice(self.pharmacists), 'Bottles broken when a shelf collapsed')
            self.stamp(since, self.at(day, 15))

    def expire_writeoff(self, day):
        from hospital import pharmacy as ph
        from hospital.models import StockBatch
        actor = self.rng.choice(self.pharmacists)
        since = self.last_id()
        for b in StockBatch.objects.filter(store=self.pharmacy, quantity__gt=0, expiry__lt=day).select_related('medication')[:6]:
            ph.write_off(b, b.quantity, 'expired', actor, 'Monthly expiry check', self.witness_for(actor) if b.medication.controlled else None)
        self.stamp(since, self.at(day, 16))

    def month_end_count(self, day):
        """A full count of the dispensing pharmacy: most lines agree, a few do not."""
        from hospital import pharmacy as ph
        actor = self.rng.choice(self.pharmacists)
        c = ph.start_count(self.pharmacy, actor, 'Month-end stock take')
        reasons = ['Dispensing not recorded', 'Breakage', 'Found on another shelf', 'Counting error last time']
        for l in c.lines.all():
            l.counted = l.system_quantity
            if l.system_quantity > 5 and self.rng.random() < .12:
                l.counted = max(0, l.system_quantity + self.rng.choice([-1, -1, -2, -3, -5, 1, 2]))
                l.reason = self.rng.choice(reasons)
            l.save(update_fields=['counted', 'reason'])
        since = self.last_id()
        ph.post_count(c, actor)
        self.stamp(since, self.at(day, 17), c)

    # ---------------------------------------------------------------- work in progress at the end
    def finish_state(self):
        from hospital import pharmacy as ph
        from hospital.models import PurchaseOrder, PurchaseOrderLine, Requisition, RequisitionLine, StockBatch
        today = timezone.localdate()
        pharm = self.pharmacists[0]
        # deliveries still due stay as 'sent' or 'partial' orders; add a draft from today's suggestions
        sugg = ph.reorder_suggestions()[:6]
        if sugg:
            po = PurchaseOrder.objects.create(supplier=sugg[0]['m'].default_supplier or self.sups['kombo'], status='draft', deliver_to=self.store, created_by=pharm,
                                              notes='Draft from reorder suggestions · check quantities before sending')
            for s in sugg:
                PurchaseOrderLine.objects.create(order=po, medication=s['m'], quantity=s['suggest'], unit_cost=next(x['cost'] for x in self.meds if x['m'].pk == s['m'].pk))
        # an urgent requisition from Maternity waiting for approval, and an approved one from ICU waiting to be issued
        mat = self.locs['Maternity Ward Stock']
        r = Requisition.objects.create(supply_from=self.pharmacy, deliver_to=mat, requested_by=self.nurses[0], priority='urgent', needed_by=today,
                                       notes='Two eclampsia cases overnight · magnesium sulfate nearly gone')
        for label, q in [('Magnesium sulfate 50%, 10 mL', 20), ('Oxytocin 10 IU/mL', 30), ('Hydralazine 20 mg', 5), ("Ringer's lactate 1 L", 12)]:
            if label in self.by_label:
                RequisitionLine.objects.create(requisition=r, medication=self.by_label[label]['m'], requested=q)
        icu = self.locs['ICU Stock']
        r2 = Requisition.objects.create(supply_from=self.pharmacy, deliver_to=icu, requested_by=self.nurses[-1], status='approved', approved_by=pharm, notes='Weekly top-up')
        for label, q in [('Morphine 10 mg/mL', 10), ('Ceftriaxone 1 g', 20), ('Sodium chloride 0.9%, 1 L', 24), ('Adrenaline 1 mg/mL', 10)]:
            if label in self.by_label:
                RequisitionLine.objects.create(requisition=r2, medication=self.by_label[label]['m'], requested=q, approved=q)
        # an open stock take on the paediatric ward, half counted
        c = ph.start_count(self.locs['Pediatric Ward Stock'], pharm, 'Quarterly ward check')
        for i, l in enumerate(c.lines.all()):
            if i % 2 == 0:
                l.counted = l.system_quantity - (1 if i % 6 == 0 and l.system_quantity else 0)
                l.reason = 'Used on night shift, not recorded' if l.counted != l.system_quantity else ''
                l.save(update_fields=['counted', 'reason'])
        # a recalled batch held in quarantine
        b = StockBatch.objects.filter(medication__name='Ceftriaxone', store=self.store, quantity__gt=0).order_by('-created_at').first()
        if b:
            ph.set_quarantine(b, True, pharm, 'Supplier recall notice: particles reported in vials from this batch')
