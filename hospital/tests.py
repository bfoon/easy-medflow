import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from .models import (Admission, Allergy, Bed, Department, Encounter, FormDefinition, FormSubmission, LabOrder, LabTest,
                     Medication, Patient, Prescription, QueueTicket, Referral, Signature, StaffProfile, StockBatch,
                     WorkflowDefinition, WorkflowRun)
from .services import availability, prescription_warnings

PW = 'test-only-Pa55word!'


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('bootstrap_hospital', verbosity=0)
        U = get_user_model()
        cls.users = {}
        for role in ['doctor', 'nurse', 'reception', 'lab', 'pharmacy']:
            u = U.objects.create_user(username=role, password=PW)
            StaffProfile.objects.create(user=u, role=role)
            cls.users[role] = u
        cls.dept = Department.objects.get(name='Outpatient')
        cls.patient = Patient.objects.create(first_name='Awa', last_name='Jallow', dob=date(1990, 1, 1), sex='F')
        cls.med = Medication.objects.get(name='Amoxicillin')
        StockBatch.objects.create(medication=cls.med, batch_number='A1', expiry=date.today() + timedelta(days=30), quantity=5)
        StockBatch.objects.create(medication=cls.med, batch_number='A2', expiry=date.today() + timedelta(days=90), quantity=50)

    def as_(self, role):
        self.client.login(username=role, password=PW)
        return self.client

    def encounter(self):
        return Encounter.objects.create(patient=self.patient, department=self.dept, reason='Fever', clinician=self.users['doctor'])


class SafetySupportTests(Base):
    def test_exact_name_warning(self):
        Allergy.objects.create(patient=self.patient, substance='amoxicillin', reaction='rash', severity='severe')
        w = prescription_warnings(self.encounter(), self.med, 5)
        self.assertEqual(len(w['possible_allergy_matches']), 1)

    def test_expired_stock_is_not_available(self):
        StockBatch.objects.create(medication=self.med, batch_number='old', expiry=date.today() - timedelta(days=1), quantity=200)
        self.assertEqual(availability(self.med), 55)


class QueueTests(Base):
    def test_ticket_opens_visit_and_moves_through_board(self):
        c = self.as_('reception')
        r = c.post('/queue/new/', {'patient': self.patient.pk, 'department': self.dept.pk, 'priority': 2})
        self.assertRedirects(r, '/queue/')
        t = QueueTicket.objects.get()
        self.assertIsNotNone(t.encounter)               # visit auto-created
        self.assertTrue(t.display_code.startswith('O'))  # short waiting-room code
        h = {'HTTP_X_REQUESTED_WITH': 'fetch'}
        self.assertEqual(c.post(f'/queue/{t.pk}/called/', {'counter': 'Room 3'}, **h).json(), {'ok': True, 'status': 'called'})
        t.refresh_from_db(); self.assertEqual(t.counter, 'Room 3')
        self.assertEqual(c.post(f'/queue/{t.pk}/completed/', **h).status_code, 400)  # can't skip a step
        c.post(f'/queue/{t.pk}/in_service/', **h); c.post(f'/queue/{t.pk}/completed/', **h)
        t.refresh_from_db(); self.assertEqual(t.status, 'completed'); self.assertIsNotNone(t.completed_at)

    def test_display_api_never_exposes_names(self):
        QueueTicket.objects.create(patient=self.patient, encounter=self.encounter(), department=self.dept, status='called')
        body = self.as_('nurse').get('/api/queue/').content.decode()
        self.assertNotIn('Jallow', body)


class PharmacyTests(Base):
    def test_draft_sign_dispense_uses_earliest_expiry(self):
        e = self.encounter()
        r = self.as_('doctor').post('/prescriptions/new/', {'encounter': e.pk, 'medication': self.med.pk, 'directions': '500mg tds', 'quantity': 8, 'allergy_reviewed': 'on'})
        self.assertRedirects(r, '/pharmacy/')
        rx = Prescription.objects.get()
        self.client.post(f'/prescriptions/{rx.pk}/sign/')
        rx.refresh_from_db(); self.assertEqual(rx.state, 'signed')
        self.assertTrue(Signature.objects.filter(prescription=rx).exists())
        self.client.logout(); self.as_('pharmacy').post(f'/prescriptions/{rx.pk}/dispense/')
        rx.refresh_from_db(); self.assertEqual(rx.state, 'dispensed')
        self.assertEqual(StockBatch.objects.get(batch_number='A1').quantity, 0)
        self.assertEqual(StockBatch.objects.get(batch_number='A2').quantity, 47)

    def test_allergy_match_blocks_without_override(self):
        Allergy.objects.create(patient=self.patient, substance='Amoxicillin', reaction='anaphylaxis', severity='severe')
        r = self.as_('doctor').post('/prescriptions/new/', {'encounter': self.encounter().pk, 'medication': self.med.pk, 'directions': 'x', 'quantity': 1, 'allergy_reviewed': 'on'})
        self.assertEqual(r.status_code, 200); self.assertContains(r, 'Possible allergy match')
        self.assertFalse(Prescription.objects.exists())

    def test_nurse_cannot_sign(self):
        rx = Prescription.objects.create(encounter=self.encounter(), medication=self.med, directions='x', quantity=1, allergy_reviewed=True)
        self.assertEqual(self.as_('nurse').post(f'/prescriptions/{rx.pk}/sign/').status_code, 403)


