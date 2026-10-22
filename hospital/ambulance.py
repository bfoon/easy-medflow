"""Ambulance service rules: triage, where the ambulances are, which one to send, where to take the patient, the journey
from call to handover, what the crew should prepare, and the ATMIST handover that opens the emergency visit.

Every page and the phone-app API (hospital/ambulance_api.py) go through these functions, so the rules are the same
whichever screen or device is used.

The triage questions, caller instructions and crew checklists below are ILLUSTRATIVE starting points modelled on common
dispatcher and pre-hospital practice. A medical director must review and adapt them before real use.
"""
import math
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from .models_ambulance import Ambulance, CallEvent, CallObservation, CrewShift, EmergencyCall, EmsStation, PositionPing

# ------------------------------------------------------------------ complaint catalogue
# Each question: (key, text, trigger answer, priority if triggered, short reason)
UNIVERSAL = [
    ('u_awake', 'Is the person awake and able to talk?', 'no', 1, 'Not awake'),
    ('u_breathing', 'Are they breathing normally?', 'no', 1, 'Not breathing normally'),
    ('u_bleeding', 'Is there heavy bleeding that will not stop?', 'yes', 1, 'Heavy bleeding'),
]

COMPLAINTS = [
    {'key': 'arrest', 'label': 'Collapsed, not breathing', 'icon': 'bi-heartbreak', 'base': 1, 'level': 'als', 'universal': False,
     'questions': [('a_witnessed', 'Did someone see them collapse?', 'yes', 1, 'Witnessed collapse'),
                   ('a_cpr', 'Has anyone started pressing on the chest?', 'no', 1, 'No CPR yet')],
     'first_aid': ['Lie them flat on their back on the floor.', 'Kneel beside them, put the heel of your hand in the centre of the chest, your other hand on top.',
                   'Push down hard and fast, about 2 pushes every second. Count out loud with me: one, two, three, four…',
                   'Do not stop until the ambulance crew takes over. If someone else is there, swap every 2 minutes.',
                   'Send someone to wait outside to wave the ambulance in.'],
     'prep': [('Equipment', ['Defibrillator charged, pads out of the packet', 'Bag-valve-mask and airway kit (i-gel / OPA)', 'Suction unit tested',
                             'Mechanical CPR device or second rescuer plan']),
              ('Medicines', ['Adrenaline 1 mg/10 mL drawn up', 'Amiodarone 300 mg ready', 'IV/IO access kit and saline']),
              ('On scene', ['Lead paramedic on chest, second on airway; driver brings the defibrillator', 'Start a 2-minute CPR cycle timer'])],
     'alert': 'Resuscitation room: cardiac arrest, CPR in progress.', 'match': ['ICU', 'Cath lab', 'Emergency']},
    {'key': 'chest_pain', 'label': 'Chest pain', 'icon': 'bi-heart-pulse', 'base': 2, 'level': 'als',
     'questions': [('c_spread', 'Is the pain crushing, or spreading to the arm, jaw or back?', 'yes', 1, 'Crushing / spreading pain'),
                   ('c_sweaty', 'Are they pale, sweaty or feeling faint?', 'yes', 1, 'Pale and sweaty'),
                   ('c_history', 'Have they had heart problems before?', 'yes', 2, 'Known heart disease')],
     'first_aid': ['Help them sit down, leaning back against a wall, knees bent.', 'Loosen tight clothing and keep them calm and still.',
                   'If they are not allergic and a doctor has not said no, they can chew one aspirin (300 mg).',
                   'If they become unresponsive and stop breathing normally, tell me straight away.'],
     'prep': [('Equipment', ['12-lead ECG with electrodes', 'Defibrillator with pads ready', 'Oxygen (give only if SpO₂ under 94%)']),
              ('Medicines', ['Aspirin 300 mg chewable (check allergy and bleeding)', 'GTN spray (only if systolic over 90)', 'Morphine for severe pain, with antiemetic']),
              ('On scene', ['12-lead ECG within 10 minutes of arrival', 'Send the ECG ahead if it shows ST elevation'])],
     'alert': 'Emergency: possible heart attack. ECG and troponin on arrival.', 'match': ['Cath lab', 'Cardiac', 'ICU']},
    {'key': 'breathing', 'label': 'Difficulty breathing', 'icon': 'bi-lungs', 'base': 2, 'level': 'als',
     'questions': [('b_words', 'Can they say a full sentence without stopping for breath?', 'no', 1, 'Cannot finish sentences'),
                   ('b_blue', 'Are their lips or face blue or grey?', 'yes', 1, 'Blue lips'),
                   ('b_asthma', 'Do they have asthma and is their inhaler not helping?', 'yes', 2, 'Inhaler not helping')],
     'first_aid': ['Sit them upright, leaning slightly forward. Do not let them lie flat.', 'If they have an inhaler, help them use it: one puff every 30–60 seconds, up to 10 puffs.',
                   'Open windows and keep people back to give them air.'],
     'prep': [('Equipment', ['Oxygen cylinder full, non-rebreather and nasal cannula', 'Nebuliser mask', 'Pulse oximeter and capnography', 'CPAP if carried']),
              ('Medicines', ['Salbutamol 5 mg nebules', 'Ipratropium 500 mcg', 'Hydrocortisone 200 mg IV', 'Adrenaline 1:1000 IM if anaphylaxis'])],
     'alert': 'Emergency: severe breathing difficulty.', 'match': ['ICU', 'Emergency']},
    {'key': 'stroke', 'label': 'Stroke signs (face, arm, speech)', 'icon': 'bi-person-exclamation', 'base': 2, 'level': 'als',
     'questions': [('s_fast', 'Is the face drooping, an arm weak, or speech slurred?', 'yes', 2, 'FAST positive'),
                   ('s_onset', 'Did it start within the last 4½ hours?', 'yes', 1, 'Within the treatment window'),
                   ('s_sugar', 'Do they have diabetes?', 'yes', 2, 'Diabetic: check sugar')],
     'first_aid': ['Note the exact time the symptoms started, or when they were last seen well.', 'Do not give them anything to eat or drink.',
                   'If they are drowsy, lay them on their side.'],
     'prep': [('Equipment', ['Glucometer', 'FAST / BE-FAST card', 'Suction']),
              ('On scene', ['Record the time last seen well', 'Check blood glucose before anything else', 'Keep scene time under 15 minutes']),
              ('Medicines', ['Glucose 10% if sugar under 4 mmol/L'])],
     'alert': 'Emergency: suspected stroke inside treatment window. CT on arrival.', 'match': ['CT', 'MRI', 'Neurology', 'Stroke']},
    {'key': 'rta', 'label': 'Road traffic crash', 'icon': 'bi-car-front', 'base': 2, 'level': 'als',
     'questions': [('r_trapped', 'Is anyone trapped in a vehicle?', 'yes', 1, 'Trapped'),
                   ('r_pedestrian', 'Was a pedestrian or motorbike rider hit?', 'yes', 1, 'Pedestrian / motorbike'),
                   ('r_fire', 'Is there fire, smoke or leaking fuel?', 'yes', 1, 'Fire / fuel risk'),
                   ('r_walking', 'Is everyone walking and talking?', 'yes', 3, 'All walking')],
     'first_aid': ['Stay safe: do not stand in the road. Ask someone to stop the traffic.', 'Do not move anyone who may have a neck or back injury unless there is fire.',
                   'Press firmly on any bleeding with a clean cloth and keep pressing.', 'Tell me how many people are hurt.'],
     'prep': [('Equipment', ['Scoop stretcher, long board and head blocks', 'Cervical collars, all sizes', 'Pelvic binder', 'Tourniquets and haemostatic dressings',
                             'Splints and traction splint', 'High-visibility jackets and scene cones']),
              ('Medicines', ['Tranexamic acid 1 g', 'Analgesia: morphine / ketamine per protocol', 'Warm IV fluids']),
              ('On scene', ['Park to protect the scene, lights on', 'Triage everyone if more than one patient (red / yellow / green)'])],
     'alert': 'Trauma team: road traffic crash.', 'match': ['Theatre', 'Orthopaedic', 'Trauma', 'ICU']},
    {'key': 'labour', 'label': 'Labour & childbirth', 'icon': 'bi-gender-female', 'base': 3, 'level': 'neonatal',
     'questions': [('l_bleeding', 'Is she bleeding heavily?', 'yes', 1, 'Heavy bleeding in pregnancy'),
                   ('l_head', 'Can you see the baby’s head, or the cord?', 'yes', 1, 'Birth imminent / cord seen'),
                   ('l_fits', 'Has she had a fit, a severe headache or blurred vision?', 'yes', 1, 'Possible eclampsia'),
                   ('l_early', 'Is she less than 37 weeks pregnant?', 'yes', 2, 'Preterm labour')],
     'first_aid': ['Help her lie on her left side or in the position she prefers.', 'Get clean towels or cloths and a warm wrap for the baby.',
                   'If the baby is born, dry it straight away and lay it skin-to-skin on the mother’s chest. Cover them both.',
                   'Do not pull on the cord. Do not cut the cord.'],
     'prep': [('Equipment', ['Maternity / delivery pack', 'Warm towels and baby wrap, hat', 'Neonatal bag-valve-mask (size 0/1 masks)', 'Cord clamps and sterile scissors',
                             'Neonatal suction']),
              ('Medicines', ['Oxytocin 10 IU IM', 'Misoprostol 600 mcg', 'Magnesium sulphate 4 g if fits']),
              ('On scene', ['Midwife or crew member stays with the mother', 'Note time of birth and Apgar at 1 and 5 minutes'])],
     'alert': 'Labour ward: woman in labour arriving by ambulance.', 'match': ['Obstetric', 'NICU', 'Maternity'], 'department': 'Maternity'},
    {'key': 'seizure', 'label': 'Fits / seizure', 'icon': 'bi-lightning', 'base': 2, 'level': 'bls',
     'questions': [('z_long', 'Has the fit lasted more than 5 minutes, or are there repeated fits?', 'yes', 1, 'Fitting over 5 minutes'),
                   ('z_pregnant', 'Is she pregnant?', 'yes', 1, 'Fits in pregnancy'),
                   ('z_child_fever', 'Is it a child with a fever?', 'yes', 2, 'Febrile child')],
     'first_aid': ['Move hard or sharp things away. Do not hold them down.', 'Do not put anything in their mouth.', 'Note the time the fit started.',
                   'When the jerking stops, roll them onto their side.'],
     'prep': [('Equipment', ['Suction', 'Oxygen and masks (adult and child)', 'Glucometer']),
              ('Medicines', ['Buccal midazolam 10 mg (child by age)', 'Diazepam rectal tubes', 'Glucose 10%', 'Paracetamol for fever'])],
     'alert': 'Emergency: patient with seizures.', 'match': ['Neurology', 'Emergency']},
    {'key': 'unconscious', 'label': 'Unconscious / fainted', 'icon': 'bi-person-fill-down', 'base': 2, 'level': 'als',
     'questions': [('n_wake', 'Can you wake them by shouting and shaking their shoulders?', 'no', 1, 'Cannot be woken'),
                   ('n_diabetic', 'Do they have diabetes?', 'yes', 2, 'Diabetic')],
     'first_aid': ['If they are breathing, roll them onto their side with the head tilted back.', 'Do not give food or drink.',
                   'If they stop breathing, tell me at once and we will start chest compressions.'],
     'prep': [('Equipment', ['Airway kit and suction', 'Glucometer', 'Defibrillator']), ('Medicines', ['Glucose 10% / glucagon 1 mg', 'Naloxone 400 mcg'])],
     'alert': 'Emergency: unconscious patient.', 'match': ['ICU', 'Emergency']},
    {'key': 'bleeding', 'label': 'Severe bleeding / wound', 'icon': 'bi-droplet', 'base': 2, 'level': 'bls',
     'questions': [('w_spurting', 'Is blood spurting or soaking through cloths?', 'yes', 1, 'Spurting bleeding'),
                   ('w_stab', 'Was it a stab or gunshot wound?', 'yes', 1, 'Penetrating injury')],
     'first_aid': ['Press hard on the wound with a clean cloth. Do not lift it to look.', 'If blood soaks through, add more cloth on top and keep pressing.',
                   'Lay them down and raise their legs if they feel faint.'],
     'prep': [('Equipment', ['Tourniquets', 'Haemostatic gauze and pressure dressings', 'Large-bore cannulas']), ('Medicines', ['Tranexamic acid 1 g', 'Warm fluids'])],
     'alert': 'Trauma team: major bleeding.', 'match': ['Theatre', 'Trauma', 'Blood bank']},
    {'key': 'burns', 'label': 'Burns', 'icon': 'bi-fire', 'base': 2, 'level': 'bls',
     'questions': [('x_face', 'Are the face, mouth or neck burnt, or is the voice hoarse?', 'yes', 1, 'Airway burn risk'),
                   ('x_large', 'Is the burn bigger than their whole arm?', 'yes', 1, 'Large burn'),
                   ('x_child', 'Is it a child?', 'yes', 2, 'Child with burns')],
     'first_aid': ['Cool the burn under cool running water for 20 minutes. Not ice.', 'Take off rings, watches and clothing near the burn, unless stuck.',
                   'Cover loosely with clean cling film or a clean plastic bag.', 'Keep the rest of them warm.'],
     'prep': [('Equipment', ['Burns dressings / cling film', 'Sterile water for cooling', 'Airway kit, consider early intubation support']),
              ('Medicines', ['Strong analgesia', 'IV fluids (Parkland estimate)'])],
     'alert': 'Emergency: burns patient.', 'match': ['Burns', 'Plastic', 'ICU']},
    {'key': 'snakebite', 'label': 'Snakebite', 'icon': 'bi-bug', 'base': 2, 'level': 'rural',
     'questions': [('k_swelling', 'Is the swelling spreading up the limb?', 'yes', 1, 'Spreading swelling'),
                   ('k_bleed', 'Are the gums, nose or bite bleeding?', 'yes', 1, 'Bleeding (venom)'),
                   ('k_eyes', 'Are the eyelids drooping or is breathing difficult?', 'yes', 1, 'Neurotoxic signs')],
     'first_aid': ['Keep them still and calm. Carry them if possible; do not let them walk.', 'Take off rings, bracelets and tight clothing on the bitten limb.',
                   'Do not cut, suck or burn the bite. Do not tie a tight tourniquet.', 'Do not try to catch the snake. A photo from a safe distance helps.',
                   'Note the time of the bite.'],
     'prep': [('Equipment', ['Splint for the bitten limb', 'Pen to mark swelling edge with time', 'Airway kit and bag-valve-mask']),
              ('Medicines', ['Adrenaline ready (antivenom reaction risk)', 'Analgesia: paracetamol (no NSAIDs)']),
              ('On scene', ['20-minute whole-blood clotting test if kit carried', 'Ask about snake colour and size'])],
     'alert': 'Emergency: snakebite. Check antivenom stock now.', 'match': ['Antivenom', 'ICU', 'Emergency']},
    {'key': 'poisoning', 'label': 'Poisoning / overdose', 'icon': 'bi-capsule', 'base': 2, 'level': 'als',
     'questions': [('p_pesticide', 'Was it a pesticide, weed-killer or chemical?', 'yes', 1, 'Pesticide / chemical'),
                   ('p_drowsy', 'Are they very drowsy or confused?', 'yes', 1, 'Drowsy after poisoning')],
     'first_aid': ['Do not make them vomit.', 'Keep the container, tablets or packet to give to the crew.', 'If the chemical is on skin or clothes, remove clothes and wash the skin with water.'],
     'prep': [('Equipment', ['Gloves, apron and eye protection (pesticides)', 'Suction', 'Bag for contaminated clothing']),
              ('Medicines', ['Atropine (organophosphate)', 'Naloxone', 'Activated charcoal if within 1 hour and awake'])],
     'alert': 'Emergency: poisoning. Decontamination area may be needed.', 'match': ['ICU', 'Emergency']},
    {'key': 'drowning', 'label': 'Drowning', 'icon': 'bi-water', 'base': 1, 'level': 'als',
     'questions': [('d_out', 'Are they out of the water now?', 'no', 1, 'Still in water')],
     'first_aid': ['Do not go into the water yourself unless trained. Throw something that floats.', 'Once out, if not breathing, give 5 rescue breaths and then start chest compressions.',
                   'Keep them warm.'],
     'prep': [('Equipment', ['Defibrillator', 'Suction', 'Blankets / foil blanket', 'Throw line']), ('On scene', ['Expect hypothermia and vomiting'])],
     'alert': 'Resuscitation room: drowning.', 'match': ['ICU', 'Emergency']},
    {'key': 'fall', 'label': 'Fall / injury', 'icon': 'bi-person-wheelchair', 'base': 3, 'level': 'bls',
     'questions': [('f_head', 'Did they hit their head and are now confused or vomiting?', 'yes', 2, 'Head injury'),
                   ('f_neck', 'Is there neck pain, or can they not move their legs?', 'yes', 2, 'Possible spinal injury'),
                   ('f_height', 'Did they fall from higher than a standing height (tree, roof, stairs)?', 'yes', 2, 'Fall from height')],
     'first_aid': ['Do not move them if there is neck or back pain.', 'Keep them warm and still.', 'Support any injured limb in the position you found it.'],
     'prep': [('Equipment', ['Scoop stretcher and head blocks', 'Splints and slings', 'Vacuum mattress']), ('Medicines', ['Analgesia: paracetamol, morphine, Entonox'])],
     'alert': 'Emergency: injured patient.', 'match': ['Orthopaedic', 'X-ray', 'Theatre']},
    {'key': 'sick_child', 'label': 'Very sick child / fever', 'icon': 'bi-balloon', 'base': 3, 'level': 'bls',
     'questions': [('h_floppy', 'Is the child floppy, very sleepy or hard to wake?', 'yes', 1, 'Floppy / drowsy child'),
                   ('h_drink', 'Has the child stopped drinking or breastfeeding?', 'yes', 2, 'Not drinking'),
                   ('h_rash', 'Is there a rash that does not fade when pressed with a glass?', 'yes', 1, 'Non-blanching rash')],
     'first_aid': ['Keep the child lightly dressed; do not wrap them up.', 'Offer small sips of water or breastfeed if awake.',
                   'If the child fits, lay them on their side and time it.'],
     'prep': [('Equipment', ['Paediatric bag: child bag-valve-mask, masks, cannulas', 'Weight-by-age tape', 'Malaria rapid test if carried', 'Glucometer']),
              ('Medicines', ['Paracetamol by weight', 'Artesunate if severe malaria protocol', 'Glucose 10% (2 mL/kg)'])],
     'alert': 'Paediatrics: sick child arriving.', 'match': ['Paediatric', 'NICU'], 'department': 'Pediatrics'},
    {'key': 'transfer', 'label': 'Inter-facility transfer', 'icon': 'bi-arrow-left-right', 'base': 4, 'level': 'bls', 'universal': False,
     'questions': [('t_ventilated', 'Is the patient on a ventilator or oxygen?', 'yes', 2, 'Needs oxygen / ventilation'),
                   ('t_time', 'Is the receiving team waiting for a time-critical treatment?', 'yes', 2, 'Time-critical transfer')],
     'first_aid': ['Have the transfer letter, latest results and medicines ready to hand over.'],
     'prep': [('Equipment', ['Transfer monitor', 'Enough oxygen for the journey + 30 minutes', 'Syringe drivers charged']),
              ('On scene', ['Collect notes, scans and drug chart', 'Handover from the sending nurse or doctor'])],
     'alert': 'Transfer arriving.', 'match': []},
    {'key': 'other', 'label': 'Something else', 'icon': 'bi-question-circle', 'base': 3, 'level': 'bls',
     'questions': [], 'first_aid': ['Stay with the person and keep them comfortable.', 'Call back at once if they get worse.'],
     'prep': [], 'alert': 'Emergency: patient arriving by ambulance.', 'match': []},
]
BY_KEY = {c['key']: c for c in COMPLAINTS}
GENERAL_PREP = [('Every call', ['Gloves, masks and eye protection on', 'Read the landmark and call the caller if the address is unclear',
                                'Stretcher and carry chair ready to unload'])]

