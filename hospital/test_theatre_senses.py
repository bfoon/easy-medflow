"""Tests for operating theatre management and the eye & ear examination (including Python/JavaScript parity)."""
import json
import random
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from . import senses as S
from . import theatre as T
from .models import (AuditEvent, Encounter, Patient, InvoiceLine, LabOrder, LabParameter, LabResultValue, LabTest, OperatingRoom, ProcedureType,
                     SenseExam, SurgicalCase)
from .test_studio_care import JS, NODE, node_eval
from .tests import Base

H = {'content_type': 'application/json'}


# ================================================================== eyes & ears: the rules
class SensesEngineTests(TestCase):
    def exam(self, eyes=None, ears=None, **kw):
        return S.clean_exam({'eyes': eyes or {}, 'ears': ears or {}, **kw})

    def test_who_vision_category_uses_the_better_eye(self):
        d = self.exam({'right': {'examined': True, 'va': '1/60'}, 'left': {'examined': True, 'va': '6/24'}})
        c = S.compute(d)
        self.assertEqual(c['eyes']['right']['category'], 'blind')
        self.assertEqual(S.compute(self.exam({'right': {'examined': True, 'va': '3/60'}}))['eyes']['right']['category'], 'severe')   # blindness is worse than 3/60
        self.assertEqual(c['vision']['category'], 'moderate')        # 6/24 in the better eye
        self.assertTrue(any('Moderate visual impairment (better eye)' in a['text'] for a in c['alerts']))

    def test_cataract_suggests_surgery_on_that_side(self):
        d = self.exam({'right': {'examined': True, 'va': '6/36', 'lens': 'moderate'}, 'left': {'examined': True, 'va': '6/6', 'lens': 'early'}})
        c = S.compute(d)
        self.assertEqual([(p['code'], p['side']) for p in c['procedures']], [('cataract', 'right')])
        self.assertGreater(c['eyes']['right']['vision']['blur'], c['eyes']['left']['vision']['blur'])
        self.assertGreater(c['eyes']['right']['vision']['tint'], 0)

    def test_acute_angle_closure_is_an_emergency(self):
        d = self.exam({'right': {'examined': True, 'iop': 52, 'chamber': 'shallow', 'cdr': 0.5}})
        c = S.compute(d)
        self.assertEqual(c['alerts'][0]['level'], 'high')
        self.assertIn('angle-closure', c['alerts'][0]['text'])
        self.assertEqual(c['eyes']['right']['outflow'], 0.15)       # the drain is blocked

    def test_glaucoma_shrinks_the_visual_field(self):
        d = self.exam({'right': {'examined': True, 'cdr': 0.9, 'iop': 28}, 'left': {'examined': True, 'cdr': 0.3, 'iop': 15}})
        c = S.compute(d)
        self.assertEqual(c['eyes']['right']['glaucoma'], 'likely')
        self.assertLess(c['eyes']['right']['vision']['field'], 0.4)
        self.assertEqual(c['eyes']['left']['vision']['field'], 1.0)
        self.assertTrue(any('differ by 0.6' in a['text'] for a in c['alerts']))

    def test_retinopathy_reads_the_chart_values(self):
        d = self.exam({'right': {'examined': True, 'retina': {'dr': 'moderate', 'htn': 3}}})
        c = S.compute(d, {'diabetic': True, 'hba1c': 10.2, 'systolic': 200, 'diastolic': 110})
        texts = ' '.join(a['text'] for a in c['alerts'])
        self.assertIn('HbA1c 10.2%', texts)
        self.assertIn('hypertensive emergency', texts)
        calm = S.compute(d, {'systolic': 130, 'diastolic': 80})
        self.assertNotIn('hypertensive emergency', ' '.join(a['text'] for a in calm['alerts']))

    def test_hearing_grades_and_conductive_gap(self):
        d = self.exam(ears={'right': {'examined': True, 'ac': {'500': 40, '1000': 40, '2000': 35, '4000': 35}, 'bc': {'500': 5, '1000': 10, '2000': 10, '4000': 5},
                                      'tm': 'effusion'},
                            'left': {'examined': True, 'ac': {'500': 45, '1000': 50, '2000': 40, '4000': 45}}})
        c = S.compute(d)
        r, l = c['ears']['right'], c['ears']['left']
        self.assertEqual((r['pta'], r['grade'], r['type'], r['gap']), (37.5, 'moderate', 'conductive', 30.0))
        self.assertEqual(r['cochlea']['4000'], 0)                    # conductive loss: the hair cells are fine
        self.assertEqual(l['type'], 'sensorineural_probable')
        self.assertGreater(l['cochlea']['1000'], 0.3)
        self.assertTrue(c['hearing']['aid'])                          # moderate loss in the better ear
        self.assertIn(('grommet', 'right'), [(p['code'], p['side']) for p in c['procedures']])

    def test_asymmetric_sensorineural_loss_asks_for_mri(self):
        d = self.exam(ears={'right': {'examined': True, 'ac': {'500': 10, '1000': 10, '2000': 15, '4000': 15}},
                            'left': {'examined': True, 'ac': {'500': 40, '1000': 45, '2000': 50, '4000': 60}}})
        self.assertTrue(any('vestibular schwannoma' in a['text'] for a in S.compute(d)['alerts']))

    def test_cleaning_drops_nonsense(self):
        d = S.clean_exam({'eyes': {'right': {'va': '20/20', 'iop': 'high', 'cdr': 7, 'lens': 'glass', 'pupil_mm': 40}},
                          'ears': {'left': {'ac': {'500': 999, '3000': 20, '1000': 'x', '2000': 37}, 'tm': 'perforation'}}, 'weber': 'up'})
        self.assertEqual(d['eyes']['right']['va'], '')
        self.assertIsNone(d['eyes']['right']['iop'])
        self.assertEqual(d['eyes']['right']['cdr'], 1.0)
        self.assertEqual(d['eyes']['right']['lens'], 'clear')
        self.assertEqual(d['eyes']['right']['pupil_mm'], 9)
        self.assertEqual(d['ears']['left']['ac'], {'500': 120, '2000': 35})   # clipped and rounded to 5 dB; 3 kHz is not on the chart
        self.assertEqual(d['ears']['left']['perforation_pct'], 25)
        self.assertEqual(d['weber'], '')

    @__import__('unittest').skipUnless(NODE, 'node not installed')
    def test_javascript_computes_the_same(self):
        rng = random.Random(11)
        cases = [({'eyes': {'right': {'examined': True, 'va': '6/60', 'pinhole': '6/18', 'iop': 34, 'cdr': 0.8, 'lens': 'dense', 'rapd': True, 'conjunctiva': 'injected',
                                      'discharge': 'purulent', 'chamber': 'shallow', 'retina': {'dr': 'proliferative', 'maculopathy': True, 'htn': 3, 'detachment': True, 'amd': 'wet'}},
                            'left': {'examined': True, 'va': '6/9', 'iop': 18, 'cdr': 0.45, 'lens': 'early', 'conjunctiva': 'pterygium', 'retina': {'dr': 'mild', 'htn': 1}}},
                   'ears': {'right': {'examined': True, 'ac': {'250': 20, '500': 30, '1000': 35, '2000': 40, '4000': 65, '8000': 50}, 'bc': {'500': 10, '1000': 15, '2000': 20, '4000': 45},
                                      'tm': 'perforation', 'perforation_pct': 40, 'discharge': 'purulent', 'canal': 'wax'},
                            'left': {'examined': True, 'ac': {'500': 55, '1000': 60, '2000': 70, '4000': 80}, 'tm': 'cholesteatoma', 'tympanogram': 'B'}},
                   'symptoms': {'eye_pain': True, 'tinnitus': True, 'vertigo': True, 'sudden_loss': True}, 'weber': 'left'},
                  {'age': 67, 'diabetic': True, 'hba1c': 9.4, 'systolic': 192, 'diastolic': 118})]
        for _ in range(25):
            def eye():
                return {'examined': rng.random() < .9, 'va': rng.choice(S.ACUITY + ['']), 'pinhole': rng.choice(S.ACUITY + ['']), 'iop': rng.choice([None, rng.randint(2, 60)]),
                        'cdr': rng.choice([None, rng.randint(0, 20) / 20]), 'lens': rng.choice(list(S.LENS)), 'pupil_mm': rng.randint(2, 9), 'reaction': rng.choice(list(S.REACTION)),
                        'rapd': rng.random() < .2, 'conjunctiva': rng.choice(list(S.CONJUNCTIVA)), 'discharge': rng.choice(list(S.DISCHARGE_EYE)), 'cornea': rng.choice(list(S.CORNEA)),
                        'chamber': rng.choice(list(S.CHAMBER)), 'field': rng.choice(list(S.FIELD)),
                        'retina': {'dr': rng.choice(list(S.DR)), 'maculopathy': rng.random() < .2, 'htn': rng.randint(0, 4), 'papilloedema': rng.random() < .1,
                                   'detachment': rng.random() < .1, 'amd': rng.choice(list(S.AMD))}}

            def ear():
                return {'examined': rng.random() < .9, 'ac': {f: rng.randint(-2, 24) * 5 for f in S.FREQS if rng.random() < .85},
                        'bc': {f: rng.randint(-2, 16) * 5 for f in S.PTA_FREQS if rng.random() < .5}, 'canal': rng.choice(list(S.CANAL)), 'tm': rng.choice(list(S.TM)),
                        'perforation_pct': rng.randint(0, 100), 'discharge': rng.choice(list(S.DISCHARGE_EAR)), 'tympanogram': rng.choice(list(S.TYMPANOGRAM)),
                        'rinne': rng.choice(['', 'positive', 'negative'])}
            cases.append(({'eyes': {'right': eye(), 'left': eye()}, 'ears': {'right': ear(), 'left': ear()}, 'weber': rng.choice(['', 'central', 'left', 'right']),
                           'symptoms': {x: rng.random() < .3 for x in ('eye_pain', 'tinnitus', 'vertigo', 'sudden_loss')}},
                          {'age': rng.choice([None, 5, 40, 65]), 'diabetic': rng.random() < .5, 'hba1c': rng.choice([None, 7.1, 9.4]),
                           'systolic': rng.choice([None, 120, 185]), 'diastolic': rng.choice([None, 80, 125])}))
        payload = [[S.clean_exam(d), ctx] for d, ctx in cases]
        js = node_eval(f"global.window=globalThis;global.matchMedia=()=>({{matches:true}});require('{JS / 'senses-figure.js'}');"
                       f"console.log(JSON.stringify({json.dumps(payload)}.map(([d,c])=>MFSenses.compute(d,c))))")
        for (d, ctx), out in zip(payload, js):
            self.assertEqual(json.loads(json.dumps(S.compute(d, ctx))), out)


