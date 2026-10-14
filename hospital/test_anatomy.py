"""The realistic layered anatomy on Lab insights: the findings engine (run in Node) and the page wiring."""
import json
import unittest
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .models import Encounter, StaffProfile
from .test_studio_care import JS, NODE, node_eval
from .tests import Base
from .views import patient_lab_data


def P(code, name, display, num, flag, system='blood', unit=''):
    return {'code': code, 'name': name, 'unit': unit, 'system': system, 'range': '', 'latest': {'display': display, 'num': num, 'flag': flag},
            'history': [{'display': display, 'num': num, 'flag': flag}]}


def findings(data):
    return node_eval(f"const A=require('{JS / 'anatomy-real.js'}'); console.log(JSON.stringify(A.findings({json.dumps(data)})))")


@unittest.skipUnless(NODE, 'node not installed')
class AnatomyFindingsTests(TestCase):
    def test_a_healthy_record_draws_a_healthy_body(self):
        f = findings({})
        self.assertEqual(f['findings'], [])
        self.assertEqual((f['skin']['pallor'], f['skin']['jaundice'], f['vessel']['pressure'], f['bone']['fractures']), (0, 0, 'normal', []))

    def test_values_change_the_layers(self):
        f = findings({'patient': {'sex': 'F'}, 'vitals': {'bp': '190/124', 'spo2': '86', 'temperature_c': '39.8', 'heart_rate': '120'},
                      'params': [P('HB', 'Haemoglobin', '5.8', 5.8, 'LL', unit='g/dL'), P('TBIL', 'Total bilirubin', '140', 140, 'HH', 'liver'),
                                 P('TNI', 'Troponin I', '300', 300, 'HH', 'heart'), P('PLT', 'Platelets', '18', 18, 'LL'),
                                 P('CREA', 'Creatinine', '480', 480, 'HH', 'kidneys'), P('URIC', 'Uric acid', '610', 610, 'H', 'bone')]})
        self.assertGreater(f['skin']['pallor'], .8)                      # Hb 5.8 in a woman
        self.assertGreater(f['skin']['jaundice'], .9)
        self.assertGreater(f['skin']['cyanosis'], .5)
        self.assertGreater(f['skin']['fever'], .8)
        self.assertTrue(f['skin']['petechiae'])
        self.assertEqual(f['vessel']['pressure'], 'crisis')
        self.assertGreater(f['organ']['infarct'], .5)
        self.assertGreater(f['organ']['kidneys'], .5)
        self.assertTrue(f['bone']['gout'])
        self.assertEqual(f['hr'], 120)
        layers = {x['layer'] for x in f['findings']}
        self.assertEqual(layers, {'skin', 'vessel', 'organ', 'bone'})
        levels = [x['level'] for x in f['findings']]
        self.assertEqual(levels, sorted(levels, reverse=True))           # most urgent first

    def test_old_diagnoses_are_not_shown_as_current(self):
        f = findings({'dx': ['Pneumonia', 'Urinary tract infection', 'Type 2 diabetes'], 'dx_recent': ['Type 2 diabetes review']})
        titles = [x['title'] for x in f['findings']]
        self.assertNotIn('Pneumonia', titles)
        self.assertNotIn('Bladder infection', titles)
        f = findings({'dx': [], 'dx_recent': ['Pneumonia, right lower lobe']})
        self.assertIn('Pneumonia', [x['title'] for x in f['findings']])

    def test_imaging_fractures_have_a_side_and_respect_negation_and_dates(self):
        f = findings({'today': '2026-10-14', 'imaging': [{'region': 'Left leg', 'impression': 'Displaced fracture of the left tibia', 'date': '2026-10-10'},
                                                         {'region': 'Right arm', 'impression': 'Fracture of the right radius', 'date': '2024-01-01'},
                                                         {'region': 'Chest', 'impression': 'No rib fracture.', 'date': '2026-10-12'}]})
        fr = f['bone']['fractures']
        self.assertEqual([(x['bone'], x['side']) for x in fr], [('tibia', 'left')])
        self.assertEqual(f['findings'][0]['side'], 'left')

    def test_whole_words_only(self):
        f = findings({'dx_recent': ['Constitutional symptoms', 'Acute gastritis']})
        self.assertNotIn('Bladder infection', [x['title'] for x in f['findings']])   # "uti" inside "constitutional"

    def test_malaria_enlarges_the_spleen_and_puts_parasites_in_the_blood(self):
        f = findings({'params': [P('DENS', 'Parasite density', '210000', 210000, 'H')]})
        self.assertTrue(f['vessel']['malaria'])
        self.assertGreater(f['organ']['spleen'], 0)
        self.assertEqual(f['findings'][0]['level'], 3)                   # very high parasite count


class AnatomyPageTests(Base):
    def test_page_offers_the_anatomy_view_and_remembers_it(self):
        e = self.encounter()
        c = self.as_('doctor')
        html = c.get(f'/patients/{self.patient.pk}/labs/').content.decode()
        self.assertIn('data-view="anatomy"', html)
        self.assertIn('id="anatomy-real"', html)
        self.assertIn('anatomy-real.js', html)
        self.assertLess(html.index('anatomy-real.js'), html.index('insights.js'))   # MFAnatomy exists before the view switch runs
        self.assertEqual(c.post('/labs/view/', {'view': 'anatomy'}).json()['view'], 'anatomy')
        self.assertEqual(StaffProfile.objects.get(user=self.users['doctor']).lab_view, 'anatomy')
        self.assertIn('data-initial-view="anatomy"', c.get(f'/patients/{self.patient.pk}/labs/').content.decode())
        self.assertEqual(c.post('/labs/view/', {'view': 'nonsense'}).status_code, 400)

    def test_recent_diagnoses_are_sent_separately(self):
        old = Encounter.objects.create(patient=self.patient, department=self.dept, reason='Cough', diagnosis='Pneumonia', status='completed')
        Encounter.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=200))
        Encounter.objects.create(patient=self.patient, department=self.dept, reason='Fever', diagnosis='Uncomplicated malaria')
        d = patient_lab_data(self.patient)
        self.assertIn('Pneumonia', d['dx'])
        self.assertNotIn('Pneumonia', d['dx_recent'])
        self.assertIn('Uncomplicated malaria', d['dx_recent'])
        self.assertEqual(d['today'], timezone.localdate().isoformat())