PRIORITY_COLOR = {1: '#C8323F', 2: '#D2593A', 3: '#E0912A', 4: '#0F7B78'}
PRIORITY_WORD = {1: 'Immediate', 2: 'Emergency', 3: 'Urgent', 4: 'Routine'}
# Response targets used for the board and insights (minutes from call to crew on scene)
TARGET_MIN = {1: 15, 2: 25, 3: 60, 4: 120}
STATUS_COLOR = {'available': '#0F7B78', 'dispatched': '#4A5FC1', 'en_route': '#4A5FC1', 'on_scene': '#C8323F', 'transporting': '#8A4A8F',
                'at_hospital': '#8A4A8F', 'returning': '#3E8E9C', 'off_duty': '#9AAAB5', 'maintenance': '#5A6F7D'}
LEVEL_ICON = {'als': 'bi-truck-front', 'bls': 'bi-truck-front', 'neonatal': 'bi-truck-front', 'rural': 'bi-truck', 'moto': 'bi-bicycle', 'boat': 'bi-water'}
JOURNEY = [('received_at', 'Call'), ('dispatched_at', 'Assigned'), ('en_route_at', 'On the way'), ('on_scene_at', 'With patient'),
           ('transporting_at', 'To hospital'), ('at_hospital_at', 'At hospital'), ('closed_at', 'Closed')]