# ================================================================== eyes & ears: the page
class SenseExamViewTests(Base):
    def test_save_recompute_and_permissions(self):
        e = self.encounter()
        url = f'/encounters/{e.pk}/eyes-ears/'
        c = self.as_('doctor')
        self.assertContains(c.get(url), 'senses-boot')
        exam = {'eyes': {'right': {'examined': True, 'va': '6/60', 'lens': 'dense', 'iop': 'not a number'}}}
        r = c.post(url, json.dumps({'exam': exam}), **H).json()
        self.assertTrue(r['ok'])
        x = SenseExam.objects.get()
        self.assertIsNone(x.data['eyes']['right']['iop'])
        self.assertEqual(x.computed['procedures'][0]['code'], 'cataract')
        self.assertIn('procedure_type=', r['procedures'][0]['url'])       # links straight into theatre booking
        self.assertEqual(c.post(url, 'nonsense', **H).status_code, 400)
        c.logout()
        self.assertEqual(self.as_('reception').get(url).status_code, 403)

    def test_chart_shows_exam_on_timeline(self):
        e = self.encounter()
        self.as_('doctor').post(f'/encounters/{e.pk}/eyes-ears/', json.dumps({'exam': {'ears': {'left': {'examined': True, 'ac': {'500': 50, '1000': 50, '2000': 55}}}}}), **H)
        self.assertContains(self.client.get(f'/patients/{self.patient.pk}/'), 'Eye &amp; ear examination')


