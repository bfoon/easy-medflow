"""Dr. Flow: prescribing and test-ordering advice, the safety gate, the chart brief, and questions with pictures."""
import json
from datetime import date
from unittest import mock

from django.test import override_settings

from . import drflow, drflow_ask, medical_ai
from .models import (Allergy, AuditEvent, Condition, DrFlowAsk, Encounter, LabOrder, LabParameter, LabRequest, LabResultValue, LabTest,
                     Medication, Prescription, PrescriptionItem)
from .test_evidence import Base

AI_ON = override_settings(CLINICAL_AI_ENABLED=True, CLINICAL_AI_PROVIDER='endpoint', CLINICAL_AI_ENDPOINT='https://ai.example.org/review')


def med(name, generic='', strength='', form='tablet'):
    return Medication.objects.get_or_create(name=name, defaults={'generic_name': generic or name.lower(), 'strength': strength, 'form': form})[0]


class DrFlowBase(Base):
    def visit(self, patient=None, reason='Review', dx='', **kw):
        return Encounter.objects.create(patient=patient or self.man, department=self.dept, reason=reason, diagnosis=dx, clinician=self.users['doctor'], **kw)

    def titles(self, findings):
        return [f['title'] for f in findings]

    def rx(self, e, *meds, **line):
        return drflow.rx_findings(e, [{'med': m, 'route': 'oral', **line} for m in meds])


class PrescribingRules(DrFlowBase):
    def test_interactions_and_duplicates(self):
        e = self.visit()
        t = self.titles(self.rx(e, med('RHZE', 'rifampicin/isoniazid/pyrazinamide/ethambutol'), med('Artemether/Lumefantrine', 'artemether-lumefantrine')))
        self.assertIn('Rifampicin with artemether-lumefantrine', t)
        f = self.rx(e, med('Morphine', 'morphine sulfate'), med('Diazepam'))
        self.assertEqual((f[0]['level'], f[0]['title']), ('danger', 'Breathing risk: opioid with a sedative'))
        self.assertIn('Two NSAIDs', self.titles(self.rx(e, med('Ibuprofen'), med('Diclofenac'))))
        self.assertIn('Two medicines that lengthen the QT interval', self.titles(self.rx(e, med('Quinine', 'quinine sulfate'), med('Haloperidol'))))
        self.assertEqual(self.rx(e, med('Paracetamol'), med('Amoxicillin')), [])            # nothing to say about a safe pair

    def test_interaction_with_a_medicine_from_an_earlier_prescription(self):
        e = self.visit()
        p = Prescription.objects.create(encounter=e)
        PrescriptionItem.objects.create(prescription=p, medication=med('Lisinopril', strength='10 mg'), quantity=30)
        f = [x for x in self.rx(e, med('Ibuprofen')) if x['kind'] == 'interaction'][0]
        self.assertIn(f'already prescribed ({p.number})', f['detail'])
        self.assertEqual(self.titles(drflow.rx_findings(e, [{'med': med('Ibuprofen')}], exclude_prescription=p)), [])   # editing that prescription

    def test_topical_medicines_are_not_treated_as_systemic(self):
        e = self.visit()
        self.assertEqual(drflow.rx_findings(e, [{'med': med('Chloramphenicol', strength='0.5%'), 'route': 'eye'}, {'med': med('Warfarin'), 'route': 'oral'}]), [])

    def test_pregnancy(self):
        e = self.visit(self.woman, reason='ANC visit')
        Condition.objects.create(patient=self.woman, name='Pregnancy, 2nd trimester')
        f = {x['title']: x for x in self.rx(e, med('Lisinopril'), med('Doxycycline'), med('Artemether/Lumefantrine', 'artemether-lumefantrine'))}
        self.assertEqual(f['Lisinopril in pregnancy']['level'], 'danger')
        self.assertEqual(f['Doxycycline in pregnancy']['level'], 'warn')
        self.assertNotIn('Artemether/Lumefantrine in pregnancy', f)                         # WHO: safe in all trimesters
        not_known = self.visit(self.woman, reason='Headache')
        Condition.objects.filter(patient=self.woman).delete()
        self.assertIn('Check pregnancy before Lisinopril', self.titles(self.rx(not_known, med('Lisinopril'))))

    def test_word_boundaries(self):
        """'anc' inside 'pregnancy' or 'chance' must not count as an antenatal visit."""
        e = self.visit(self.woman, reason='Small chance of infection')
        self.assertFalse(drflow.patient_facts(e)['pregnant'])

    def test_children_and_older_people(self):
        kid = self.man.__class__.objects.create(first_name='Musa', last_name='Bah', dob=date(date.today().year - 6, 1, 1), sex='M')
        t = self.titles(self.rx(self.visit(kid), med('Aspirin', 'acetylsalicylic acid'), med('Tramadol'), med('Doxycycline')))
        for x in ('Aspirin under 16 years', 'Tramadol under 12 years', 'Doxycycline under 8 years', 'Weigh the child for Doxycycline'):
            self.assertIn(x, t)
        old = self.man.__class__.objects.create(first_name='Ousman', last_name='Sowe', dob=date(1950, 1, 1), sex='M')
        self.assertIn('Glibenclamide in an older person', self.titles(self.rx(self.visit(old), med('Glibenclamide'))))

    def test_g6pd(self):
        e = self.visit()
        prim = med('Primaquine')
        self.assertIn('G6PD status unknown for Primaquine', self.titles(self.rx(e, prim)))
        lr = LabRequest.objects.create(encounter=e)
        o = LabOrder.objects.create(encounter=e, request=lr, test=LabTest.objects.get(code='G6PD'), status='verified', resulted_at=e.created_at)
        LabResultValue.objects.create(order=o, parameter=LabParameter.objects.get(code='G6PD'), value_text='Deficient', flag='A')
        f = self.rx(e, prim)
        self.assertEqual((f[0]['level'], f[0]['title']), ('danger', 'Primaquine with G6PD deficiency'))

    def test_results_and_doses(self):
        lr, e = self.result(self.man, {LabParameter.objects.get(code='K'): 6.4})
        self.assertIn('Lisinopril with high potassium', self.titles(self.rx(e, med('Lisinopril'))))
        ibu = med('Ibuprofen', strength='400 mg')
        self.assertIn('Ibuprofen: 3200 mg a day', self.titles(drflow.rx_findings(e, [{'med': ibu, 'dose': '800 mg', 'frequency': 'QDS'}])))
        self.assertIn('Ibuprofen: 3200 mg a day', self.titles(drflow.rx_findings(e, [{'med': ibu, 'units': 2, 'frequency': 'QDS'}])))
        self.assertNotIn('Ibuprofen: 1200 mg a day', self.titles(drflow.rx_findings(e, [{'med': ibu, 'frequency': 'TDS'}])))

    def test_mg_parser(self):
        self.assertEqual([drflow._mg(x) for x in ('500 mg', '1 g', '80/480 mg', '250mcg', 'two tablets', '')], [500, 1000, 80, .25, None, None])

    def test_negative_malaria_test(self):
        lr, e = self.result(self.man, {LabParameter.objects.get(code='RDT'): 'Negative'}, test=LabTest.objects.get(code='MAL'), dx='Malaria')
        self.assertIn('Artemether/Lumefantrine with a negative malaria test',
                      self.titles(self.rx(e, med('Artemether/Lumefantrine', 'artemether-lumefantrine'))))