READINESS = [('oxygen', 'Oxygen cylinders full and spare on board'), ('defib', 'Defibrillator charged, pads in date'), ('suction', 'Suction working'),
             ('drugs', 'Drug bag sealed and in date'), ('stretcher', 'Stretcher and carry chair working'), ('radio', 'Radio and crew phone charged'),
             ('lights', 'Lights and siren tested'), ('tyres', 'Tyres, fuel and oil checked'), ('clean', 'Vehicle cleaned and restocked')]


def complaint(key):
    return BY_KEY.get(key) or BY_KEY['other']


def questions_for(key):
    c = complaint(key)
    return (UNIVERSAL if c.get('universal', True) else []) + c['questions']


def triage(key, answers):
    """Priority from the complaint and the answers given. Returns (priority 1–4, [reasons])."""
    c = complaint(key)
    p, why = c['base'], []
    for qkey, _, trigger, qp, reason in questions_for(key):
        a = str((answers or {}).get(qkey, '')).lower()
        if a and a == trigger:
            if qp < p:
                p = qp
            why.append(reason)
    if key == 'arrest':
        why.insert(0, 'Cardiac arrest')
    return p, why


def catalogue():
    """The complaint list for screens and the phone app."""
    return [{'key': c['key'], 'label': c['label'], 'icon': c['icon'], 'base_priority': c['base'],
             'questions': [{'key': q[0], 'text': q[1]} for q in questions_for(c['key'])], 'first_aid': c['first_aid']} for c in COMPLAINTS]


# ------------------------------------------------------------------ geography
ROAD_FACTOR = 1.35          # roads are longer than a straight line
GREATER_BANJUL_EAST = -16.45  # east of this the roads are open highway


def home():
    """This hospital: where patients come by default."""
    return {'id': None, 'name': getattr(settings, 'HOSPITAL_NAME', 'This hospital'), 'lat': getattr(settings, 'EMS_HOSPITAL_LAT', 13.4440),
            'lon': getattr(settings, 'EMS_HOSPITAL_LON', -16.6790),
            'capabilities': [c.strip() for c in getattr(settings, 'EMS_HOSPITAL_CAPABILITIES', 'Emergency, ICU, Theatre, Maternity, Paediatric, X-ray, CT').split(',') if c.strip()]}


