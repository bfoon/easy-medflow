"""Dr. Flow on imaging: privacy of what is sent (pixels and words), parsing labels, the worker, and the endpoints."""
import io
import json
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from . import imaging_ai, medical_ai
from .models import Encounter, ImagingAIRun, ImagingImage, ImagingOrder, StaffProfile
from .test_evidence import PW, Base

AI_ON = override_settings(CLINICAL_AI_ENABLED=True, CLINICAL_AI_PROVIDER='endpoint', CLINICAL_AI_ENDPOINT='https://ai.example.org/image')
GEMINI = override_settings(CLINICAL_AI_ENABLED=True, CLINICAL_AI_PROVIDER='gemini', CLINICAL_AI_MODEL='gemini-vision',
                           CLINICAL_AI_ENDPOINT='https://generativelanguage.googleapis.com/v1beta/openai/', CLINICAL_AI_TOKEN='k')

ANSWER = {
    'summary': 'Right lower zone opacity, likely consolidation.',
    'quality': 'Slightly rotated, adequate inspiration.',
    'labels': [
        {'name': 'Right lower zone opacity', 'box_2d': [600, 100, 850, 450], 'explanation': 'Air-space shadowing.', 'concern': 'abnormal', 'confidence': 'moderate'},
        {'name': 'Trachea', 'point': [150, 500], 'explanation': 'Central.', 'concern': 'normal', 'confidence': 'high'},
        {'name': 'No position', 'explanation': 'x', 'concern': 'bogus', 'confidence': 'bogus'},
    ],
    'explanation': '## Findings\nOpacity [1]. Trachea central [2].',
    'limitations': 'Single view.',
}


def image_bytes(size=(200, 100), color=(180, 180, 180), exif=True, fmt='JPEG'):
    from PIL import Image
    im = Image.new('RGB', size, color)
    b = io.BytesIO()
    if exif and fmt == 'JPEG':
        ex = Image.Exif()
        ex[0x010F] = 'PhoneMaker'          # Make
        ex[0x9286] = 'Lamin Ceesay'        # UserComment-like field carrying a name
        im.save(b, fmt, exif=ex.tobytes())
    else:
        im.save(b, fmt)
    return b.getvalue()


