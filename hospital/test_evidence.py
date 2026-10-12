"""Lab result guidance: WHO references, local practice, trusted-source fetching, the guidance panel and AI."""
import json
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from . import evidence, medical_ai
from .models import (AISuggestion, Condition, Department, Encounter, EvidenceFetch, EvidenceItem, LabOrder, LabParameter, LabRequest,
                     LabResultValue, LabTest, Medication, ParameterGuidance, Patient, Prescription, PrescriptionItem, ReferenceRange, StaffProfile)

PW = 'test-only-Pa55word!'


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('bootstrap_hospital', verbosity=0)
        U = get_user_model()
        cls.users = {}
        for role in ['doctor', 'nurse', 'lab', 'reception', 'pharmacy']:
            u = U.objects.create_user(username=role, password=PW)
            StaffProfile.objects.create(user=u, role=role)
            cls.users[role] = u
        cls.dept = Department.objects.get(name='Outpatient')
        cls.man = Patient.objects.create(first_name='Lamin', last_name='Ceesay', dob=date(1980, 5, 1), sex='M')
        cls.woman = Patient.objects.create(first_name='Fatou', last_name='Jobe', dob=date(1994, 3, 2), sex='F')
        cls.hb = LabParameter.objects.get(test__code='HB', code='HB')
        cls.cbc = LabTest.objects.get(code='CBC')

    def as_(self, role):
        self.client.login(username=role, password=PW)
        return self.client

    def result(self, patient, values, test=None, dx='', when=None, outcome='', status='open'):
        """A reported lab request with the given {parameter: value} results; returns (request, encounter)."""
        test = test or self.hb.test
        e = Encounter.objects.create(patient=patient, department=self.dept, reason='Tired', diagnosis=dx, clinician=self.users['doctor'],
                                     outcome=outcome, status=status)
        lr = LabRequest.objects.create(encounter=e, requested_by=self.users['doctor'])
        o = LabOrder.objects.create(encounter=e, request=lr, test=test, status='resulted', resulted_at=when or timezone.now())
        for prm, val in values.items():
            num = Decimal(str(val)) if prm.kind == 'number' else None
            LabResultValue.objects.create(order=o, parameter=prm, value_number=num, value_text='' if num is not None else val,
                                          flag=prm.flag_for(val, patient.sex))
        return lr, e


