"""Ambulance service: triage, choosing the ambulance and hospital, the journey, crew API, handover into the emergency
queue, the public phone-app API, permissions, the demo simulator and the demo data."""
import json
from datetime import date

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from . import ambulance as A
from .models import Encounter, NetworkFacility, Notification, Patient, QueueTicket, StaffProfile
from .models_ambulance import Ambulance, ApiDevice, CrewShift, EmergencyCall, EmsStation, PositionPing

PW = 'test-only-Pa55word!'
SCENE = (13.4383, -16.6781)      # Serrekunda
CHEST = {'complaint': 'chest_pain', 'answers': {'u_awake': 'yes', 'u_breathing': 'yes', 'c_spread': 'yes'}, 'caller_phone': '+220 770 1234',
         'caller_name': 'Awa', 'patient_age': 58, 'patient_sex': 'M', 'latitude': SCENE[0], 'longitude': SCENE[1], 'landmark': 'Green gate'}


@override_settings(NOTIFY_EMAIL_SYNC=True, EMS_APP_KEYS=[], EMS_SIMULATION=True)
class EmsBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('bootstrap_hospital', verbosity=0)
        U = get_user_model()
        cls.u = {}
        for name, role in [('dispatcher', 'dispatcher'), ('medic', 'paramedic'), ('driver', 'driver'), ('reception', 'reception'),
                           ('nurse', 'nurse'), ('lab', 'lab'), ('manager', 'management')]:
            user = U.objects.create_user(username=name, password=PW, first_name=name.title(), last_name='Testsurname')
            StaffProfile.objects.create(user=user, role=role)
            cls.u[name] = user
        cls.base = EmsStation.objects.create(name='Base', kind='base', latitude=13.4452, longitude=-16.6772)
        far = EmsStation.objects.create(name='Far', kind='station', latitude=13.2714, longitude=-16.6494)
        cls.als = Ambulance.objects.create(call_sign='Hornbill 1', level='als', station=cls.base, latitude=13.4452, longitude=-16.6772)
        cls.bls_far = Ambulance.objects.create(call_sign='Kingfisher 9', level='bls', station=far, latitude=13.2714, longitude=-16.6494)
        cls.moto = Ambulance.objects.create(call_sign='Swift 1', level='moto', station=cls.base, latitude=13.4400, longitude=-16.6780)
        for a in (cls.als, cls.bls_far, cls.moto):
            CrewShift.objects.create(ambulance=a, user=cls.u['driver'] if a == cls.bls_far else cls.u['nurse'], role='driver')
        CrewShift.objects.create(ambulance=cls.als, user=cls.u['medic'], role='paramedic')

    def setUp(self):
        cache.clear()

    def as_(self, who, **kw):
        c = Client(**kw)
        c.login(username=who, password=PW)
        return c

    def call(self, **over):
        return A.create_call(dict(CHEST, **over), by=self.u['dispatcher'])

    def token(self, who='medic'):
        return 'Bearer ' + ApiDevice.issue(self.u[who], 'Test phone')[1]

    def api(self, method, url, data=None, auth=None, **headers):
        c = Client()
        if auth:
            headers['HTTP_AUTHORIZATION'] = auth
        if method == 'get':
            return c.get(url, data or {}, **headers)
        return c.post(url, json.dumps(data or {}), content_type='application/json', **headers)


class TriageTests(EmsBase):
    def test_answers_raise_priority_and_explain_why(self):
        self.assertEqual(A.triage('chest_pain', {})[0], 2)
        p, why = A.triage('chest_pain', {'c_spread': 'yes', 'u_awake': 'yes'})
        self.assertEqual(p, 1)
        self.assertIn('Crushing / spreading pain', why)
        self.assertEqual(A.triage('labour', {'l_early': 'yes'})[0], 2)
        self.assertEqual(A.triage('fall', {'u_awake': 'no'})[0], 1)        # universal questions apply
        self.assertEqual(A.triage('transfer', {'u_awake': 'no'})[0], 4)    # but not to planned transfers

    def test_every_complaint_is_well_formed(self):
        for c in A.COMPLAINTS:
            self.assertIn(c['base'], (1, 2, 3, 4))
            self.assertTrue(c['first_aid'], c['key'])
            keys = [q[0] for q in A.questions_for(c['key'])]
            self.assertEqual(len(keys), len(set(keys)), c['key'])
            for q in A.questions_for(c['key']):
                self.assertIn(q[2], ('yes', 'no'))

    def test_call_taker_can_override_with_reason_logged(self):
        c = A.create_call(dict(CHEST, priority='3'), by=self.u['dispatcher'])
        self.assertEqual(c.priority, 3)
        self.assertIn('set to P3', c.priority_reason)


