"""Doctor's reports adopted from the AI summary: adopt, edit, files, AI helpers, sign, amend, PDF and ZIP, verify."""
import io
import json
import shutil
import tempfile
import zipfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from . import medical_ai, reports
from .models import AISuggestion, DoctorReport, ImagingImage, ImagingOrder, ReportAssist
from .test_evidence import Base

AI_TEXT = """## Summary
Low haemoglobin, **likely iron deficiency**. See [WHO](https://www.who.int/a).
## Urgent / red flags
- None now.
## Suggested next steps
1. Check ferritin
   - reason: confirm iron deficiency
## Differential considerations
- Malaria, sickle cell
## Hospital range vs WHO reference
Both agree.
## Gaps and uncertainties
- No examination recorded."""


def png(color=(200, 30, 40), size=(40, 30)):
    from PIL import Image
    b = io.BytesIO()
    Image.new('RGB', size, color).save(b, 'PNG')
    return b.getvalue()


def tiny_pdf():
    from reportlab.pdfgen import canvas
    b = io.BytesIO()
    c = canvas.Canvas(b); c.drawString(100, 750, 'Outside ECG'); c.save()
    return b.getvalue()


class ReportBase(Base):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.ov = override_settings(MEDIA_ROOT=self.media)
        self.ov.enable()

    def tearDown(self):
        self.ov.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def suggestion(self):
        lr, e = self.result(self.man, {self.hb: 9.0}, dx='Anaemia')
        s = AISuggestion.objects.create(lab_request=lr, encounter=e, requested_by=self.users['doctor'], status='done', text=AI_TEXT,
                                        provider='anthropic', model_name='claude-test', finished_at=timezone.now(),
                                        sources=[{'title': 'WHO anaemia', 'url': 'https://www.who.int/a', 'cited': True}])
        return lr, e, s

    def adopted(self):
        lr, e, s = self.suggestion()
        r = self.as_('doctor').post(f'/labs/ai/{s.pk}/adopt/')
        rep = DoctorReport.objects.get()
        self.assertRedirects(r, f'/reports/{rep.pk}/', fetch_redirect_response=False)
        return lr, e, s, rep


AI_ON = override_settings(CLINICAL_AI_ENABLED=True, CLINICAL_AI_PROVIDER='endpoint', CLINICAL_AI_ENDPOINT='https://ai.example.org/review')


class AdoptTests(ReportBase):
    @AI_ON
    def test_summary_is_clickable_and_adopts_into_report_sections(self):
        lr, e, s = self.suggestion()
        page = self.as_('doctor').get(f'/labs/requests/{lr.pk}/guidance/')
        self.assertContains(page, 'data-adopt="gd-adopt-form"')
        self.assertContains(page, f'/labs/ai/{s.pk}/adopt/')
        self.assertContains(page, 'data-ai-state="done"')
        self.assertContains(page, 'data-robodoc-call')
        self.as_('doctor').post(f'/labs/ai/{s.pk}/adopt/')
        rep = DoctorReport.objects.get()
        self.assertEqual((rep.status, rep.source_suggestion, rep.lab_request), ('draft', s, lr))
        for h in ('## Clinical summary', '## Red flags', '## Plan', '## Differential diagnosis', "## Doctor's assessment"):
            self.assertIn(h, rep.body)
        self.assertIn('[WHO](https://www.who.int/a)', rep.body)
        self.assertEqual(reports.edited_pct(rep), 0)
        # adopting again opens the same draft; the panel now links to it
        self.as_('doctor').post(f'/labs/ai/{s.pk}/adopt/')
        self.assertEqual(DoctorReport.objects.count(), 1)
        self.assertContains(self.as_('doctor').get(f'/labs/requests/{lr.pk}/guidance/'), 'Continue editing')
        self.assertContains(self.as_('doctor').get(f'/labs/requests/{lr.pk}/'), rep.number)

    @AI_ON
    def test_who_may_adopt(self):
        lr, e, s = self.suggestion()
        self.assertEqual(self.as_('lab').post(f'/labs/ai/{s.pk}/adopt/').status_code, 403)
        self.assertNotContains(self.as_('lab').get(f'/labs/requests/{lr.pk}/guidance/'), 'data-adopt=')
        self.assertEqual(self.as_('nurse').post(f'/labs/ai/{s.pk}/adopt/').status_code, 302)

    def test_newer_summary_can_replace_draft(self):
        lr, e, s, rep = self.adopted()
        s2 = AISuggestion.objects.create(lab_request=lr, encounter=e, status='done', text='## Summary\nNew view.', finished_at=timezone.now())
        self.assertContains(self.as_('doctor').get(f'/reports/{rep.pk}/'), 'newer AI summary')
        self.as_('doctor').post(f'/reports/{rep.pk}/replace/{s2.pk}/')
        rep.refresh_from_db()
        self.assertIn('New view.', rep.body)
        self.assertEqual(rep.source_suggestion, s2)


