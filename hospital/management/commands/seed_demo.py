"""Populate MedFlow with FICTIONAL demo data so every screen has something to show.

Never run against a database that holds real patient information.
"""
import random
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from hospital.models import (LabRequest, PrescriptionItem, LabResultValue, Admission, Allergy, Attendance, AuditEvent, Bed, Condition, Department, Encounter,
                             FormDefinition, FormSubmission, LabOrder, LabTest, Medication, Patient, Prescription,
                             QueueTicket, Referral, StaffProfile, StockBatch, WorkflowDefinition, WorkflowRun)
from hospital.services import advance_workflow, group_orphan_lab_orders, sign_document

FIRST_F = ['Awa', 'Fatou', 'Isatou', 'Mariama', 'Binta', 'Haddy', 'Ndey', 'Kaddy', 'Aminata', 'Jainaba', 'Sainabou', 'Oumie']
FIRST_M = ['Lamin', 'Ebrima', 'Modou', 'Ousman', 'Alieu', 'Momodou', 'Bakary', 'Sulayman', 'Omar', 'Musa', 'Kebba', 'Yusupha']
LAST = ['Jallow', 'Ceesay', 'Bah', 'Touray', 'Sowe', 'Camara', 'Njie', 'Jobe', 'Sanneh', 'Darboe', 'Faye', 'Manneh', 'Sarr', 'Drammeh']
PLACES = ['Serrekunda', 'Bakau', 'Brikama', 'Banjul', 'Lamin', 'Kololi', 'Farafenni', 'Soma']
REASONS = [('Fever and headache for 3 days', 'Suspected malaria', 'MAL'), ('Persistent cough', 'Upper respiratory tract infection', 'CBC'),
           ('Abdominal pain', 'Gastritis', 'STL'), ('Routine antenatal visit', 'Normal pregnancy, 24 weeks', 'HB'),
           ('Diarrhoea and vomiting', 'Acute gastroenteritis', 'STL'), ('Dizziness, high BP reading', 'Hypertension, uncontrolled', 'RFT'),
           ('Increased thirst and urination', 'Type 2 diabetes, suspected', 'GLU'), ('Painful urination', 'Urinary tract infection', 'UA'),
           ('Fatigue and pallor', 'Iron-deficiency anaemia', 'HB'), ('Child with fever', 'Febrile illness, pediatric', 'MAL')]
# Each diagnosis gets a realistic multi-medicine prescription: (medicine, strength, per dose, frequency, days, instructions)
RX = {
    'Suspected malaria': [('Artemether/Lumefantrine', '20/120 mg', 4, 'BD', 3, 'Take with food or milk'), ('Paracetamol', '500 mg', 2, 'TDS', 3, 'For fever')],
    'Upper respiratory tract infection': [('Paracetamol', '500 mg', 2, 'QDS', 5, ''), ('Amoxicillin', '500 mg', 1, 'TDS', 5, 'Complete the course')],
    'Gastritis': [('Paracetamol', '500 mg', 1, 'PRN', 5, 'Not more than 8 tablets in 24 hours')],
    'Acute gastroenteritis': [('ORS', '20.5 g', 1, 'TDS', 3, 'One sachet in 1 litre of clean water'), ('Zinc sulfate', '20 mg', 1, 'OD', 10, '')],
    'Hypertension, uncontrolled': [('Amlodipine', '5 mg', 1, 'OD', 30, 'Take in the morning')],
    'Type 2 diabetes, suspected': [('Metformin', '500 mg', 1, 'BD', 30, 'Take with meals')],
    'Urinary tract infection': [('Amoxicillin', '500 mg', 1, 'TDS', 7, 'Complete the course'), ('Paracetamol', '500 mg', 2, 'PRN', 3, 'For pain')],
    'Iron-deficiency anaemia': [('Ferrous sulfate', '200 mg', 1, 'BD', 30, 'Take with orange juice; may darken stools')],
    'Febrile illness, pediatric': [('Paracetamol', '120 mg/5 mL', 5, 'QDS', 3, 'Dose by weight; 5 mL per dose')],
    'Normal pregnancy, 24 weeks': [('Ferrous sulfate', '200 mg', 1, 'OD', 30, '')],
}
STAFF = [('dr.jallow', 'Fatou', 'Jallow', 'doctor', 'General Medicine'), ('dr.ceesay', 'Lamin', 'Ceesay', 'doctor', 'Emergency'),
         ('nurse.bah', 'Isatou', 'Bah', 'nurse', 'Outpatient'), ('reception.sowe', 'Modou', 'Sowe', 'reception', 'Outpatient'),
         ('lab.touray', 'Awa', 'Touray', 'lab', 'Laboratory'), ('pharm.njie', 'Ebrima', 'Njie', 'pharmacy', 'Pharmacy'),
         ('manager.camara', 'Mariama', 'Camara', 'management', None)]


