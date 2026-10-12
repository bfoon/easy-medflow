"""Tests for the bedside scene data, injury maths, forms engine (including Python/JavaScript parity), flows and e-sign."""
import base64
import json
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from . import bedside as B
from . import esign as E
from . import flows
from . import formkit as F
from . import injury as I
from .models import (Admission, Bed, BedsideObservation, Envelope, EnvelopeEvent, FormDefinition, FormSubmission, InjuryAssessment,
                     WorkflowDefinition, WorkflowRun, WorkflowTask)
from .tests import PW, Base

JS = Path(__file__).parent / 'static' / 'hospital' / 'js'
NODE = shutil.which('node')
def _png():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGBA', (60, 20), (15, 44, 63, 255)).save(buf, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


PNG = _png()


def node_eval(script):
    out = subprocess.run([NODE, '-e', script], capture_output=True, text=True, timeout=30)
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


# ------------------------------------------------------------------ injury & burns
class InjuryEngineTests(TestCase):
    def test_lund_browder_and_parkland(self):
        d = I.clean_assessment({'burns': [{'region': 'chest', 'depth': 'deep_partial', 'pct': 100},
                                          {'region': 'abdomen', 'depth': 'full', 'pct': 100},
                                          {'region': 'forearm', 'side': 'left', 'view': 'front', 'depth': 'superficial', 'pct': 100}]})
        c = I.compute(d, age=30, weight_kg=70)
        self.assertEqual(c['tbsa'], 13.0)                    # chest 6.5 + abdomen 6.5; simple redness not counted
        self.assertEqual(c['fluids']['total_24h'], 3640)     # 4 × 70 × 13
        self.assertEqual(c['fluids']['rate_first_ml_h'], 228)
        self.assertFalse(c['fluids']['resuscitation_needed'])  # adults from 15%
        child = I.compute(d, age=3, weight_kg=14)
        self.assertTrue(child['fluids']['resuscitation_needed'])  # children from 10%
        self.assertEqual(child['fluids']['urine_target_ml_h'], 14)

    def test_age_changes_head_share(self):
        d = I.clean_assessment({'burns': [{'region': 'head', 'view': 'front', 'depth': 'full', 'pct': 100}]})
        self.assertEqual(I.compute(d, age=0)['tbsa'], 9.5)    # infant head 19% / 2 views
        self.assertEqual(I.compute(d, age=40)['tbsa'], 3.5)

    def test_same_area_cannot_exceed_100_percent(self):
        d = I.clean_assessment({'burns': [{'region': 'chest', 'depth': 'full', 'pct': 80}, {'region': 'chest', 'depth': 'full', 'pct': 80}]})
        self.assertEqual(I.compute(d)['tbsa'], 6.5)

    def test_catch_up_rate_from_time_of_burn(self):
        d = I.clean_assessment({'burn': {'time': '2026-10-12T08:00', 'given_ml': 500}, 'burns': [{'region': 'chest', 'depth': 'full', 'pct': 100},
                                                                                                    {'region': 'upper_back', 'depth': 'full', 'pct': 100}]})
        c = I.compute(d, weight_kg=60, now=datetime(2026, 10, 12, 12, 0))
        self.assertEqual(c['fluids']['total_24h'], 3120)
        self.assertEqual(c['fluids']['catch_up_ml_h'], 265)   # (1560 − 500) / 4 h left of the first 8

    def test_spinal_level_and_neurogenic_shock_follow_vitals(self):
        d = I.clean_assessment({'spine': {'level': 'C6', 'asia': 'A', 'immobilised': False}})
        c = I.compute(d, vitals={'systolic': 82, 'heart_rate': 48})
        self.assertIn('hand', c['spine']['affected']); self.assertNotIn('upper_arm', c['spine']['affected'])
        self.assertTrue(c['spine']['neurogenic_shock'])
        texts = ' '.join(a['text'] for a in c['alerts'])
        self.assertIn('neurogenic shock', texts); self.assertIn('apply a collar', texts)
        self.assertFalse(I.compute(d, vitals={'systolic': 120, 'heart_rate': 80})['spine']['neurogenic_shock'])
        self.assertEqual(I.spinal_effects('L4', 'E')['affected'], [])

    def test_cleaning_drops_bad_input(self):
        d = I.clean_assessment({'burns': [{'region': 'tail', 'pct': 50}, {'region': 'hand', 'pct': 'x'}],
                                'injuries': [{'type': 'fracture', 'region': 'leg', 'open': True, 'bleeding': 'lots'}],
                                'head': {'eye': 9, 'verbal': 0, 'motor': 6}})
        self.assertEqual(d['burns'], [])
        self.assertEqual(d['injuries'][0]['bleeding'], 'none')
        self.assertEqual(d['head'], {'eye': 4, 'verbal': 1, 'motor': 6, 'pupils': 'equal', 'loc': False})

    @__import__('unittest').skipUnless(NODE, 'node not installed')
    def test_javascript_computes_the_same(self):
        cases = [
            ({'burns': [{'region': 'chest', 'side': '', 'view': 'front', 'depth': 'deep_partial', 'pct': 37},
                        {'region': 'forearm', 'side': 'left', 'view': 'back', 'depth': 'superficial_partial', 'pct': 55, 'circumferential': True},
                        {'region': 'thigh', 'side': 'right', 'view': 'front', 'depth': 'full', 'pct': 25}],
              'burn': {'inhalation': True, 'time': '2026-10-12T06:15', 'given_ml': 300},
              'spine': {'level': 'T4', 'asia': 'B', 'type': 'fracture', 'immobilised': True},
              'head': {'eye': 2, 'verbal': 3, 'motor': 5, 'pupils': 'unequal', 'loc': True},
              'injuries': [{'type': 'laceration', 'region': 'leg', 'side': 'left', 'view': 'front', 'severity': 'severe', 'bleeding': 'active', 'open': False}]},
             7, 23.5, {'systolic': 84, 'heart_rate': 52, 'spo2': 89}),
            ({'burns': [{'region': 'head', 'side': '', 'view': 'front', 'depth': 'superficial_partial', 'pct': 45}]}, 2, 12, {}),
            ({'spine': {'level': 'C2', 'asia': 'A', 'type': 'dislocation', 'immobilised': False}}, None, None, {}),
        ]
        now = '2026-10-12T11:40:00'
        cat = I.catalogue()
        for data, age, w, vit in cases:
            data = I.clean_assessment(data)
            py = I.compute(data, age=age, weight_kg=w, vitals=vit, now=datetime.fromisoformat(now))
            js = node_eval(f"global.window=globalThis;global.matchMedia=()=>({{matches:true}});require('{JS / 'injury-figure.js'}');"
                           f"const r=MFInjury.compute({json.dumps(data)},{json.dumps(cat)},{{age:{json.dumps(age)},weight_kg:{json.dumps(w)},vitals:{json.dumps(vit)},now:new Date('{now}')}});"
                           "console.log(JSON.stringify(r))")
            self.assertEqual(json.loads(json.dumps(py)), js)