class RecommendTests(EmsBase):
    def test_closest_advanced_crew_first_for_chest_pain(self):
        recs = A.recommend(self.call())
        self.assertEqual(recs[0]['a'], self.als)
        self.assertTrue(recs[0].get('best'))
        self.assertIn('Advanced life support crew', recs[0]['reasons'])

    def test_motorbike_is_first_response_for_p1_only(self):
        c = self.call(complaint='fall', answers={'u_awake': 'yes'})
        self.assertEqual(c.priority, 3)
        recs = A.recommend(c)
        self.assertNotEqual(recs[0]['a'], self.moto)
        self.assertIn('Motorbike: cannot carry a patient', next(r for r in recs if r['a'] == self.moto)['warn'])

    def test_busy_and_uncrewed_ambulances(self):
        A.dispatch(self.call(), self.als, self.u['dispatcher'])
        self.assertNotIn(self.als, [r['a'] for r in A.recommend(self.call())])
        CrewShift.objects.filter(ambulance=self.bls_far).update(ended_at='2026-01-01T00:00Z')
        far = next(r for r in A.recommend(self.call()) if r['a'] == self.bls_far)
        self.assertIn('No crew signed on', far['warn'])

    def test_destination_prefers_the_right_service(self):
        NetworkFacility.objects.create(name='Heart Centre', kind='clinic', capabilities='Cath lab, Cardiac ICU', latitude=13.4580, longitude=-16.7040,
                                       receives_ambulances=True)
        self.assertEqual(A.destinations(self.call())[0]['name'], 'Heart Centre')
        self.assertTrue(A.destinations(self.call(complaint='fall'))[0]['home'])