class Command(BaseCommand):
    help = 'Create fictional demo data (staff, patients, visits, queue, labs, pharmacy, beds, referrals, forms).'

    def add_arguments(self, parser):
        parser.add_argument('--password', default='medflow-demo-2026', help='Password for the demo staff accounts')
        parser.add_argument('--force', action='store_true', help='Allow running when DEBUG is False (never on real data)')
        parser.add_argument('--patients', type=int, default=36)
        parser.add_argument('--if-empty', action='store_true', help='Skip quietly (instead of failing) when patients already exist')

    def handle(self, *args, **o):
        if not settings.DEBUG and not o['force']:
            raise CommandError('Refusing to seed demo data with DEBUG=False. Use --force only on a throwaway database.')
        if Patient.objects.exists():
            if o['if_empty']:
                self.stdout.write('Demo data already present; skipping.')
                return
            raise CommandError('Patients already exist. seed_demo only runs on an empty database.')
        random.seed(7)
        call_command('bootstrap_hospital', verbosity=0)
        with transaction.atomic():
            self.seed(o)
        self.stdout.write(self.style.SUCCESS(
            f"Demo data created. Staff logins (password: {o['password']}): " + ', '.join(s[0] for s in STAFF)))

    def seed(self, o):
        U = get_user_model()
        now = timezone.now()
        depts = {d.name: d for d in Department.objects.all()}
        staff = {}
        for username, fn, ln, role, dept in STAFF:
            u, _ = U.objects.get_or_create(username=username, defaults={'first_name': fn, 'last_name': ln})
            u.set_password(o['password']); u.save()
            StaffProfile.objects.update_or_create(user=u, defaults={'role': role, 'department': depts.get(dept), 'license_number': f'GMC-{random.randint(1000, 9999)}' if role == 'doctor' else ''})
            staff[role] = staff.get(role) or u
        doctor, nurse, lab, pharm = staff['doctor'], staff['nurse'], staff['lab'], staff['pharmacy']
        for u in [doctor, nurse, staff['reception'], lab, pharm]:
            a = Attendance.objects.create(staff=u)
            Attendance.objects.filter(pk=a.pk).update(clock_in=now - timedelta(hours=random.uniform(1, 6)))
        for d in range(1, 6):
            for u in [doctor, nurse, staff['reception']]:
                start = now - timedelta(days=d, hours=random.uniform(0, 2))
                Attendance.objects.create(staff=u, clock_in=start - timedelta(hours=8), clock_out=start)

        # stock: one expired batch to show expiry handling, plus live batches; one item deliberately low
        for m in Medication.objects.all():
            m.reorder_level = 40; m.save(update_fields=['reorder_level'])
            qty = 12 if m.name == 'Ceftriaxone' else 0 if m.name == 'Zinc sulfate' else random.randint(90, 400)
            StockBatch.objects.create(medication=m, batch_number=f'B{random.randint(10000, 99999)}', expiry=date.today() + timedelta(days=random.randint(60, 540)), quantity=qty)
            StockBatch.objects.create(medication=m, batch_number=f'X{random.randint(10000, 99999)}', expiry=date.today() - timedelta(days=10), quantity=50)

        tests = {t.code: t for t in LabTest.objects.all()}
        meds = {m.name: m for m in Medication.objects.all()}
        patients = []
        for i in range(o['patients']):
            female = i % 2 == 0
            p = Patient.objects.create(
                first_name=random.choice(FIRST_F if female else FIRST_M), last_name=random.choice(LAST),
                dob=date.today() - timedelta(days=random.randint(2 * 365, 78 * 365)), sex='F' if female else 'M',
                phone=f'+220 {random.randint(300, 799)} {random.randint(1000, 9999)}', address=f'{random.randint(1, 90)} Kairaba Ave, {random.choice(PLACES)}',
                emergency_contact=f'{random.choice(FIRST_F + FIRST_M)} {random.choice(LAST)} · +220 {random.randint(300, 799)} {random.randint(1000, 9999)}',
                blood_group=random.choice(['O+', 'A+', 'B+', 'O-', 'AB+', '']),
                medical_alerts='Sickle cell disease. Avoid dehydration.' if i == 3 else '')
            Patient.objects.filter(pk=p.pk).update(created_at=now - timedelta(days=random.randint(0, 120)))
            patients.append(p)
            if i % 4 == 0:
                Allergy.objects.create(patient=p, substance=random.choice(['Penicillin', 'Sulfonamides', 'Peanuts', 'Aspirin']), reaction=random.choice(['Rash', 'Hives', 'Swelling', 'Wheeze']), severity=random.choice(['mild', 'moderate', 'severe']), verified_by=nurse)
            if i == 5:
                Allergy.objects.create(patient=p, substance='Amoxicillin', reaction='Anaphylaxis', severity='severe', verified_by=doctor)
            if i % 3 == 0:
                Condition.objects.create(patient=p, name=random.choice(['Hypertension', 'Asthma', 'Type 2 diabetes', 'Sickle cell disease', 'HIV, on ART']), status='active', onset=date.today() - timedelta(days=random.randint(200, 3000)))

        def audit(actor, action, target, when):
            ev = AuditEvent.objects.create(actor=actor, action=action, target=target)
            AuditEvent.objects.filter(pk=ev.pk).update(occurred_at=when)

        # past week of visits (drives the arrivals chart and history)
        for day in range(6, 0, -1):
            for p in random.sample(patients, random.randint(5, 11)):
                reason, dx, test = random.choice(REASONS)
                day_start = timezone.localtime(now).replace(hour=8, minute=0, second=0, microsecond=0) - timedelta(days=day)
                when = day_start + timedelta(minutes=random.randint(0, 9 * 60))
                dept = depts['Pediatrics'] if p.age and p.age < 12 else depts[random.choice(['Outpatient', 'General Medicine', 'Emergency'])]
                e = Encounter.objects.create(patient=p, clinician=doctor, department=dept, reason=reason, symptoms=reason, assessment='Examined. Stable.',
                                             diagnosis=dx, plan='Treat and review in one week if not improving.', status='completed', completed_at=when + timedelta(hours=1),
                                             vitals={'bp': f'{random.randint(105, 160)}/{random.randint(65, 100)}', 'heart_rate': str(random.randint(62, 108)), 'temperature_c': f'{random.uniform(36.3, 39.4):.1f}', 'spo2': str(random.randint(94, 99))})
                t = QueueTicket.objects.create(patient=p, encounter=e, department=dept, priority=random.choice([2, 3, 3, 3, 4]), status='completed')
                Encounter.objects.filter(pk=e.pk).update(created_at=when)
                QueueTicket.objects.filter(pk=t.pk).update(created_at=when, called_at=when + timedelta(minutes=25), completed_at=when + timedelta(minutes=50))
                lo = LabOrder.objects.create(encounter=e, test=tests[test], status='verified', result=random.choice(['Within normal limits', 'Positive', 'Negative', 'Hb 9.8 g/dL']),
                                             reference_range='See lab manual', abnormal=random.random() < .3, verified_by=lab, verified_at=when + timedelta(hours=2), resulted_at=when + timedelta(hours=1, minutes=30))
                LabOrder.objects.filter(pk=lo.pk).update(created_at=when)
                rx = Prescription.objects.create(encounter=e, state='dispensed', allergy_reviewed=True, signed_by=doctor, signed_at=when)
                self.add_items(rx, RX[dx], meds)
                Prescription.objects.filter(pk=rx.pk).update(created_at=when)

        # today: a live waiting room in every state
        today_pts = random.sample(patients, 16)
        states = ['waiting'] * 7 + ['called'] * 2 + ['in_service'] * 3 + ['skipped'] + ['completed'] * 3
        rooms = ['Room 1', 'Room 2', 'Room 3', 'Triage', 'Room 4']
        open_encs = []
        for n, (p, st) in enumerate(zip(today_pts, states)):
            reason, dx, test = REASONS[n % len(REASONS)]
            midnight = timezone.localtime(now).replace(hour=0, minute=1, second=0, microsecond=0)
            when = max(now - timedelta(minutes=random.randint(5, 150)), midnight)
            dept = depts['Pediatrics'] if p.age and p.age < 12 else depts[random.choice(['Outpatient', 'General Medicine', 'Emergency', 'Maternity' if p.sex == 'F' else 'Outpatient'])]
            pri = 1 if n == 0 else 2 if n in (1, 4, 9) else random.choice([3, 3, 4])
            e = Encounter.objects.create(patient=p, clinician=doctor if st in ('in_service', 'completed') else None, department=dept, reason=reason, symptoms=reason,
                                         assessment='Assessment in progress' if st == 'in_service' else '', diagnosis=dx if st in ('in_service', 'completed') else '',
                                         vitals={'bp': f'{random.randint(105, 165)}/{random.randint(65, 102)}', 'heart_rate': str(random.randint(62, 118)), 'temperature_c': f'{random.uniform(36.3, 39.6):.1f}', 'spo2': str(random.randint(92, 99)), 'resp_rate': str(random.randint(14, 24))} if st != 'waiting' else {},
                                         status='completed' if st == 'completed' else 'open')
            t = QueueTicket.objects.create(patient=p, encounter=e, department=dept, priority=pri, status=st,
                                           counter=random.choice(rooms) if st in ('called', 'in_service', 'completed') else '')
            QueueTicket.objects.filter(pk=t.pk).update(created_at=when, called_at=when + timedelta(minutes=20) if st != 'waiting' else None,
                                                       completed_at=when + timedelta(minutes=45) if st == 'completed' else None)
            Encounter.objects.filter(pk=e.pk).update(created_at=when)
            if e.status == 'open' and st != 'waiting':
                open_encs.append((e, dx, test))
            audit(staff['reception'], 'create', f'hospital.QueueTicket:{t.pk}', when)
            if st != 'waiting':
                audit(nurse, 'queue_transition', f'ticket:{t.pk}', when + timedelta(minutes=20))

        # labs across the whole pipeline, prescriptions in every state
        bundles = [(['CBC', 'MAL', 'GLU'], 'ordered', 'urgent'), (['RFT', 'LFT', 'CRP'], 'collected', 'routine'), (['UA', 'CRP'], 'processing', 'routine'),
                   (['CBC', 'HB', 'MPS'], 'resulted', 'urgent'), (['LIPID', 'HBA1C', 'GLU'], 'ordered', 'routine')]
        for (e, dx, _), (codes, st, prio) in zip(open_encs, bundles):
            created = now - timedelta(minutes=random.randint(10, 90)); spec = f'SP-{random.randint(100000, 999999)}' if st != 'ordered' else ''
            lr = LabRequest.objects.create(encounter=e, requested_by=doctor, priority=prio, specimen_id=spec,
                                           clinical_notes=f'{dx}.' if prio == 'urgent' else '', collected_at=created if spec else None)
            LabRequest.objects.filter(pk=lr.pk).update(created_at=created)
            for code in codes:
                lo = LabOrder.objects.create(encounter=e, request=lr, test=tests[code], status=st, specimen_id=spec, resulted_at=now if st == 'resulted' else None)
                LabOrder.objects.filter(pk=lo.pk).update(created_at=created)
            audit(doctor, 'create', f'hospital.LabRequest:{lr.pk}', created)
        for (e, dx, _), st in zip(open_encs, ['draft', 'signed', 'signed', 'draft', 'signed']):
            rx = Prescription.objects.create(encounter=e, allergy_reviewed=True)
            self.add_items(rx, RX[dx], meds)
            if st == 'signed':
                rx.state = 'signed'; rx.signed_by = doctor; rx.signed_at = now; rx.save()
                sign_document('prescription', rx, doctor, 'Prescriber authorization')

        # admissions: fill some beds, leave a couple cleaning and one in maintenance
        beds = list(Bed.objects.select_related('ward').order_by('code'))
        pool = [p for p in patients if p not in today_pts]
        def fits(bed, p):
            if bed.kind == 'maternity': return p.sex == 'F' and p.age and 16 <= p.age <= 45
            if bed.kind == 'pediatric': return p.age is not None and p.age < 14
            return p.age is None or p.age >= 14
        pairs = []
        for bed in [b for b in beds if b.code.endswith(('01', '02', '04', '05', '07'))]:
            p = next((x for x in pool if fits(bed, x)), None)
            if p: pool.remove(p); pairs.append((bed, p))
        for bed, p in pairs:
            e = Encounter.objects.create(patient=p, clinician=doctor, department=depts['General Medicine'], reason='Admitted for observation and treatment', diagnosis=random.choice(['Severe malaria', 'Pneumonia', 'Pre-eclampsia', 'Dehydration', 'Sickle cell crisis']), status='open')
            a = Admission.objects.create(encounter=e, bed=bed)
            Admission.objects.filter(pk=a.pk).update(admitted_at=now - timedelta(days=random.randint(0, 6), hours=random.randint(1, 20)))
            bed.state = 'occupied'; bed.save(update_fields=['state'])
        for b in [b for b in beds if b.state == 'available'][:3]:
            b.state = 'cleaning'; b.save(update_fields=['state'])
        icu = [b for b in beds if b.kind == 'icu' and b.state == 'available']
        if icu:
            icu[-1].state = 'maintenance'; icu[-1].save(update_fields=['state'])

        # referrals at every stage
        ref_specs = [('Edward Francis Small Teaching Hospital', 'Cardiology', 'urgent', 'sent'), ('Bundung Maternal & Child Health Hospital', 'Obstetrics', 'emergency', 'accepted'),
                     ('Sheikh Zayed Regional Eye Care Centre', 'Ophthalmology', 'routine', 'draft'), ('Africmed Clinic', 'Orthopaedics', 'routine', 'transferred'),
                     ('Medical Research Council Unit', 'Infectious disease', 'urgent', 'completed'), ('Serrekunda General Hospital', 'Surgery', 'routine', 'declined')]
        for (e, dx, _), (dest, spec, urg, st) in zip(open_encs * 2, ref_specs):
            Referral.objects.create(encounter=e, destination=dest, speciality=spec, urgency=urg, status=st, reason=f'{dx}: specialist review requested.',
                                    contact='+220 422 8223', accepted_by='Duty registrar' if st in ('accepted', 'transferred', 'completed') else '',
                                    sent_at=now if st != 'draft' else None, completed_at=now if st == 'completed' else None)

        # forms studio: two forms, one workflow, submissions in different states
        triage = FormDefinition.objects.create(name='Triage assessment', slug='triage-assessment', published=True, schema={'fields': [
            {'key': 'chief_complaint', 'label': 'Chief complaint', 'type': 'textarea', 'required': True},
            {'key': 'pain_score', 'label': 'Pain score (0–10)', 'type': 'number', 'required': True},
            {'key': 'category', 'label': 'Triage category', 'type': 'select', 'options': ['Emergency', 'Urgent', 'Standard', 'Non-urgent'], 'required': True},
            {'key': 'pregnant', 'label': 'Possibly pregnant', 'type': 'checkbox'}]})
        consent = FormDefinition.objects.create(name='Procedure consent', slug='procedure-consent', published=True, schema={'fields': [
            {'key': 'procedure', 'label': 'Procedure', 'type': 'text', 'required': True},
            {'key': 'risks_explained', 'label': 'Risks explained to patient', 'type': 'checkbox'},
            {'key': 'date', 'label': 'Planned date', 'type': 'date', 'required': True}]})
        FormDefinition.objects.create(name='Discharge summary', slug='discharge-summary', published=False, schema={'fields': [
            {'key': 'summary', 'label': 'Clinical summary', 'type': 'textarea', 'required': True}]})
        wf = WorkflowDefinition.objects.create(name='Consent sign-off', steps=[{'name': 'Nurse check', 'role': 'nurse'}, {'name': 'Physician approval', 'role': 'doctor'}])
        for n, p in enumerate(patients[:5]):
            defn = consent if n % 2 else triage
            vals = {'procedure': 'Wound debridement', 'risks_explained': True, 'date': str(date.today())} if defn == consent else {'chief_complaint': 'Fever', 'pain_score': '4', 'category': 'Standard', 'pregnant': False}
            s = FormSubmission.objects.create(definition=defn, patient=p, values=vals, schema_snapshot=defn.schema, submitted_by=nurse)
            if defn == consent:
                run = WorkflowRun.objects.create(definition=wf, submission=s)
                if n == 3:
                    advance_workflow(run, nurse, 'approve', 'Checked with patient')
            elif n == 0:
                sign_document('form', s, doctor, 'Reviewed and signed')
            audit(nurse, 'submit_form', f'form_submission:{s.pk}', now - timedelta(minutes=30 + n * 7))
        self.structured_results(now, doctor, lab, depts, tests, staff)
        audit(pharm, 'dispense', 'prescription:1', now - timedelta(minutes=12))
        audit(lab, 'lab_update', 'lab_order:1', now - timedelta(minutes=8))


    # ------------------------------------------------------------------ structured lab values
    @staticmethod
    def fill(order, tech, overrides=None, abnormal_rate=0.2):
        """Give every parameter of an order a plausible value, flagged against the catalogue's limits."""
        overrides = overrides or {}
        sex = order.encounter.patient.sex
        for prm in order.test.parameters.all():
            if prm.code in overrides:
                val = overrides[prm.code]
            elif prm.kind == 'choice':
                ok = [c for c in prm.choices if c not in prm.abnormal_choices] or prm.choices
                val = random.choice(prm.abnormal_choices) if prm.abnormal_choices and random.random() < abnormal_rate / 2 else ok[0]
            elif prm.kind == 'text':
                val = 'No abnormality seen'
            else:
                lo, hi = prm.range_for(sex)
                lo = float(lo) if lo is not None else (float(hi) * .4 if hi is not None else 1.0)
                hi = float(hi) if hi is not None else lo * 1.8
                v = random.uniform(lo + (hi - lo) * .1, hi - (hi - lo) * .1)
                if random.random() < abnormal_rate:
                    v = hi * random.uniform(1.08, 1.35) if random.random() < .6 else lo * random.uniform(.7, .92)
                val = round(v, prm.decimals)
            num = val if prm.kind == 'number' else None
            LabResultValue.objects.update_or_create(order=order, parameter=prm, defaults={
                'value_number': num, 'value_text': '' if num is not None else str(val), 'flag': prm.flag_for(val, sex), 'entered_by': tech})
        order.abnormal = order.values.exclude(flag__in=['', 'N']).exists()
        order.result = ''
        order.performed_by = tech
        order.save(update_fields=['abnormal', 'result', 'performed_by'])

    def structured_results(self, now, doctor, lab, depts, tests, staff):
        meds = {m.name: m for m in Medication.objects.all()}
        for o in LabOrder.objects.filter(status__in=['resulted', 'verified']).select_related('test', 'encounter__patient'):
            self.fill(o, lab)
        LabOrder.objects.filter(status__in=['collected', 'processing']).update(performed_by=lab)

        # Featured demo patient: an evolving cardiac emergency with history, so the body map and trends have a story.
        p = Patient.objects.create(first_name='Babucarr', last_name='Sowe', dob=date.today() - timedelta(days=58 * 365 + 40), sex='M',
                                   phone='+220 712 4408', address='14 Kairaba Ave, Serrekunda', blood_group='A+',
                                   emergency_contact='Isatou Sowe · +220 712 4409', medical_alerts='Type 2 diabetes. Hypertension.')
        Condition.objects.create(patient=p, name='Type 2 diabetes', status='active', onset=date.today() - timedelta(days=2200))
        Condition.objects.create(patient=p, name='Hypertension', status='active', onset=date.today() - timedelta(days=1500))

        def visit(days_ago, reason, dx, status='completed'):
            e = Encounter.objects.create(patient=p, clinician=doctor, department=depts['Emergency' if days_ago < 3 else 'General Medicine'],
                                         reason=reason, diagnosis=dx, status=status, symptoms=reason,
                                         vitals={'bp': '168/98', 'heart_rate': '104', 'temperature_c': '36.9', 'spo2': '94', 'resp_rate': '22'} if days_ago < 3 else {'bp': '148/92', 'heart_rate': '82'})
            Encounter.objects.filter(pk=e.pk).update(created_at=now - timedelta(days=days_ago))
            return e

        def result(e, code, hours_ago, values, status='verified', ack=False):
            o = LabOrder.objects.create(encounter=e, test=tests[code], status=status, specimen_id=f'SP-{random.randint(100000, 999999)}',
                                        resulted_at=now - timedelta(hours=hours_ago), verified_by=lab if status == 'verified' else None,
                                        verified_at=now - timedelta(hours=hours_ago - .5) if status == 'verified' else None)
            LabOrder.objects.filter(pk=o.pk).update(created_at=now - timedelta(hours=hours_ago + 1))
            o.refresh_from_db(); self.fill(o, lab, values, abnormal_rate=0)
            if ack:
                o.values.exclude(flag__in=['', 'N']).update(acknowledged_by=doctor, acknowledged_at=now - timedelta(hours=hours_ago - 1))
            return o

        # routine diabetes reviews over the past year: HbA1c improving, lipids high
        for months, a1c, glu in [(11, 9.1, 9.8), (7, 8.4, 8.6), (3, 7.6, 7.4)]:
            e = visit(months * 30, 'Diabetes review', 'Type 2 diabetes, suboptimal control')
            result(e, 'HBA1C', months * 30 * 24, {'A1C': a1c}, ack=True)
            result(e, 'GLU', months * 30 * 24, {'FBG': glu}, ack=True)
            result(e, 'RFT', months * 30 * 24, {'CREA': [98, 104, 112][[11, 7, 3].index(months)], 'K': 4.6, 'NA': 139, 'UREA': 6.2, 'CL': 101}, ack=True)
        e = visit(90, 'Lipid check', 'Dyslipidaemia')
        result(e, 'LIPID', 90 * 24, {'TC': 6.4, 'LDL': 4.3, 'HDL': 0.9, 'TG': 2.4}, ack=True)

        # today: chest pain → serial troponins rising past the critical limit, high potassium, raised BNP
        now_e = visit(0, 'Central chest pain radiating to left arm, 2 hours', 'Suspected acute coronary syndrome', status='open')
        result(now_e, 'TROP', 6, {'TNI': 48}, ack=True)
        result(now_e, 'TROP', 3, {'TNI': 96})
        result(now_e, 'TROP', 0.5, {'TNI': 182}, status='resulted')
        result(now_e, 'CARD', 3, {'CKMB': 41, 'BNP': 640})
        result(now_e, 'RFT', 3, {'CREA': 141, 'UREA': 9.4, 'NA': 137, 'K': 6.4, 'CL': 103})
        result(now_e, 'CBC', 3, {'HB': 14.2, 'WBC': 12.6, 'PLT': 248, 'RBC': 4.9, 'HCT': 43, 'MCV': 88})
        result(now_e, 'GLU', 3, {'FBG': 11.8})
        result(now_e, 'LFT', 3, {'ALT': 64, 'AST': 92, 'ALP': 98, 'TBIL': 14, 'ALB': 41})
        result(now_e, 'ABG', 2, {'PH': 7.33, 'PCO2': 4.4, 'PO2': 9.6, 'HCO3': 21, 'SAO2': 93})
        LabOrder.objects.create(encounter=now_e, test=tests['TFT'])
        t = QueueTicket.objects.create(patient=p, encounter=now_e, department=depts['Emergency'], priority=1, status='in_service', counter='Resus')
        QueueTicket.objects.filter(pk=t.pk).update(created_at=now - timedelta(minutes=70), called_at=now - timedelta(minutes=66), started_at=now - timedelta(minutes=60))
        LabOrder.objects.create(encounter=now_e, test=tests['HBA1C'])
        # group everything into per-patient requests; the featured patient's current requests are STAT
        group_orphan_lab_orders()
        LabRequest.objects.filter(encounter=now_e).update(priority='stat', requested_by=doctor, clinical_notes='Central chest pain 2 h, query ACS. Diabetic.')
        LabRequest.objects.filter(requested_by__isnull=True).update(requested_by=doctor)
        for lr in LabRequest.objects.prefetch_related('orders'):
            spec = next((o.specimen_id for o in lr.orders.all() if o.specimen_id), '')
            if spec and not lr.specimen_id:
                lr.specimen_id = spec; lr.save(update_fields=['specimen_id'])
        rx = Prescription.objects.create(encounter=now_e, allergy_reviewed=True, notes='Chest pain protocol. Review after cardiology input.')
        self.add_items(rx, [('Paracetamol', '500 mg', 2, 'PRN', 2, 'For pain; not more than 8 tablets in 24 hours'),
                            ('Amlodipine', '5 mg', 1, 'OD', 30, 'Continue usual dose'), ('Metformin', '500 mg', 1, 'BD', 30, 'Withhold if fasting for procedures')], meds)
        self.featured = p

    @staticmethod
    def add_items(rx, lines, meds):
        for i, (name, dose, per, freq, days, note) in enumerate(lines):
            qty = PrescriptionItem.calculate_quantity(per, freq, days) or per * 8
            PrescriptionItem.objects.create(prescription=rx, medication=meds[name], dose=dose, units_per_dose=per, frequency=freq,
                                            duration_days=days, quantity=qty, instructions=note, sort_order=i)