# ------------------------------------------------------------------ bedside
class BedsideTests(Base):
    def setUp(self):
        self.e = self.encounter()
        self.e.vitals = {'weight_kg': '60'}; self.e.save()
        self.bed = Bed.objects.filter(state='available').first()
        self.adm = Admission.objects.create(encounter=self.e, bed=self.bed)
        self.bed.state = 'occupied'; self.bed.save()

    def test_drip_rate_and_warnings(self):
        dev = B.clean_devices({'iv': {'on': True, 'rate_ml_h': 125, 'drop_factor': 20, 'bag_ml': 1000, 'remaining_ml': 40},
                               'catheter': {'on': True, 'output_ml_h': 20}, 'oxygen': {'on': True, 'device': 'nasal', 'flow_l_min': 50}})
        d = B.derive(dev, weight_kg=60)
        self.assertEqual(d['drops_per_min'], 41.7)
        self.assertEqual(dev['oxygen']['flow_l_min'], 6)        # nasal cannula is capped at 6 L/min
        self.assertEqual(d['fio2'], 44)
        self.assertEqual(d['urine_ml_kg_h'], 0.33)
        self.assertTrue(any('nearly empty' in w for w in d['warnings']))
        self.assertTrue(any('below 0.5' in w for w in d['warnings']))

    def test_news2(self):
        self.assertEqual(B.news2({'resp_rate': 26, 'spo2': 91, 'on_oxygen': True, 'systolic': 96, 'heart_rate': 118, 'consciousness': 'A', 'temperature_c': 38.6})['total'], 13)
        low = B.news2({'resp_rate': 16, 'spo2': 98, 'systolic': 125, 'heart_rate': 72, 'temperature_c': 36.8})
        self.assertEqual((low['total'], low['risk']), (0, 'low'))
        self.assertEqual(B.news2({'consciousness': 'V', 'heart_rate': 80})['risk'], 'low-medium')

    def test_save_devices_and_observations_through_the_page(self):
        c = self.as_('nurse')
        r = c.post(f'/beds/admissions/{self.adm.pk}/bedside/', json.dumps({'devices': {'iv': {'on': True, 'rate_ml_h': 2000, 'drop_factor': 15}}}),
                   content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['devices']['iv']['rate_ml_h'], 999)   # clamped by the server
        self.assertEqual(r.json()['derived']['drops_per_min'], 249.8)
        r = c.post(f'/beds/admissions/{self.adm.pk}/observations/', json.dumps({'heart_rate': 130, 'systolic': 88, 'diastolic': 50, 'resp_rate': 28, 'spo2': 90}),
                   content_type='application/json')
        self.assertEqual(r.json()['news2']['total'], 11)          # HR 2 + BP 3 + RR 3 + SpO2 3
        self.assertEqual(BedsideObservation.objects.get().news2, 11)
        bad = c.post(f'/beds/admissions/{self.adm.pk}/observations/', json.dumps({'systolic': 80, 'diastolic': 90}), content_type='application/json')
        self.assertEqual(bad.status_code, 400)
        page = c.get(f'/beds/{self.bed.pk}/')
        self.assertContains(page, 'bedside-boot'); self.assertContains(page, 'bs-host')
        self.client.logout()
        self.assertEqual(self.as_('reception').post(f'/beds/admissions/{self.adm.pk}/bedside/', '{}', content_type='application/json').status_code, 403)

    def test_injury_page_saves_versions(self):
        c = self.as_('doctor')
        self.assertEqual(c.get(f'/encounters/{self.e.pk}/injuries/').status_code, 200)
        body = {'assessment': {'burns': [{'region': 'chest', 'depth': 'full', 'pct': 100}, {'region': 'upper_back', 'depth': 'full', 'pct': 100},
                                          {'region': 'abdomen', 'depth': 'full', 'pct': 50}]}, 'weight_kg': 60}
        r = c.post(f'/encounters/{self.e.pk}/injuries/', json.dumps(body), content_type='application/json')
        self.assertEqual(r.json()['computed']['tbsa'], 16.3)
        c.post(f'/encounters/{self.e.pk}/injuries/', json.dumps(body), content_type='application/json')
        self.assertEqual(InjuryAssessment.objects.filter(encounter=self.e).count(), 2)
        payload = c.get(f'/beds/{self.bed.pk}/').context['bedside']
        self.assertIn('Burns 16.3% TBSA', payload['injury']['summary'])


