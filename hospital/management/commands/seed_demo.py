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

from hospital.models import (Admission, Allergy, Attendance, AuditEvent, Bed, Condition, Department, Encounter,
                             FormDefinition, FormSubmission, LabOrder, LabTest, Medication, Patient, Prescription,
                             QueueTicket, Referral, StaffProfile, StockBatch, WorkflowDefinition, WorkflowRun)
from hospital.services import advance_workflow, sign_document

FIRST_F = ['Awa', 'Fatou', 'Isatou', 'Mariama', 'Binta', 'Haddy', 'Ndey', 'Kaddy', 'Aminata', 'Jainaba', 'Sainabou', 'Oumie']
FIRST_M = ['Lamin', 'Ebrima', 'Modou', 'Ousman', 'Alieu', 'Momodou', 'Bakary', 'Sulayman', 'Omar', 'Musa', 'Kebba', 'Yusupha']
LAST = ['Jallow', 'Ceesay', 'Bah', 'Touray', 'Sowe', 'Camara', 'Njie', 'Jobe', 'Sanneh', 'Darboe', 'Faye', 'Manneh', 'Sarr', 'Drammeh']
PLACES = ['Serrekunda', 'Bakau', 'Brikama', 'Banjul', 'Lamin', 'Kololi', 'Farafenni', 'Soma']
REASONS = [('Fever and headache for 3 days', 'Suspected malaria', 'Malaria RDT'), ('Persistent cough', 'Upper respiratory tract infection', 'Complete Blood Count'),
           ('Abdominal pain', 'Gastritis', 'Stool Microscopy'), ('Routine antenatal visit', 'Normal pregnancy, 24 weeks', 'Haemoglobin'),
           ('Diarrhoea and vomiting', 'Acute gastroenteritis', 'Stool Microscopy'), ('Dizziness, high BP reading', 'Hypertension, uncontrolled', 'Renal Function Panel'),
           ('Increased thirst and urination', 'Type 2 diabetes, suspected', 'Blood Glucose'), ('Painful urination', 'Urinary tract infection', 'Urinalysis'),
           ('Fatigue and pallor', 'Iron-deficiency anaemia', 'Haemoglobin'), ('Child with fever', 'Febrile illness, pediatric', 'Malaria RDT')]
RX = {'Suspected malaria': ('Artemether/Lumefantrine', '4 tablets twice daily for 3 days', 24), 'Upper respiratory tract infection': ('Paracetamol', '1 g every 8 hours as needed', 18),
      'Gastritis': ('Paracetamol', '500 mg every 8 hours as needed', 12), 'Acute gastroenteritis': ('ORS', '1 sachet after each loose stool', 10),
      'Hypertension, uncontrolled': ('Amlodipine', '5 mg once daily', 30), 'Type 2 diabetes, suspected': ('Metformin', '500 mg twice daily with meals', 60),
      'Urinary tract infection': ('Amoxicillin', '500 mg three times daily for 7 days', 21), 'Iron-deficiency anaemia': ('Ferrous sulfate', '200 mg twice daily', 60),
      'Febrile illness, pediatric': ('Paracetamol', '15 mg/kg every 6 hours as needed', 10), 'Normal pregnancy, 24 weeks': ('Ferrous sulfate', '200 mg once daily', 30)}
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

        tests = {t.name: t for t in LabTest.objects.all()}
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
                name, directions, qty = RX[dx]
                rx = Prescription.objects.create(encounter=e, medication=meds[name], directions=directions, quantity=qty, state='dispensed', allergy_reviewed=True, signed_by=doctor, signed_at=when)
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
        lab_states = ['ordered', 'ordered', 'collected', 'processing', 'resulted', 'resulted']
        for (e, dx, test), st in zip(open_encs * 2, lab_states):
            lo = LabOrder.objects.create(encounter=e, test=tests[test], status=st, specimen_id=f'SP-{random.randint(100000, 999999)}' if st != 'ordered' else '',
                                         result='Positive for P. falciparum' if st == 'resulted' and 'malaria' in dx.lower() else 'Hb 8.9 g/dL' if st == 'resulted' else '',
                                         reference_range='12–16 g/dL' if st == 'resulted' else '', abnormal=st == 'resulted', resulted_at=now if st == 'resulted' else None)
            LabOrder.objects.filter(pk=lo.pk).update(created_at=now - timedelta(minutes=random.randint(10, 90)))
            audit(doctor, 'create', f'hospital.LabOrder:{lo.pk}', now - timedelta(minutes=random.randint(5, 60)))
        for (e, dx, _), st in zip(open_encs, ['draft', 'signed', 'signed', 'draft', 'signed']):
            name, directions, qty = RX[dx]
            rx = Prescription.objects.create(encounter=e, medication=meds[name], directions=directions, quantity=qty, allergy_reviewed=True)
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
        audit(pharm, 'dispense', 'prescription:1', now - timedelta(minutes=12))
        audit(lab, 'lab_update', 'lab_order:1', now - timedelta(minutes=8))