class WhoReferenceTests(Base):
    def test_seed_is_idempotent_and_keeps_lab_edits(self):
        n = ReferenceRange.objects.filter(source='who').count()
        self.assertGreaterEqual(n, 20)
        r = ReferenceRange.objects.get(seed_key='who:hb-men')
        r.low = Decimal('13.5'); r.save()
        self.assertEqual(evidence.seed_who_references(), 0)
        self.assertEqual(ReferenceRange.objects.get(seed_key='who:hb-men').low, Decimal('13.5'))

    def test_man_low_by_hospital_but_not_anaemic_by_who(self):
        lr, e = self.result(self.man, {self.hb: 13.2})
        who, ctx = evidence.who_for_request(lr)
        v = LabResultValue.objects.get(order__request=lr)
        self.assertEqual(v.flag, 'L')                                    # hospital range 13.5–17.5
        labels = [(w['ref'].label, w['band']['label']) for w in who[v.pk]]
        self.assertEqual(labels, [('Anaemia cut-off', 'No anaemia')])
        self.assertFalse(evidence.agreement(v, who[v.pk])['agree'])

    def test_high_value_is_left_to_the_hospital_range(self):
        lr, e = self.result(self.man, {self.hb: 19.5})
        who, ctx = evidence.who_for_request(lr)
        v = LabResultValue.objects.get(order__request=lr)
        a = evidence.agreement(v, who[v.pk])
        self.assertIsNone(a['agree'])
        self.assertIn('no upper limit', a['text'])

    def test_severity_band_and_malaria_threshold(self):
        lr, e = self.result(self.man, {self.hb: 6.5}, dx='Severe malaria')
        who, ctx = evidence.who_for_request(lr)
        self.assertTrue(ctx['malaria'])
        rows = {w['ref'].label: w for w in who[LabResultValue.objects.get(order__request=lr).pk]}
        self.assertEqual(rows['Anaemia cut-off']['band']['label'], 'Severe anaemia')
        self.assertTrue(rows['Severe malaria criterion: severe anaemia']['outside'])

    def test_pregnancy_trimester_from_record(self):
        Encounter.objects.create(patient=self.woman, department=self.dept, reason='Antenatal visit', diagnosis='Pregnancy 20 weeks',
                                 clinician=self.users['doctor'])
        lr, e = self.result(self.woman, {self.hb: 10.6})
        who, ctx = evidence.who_for_request(lr)
        self.assertEqual((ctx['pregnant'], ctx['trimester']), (True, 2))
        (w,) = who[LabResultValue.objects.get(order__request=lr).pk]
        self.assertEqual((w['ref'].condition, str(w['ref'].low), w['band']['label']), ('t2', '10.5000', 'No anaemia'))

    def test_not_pregnant_after_delivery_and_inflammation_changes_ferritin(self):
        Condition.objects.create(patient=self.woman, name='Delivered, postpartum', status='active')
        crp = LabParameter.objects.get(code='CRP')
        self.result(self.woman, {crp: 40}, test=crp.test)
        ferr = LabParameter.objects.get(code='FERR')
        lr, e = self.result(self.woman, {ferr: 50}, test=ferr.test)
        who, ctx = evidence.who_for_request(lr)
        self.assertFalse(ctx['pregnant'])
        self.assertTrue(ctx['inflammation'])
        (w,) = who[LabResultValue.objects.get(order__request=lr).pk]
        self.assertEqual((w['ref'].low, w['outside']), (Decimal('70.0000'), True))   # iron deficiency when inflamed: < 70

    def test_unit_mismatch_is_never_compared(self):
        ReferenceRange.objects.filter(code='HB').update(unit='g/L')
        lr, e = self.result(self.man, {self.hb: 9})
        (w,) = evidence.who_for_request(lr)[0][LabResultValue.objects.get(order__request=lr).pk]
        self.assertFalse(w['same_unit'])
        self.assertIsNone(w['outside'])


class PracticeTests(Base):
    def test_what_clinicians_did_next_needs_three_patients(self):
        ferr = LabTest.objects.get(code='FERR')
        iron = Medication.objects.get(name='Ferrous sulfate')
        t0 = timezone.now() - timedelta(days=20)
        for i in range(3):
            p = Patient.objects.create(first_name='P', last_name=str(i), dob=date(1985, 1, 1), sex='M')
            lr, e = self.result(p, {self.hb: 9.0}, when=t0, outcome='improved', status='completed')
            o = LabOrder.objects.create(encounter=e, test=ferr)
            LabOrder.objects.filter(pk=o.pk).update(created_at=t0 + timedelta(days=1))
            rx = Prescription.objects.create(encounter=e, allergy_reviewed=True, state='dispensed')
            Prescription.objects.filter(pk=rx.pk).update(created_at=t0 + timedelta(hours=2))
            PrescriptionItem.objects.create(prescription=rx, medication=iron, units_per_dose=1, frequency='OD', duration_days=30, quantity=30)
            if i == 1:
                pr = evidence.practice_after(self.hb, 'L')
                self.assertEqual((pr['n'], pr['tests']), (2, []))           # below the minimum group: nothing shown
        pr = evidence.practice_after(self.hb, 'L', exclude_patient=self.man)
        self.assertEqual(pr['n'], 3)
        self.assertEqual([(t['code'], t['pct']) for t in pr['tests']], [('FERR', 100)])
        self.assertEqual((pr['meds'][0]['pct'], pr['meds'][0]['success']), (100, 100))
        self.assertEqual(pr['outcomes'][0]['label'], 'Improved')


