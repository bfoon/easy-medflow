"""FICTIONAL demo data for the ambulance service (hospital/ambulance.py).

Stations from Banjul to Basse, a fleet named after Gambian birds, crews on shift, live calls in every state of the
journey (one at each step, so every screen has something to show), and 30 days of finished calls for the insights.
Live calls run through the real service layer, so they obey the same rules as real use; times are then moved into the past.

Never run against a database that holds real patient information.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from . import ambulance as A
from .models import Department, Location, NetworkFacility, Patient, StaffProfile
from .models_ambulance import Ambulance, CallEvent, CallObservation, CrewShift, EmergencyCall, EmsStation, PositionPing

STATIONS = [  # name, code, kind, lat, lon, address, phone
    ('Westfield EMS Base', 'WFB', 'base', 13.4452, -16.6772, 'Kairaba Avenue junction, next to the hospital', '+220 440 1122'),
    ('Bakau Coastal Post', 'BKP', 'post', 13.4781, -16.6819, 'Atlantic Road, by the fish market', ''),
    ('Brusubi Turntable Post', 'BRT', 'post', 13.4250, -16.7400, 'Brusubi roundabout, Kombo Coastal Road', ''),
    ('Brikama Station', 'BRK', 'station', 13.2714, -16.6494, 'Brikama main road, opposite the market', '+220 448 3300'),
    ('Barra Ferry Post', 'BFP', 'post', 13.4800, -16.5450, 'Barra ferry terminal', ''),
    ('Farafenni Station', 'FRF', 'station', 13.5667, -15.6000, 'Trans-Gambia highway, Farafenni', '+220 573 0101'),
    ('Soma Junction Post', 'SMJ', 'post', 13.4400, -15.5300, 'Soma junction filling station', ''),
    ('Janjanbureh Jetty', 'JJB', 'jetty', 13.5333, -14.7667, 'MacCarthy Island ferry jetty', ''),
    ('Basse Upriver Station', 'BSS', 'station', 13.3100, -14.2100, 'Basse Santa Su, near the bridge', '+220 566 2020'),
]
FLEET = [  # call sign, level, station code, plate, fuel, oxygen
    ('Hornbill 1', 'als', 'WFB', 'KM 4471 A', 82, 90), ('Hornbill 2', 'als', 'WFB', 'KM 4472 A', 64, 76),
    ('Kingfisher 1', 'bls', 'BKP', 'KM 2210 B', 91, 95), ('Kingfisher 2', 'bls', 'BRT', 'WCR 3318 C', 18, 80),
    ('Sunbird 1', 'neonatal', 'BRK', 'WCR 5501 M', 70, 88), ('Heron 1', 'rural', 'BRK', 'WCR 7720 R', 77, 92),
    ('Swift 1', 'moto', 'WFB', 'KM 0091 M', 100, 100), ('Weaver 1', 'bls', 'BFP', 'NBR 1402 B', 55, 35),
    ('Egret 1', 'rural', 'FRF', 'NBR 6630 R', 88, 97), ('Bee-eater 1', 'bls', 'SMJ', 'LRR 2290 B', 93, 90),
    ('Pelican 1', 'boat', 'JJB', 'CRR BOAT 1', 66, 100), ('Roller 1', 'rural', 'BSS', 'URR 4410 R', 40, 85),
]
CREW = [  # username, first, last, staff role
    ('dispatch.sanneh', 'Haddy', 'Sanneh', 'dispatcher'), ('dispatch.kah', 'Alhagie', 'Kah', 'dispatcher'),
    ('medic.jobe', 'Omar', 'Jobe', 'paramedic'), ('medic.faye', 'Ndey', 'Faye', 'paramedic'), ('medic.colley', 'Pa Modou', 'Colley', 'paramedic'),
    ('medic.bojang', 'Isatou', 'Bojang', 'paramedic'), ('medic.jammeh', 'Ebou', 'Jammeh', 'paramedic'),
    ('driver.manneh', 'Kebba', 'Manneh', 'driver'), ('driver.sarr', 'Musa', 'Sarr', 'driver'), ('driver.kujabi', 'Lamin', 'Kujabi', 'driver'),
    ('driver.secka', 'Saikou', 'Secka', 'driver'), ('driver.touray', 'Bubacarr', 'Touray', 'driver'),
    ('midwife.drammeh', 'Kaddy', 'Drammeh', 'nurse'),
]
# who is on which vehicle now: call sign → [(username, crew role)]
ROSTER = {
    'Hornbill 1': [('medic.jobe', 'paramedic'), ('driver.manneh', 'driver')],
    'Hornbill 2': [('medic.colley', 'paramedic'), ('driver.sarr', 'driver')],
    'Kingfisher 1': [('medic.faye', 'paramedic'), ('driver.kujabi', 'driver')],
    'Kingfisher 2': [('medic.bojang', 'emt'), ('driver.secka', 'driver')],
    'Sunbird 1': [('midwife.drammeh', 'midwife'), ('driver.touray', 'driver')],
    'Heron 1': [('medic.jammeh', 'paramedic')],
    'Swift 1': [('nurse.bah', 'nurse')],
    'Weaver 1': [('dr.ceesay', 'doctor')],
}
FACILITIES = {  # existing demo facilities that take ambulances, with map positions
    'Banjul Regional Teaching Hospital': (13.4530, -16.5770), 'Brikama Mother & Child Centre': (13.2740, -16.6430),
    'Kotu Heart Centre': (13.4580, -16.7040), 'Riverside Orthopaedic & Spine Clinic': (13.4760, -16.6790),
}
NEW_FACILITIES = [  # fictional up-country hospitals
    ('North Bank General Hospital (Farafenni)', 'Farafenni', 13.5690, -15.5980, '+220 573 0200', 'Emergency, ICU, Theatre, Maternity, X-ray'),
    ('Upriver Regional Hospital (Bansang)', 'Bansang', 13.4350, -14.6530, '+220 567 1100', 'Emergency, Theatre, Maternity, Paediatric, Antivenom'),
]
WEIGHTS = [('chest_pain', 9), ('breathing', 9), ('rta', 14), ('labour', 16), ('sick_child', 12), ('fall', 10), ('seizure', 6), ('stroke', 5),
           ('unconscious', 5), ('bleeding', 4), ('burns', 3), ('snakebite', 3), ('poisoning', 3), ('transfer', 6), ('arrest', 2), ('drowning', 1), ('other', 4)]
LANDMARKS = ['opposite the mosque', 'behind the bakery', 'near the football field', 'next to the primary school', 'by the big baobab tree',
             'blue gate after the pharmacy', 'compound with the green door', 'at the taxi garage', 'near the health centre', 'by the market entrance']
NOW = None


def ago(minutes):
    return NOW - timedelta(minutes=minutes)


def _users(password):
    U = get_user_model()
    em = Department.objects.filter(name='Emergency').first()
    out = {}
    for username, first, last, role in CREW:
        u = U.objects.filter(username=username).first()
        if not u:
            u = U.objects.create_user(username=username, password=password, first_name=first, last_name=last)
        StaffProfile.objects.get_or_create(user=u, defaults={'role': role, 'department': em})
        out[username] = u
    for username in ('nurse.bah', 'dr.ceesay'):
        u = U.objects.filter(username=username).first()
        if u:
            out[username] = u
    return out


def _between(a, b, f):
    return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f


def _place(amb, lat, lon, heading=0, speed=0, minutes=0):
    Ambulance.objects.filter(pk=amb.pk).update(latitude=lat, longitude=lon, heading=heading, speed_kmh=speed, position_at=ago(minutes))
    amb.refresh_from_db()


def _retime(call):
    """Give the timeline events the same times as the journey they describe."""
    marks = [('P', call.received_at), ('Sent without', call.dispatched_at), ('Confirmed', call.verified_at), (' assigned', call.dispatched_at),
             ('Ambulance on the way', call.en_route_at), ('Crew with', call.on_scene_at), ('On the way to hospital', call.transporting_at),
             ('Pre-alert', call.transporting_at), ('Arrived at hospital', call.at_hospital_at), ('Closed', call.closed_at), ('Cancelled', call.closed_at)]
    for e in call.events.filter(kind__in=['status', 'system']):
        for key, t in marks:
            if t and (e.text.startswith(key) if key != ' assigned' else key in e.text):
                CallEvent.objects.filter(pk=e.pk).update(at=t)
                break


def _stamp(call, **times):
    EmergencyCall.objects.filter(pk=call.pk).update(**times)
    call.refresh_from_db()
    _retime(call)


def _obs(call, minutes, by=None, **v):
    o = CallObservation.objects.create(call=call, by=by, **v)
    CallObservation.objects.filter(pk=o.pk).update(taken_at=ago(minutes))


def _treat(call, minutes, text, by=None):
    CallEvent.objects.create(call=call, kind='treatment', text=text, by=by, at=ago(minutes))


def _loc(name):
    return Location.objects.filter(name=name).first()


def run(password='medflow-demo-2026', history_days=30):
    """Create everything. Returns a list of what was made, or None if the ambulance service already has stations."""
    global NOW
    if EmsStation.objects.exists():
        return None
    NOW = timezone.now()
    rnd = random.Random(2026)
    users = _users(password)
    dispatcher = users['dispatch.sanneh']

    # ---------------------------------------------------------------- places and vehicles
    st = {}
    for name, code, kind, lat, lon, addr, phone in STATIONS:
        st[code] = EmsStation.objects.create(name=name, code=code, kind=kind, latitude=lat, longitude=lon, address=addr, phone=phone)
    for name, (lat, lon) in FACILITIES.items():
        NetworkFacility.objects.filter(name=name).update(latitude=lat, longitude=lon, receives_ambulances=True)
    for name, town, lat, lon, phone, caps in NEW_FACILITIES:
        NetworkFacility.objects.get_or_create(name=name, defaults={'kind': 'hospital', 'location': town, 'phone': phone, 'capabilities': caps,
                                                                  'latitude': lat, 'longitude': lon, 'receives_ambulances': True})
    units = {}
    for sign, level, code, plate, fuel, oxy in FLEET:
        s = st[code]
        units[sign] = Ambulance.objects.create(call_sign=sign, level=level, station=s, plate=plate, fuel_pct=fuel, oxygen_pct=oxy,
                                               latitude=s.latitude, longitude=s.longitude, position_at=ago(rnd.randint(1, 30)),
                                               odometer_km=rnd.randint(18000, 140000), checklist={k: True for k, _ in A.READINESS},
                                               checked_at=NOW.replace(hour=7, minute=rnd.randint(5, 50)) if NOW.hour >= 8 else ago(60),
                                               checked_by=users['medic.jobe'])
    Ambulance.objects.filter(call_sign='Weaver 1').update(checklist=dict({k: True for k, _ in A.READINESS}, oxygen=False), notes='Spare oxygen cylinder empty, collect at base')
    Ambulance.objects.filter(call_sign='Egret 1').update(checked_at=ago(60 * 26))
    Ambulance.objects.filter(call_sign='Bee-eater 1').update(status='off_duty')
    Ambulance.objects.filter(call_sign='Roller 1').update(status='maintenance', notes='Rear suspension: in the workshop until Friday')
    for sign, people in ROSTER.items():
        for username, role in people:
            if username in users:
                s = CrewShift.objects.create(ambulance=units[sign], user=users[username], role=role)
                CrewShift.objects.filter(pk=s.pk).update(started_at=NOW.replace(hour=7, minute=30) if NOW.hour >= 8 else ago(90))
    for u in units.values():
        u.refresh_from_db()
    told = [f'{len(STATIONS)} stations, {len(FLEET)} ambulances, {sum(len(v) for v in ROSTER.values())} crew on shift']

    home = A.home()
    babucarr = Patient.objects.filter(first_name='Babucarr', last_name='Sowe').first()

    # ---------------------------------------------------------------- 1. P1 chest pain in Bakau: Hornbill 2 on the way (known cardiac patient)
    c = A.create_call({'complaint': 'chest_pain', 'answers': {'u_awake': 'yes', 'u_breathing': 'yes', 'c_spread': 'yes', 'c_sweaty': 'yes', 'c_history': 'yes'},
                       'caller_name': 'Awa Sowe', 'caller_phone': babucarr.phone if babucarr else '+220 712 4408', 'caller_relation': 'Daughter',
                       'patient': babucarr.pk if babucarr else '', 'patient_name': 'Babucarr Sowe', 'patient_age': 61, 'patient_sex': 'M',
                       'description': 'Crushing pain in the chest since he came back from the mosque, sweating a lot. Had chest pain last week too.',
                       'landmark': 'Cape Point road, yellow house behind the Total station', 'latitude': 13.4795, 'longitude': -16.6735,
                       'location': getattr(_loc('Bakau'), 'pk', '')}, by=dispatcher)
    kotu = NetworkFacility.objects.filter(name='Kotu Heart Centre').first()
    A.dispatch(c, units['Hornbill 2'], dispatcher, destination=kotu)
    c.refresh_from_db()
    A.advance(c, 'en_route', users['driver.sarr'])
    _stamp(c, received_at=ago(9), verified_at=ago(9), dispatched_at=ago(7), en_route_at=ago(6), eta_scene_at=NOW + timedelta(minutes=5))
    wf = (st['WFB'].latitude, st['WFB'].longitude)
    for i, f in enumerate([.1, .25, .4, .55]):
        lat, lon = _between(wf, (c.latitude, c.longitude), f)
        PositionPing.objects.create(ambulance=units['Hornbill 2'], call=c, latitude=lat, longitude=lon, speed_kmh=48 + i * 4, heading=8, at=ago(6 - i * 1.5))
    _place(units['Hornbill 2'], *_between(wf, (c.latitude, c.longitude), .55), heading=8, speed=56)
    A.log(c, 'Daughter told: chew one aspirin 300 mg, sit him up, unlock the gate', 'note', dispatcher)
    told.append(f'{c.reference}: P1 chest pain in Bakau, Hornbill 2 on the way to Babucarr Sowe (known cardiac patient)')

    # ---------------------------------------------------------------- 2. P1 road crash at Brusubi: Hornbill 1 on scene, two patients
    c = A.create_call({'complaint': 'rta', 'answers': {'u_awake': 'yes', 'u_breathing': 'yes', 'u_bleeding': 'yes', 'r_pedestrian': 'yes', 'r_walking': 'no'},
                       'caller_name': 'Police officer Jarju', 'caller_phone': '+220 990 4410', 'caller_relation': 'Police', 'patients_count': 2,
                       'patient_name': 'Unknown man', 'patient_age': 30, 'patient_sex': 'M',
                       'description': 'Gele-gele van hit a motorbike at the turntable. Rider on the ground bleeding from the leg, passenger walking.',
                       'landmark': 'Brusubi turntable, Kombo Coastal Road side', 'latitude': 13.4262, 'longitude': -16.7385, 'source': 'police'},
                      by=users.get('dispatch.kah', dispatcher), source='police')
    A.dispatch(c, units['Hornbill 1'], dispatcher)
    c.refresh_from_db()
    for to in ('en_route', 'on_scene'):
        A.advance(c, to, users['medic.jobe'])
    _stamp(c, received_at=ago(24), verified_at=ago(24), dispatched_at=ago(23), en_route_at=ago(22), on_scene_at=ago(11))
    _place(units['Hornbill 1'], 13.4259, -16.7381)
    _obs(c, 9, users['medic.jobe'], heart_rate=124, systolic=94, diastolic=60, resp_rate=24, spo2=95, gcs=14, avpu='V', pain=8)
    _treat(c, 8, 'Tourniquet right thigh 13 cm above knee, bleeding controlled', users['medic.jobe'])
    _treat(c, 6, 'Tranexamic acid 1 g IV', users['medic.jobe'])
    _obs(c, 3, users['medic.jobe'], heart_rate=112, systolic=102, diastolic=66, resp_rate=22, spo2=97, gcs=15, avpu='A', pain=6)
    _treat(c, 2, 'Traction splint right femur; morphine 5 mg IV', users['medic.jobe'])
    A.log(c, 'Second patient (passenger) walking, cut on forearm; Kingfisher 2 not needed', 'note', users['medic.jobe'])
    prep = A.prep_for(c)
    for g in prep['groups'][:2]:
        for item in g['items'][:4]:
            A.toggle_prep(c, item['key'], True, users['medic.jobe'])
    _place(units['Kingfisher 2'], st['BRT'].latitude, st['BRT'].longitude)
    told.append(f'{c.reference}: P1 motorbike crash at Brusubi, Hornbill 1 on scene with vitals and treatment (sign in as medic.jobe)')

    # ---------------------------------------------------------------- 3. P2 labour in Lamin: Sunbird 1 bringing her here
    c = A.create_call({'complaint': 'labour', 'answers': {'u_awake': 'yes', 'u_breathing': 'yes', 'l_head': 'no', 'l_bleeding': 'no', 'l_early': 'yes'},
                       'caller_name': 'Momodou Ceesay', 'caller_phone': '+220 788 3021', 'caller_relation': 'Husband',
                       'patient_name': 'Mariama Ceesay', 'patient_age': 24, 'patient_sex': 'F',
                       'description': 'Pains every 4 minutes since this morning, 35 weeks, first baby.', 'landmark': 'Lamin, behind the lodge, compound with the mango trees',
                       'latitude': 13.3601, 'longitude': -16.6420, 'location': getattr(_loc('Lamin'), 'pk', '')}, by=dispatcher)
    A.dispatch(c, units['Sunbird 1'], dispatcher)
    c.refresh_from_db()
    for to in ('en_route', 'on_scene', 'transporting'):
        A.advance(c, to, users['midwife.drammeh'])
    _stamp(c, received_at=ago(52), verified_at=ago(52), dispatched_at=ago(50), en_route_at=ago(49), on_scene_at=ago(31), transporting_at=ago(12),
           eta_hospital_at=NOW + timedelta(minutes=7))
    _obs(c, 25, users['midwife.drammeh'], heart_rate=96, systolic=118, diastolic=74, resp_rate=18, spo2=99, temperature_c=Decimal('37.1'), avpu='A', pain=7)
    _obs(c, 10, users['midwife.drammeh'], heart_rate=102, systolic=122, diastolic=78, resp_rate=20, spo2=99, avpu='A', pain=8)
    _treat(c, 24, 'Contractions every 3–4 min, lasting 50 s; membranes intact; fetal heart 142', users['midwife.drammeh'])
    _treat(c, 15, 'Left lateral position, Entonox for pain', users['midwife.drammeh'])
    _place(units['Sunbird 1'], *_between((c.latitude, c.longitude), (home['lat'], home['lon']), .62), heading=350, speed=52)
    told.append(f'{c.reference}: P2 preterm labour, Sunbird 1 arriving at this hospital in 7 minutes (see “Arriving”)')

    # ---------------------------------------------------------------- 4. P2 seizure: Weaver 1 already at the hospital, ready to hand over
    c = A.create_call({'complaint': 'seizure', 'answers': {'u_awake': 'yes', 'u_breathing': 'yes', 'z_child_fever': 'yes', 'z_long': 'no'},
                       'caller_name': 'Binta Jallow', 'caller_phone': '+220 361 7745', 'caller_relation': 'Mother', 'patient_name': 'Alieu Jallow',
                       'patient_age': 3, 'patient_sex': 'M', 'description': 'Fitting with high fever, stopped after 3 minutes, now sleepy.',
                       'landmark': 'Essau, near the old ferry road', 'latitude': 13.4830, 'longitude': -16.5340, 'location': getattr(_loc('Essau'), 'pk', '')}, by=dispatcher)
    A.dispatch(c, units['Weaver 1'], dispatcher)
    c.refresh_from_db()
    for to in ('en_route', 'on_scene', 'transporting', 'at_hospital'):
        A.advance(c, to, users['dr.ceesay'] if 'dr.ceesay' in users else dispatcher)
    _stamp(c, received_at=ago(80), verified_at=ago(80), dispatched_at=ago(78), en_route_at=ago(77), on_scene_at=ago(66), transporting_at=ago(55), at_hospital_at=ago(4))
    _obs(c, 60, None, heart_rate=158, resp_rate=34, spo2=94, temperature_c=Decimal('39.8'), glucose_mmol=Decimal('5.6'), avpu='V')
    _obs(c, 20, None, heart_rate=142, resp_rate=30, spo2=97, temperature_c=Decimal('38.9'), avpu='A')
    _treat(c, 58, 'Paracetamol 180 mg PR; cooled; recovery position', None)
    _treat(c, 40, 'Malaria rapid test positive (Pf)', None)
    _place(units['Weaver 1'], home['lat'] + .0004, home['lon'] + .0003)
    told.append(f'{c.reference}: P2 febrile seizure, Weaver 1 at this hospital waiting to hand over (ATMIST pre-filled)')

    # ---------------------------------------------------------------- 5. P2 snakebite in Sanyang: Heron 1 just assigned
    c = A.create_call({'complaint': 'snakebite', 'answers': {'u_awake': 'yes', 'u_breathing': 'yes', 'k_swelling': 'no', 'k_bleed': 'no', 'k_eyes': 'no'},
                       'caller_name': 'Yusupha Bojang', 'caller_phone': '+220 703 5512', 'caller_relation': 'Brother', 'patient_name': 'Sulayman Bojang',
                       'patient_age': 17, 'patient_sex': 'M', 'description': 'Bitten on the foot in the rice field 20 minutes ago, brown snake, foot swollen around the bite.',
                       'landmark': 'Sanyang rice fields, path past the school, someone will wait on the road', 'latitude': 13.2720, 'longitude': -16.7660,
                       'location': getattr(_loc('Sanyang'), 'pk', '')}, by=dispatcher)
    A.dispatch(c, units['Heron 1'], dispatcher, destination=None)
    _stamp(c, received_at=ago(5), verified_at=ago(5), dispatched_at=ago(1), eta_scene_at=NOW + timedelta(minutes=19))
    told.append(f'{c.reference}: P2 snakebite in Sanyang, Heron 1 (4×4) just assigned')

    # ---------------------------------------------------------------- 6. P1 sick child from the phone app: waiting for the call-back
    c = A.create_call({'complaint': 'sick_child', 'answers': {'u_awake': 'yes', 'u_breathing': 'yes', 'h_floppy': 'yes', 'h_drink': 'yes'},
                       'caller_name': 'Isatou Touray', 'caller_phone': '+220 377 2290', 'patient_name': 'Fatoumata', 'patient_age': 1, 'patient_sex': 'F',
                       'description': 'Baby very hot since yesterday, not breastfeeding, very sleepy', 'landmark': 'Dippa Kunda, near the football field',
                       'latitude': 13.4338, 'longitude': -16.6716, 'accuracy_m': 14}, source='app')
    _stamp(c, received_at=ago(3))
    A.log(c, 'Caller: The house with the blue gate, I will send my son to the road', 'message')
    told.append(f'{c.reference}: P1 floppy baby from the phone app, waiting for the service desk to call back')

    # ---------------------------------------------------------------- 7. P3 fall in Brikama: waiting
    c = A.create_call({'complaint': 'fall', 'answers': {'u_awake': 'yes', 'u_breathing': 'yes', 'f_head': 'no', 'f_neck': 'no', 'f_height': 'no'},
                       'caller_name': 'Ousman Darboe', 'caller_phone': '+220 745 1180', 'caller_relation': 'Son', 'patient_name': 'Haddy Darboe',
                       'patient_age': 79, 'patient_sex': 'F', 'description': 'Slipped in the bathroom, cannot stand, pain in the right hip.',
                       'landmark': 'Nema, behind the Gamtel office', 'location': getattr(_loc('Nema'), 'pk', '')}, by=dispatcher)
    _stamp(c, received_at=ago(17), verified_at=ago(17))
    told.append(f'{c.reference}: P3 older woman with a hip injury in Brikama, waiting (Kingfisher 2 is low on fuel: see the warning)')

    # ---------------------------------------------------------------- 8. P4 transfer from Farafenni: waiting
    c = A.create_call({'complaint': 'transfer', 'answers': {'t_ventilated': 'no', 't_time': 'no'}, 'caller_name': 'Nurse Sowe, North Bank General',
                       'caller_phone': '+220 573 0200', 'caller_relation': 'Health centre', 'patient_name': 'Ebrima Faal', 'patient_age': 54, 'patient_sex': 'M',
                       'description': 'Stable diabetic foot, for surgical review at E-MedFlow. Notes and X-ray ready.',
                       'landmark': 'North Bank General Hospital, ward 2', 'latitude': 13.5690, 'longitude': -15.5980, 'source': 'transfer'}, by=dispatcher, source='transfer')
    _stamp(c, received_at=ago(40), verified_at=ago(40))
    _place(units['Egret 1'], st['FRF'].latitude, st['FRF'].longitude)
    told.append(f'{c.reference}: P4 transfer from Farafenni, waiting for Egret 1')

    # ---------------------------------------------------------------- 30 days of finished calls
    n = _history(rnd, history_days, users, units, st)
    told.append(f'{n} finished calls over the last {history_days} days for the insights page')
    return told


def _history(rnd, days, users, units, st):
    towns = list(Location.objects.filter(kind='town', active=True))
    near = [t for t in towns if float(t.longitude) < -16.4] or towns
    ambs = [u for u in units.values() if u.level not in ('boat',)]
    facilities = list(NetworkFacility.objects.filter(receives_ambulances=True))
    keys, weights = zip(*WEIGHTS)
    calls, events = [], []
    for d in range(days, -1, -1):
        day_start = (NOW - timedelta(days=d)).replace(hour=0, minute=0, second=0, microsecond=0)
        for _ in range(rnd.randint(5, 13) if d else 4):
            hour = rnd.choices(range(24), weights=[1, 1, 1, 1, 1, 2, 3, 5, 6, 6, 6, 6, 6, 6, 6, 7, 8, 9, 9, 8, 6, 4, 3, 2])[0]
            rec = day_start + timedelta(hours=hour, minutes=rnd.randint(0, 59))
            if rec > NOW - timedelta(hours=2):
                continue
            key = rnd.choices(keys, weights=weights)[0]
            town = rnd.choice(near if rnd.random() < .8 else towns)
            lat, lon = float(town.latitude) + rnd.uniform(-.008, .008), float(town.longitude) + rnd.uniform(-.008, .008)
            amb = min(rnd.sample(ambs, 4), key=lambda a: A.km(a.station.latitude, a.station.longitude, lat, lon))
            dist = A.km(amb.station.latitude, amb.station.longitude, lat, lon) * A.ROAD_FACTOR
            p = A.complaint(key)['base']
            if rnd.random() < .3:
                p = max(1, p - 1)
            resp = 2 + rnd.uniform(.5, 3) + dist / A.speed_kmh(amb.level, p, lon) * 60 * rnd.uniform(.9, 1.6)
            src = rnd.choices(['phone', 'app', 'police', 'transfer'], weights=[60, 25, 8, 7 if key == 'transfer' else 0])[0]
            outcome = rnd.choices(['transported', 'treated', 'refused', 'no_patient', 'cancelled', 'deceased'], weights=[78, 9, 4, 3, 5, 1])[0]
            disp = rec + timedelta(minutes=rnd.uniform(.5, 4 if p > 2 else 1.5))
            c = EmergencyCall(reference=f'EMS-{timezone.localtime(rec):%y%m%d}-{rnd.getrandbits(16):04X}', source=src, complaint=key, priority=p,
                              caller_phone=f'+220 {rnd.randint(300, 799)} {rnd.randint(1000, 9999)}', patient_age=rnd.randint(0, 88),
                              patient_sex=rnd.choice('FM'), latitude=lat, longitude=lon, location=town, landmark=rnd.choice(LANDMARKS),
                              ambulance=amb, received_at=rec, verified_at=rec, dispatched_at=disp, en_route_at=disp + timedelta(minutes=1),
                              destination=rnd.choice(facilities) if facilities and rnd.random() < .25 else None, taken_by=users['dispatch.sanneh'],
                              dispatched_by=users['dispatch.sanneh'])
            if outcome == 'cancelled':
                c.status, c.outcome, c.closed_at, c.cancel_reason = 'cancelled', 'cancelled', disp + timedelta(minutes=rnd.uniform(2, 10)), 'Family took the patient by taxi'
                c.en_route_at = None
            else:
                c.on_scene_at = rec + timedelta(minutes=resp)
                c.status, c.outcome = 'closed', outcome
                if outcome == 'transported':
                    c.transporting_at = c.on_scene_at + timedelta(minutes=rnd.uniform(8, 25))
                    c.at_hospital_at = c.transporting_at + timedelta(minutes=rnd.uniform(8, 35))
                    c.closed_at = c.at_hospital_at + timedelta(minutes=rnd.uniform(8, 20))
                else:
                    c.closed_at = c.on_scene_at + timedelta(minutes=rnd.uniform(10, 30))
            calls.append(c)
    EmergencyCall.objects.bulk_create(calls, batch_size=200)
    for c in EmergencyCall.objects.filter(reference__in=[x.reference for x in calls]):
        events.append(CallEvent(call=c, kind='system', text=f'{c.get_priority_display()}: {A.complaint(c.complaint)["label"]}', at=c.received_at))
        events.append(CallEvent(call=c, kind='status', text=f'{c.ambulance.call_sign} assigned', at=c.dispatched_at))
        if c.closed_at:
            events.append(CallEvent(call=c, kind='status', text=f'Closed: {c.get_outcome_display().lower()}' if c.status == 'closed' else 'Cancelled', at=c.closed_at))
    CallEvent.objects.bulk_create(events, batch_size=500)
    return len(calls)