class JourneyTests(EmsBase):
    def test_full_journey_through_the_crew_api_ends_in_the_emergency_queue(self):
        c = self.call()
        A.dispatch(c, self.als, self.u['dispatcher'])
        auth = self.token()
        me = self.api('get', '/api/ems/v1/crew/me/', auth=auth).json()
        self.assertEqual(me['call']['reference'], c.reference)
        self.assertEqual(me['call']['next'][0], 'en_route')
        self.assertGreater(me['call']['prep']['total'], 5)
        # first GPS fix while moving starts the drive
        r = self.api('post', '/api/ems/v1/crew/position/', {'latitude': 13.4430, 'longitude': -16.6775, 'speed_kmh': 45}, auth=auth)
        self.assertEqual(r.json()['call_status'], 'en_route')
        self.assertTrue(PositionPing.objects.filter(ambulance=self.als).exists())
        self.assertEqual(self.api('post', '/api/ems/v1/crew/status/', {'status': 'on_scene'}, auth=auth).status_code, 200)
        r = self.api('post', '/api/ems/v1/crew/observations/', {'heart_rate': 132, 'systolic': 86, 'spo2': 91}, auth=auth)
        self.assertIn(['red', 'BP 86'], r.json()['flags'])
        self.api('post', '/api/ems/v1/crew/notes/', {'kind': 'treatment', 'text': 'Aspirin 300 mg chewed'}, auth=auth)
        key = me['call']['prep']['groups'][0]['items'][0]['key']
        self.assertEqual(self.api('post', '/api/ems/v1/crew/prep/', {'key': key, 'done': True}, auth=auth).json()['prep']['done'], 1)
        self.assertEqual(self.api('post', '/api/ems/v1/crew/prep/', {'key': 'not-a-real-item', 'done': True}, auth=auth).status_code, 409)
        self.api('post', '/api/ems/v1/crew/status/', {'status': 'transporting'}, auth=auth)
        self.assertTrue(Notification.objects.filter(kind='ambulance', title__startswith='Ambulance in').exists())   # pre-alert
        self.assertEqual(self.api('post', '/api/ems/v1/crew/handover/', {}, auth=auth).status_code, 409)              # not arrived yet
        self.api('post', '/api/ems/v1/crew/status/', {'status': 'at_hospital'}, auth=auth)
        h = self.api('get', '/api/ems/v1/crew/me/', auth=auth).json()['call']['handover']
        self.assertIn('BP 86', h['signs'])
        self.assertIn('Aspirin', h['treatment'])
        r = self.api('post', '/api/ems/v1/crew/handover/', dict(h, received_by='Dr Test'), auth=auth).json()
        self.assertTrue(r['registered'])
        c.refresh_from_db()
        self.assertEqual((c.status, c.outcome), ('closed', 'transported'))
        enc = Encounter.objects.get(pk=r['encounter'])
        self.assertEqual(enc.department.name, 'Emergency')
        self.assertEqual(enc.vitals['heart_rate'], 132)
        self.assertEqual(QueueTicket.objects.get(encounter=enc).priority, 1)
        self.assertIn('estimated', enc.patient.medical_alerts)
        self.assertEqual(enc.patient.dob, date(date.today().year - 58, 1, 1))
        self.als.refresh_from_db()
        self.assertEqual(self.als.status, 'returning')
        self.assertEqual(self.api('post', '/api/ems/v1/crew/available/', auth=auth).json()['unit']['status'], 'available')

    def test_known_patient_is_reused_and_their_history_reaches_the_crew(self):
        p = Patient.objects.create(first_name='Babucarr', last_name='Sowe', dob=date(1965, 3, 1), sex='M', phone='+220 712 4408')
        p.allergies.create(substance='Penicillin', reaction='Rash', severity='severe')
        self.assertEqual(A.lookup_caller('7124408')[0]['id'], p.pk)
        c = self.call(patient=p.pk)
        prep = A.prep_for(c)
        self.assertTrue(any('Penicillin' in a for a in prep['known']['allergies']))
        self.assertTrue(any('Penicillin' in i['text'] for g in prep['groups'] for i in g['items']))
        A.dispatch(c, self.als, self.u['dispatcher'])
        for to in ('en_route', 'on_scene', 'transporting', 'at_hospital'):
            A.advance(c, to, self.u['medic'])
        c.refresh_from_db()
        A.handover(c, {}, self.u['medic'])
        self.assertEqual(Patient.objects.filter(first_name='Babucarr').count(), 1)
        self.assertEqual(Encounter.objects.get(patient=p).reason[:9], 'Ambulance')

    def test_rules_refuse_impossible_steps(self):
        c = self.call()
        with self.assertRaises(A.Refused):
            A.advance(c, 'on_scene', self.u['medic'])
        A.dispatch(c, self.als, self.u['dispatcher'])
        with self.assertRaises(A.Refused):
            A.dispatch(self.call(), self.als, self.u['dispatcher'])            # already busy
        for to in ('en_route', 'on_scene'):
            A.advance(c, to, self.u['medic'])
        with self.assertRaises(A.Refused):
            A.advance(c, 'closed', self.u['medic'])                             # closing on scene needs a reason
        A.advance(c, 'closed', self.u['medic'], outcome='treated')
        with self.assertRaises(A.Refused):
            A.dispatch(self.call(latitude=None, longitude=None), self.moto, self.u['dispatcher'])   # nowhere to go

    def test_cancel_frees_the_ambulance(self):
        c = self.call()
        A.dispatch(c, self.als, self.u['dispatcher'])
        with self.assertRaises(A.Refused):
            A.cancel(c, self.u['dispatcher'], '  ')
        A.cancel(c, self.u['dispatcher'], 'Family drove him')
        self.als.refresh_from_db()
        self.assertEqual(self.als.status, 'returning')
        self.assertEqual(EmergencyCall.objects.get(pk=c.pk).outcome, 'cancelled')

    def test_simulator_drives_to_scene_and_hospital(self):
        c = self.call()
        A.dispatch(c, self.als, self.u['dispatcher'])
        for _ in range(60):
            A.simulate_tick(seconds=5, speedup=60)
            c.refresh_from_db()
            if c.status == 'on_scene':
                break
        self.assertEqual(c.status, 'on_scene')
        with override_settings(EMS_SIMULATION=False):
            with self.assertRaises(A.Refused):
                A.simulate_tick()


