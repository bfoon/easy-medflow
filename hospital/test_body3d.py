"""The 3D body on Lab insights: the numbers on the model are the entered values, and the page wiring."""
import json
import subprocess
import unittest

from django.test import TestCase

from .models import Encounter, StaffProfile
from .test_studio_care import JS, NODE, node_eval
from .tests import Base
from .views import patient_lab_data


def values(data):
    return node_eval(f"const B=require('{JS / 'body3d.js'}'); console.log(JSON.stringify(B.values({json.dumps(data)})))")


def P(code, name, display, num, flag, system='blood', unit='', history=None):
    latest = {'display': display, 'num': num, 'flag': flag, 'date': '2026-10-16 09:00'}
    return {'id': hash(code) % 10000, 'code': code, 'name': name, 'unit': unit, 'system': system, 'range': '', 'test': 'Test',
            'latest': latest, 'history': (history or []) + [latest]}


@unittest.skipUnless(NODE, 'node not installed')
class Body3DValuesTests(TestCase):
    def test_every_entered_value_is_on_the_body_exactly_as_typed(self):
        data = {'vitals': {'bp': '190/124', 'heart_rate': '118', 'spo2': '89', 'resp_rate': '24', 'temperature_c': '39.2', 'weight_kg': '72'},
                'params': [P('HB', 'Haemoglobin', '7.1', 7.1, 'L', unit='g/dL'), P('TNI', 'Troponin I', '310', 310, 'HH', 'heart', 'ng/L'),
                           P('CREA', 'Creatinine', '265', 265, 'H', 'kidneys', 'µmol/L'), P('TSH', 'TSH', '2.10', 2.1, '', 'thyroid', 'mIU/L'),
                           P('WIDAL', 'Widal', 'Reactive 1:160', None, 'A', 'immune')]}
        g = {x['anchor']: x for x in values(data)}
        shown = {(i['code'], i['display'], i['unit']) for x in g.values() for i in x['items']}
        self.assertEqual(shown, {('bp', '190/124', 'mmHg'), ('heart_rate', '118', 'bpm'), ('spo2', '89', '%'), ('resp_rate', '24', '/min'),
                                 ('temperature_c', '39.2', '°C'), ('weight_kg', '72', 'kg'), ('HB', '7.1', 'g/dL'), ('TNI', '310', 'ng/L'),
                                 ('CREA', '265', 'µmol/L'), ('TSH', '2.10', 'mIU/L'), ('WIDAL', 'Reactive 1:160', '')})   # "2.10" stays "2.10"
        self.assertEqual([i['code'] for i in g['heart']['items']], ['heart_rate', 'TNI'])     # pinned to the organ, vitals first
        self.assertEqual({i['code'] for i in g['lungs']['items']}, {'spo2', 'resp_rate'})
        self.assertEqual([i['code'] for i in g['arm']['items']], ['bp'])
        self.assertEqual([i['code'] for i in g['spleen']['items']], ['WIDAL'])                # immune → spleen
        self.assertEqual(g['heart']['level'], 3)                                               # troponin HH
        self.assertEqual(g['thyroid']['level'], 0)

    def test_the_latest_result_is_shown_not_an_older_one(self):
        old = {'display': '9.8', 'num': 9.8, 'flag': '', 'date': '2026-09-01 08:00'}
        g = values({'params': [P('HB', 'Haemoglobin', '6.2', 6.2, 'LL', unit='g/dL', history=[old])]})
        self.assertEqual(g[0]['items'][0]['display'], '6.2')
        self.assertEqual(g[0]['items'][0]['flag'], 'LL')

    def test_unknown_system_goes_to_blood_and_empty_vitals_are_skipped(self):
        g = values({'vitals': {'bp': '', 'heart_rate': None, 'spo2': '97'}, 'params': [P('X1', 'Odd test', '4', 4, '', 'nonsense')]})
        anchors = {x['anchor']: [i['code'] for i in x['items']] for x in g}
        self.assertEqual(anchors, {'lungs': ['spo2'], 'blood': ['X1']})

    def test_vital_flags_use_the_anatomy_limits(self):
        f = lambda k, v: node_eval(f"const B=require('{JS / 'body3d.js'}'); console.log(JSON.stringify(B.vitalFlag('{k}', '{v}')))")
        self.assertEqual(f('bp', '190/124'), 'HH')
        self.assertEqual(f('bp', '150/85'), 'H')
        self.assertEqual(f('bp', '118/76'), '')
        self.assertEqual(f('bp', '85/50'), 'L')
        self.assertEqual(f('spo2', '86'), 'LL')
        self.assertEqual(f('heart_rate', '140'), 'HH')
        self.assertEqual(f('temperature_c', '38,1'), 'H')    # comma decimals as typed on some keyboards

    def test_script_parses(self):
        out = subprocess.run([NODE, '--check', str(JS / 'body3d.js')], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)


class Body3DPageTests(Base):
    def test_page_offers_the_3d_body_and_remembers_it(self):
        self.encounter()
        c = self.as_('doctor')
        html = c.get(f'/patients/{self.patient.pk}/labs/').content.decode()
        self.assertIn('data-view="body3d"', html)
        self.assertIn('id="body3d"', html)
        self.assertIn('body3d.css', html)
        self.assertLess(html.index('js/anatomy-real.js'), html.index('js/body3d.js'))   # findings engine first
        self.assertLess(html.index('js/body3d.js'), html.index('js/insights.js'))       # MFBody3D exists before the view switch runs
        self.assertIn('window.MF_THREE', html)
        self.assertEqual(c.post('/labs/view/', {'view': 'body3d'}).json()['view'], 'body3d')
        self.assertEqual(StaffProfile.objects.get(user=self.users['doctor']).lab_view, 'body3d')
        self.assertIn('data-initial-view="body3d"', c.get(f'/patients/{self.patient.pk}/labs/').content.decode())

    def test_the_data_the_model_reads_carries_the_entered_vitals(self):
        e = self.encounter()
        Encounter.objects.filter(pk=e.pk).update(vitals={'bp': '150/95', 'heart_rate': '104', 'spo2': '93'})
        d = patient_lab_data(self.patient)
        self.assertEqual((d['vitals']['bp'], d['vitals']['heart_rate'], d['vitals']['spo2']), ('150/95', '104', '93'))
        self.assertEqual(d['patient']['sex'], self.patient.sex)