MEDLINE_JSON = json.dumps({'feed': {'entry': [{'title': {'_value': 'Hemoglobin Test'}, 'link': [{'href': 'https://medlineplus.gov/lab-tests/hemoglobin-test/'}],
                                               'summary': {'_value': '<p>A hemoglobin test measures <b>hemoglobin</b>.</p>'}},
                                              {'title': {'_value': 'Evil'}, 'link': [{'href': 'https://example.com/x'}], 'summary': {'_value': ''}}]}})
TOPICS_XML = ('<nlmSearchResult><list><document rank="0" url="https://medlineplus.gov/anemia.html"><content name="title">'
              '&lt;span class="qt0"&gt;Anemia&lt;/span&gt;</content><content name="FullSummary">&lt;p&gt;Anemia is a condition…&lt;/p&gt;</content>'
              '</document></list></nlmSearchResult>')
ESEARCH = json.dumps({'esearchresult': {'idlist': ['111']}})
ESUMMARY = json.dumps({'result': {'111': {'title': 'Iron deficiency anaemia: a guideline', 'pubdate': '2024 Jan', 'source': 'BMJ',
                                          'pubtype': ['Practice Guideline', 'Journal Article']}}})
EFETCH = '<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>111</PMID><Article><Abstract><AbstractText>Treat with oral iron.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'
WHO_HTML = ('<html><head><title>Anaemia</title><meta name="description" content="WHO anaemia fact sheet"></head><body><nav><li>Menu</li></nav>'
            '<h1>Anaemia</h1><h2>Key facts</h2><ul><li>Anaemia affects 40% of children.</li><li>Iron deficiency is a common cause.</li></ul>'
            '<h2>Overview</h2><p>' + 'Text ' * 30 + '</p><script>var x = "<li>no</li>";</script></body></html>')


def fake_get(url, accept='*/*', timeout=15, robots=False):
    if 'connect.medlineplus.gov' in url:
        return MEDLINE_JSON
    if 'wsearch.nlm.nih.gov' in url:
        return TOPICS_XML
    if 'esearch' in url:
        return ESEARCH
    if 'esummary' in url:
        return ESUMMARY
    if 'efetch' in url:
        return EFETCH
    if 'who.int' in url:
        return WHO_HTML
    raise AssertionError(url)