class LabTests(Base):
    def test_full_pipeline(self):
        o = LabOrder.objects.create(encounter=self.encounter(), test=LabTest.objects.get(code='MAL'))
        c = self.as_('lab')
        c.post(f'/labs/{o.pk}/collect/', {'specimen_id': 'S-1'}); c.post(f'/labs/{o.pk}/process/')
        c.post(f'/labs/{o.pk}/result/', {'result': 'Positive', 'abnormal': 'on'}); c.post(f'/labs/{o.pk}/verify/')
        o.refresh_from_db()
        self.assertEqual((o.status, o.specimen_id, o.abnormal, o.verified_by), ('verified', 'S-1', True, self.users['lab']))


class BedTests(Base):
    def test_admit_discharge_clean_cycle(self):
        bed = Bed.objects.filter(state='available').first()
        c = self.as_('nurse')
        c.post('/admissions/new/', {'encounter': self.encounter().pk, 'bed': bed.pk})
        bed.refresh_from_db(); self.assertEqual(bed.state, 'occupied')
        c.post(f'/admissions/{Admission.objects.get().pk}/discharge/')
        bed.refresh_from_db(); self.assertEqual(bed.state, 'cleaning')
        c.post(f'/beds/{bed.pk}/ready/')
        bed.refresh_from_db(); self.assertEqual(bed.state, 'available')


class ReferralTests(Base):
    def test_transitions_enforced(self):
        r = Referral.objects.create(encounter=self.encounter(), destination='EFSTH', reason='Cardiology review')
        c = self.as_('doctor')
        self.assertEqual(c.post(f'/referrals/{r.pk}/completed/').status_code, 400)
        for s in ['sent', 'accepted', 'transferred', 'completed']:
            c.post(f'/referrals/{r.pk}/{s}/')
        r.refresh_from_db(); self.assertEqual(r.status, 'completed'); self.assertIsNotNone(r.completed_at)


class StudioTests(Base):
    def setUp(self):
        get_user_model().objects.create_superuser('root', 'r@example.com', PW)

    def test_builder_form_workflow_and_signature(self):
        c = self.as_('root')
        schema = {'fields': [{'key': 'reason', 'label': 'Reason', 'type': 'textarea', 'required': True},
                             {'key': 'risk', 'label': 'Risk', 'type': 'select', 'options': ['low', 'high']}]}
        r = c.post('/studio/forms/new/', {'name': 'Consent', 'slug': 'consent', 'schema': json.dumps(schema), 'published': 'on'})
        self.assertRedirects(r, '/studio/')
        bad = c.post('/studio/forms/new/', {'name': 'Bad', 'slug': 'bad', 'schema': json.dumps({'fields': [{'key': '1x', 'type': 'nope'}]})})
        self.assertEqual(bad.status_code, 200)
        c.post('/studio/workflows/new/', {'name': 'Two step', 'steps': json.dumps([{'name': 'Check', 'role': 'nurse'}, {'name': 'Approve', 'role': 'doctor'}]), 'active': 'on'})
        f, wf = FormDefinition.objects.get(slug='consent'), WorkflowDefinition.objects.get()
        c.post(f'/studio/forms/{f.pk}/fill/{self.patient.pk}/', {'reason': 'Surgery', 'risk': 'low', 'workflow': wf.pk})
        run = WorkflowRun.objects.get()
        self.client.logout(); self.as_('doctor').post(f'/studio/runs/{run.pk}/approve/')  # wrong role for step 1
        run.refresh_from_db(); self.assertEqual(run.step_index, 0)
        self.client.logout(); self.as_('nurse').post(f'/studio/runs/{run.pk}/approve/')
        self.client.logout(); self.as_('doctor').post(f'/studio/runs/{run.pk}/approve/')
        run.refresh_from_db(); self.assertEqual(run.status, 'approved')
        sub = FormSubmission.objects.get()
        self.client.post(f'/studio/submissions/{sub.pk}/sign/')
        sig = Signature.objects.get(submission=sub)
        self.assertEqual(len(sig.document_hash), 64)


class PageTests(Base):
    def test_every_page_renders_for_superuser(self):
        get_user_model().objects.create_superuser('root', 'r@example.com', PW)
        c = self.as_('root'); e = self.encounter()
        for url in ['/', '/patients/', f'/patients/{self.patient.pk}/', f'/encounters/{e.pk}/', '/queue/', '/queue/display/',
                    '/labs/', '/pharmacy/', '/beds/', '/referrals/', '/attendance/', '/studio/', '/studio/forms/new/',
                    '/studio/workflows/new/', '/encounters/new/', '/prescriptions/new/', '/api/pulse/']:
            self.assertEqual(c.get(url).status_code, 200, url)

    def test_reception_blocked_from_pharmacy_actions(self):
        self.assertEqual(self.as_('reception').get('/prescriptions/new/').status_code, 403)