def km(lat1, lon1, lat2, lon2):
    """Great-circle distance in kilometres."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1, math.sqrt(a)))


def bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


COMPASS = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west']


def compass(deg):
    return COMPASS[int((deg + 22.5) // 45) % 8]


def speed_kmh(amb_level, priority, lon=None):
    if amb_level == 'boat':
        return 20
    if amb_level == 'moto':
        return 48
    base = 50 if priority <= 2 else 40
    if lon is not None and lon > GREATER_BANJUL_EAST:
        base += 20          # open road up-country
    return base


def amb_position(a):
    if a.latitude is not None and a.longitude is not None:
        return a.latitude, a.longitude
    if a.station_id:
        return a.station.latitude, a.station.longitude
    h = home()
    return h['lat'], h['lon']


def eta_minutes(a, lat, lon, priority=2):
    """Minutes for this ambulance to reach a point: turnout time + road distance at a realistic speed."""
    alat, alon = amb_position(a)
    d = km(alat, alon, lat, lon)
    if d is None:
        return None, None
    road = d * (1.0 if a.level == 'boat' else ROAD_FACTOR)
    turnout = 1.5 if a.status == 'available' else 0.5
    mins = turnout + road / speed_kmh(a.level, priority, (alon + lon) / 2) * 60
    return round(mins, 1), round(road, 1)


# ------------------------------------------------------------------ which ambulance to send
def recommend(call, limit=6):
    """Free ambulances ranked for this call, with the reasons a dispatcher can read at a glance."""
    if not call.has_position:
        return []
    c = complaint(call.complaint)
    out = []
    for a in Ambulance.objects.filter(active=True, status__in=['available', 'returning']).select_related('station').prefetch_related('shifts__user'):
        if a.level == 'boat':
            sp = (a.station.latitude, a.station.longitude) if a.station_id else amb_position(a)
            if km(sp[0], sp[1], call.latitude, call.longitude) > 15:
                continue              # a river ambulance only serves riverside villages near its jetty
        eta, road = eta_minutes(a, call.latitude, call.longitude, call.priority)
        score, reasons, warn = eta, [], []
        if c['level'] == 'als' and a.level == 'als':
            reasons.append('Advanced life support crew')
        elif c['level'] == 'als' and a.level in ('bls', 'rural'):
            score += 5
            warn.append('Basic crew for an ALS call')
        if c['level'] == 'neonatal':
            if a.level == 'neonatal':
                reasons.append('Mother & newborn kit')
                score -= 3
            else:
                score += 3
        if c['level'] == 'rural' and a.level == 'rural':
            reasons.append('4×4 for rough roads')
            score -= 2
        if a.level == 'moto':
            if call.priority == 1:
                reasons.append('Fast first response')
                warn.append('Cannot carry a patient: send an ambulance too')
            else:
                score += 60          # only a first responder: never the best choice when the patient must be carried
                warn.append('Motorbike: cannot carry a patient')
        if a.fuel_pct < 25:
            score += 4
            warn.append(f'Fuel {a.fuel_pct}%')
        if c['key'] in ('breathing', 'arrest', 'drowning') and a.oxygen_pct < 40:
            score += 4
            warn.append(f'Oxygen {a.oxygen_pct}%')
        crew = a.crew
        if not crew:
            score += 15
            warn.append('No crew signed on')
        if a.status == 'returning':
            reasons.append('Already on the road')
        out.append({'a': a, 'eta': eta, 'km': road, 'score': score, 'reasons': reasons, 'warn': warn, 'crew': crew})
    out.sort(key=lambda r: (not r['a'].can_transport, r['score']))     # first responders are listed after ambulances
    if out and out[0]['a'].can_transport:
        out[0]['best'] = True
        if out[0]['eta'] == min(r['eta'] for r in out if r['a'].can_transport):
            out[0]['reasons'].insert(0, 'Closest')
    return out[:limit]


# ------------------------------------------------------------------ where to take the patient
def destinations(call):
    """Places that take ambulance patients, best first: those with the right service, then the nearest."""
    from .models import NetworkFacility
    c = complaint(call.complaint)
    want = [w.lower() for w in c.get('match', [])]

    def rank(caps):
        """0 = has the most specific service for this complaint (listed first), 99 = none of them."""
        return min((i for i, w in enumerate(want) if any(w in cap.lower() for cap in caps)), default=99)
    h = home()
    lat, lon = (call.latitude, call.longitude) if call.has_position else (h['lat'], h['lon'])
    opts = [{'id': None, 'name': h['name'], 'km': km(lat, lon, h['lat'], h['lon']), 'lat': h['lat'], 'lon': h['lon'],
             'rank': rank(h['capabilities']) if want else 0, 'home': True}]
    for f in NetworkFacility.objects.filter(receives_ambulances=True, latitude__isnull=False, longitude__isnull=False):
        caps = f.capability_list
        opts.append({'id': f.pk, 'name': f.name, 'km': km(lat, lon, f.latitude, f.longitude), 'lat': f.latitude, 'lon': f.longitude,
                     'rank': rank(caps) if want else 99, 'home': False})
    for o in opts:
        o['km'] = round(o['km'] * ROAD_FACTOR, 1) if o['km'] is not None else None
        o['match'] = o['rank'] < 99
    # the most specific service within reach (60 km by road) wins; then the nearest. This hospital wins ties.
    opts.sort(key=lambda o: (o['rank'] if (o['km'] or 0) <= 60 else 99, o['km'] or 0, not o['home']))
    return opts


def destination_point(call):
    if call.destination_id and call.destination.latitude is not None:
        return {'name': call.destination.name, 'lat': call.destination.latitude, 'lon': call.destination.longitude, 'home': False}
    h = home()
    return {'name': h['name'], 'lat': h['lat'], 'lon': h['lon'], 'home': True}


def target_of(a, call=None):
    """Where this ambulance is heading now (scene, hospital or its station)."""
    call = call or a.current_call
    if call and a.status in ('dispatched', 'en_route') and call.has_position:
        return {'lat': call.latitude, 'lon': call.longitude, 'name': call.landmark or 'Patient', 'kind': 'scene'}
    if call and a.status in ('transporting', 'at_hospital'):
        d = destination_point(call)
        return {'lat': d['lat'], 'lon': d['lon'], 'name': d['name'], 'kind': 'hospital'}
    if a.status == 'returning' and a.station_id:
        return {'lat': a.station.latitude, 'lon': a.station.longitude, 'name': a.station.name, 'kind': 'station'}
    return None


# ------------------------------------------------------------------ the journey
FLOW = {'new': ['waiting', 'dispatched', 'cancelled'], 'waiting': ['dispatched', 'cancelled'], 'dispatched': ['en_route', 'cancelled'],
        'en_route': ['on_scene', 'cancelled'], 'on_scene': ['transporting', 'closed'], 'transporting': ['at_hospital'], 'at_hospital': ['closed']}
STAMP = {'dispatched': 'dispatched_at', 'en_route': 'en_route_at', 'on_scene': 'on_scene_at', 'transporting': 'transporting_at',
         'at_hospital': 'at_hospital_at', 'closed': 'closed_at', 'cancelled': 'closed_at', 'waiting': 'verified_at'}
CREW_NEXT = {'dispatched': ('en_route', 'Start driving', 'bi-sign-turn-right'), 'en_route': ('on_scene', 'Arrived on scene', 'bi-geo-alt-fill'),
             'on_scene': ('transporting', 'Patient on board, leave scene', 'bi-hospital'), 'transporting': ('at_hospital', 'Arrived at hospital', 'bi-building-check')}


class Refused(ValueError):
    pass


def log(call, text, kind='status', by=None, at=None):
    return CallEvent.objects.create(call=call, kind=kind, text=text[:400], by=by if getattr(by, 'pk', None) else None, at=at or timezone.now())


def _who(user):
    if not getattr(user, 'pk', None):
        return 'System'
    return user.get_full_name() or user.get_username()


@transaction.atomic
def create_call(data, by=None, source='phone'):
    """A new emergency call from the service desk or the phone app. ``data`` is a plain dict (form or JSON)."""
    from .models import Location, Patient
    key = data.get('complaint') if data.get('complaint') in BY_KEY else 'other'
    answers = {k: str(v).lower() for k, v in (data.get('answers') or {}).items() if str(v).lower() in ('yes', 'no')}
    p, why = triage(key, answers)
    if data.get('priority') and str(data['priority']).isdigit() and 1 <= int(data['priority']) <= 4 and by is not None:
        manual = int(data['priority'])
        if manual != p:
            why.append(f'Priority set to P{manual} by the call taker')
            p = manual
    lat, lon = _float(data.get('latitude')), _float(data.get('longitude'))
    loc = None
    if data.get('location'):
        loc = Location.objects.filter(pk=data['location']).first() if str(data['location']).isdigit() else None
        if loc and (lat is None or lon is None):
            lat, lon = float(loc.latitude), float(loc.longitude)
    if lat is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise Refused('That map position is not valid.')
    patient = None
    if data.get('patient') and str(data['patient']).isdigit():
        patient = Patient.objects.filter(pk=data['patient'], deceased_at__isnull=True).first()
    age = data.get('patient_age')
    call = EmergencyCall(
        source=source if source in dict(EmergencyCall.SOURCE) else 'phone', caller_name=str(data.get('caller_name', ''))[:120].strip(),
        caller_phone=str(data.get('caller_phone', ''))[:40].strip(), caller_relation=str(data.get('caller_relation', ''))[:60].strip(),
        patient=patient, patient_name=(patient.full_name if patient else str(data.get('patient_name', ''))[:160].strip()),
        patient_age=(patient.age if patient else (int(age) if str(age or '').isdigit() and int(age) < 130 else None)),
        patient_sex=(patient.sex if patient and patient.sex in ('F', 'M') else data.get('patient_sex') if data.get('patient_sex') in ('F', 'M') else 'X'),
        patients_count=max(1, min(99, int(data.get('patients_count') or 1))) if str(data.get('patients_count') or '1').isdigit() else 1,
        complaint=key, answers=answers, priority=p, priority_reason='; '.join(why)[:200], description=str(data.get('description', ''))[:2000].strip(),
        landmark=str(data.get('landmark', ''))[:200].strip(), location=loc, latitude=lat, longitude=lon,
        accuracy_m=int(data['accuracy_m']) if str(data.get('accuracy_m') or '').isdigit() else None,
        status='new' if source == 'app' else 'waiting', taken_by=by if getattr(by, 'pk', None) else None)
    if not call.caller_phone and source == 'app':
        raise Refused('A phone number is needed so the service desk can call back.')
    if call.status == 'waiting':
        call.verified_at = call.received_at
    call.save()
    via = dict(EmergencyCall.SOURCE)[call.source].lower()
    log(call, f'{call.get_priority_display()}: {complaint(key)["label"]} ({via})' + (f' · {call.priority_reason}' if call.priority_reason else ''), 'system', by)
    if source == 'app':
        _notify_desk(call)
    return call


def _float(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _notify_desk(call):
    from .models import StaffProfile
    from .notify import notify
    from django.urls import reverse
    users = [s.user for s in StaffProfile.objects.filter(role__in=['dispatcher', 'admin'], active=True).select_related('user')]
    notify(users, f'App request {call.reference}: {complaint(call.complaint)["label"]} (P{call.priority})',
           'Call the person back to confirm, then send an ambulance.', reverse('ems_call', args=[call.pk]), kind='ambulance')


def verify(call, by, note=''):
    if call.status != 'new':
        raise Refused('Only app requests waiting for a call-back need confirming.')
    call.status, call.verified_at = 'waiting', timezone.now()
    call.save(update_fields=['status', 'verified_at', 'updated_at'])
    log(call, f'Confirmed by call-back ({_who(by)})' + (f': {note}' if note else ''), 'status', by)
    return call


@transaction.atomic
def dispatch(call, amb, by, destination=None):
    """Send an ambulance. ``destination`` is a NetworkFacility, or None for this hospital."""
    call = EmergencyCall.objects.select_for_update().get(pk=call.pk)
    amb = Ambulance.objects.select_for_update().get(pk=amb.pk)
    if call.status not in ('new', 'waiting'):
        raise Refused(f'This call is already {call.get_status_display().lower()}.')
    if not amb.is_free:
        raise Refused(f'{amb.call_sign} is {amb.get_status_display().lower()}.')
    if not call.has_position:
        raise Refused('Put the patient on the map first, so the crew can find them.')
    now = timezone.now()
    eta, road = eta_minutes(amb, call.latitude, call.longitude, call.priority)
    if call.status == 'new':
        call.verified_at = now
        log(call, 'Sent without a call-back (dispatcher decision)', 'system', by)
    call.ambulance, call.status, call.dispatched_at, call.dispatched_by = amb, 'dispatched', now, by if getattr(by, 'pk', None) else None
    call.eta_scene_at = now + timedelta(minutes=eta or 10)
    if destination is not False:
        call.destination = destination
    call.save()
    amb.status = 'dispatched'
    if amb.latitude is None:
        amb.latitude, amb.longitude = amb_position(amb)
    amb.save(update_fields=['status', 'latitude', 'longitude', 'updated_at'])
    log(call, f'{amb.call_sign} assigned · about {round(eta or 0)} min, {road} km', 'status', by)
    _tell_crew(call, amb)
    return call


def _tell_crew(call, amb):
    from .notify import notify
    from django.urls import reverse
    users = [s.user for s in amb.shifts.filter(ended_at__isnull=True).select_related('user')]
    notify(users, f'{amb.call_sign}: P{call.priority} {complaint(call.complaint)["label"]}', call.landmark or 'Open the crew screen for directions.',
           reverse('ems_crew'), kind='ambulance')


@transaction.atomic
def advance(call, to, by, outcome='', note='', at=None):
    """Move the call (and its ambulance) to the next step of the journey."""
    # PostgreSQL refuses FOR UPDATE on the nullable side of an outer join (ambulance and
    # destination are optional), so lock only the call row here...
    call = EmergencyCall.objects.select_for_update(of=('self',)).select_related('ambulance', 'destination').get(pk=call.pk)
    # ...and lock the ambulance on its own, in the same order as dispatch() (call, then ambulance).
    if call.ambulance_id:
        call.ambulance = Ambulance.objects.select_for_update().get(pk=call.ambulance_id)
    if to not in FLOW.get(call.status, []):
        raise Refused(f'A call that is “{call.get_status_display().lower()}” cannot move to “{dict(EmergencyCall.STATUS).get(to, to).lower()}”.')
    if to == 'dispatched':
        raise Refused('Use “Send” to assign an ambulance.')
    now = at or timezone.now()
    amb = call.ambulance
    if to == 'closed':
        if call.status == 'on_scene':
            if outcome not in ('treated', 'refused', 'deceased', 'no_patient'):
                raise Refused('Say how the call ended: treated on scene, refused transport, died, or no patient found.')
        else:
            outcome = 'transported'
        call.outcome = outcome
    if to == 'cancelled':
        call.outcome, call.cancel_reason = 'cancelled', note[:200]
    setattr(call, STAMP[to], now)
    call.status = to
    if to == 'transporting':
        d = destination_point(call)
        if amb:
            eta, _ = eta_minutes(amb, d['lat'], d['lon'], call.priority)
            call.eta_hospital_at = now + timedelta(minutes=eta or 15)
    if to == 'on_scene':
        call.eta_scene_at = now
    call.save()
    label = dict(EmergencyCall.STATUS)[to]
    if to == 'closed':
        label = f'Closed: {call.get_outcome_display().lower()}'
    log(call, label + (f' · {note}' if note else ''), 'status', by, at=now)
    if amb:
        amb.status = {'cancelled': 'returning', 'closed': 'returning'}.get(to, to)
        amb.save(update_fields=['status', 'updated_at'])
    if to == 'transporting' and destination_point(call)['home']:
        _pre_alert(call)
    return call


def _pre_alert(call):
    """Tell the receiving team at this hospital what is coming, so they can prepare."""
    from .models import StaffProfile
    from .notify import notify
    from django.urls import reverse
    c = complaint(call.complaint)
    dept = c.get('department', 'Emergency')
    clinical = StaffProfile.objects.filter(active=True, role__in=['doctor', 'nurse']).select_related('user')
    users = ([s.user for s in clinical.filter(Q(department__name=dept) | Q(department__name='Emergency'))]
             or [s.user for s in clinical] or [s.user for s in StaffProfile.objects.filter(role='admin', active=True).select_related('user')])
    mins = max(1, round((call.eta_hospital_at - timezone.now()).total_seconds() / 60)) if call.eta_hospital_at else None
    notify(users, f'Ambulance in {mins} min: P{call.priority} {c["label"]}' if mins else f'Ambulance coming: P{call.priority} {c["label"]}',
           c['alert'], reverse('ems_call', args=[call.pk]), kind='ambulance')
    log(call, f'Pre-alert sent to {dept if dept != "Emergency" else "the emergency team"}', 'system')


def cancel(call, by, reason):
    if not reason.strip():
        raise Refused('Give a reason for cancelling.')
    return advance(call, 'cancelled', by, note=reason.strip())


def back_in_service(amb, by=None):
    if amb.is_busy:
        raise Refused(f'{amb.call_sign} still has a patient. Close the call first.')
    amb.status = 'available'
    amb.save(update_fields=['status', 'updated_at'])
    return amb


def set_unit_status(amb, status, by=None):
    """Off duty / out of service / available, from the fleet page."""
    if status not in ('available', 'off_duty', 'maintenance'):
        raise Refused('Choose available, off duty or out of service.')
    if amb.is_busy:
        raise Refused(f'{amb.call_sign} is on a call.')
    amb.status = status
    amb.save(update_fields=['status', 'updated_at'])
    return amb


def record_position(amb, lat, lon, speed=None, heading=None, accuracy=None, at=None):
    """A GPS fix from the crew phone. Keeps the ETA live and starts the drive automatically when the wheels turn."""
    lat, lon = _float(lat), _float(lon)
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise Refused('Latitude and longitude are needed.')
    now = at or timezone.now()
    prev = (amb.latitude, amb.longitude)
    if heading is None and prev[0] is not None and km(prev[0], prev[1], lat, lon) > 0.01:
        heading = bearing(prev[0], prev[1], lat, lon)
    amb.latitude, amb.longitude, amb.position_at = lat, lon, now
    amb.speed_kmh = max(0.0, _float(speed) or 0.0)
    if heading is not None:
        amb.heading = _float(heading) or 0.0
    amb.save(update_fields=['latitude', 'longitude', 'position_at', 'speed_kmh', 'heading', 'updated_at'])
    call = amb.current_call
    PositionPing.objects.create(ambulance=amb, call=call, latitude=lat, longitude=lon, speed_kmh=amb.speed_kmh, heading=amb.heading,
                                accuracy_m=int(accuracy) if str(accuracy or '').split('.')[0].isdigit() else None, at=now)
    if call:
        if call.status == 'dispatched' and amb.speed_kmh >= 10:
            advance(call, 'en_route', None, note='moving (GPS)', at=now)
            call.refresh_from_db()
        t = target_of(amb, call)
        if t and call.status in ('en_route', 'transporting'):
            eta, _ = eta_minutes(amb, t['lat'], t['lon'], call.priority)
            field = 'eta_scene_at' if call.status == 'en_route' else 'eta_hospital_at'
            setattr(call, field, now + timedelta(minutes=eta or 0))
            call.save(update_fields=[field, 'updated_at'])
    return amb


def record_observation(call, data, by=None):
    def num(k, lo, hi, dec=False):
        v = _float(data.get(k))
        if v is None:
            return None
        if not lo <= v <= hi:
            raise Refused(f'{k.replace("_", " ")} {v:g} is outside the possible range ({lo}–{hi}).')
        return round(v, 1) if dec else int(round(v))
    o = CallObservation(call=call, by=by if getattr(by, 'pk', None) else None, heart_rate=num('heart_rate', 0, 300), systolic=num('systolic', 0, 300),
                        diastolic=num('diastolic', 0, 200), resp_rate=num('resp_rate', 0, 80), spo2=num('spo2', 0, 100),
                        temperature_c=num('temperature_c', 25, 45, True), glucose_mmol=num('glucose_mmol', 0, 60, True), gcs=num('gcs', 3, 15),
                        pain=num('pain', 0, 10), avpu=data.get('avpu') if data.get('avpu') in ('A', 'V', 'P', 'U') else '')
    if not any([o.heart_rate, o.systolic, o.resp_rate, o.spo2, o.temperature_c, o.glucose_mmol, o.gcs, o.avpu, o.pain is not None]):
        raise Refused('Enter at least one measurement.')
    o.save()
    return o


def obs_flags(o):
    """Simple red/amber flags for a set of vital signs (shown to the crew and the hospital)."""
    f = []
    if o.heart_rate is not None and (o.heart_rate < 40 or o.heart_rate > 130):
        f.append(('red', f'HR {o.heart_rate}'))
    elif o.heart_rate is not None and (o.heart_rate < 50 or o.heart_rate > 110):
        f.append(('amber', f'HR {o.heart_rate}'))
    if o.systolic is not None and o.systolic < 90:
        f.append(('red', f'BP {o.systolic}'))
    if o.spo2 is not None and o.spo2 < 92:
        f.append(('red', f'SpO₂ {o.spo2}%'))
    if o.resp_rate is not None and (o.resp_rate < 9 or o.resp_rate > 24):
        f.append(('red' if o.resp_rate > 29 or o.resp_rate < 9 else 'amber', f'RR {o.resp_rate}'))
    if o.gcs is not None and o.gcs < 13:
        f.append(('red', f'GCS {o.gcs}'))
    if o.avpu and o.avpu != 'A':
        f.append(('red', f'AVPU {o.avpu}'))
    if o.glucose_mmol is not None and float(o.glucose_mmol) < 4:
        f.append(('red', f'Glucose {o.glucose_mmol}'))
    if o.temperature_c is not None and float(o.temperature_c) >= 39:
        f.append(('amber', f'Temp {o.temperature_c}'))
    return f


def obs_line(o):
    parts = []
    if o.heart_rate is not None:
        parts.append(f'HR {o.heart_rate}')
    if o.systolic is not None:
        parts.append(f'BP {o.systolic}/{o.diastolic or "–"}')
    if o.resp_rate is not None:
        parts.append(f'RR {o.resp_rate}')
    if o.spo2 is not None:
        parts.append(f'SpO₂ {o.spo2}%')
    if o.temperature_c is not None:
        parts.append(f'T {o.temperature_c}°C')
    if o.glucose_mmol is not None:
        parts.append(f'BM {o.glucose_mmol}')
    if o.gcs is not None:
        parts.append(f'GCS {o.gcs}')
    if o.avpu:
        parts.append(f'AVPU {o.avpu}')
    if o.pain is not None:
        parts.append(f'pain {o.pain}/10')
    return ', '.join(parts)


# ------------------------------------------------------------------ crew preparation
def _k(group, text):
    return slugify(f'{group}-{text}')[:60]


def prep_for(call):
    """The crew's checklist for this call, with who ticked each item, plus what is known about the patient."""
    c = complaint(call.complaint)
    done = call.prep or {}
    groups = []
    extra = []
    if call.patient_age is not None and call.patient_age < 12:
        extra.append('Paediatric bag and weight-by-age tape')
    if call.patients_count > 1:
        extra.append(f'{call.patients_count} patients: triage tags, ask for a second unit early')
    p = call.patient
    if p:
        for a in p.allergies.filter(status='active'):
            extra.append(f'Allergy: {a.substance} ({a.get_severity_display().lower()}) — avoid')
    for title, items in GENERAL_PREP + c['prep'] + ([('This patient', extra)] if extra else []):
        groups.append({'title': title, 'items': [{'key': _k(title, t), 'text': t, 'done': done.get(_k(title, t))} for t in items]})
    total = sum(len(g['items']) for g in groups)
    ticked = sum(1 for g in groups for i in g['items'] if i['done'])
    return {'groups': groups, 'total': total, 'done': ticked, 'pct': round(ticked * 100 / total) if total else 100, 'alert': c['alert'],
            'first_aid': c['first_aid'], 'known': known_patient(p) if p else None}