class ImagingAITests(Base):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.ov = override_settings(MEDIA_ROOT=self.media)
        self.ov.enable()
        U = get_user_model()
        if not U.objects.filter(username='radiology').exists():
            u = U.objects.create_user(username='radiology', password=PW)
            StaffProfile.objects.create(user=u, role='radiology')
        self.e = Encounter.objects.create(patient=self.man, department=self.dept, reason='Cough', diagnosis='Pneumonia? Lamin unwell',
                                          clinician=self.users['doctor'])
        self.o = ImagingOrder.objects.create(encounter=self.e, modality='xray', region='Chest PA', status='acquired',
                                             clinical_question=f'Lamin Ceesay {self.man.mrn} cough 3 weeks, TB?',
                                             findings='Opacity right base in Ceesay', requested_by=self.users['doctor'])
        self.img = ImagingImage.objects.create(order=self.o, file=SimpleUploadedFile('chest.jpg', image_bytes()), caption='PA Lamin')

    def tearDown(self):
        self.ov.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def post(self, role, name, pk, body):
        return self.as_(role).post(reverse(name, args=[pk]), data=json.dumps(body), content_type='application/json')

    # ---------------------------------------------------------------- what leaves the server
    def test_prepare_image_strips_metadata_shrinks_and_blacks_out(self):
        from PIL import Image
        with override_settings(CLINICAL_AI_IMAGE_MAX_SIDE=600):
            big = io.BytesIO(image_bytes(size=(2000, 1000)))
            jpeg, w, h = imaging_ai.prepare_image(big, [[0, 0, .25, .5]])
        self.assertEqual((w, h), (600, 300))
        im = Image.open(io.BytesIO(jpeg))
        self.assertFalse(im.getexif())                         # no camera, GPS or name in metadata
        self.assertNotIn(b'Lamin', jpeg)
        self.assertLess(sum(im.convert('L').getpixel((20, 20)) for _ in [0]), 15)       # covered corner is black
        self.assertGreater(im.convert('L').getpixel((500, 250)), 150)                   # the rest untouched

    def test_redactions_are_clamped_and_filtered(self):
        self.assertEqual(imaging_ai.clean_redactions([[-1, .5, 3, 3], [.1, .1, 0, 0], ['x', 1, 1, 1], [.2, .2, .1, .1]]),
                         [[0.0, 0.5, 1.0, 0.5], [0.2, 0.2, 0.1, 0.1]])

    def test_context_has_no_identifiers(self):
        r = ImagingAIRun(image=self.img, order=self.o, kind='question', question='x')
        r.save()
        ctx = json.dumps(imaging_ai.image_context(r, include_draft=True))
        for bad in ('Lamin', 'Ceesay', self.man.mrn, '1980'):
            self.assertNotIn(bad, ctx)
        self.assertIn('[patient]', ctx)
        self.assertIn('Chest PA', ctx)
        self.assertIn('radiologist_draft', ctx)
        blind = json.dumps(imaging_ai.image_context(r, include_draft=False))
        self.assertNotIn('radiologist_draft', blind)        # a first analysis is an independent read

    # ---------------------------------------------------------------- reading the answer
    def test_parse_answer_converts_positions(self):
        ans = imaging_ai.parse_answer('```json\n' + json.dumps(ANSWER) + '\n```')
        self.assertEqual(len(ans['labels']), 3)
        a, b, c = ans['labels']
        self.assertEqual(a['box'], [0.1, 0.6, 0.35, 0.25])     # [ymin,xmin,ymax,xmax]/1000 → [x,y,w,h]
        self.assertEqual(b['point'], [0.5, 0.15])              # [y,x] → [x,y]
        self.assertIsNone(c['box']); self.assertIsNone(c['point'])
        self.assertEqual((c['concern'], c['confidence']), ('watch', 'low'))
        self.assertEqual([x['n'] for x in ans['labels']], [1, 2, 3])

    def test_parse_answer_keeps_plain_text(self):
        ans = imaging_ai.parse_answer('Sorry, I can only say the lungs look clear.')
        self.assertEqual(ans['labels'], [])
        self.assertIn('lungs look clear', ans['explanation'])

    # ---------------------------------------------------------------- endpoints and worker
    def test_ask_requires_confirmation_and_ai(self):
        r = self.post('doctor', 'imaging_ai_ask', self.img.pk, {'kind': 'analyse', 'confirm_no_identifiers': True})
        self.assertEqual(r.status_code, 400)                   # AI off
        with AI_ON:
            r = self.post('doctor', 'imaging_ai_ask', self.img.pk, {'kind': 'analyse'})
            self.assertEqual(r.status_code, 400)
            self.assertIn('confirmation', r.json()['error'])
            r = self.post('doctor', 'imaging_ai_ask', self.img.pk, {'kind': 'question', 'question': '  ', 'confirm_no_identifiers': True})
            self.assertEqual(r.status_code, 400)
        self.assertFalse(ImagingAIRun.objects.exists())

    @AI_ON
    def test_analyse_stores_labels_and_audit_digests(self):
        sent = {}

        def post(url, body, headers, timeout):
            sent.update(body)
            return {'text': json.dumps(ANSWER)}
        with mock.patch.object(medical_ai, '_post_json', post):
            r = self.post('radiology', 'imaging_ai_ask', self.img.pk,
                          {'kind': 'analyse', 'confirm_no_identifiers': True, 'redactions': [[0, 0, .3, .2]]})
        self.assertEqual(r.status_code, 200, r.content)
        run = ImagingAIRun.objects.get()
        self.assertEqual(run.status, 'done', run.error)
        self.assertEqual(len(run.labels), 3)
        self.assertEqual(run.redactions, [[0.0, 0.0, 0.3, 0.2]])
        self.assertEqual(len(run.image_digest), 64)
        self.assertEqual(sent['image']['media_type'], 'image/jpeg')
        self.assertNotIn('Lamin', json.dumps(sent['context']))
        self.assertNotIn('radiologist_draft', sent['context'])
        d = r.json()['run']
        self.assertEqual(d['labels'][0]['name'], 'Right lower zone opacity')
        # the thread shows it; the image, its annotations and the report are untouched
        t = self.as_('doctor').get(reverse('imaging_ai_thread', args=[self.img.pk])).json()
        self.assertTrue(t['enabled']); self.assertEqual(len(t['runs']), 1)
        self.img.refresh_from_db(); self.o.refresh_from_db()
        self.assertEqual(self.img.annotations, []); self.assertEqual(self.o.status, 'acquired')

    @AI_ON
    def test_question_sends_draft_and_earlier_answers(self):
        ImagingAIRun.objects.create(image=self.img, order=self.o, kind='analyse', status='done', summary='Consolidation right base',
                                    labels=[{'n': 1, 'name': 'Opacity'}])
        sent = {}

        def post(url, body, headers, timeout):
            sent.update(body)
            return {'text': json.dumps({'summary': 'Unlikely TB.', 'labels': [], 'explanation': '## Answer\nNo cavity.'})}
        with mock.patch.object(medical_ai, '_post_json', post):
            r = self.post('nurse', 'imaging_ai_ask', self.img.pk, {'kind': 'question', 'question': 'Could Lamin have TB?', 'confirm_no_identifiers': True})
        run = ImagingAIRun.objects.latest('id')
        self.assertEqual(run.status, 'done', run.error)
        self.assertIn('[patient]', sent['instructions'])
        self.assertNotIn('Lamin', sent['instructions'])
        self.assertEqual(sent['context']['earlier_questions_on_this_image'][0]['answer_summary'], 'Consolidation right base')
        self.assertIn('[patient]', sent['context']['radiologist_draft']['findings'])
        self.assertEqual(r.json()['run']['summary'], 'Unlikely TB.')

    @GEMINI
    def test_gemini_gets_an_image_part(self):
        sent = {}

        def post(url, body, headers, timeout):
            sent.update(body=body, url=url, headers=headers)
            return {'choices': [{'message': {'content': json.dumps(ANSWER)}, 'finish_reason': 'stop'}]}
        with mock.patch.object(medical_ai, '_post_json', post):
            self.post('doctor', 'imaging_ai_ask', self.img.pk, {'kind': 'analyse', 'confirm_no_identifiers': True})
        run = ImagingAIRun.objects.get()
        self.assertEqual(run.status, 'done', run.error)
        self.assertTrue(sent['url'].endswith('/openai/chat/completions'))
        parts = sent['body']['messages'][1]['content']
        self.assertEqual(parts[1]['type'], 'image_url')
        self.assertTrue(parts[1]['image_url']['url'].startswith('data:image/jpeg;base64,'))
        self.assertEqual(run.model_name, 'gemini-vision')

    @AI_ON
    def test_failure_is_recorded_and_retry_allowed(self):
        def post(url, body, headers, timeout):
            raise medical_ai.AIServiceError(503, 'busy')
        with mock.patch.object(medical_ai, '_post_json', post):
            r = self.post('doctor', 'imaging_ai_ask', self.img.pk, {'kind': 'analyse', 'confirm_no_identifiers': True})
        self.assertEqual(r.json()['run']['status'], 'failed')
        self.assertNotIn('busy', r.json()['run']['error'])     # no provider details to the page
        with mock.patch.object(medical_ai, '_post_json', lambda *a, **k: {'text': json.dumps(ANSWER)}):
            r = self.post('doctor', 'imaging_ai_ask', self.img.pk, {'kind': 'analyse', 'confirm_no_identifiers': True})
        self.assertEqual(r.json()['run']['status'], 'done')

    def test_preview_rate_and_permissions(self):
        r = self.post('doctor', 'imaging_ai_preview', self.img.pk, {'redactions': [[0, 0, .5, .5]]})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d['image'].startswith('data:image/jpeg;base64,'))
        self.assertNotIn('Lamin', d['context'])
        run = ImagingAIRun.objects.create(image=self.img, order=self.o, status='done', summary='x')
        self.assertEqual(self.post('doctor', 'imaging_ai_rate', run.pk, {'helpful': '1'}).status_code, 200)
        run.refresh_from_db(); self.assertTrue(run.helpful)
        self.assertEqual(self.as_('reception').get(reverse('imaging_ai_thread', args=[self.img.pk])).status_code, 403)
        self.assertEqual(self.post('lab', 'imaging_ai_ask', self.img.pk, {'confirm_no_identifiers': True}).status_code, 403)

    def test_page_shows_dr_flow_to_clinicians_only(self):
        page = self.as_('doctor').get(reverse('imaging_detail', args=[self.o.pk])).content.decode()
        self.assertIn('id="iva"', page)
        self.assertIn('imaging-ai.js', page)
        self.client.logout()
        page = self.as_('reception').get(reverse('imaging_detail', args=[self.o.pk])).content.decode()
        self.assertNotIn('id="iva"', page)
