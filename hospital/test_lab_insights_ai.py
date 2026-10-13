"""Dr. Flow on Lab insights: the heads-up without AI, the big picture and questions, and no personal data sent."""
import json
from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from . import lab_insights_ai as L
from . import medical_ai
from .models import ImagingOrder, LabInsightAsk, LabOrder, LabParameter, LabRequest, LabResultValue
from .test_evidence import Base

AI_ON = override_settings(CLINICAL_AI_ENABLED=True, CLINICAL_AI_PROVIDER='endpoint', CLINICAL_AI_ENDPOINT='https://ai.example.org/labs')


class LabInsightsAITests(Base):
    def setUp(self):
        now = timezone.now()
        self.k = LabParameter.objects.get(code='K')
        self.plt = LabParameter.objects.get(code='PLT')
        nurse = self.users['nurse']; nurse.first_name, nurse.last_name = 'Isatou', 'Bah'; nurse.save()
        self.result(self.man, {self.hb: 12.0}, test=self.cbc, when=now - timedelta(days=10))
        lr, self.e = self.result(self.man, {self.hb: 9.0, self.plt: 120}, test=self.cbc, when=now - timedelta(days=6))
        self.result(self.man, {self.hb: 8.5, self.plt: 210}, test=self.cbc, when=now - timedelta(days=1))
        self.result(self.man, {self.k: 4.0}, test=self.k.test, when=now - timedelta(days=5))
        self.result(self.man, {self.k: 6.8}, test=self.k.test, when=now)
        LabResultValue.objects.filter(order__encounter__patient=self.man, parameter=self.hb, value_number=9).update(acknowledged_by=nurse, acknowledged_at=now)
        LabOrder.objects.filter(encounter__patient=self.man, values__parameter=self.k, values__value_number=6.8).update(result='Called Lamin Ceesay on 7712345')
        req = LabRequest.objects.create(encounter=self.e, requested_by=self.users['doctor'])
        o = LabOrder.objects.create(encounter=self.e, request=req, test=self.cbc, status='collected')
        LabOrder.objects.filter(pk=o.pk).update(created_at=now - timedelta(days=3))
        ImagingOrder.objects.create(encounter=self.e, modality='xray', region='Chest', status='reported', abnormal=True,
                                    impression='Lamin: right lower lobe consolidation', requested_by=self.users['doctor'])

    def secrets(self):
        return ['Lamin', 'Ceesay', self.man.mrn, '7712345', '1980-05-01', 'Isatou', 'Bah', str(timezone.now().year) + '-']

    def test_headsup_without_ai(self):
        h = L.headsup(self.man)
        text = ' | '.join(x['text'] for x in h)
        self.assertEqual(h[0]['level'], 'danger')
        self.assertIn(f'Critical, not yet reviewed: {self.k.name} 6.8', text)
        self.assertIn(f'Getting worse: {self.hb.name} 8.5', text)
        self.assertIn('Back to normal', text)
        self.assertIn('waiting for review', text)
        self.assertIn('Waiting over 2 days in the lab: Complete Blood Count', text)
        self.assertIn('Abnormal imaging: X-ray Chest', text)
        crit = next(x for x in h if x['level'] == 'danger')
        self.assertEqual(crit['param'], self.k.pk)                       # the page opens this result

    def test_trend_rules(self):
        p = {'lo': 3.5, 'hi': 5.1, 'history': [{'num': 4.0}, {'num': 6.0}]}
        self.assertEqual(L.trend(p), 'newly abnormal')
        p['history'] = [{'num': 6.0}, {'num': 7.0}]; self.assertEqual(L.trend(p), 'worsening')
        p['history'] = [{'num': 7.0}, {'num': 5.6}]; self.assertEqual(L.trend(p), 'improving')
        p['history'] = [{'num': 6.0}, {'num': 4.2}]; self.assertEqual(L.trend(p), 'back to normal')
        p['history'] = [{'num': 4.0}, {'num': 4.05}]; self.assertEqual(L.trend(p), 'stable')
        p['history'] = [{'num': 4.0}]; self.assertIsNone(L.trend(p))

    def test_context_is_de_identified(self):
        ctx = L.insights_context(self.man)
        hb = next(r for r in ctx['results'] if r['result'] == self.hb.name)
        self.assertEqual(len(hb['earlier']), 2)
        self.assertAlmostEqual(hb['earlier'][0]['days_ago'], 10, delta=0.2)
        self.assertEqual(hb['trend'], 'worsening')
        self.assertIn('[patient]', json.dumps(ctx['lab_comments']))
        self.assertIn('[patient]', ctx['imaging'][0]['impression'])
        self.assertEqual(ctx['tests_still_in_the_lab'][0]['status'], 'Collected')
        self.assertIn('open_visit', ctx)
        blob = json.dumps(ctx, default=str)
        for s in self.secrets():
            self.assertNotIn(s, blob, s)

    def test_panel_without_ai(self):
        d = self.as_('doctor').get(f'/patients/{self.man.pk}/labs/drflow/').json()
        self.assertFalse(d['enabled']); self.assertTrue(d['headsup']); self.assertEqual(d['thread'], [])
        r = self.as_('doctor').post(f'/patients/{self.man.pk}/labs/drflow/ask/', {'kind': 'headsup'})
        self.assertEqual(r.status_code, 400)

    @AI_ON
    def test_big_picture_then_question_remembers(self):
        sent = []

        def post(url, body, headers, timeout):
            sent.append(body)
            return {'text': '## Heads-up\n1. Potassium is critical.' if len(sent) == 1 else '## Answer\nHaemoglobin is falling.'}
        with mock.patch.object(medical_ai, '_post_json', post):
            a = self.as_('doctor').post(f'/patients/{self.man.pk}/labs/drflow/ask/', {'kind': 'headsup'}).json()['ask']
            q = self.as_('nurse').post(f'/patients/{self.man.pk}/labs/drflow/ask/', {'kind': 'question', 'question': 'Why is Lamin so pale?'}).json()['ask']
        self.assertEqual((a['status'], q['status']), ('done', 'done'))
        self.assertIn('## Heads-up', sent[0]['instructions'])
        self.assertIn('[patient]', sent[1]['instructions'])                      # the name typed in the question is removed
        self.assertEqual(sent[1]['context']['earlier_questions'][0]['answer'], '## Heads-up\n1. Potassium is critical.')
        for body in sent:
            blob = json.dumps(body, default=str)
            for s in self.secrets():
                self.assertNotIn(s, blob, s)
        self.assertEqual(LabInsightAsk.objects.count(), 2)
        self.assertTrue(all(len(x.context_digest) == 64 for x in LabInsightAsk.objects.all()))
        d = self.as_('doctor').get(f'/patients/{self.man.pk}/labs/drflow/').json()
        self.assertEqual([x['kind'] for x in d['thread']], ['headsup', 'question'])   # oldest first
        self.assertEqual(self.as_('doctor').post(f'/labs/insights/drflow/{q["id"]}/rate/', {'helpful': '0'}).status_code, 200)

    @AI_ON
    def test_failure_validation_and_permissions(self):
        with mock.patch.object(medical_ai, '_post_json', side_effect=medical_ai.AIServiceError(503, 'busy')):
            a = self.as_('doctor').post(f'/patients/{self.man.pk}/labs/drflow/ask/', {'kind': 'headsup'}).json()['ask']
        self.assertEqual(a['status'], 'failed'); self.assertNotIn('busy', a['error'])
        self.assertEqual(self.as_('doctor').post(f'/patients/{self.man.pk}/labs/drflow/ask/', {'kind': 'question', 'question': 'x'}).status_code, 400)
        self.assertEqual(self.as_('reception').get(f'/patients/{self.man.pk}/labs/drflow/').status_code, 403)
        self.assertEqual(self.as_('lab').post(f'/patients/{self.man.pk}/labs/drflow/ask/', {'kind': 'headsup'}).status_code, 403)

    def test_context_preview_and_page(self):
        d = self.as_('doctor').get(f'/patients/{self.man.pk}/labs/drflow/context/').json()
        for s in self.secrets():
            self.assertNotIn(s, d['context'], s)
        page = self.as_('doctor').get(f'/patients/{self.man.pk}/labs/').content.decode()
        self.assertIn('id="lidf"', page); self.assertIn('lab-insights-drflow.js', page); self.assertIn('robodoc.js', page)