class SafetyGate(DrFlowBase):
    def line(self, m, **kw):
        return {'medication': m.pk, 'units_per_dose': 1, 'route': 'oral', 'frequency': 'TDS', 'duration_days': 5, 'quantity': 15, **kw}

    def rx_post(self, e, lines, **extra):
        data = {'encounter': e.pk, 'allergy_reviewed': 'on', 'items-TOTAL_FORMS': len(lines), 'items-INITIAL_FORMS': 0,
                'items-MIN_NUM_FORMS': 1, 'items-MAX_NUM_FORMS': 30, **extra}
        for i, ln in enumerate(lines):
            for k, v in ln.items():
                data[f'items-{i}-{k}'] = v
        return self.as_('doctor').post('/prescriptions/new/', data)

    def test_serious_warning_needs_a_reason_and_is_audited(self):
        e = self.visit()
        lines = [self.line(med('Morphine', 'morphine sulfate')), self.line(med('Diazepam'))]
        r = self.rx_post(e, lines)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Dr. Flow found: Breathing risk: opioid with a sedative')
        self.assertFalse(Prescription.objects.exists())
        r = self.rx_post(e, lines, override_reason='Palliative care, monitored on the ward with naloxone available.')
        self.assertEqual(Prescription.objects.count(), 1)
        ev = AuditEvent.objects.filter(action='create', target__startswith='hospital.Prescription').latest('occurred_at')
        self.assertEqual(ev.details['drflow_overridden'], ['Breathing risk: opioid with a sedative'])

    def test_warnings_below_danger_do_not_block(self):
        self.rx_post(self.visit(), [self.line(med('Ibuprofen')), self.line(med('Diclofenac'))])     # two NSAIDs: a warning only
        self.assertEqual(Prescription.objects.count(), 1)

    def test_live_endpoint(self):
        e = self.visit()
        m1, m2 = med('Morphine', 'morphine sulfate'), med('Diazepam')
        j = self.as_('doctor').post('/drflow/rx/', {'encounter': e.pk, 'lines': json.dumps([{'med': m1.pk}, {'med': m2.pk}, {'med': 'x'}])}).json()
        self.assertEqual((j['ready'], j['blocking']), (True, 1))
        self.assertEqual(j['findings'][0]['ask'], {'kind': 'med', 'id': m1.pk, 'topic': 'morphine sulfate'})
        self.assertEqual(self.as_('reception').post('/drflow/rx/', {'encounter': e.pk}).status_code, 403)
        self.assertFalse(self.as_('doctor').post('/drflow/rx/', {}).json()['ready'])