class PublicApiTests(EmsBase):
    def test_app_request_waits_for_call_back_and_can_be_tracked(self):
        r = self.api('post', '/api/ems/v1/requests/', CHEST)
        self.assertEqual(r.status_code, 201)
        d = r.json()
        c = EmergencyCall.objects.get(token=d['token'])
        self.assertEqual((c.status, c.source, c.priority), ('new', 'app', 1))
        self.assertTrue(Notification.objects.filter(user=self.u['dispatcher'], kind='ambulance').exists())
        A.verify(c, self.u['dispatcher'])
        A.dispatch(c, self.als, self.u['dispatcher'])
        s = self.api('get', f'/api/ems/v1/requests/{c.token}/').json()
        self.assertEqual(s['ambulance']['call_sign'], 'Hornbill 1')
        self.assertIsNotNone(s['eta_minutes'])
        dumped = json.dumps(s)
        self.assertNotIn('Testsurname', dumped)            # crew surnames stay private
        self.assertNotIn('770 1234', dumped)
        self.assertEqual(self.api('post', f'/api/ems/v1/requests/{c.token}/location/', {'latitude': 13.44, 'longitude': -16.68}).status_code, 200)
        self.assertEqual(Client().get(f'/e/{c.token}/').status_code, 200)

    def test_request_validation_and_abuse_limits(self):
        self.assertEqual(self.api('post', '/api/ems/v1/requests/', dict(CHEST, caller_phone='12')).status_code, 400)
        self.assertEqual(self.api('post', '/api/ems/v1/requests/', dict(CHEST, latitude='')).status_code, 400)
        self.assertEqual(self.api('post', '/api/ems/v1/requests/', CHEST).status_code, 201)
        self.assertEqual(self.api('post', '/api/ems/v1/requests/', CHEST).status_code, 201)
        self.assertEqual(self.api('post', '/api/ems/v1/requests/', CHEST).status_code, 409)     # two open requests per phone
        self.assertEqual(self.api('get', '/api/ems/v1/requests/nope/').status_code, 404)

    @override_settings(EMS_APP_KEYS=['secret-key'])
    def test_app_key_needed_to_ask_but_not_to_track(self):
        self.assertEqual(self.api('post', '/api/ems/v1/requests/', CHEST).status_code, 401)
        r = self.api('post', '/api/ems/v1/requests/', CHEST, HTTP_X_APP_KEY='secret-key')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.api('get', f'/api/ems/v1/requests/{r.json()["token"]}/').status_code, 200)

    def test_caller_cannot_cancel_once_the_crew_is_there(self):
        c = self.call()
        self.assertEqual(self.api('post', f'/api/ems/v1/requests/{c.token}/cancel/').status_code, 200)
        c2 = self.call(caller_phone='+220 333 4444')
        A.dispatch(c2, self.als, self.u['dispatcher'])
        A.advance(c2, 'en_route', None)
        A.advance(c2, 'on_scene', None)
        self.assertEqual(self.api('post', f'/api/ems/v1/requests/{c2.token}/cancel/').status_code, 409)

    def test_meta_and_openapi(self):
        m = self.api('get', '/api/ems/v1/meta/').json()
        self.assertEqual(len(m['complaints']), len(A.COMPLAINTS))
        spec = self.api('get', '/api/ems/v1/openapi.json').json()
        self.assertIn('/requests/{token}/', spec['paths'])
        self.assertIn('post', spec['paths']['/crew/status/'])


