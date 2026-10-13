"""Dr. Flow on the bed page: quick facts without AI, the handover summary, and no personal data in what is sent."""
import json
from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from . import bed_summary as S
from . import medical_ai
from .models import (Admission, Allergy, Bed, BedsideObservation, BedsideState, BedSummary, Encounter, LabOrder, LabRequest,
                     Medication, MedicationAdministration, Prescription, PrescriptionItem)
from .test_evidence import Base

AI_ON = override_settings(CLINICAL_AI_ENABLED=True, CLINICAL_AI_PROVIDER='endpoint', CLINICAL_AI_ENDPOINT='https://ai.example.org/bed')
HANDOVER = '''Man in his 40s, day 3 with pneumonia, worsening.
## Situation
NEWS2 7 and rising.
## Background
Penicillin allergy.
## Assessment
Getting worse.
## Recommendations
1. Escalate to the doctor now
## Watch for
- SpO2 below 90%'''


class BedSummaryTests(Base):
    def setUp(self):
        p = self.man
        p.phone = '+220 7712345'; p.address = '12 Secret Street, Bakau'; p.save()
        now = timezone.now()
        self.e = Encounter.objects.create(patient=p, department=self.dept, reason='Brought by Awa Jallow, cough', diagnosis='Pneumonia',
                                          clinician=self.users['doctor'], vitals={'weight_kg': '60'})
        Allergy.objects.create(patient=p, substance='Penicillin', reaction='Rash', severity='severe')
        self.bed = Bed.objects.filter(state='available').first()
        self.adm = Admission.objects.create(encounter=self.e, bed=self.bed, admitted_at=now - timedelta(days=2, hours=3),
                                            discharge_notes='Lamin wife in room 4')
        BedsideState.objects.create(admission=self.adm, devices={'oxygen': {'on': True, 'device': 'mask', 'flow_l_min': 8},
                                                                 'chest_drain': {'on': True, 'side': 'right', 'bubbling': True}})
        BedsideObservation.objects.create(admission=self.adm, taken_at=now - timedelta(hours=6), heart_rate=96, resp_rate=20, spo2=95,
                                          systolic=118, temperature_c=37.8, recorded_by=self.users['nurse'])
        BedsideObservation.objects.create(admission=self.adm, taken_at=now - timedelta(hours=1), heart_rate=118, systolic=96, resp_rate=26,
                                          spo2=89, temperature_c=38.6, on_oxygen=True, recorded_by=self.users['nurse'])
        med = Medication.objects.create(name='Unstocked Cef', generic_name='Ceftriaxone', strength='1 g', form='Vial', category='antibiotic')
        rx = Prescription.objects.create(encounter=self.e, state='signed', notes='Call Lamin', signed_by=self.users['doctor'], signed_at=now - timedelta(days=2))
        item = PrescriptionItem.objects.create(prescription=rx, medication=med, route='iv', frequency='OD', duration_days=5, quantity=5)
        MedicationAdministration.objects.create(item=item, scheduled_for=now - timedelta(hours=20), status='missed', given_by=self.users['nurse'])
        lr = LabRequest.objects.create(encounter=self.e, requested_by=self.users['doctor'])
        LabOrder.objects.create(encounter=self.e, request=lr, test=self.cbc, status='collected')

    def secrets(self):
        p = self.man
        return ['Lamin', 'Ceesay', p.mrn, '7712345', 'Secret Street', 'Bakau', '1980-05-01', 'Awa', 'Jallow', 'room 4',
                self.bed.code, self.bed.ward.name, str(timezone.now().year) + '-']

    def test_context_has_the_stay_and_no_personal_data(self):
        ctx = S.summary_context(self.adm)
        st = ctx['this_stay']
        self.assertEqual(st['bed_type'], self.bed.get_kind_display())
        self.assertGreater(st['days_since_admission'], 2)
        self.assertIn(self.cbc.name, st['lab_tests_still_pending'])
        self.assertIn('bedside', ctx); self.assertIn('pharmacy', ctx)
        blob = json.dumps(ctx, default=str)
        for s in self.secrets():
            self.assertNotIn(s, blob, s)

    def test_quick_facts_work_without_ai(self):
        q = S.quick_facts(self.adm)
        text = ' | '.join(x['text'] for x in q)
        self.assertIn('NEWS2', text)
        self.assertIn('and rising', text)
        self.assertIn('SpO2 89% on oxygen', text)
        self.assertIn('bubbling', text)
        self.assertIn('missed, refused or held', text)
        self.assertIn('Out of stock in the pharmacy: Ceftriaxone 1 g vial', text)
        self.assertIn('Allergies: Penicillin', text)
        self.assertIn('Day 3 of the stay', text)
        self.assertEqual(q[0]['level'], 'danger')                      # safety first
        r = self.as_('nurse').get(f'/beds/admissions/{self.adm.pk}/drflow/').json()
        self.assertFalse(r['enabled']); self.assertTrue(r['quick']); self.assertIsNone(r['summary'])

    @AI_ON
    def test_handover_summary_is_written_and_audited(self):
        sent = {}

        def post(url, body, headers, timeout):
            sent.update(body)
            return {'text': HANDOVER}
        with mock.patch.object(medical_ai, '_post_json', post):
            r = self.as_('doctor').post(f'/beds/admissions/{self.adm.pk}/drflow/ask/')
        self.assertEqual(r.status_code, 200, r.content)
        s = BedSummary.objects.get()
        self.assertEqual(s.status, 'done', s.error)
        self.assertEqual(len(s.context_digest), 64)
        self.assertIn('## Situation', sent['instructions'])
        self.assertNotIn('## Hospital range vs WHO reference', sent['instructions'])   # the general prompt, not the lab one
        blob = json.dumps(sent, default=str)
        for secret in self.secrets():
            self.assertNotIn(secret, blob, secret)
        d = r.json()['summary']
        self.assertEqual(d['status'], 'done'); self.assertIn('<h4>', d['html'])
        st = self.as_('doctor').get(f'/beds/drflow/{s.pk}/').json()['summary']
        self.assertEqual(st['id'], s.pk)
        self.assertEqual(self.as_('doctor').post(f'/beds/drflow/{s.pk}/rate/', {'helpful': '1'}).status_code, 200)
        s.refresh_from_db(); self.assertTrue(s.helpful)

    @AI_ON
    def test_failure_discharge_and_permissions(self):
        with mock.patch.object(medical_ai, '_post_json', side_effect=medical_ai.AIServiceError(503, 'busy')):
            r = self.as_('doctor').post(f'/beds/admissions/{self.adm.pk}/drflow/ask/').json()
        self.assertEqual(r['summary']['status'], 'failed')
        self.assertNotIn('busy', r['summary']['error'])
        self.assertEqual(self.as_('reception').get(f'/beds/admissions/{self.adm.pk}/drflow/').status_code, 403)
        self.assertEqual(self.as_('pharmacy').post(f'/beds/admissions/{self.adm.pk}/drflow/ask/').status_code, 403)
        self.adm.discharged_at = timezone.now(); self.adm.save()
        self.assertEqual(self.as_('doctor').post(f'/beds/admissions/{self.adm.pk}/drflow/ask/').status_code, 400)

    def test_context_preview_and_page(self):
        d = self.as_('doctor').get(f'/beds/admissions/{self.adm.pk}/drflow/context/').json()
        for s in self.secrets():
            self.assertNotIn(s, d['context'], s)
        page = self.as_('nurse').get(f'/beds/{self.bed.pk}/').content.decode()
        self.assertIn('id="bsum"', page); self.assertIn('bed-summary.js', page)
        self.client.logout()
        page = self.as_('reception').get(f'/beds/{self.bed.pk}/').content.decode()
        self.assertNotIn('id="bsum"', page)