class OrderingRules(DrFlowBase):
    def test_repeat_overlap_already_ordered(self):
        lr, e = self.result(self.man, {self.hb: 13.2}, test=self.cbc)
        hb_test = LabTest.objects.get(code='HB')
        t = {f['title']: f for f in drflow.lab_findings(e, [self.cbc, hb_test])}
        self.assertTrue(any(x.startswith('Complete Blood Count was done on') for x in t))
        self.assertEqual(t['Complete Blood Count already includes Haemoglobin']['actions'], [{'label': 'Untick Haemoglobin', 'untick': hb_test.pk}])
        LabOrder.objects.create(encounter=e, request=LabRequest.objects.create(encounter=e), test=LabTest.objects.get(code='CRP'))
        self.assertIn('C-Reactive Protein is already ordered', self.titles(drflow.lab_findings(e, [LabTest.objects.get(code='CRP')])))

    def test_suggestions(self):
        e = self.visit(self.woman, reason='ANC booking')
        Condition.objects.create(patient=self.woman, name='Pregnancy')
        t = self.titles(drflow.lab_findings(e, []))
        self.assertIn('Antenatal booking: HIV test', t)
        e2 = self.visit(reason='Fever for 3 days')
        f = [x for x in drflow.lab_findings(e2, []) if x['title'] == 'Fever: test for malaria'][0]
        self.assertEqual(f['actions'][0]['test'], LabTest.objects.get(code='MAL').pk)

    def test_endpoint(self):
        e = self.visit()
        j = self.as_('doctor').post('/drflow/labs/', {'encounter': e.pk, 'tests': f'{self.cbc.pk},abc'}).json()
        self.assertTrue(j['ready'])


class Brief(DrFlowBase):
    def test_brief_and_chart(self):
        Allergy.objects.create(patient=self.man, substance='Penicillin', reaction='Rash', severity='severe')
        self.visit()
        b = self.as_('doctor').get(f'/drflow/patients/{self.man.pk}/brief/').json()
        self.assertEqual(b['alerts'], 1)
        self.assertEqual(b['lines'][0]['text'], 'Allergic to Penicillin (severe)')
        page = self.as_('doctor').get(f'/patients/{self.man.pk}/')
        self.assertContains(page, 'data-drflow-chart')
        self.assertContains(page, 'robodoc.js')
        self.assertNotContains(self.as_('reception').get(f'/patients/{self.man.pk}/'), 'data-drflow-chart')
        self.assertEqual(self.as_('reception').get(f'/drflow/patients/{self.man.pk}/brief/').status_code, 403)


OPENI = {'list': [{'imgThumb': '/imgs/150/1.png', 'imgLarge': '/imgs/512/1.png', 'pmcid': 'PMC1', 'image': {'caption': 'Ring <b>forms</b>'}}]}
WIKI_SEARCH = {'query': {'search': [{'title': 'Paracetamol'}]}}
WIKI_MEDIA = {'items': [{'type': 'image', 'title': 'File:Pills.jpg', 'caption': {'text': 'Tablets'}, 'srcset': [{'src': '//upload.wikimedia.org/a/Pills.jpg'}]},
                        {'type': 'image', 'title': 'File:Commons-logo.svg', 'srcset': [{'src': '//upload.wikimedia.org/logo.png'}]},
                        {'type': 'image', 'title': 'File:Evil.jpg', 'srcset': [{'src': 'https://evil.example/x.jpg'}]}]}


def fake_json(url, timeout=10):
    return OPENI if 'openi' in url else WIKI_SEARCH if 'list=search' in url else WIKI_MEDIA