class AccessTests(EmsBase):
    def test_pages_by_role(self):
        c = self.call()
        for who, url, code in [('dispatcher', '/ambulance/', 200), ('dispatcher', '/ambulance/calls/new/', 200), ('dispatcher', f'/ambulance/calls/{c.pk}/', 200),
                               ('reception', '/ambulance/calls/new/', 200), ('medic', '/ambulance/calls/new/', 403), ('medic', '/ambulance/crew/', 200),
                               ('lab', '/ambulance/', 403), ('manager', '/ambulance/fleet/', 200), ('manager', '/ambulance/insights/', 200),
                               ('dispatcher', '/ambulance/api/', 200), ('dispatcher', '/ambulance/crew/', 403)]:
            self.assertEqual(self.as_(who).get(url).status_code, code, (who, url))
        self.assertEqual(Client().get('/ambulance/').status_code, 302)

    def test_desk_form_creates_a_call(self):
        r = self.as_('dispatcher').post('/ambulance/calls/new/', {'complaint': 'labour', 'q_l_bleeding': 'yes', 'caller_phone': '+220 700 0000',
                                                                  'latitude': SCENE[0], 'longitude': SCENE[1], 'source': 'phone'})
        c = EmergencyCall.objects.get(complaint='labour')
        self.assertRedirects(r, f'/ambulance/calls/{c.pk}/')
        self.assertEqual((c.priority, c.status), (1, 'waiting'))

    def test_session_api_needs_csrf_and_tokens_can_be_revoked(self):
        c = self.as_('medic', enforce_csrf_checks=True)
        r = c.post('/api/ems/v1/crew/available/', '{}', content_type='application/json')
        self.assertEqual(r.status_code, 403)
        dev, raw = ApiDevice.issue(self.u['medic'], 'Phone')
        self.assertEqual(self.api('get', '/api/ems/v1/crew/me/', auth=f'Bearer {raw}').status_code, 200)
        self.assertEqual(ApiDevice.objects.get(pk=dev.pk).key_hash, ApiDevice.hash(raw))     # only the hash is stored
        self.as_('manager').post(f'/ambulance/devices/{dev.pk}/revoke/')
        self.assertEqual(self.api('get', '/api/ems/v1/crew/me/', auth=f'Bearer {raw}').status_code, 401)
        self.assertEqual(self.api('get', '/api/ems/v1/dispatch/board/', auth=self.token('medic')).status_code, 200)
        self.assertEqual(self.api('post', '/api/ems/v1/dispatch/calls/', CHEST, auth=self.token('medic')).status_code, 403)

    def test_sign_in_for_a_token(self):
        r = self.api('post', '/api/ems/v1/auth/token/', {'username': 'medic', 'password': PW, 'device_name': 'Tablet'})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()['token'].startswith('ems_'))
        self.assertEqual(self.api('post', '/api/ems/v1/auth/token/', {'username': 'lab', 'password': PW}).status_code, 401)

    def test_dispatch_via_api(self):
        c = self.call()
        auth = self.token('dispatcher')
        rec = self.api('get', f'/api/ems/v1/dispatch/calls/{c.pk}/recommend/', auth=auth).json()
        r = self.api('post', f'/api/ems/v1/dispatch/calls/{c.pk}/assign/', {'ambulance': rec['units'][0]['id']}, auth=auth)
        self.assertEqual(r.json()['call']['status'], 'dispatched')
        self.assertTrue(Notification.objects.filter(user=self.u['medic'], kind='ambulance').exists())   # the crew hears about it