# ------------------------------------------------------------------ forms engine
PARITY_CASES = [
    ('round(bmi(w,h),1)', {'w': 70, 'h': 175}), ('if(pain>5,"severe","mild")', {'pain': '7'}), ('sum(col(items,"q"))*2', {'items': [{'q': 2}, {'q': '3.5'}, {'q': None}]}),
    ('w/0', {'w': 1}), ('2^3^2', {}), ('-w+3*2', {'w': 70}), ('concat("BMI ", round(w/(h/100)^2))', {'w': 70, 'h': 175}), ('not (w>60 and h<170)', {'w': 70, 'h': 165}),
    ('days_between("2026-01-01", today())', {}), ('age(dob)', {'dob': '1990-10-13'}), ('avg(a,b,c)', {'a': 1, 'b': '', 'c': 4}), ('count(a,b,c)', {'a': 1, 'b': '', 'c': [1]}),
    ('upper(x) + "!"', {'x': 'ok'}), ('coalesce(a,b,"none")', {'a': '', 'b': None}), ('round(10/3, 4)', {}), ('5 % 3 + 1.5', {}), ('x == "YES"', {'x': 'yes'}),
    ('a.heart_rate > 100', {'a': {'heart_rate': 120}}), ('len(xs)', {'xs': ['a', 'b']}), ('min(3, 1, 2) + max(1, 9)', {}), ('floor(2.7) + ceil(2.1) + abs(-1)', {}),
    ('round(2.675, 2)', {}), ('1 + "2"', {}), ('"a" + 1', {}), ('sqrt(-4)', {}), ('if(true, 1)', {}), ('foo(1)', {}), ('(1 + 2', {}), ('1 2', {}),
]
RULE_CASES = [
    ({'field': 'a', 'op': 'eq', 'value': '7'}, {'a': 7.0}), ({'field': 'a', 'op': 'contains', 'value': '7'}, {'a': 7.0}), ({'field': 'a', 'op': 'between', 'value': '10', 'value2': '1'}, {'a': '5'}),
    ({'field': 'a', 'op': 'in', 'value': 'x, y'}, {'a': 'Y'}), ({'field': 'a', 'op': 'includes_all', 'value': 'b,c'}, {'a': ['A', 'b', 'C']}),
    ({'field': 'a', 'op': 'within_days', 'value': '3'}, {'a': '2026-10-14'}), ({'field': 'a', 'op': 'in_past'}, {'a': '2026-10-11'}),
    ({'field': 'a', 'op': 'gt', 'ref': 'b'}, {'a': 3, 'b': '2'}), ({'field': 'a', 'op': 'truthy'}, {'a': 'no'}), ({'field': 'a', 'op': 'eq', 'value': 'yes'}, {'a': True}),
    ({'field': 'a', 'op': 'neq', 'value': '1_000'}, {'a': 1000}), ({'field': 'v.spo2', 'op': 'lt', 'value': '92'}, {'v': {'spo2': 90}}),
    ({'any': [{'field': 'a', 'op': 'empty'}, {'field': 'b', 'op': 'gte', 'value': '3'}], 'not': True}, {'a': 'x', 'b': 2}),
]


