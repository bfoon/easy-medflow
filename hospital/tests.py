from django.utils import timezone
from decimal import Decimal
import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from .models import (Allergy, Invoice, Payment, Admission, Bed, NetworkFacility, ReferralTask, Specialist, SpecialistSlot, ImagingOrder, StockRequest, LabRequest, PrescriptionItem, LabParameter, LabResultValue, Admission, Allergy, Bed, Department, Encounter, FormDefinition, FormSubmission, LabOrder, LabTest,
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
        rx = Prescription.objects.get()
        self.assertRedirects(r, f'/prescriptions/{rx.pk}/')
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
        r = self.rx_post(self.encounter(), lines, override_reason='Desensitised; benefit outweighs risk')
        self.assertRedirects(r, f'/prescriptions/{Prescription.objects.get().pk}/')

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


class StayOnPageAndDetailTests(Base):
    def test_forms_opened_in_the_panel_close_themselves_after_saving(self):
        e = self.encounter()
        r = self.as_('doctor').post('/labs/new/?embed=1', {'encounter': e.pk, 'tests': [LabTest.objects.get(code='CBC').pk]})
        self.assertContains(r, 'medflow:done')                 # tells the patient page to close the panel and refresh
        self.assertEqual(LabRequest.objects.count(), 1)
        page = self.client.get(f'/prescriptions/new/?encounter={e.pk}&embed=1')
        self.assertNotContains(page, 'class="rail"')            # no navigation chrome inside the panel

    def test_detail_pages_open(self):
        e = self.encounter()
        lr = LabRequest.objects.create(encounter=e)
        LabOrder.objects.create(encounter=e, request=lr, test=LabTest.objects.get(code='GLU'))
        rx = Prescription.objects.create(encounter=e, allergy_reviewed=True)
        PrescriptionItem.objects.create(prescription=rx, medication=self.med, quantity=3)
        c = self.as_('doctor')
        self.assertContains(c.get(f'/labs/requests/{lr.pk}/'), 'Blood Glucose')
        self.assertContains(c.get(f'/prescriptions/{rx.pk}/'), 'Amoxicillin')
        self.assertEqual(c.get(f'/prescriptions/{rx.pk}/edit/').status_code, 200)

    def test_completing_a_visit_records_the_outcome(self):
        e = self.encounter()
        self.as_('doctor').post(f'/encounters/{e.pk}/complete/', {'outcome': 'improved'})
        e.refresh_from_db(); self.assertEqual((e.status, e.outcome), ('completed', 'improved'))


class OutOfStockTests(Base):
    def setUp(self):
        self.zinc = Medication.objects.get(name='Zinc sulfate')   # no stock
        self.rx = Prescription.objects.create(encounter=self.encounter(), allergy_reviewed=True, state='signed')
        self.ok = PrescriptionItem.objects.create(prescription=self.rx, medication=self.med, frequency='OD', duration_days=2, quantity=2)
        self.short = PrescriptionItem.objects.create(prescription=self.rx, medication=self.zinc, frequency='OD', duration_days=10, quantity=10)

    def test_inform_patient_then_dispense_the_rest(self):
        c = self.as_('pharmacy')
        c.post(f'/prescriptions/items/{self.short.pk}/unavailable/', {'note': 'Buy at a community pharmacy'})
        self.short.refresh_from_db()
        self.assertEqual(self.short.availability, 'unavailable'); self.assertIsNotNone(self.short.patient_informed_at)
        c.post(f'/prescriptions/{self.rx.pk}/dispense/')
        self.rx.refresh_from_db(); self.assertEqual(self.rx.state, 'dispensed')
        self.assertEqual(self.ok.dispensed_quantity, 2)
        self.assertContains(c.get(f'/prescriptions/{self.rx.pk}/'), 'Medicines to obtain elsewhere')   # printable patient note

    def test_order_from_supplier_partial_dispense_then_receive(self):
        c = self.as_('pharmacy')
        c.post(f'/prescriptions/items/{self.short.pk}/order/')
        sr = StockRequest.objects.get(); self.assertEqual((sr.medication, sr.prescription_item), (self.zinc, self.short))
        c.post(f'/prescriptions/{self.rx.pk}/dispense/')
        self.rx.refresh_from_db(); self.assertEqual(self.rx.state, 'partial')          # in-stock line dispensed, ordered line waits
        c.post(f'/pharmacy/supplier/{sr.pk}/receive/', {'batch_number': 'Z1', 'expiry': (date.today() + timedelta(days=200)).isoformat(), 'quantity': 50})
        self.short.refresh_from_db(); self.assertEqual(self.short.availability, '')
        c.post(f'/prescriptions/{self.rx.pk}/dispense/')
        self.rx.refresh_from_db(); self.assertEqual(self.rx.state, 'dispensed')
        self.assertEqual(StockBatch.objects.get(batch_number='Z1').quantity, 40)

    def test_unhandled_shortage_blocks_dispensing(self):
        self.as_('pharmacy').post(f'/prescriptions/{self.rx.pk}/dispense/')
        self.rx.refresh_from_db(); self.assertEqual(self.rx.state, 'signed')
        self.assertEqual(StockBatch.objects.get(batch_number='A1').quantity, 5)


class ImagingTests(Base):
    def setUp(self):
        import shutil, tempfile
        from django.test import override_settings
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.override = override_settings(MEDIA_ROOT=self.tmp); self.override.enable(); self.addCleanup(self.override.disable)
        U = get_user_model(); u = U.objects.create_user(username='rad', password=PW); StaffProfile.objects.create(user=u, role='radiology')

    def test_request_upload_report_and_show_on_body_map(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from hospital import demo_images
        e = self.encounter()
        self.as_('doctor').post('/imaging/new/', {'encounter': e.pk, 'modality': 'xray', 'region': 'Chest PA', 'body_system': 'lungs', 'priority': 'urgent'})
        o = ImagingOrder.objects.get(); self.client.logout(); c = self.as_('rad')
        c.post(f'/imaging/{o.pk}/upload/', {'images': SimpleUploadedFile('chest.png', demo_images.chest_xray(), content_type='image/png')})
        c.post(f'/imaging/{o.pk}/upload/', {'images': SimpleUploadedFile('evil.png', b'<script>alert(1)</script>', content_type='image/png')})
        self.assertEqual(o.images.count(), 1)                                                      # renamed non-image rejected
        o.refresh_from_db(); self.assertEqual(o.status, 'acquired')
        c.post(f'/imaging/{o.pk}/report/', {'findings': 'Big heart', 'impression': 'Cardiomegaly', 'action': 'final',
                                            'measurements': json.dumps([{'label': 'CTR', 'value': '0.6', 'abnormal': True}])})
        o.refresh_from_db(); self.assertEqual((o.status, o.abnormal), ('reported', True))
        img = o.images.get()
        self.assertEqual(c.get(f'/imaging/files/{img.pk}/')['Content-Type'], 'image/png')
        self.client.logout()
        self.assertEqual(self.client.get(f'/imaging/files/{img.pk}/').status_code, 302)              # never public
        page = self.as_('doctor').get(f'/patients/{self.patient.pk}/labs/')
        self.assertContains(page, 'Cardiomegaly')

    def test_reception_cannot_upload(self):
        o = ImagingOrder.objects.create(encounter=self.encounter(), modality='xray', region='Chest', body_system='lungs')
        self.assertEqual(self.as_('reception').post(f'/imaging/{o.pk}/upload/').status_code, 403)


class SimilarCasesTests(Base):
    def make_case(self, sex, dx, med, outcome):
        p = Patient.objects.create(first_name='Case', last_name=f'Person{Patient.objects.count()}', dob=date(1985, 5, 5), sex=sex)
        e = Encounter.objects.create(patient=p, reason='x', diagnosis=dx, status='completed', outcome=outcome)
        rx = Prescription.objects.create(encounter=e, allergy_reviewed=True, state='dispensed')
        PrescriptionItem.objects.create(prescription=rx, medication=Medication.objects.get(name=med), quantity=6)
        return e

    def test_groups_are_anonymous_and_small_groups_hidden(self):
        from hospital.services import similar_cases, case_token
        for out in ['resolved', 'resolved', 'improved', 'no_change']:
            self.make_case('F', 'Malaria, uncomplicated', 'Artemether/Lumefantrine', out)
        lonely = self.make_case('M', 'Malaria', 'Paracetamol', 'resolved')     # group of one: must not be shown
        r = similar_cases(self.patient, 'Suspected malaria')
        self.assertEqual([(g['regimen'], g['n'], g['rate']) for g in r['groups']], [('Artemether/Lumefantrine', 4, 75)])
        c = self.as_('doctor')
        token = r['groups'][0]['shown'][0]['token']
        d = c.get(f'/cases/{token}/?patient={self.patient.pk}').json()
        self.assertTrue(d['ok']); self.assertEqual(d['title'], 'Anonymous case')
        self.assertNotIn('Person', json.dumps(d))                                # no names leak
        self.assertEqual(c.get(f'/cases/{case_token(lonely.pk)}/?patient={self.patient.pk}').status_code, 404)
        self.assertEqual(c.get(f'/cases/forged-token/?patient={self.patient.pk}').status_code, 404)

    def test_own_past_case_is_shown_as_this_patient(self):
        from hospital.services import similar_cases
        e = Encounter.objects.create(patient=self.patient, reason='x', diagnosis='Malaria', status='completed', outcome='resolved')
        r = similar_cases(self.patient, 'Malaria')
        own = [c for g in r['groups'] for c in g['shown'] if c['own']]
        self.assertEqual(len(own), 1)
        d = self.as_('doctor').get(f'/cases/{own[0]["token"]}/?patient={self.patient.pk}').json()
        self.assertTrue(d['own']); self.assertIn('This patient', d['title']); self.assertIn(f'/encounters/{e.pk}/', d['url'])


class NetworkTests(Base):
    def setUp(self):
        from django.utils import timezone as tz
        self.fac = NetworkFacility.objects.create(name='Heart Centre', kind='clinic')
        self.other_fac = NetworkFacility.objects.create(name='Other Clinic')
        self.sp = Specialist.objects.create(facility=self.fac, name='Ada Heart', speciality='Cardiology', rating=4.8, reviews=20)
        self.slot = SpecialistSlot.objects.create(specialist=self.sp, start=tz.now() + timedelta(days=2))
        U = get_user_model()
        self.partner = U.objects.create_user('partner', password=PW); StaffProfile.objects.create(user=self.partner, role='partner', facility=self.fac)
        self.outsider = U.objects.create_user('outsider', password=PW); StaffProfile.objects.create(user=self.outsider, role='partner', facility=self.other_fac)
        self.enc = self.encounter()

    def refer(self, **extra):
        data = {'encounter': self.enc.pk, 'kind': 'consultation', 'facility': self.fac.pk, 'specialist': self.sp.pk, 'urgency': 'urgent',
                'reason': 'Chest pain', 'consent_to_share': 'on', 'send_now': 'on', 'slot_id': self.slot.pk, **extra}
        return self.as_('doctor').post('/referrals/new/', data)

    def test_directory_and_slots(self):
        c = self.as_('doctor')
        self.assertContains(c.get('/network/'), 'Ada Heart')
        self.assertContains(c.get(f'/network/specialists/{self.sp.pk}/'), self.slot.start.astimezone().strftime('%H:%M'))
        self.assertEqual(c.get(f'/network/specialists/{self.sp.pk}/slots/').json()['slots'][0]['id'], self.slot.pk)

    def test_booking_holds_the_slot_and_prevents_double_booking(self):
        self.refer()
        r = Referral.objects.get()
        self.assertEqual((r.slot, r.status, r.destination, r.shared), (self.slot, 'sent', 'Heart Centre', True))
        self.client.logout(); self.refer()                          # same slot again
        self.assertEqual(Referral.objects.count(), 1)

    def test_records_need_consent_before_sending(self):
        r = self.refer(consent_to_share='')
        self.assertContains(r, 'consent'); self.assertFalse(Referral.objects.exists())

    def test_operation_referral_creates_shared_checklist(self):
        self.refer(kind='operation', planned_date=(date.today() + timedelta(days=3)).isoformat())
        r = Referral.objects.get()
        self.assertEqual(r.tasks.filter(assigned_to_side='sender').count(), 6)
        self.assertEqual(r.tasks.filter(assigned_to_side='receiver').count(), 3)
        self.assertTrue(r.tasks.filter(lab_test__code='CBC').exists())

    def test_partner_sees_only_their_shared_referrals(self):
        self.refer(); r = Referral.objects.get()
        c = self.as_('partner')
        self.assertRedirects(c.get('/'), '/network/inbox/')
        self.assertContains(c.get('/network/inbox/'), self.patient.full_name)
        self.assertEqual(c.get(f'/patients/{self.patient.pk}/').status_code, 403)        # no access to the hospital chart
        self.assertEqual(c.get('/labs/').status_code, 403)
        self.assertContains(c.get(f'/referrals/{r.pk}/summary/'), 'Shared patient record')
        self.client.logout(); c = self.as_('outsider')
        self.assertEqual(c.get(f'/referrals/{r.pk}/').status_code, 403)                  # another facility cannot see it
        self.assertEqual(c.get(f'/referrals/{r.pk}/summary/').status_code, 403)

    def test_without_consent_partner_cannot_open_the_record(self):
        r = Referral.objects.create(encounter=self.enc, facility=self.fac, destination='Heart Centre', reason='x', status='sent', consent_to_share=False)
        c = self.as_('partner')
        self.assertEqual(c.get(f'/referrals/{r.pk}/').status_code, 200)
        self.assertEqual(c.get(f'/referrals/{r.pk}/summary/').status_code, 403)
        draft = Referral.objects.create(encounter=self.enc, facility=self.fac, destination='Heart Centre', reason='x', status='draft', consent_to_share=True)
        self.assertEqual(c.get(f'/referrals/{draft.pk}/').status_code, 403)              # drafts are never visible

    def test_two_way_requests(self):
        self.refer(); r = Referral.objects.get()
        c = self.as_('partner')
        c.post(f'/referrals/{r.pk}/status/accepted/'); r.refresh_from_db(); self.assertEqual(r.status, 'accepted')
        c.post(f'/referrals/{r.pk}/tasks/', {'kind': 'test', 'title': 'Repeat potassium', 'lab_test': LabTest.objects.get(code='RFT').pk})
        t = ReferralTask.objects.get()
        self.assertEqual((t.requested_by_side, t.assigned_to_side), ('receiver', 'sender'))
        self.assertEqual(c.post(f'/referrals/tasks/{t.pk}/done/').status_code, 400)       # partner cannot tick off the hospital's task
        self.client.logout(); c = self.as_('doctor')
        c.post(f'/referrals/tasks/{t.pk}/order_test/')
        self.assertTrue(LabRequest.objects.filter(encounter=self.enc, orders__test__code='RFT').exists())
        c.post(f'/referrals/tasks/{t.pk}/done/', {'response': 'K 4.9'})
        t.refresh_from_db(); self.assertEqual((t.status, t.response), ('done', 'K 4.9'))
        self.assertEqual(c.post(f'/referrals/{r.pk}/status/accepted/').status_code, 400)   # only the receiver accepts

    def test_declining_releases_the_slot(self):
        self.refer(); r = Referral.objects.get()
        self.as_('partner').post(f'/referrals/{r.pk}/status/declined/')
        r.refresh_from_db(); self.assertIsNone(r.slot)


class BedDetailTests(Base):
    def test_bed_page_with_and_without_patient(self):
        bed = Bed.objects.filter(state='available').first()
        c = self.as_('nurse')
        self.assertContains(c.get(f'/beds/{bed.pk}/'), 'Ready for a patient')
        c.post('/admissions/new/', {'encounter': self.encounter().pk, 'bed': bed.pk})
        page = c.get(f'/beds/{bed.pk}/')
        self.assertContains(page, self.patient.full_name); self.assertContains(page, 'days in bed')
        c.post(f'/admissions/{Admission.objects.get().pk}/discharge/')
        c.post(f'/beds/{bed.pk}/ready/')
        c.post(f'/beds/{bed.pk}/maintenance/', {'reason': 'Broken rail'})
        bed.refresh_from_db(); self.assertEqual(bed.state, 'maintenance')


class FinanceTests(Base):
    def setUp(self):
        U = get_user_model()
        self.fin = U.objects.create_user('fin', password=PW); StaffProfile.objects.create(user=self.fin, role='finance')
        self.e = self.encounter()

    def billable_visit(self):
        lr = LabRequest.objects.create(encounter=self.e)
        LabOrder.objects.create(encounter=self.e, request=lr, test=LabTest.objects.get(code='CBC'))                 # D450
        ImagingOrder.objects.create(encounter=self.e, modality='xray', region='Chest', body_system='lungs')       # D750
        rx = Prescription.objects.create(encounter=self.e, allergy_reviewed=True, state='signed')
        PrescriptionItem.objects.create(prescription=rx, medication=self.med, frequency='TDS', duration_days=2, quantity=6)
        self.as_('pharmacy').post(f'/prescriptions/{rx.pk}/dispense/'); self.client.logout()                    # 6 × D6
        bed = Bed.objects.filter(kind='general').first()
        a = Admission.objects.create(encounter=self.e, bed=bed)
        Admission.objects.filter(pk=a.pk).update(admitted_at=timezone.now() - timedelta(hours=30))               # 2 bed-days × D800

    def test_capture_every_charge_once(self):
        self.billable_visit()
        c = self.as_('reception')
        r = c.get(f'/finance/visit/{self.e.pk}/'); inv = Invoice.objects.get()
        self.assertRedirects(r, f'/finance/bills/{inv.pk}/')
        cats = sorted(inv.lines.values_list('category', flat=True))
        self.assertEqual(cats, ['bed', 'bed', 'consultation', 'imaging', 'lab', 'pharmacy'])
        self.assertEqual(inv.total, Decimal('300') + 450 + 750 + 36 + 1600)
        c.post(f'/finance/bills/{inv.pk}/capture/')
        self.assertEqual(inv.lines.count(), 6)                               # nothing billed twice

    def test_issue_pay_partially_then_fully(self):
        self.billable_visit()
        c = self.as_('reception'); c.get(f'/finance/visit/{self.e.pk}/'); inv = Invoice.objects.get()
        c.post(f'/finance/bills/{inv.pk}/pay/', {'amount': '100', 'method': 'cash'})
        self.assertFalse(Payment.objects.exists())                           # cannot pay a draft
        c.post(f'/finance/bills/{inv.pk}/issue/')
        c.post(f'/finance/bills/{inv.pk}/pay/', {'amount': '1000', 'method': 'wave'})
        self.assertFalse(Payment.objects.exists())                           # mobile money needs a reference
        c.post(f'/finance/bills/{inv.pk}/pay/', {'amount': '1000', 'method': 'wave', 'reference': 'WV123'})
        inv.refresh_from_db(); self.assertEqual((inv.status, inv.balance), ('partial', Decimal('2136.00')))
        c.post(f'/finance/bills/{inv.pk}/pay/', {'amount': '99999', 'method': 'cash'})
        self.assertEqual(Payment.objects.count(), 1)                         # overpayment refused
        c.post(f'/finance/bills/{inv.pk}/pay/', {'amount': '2136', 'method': 'cash'})
        inv.refresh_from_db(); self.assertEqual((inv.status, inv.balance), ('paid', Decimal('0')))
        self.assertContains(c.get(f'/finance/payments/{Payment.objects.first().pk}/receipt/'), 'Official receipt')

    def test_insurance_split_and_discount_rules(self):
        self.billable_visit()
        c = self.as_('reception'); c.get(f'/finance/visit/{self.e.pk}/'); inv = Invoice.objects.get()
        c.post(f'/finance/bills/{inv.pk}/update/', {'insurer': 'X', 'insurance_cover': 80, 'discount': '0'})
        inv.refresh_from_db(); self.assertEqual((inv.insurance_share, inv.patient_share), (Decimal('2508.80'), Decimal('627.20')))
        r = c.post(f'/finance/bills/{inv.pk}/update/', {'insurance_cover': 80, 'discount': '100', 'discount_reason': 'kind'})
        self.assertEqual(r.status_code, 403)                                  # reception cannot discount
        self.client.logout(); c = self.as_('fin')
        c.post(f'/finance/bills/{inv.pk}/update/', {'insurance_cover': 0, 'discount': '136'})
        inv.refresh_from_db(); self.assertEqual(inv.discount, 0)              # a discount needs a reason
        c.post(f'/finance/bills/{inv.pk}/update/', {'insurance_cover': 0, 'discount': '136', 'discount_reason': 'Hardship'})
        inv.refresh_from_db(); self.assertEqual(inv.total, Decimal('3000.00'))

    def test_voided_payment_and_bill(self):
        self.billable_visit()
        c = self.as_('fin'); c.get(f'/finance/visit/{self.e.pk}/'); inv = Invoice.objects.get()
        c.post(f'/finance/bills/{inv.pk}/issue/'); c.post(f'/finance/bills/{inv.pk}/pay/', {'amount': '500', 'method': 'cash'})
        pay = Payment.objects.get()
        c.post(f'/finance/payments/{pay.pk}/void/', {'reason': 'Entered twice'})
        inv.refresh_from_db(); pay.refresh_from_db(); self.assertTrue(pay.voided); self.assertEqual(inv.status, 'issued')
        c.post(f'/finance/bills/{inv.pk}/void/', {'reason': 'Wrong patient'})
        inv.refresh_from_db(); self.assertEqual(inv.status, 'void')
        c.get(f'/finance/visit/{self.e.pk}/')
        self.assertEqual(Invoice.objects.exclude(pk=inv.pk).get().lines.count(), 6)   # charges from a voided bill can be billed again

    def test_access(self):
        self.assertEqual(self.as_('doctor').get('/finance/').status_code, 403)
        self.client.logout()
        for path in ['/finance/', '/finance/bills/', '/finance/prices/']:
            self.assertEqual(self.as_('reception').get(path).status_code, 200, path)


class DecisionSupportTests(Base):
    def test_allergy_by_drug_class_and_cross_reaction(self):
        from hospital.clinical import allergy_matches
        amox, cef, ibu = (Medication.objects.get(name=n) for n in ('Amoxicillin', 'Ceftriaxone', 'Ibuprofen'))
        self.assertEqual(allergy_matches([{'substance': 'Penicillin'}], amox)[0][0]['match'], 'class')
        self.assertEqual(len(allergy_matches([{'substance': 'Penicillin'}], cef)[1]), 1)       # caution, not a block
        self.assertEqual(allergy_matches([{'substance': 'Aspirin'}], ibu)[0][0]['match'], 'class')
        self.assertEqual(allergy_matches([{'substance': 'Peanuts'}], amox), ([], []))

    def test_penicillin_allergy_blocks_amoxicillin_without_override(self):
        Allergy.objects.create(patient=self.patient, substance='Penicillin', reaction='rash', severity='moderate')
        e = self.encounter()
        data = {'encounter': e.pk, 'allergy_reviewed': 'on', 'items-TOTAL_FORMS': 1, 'items-INITIAL_FORMS': 0, 'items-MIN_NUM_FORMS': 1, 'items-MAX_NUM_FORMS': 30,
                'items-0-medication': self.med.pk, 'items-0-units_per_dose': 1, 'items-0-route': 'oral', 'items-0-frequency': 'TDS', 'items-0-duration_days': 5}
        r = self.as_('doctor').post('/prescriptions/new/', data)
        self.assertContains(r, 'Possible allergy match'); self.assertFalse(Prescription.objects.exists())

    def test_review_flags_risks_missing_work_up_and_mismatch(self):
        from hospital.clinical import clinical_review
        e = self.encounter(); e.diagnosis = 'Malaria'; e.save()
        titles = [f['title'] for f in clinical_review(e)]
        self.assertIn('Malaria not confirmed by a test', titles)
        lr = LabRequest.objects.create(encounter=e)
        o = LabOrder.objects.create(encounter=e, request=lr, test=LabTest.objects.get(code='MAL'), status='verified', resulted_at=timezone.now())
        LabResultValue.objects.create(order=o, parameter=o.test.parameters.get(code='RDT'), value_text='Negative', flag='N')
        o2 = LabOrder.objects.create(encounter=e, request=lr, test=LabTest.objects.get(code='RFT'), status='verified', resulted_at=timezone.now())
        LabResultValue.objects.create(order=o2, parameter=o2.test.parameters.get(code='CREA'), value_number=180, flag='H')
        f = {x['title']: x for x in clinical_review(e, [Medication.objects.get(name='Metformin')])}
        self.assertEqual(f['Malaria test negative']['level'], 'danger')                      # possible misdiagnosis
        self.assertIn('Metformin with raised creatinine', f)
        self.assertNotIn('Malaria not confirmed by a test', f)

    def test_suggestions_need_enough_cases(self):
        from hospital.clinical import treatment_suggestions
        e = self.encounter(); e.diagnosis = 'Malaria'; e.save()
        self.assertEqual(treatment_suggestions(e)['meds'], [])
        al = Medication.objects.get(name='Artemether/Lumefantrine')
        for i in range(3):
            p = Patient.objects.create(first_name='S', last_name=str(i), dob=date(1990, 1, 1), sex='M')
            pe = Encounter.objects.create(patient=p, reason='x', diagnosis='Malaria', status='completed', outcome='resolved')
            rx = Prescription.objects.create(encounter=pe, allergy_reviewed=True, state='dispensed')
            PrescriptionItem.objects.create(prescription=rx, medication=al, units_per_dose=4, frequency='BD', duration_days=3, quantity=24)
        s = treatment_suggestions(e)
        self.assertEqual((s['meds'][0]['name'].split()[0], s['meds'][0]['frequency'], s['meds'][0]['success']), ('Artemether/Lumefantrine', 'BD', 100))
        d = self.as_('doctor').get(f'/api/clinical/?encounter={e.pk}&meds={al.pk}').json()
        self.assertTrue(d['ready']); self.assertEqual(d['suggestions']['n'], 3); self.assertFalse(d['ai'])

    def test_ai_context_has_no_identifiers(self):
        from hospital.clinical import deidentified_context, ai_review
        self.patient.phone = '+220 7000000'; self.patient.address = '12 Secret Street'; self.patient.save()
        e = self.encounter(); e.diagnosis = 'Pneumonia'; e.symptoms = 'Told by Awa Jallow'; e.save()
        blob = json.dumps(deidentified_context(e), default=str)
        for secret in ('Awa', 'Jallow', self.patient.mrn, '7000000', 'Secret Street', '1990-01-01'):
            self.assertNotIn(secret, blob)
        self.assertIn('Pneumonia', blob)
        self.assertIsNone(ai_review(e))                                      # off until configured
        self.assertContains(self.as_('doctor').get(f'/encounters/{e.pk}/ai-context/'), 'AI not connected')

    def test_story_and_review_pages(self):
        e = self.encounter(); e.diagnosis = 'Malaria'; e.save()
        c = self.as_('doctor')
        self.assertContains(c.get(f'/patients/{self.patient.pk}/story/'), 'story-data')
        self.assertContains(c.get(f'/encounters/{e.pk}/'), 'Clinical safety review')
        self.assertEqual(self.client.get(f'/patients/{self.patient.pk}/story/').status_code, 200)