@override_settings(NOTIFY_EMAIL_SYNC=True, EMS_SIMULATION=True)
class FleetTests(EmsBase):
    NEW = {'call_sign': '  Pelican   4 ', 'plate': 'bjl 1234 a', 'level': 'neonatal', 'odometer_km': 1200, 'notes': 'Incubator fitted',
           'start_status': 'available'}

    def test_register_a_new_ambulance(self):
        c = self.as_('dispatcher')
        self.assertEqual(c.get('/ambulance/fleet/new/').status_code, 200)
        r = c.post('/ambulance/fleet/new/', dict(self.NEW, station=self.base.pk))
        self.assertRedirects(r, '/ambulance/fleet/')
        a = Ambulance.objects.get(call_sign='Pelican 4')
        self.assertEqual((a.plate, a.level, a.station, a.status, a.active), ('BJL 1234 A', 'neonatal', self.base, 'available', True))
        self.assertContains(c.get('/ambulance/fleet/'), 'Pelican 4')
        self.assertTrue(any(u['call_sign'] == 'Pelican 4' for u in A.board_payload()['units']))
        self.assertIn('Pelican 4', [x.call_sign for x in Ambulance.objects.filter(active=True)])

    def test_new_vehicle_can_start_out_of_service_and_without_a_station(self):
        self.as_('dispatcher').post('/ambulance/fleet/new/', dict(self.NEW, start_status='maintenance'))
        a = Ambulance.objects.get(call_sign='Pelican 4')
        self.assertEqual((a.status, a.station), ('maintenance', None))
        self.assertEqual(A.readiness(a)[0], 0)

    def test_call_sign_and_plate_must_be_unique(self):
        c = self.as_('dispatcher')
        r = c.post('/ambulance/fleet/new/', dict(self.NEW, call_sign='hornbill 1'))
        self.assertContains(r, 'already in the fleet')
        self.als.plate = 'BJL 1234 A'
        self.als.save()
        r = c.post('/ambulance/fleet/new/', self.NEW)
        self.assertContains(r, 'already registered to Hornbill 1')
        self.assertFalse(Ambulance.objects.filter(call_sign__iexact='pelican 4').exists())
        self.assertContains(c.post('/ambulance/fleet/new/', dict(self.NEW, call_sign='   ')), 'This field is required')

    def test_only_fleet_managers_register_or_edit(self):
        for who in ('medic', 'reception', 'lab'):
            self.assertEqual(self.as_(who).get('/ambulance/fleet/new/').status_code, 403, who)
            self.assertEqual(self.as_(who).post('/ambulance/fleet/new/', self.NEW).status_code, 403, who)
            self.assertEqual(self.as_(who).get(f'/ambulance/fleet/{self.als.pk}/edit/').status_code, 403, who)
        self.assertFalse(Ambulance.objects.filter(call_sign='Pelican 4').exists())
        self.assertNotContains(self.as_('medic').get('/ambulance/fleet/'), 'Register an ambulance')
        self.assertContains(self.as_('manager').get('/ambulance/fleet/'), 'Register an ambulance')   # managers run the fleet too

    def test_edit_keeps_live_state(self):
        self.als.fuel_pct, self.als.status = 40, 'off_duty'
        self.als.save()
        c = self.as_('dispatcher')
        self.assertContains(c.get(f'/ambulance/fleet/{self.als.pk}/edit/'), 'Edit Hornbill 1')
        r = c.post(f'/ambulance/fleet/{self.als.pk}/edit/', {'call_sign': 'Hornbill 1', 'plate': 'kmc 77', 'level': 'bls', 'station': '',
                                                              'odometer_km': 5000, 'notes': '', 'active': 'on'})
        self.assertRedirects(r, '/ambulance/fleet/')
        self.als.refresh_from_db()
        self.assertEqual((self.als.plate, self.als.level, self.als.station, self.als.fuel_pct, self.als.status), ('KMC 77', 'bls', None, 40, 'off_duty'))

    def test_retire_is_refused_on_a_call_or_with_crew_then_allowed(self):
        c = self.as_('dispatcher')
        edit = lambda: c.post(f'/ambulance/fleet/{self.als.pk}/edit/', {'call_sign': 'Hornbill 1', 'level': 'als', 'station': self.base.pk,
                                                                         'odometer_km': 0, 'notes': ''})   # 'active' unticked
        call = A.dispatch(self.call(), self.als, self.u['dispatcher'])
        self.assertContains(edit(), 'is on a call')
        A.cancel(call, self.u['dispatcher'], 'test')
        self.assertContains(edit(), 'crew is still on board')
        self.als.refresh_from_db()
        self.assertTrue(self.als.active)
        CrewShift.objects.filter(ambulance=self.als).update(ended_at=call.closed_at or call.updated_at)
        self.assertRedirects(edit(), '/ambulance/fleet/')
        self.als.refresh_from_db()
        self.assertFalse(self.als.active)
        page = c.get('/ambulance/fleet/')
        self.assertContains(page, 'Retired vehicles')
        self.assertNotIn('Hornbill 1', [u['call_sign'] for u in A.board_payload()['units']])
        self.assertContains(c.post('/ambulance/fleet/new/', dict(self.NEW, call_sign='HORNBILL 1')), '(retired)')


class DemoDataTests(TestCase):
    def test_seed_runs_once_and_every_page_renders(self):
        call_command('bootstrap_hospital', verbosity=0)
        call_command('seed_ambulance', verbosity=0, days=5, force=True)
        call_command('seed_ambulance', verbosity=0, force=True)         # second run adds nothing
        self.assertEqual(EmsStation.objects.count(), 9)
        self.assertEqual(set(EmergencyCall.objects.filter(status__in=EmergencyCall.OPEN).values_list('status', flat=True)),
                         {'new', 'waiting', 'dispatched', 'en_route', 'on_scene', 'transporting', 'at_hospital'})
        c = Client()
        c.login(username='dispatch.sanneh', password='medflow-demo-2026')
        for url in ['/ambulance/', '/ambulance/fleet/', '/ambulance/insights/', '/ambulance/calls/new/'] + \
                   [f'/ambulance/calls/{x.pk}/' for x in EmergencyCall.objects.all()[:12]]:
            self.assertEqual(c.get(url).status_code, 200, url)
        c.login(username='medic.jobe', password='medflow-demo-2026')
        self.assertEqual(c.get('/api/ems/v1/crew/me/').json()['call']['status'], 'on_scene')