class FormkitTests(TestCase):
    def test_schema_validation(self):
        s, errs = F.clean_schema({'fields': [{'key': 'a', 'type': 'number', 'label': 'A'}, {'key': 'b', 'type': 'calc', 'label': 'B', 'formula': 'a*2+c'},
                                             {'key': 'c', 'type': 'calc', 'label': 'C', 'formula': 'b+1'}]})
        self.assertIsNone(s); self.assertTrue(any('depends on itself' in e for e in errs))
        _, errs = F.clean_schema({'fields': [{'key': 'a', 'type': 'text', 'label': 'A', 'show_if': {'all': [{'field': 'zz', 'op': 'empty'}]}}]})
        self.assertTrue(any('does not exist' in e for e in errs))
        s, errs = F.clean_schema({'fields': [{'key': 'reason', 'type': 'textarea', 'label': 'Reason', 'required': True}]})
        self.assertEqual(errs, []); self.assertEqual(s['version'], 2)

    def test_hidden_fields_are_cleared_and_not_required(self):
        s, _ = F.clean_schema({'fields': [
            {'key': 'blood', 'type': 'yesno', 'label': 'Blood'},
            {'key': 'consent', 'type': 'yesno', 'label': 'Consent', 'required': True, 'show_if': {'all': [{'field': 'blood', 'op': 'eq', 'value': 'yes'}]}},
            {'key': 'w', 'type': 'number', 'label': 'W', 'min': 1, 'max': 300}, {'key': 'h', 'type': 'number', 'label': 'H'},
            {'key': 'bmi', 'type': 'calc', 'label': 'BMI', 'formula': 'round(bmi(w,h),1)'},
            {'key': 'note', 'type': 'text', 'label': 'Note', 'require_if': {'all': [{'field': 'bmi', 'op': 'gt', 'value': '30'}]}}]})
        v, errs, hidden = F.evaluate_form(s, {'blood': 'no', 'consent': 'yes', 'w': '70', 'h': '175', 'bmi': 99})
        self.assertEqual(errs, {}); self.assertIn('consent', hidden); self.assertEqual(v['consent'], ''); self.assertEqual(v['bmi'], 22.9)
        v, errs, _ = F.evaluate_form(s, {'blood': 'yes', 'w': '120', 'h': '160'})
        self.assertEqual(set(errs), {'consent', 'note'})
        _, errs, _ = F.evaluate_form(s, {'w': '900'})
        self.assertEqual(errs['w'], 'Enter 300 or less.')

    def test_steps_only_change_their_own_fields(self):
        s, _ = F.clean_schema({'fields': [{'key': 'a', 'type': 'text', 'label': 'A', 'required': True},
                                          {'key': 'b', 'type': 'text', 'label': 'B', 'required': True, 'filled_by': 'pharm'}]})
        v, errs, _ = F.evaluate_form(s, {'a': 'mine', 'b': 'sneaky'})
        self.assertEqual((errs, v['b']), ({}, ''))
        v, errs, _ = F.evaluate_form(s, {'a': 'changed', 'b': 'ok'}, scope='pharm', previous={'a': 'mine'})
        self.assertEqual((v['a'], v['b']), ('mine', 'ok'))

    def test_composite_fields(self):
        s, _ = F.clean_schema({'fields': [{'key': 'v', 'type': 'vitals', 'label': 'V'}, {'key': 'g', 'type': 'gcs', 'label': 'G'},
                                          {'key': 'sig', 'type': 'signature', 'label': 'S', 'required': True},
                                          {'key': 't', 'type': 'table', 'label': 'T', 'min_rows': 1, 'columns': [{'key': 'n', 'label': 'N', 'type': 'number'}]}]})
        v, errs, _ = F.evaluate_form(s, {'v': {'heart_rate': 130, 'resp_rate': 26}, 'g': {'eye': 3, 'verbal': 4, 'motor': 6}, 'sig': 'javascript:x', 't': [{'n': ''}]})
        self.assertEqual(v['v']['news2'], 5); self.assertEqual(v['g']['total'], 13)
        self.assertIn('sig', errs); self.assertIn('t', errs)

    @__import__('unittest').skipUnless(NODE, 'node not installed')
    def test_javascript_parity(self):
        today = '2026-10-12'
        py = []
        for src, vals in PARITY_CASES:
            py.append(F.run_formula(src, vals, 2, date.fromisoformat(today)))
        for rule, vals in RULE_CASES:
            py.append(F.check(rule, vals, date.fromisoformat(today)))
        js = node_eval(f"const F=require('{JS / 'formkit.js'}');const out=[];"
                       f"for(const [s,v] of {json.dumps(PARITY_CASES)}) out.push(F.runFormula(s,v,2,'{today}'));"
                       f"for(const [r,v] of {json.dumps(RULE_CASES)}) out.push(F.check(r,v,'{today}'));console.log(JSON.stringify(out))")
        self.assertEqual(json.loads(json.dumps(py)), js)