@override_settings(MEDICAL_EVIDENCE_FETCH=True)
class FetchTests(Base):
    def test_parsers_and_trusted_domains_only(self):
        with mock.patch.object(evidence, 'http_get', fake_get):
            ml = evidence.medlineplus_lab_test('718-7')
            self.assertEqual([(x['title'], x['summary']) for x in ml], [('Hemoglobin Test', 'A hemoglobin test measures hemoglobin .')])
            self.assertEqual(evidence.medlineplus_topics('anemia')[0]['title'], 'Anemia')
            pm = evidence.pubmed_guidelines('anemia')[0]
            self.assertEqual((pm['url'], pm['kind']), ('https://pubmed.ncbi.nlm.nih.gov/111/', 'practice guideline'))
            self.assertIn('Treat with oral iron.', pm['summary'])
            who = evidence.who_fact_sheet('https://www.who.int/news-room/fact-sheets/detail/anaemia')[0]
            self.assertEqual(who['title'], 'Anaemia')
            self.assertIn('Iron deficiency is a common cause.', who['summary'])
            self.assertNotIn('Menu', who['summary'])
        self.assertTrue(evidence.is_trusted('https://pubmed.ncbi.nlm.nih.gov/1/'))
        self.assertFalse(evidence.is_trusted('https://who.int.evil.com/x'))
        with self.assertRaises(ValueError):
            evidence.http_get('https://example.com/')
        with self.assertRaises(ValueError):
            evidence.http_get('http://www.who.int/')                    # HTTPS only

    def test_robots_txt_is_obeyed(self):
        class R:
            def __init__(self, body): self.body = body
            def read(self, n=-1): return self.body
            def __enter__(self): return self
            def __exit__(self, *a): return False
        evidence._ROBOTS.clear()
        with mock.patch('urllib.request.urlopen', return_value=R(b'User-agent: *\nDisallow: /private/')):
            self.assertTrue(evidence.robots_allow('https://www.who.int/news-room/fact-sheets/detail/anaemia'))
            self.assertFalse(evidence.robots_allow('https://www.who.int/private/page'))
        evidence._ROBOTS.clear()

    def test_refresh_stores_ranked_items_and_survives_a_failing_source(self):
        def flaky(url, **kw):
            if 'eutils' in url:
                raise OSError('down')
            return fake_get(url, **kw)
        with mock.patch.object(evidence, 'http_get', flaky):
            f = evidence.refresh_evidence('HB:L', 'HB', 'Haemoglobin', 'g/dL')
        self.assertEqual(f.status, 'done')
        self.assertIn('pubmed: OSError', f.error)
        items = list(EvidenceItem.objects.filter(key='HB:L'))
        self.assertEqual(items[0].source, 'who')                            # WHO first
        self.assertEqual({i.source for i in items}, {'who', 'medlineplus'})
        self.assertFalse(any('example.com' in i.url for i in items))

    def test_submitting_abnormal_results_fetches_sources(self):
        e = Encounter.objects.create(patient=self.man, department=self.dept, reason='Tired', clinician=self.users['doctor'])
        lr = LabRequest.objects.create(encounter=e, requested_by=self.users['doctor'])
        o = LabOrder.objects.create(encounter=e, request=lr, test=self.hb.test, status='processing')
        with mock.patch.object(evidence, 'http_get', fake_get), self.captureOnCommitCallbacks(execute=True):
            r = self.as_('lab').post(f'/labs/requests/{lr.pk}/results/', {f'p_{o.pk}_{self.hb.pk}': '9.1', 'action': 'submit'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(EvidenceFetch.objects.get(key='HB:L').status, 'done')   # eager worker in tests
        self.assertTrue(EvidenceItem.objects.filter(key='HB:L', source='who').exists())

    def test_changed_source_page_puts_reference_on_review(self):
        r = ReferenceRange.objects.get(seed_key='who:hb-men')
        ReferenceRange.objects.exclude(citation_url=r.citation_url).update(citation_url='')
        with mock.patch.object(evidence, 'http_get', return_value='<h1>A</h1><p>' + 'x ' * 40 + '</p>'):
            evidence.check_reference_sources()
        self.assertEqual(ReferenceRange.objects.get(pk=r.pk).status, 'curated')     # first check only records the fingerprint
        with mock.patch.object(evidence, 'http_get', return_value='<h1>B changed</h1><p>' + 'y ' * 40 + '</p>'):
            self.assertGreater(evidence.check_reference_sources(), 0)
        self.assertEqual(ReferenceRange.objects.get(pk=r.pk).status, 'review')


class GuidanceViewTests(Base):
    def test_request_page_shows_who_column_and_guidance(self):
        lr, e = self.result(self.man, {self.hb: 9.0})
        r = self.as_('doctor').get(f'/labs/requests/{lr.pk}/')
        self.assertContains(r, '<th>WHO</th>', html=False)
        self.assertContains(r, 'Moderate anaemia')
        self.assertContains(r, 'id="guidance"')
        self.assertContains(self.as_('doctor').get(f'/labs/requests/{lr.pk}/report/'), 'WHO: ≥ 13 g/dL')

    def test_fragment_brings_everything_together(self):
        lr, e = self.result(self.man, {self.hb: 9.0})
        ParameterGuidance.objects.create(code='HB', direction='L', title='Anaemia work-up', steps='Check stool for hookworm\nStart iron if ferritin low')
        EvidenceItem.objects.create(key='HB:L', source='who', title='Anaemia fact sheet', url='https://www.who.int/news-room/fact-sheets/detail/anaemia',
                                    summary='Key facts…')
        r = self.as_('doctor').get(f'/labs/requests/{lr.pk}/guidance/?first=1')
        for text in ('Anaemia cut-off', 'Moderate anaemia', 'Anaemia work-up', 'Check stool for hookworm', 'Anaemia fact sheet',
                     'Not enough similar cases', 'AI is not connected', 'data-kb="HB"'):
            self.assertContains(r, text)
        self.assertNotContains(r, 'Lamin')                                 # the panel never needs the name
        self.assertEqual(self.as_('reception').get(f'/labs/requests/{lr.pk}/guidance/').status_code, 403)
        self.assertEqual(self.as_('pharmacy').get(f'/labs/requests/{lr.pk}/guidance/').status_code, 403)
        self.assertEqual(self.as_('lab').get(f'/labs/requests/{lr.pk}/guidance/').status_code, 200)

    def test_refresh_needs_fetching_switched_on(self):
        lr, e = self.result(self.man, {self.hb: 9.0})
        self.assertEqual(self.as_('doctor').post(f'/labs/requests/{lr.pk}/guidance/refresh/').status_code, 400)
        with override_settings(MEDICAL_EVIDENCE_FETCH=True), mock.patch.object(evidence, 'http_get', fake_get):
            r = self.as_('doctor').post(f'/labs/requests/{lr.pk}/guidance/refresh/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(EvidenceItem.objects.filter(key='HB:L').exists())

    def test_references_page(self):
        r = ReferenceRange.objects.get(seed_key='who:hb-men')
        self.assertContains(self.as_('doctor').get('/labs/references/'), 'Anaemia cut-off')
        self.assertEqual(self.as_('doctor').post('/labs/references/', {'action': 'verify', 'pk': r.pk}).status_code, 403)
        self.as_('lab').post('/labs/references/', {'action': 'verify', 'pk': r.pk})
        self.assertEqual(ReferenceRange.objects.get(pk=r.pk).status, 'verified')
        self.as_('lab').post('/labs/references/', {'action': 'add', 'code': 'PLT', 'label': 'Thrombocytopenia', 'source': 'international',
                                                   'kind': 'threshold', 'low': '150', 'unit': '×10⁹/L', 'citation_title': 'Local review 2026',
                                                   'citation_url': 'https://example.org/x'})
        self.assertTrue(ReferenceRange.objects.filter(code='PLT', status='verified').exists())
        self.as_('lab').post('/labs/references/', {'action': 'add', 'code': 'NOPE', 'low': '1', 'source': 'who', 'kind': 'interval', 'citation_title': 'x'})
        self.assertFalse(ReferenceRange.objects.filter(code='NOPE').exists())


def anthropic_reply(stop='end_turn', text='## Summary\nModerate anaemia.\n## Suggested next steps\n1. Order **ferritin** <script>x</script>\n   - reason: iron'):
    return {'stop_reason': stop, 'content': [
        {'type': 'server_tool_use', 'id': 's1', 'name': 'web_search', 'input': {'query': 'WHO anaemia guideline'}},
        {'type': 'web_search_tool_result', 'tool_use_id': 's1', 'content': [{'type': 'web_search_result', 'url': 'https://www.who.int/a', 'title': 'WHO A'}]},
        {'type': 'text', 'text': text, 'citations': [{'type': 'web_search_result_location', 'url': 'https://www.who.int/a', 'title': 'WHO A',
                                                      'cited_text': 'Anaemia is…'}]}]}


class AITests(Base):
    def test_off_by_default(self):
        lr, e = self.result(self.man, {self.hb: 9.0})
        self.assertEqual(self.as_('doctor').post(f'/labs/requests/{lr.pk}/ai/').status_code, 400)
        self.assertContains(self.as_('doctor').get(f'/labs/requests/{lr.pk}/ai-context/'), 'AI not connected')

    @override_settings(CLINICAL_AI_ENABLED=True, ANTHROPIC_API_KEY='sk-test', CLINICAL_AI_PROVIDER='')
    def test_anthropic_answer_with_sources_and_pause_turn(self):
        self.man.phone = '+220 7111111'; self.man.save()
        lr, e = self.result(self.man, {self.hb: 9.0}, dx='Anaemia')
        sent = []

        def post(url, body, headers, timeout):
            sent.append(json.loads(json.dumps(body, default=str)))
            return anthropic_reply('pause_turn', '') if len(sent) == 1 else anthropic_reply()
        with mock.patch.object(medical_ai, '_post_json', post):
            r = self.as_('doctor').post(f'/labs/requests/{lr.pk}/ai/')
        self.assertEqual(r.status_code, 200)
        s = AISuggestion.objects.get()
        self.assertEqual((s.status, s.provider, s.model_name), ('done', 'anthropic', 'claude-sonnet-5-5'))
        self.assertEqual(len(sent), 2)                                       # paused turn continued once
        self.assertEqual(sent[1]['messages'][1]['role'], 'assistant')
        tool = sent[0]['tools'][0]
        self.assertEqual((tool['type'], 'who.int' in tool['allowed_domains']), ('web_search_20250305', True))
        blob = json.dumps(sent[0])
        for secret in ('Lamin', 'Ceesay', self.man.mrn, '7111111', '1980-05-01'):
            self.assertNotIn(secret, blob)
        self.assertIn('Anaemia cut-off', blob)
        self.assertEqual(s.sources[0], {'title': 'WHO A', 'url': 'https://www.who.int/a', 'cited': True, 'quote': 'Anaemia is…'})
        self.assertEqual(s.searches, ['WHO anaemia guideline'])
        self.assertEqual(len(s.context_digest), 64)
        page = self.as_('doctor').get(f'/labs/requests/{lr.pk}/guidance/')
        self.assertContains(page, '<b>ferritin</b>')
        self.assertContains(page, '&lt;script&gt;')                          # AI text is escaped
        self.assertNotContains(page, '<script>x</script>')
        self.assertContains(page, '<span class="sub">reason: iron</span>')
        self.as_('doctor').post(f'/labs/ai/{s.pk}/rate/', {'helpful': '1'})
        self.assertTrue(AISuggestion.objects.get().helpful)

    @override_settings(CLINICAL_AI_ENABLED=True, ANTHROPIC_API_KEY='sk-test')
    def test_failure_is_shown_not_raised(self):
        lr, e = self.result(self.man, {self.hb: 9.0})
        with mock.patch.object(medical_ai, '_post_json', side_effect=RuntimeError('AI service returned HTTP 529')):
            self.as_('doctor').post(f'/labs/requests/{lr.pk}/ai/')
        self.assertEqual(AISuggestion.objects.get().status, 'failed')
        self.assertContains(self.as_('doctor').get(f'/labs/requests/{lr.pk}/guidance/'), 'HTTP 529')
        self.assertEqual(self.as_('lab').post(f'/labs/requests/{lr.pk}/ai/').status_code, 403)   # lab staff see guidance, doctors ask the AI

    @override_settings(CLINICAL_AI_ENABLED=True, CLINICAL_AI_PROVIDER='endpoint', CLINICAL_AI_ENDPOINT='https://ai.example.org/review')
    def test_own_endpoint(self):
        lr, e = self.result(self.man, {self.hb: 9.0})
        with mock.patch.object(medical_ai, '_post_json', return_value={'text': 'Check ferritin.', 'sources': [{'title': 'X', 'url': 'https://www.who.int/x'}]}):
            self.as_('doctor').post(f'/labs/requests/{lr.pk}/ai/')
        s = AISuggestion.objects.get()
        self.assertEqual((s.status, s.text, s.sources[0]['url']), ('done', 'Check ferritin.', 'https://www.who.int/x'))


class MarkdownTests(TestCase):
    def test_simple_md(self):
        from .templatetags.evidence_tags import simple_md
        html = simple_md('## Next\n1. Do **this** [WHO](https://www.who.int/x)\n2. <img src=x onerror=alert(1)>\n- [bad](javascript:alert(1))')
        self.assertIn('<h4>Next</h4><ol><li>Do <b>this</b> <a href="https://www.who.int/x"', html)
        self.assertIn('&lt;img', html)
        self.assertNotIn('href="javascript', html)