def known_patient(p):
    """What the hospital already knows that matters on the road. Shown only for the call's patient."""
    from .models import PrescriptionItem
    since = timezone.now() - timedelta(days=90)
    meds = (PrescriptionItem.objects.filter(prescription__encounter__patient=p, prescription__state__in=['signed', 'dispensed'],
                                            prescription__created_at__gte=since)
            .select_related('medication').order_by('-prescription__created_at')[:6])
    last = p.encounters.exclude(vitals={}).order_by('-created_at').first()
    return {'name': p.full_name, 'mrn': p.mrn, 'age': p.age, 'sex': p.get_sex_display(), 'blood_group': p.blood_group,
            'alerts': p.medical_alerts, 'allergies': [f'{a.substance} ({a.get_severity_display().lower()}): {a.reaction}' for a in p.allergies.filter(status='active')],
            'conditions': [c.name for c in p.conditions.filter(status='active')[:8]],
            'medicines': sorted({f'{m.medication.name} {m.dose}'.strip() for m in meds}),
            'last_vitals': last.vitals if last else None, 'emergency_contact': p.emergency_contact}


def toggle_prep(call, key, done, by):
    valid = {i['key'] for g in prep_for(call)['groups'] for i in g['items']}
    if key not in valid:
        raise Refused('That checklist item does not belong to this call.')
    prep = dict(call.prep or {})
    if done:
        prep[key] = {'by': _who(by), 'at': timezone.now().isoformat()}
    else:
        prep.pop(key, None)
    call.prep = prep
    call.save(update_fields=['prep', 'updated_at'])
    return prep