class Ask(DrFlowBase):
    def test_facts_without_ai_or_pictures(self):
        e = self.visit()
        m = med('Paracetamol', strength='500 mg')
        j = self.as_('doctor').post('/drflow/ask/', {'kind': 'med', 'id': m.pk, 'encounter': e.pk}).json()
        self.assertEqual((j['title'], j['ai'], j['images']), ('Paracetamol 500 mg', False, False))
        self.assertIn('In the pharmacy', [f['label'] for f in j['facts']])
        s = self.as_('doctor').get(j['poll']).json()
        self.assertEqual((s['status'], s['html'], s['images']), ('done', '', []))
        t = self.as_('doctor').post('/drflow/ask/', {'kind': 'test', 'id': self.cbc.pk}).json()
        self.assertIn('Sample', [f['label'] for f in t['facts']])
        self.assertEqual(self.as_('doctor').post('/drflow/ask/', {'kind': 'free', 'question': 'x'}).status_code, 400)
        self.assertEqual(self.as_('doctor').post('/drflow/ask/', {'kind': 'med', 'id': 999999}).status_code, 404)
        self.assertEqual(self.as_('doctor').post('/drflow/ask/', {'kind': 'nope'}).status_code, 404)
        self.assertEqual(self.as_('lab').post('/drflow/ask/', {'kind': 'test', 'id': self.cbc.pk}).status_code, 403)

    def test_personal_warnings_in_the_card(self):
        e = self.visit(self.woman, reason='ANC')
        Condition.objects.create(patient=self.woman, name='Pregnancy')
        j = self.as_('doctor').post('/drflow/ask/', {'kind': 'med', 'id': med('Lisinopril').pk, 'encounter': e.pk}).json()
        self.assertEqual(j['warnings'][0]['title'], 'Lisinopril in pregnancy')

    @AI_ON
    @override_settings(DRFLOW_IMAGES=True)
    def test_ai_and_pictures_deidentified_and_cached(self):
        self.man.phone = '+220 7111111'; self.man.save()
        e = self.visit(dx='Fever')
        m = med('Paracetamol', strength='500 mg')
        sent = []

        def post(url, body, headers, timeout):
            sent.append(json.dumps(body, default=str))
            return {'text': '## What it is\nAn **analgesic**.', 'sources': [{'title': 'BNF', 'url': 'https://bnf.nice.org.uk/x'}, {'title': 'bad', 'url': 'javascript:x'}]}
        with mock.patch.object(medical_ai, '_post_json', post), mock.patch.object(drflow_ask, '_get_json', fake_json):
            j = self.as_('doctor').post('/drflow/ask/', {'kind': 'med', 'id': m.pk, 'encounter': e.pk}).json()
            s = self.as_('doctor').get(j['poll']).json()
        self.assertIn('<b>analgesic</b>', s['html'])
        self.assertEqual([x['url'] for x in s['sources']], ['https://bnf.nice.org.uk/x'])
        self.assertEqual([i['source'] for i in s['images']], ['Wikimedia Commons', 'NLM Open-i'])   # medicines: encyclopaedia first
        self.assertEqual(s['images'][0]['full'], 'https://upload.wikimedia.org/a/Pills.jpg')
        self.assertEqual(s['images'][1]['caption'], 'Ring forms')                                 # markup stripped
        self.assertEqual(s['images'][1]['page'], 'https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1/')
        for secret in ('Lamin', 'Ceesay', self.man.mrn, '7111111'):
            self.assertNotIn(secret, sent[0])
        self.assertIn('For this patient', sent[0])
        self.assertNotIn('Answer with exactly these headings', sent[0])        # not the lab-review format
        # general questions (not about this patient) are answered once and reused
        with mock.patch.object(medical_ai, '_post_json', post), mock.patch.object(drflow_ask, '_get_json', fake_json):
            a = self.as_('doctor').post('/drflow/ask/', {'kind': 'med', 'id': m.pk, 'personal': '0'}).json()
            b = self.as_('doctor').post('/drflow/ask/', {'kind': 'med', 'id': m.pk, 'personal': '0'}).json()
        self.assertEqual((a['id'], b['cached']), (b['id'], True))
        self.assertEqual(len(sent), 2)
        self.assertEqual(DrFlowAsk.objects.count(), 2)

    @AI_ON
    @override_settings(DRFLOW_IMAGES=True)
    def test_unreachable_sources_do_not_break_the_answer(self):
        with mock.patch.object(medical_ai, '_post_json', side_effect=RuntimeError('HTTP 529')), \
                mock.patch.object(drflow_ask, '_get_json', side_effect=OSError('offline')):
            j = self.as_('doctor').post('/drflow/ask/', {'kind': 'test', 'id': self.cbc.pk}).json()
            s = self.as_('doctor').get(j['poll']).json()
        self.assertEqual((s['status'], s['images'], s['html']), ('done', [], ''))
        self.assertIn('HTTP 529', s['error'])

    def test_image_hosts_are_allow_listed(self):
        with self.assertRaises(ValueError):
            drflow_ask._get_json('https://evil.example/api')
        with self.assertRaises(ValueError):
            drflow_ask._get_json('http://en.wikipedia.org/w/api.php')