# ------------------------------------------------------------------ flows
@override_settings(NOTIFY_EMAIL_SYNC=True)
class FlowTests(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        U = get_user_model()
        from .models import StaffProfile
        for name in ('doctor2', 'doctor3', 'nurse2'):
            u = U.objects.create_user(username=name, password=PW)
            StaffProfile.objects.create(user=u, role=name.rstrip('23'))
            cls.users[name] = u
        cls.form = FormDefinition.objects.create(name='Request', slug='request', published=True, schema=F.clean_schema({'fields': [
            {'key': 'amount', 'type': 'number', 'label': 'Amount', 'required': True},
            {'key': 'urgent', 'type': 'checkbox', 'label': 'Urgent'},
            {'key': 'pharm_note', 'type': 'text', 'label': 'Pharmacy note', 'required': True, 'filled_by': 'fill1'}]})[0])

    def make(self, graph):
        g, errs = flows.clean_graph(graph, self.form.schema)
        self.assertEqual(errs, [])
        return WorkflowDefinition.objects.create(name='Flow', graph=g, form=self.form)

    def submit(self, values):
        return FormSubmission.objects.create(definition=self.form, patient=self.patient, values=values, schema_snapshot=self.form.schema, submitted_by=self.users['nurse'])

    def task(self, run, user):
        return next(t for t in run.tasks.filter(status='pending') if flows.can_act(t, user))

    def test_graph_validation(self):
        _, errs = flows.clean_graph({'nodes': [{'id': 'a', 'type': 'start'}, {'id': 'b', 'type': 'approval', 'config': {'assign': {'mode': 'role', 'role': 'doctor'}}},
                                               {'id': 'c', 'type': 'review', 'config': {}}],
                                     'edges': [{'from': 'a', 'to': 'b'}, {'from': 'b', 'port': 'approved', 'to': 'c'}, {'from': 'c', 'to': 'b'}]}, self.form.schema)
        self.assertTrue(any('loops' in e for e in errs))
        _, errs = flows.clean_graph({'nodes': [{'id': 'a', 'type': 'start'}, {'id': 'j', 'type': 'join'}], 'edges': [{'from': 'a', 'to': 'j'}]})
        self.assertTrue(any('fewer than two' in e for e in errs))

    def test_quorum_route_parallel_join_and_fill(self):
        wf = self.make({'nodes': [
            {'id': 'start', 'type': 'start'},
            {'id': 'r', 'type': 'route', 'config': {'branches': [{'id': 'big', 'label': 'Large', 'rules': {'all': [{'field': 'amount', 'op': 'gt', 'value': '1000'}]}}]}},
            {'id': 'q', 'type': 'approval', 'label': 'Two doctors', 'config': {'assign': {'mode': 'role', 'role': 'doctor'}, 'mode': 'quorum', 'quorum': 2}},
            {'id': 'par', 'type': 'parallel'}, {'id': 'fill1', 'type': 'fill', 'config': {'assign': {'mode': 'role', 'role': 'pharmacy'}}},
            {'id': 'rev', 'type': 'review', 'config': {'assign': {'mode': 'role', 'role': 'nurse'}}},
            {'id': 'j', 'type': 'join'}, {'id': 'set', 'type': 'set', 'config': {'field': 'urgent', 'formula': 'amount > 5000'}},
            {'id': 'end', 'type': 'end'}],
            'edges': [{'from': 'start', 'to': 'r'}, {'from': 'r', 'port': 'big', 'to': 'q'}, {'from': 'r', 'port': 'otherwise', 'to': 'par'},
                      {'from': 'q', 'port': 'approved', 'to': 'par'}, {'from': 'par', 'to': 'fill1'}, {'from': 'par', 'to': 'rev'},
                      {'from': 'fill1', 'to': 'j'}, {'from': 'rev', 'to': 'j'}, {'from': 'j', 'to': 'set'}, {'from': 'set', 'to': 'end'}]})
        run = flows.start_run(wf, self.submit({'amount': 9000.0, 'urgent': False}), self.users['nurse'])
        self.assertEqual(run.tasks.filter(status='pending').count(), 2)              # two doctor seats
        flows.decide(self.task(run, self.users['doctor']), self.users['doctor'], 'approve')
        with self.assertRaisesMessage(flows.FlowError, 'already decided'):
            flows.decide(self.task(run, self.users['doctor']), self.users['doctor'], 'approve')
        flows.decide(self.task(run, self.users['doctor2']), self.users['doctor2'], 'approve')
        run.refresh_from_db()
        self.assertEqual(sorted(run.state['active']), ['fill1', 'rev'])
        with self.assertRaises(flows.FlowError):
            flows.decide(self.task(run, self.users['pharmacy']), self.users['pharmacy'], 'submit', values={'pharm_note': ''})
        flows.decide(self.task(run, self.users['pharmacy']), self.users['pharmacy'], 'submit', values={'pharm_note': 'In stock', 'amount': 1})
        run.refresh_from_db(); self.assertEqual(run.status, 'open')                  # still waiting at the join
        flows.decide(self.task(run, self.users['nurse2']), self.users['nurse2'], 'acknowledge')
        run.refresh_from_db(); run.submission.refresh_from_db()
        self.assertEqual(run.status, 'approved')
        self.assertEqual(run.submission.values['pharm_note'], 'In stock')
        self.assertEqual(run.submission.values['amount'], 9000.0)                   # fill step could not change it
        self.assertIs(run.submission.values['urgent'], True)                         # set by the Set step

    def test_reject_return_and_resubmit(self):
        wf = self.make({'nodes': [{'id': 'start', 'type': 'start'}, {'id': 'a', 'type': 'approval', 'config': {'assign': {'mode': 'role', 'role': 'doctor'}, 'mode': 'all'}}],
                        'edges': [{'from': 'start', 'to': 'a'}]})
        run = flows.start_run(wf, self.submit({'amount': 5.0}), self.users['nurse'])
        with self.assertRaisesMessage(flows.FlowError, 'Say why'):
            flows.decide(self.task(run, self.users['doctor']), self.users['doctor'], 'return')
        flows.decide(self.task(run, self.users['doctor']), self.users['doctor'], 'return', 'Amount looks wrong')
        run.refresh_from_db(); self.assertEqual(run.status, 'returned')
        with self.assertRaises(flows.FlowError):
            flows.resubmit(run, self.users['doctor'], {'amount': 6})
        flows.resubmit(run, self.users['nurse'], {'amount': 6})
        run.refresh_from_db(); self.assertEqual((run.status, run.round), ('open', 2))
        flows.decide(self.task(run, self.users['doctor']), self.users['doctor'], 'reject', 'No')
        run.refresh_from_db(); self.assertEqual(run.status, 'rejected')               # unconnected rejected exit

    def test_overdue_steps_escalate(self):
        wf = self.make({'nodes': [{'id': 'start', 'type': 'start'}, {'id': 'a', 'type': 'review', 'config': {'assign': {'mode': 'role', 'role': 'nurse'}, 'due_hours': 2, 'escalate_role': 'doctor'}}],
                        'edges': [{'from': 'start', 'to': 'a'}]})
        run = flows.start_run(wf, self.submit({'amount': 1.0}), self.users['nurse'])
        self.assertEqual(flows.sweep(), 0)
        self.assertEqual(flows.sweep(datetime.now().astimezone() + timedelta(hours=3)), 1)
        self.assertTrue(self.users['doctor'].notifications.filter(title__startswith='Overdue').exists())

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_signature_step_with_in_person_patient(self):
        wf = self.make({'nodes': [{'id': 'start', 'type': 'start'},
                                  {'id': 'sig', 'type': 'signature', 'config': {'signers': [{'source': 'patient', 'order': 1}, {'source': 'initiator', 'as': 'witness', 'order': 1}]}}],
                        'edges': [{'from': 'start', 'to': 'sig'}]})
        run = flows.start_run(wf, self.submit({'amount': 1.0}), self.users['nurse'])
        env = run.envelopes.get()
        self.assertEqual(env.status, 'sent')
        self.assertEqual(env.fields.filter(kind='signature').count(), 2)
        patient, witness = env.recipients.get(role='in_person'), env.recipients.get(role='witness')
        req = type('R', (), {'META': {'REMOTE_ADDR': '127.0.0.1'}})()
        with self.assertRaisesMessage(E.EsignError, 'confirmed who is signing'):
            E.sign(patient, req, values={}, signature=PNG, consent=True, actor=self.users['nurse'])
        with self.captureOnCommitCallbacks(execute=True):
            E.sign(patient, req, values={}, signature=PNG, consent=True, identity_check='Name and DOB checked', actor=self.users['nurse'])
            E.sign(witness, req, values={}, signature=PNG, consent=True, actor=self.users['nurse'])
        env.refresh_from_db(); run.refresh_from_db()
        self.assertEqual(env.status, 'completed')
        self.assertEqual(run.status, 'approved')


# ------------------------------------------------------------------ e-sign
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), NOTIFY_EMAIL_SYNC=True)
class EsignTests(Base):
    def envelope(self, recips, **kw):
        data, _ = E.letter_pdf('Consent', 'I, {patient.name}, agree.\n\nSecond paragraph.', self.patient)
        return E.create_envelope(user=self.users['doctor'], subject='Consent', pdf_bytes=data, patient=self.patient, recipients=recips, **kw)

    def test_rejects_non_pdf(self):
        with self.assertRaisesMessage(E.EsignError, 'not a PDF'):
            E.inspect_pdf(b'hello')

    def test_routing_order_signing_and_seal(self):
        env = self.envelope([{'name': 'Ext Person', 'email': 'ext@example.com', 'order': 1, 'access_code': '4321'},
                             {'user': self.users['nurse'], 'role': 'approver', 'order': 2},
                             {'name': 'Records', 'email': 'rec@example.com', 'role': 'cc', 'order': 3}], require_full_read=True)
        ext = env.recipients.get(order=1)
        with self.assertRaisesMessage(E.EsignError, 'no signature field'):
            E.send(env, self.users['doctor'])
        E.auto_place(env)
        E.send(env, self.users['doctor'])
        self.assertEqual(env.recipients.get(order=2).status, 'waiting')
        # external signer: access code, then must read every page
        c = self.client
        r = c.get(f'/esign/sign/{ext.token}/')
        self.assertContains(r, 'access code')
        self.assertEqual(c.post(f'/esign/sign/{ext.token}/act/', json.dumps({'action': 'code', 'code': '0000'}), content_type='application/json').status_code, 400)
        self.assertEqual(c.post(f'/esign/sign/{ext.token}/act/', json.dumps({'action': 'code', 'code': '4321'}), content_type='application/json').status_code, 200)
        self.assertEqual(c.get(f'/esign/sign/{ext.token}/').status_code, 200)
        self.assertEqual(c.get(f'/esign/sign/{ext.token}/document/')['Content-Type'], 'application/pdf')
        sign = lambda: c.post(f'/esign/sign/{ext.token}/act/', json.dumps({'action': 'sign', 'consent': True, 'signature': PNG, 'values': {}}), content_type='application/json')
        self.assertIn('Read every page', sign().json()['error'])
        c.post(f'/esign/sign/{ext.token}/act/', json.dumps({'action': 'viewed', 'pages': list(range(1, env.pages + 1))}), content_type='application/json')
        self.assertEqual(sign().status_code, 200)
        nurse = env.recipients.get(order=2)
        nurse.refresh_from_db(); self.assertEqual(nurse.status, 'sent')
        self.client.logout()
        n = self.as_('nurse')
        self.assertEqual(n.post(f'/esign/sign/{nurse.token}/act/', json.dumps({'action': 'approve', 'consent': True}), content_type='application/json').status_code, 200)
        env.refresh_from_db()
        self.assertEqual(env.status, 'completed')
        self.assertEqual(env.recipients.get(order=3).status, 'copied')
        ok, problems = E.verify(env)
        self.assertTrue(ok, problems)
        from pypdf import PdfReader
        self.assertEqual(len(PdfReader(env.signed_document.path).pages), env.pages + 1)     # + certificate
        # verify page finds the sealed file; tampering with the trail is detected
        self.client.logout()
        with open(env.signed_document.path, 'rb') as fh:
            r = self.client.post('/esign/verify/', {'document': fh})
        self.assertContains(r, 'authentic')
        ev = EnvelopeEvent.objects.filter(envelope=env, action='signed').first()
        EnvelopeEvent.objects.filter(pk=ev.pk).update(details={'name': 'Someone else'})
        self.assertFalse(E.verify(env)[0])

    def test_decline_and_wrong_person(self):
        env = self.envelope([{'user': self.users['nurse'], 'order': 1}])
        E.auto_place(env); E.send(env, self.users['doctor'])
        rec = env.recipients.get()
        self.assertEqual(self.as_('doctor').get(f'/esign/sign/{rec.token}/').status_code, 403)
        self.client.logout()
        n = self.as_('nurse')
        self.assertEqual(n.post(f'/esign/sign/{rec.token}/act/', json.dumps({'action': 'decline', 'reason': 'Wrong patient'}), content_type='application/json').status_code, 200)
        env.refresh_from_db(); self.assertEqual(env.status, 'declined')
        self.assertTrue(self.users['doctor'].notifications.filter(title__startswith='Declined').exists())

    def test_prepare_compose_and_pages(self):
        c = self.as_('doctor')
        data, _ = E.letter_pdf('Letter', 'Body')
        from django.core.files.uploadedfile import SimpleUploadedFile
        r = c.post('/esign/new/', {'source': 'upload', 'subject': 'Upload', 'document': SimpleUploadedFile('a.pdf', data, 'application/pdf'),
                                   'recipients': json.dumps([{'user': self.users['nurse'].pk, 'role': 'signer', 'order': 1}])})
        env = Envelope.objects.get(subject='Upload')
        self.assertRedirects(r, f'/esign/{env.uid}/prepare/')
        rec = env.recipients.get()
        bad = c.post(f'/esign/{env.uid}/prepare/', json.dumps({'fields': [{'recipient': rec.pk, 'kind': 'signature', 'page': 9, 'x': .1, 'y': .1, 'w': .2, 'h': .05}]}), content_type='application/json')
        self.assertEqual(bad.status_code, 400)
        ok = c.post(f'/esign/{env.uid}/prepare/', json.dumps({'send': True, 'fields': [{'recipient': rec.pk, 'kind': 'signature', 'page': 1, 'x': .95, 'y': .1, 'w': .2, 'h': .05}]}), content_type='application/json')
        self.assertEqual(ok.status_code, 200)
        f = env.fields.get(); self.assertAlmostEqual(f.x, .8)                          # kept on the page
        for url in ['/esign/', f'/esign/{env.uid}/', f'/esign/{env.uid}/file/original/', f'/esign/{env.uid}/file/certificate/', '/esign/new/?source=letter', '/esign/verify/']:
            self.assertEqual(c.get(url).status_code, 200, url)
        self.client.logout()
        self.assertEqual(self.as_('lab').get(f'/esign/{env.uid}/').status_code, 403)