# ------------------------------------------------------------------ handover (ATMIST)
def atmist(call):
    """Age, Time, Mechanism/complaint, Injuries/information, Signs, Treatment: built from what was recorded."""
    c = complaint(call.complaint)
    sex = {'F': 'female', 'M': 'male'}.get(call.patient_sex, '')
    age = f'{call.patient_age} y' if call.patient_age is not None else 'age unknown'
    obs = list(call.observations.all())
    signs = obs_line(obs[-1]) if obs else ''
    if len(obs) > 1:
        signs = f'First: {obs_line(obs[0])}. Latest: {signs}'
    treat = [e.text for e in call.events.all() if e.kind == 'treatment']
    yes = [q[1].rstrip('?') for q in questions_for(call.complaint) if call.answers.get(q[0]) == q[2]]
    saved = call.handover or {}
    auto = {
        'age': f'{age} {sex}'.strip() + (f' · {call.patient_name}' if call.patient_name else ''),
        'time': f'Call {timezone.localtime(call.received_at):%H:%M}' + (f', crew on scene {timezone.localtime(call.on_scene_at):%H:%M}' if call.on_scene_at else ''),
        'mechanism': c['label'] + (f': {call.description}' if call.description else ''),
        'injuries': '; '.join(yes) or call.priority_reason,
        'signs': signs,
        'treatment': '; '.join(treat),
    }
    return {k: saved.get(k) or v for k, v in auto.items()}


ATMIST_LABELS = [('age', 'A', 'Age, sex, name'), ('time', 'T', 'Time of onset / call'), ('mechanism', 'M', 'Mechanism or complaint'),
                 ('injuries', 'I', 'Injuries / information'), ('signs', 'S', 'Signs (vital signs)'), ('treatment', 'T', 'Treatment given')]


