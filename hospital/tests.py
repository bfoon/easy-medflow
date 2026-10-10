import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from .models import (LabRequest, PrescriptionItem, LabParameter, LabResultValue, Admission, Allergy, Bed, Department, Encounter, FormDefinition, FormSubmission, LabOrder, LabTest,
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
    def rx_post(self, e, lines, **extra):
        data = {'encounter': e.pk, 'allergy_reviewed': 'on', 'items-TOTAL_FORMS': len(lines), 'items-INITIAL_FORMS': 0,
                'items-MIN_NUM_FORMS': 1, 'items-MAX_NUM_FORMS': 30, **extra}
        for i, ln in enumerate(lines):
            for k, v in ln.items():
                data[f'items-{i}-{k}'] = v
        return self.as_('doctor').post('/prescriptions/new/', data)

    def test_quantity_is_calculated_from_dose_frequency_and_days(self):
        self.assertEqual(PrescriptionItem.calculate_quantity(1, 'TDS', 5), 15)
        self.assertEqual(PrescriptionItem.calculate_quantity(2, 'QDS', 3), 24)
        self.assertEqual(PrescriptionItem.calculate_quantity(0.5, 'BD', 7), 7)
        self.assertEqual(PrescriptionItem.calculate_quantity(1, 'STAT', 5), 1)
        self.assertIsNone(PrescriptionItem.calculate_quantity(1, 'PRN', 5))

    def test_multi_medicine_prescription_sign_and_dispense(self):
        para = Medication.objects.get(name='Paracetamol')
        StockBatch.objects.create(medication=para, batch_number='P1', expiry=date.today() + timedelta(days=60), quantity=100)
        e = self.encounter()
        r = self.rx_post(e, [{'medication': self.med.pk, 'dose': '500 mg', 'units_per_dose': 1, 'route': 'oral', 'frequency': 'TDS', 'duration_days': 2, 'instructions': 'after food'},
                             {'medication': para.pk, 'units_per_dose': 2, 'route': 'oral', 'frequency': 'QDS', 'duration_days': 3}])
        self.assertRedirects(r, '/pharmacy/')
        rx = Prescription.objects.get()
        items = list(rx.items.order_by('sort_order'))
        self.assertEqual([(i.medication, i.quantity) for i in items], [(self.med, 6), (para, 24)])
        self.assertIn('three times daily for 2 days', items[0].directions)
        self.client.post(f'/prescriptions/{rx.pk}/sign/')
        rx.refresh_from_db(); self.assertEqual(rx.state, 'signed')
        self.client.logout(); self.as_('pharmacy').post(f'/prescriptions/{rx.pk}/dispense/')
        rx.refresh_from_db(); self.assertEqual(rx.state, 'dispensed')
        self.assertEqual(StockBatch.objects.get(batch_number='A1').quantity, 0)   # earliest expiry first
        self.assertEqual(StockBatch.objects.get(batch_number='A2').quantity, 49)
        self.assertEqual(StockBatch.objects.get(batch_number='P1').quantity, 76)

    def test_dispense_is_all_or_nothing(self):
        zinc = Medication.objects.get(name='Zinc sulfate')   # no stock at all
        rx = Prescription.objects.create(encounter=self.encounter(), allergy_reviewed=True, state='signed')
        PrescriptionItem.objects.create(prescription=rx, medication=self.med, frequency='OD', duration_days=2, quantity=2)
        PrescriptionItem.objects.create(prescription=rx, medication=zinc, frequency='OD', duration_days=2, quantity=2)
        self.as_('pharmacy').post(f'/prescriptions/{rx.pk}/dispense/')
        rx.refresh_from_db(); self.assertEqual(rx.state, 'signed')
        self.assertEqual(StockBatch.objects.get(batch_number='A1').quantity, 5)   # nothing taken from the line that was in stock

    def test_when_required_needs_a_quantity(self):
        r = self.rx_post(self.encounter(), [{'medication': self.med.pk, 'units_per_dose': 1, 'route': 'oral', 'frequency': 'PRN', 'duration_days': 3}])
        self.assertEqual(r.status_code, 200); self.assertFalse(Prescription.objects.exists())

    def test_allergy_match_on_any_line_blocks_without_override(self):
        Allergy.objects.create(patient=self.patient, substance='Amoxicillin', reaction='anaphylaxis', severity='severe')
        para = Medication.objects.get(name='Paracetamol')
        lines = [{'medication': para.pk, 'units_per_dose': 1, 'route': 'oral', 'frequency': 'TDS', 'duration_days': 3},
                 {'medication': self.med.pk, 'units_per_dose': 1, 'route': 'oral', 'frequency': 'TDS', 'duration_days': 3}]
        r = self.rx_post(self.encounter(), lines)
        self.assertContains(r, 'Possible allergy match'); self.assertFalse(Prescription.objects.exists())
        self.client.logout()
        self.assertRedirects(self.rx_post(self.encounter(), lines, override_reason='Desensitised; benefit outweighs risk'), '/pharmacy/')

    def test_nurse_cannot_sign(self):
        rx = Prescription.objects.create(encounter=self.encounter(), allergy_reviewed=True)
        PrescriptionItem.objects.create(prescription=rx, medication=self.med, quantity=1)
        self.assertEqual(self.as_('nurse').post(f'/prescriptions/{rx.pk}/sign/').status_code, 403)


class LabTests(Base):
    def test_catalogue_flags_reference_and_critical_limits(self):
        k = LabParameter.objects.get(test__code='RFT', code='K')
        self.assertEqual([k.flag_for(v) for v in ('4.2', '5.5', '3.1', '6.8', '2.1')], ['N', 'H', 'L', 'HH', 'LL'])
        hb = LabParameter.objects.get(test__code='CBC', code='HB')
        self.assertEqual(hb.flag_for('12.8', 'M'), 'L')   # below male range
        self.assertEqual(hb.flag_for('12.8', 'F'), 'N')   # within female range
        rdt = LabParameter.objects.get(test__code='MAL', code='RDT')
        self.assertEqual(rdt.flag_for('Positive · P. falciparum'), 'A')

    def test_one_request_holds_all_tests_for_the_patient(self):
        e = self.encounter()
        rft, cbc = LabTest.objects.get(code='RFT'), LabTest.objects.get(code='CBC')
        self.as_('doctor').post('/labs/new/', {'encounter': e.pk, 'tests': [rft.pk, cbc.pk], 'priority': 'urgent', 'clinical_notes': 'weak'})
        lr = LabRequest.objects.get()
        self.assertEqual((lr.orders.count(), lr.priority, lr.stage), (2, 'urgent', 'ordered'))
        self.client.logout(); c = self.as_('lab')
        c.post(f'/labs/requests/{lr.pk}/collect/', {'specimen_id': 'S-9'})
        self.assertEqual(set(lr.orders.values_list('status', 'specimen_id')), {('collected', 'S-9')})   # one collection for every test
        r = c.post(f'/labs/requests/{lr.pk}/process/'); self.assertRedirects(r, f'/labs/requests/{lr.pk}/results/')
        o_rft, o_cbc = lr.orders.get(test=rft), lr.orders.get(test=cbc)
        data = {f'p_{o_rft.pk}_{p.pk}': v for p, v in zip(rft.parameters.order_by('sort_order'), ['90', '5', '140', '6.9', '100'])}
        data[f'p_{o_cbc.pk}_{cbc.parameters.get(code="HB").pk}'] = '13'     # CBC only partly entered
        c.post(f'/labs/requests/{lr.pk}/results/', {**data, 'action': 'submit'})
        o_rft.refresh_from_db(); o_cbc.refresh_from_db()
        self.assertEqual((o_rft.status, o_cbc.status), ('resulted', 'processing'))   # complete test submitted, partial one kept back
        self.assertEqual(o_rft.values.get(parameter__code='K').flag, 'HH')
        self.assertEqual(lr.stage, 'processing')
        c.post(f'/labs/tests/{o_cbc.pk}/cancel/')
        self.assertEqual(LabRequest.objects.get().stage, 'resulted')
        c.post(f'/labs/requests/{lr.pk}/verify/')
        self.assertEqual(LabRequest.objects.get().stage, 'verified')
        self.assertContains(c.get('/labs/mine/'), lr.number)

    def test_non_numeric_value_rejected(self):
        lr = LabRequest.objects.create(encounter=self.encounter())
        o = LabOrder.objects.create(encounter=lr.encounter, request=lr, test=LabTest.objects.get(code='GLU'), status='processing')
        prm = o.test.parameters.get()
        r = self.as_('lab').post(f'/labs/requests/{lr.pk}/results/', {f'p_{o.pk}_{prm.pk}': 'abc', 'action': 'save'})
        self.assertContains(r, 'Enter a number'); self.assertFalse(o.values.exists())

    def test_insights_page_acknowledge_and_view_preference(self):
        o = LabOrder.objects.create(encounter=self.encounter(), test=LabTest.objects.get(code='TROP'), status='verified')
        prm = o.test.parameters.get()
        v = LabResultValue.objects.create(order=o, parameter=prm, value_number=182, flag=prm.flag_for(182, 'F'))
        self.assertEqual(v.flag, 'HH')
        c = self.as_('doctor')
        page = c.get(f'/patients/{self.patient.pk}/labs/')
        self.assertContains(page, 'id="lab-data"'); self.assertContains(page, 'Troponin I')
        self.assertTrue(c.post(f'/labs/values/{v.pk}/ack/').json()['ok'])
        v.refresh_from_db(); self.assertEqual(v.acknowledged_by, self.users['doctor'])
        c.post('/labs/view/', {'view': 'clean'})
        self.assertEqual(StaffProfile.objects.get(user=self.users['doctor']).lab_view, 'clean')
        self.assertEqual(c.post('/labs/view/', {'view': 'nope'}).status_code, 400)

    def test_reception_cannot_enter_results(self):
        lr = LabRequest.objects.create(encounter=self.encounter())
        LabOrder.objects.create(encounter=lr.encounter, request=lr, test=LabTest.objects.get(code='GLU'), status='processing')
        self.assertEqual(self.as_('reception').get(f'/labs/requests/{lr.pk}/results/').status_code, 403)


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
                    '/studio/workflows/new/', '/encounters/new/', '/prescriptions/new/', '/api/pulse/', '/labs/new/',
                    '/labs/catalog/', f'/patients/{self.patient.pk}/labs/']:
            self.assertEqual(c.get(url).status_code, 200, url)

    def test_reception_blocked_from_pharmacy_actions(self):
        self.assertEqual(self.as_('reception').get('/prescriptions/new/').status_code, 403)