# ================================================================== theatre
class TheatreTests(Base):
    def setUp(self):
        self.e = self.encounter()
        self.e.vitals = {'bp': '120/80'}; self.e.save()
        self.room = OperatingRoom.objects.get(name='Main Theatre 1')
        self.hernia = ProcedureType.objects.get(code='hernia-inguinal')
        self.start = timezone.now().replace(second=0, microsecond=0) + timedelta(hours=2)

    def book(self, **kw):
        data = {'encounter': self.e.pk, 'procedure_type': self.hernia.pk, 'side': 'right', 'urgency': 'elective', 'specialty': 'general',
                'anaesthesia': 'spinal', 'est_minutes': 60, 'blood_units': 0, 'room': self.room.pk,
                'scheduled_start': timezone.localtime(self.start).strftime('%Y-%m-%dT%H:%M'), **kw}
        return self.as_('doctor').post('/theatre/new/', data)

    def act(self, c, path, body):
        return self.client.post(f'/theatre/cases/{c.pk}/{path}/', json.dumps(body), **H)

    def walk_to(self, c, status):
        """Take a case along the pathway the way the team would."""
        pre = {k: 'yes' for k, _, _ in T.preop_items(c)}
        steps = [('scheduled', None), ('ready', lambda: self.act(c, 'preop', {'preop': pre})),
                 ('in_theatre', lambda: self.act(c, 'checklist/sign_in', {'items': {k: 'yes' for k, _, _ in T.CHECKLIST['sign_in']['items']}})),
                 ('operating', lambda: self.act(c, 'checklist/time_out', {'items': {k: 'yes' for k, _, _ in T.CHECKLIST['time_out']['items']}, 'antibiotic_time': '09:15'})),
                 ('recovery', lambda: (self.client.post(f'/theatre/cases/{c.pk}/note/', {'procedure_performed': 'Right Lichtenstein repair', 'blood_loss_ml': '20'}),
                                       self.act(c, 'checklist/sign_out', {'items': {k: 'yes' for k, _, _ in T.CHECKLIST['sign_out']['items']}})))]
        for st, prep in steps:
            c.refresh_from_db()
            if T.PATH.index(c.status) >= T.PATH.index(status):
                break
            if T.PATH.index(c.status) >= T.PATH.index(st):
                continue
            if prep:
                prep()
            r = self.act(c, 'action', {'to': st})
            self.assertEqual(r.status_code, 200, r.content)
        c.refresh_from_db()
        return c

    def test_booking_schedules_and_side_is_required(self):
        r = self.book(side='')
        self.assertContains(r, 'state the side')
        self.book()
        c = SurgicalCase.objects.get()
        self.assertEqual((c.status, c.patient, c.procedure), ('scheduled', self.patient, 'Inguinal hernia repair'))
        self.assertEqual(c.title, 'Inguinal hernia repair (right)')

    def test_room_and_surgeon_clashes_are_refused(self):
        doc = self.users['doctor'].pk
        self.book(surgeon=doc)
        later = lambda m: timezone.localtime(self.start + timedelta(minutes=m)).strftime('%Y-%m-%dT%H:%M')
        self.assertContains(self.book(scheduled_start=later(70)), 'turnover')          # inside the 15-minute clean-up
        other = OperatingRoom.objects.get(name='Main Theatre 2').pk
        self.assertContains(self.book(room=other, surgeon=doc, scheduled_start=later(10)), 'surgeon is already operating')
        self.assertContains(self.book(room=other, scheduled_start=later(10)), 'patient already has')   # the same patient twice at once
        e2 = Encounter.objects.create(patient=Patient.objects.create(first_name='Ida', last_name='Sowe', dob='1980-01-01', sex='F'), department=self.dept, reason='Hernia')
        self.book(encounter=e2.pk, room=other, scheduled_start=later(10))              # another patient, another surgeon, another room: fine
        self.book(scheduled_start=later(75))                                           # after turnover in the same room is fine
        self.assertEqual(SurgicalCase.objects.filter(status='scheduled').count(), 3)

    def test_waiting_list_without_a_time(self):
        self.book(room='', scheduled_start='')
        self.assertEqual(SurgicalCase.objects.get().status, 'requested')

    def test_pathway_cannot_skip_safety_steps(self):
        self.book()
        c = SurgicalCase.objects.get()
        r = self.act(c, 'action', {'to': 'ready'})
        self.assertEqual(r.status_code, 400); self.assertIn('Consent', r.json()['error'])
        self.act(c, 'preop', {'preop': {k: 'yes' for k, _, _ in T.preop_items(c)}})
        self.assertEqual(self.act(c, 'action', {'to': 'ready'}).status_code, 200)
        r = self.act(c, 'action', {'to': 'operating'})                     # cannot jump into the operation
        self.assertEqual(r.status_code, 400)
        r = self.act(c, 'action', {'to': 'in_theatre'})
        self.assertIn('Sign in', r.json()['error'])
        r = self.act(c, 'checklist/time_out', {'items': {}})                # phases in order
        self.assertIn('Sign in', r.json()['error'])
        r = self.act(c, 'checklist/sign_in', {'items': {'identity': 'yes'}})
        self.assertIn('Answer every item', r.json()['error'])
        r = self.act(c, 'checklist/sign_in', {'items': {**{k: 'yes' for k, _, _ in T.CHECKLIST['sign_in']['items']}, 'oximeter': 'na'}})
        self.assertIn('Answer every item', r.json()['error'])               # the pulse oximeter cannot be "not applicable"
        c = self.walk_to(c, 'operating')
        self.assertIsNotNone(c.incision_at); self.assertTrue(T.phase_done(c, 'time_out'))
        self.assertEqual(c.checklist['time_out']['antibiotic_time'], '09:15')
        self.act(c, 'checklist/sign_out', {'items': {k: 'yes' for k, _, _ in T.CHECKLIST['sign_out']['items']}})
        r = self.act(c, 'action', {'to': 'recovery'})
        self.assertIn('operation note', r.json()['error'])
        self.assertTrue(AuditEvent.objects.filter(action='who_checklist').exists())

    def test_only_a_doctor_writes_the_note(self):
        self.book()
        c = self.walk_to(SurgicalCase.objects.get(), 'operating')
        self.client.logout()
        self.assertEqual(self.as_('nurse').post(f'/theatre/cases/{c.pk}/note/', {'procedure_performed': 'x'}).status_code, 403)

    def test_recovery_score_from_real_values_and_discharge(self):
        self.book()
        c = self.walk_to(SurgicalCase.objects.get(), 'recovery')
        self.assertEqual(c.status, 'recovery'); self.assertIsNotNone(c.out_room_at)
        low = {'systolic': 70, 'spo2': 89, 'on_oxygen': True, 'activity': 1, 'respiration': 1, 'consciousness': 1, 'heart_rate': 130}
        r = self.act(c, 'recovery', low).json()
        self.assertEqual(r['state']['recovery'][-1]['aldrete'], 4)             # 1+1+1, BP 42% below 120 → 1, SpO2 89 → 0
        self.assertTrue(any('below 90' in a for a in r['detail']['alerts']))
        r = self.act(c, 'action', {'to': 'completed', 'discharge_to': 'ward'})
        self.assertIn('below 9', r.json()['error'])
        self.act(c, 'recovery', {'systolic': 116, 'spo2': 97, 'activity': 2, 'respiration': 2, 'consciousness': 2})
        self.assertEqual(self.act(c, 'action', {'to': 'completed', 'discharge_to': 'ward'}).status_code, 200)
        c.refresh_from_db()
        self.assertEqual((c.status, c.discharge_to), ('completed', 'ward'))

    def test_cancel_needs_a_reason(self):
        self.book()
        c = SurgicalCase.objects.get()
        self.assertEqual(self.act(c, 'action', {'to': 'cancelled'}).status_code, 400)
        self.act(c, 'action', {'to': 'cancelled', 'reason': 'Patient unwell (URTI)'})
        c.refresh_from_db(); self.assertEqual((c.status, c.cancel_reason), ('cancelled', 'Patient unwell (URTI)'))

    def test_preop_warnings_come_from_the_latest_results(self):
        self.book()
        c = SurgicalCase.objects.get()
        test = LabTest.objects.get(code='RFT')
        o = LabOrder.objects.create(encounter=self.e, test=test, status='verified')
        LabResultValue.objects.create(order=o, parameter=LabParameter.objects.get(test=test, code='K'), value_number=Decimal('6.1'))
        c.fasting_since = timezone.now() - timedelta(hours=2); c.save()
        r = T.readiness(c)
        texts = ' '.join(w['text'] for w in r['warnings'])
        self.assertIn('Potassium 6.1', texts)
        self.assertIn('Not fasted long enough', texts)

    def test_billing_adds_operation_anaesthetic_and_theatre_time_once(self):
        self.book()
        c = self.walk_to(SurgicalCase.objects.get(), 'recovery')
        SurgicalCase.objects.filter(pk=c.pk).update(in_room_at=c.out_room_at - timedelta(minutes=95))
        from .services import capture_charges, open_invoice_for
        inv = open_invoice_for(self.e, self.users['reception'])
        capture_charges(inv); capture_charges(inv)
        lines = {l.source: l for l in InvoiceLine.objects.filter(invoice=inv)}
        self.assertEqual(lines[f'surgery:{c.pk}'].unit_price, Decimal('5000.00'))
        self.assertIn(f'anaesthesia:{c.pk}', lines)
        self.assertEqual(lines[f'theatre:{c.pk}'].quantity, 2)              # 95 minutes → 2 hours
        self.assertEqual(InvoiceLine.objects.filter(source__startswith='surgery:').count(), 1)

    def test_board_and_pages(self):
        self.book()
        c = SurgicalCase.objects.get()
        b = self.client.get(f'/theatre/api/board/?date={timezone.localdate(self.start).isoformat()}').json()
        self.assertEqual(b['cases'][0]['id'], c.pk)
        self.assertEqual(len(b['rooms']), 5)
        for url in ['/theatre/', f'/theatre/cases/{c.pk}/', f'/theatre/cases/{c.pk}/edit/', f'/encounters/{self.e.pk}/', f'/patients/{self.patient.pk}/']:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.client.logout()
        self.assertEqual(self.as_('pharmacy').get('/theatre/').status_code, 403)