@transaction.atomic
def handover(call, data, by, register=True):
    """Hand the patient over at hospital: save the ATMIST, open an emergency visit with a priority queue ticket (this
    hospital only), and close the call."""
    from .models import Department, Encounter, Patient, QueueTicket
    if call.status != 'at_hospital':
        raise Refused('Hand over when the ambulance has arrived at the hospital.')
    call.handover = {k: str(data.get(k, ''))[:600].strip() for k, _, _ in ATMIST_LABELS if str(data.get(k, '')).strip()}
    call.handover.update({'by': _who(by), 'received_by': str(data.get('received_by', ''))[:120].strip()})
    call.save(update_fields=['handover', 'updated_at'])
    enc = None
    if register and destination_point(call)['home']:
        p = call.patient
        if not p:
            first, _, last = (call.patient_name or 'Unknown').partition(' ')
            dob = date(timezone.localdate().year - (call.patient_age if call.patient_age is not None else 40), 1, 1)
            p = Patient.objects.create(first_name=first[:120] or 'Unknown', last_name=(last or 'Patient')[:120], dob=dob,
                                       sex=call.patient_sex if call.patient_sex in ('F', 'M') else 'X',
                                       emergency_contact=f'{call.caller_name} {call.caller_phone}'.strip()[:200],
                                       medical_alerts=f'Arrived by ambulance {call.reference}; age estimated, confirm identity.')
            call.patient = p
        dept = Department.objects.filter(name=complaint(call.complaint).get('department', 'Emergency')).first() or Department.objects.filter(name='Emergency').first()
        a = atmist(call)
        last = call.observations.last()
        vitals = {}
        if last:
            for k in ('heart_rate', 'resp_rate', 'spo2', 'gcs'):
                if getattr(last, k) is not None:
                    vitals[k] = getattr(last, k)
            if last.systolic:
                vitals['bp'] = f'{last.systolic}/{last.diastolic or ""}'.rstrip('/')
            if last.temperature_c is not None:
                vitals['temperature_c'] = float(last.temperature_c)
        enc = Encounter.objects.create(patient=p, department=dept, reason=f'Ambulance {call.reference}: {complaint(call.complaint)["label"]}'[:300],
                                       symptoms='\n'.join(f'{l}: {a[k]}' for k, _, l in ATMIST_LABELS if a.get(k)), vitals=vitals)
        if dept:
            QueueTicket.objects.create(patient=p, encounter=enc, department=dept, priority=min(call.priority, 4), counter='Ambulance bay')
        call.encounter = enc
        call.save(update_fields=['patient', 'encounter', 'updated_at'])
        log(call, f'Registered at {dept.name if dept else "the hospital"} as {p.mrn}', 'system', by)
    advance(call, 'closed', by, note=f'handed over to {call.handover.get("received_by") or "the receiving team"}')
    return enc


# ------------------------------------------------------------------ crew shifts
def my_shift(user):
    return CrewShift.objects.filter(user=user, ended_at__isnull=True).select_related('ambulance', 'ambulance__station').first()


@transaction.atomic
def start_shift(user, amb, role):
    if role not in dict(CrewShift.ROLE):
        raise Refused('Choose your role on board.')
    end_shift(user)
    s = CrewShift.objects.create(ambulance=amb, user=user, role=role)
    if amb.status == 'off_duty':
        amb.status = 'available'
        amb.save(update_fields=['status', 'updated_at'])
    return s


def end_shift(user):
    n = CrewShift.objects.filter(user=user, ended_at__isnull=True).update(ended_at=timezone.now())
    return n


def save_check(amb, ticks, by, fuel=None, oxygen=None, notes=''):
    amb.checklist = {k: bool(ticks.get(k)) for k, _ in READINESS}
    amb.checked_at, amb.checked_by = timezone.now(), by
    if fuel is not None and str(fuel).isdigit():
        amb.fuel_pct = max(0, min(100, int(fuel)))
    if oxygen is not None and str(oxygen).isdigit():
        amb.oxygen_pct = max(0, min(100, int(oxygen)))
    amb.notes = notes[:300]
    amb.save()
    return amb


def readiness(amb):
    """0–100: how ready the vehicle is (check today, fuel, oxygen, crew)."""
    if amb.status == 'maintenance':
        return 0, ['Out of service' + (f': {amb.notes}' if amb.notes else '')]
    pts, why = 100, []
    if not amb.checked_at or timezone.localtime(amb.checked_at).date() != timezone.localdate():
        pts -= 25
        why.append('Not checked today')
    else:
        missing = [label for k, label in READINESS if not amb.checklist.get(k)]
        pts -= 6 * len(missing)
        why += [f'Not ticked: {m.split(",")[0].lower()}' for m in missing[:2]]
    if amb.fuel_pct < 25:
        pts -= 20
        why.append(f'Fuel {amb.fuel_pct}%')
    if amb.oxygen_pct < 40:
        pts -= 20
        why.append(f'Oxygen {amb.oxygen_pct}%')
    if amb.status not in ('off_duty', 'maintenance') and not amb.crew:
        pts -= 20
        why.append('No crew on board')
    return max(0, pts), why


# ------------------------------------------------------------------ snapshots for screens and the API
def unit_json(a, call=None, known=False):
    """``known=True`` means ``call`` is already the unit's current call (or None), so it is not looked up again."""
    lat, lon = amb_position(a)
    call = call if known else a.current_call
    t = target_of(a, call)
    return {'id': a.pk, 'call_sign': a.call_sign, 'level': a.level, 'level_label': a.get_level_display(), 'status': a.status,
            'status_label': a.get_status_display(), 'color': STATUS_COLOR.get(a.status, '#5A6F7D'), 'lat': lat, 'lon': lon, 'heading': a.heading,
            'speed': round(a.speed_kmh), 'fuel': a.fuel_pct, 'oxygen': a.oxygen_pct, 'station': a.station.name if a.station_id else '',
            'position_at': a.position_at.isoformat() if a.position_at else None, 'can_transport': a.can_transport,
            'crew': [{'name': s.user.get_full_name() or s.user.username, 'first': s.user.first_name or s.user.username, 'role': s.get_role_display()} for s in a.crew],
            'call': {'id': call.pk, 'reference': call.reference, 'priority': call.priority} if call else None, 'target': t}


def call_json(c, detail=False):
    d = {'id': c.pk, 'reference': c.reference, 'priority': c.priority, 'priority_label': c.get_priority_display(), 'color': PRIORITY_COLOR[c.priority],
         'complaint': c.complaint, 'complaint_label': complaint(c.complaint)['label'], 'icon': complaint(c.complaint)['icon'],
         'status': c.status, 'status_label': c.get_status_display(), 'source': c.source, 'lat': c.latitude, 'lon': c.longitude,
         'landmark': c.landmark, 'town': str(c.location) if c.location_id else '', 'waiting_min': c.waiting_minutes,
         'received_at': c.received_at.isoformat(), 'target_min': TARGET_MIN[c.priority], 'late': c.waiting_minutes > TARGET_MIN[c.priority] and not c.on_scene_at,
         'unit': c.ambulance.call_sign if c.ambulance_id else None, 'unit_id': c.ambulance_id, 'patients': c.patients_count,
         'eta_scene': c.eta_scene_at.isoformat() if c.eta_scene_at else None, 'eta_hospital': c.eta_hospital_at.isoformat() if c.eta_hospital_at else None,
         'reason': c.priority_reason}
    if detail:
        d['destination'] = destination_point(c)
        d['patient'] = {'name': c.patient_name, 'age': c.patient_age, 'sex': c.get_patient_sex_display(), 'linked': bool(c.patient_id)}
        d['description'] = c.description
        d['caller'] = {'name': c.caller_name, 'phone': c.caller_phone, 'relation': c.caller_relation}
    return d


def board_payload():
    units = list(Ambulance.objects.filter(active=True).select_related('station').prefetch_related('shifts__user'))
    open_calls = list(EmergencyCall.objects.filter(status__in=EmergencyCall.OPEN).select_related('ambulance', 'location', 'destination'))
    by_unit = {c.ambulance_id: c for c in open_calls if c.ambulance_id and c.status in EmergencyCall.ACTIVE}
    today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    done_today = EmergencyCall.objects.filter(received_at__gte=today, on_scene_at__isnull=False)
    resp = [c.response_minutes for c in done_today]
    from .models import NetworkFacility
    fac = [{'id': f.pk, 'name': f.name, 'lat': f.latitude, 'lon': f.longitude, 'caps': f.capability_list[:4]}
           for f in NetworkFacility.objects.filter(receives_ambulances=True, latitude__isnull=False)]
    incoming = [c for c in open_calls if c.status in ('transporting', 'at_hospital') and destination_point(c)['home']]
    return {
        'now': timezone.now().isoformat(),
        'units': [unit_json(a, by_unit.get(a.pk), known=True) for a in units],
        'calls': [call_json(c) for c in sorted(open_calls, key=lambda c: (c.status not in ('new', 'waiting'), c.priority, c.received_at))],
        'stations': [{'id': s.pk, 'name': s.name, 'kind': s.kind, 'lat': s.latitude, 'lon': s.longitude} for s in EmsStation.objects.filter(active=True)],
        'facilities': fac, 'home': home(),
        'incoming': [dict(call_json(c), handover=atmist(c)) for c in incoming],
        'kpi': {'waiting': sum(1 for c in open_calls if c.status in ('new', 'waiting')), 'active': sum(1 for c in open_calls if c.status in EmergencyCall.ACTIVE),
                'free': sum(1 for a in units if a.status == 'available'), 'units': len(units),
                'today': EmergencyCall.objects.filter(received_at__gte=today).count(),
                'median_response': round(statistics.median(resp), 1) if resp else None},
    }