class EditSignTests(ReportBase):
    def test_edit_files_sign_pdf_zip_verify_amend(self):
        lr, e, s, rep = self.adopted()
        c = self.as_('doctor')
        page = c.get(f'/reports/{rep.pk}/')
        self.assertContains(page, 'id="dr-editor"')
        self.assertContains(page, 'robodoc.js')
        # an imaging study with an image on the same visit
        o = ImagingOrder.objects.create(encounter=e, modality='xray', region='Chest PA', status='reported', impression='Clear lungs')
        img = ImagingImage.objects.create(order=o, file=SimpleUploadedFile('chest.png', png()), caption='Chest PA')
        # autosave edits
        body = rep.body.replace("(Add your examination findings and final impression here.)", 'Pale conjunctivae. **Iron deficiency anaemia.**')
        r = c.post(f'/reports/{rep.pk}/save/', {'body': body, 'title': 'Anaemia review', 'follow_up': '2030-01-15',
                                                 'include': json.dumps({'labs': True, 'images': [img.pk, 99999], 'attachments': [], 'ai_sources': True})})
        self.assertEqual(r.status_code, 200)
        self.assertGreater(r.json()['edited_pct'], 0)
        rep.refresh_from_db()
        self.assertEqual((rep.title, str(rep.follow_up), rep.include['images']), ('Anaemia review', '2030-01-15', [img.pk]))
        # attachments: an image and a PDF accepted, a fake PDF and an exe refused
        r = c.post(f'/reports/{rep.pk}/files/', {'files': [SimpleUploadedFile('ecg.png', png((0, 0, 0))), SimpleUploadedFile('letter.pdf', tiny_pdf()),
                                                            SimpleUploadedFile('fake.pdf', b'hello'), SimpleUploadedFile('x.exe', b'MZ')]},
                   HTTP_X_REQUESTED_WITH='fetch')
        j = r.json()
        self.assertEqual(len(j['added']), 2)
        self.assertEqual(len(j['errors']), 2)
        rep.refresh_from_db()
        self.assertEqual(len(rep.include['attachments']), 2)
        # draft PDF is watermarked and says not signed
        pdf = c.get(f'/reports/{rep.pk}/pdf/')
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertIn('DRAFT', pdf['Content-Disposition'])
        from pypdf import PdfReader
        text = ''.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
        self.assertIn('Draft', text)
        self.assertIn('Iron deficiency anaemia', text)
        self.assertIn('Outside ECG', text)                 # attached PDF merged at the end
        # nurses cannot sign; the placeholder must be replaced; the review box is required
        self.assertEqual(self.as_('nurse').post(f'/reports/{rep.pk}/sign/', {'reviewed': '1'}).status_code, 403)
        c = self.as_('doctor')
        c.post(f'/reports/{rep.pk}/sign/')
        rep.refresh_from_db(); self.assertEqual(rep.status, 'draft')
        c.post(f'/reports/{rep.pk}/sign/', {'reviewed': '1'})
        rep.refresh_from_db()
        self.assertEqual(rep.status, 'final')
        self.assertEqual(len(rep.content_hash), 64)
        self.assertEqual(rep.content_hash, reports.content_hash(rep))
        # locked
        self.assertEqual(c.post(f'/reports/{rep.pk}/save/', {'body': 'x'}).status_code, 409)
        self.assertEqual(c.post(f'/reports/{rep.pk}/files/', {'files': [SimpleUploadedFile('a.png', png())]}).status_code, 403)
        # ZIP has everything with a manifest
        z = zipfile.ZipFile(io.BytesIO(c.get(f'/reports/{rep.pk}/zip/').content))
        names = z.namelist()
        root = f'{rep.number}_{self.man.mrn}/'
        for f in ('report.pdf', 'report.md', 'lab_results.csv', 'manifest.json', 'README.txt', 'ai/ai_summary_as_received.md', 'ai/sources.json'):
            self.assertIn(root + f, names)
        self.assertTrue(any(n.startswith(root + 'images/') and n.endswith('.png') for n in names))
        self.assertEqual(len([n for n in names if n.startswith(root + 'attachments/')]), 2)
        manifest = json.loads(z.read(root + 'manifest.json'))
        self.assertEqual(manifest['content_hash'], rep.content_hash)
        import hashlib
        for m in manifest['files']:
            self.assertEqual(hashlib.sha256(z.read(root + m['file'])).hexdigest(), m['sha256'])
        self.assertIn('Haemoglobin,Haemoglobin,9.0,g/dL', z.read(root + 'lab_results.csv').decode('utf-8-sig'))
        # public verification shows no patient details
        self.client.logout()
        v = self.client.get(f'/reports/verify/{rep.verify_token}/')
        self.assertContains(v, 'Genuine')
        self.assertNotContains(v, self.man.last_name)
        self.assertNotContains(v, self.man.mrn)
        self.assertContains(self.client.get('/reports/verify/nope/'), 'Not found')
        # tampering is detected
        DoctorReport.objects.filter(pk=rep.pk).update(body='changed')
        self.assertContains(self.client.get(f'/reports/verify/{rep.verify_token}/'), 'Content mismatch')
        DoctorReport.objects.filter(pk=rep.pk).update(body=body)
        # amendment supersedes the original only when signed
        c = self.as_('doctor')
        r = c.post(f'/reports/{rep.pk}/amend/', {'reason': 'Ferritin result added'})
        new = DoctorReport.objects.exclude(pk=rep.pk).get()
        self.assertRedirects(r, f'/reports/{new.pk}/', fetch_redirect_response=False)
        self.assertEqual((new.status, new.amends, new.body), ('draft', rep, body))
        rep.refresh_from_db(); self.assertEqual(rep.status, 'final')
        c.post(f'/reports/{new.pk}/sign/', {'reviewed': '1'})
        rep.refresh_from_db(); new.refresh_from_db()
        self.assertEqual((rep.status, new.status), ('superseded', 'final'))
        self.client.logout()
        self.assertContains(self.client.get(f'/reports/verify/{rep.verify_token}/'), 'Superseded')

    def test_discard_draft(self):
        lr, e, s, rep = self.adopted()
        self.as_('doctor').post(f'/reports/{rep.pk}/discard/')
        self.assertFalse(DoctorReport.objects.exists())

    def test_reception_has_no_access(self):
        lr, e, s, rep = self.adopted()
        self.assertEqual(self.as_('reception').get(f'/reports/{rep.pk}/').status_code, 403)
        self.assertEqual(self.as_('reception').get(f'/reports/{rep.pk}/pdf/').status_code, 403)