class StudioPageTests(Base):
    def test_designers_tasks_and_templates_render(self):
        get_user_model().objects.create_superuser('root', 'r@example.com', PW)
        c = self.as_('root')
        for url in ['/studio/', '/studio/forms/new/', '/studio/forms/new/?template=consent', '/studio/forms/new/?template=admission',
                    '/studio/workflows/new/', '/studio/tasks/']:
            self.assertEqual(c.get(url).status_code, 200, url)
        from .studio_views import TEMPLATES
        for k, t in TEMPLATES.items():
            s, errs = F.clean_schema(t['schema'])
            self.assertEqual(errs, [], k)

    def test_fill_page_json_submit_with_flow(self):
        get_user_model().objects.create_superuser('root', 'r@example.com', PW)
        c = self.as_('root')
        from .studio_views import TEMPLATES
        c.post('/studio/forms/new/', {'name': 'Falls', 'slug': 'falls', 'schema': json.dumps(TEMPLATES['falls']['schema']), 'published': 'on'})
        f = FormDefinition.objects.get(slug='falls')
        self.assertEqual(f.versions.count(), 1)
        self.assertEqual(c.get(f'/studio/forms/{f.pk}/fill/{self.patient.pk}/').status_code, 200)
        c.post(f'/studio/forms/{f.pk}/draft/{self.patient.pk}/', json.dumps({'values': {'history': 'Yes'}, 'page': 0}), content_type='application/json')
        self.assertContains(c.get(f'/studio/forms/{f.pk}/fill/{self.patient.pk}/'), '"values": {"history": "Yes"}')
        vals = {'history': 'Yes', 'second_dx': 'Yes', 'aid': 'Holds furniture', 'iv': 'Yes', 'gait': 'Weak', 'mental': 'Knows own limits', 'score': 1}
        r = c.post(f'/studio/forms/{f.pk}/fill/{self.patient.pk}/', json.dumps({'values': vals}), content_type='application/json')
        self.assertEqual(r.json()['errors'], {'plan': 'This is required.'})
        vals['plan'] = ['Bed alarm']
        r = c.post(f'/studio/forms/{f.pk}/fill/{self.patient.pk}/', json.dumps({'values': vals}), content_type='application/json')
        s = FormSubmission.objects.get(definition=f)
        self.assertEqual((s.values['score'], s.values['risk']), (100.0, 'High'))
        self.assertEqual(c.get(f'/studio/submissions/{s.pk}/').status_code, 200)
        # editing a used form makes a new version; old submissions keep their own copy
        c.post(f'/studio/forms/{f.pk}/edit/', {'name': 'Falls', 'slug': 'falls', 'schema': json.dumps({'fields': [{'key': 'x', 'type': 'text', 'label': 'X'}]}), 'published': 'on'})
        f.refresh_from_db(); self.assertEqual(f.version, 2)
        self.assertIn('score', [x['key'] for x in FormSubmission.objects.get(pk=s.pk).schema_snapshot['fields']])


class BootstrapRestartTests(TestCase):
    """Container start runs bootstrap_hospital every time; it must survive medicines that share a name."""

    def test_bootstrap_runs_again_after_tablet_and_syrup_of_same_name(self):
        from django.core.management import call_command
        from .models import Medication
        call_command('bootstrap_hospital', verbosity=0)
        Medication.objects.create(name='Paracetamol', strength='120 mg/5 mL', form='Syrup')   # what seed_pharmacy adds
        before = Medication.objects.count()
        call_command('bootstrap_hospital', verbosity=0)
        call_command('bootstrap_hospital', verbosity=0)
        self.assertEqual(Medication.objects.count(), before)
        self.assertEqual(Medication.objects.filter(name='Paracetamol').count(), 2)