def public_status(call):
    """What the caller sees on the tracking link and in the phone app. No other patients, no staff surnames."""
    a = call.ambulance
    eta_at = call.eta_scene_at if call.status in ('dispatched', 'en_route') else call.eta_hospital_at if call.status == 'transporting' else None
    eta = max(0, round((eta_at - timezone.now()).total_seconds() / 60)) if eta_at else None
    steps = [('new', 'Request received'), ('waiting', 'Confirmed'), ('dispatched', 'Ambulance assigned'), ('en_route', 'On the way'),
             ('on_scene', 'Crew with you'), ('transporting', 'Going to hospital'), ('at_hospital', 'Arrived')]
    order = [s[0] for s in steps]
    idx = order.index(call.status) if call.status in order else (len(order) if call.status == 'closed' else -1)
    out = {'reference': call.reference, 'status': call.status, 'status_label': call.get_status_display(), 'priority': call.priority,
           'complaint': complaint(call.complaint)['label'], 'eta_minutes': eta, 'step': idx,
           'steps': [{'key': k, 'label': l, 'done': i <= idx} for i, (k, l) in enumerate(steps)],
           'you': {'lat': call.latitude, 'lon': call.longitude, 'landmark': call.landmark}, 'first_aid': complaint(call.complaint)['first_aid'],
           'updated_at': timezone.now().isoformat(), 'closed': call.status in ('closed', 'cancelled'),
           'destination': destination_point(call)['name'] if call.status in ('transporting', 'at_hospital') else None, 'ambulance': None}
    if a and call.status in EmergencyCall.ACTIVE:
        lat, lon = amb_position(a)
        out['ambulance'] = {'call_sign': a.call_sign, 'type': a.get_level_display(), 'plate': a.plate, 'lat': lat, 'lon': lon, 'heading': a.heading,
                            'crew': [{'first_name': s.user.first_name or 'Crew', 'role': s.get_role_display()} for s in a.crew]}
    return out


def lookup_caller(phone):
    """Patients whose phone or emergency contact matches the caller's number (for the call taker)."""
    from .models import Patient
    from .phones import phone_q
    if not phone or len(''.join(ch for ch in phone if ch.isdigit())) < 7:
        return []
    out = []
    for p in Patient.objects.filter(phone_q(phone), deceased_at__isnull=True).prefetch_related('allergies')[:5]:
        out.append({'id': p.pk, 'name': p.full_name, 'mrn': p.mrn, 'age': p.age, 'sex': p.sex, 'blood_group': p.blood_group,
                    'allergies': [a.substance for a in p.allergies.all() if a.status == 'active'], 'alerts': p.medical_alerts[:120],
                    'own': bool(p.phone_local and p.phone_local in ''.join(ch for ch in phone if ch.isdigit())),
                    'town': str(p.location) if p.location_id else '', 'lat': float(p.location.latitude) if p.location_id else None,
                    'lon': float(p.location.longitude) if p.location_id else None})
    return out


# ------------------------------------------------------------------ insights
def insights(days=30):
    since = timezone.now() - timedelta(days=days)
    calls = list(EmergencyCall.objects.filter(received_at__gte=since).select_related('ambulance'))
    by_p = defaultdict(list)
    for c in calls:
        if c.response_minutes is not None:
            by_p[c.priority].append(c.response_minutes)
    resp = [{'p': p, 'label': PRIORITY_WORD[p], 'color': PRIORITY_COLOR[p], 'n': len(by_p[p]), 'target': TARGET_MIN[p],
             'median': round(statistics.median(by_p[p]), 1) if by_p[p] else None,
             'on_time': round(100 * sum(1 for m in by_p[p] if m <= TARGET_MIN[p]) / len(by_p[p])) if by_p[p] else None} for p in (1, 2, 3, 4)]
    per_day = Counter(timezone.localtime(c.received_at).date() for c in calls)
    first = timezone.localdate() - timedelta(days=days - 1)
    daily = [{'d': first + timedelta(days=i), 'n': per_day.get(first + timedelta(days=i), 0)} for i in range(days)]
    hours = Counter(timezone.localtime(c.received_at).hour for c in calls)
    kinds = Counter(c.complaint for c in calls)
    outcomes = Counter(c.outcome or 'open' for c in calls)
    units = Counter(c.ambulance.call_sign for c in calls if c.ambulance_id)
    scene = [round((c.transporting_at - c.on_scene_at).total_seconds() / 60, 1) for c in calls if c.transporting_at and c.on_scene_at]
    return {'n': len(calls), 'resp': resp, 'daily': daily, 'daily_max': max([d['n'] for d in daily] + [1]),
            'hours': [hours.get(h, 0) for h in range(24)], 'hours_max': max(list(hours.values()) + [1]),
            'kinds': [(complaint(k)['label'], complaint(k)['icon'], n) for k, n in kinds.most_common(8)], 'kinds_max': max(list(kinds.values()) + [1]),
            'outcomes': [(dict(EmergencyCall.OUTCOME).get(k, 'Still open'), n) for k, n in outcomes.most_common()],
            'units': units.most_common(10), 'units_max': max(list(units.values()) + [1]),
            'scene_median': round(statistics.median(scene), 1) if scene else None, 'app_share': round(100 * sum(1 for c in calls if c.source == 'app') / len(calls)) if calls else 0}


# ------------------------------------------------------------------ demo motion (DEBUG / EMS_SIMULATION only)
def simulation_enabled():
    return bool(getattr(settings, 'EMS_SIMULATION', settings.DEBUG))


def _move(a, lat, lon, kmh, seconds):
    """Move toward a point. Returns True when it got there."""
    alat, alon = amb_position(a)
    d = km(alat, alon, lat, lon)
    step = kmh / 3600 * seconds / ROAD_FACTOR
    if d is None or d <= max(step, 0.03):
        record_position(a, lat, lon, speed=0, heading=a.heading)
        return True
    f = step / d
    # a gentle sideways wobble so the track looks like a road, not a ruler line
    wob = math.sin((timezone.now().timestamp() / 7) + a.pk) * 0.00035
    nlat = alat + (lat - alat) * f + wob
    nlon = alon + (lon - alon) * f - wob
    record_position(a, nlat, nlon, speed=kmh * (0.85 + 0.3 * abs(math.sin(timezone.now().timestamp() / 5 + a.pk))), heading=bearing(alat, alon, lat, lon))
    return False


def simulate_tick(seconds=5, speedup=12):
    """Advance every moving ambulance as if ``seconds × speedup`` had passed. For demos and training only."""
    if not simulation_enabled():
        raise Refused('Demo motion is switched off on this server.')
    sim = seconds * speedup
    moved = 0
    for a in Ambulance.objects.filter(active=True).exclude(status__in=['available', 'off_duty', 'maintenance']).select_related('station'):
        call = a.current_call
        if call and call.status == 'dispatched':
            advance(call, 'en_route', None, note='demo motion')
            a.refresh_from_db()
            continue
        t = target_of(a, call)
        if call and a.status == 'on_scene':
            if call.on_scene_at and (timezone.now() - call.on_scene_at).total_seconds() * speedup >= 8 * 60:
                if not call.observations.exists():
                    CallObservation.objects.create(call=call, heart_rate=96, systolic=132, diastolic=84, resp_rate=20, spo2=95, avpu='A')
                advance(call, 'transporting', None, note='demo motion')
            continue
        if call and a.status == 'at_hospital':
            if call.at_hospital_at and (timezone.now() - call.at_hospital_at).total_seconds() * speedup >= 10 * 60:
                advance(call, 'closed', None, note='demo motion, handed over')
            continue
        if not t:
            if a.status == 'returning':
                back_in_service(a)
            continue
        kmh = speed_kmh(a.level, call.priority if call else 3, a.longitude) * (1.15 if call and call.priority == 1 else 1)
        if _move(a, t['lat'], t['lon'], kmh, sim):
            if t['kind'] == 'scene':
                advance(call, 'on_scene', None, note='demo motion')
            elif t['kind'] == 'hospital':
                advance(call, 'at_hospital', None, note='demo motion')
            elif t['kind'] == 'station':
                back_in_service(a)
        a.fuel_pct = max(5, a.fuel_pct - (1 if (timezone.now().second % 7 == 0) else 0))
        a.save(update_fields=['fuel_pct'])
        moved += 1
    return moved