class AssistTests(ReportBase):
    def test_off_by_default(self):
        lr, e, s, rep = self.adopted()
        self.assertEqual(self.as_('doctor').post(f'/reports/{rep.pk}/assist/safety/', {'body': 'x'}).status_code, 400)
        self.assertContains(self.as_('doctor').get(f'/reports/{rep.pk}/'), 'helpers are off')

    @override_settings(CLINICAL_AI_ENABLED=True, CLINICAL_AI_PROVIDER='endpoint', CLINICAL_AI_ENDPOINT='https://ai.example.org/review')
    def test_assist_is_deidentified_and_polled(self):
        self.man.phone = '+220 7111111'; self.man.save()
        lr, e, s, rep = self.adopted()
        sent = []

        def post(url, body, headers, timeout):
            sent.append(json.dumps(body, default=str))
            return {'text': '- **Hb 9.0** not addressed in plan'}
        draft = f'Lamin Ceesay ({self.man.mrn}), phone +220 7111111, has anaemia.'
        with mock.patch.object(medical_ai, '_post_json', post):
            r = self.as_('doctor').post(f'/reports/{rep.pk}/assist/safety/', {'body': draft})
        self.assertEqual(r.status_code, 200)
        a = ReportAssist.objects.get()
        self.assertEqual((a.kind, a.status), ('safety', 'done'))
        for secret in ('Lamin', 'Ceesay', self.man.mrn, '7111111'):
            self.assertNotIn(secret, sent[0])
            self.assertNotIn(secret, a.input_text)
        self.assertIn('[PATIENT]', a.input_text)
        self.assertIn('doctor_draft_report', sent[0])
        j = self.as_('doctor').get(r.json()['poll']).json()
        self.assertEqual(j['status'], 'done')
        self.assertIn('<b>Hb 9.0</b>', j['html'])
        self.assertEqual(self.as_('doctor').post(f'/reports/{rep.pk}/assist/nonsense/').status_code, 404)


class PdfMarkdownTests(ReportBase):
    def test_markdown_is_escaped_in_pdf(self):
        from .esign import _styles
        fl = reports.md_flowables('## Head <b>\n1. Step **bold** <script>\n   - sub\n- item [x](https://who.int)', _styles())
        self.assertEqual(len(fl), 3)
        self.assertIn('&lt;b&gt;', fl[0].text)

    def test_ai_to_report_keeps_unknown_headings(self):
        self.assertIn('## Custom', reports.ai_to_report('## Custom\nx'))
