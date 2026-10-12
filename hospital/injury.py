"""Injury and burns assessment: cleaning the entered values and computing what follows from them.

Everything here is mirrored line-for-line in static/hospital/js/injury-figure.js (`MFInjury.compute`) so the animated
figure updates while the clinician types, and the server recomputes on save (the client is never trusted).
tests.InjuryEngineTests checks both sides against the same cases.

Teaching and documentation aid only. The burn-area and fluid figures are standard starting estimates (Lund–Browder
chart, Parkland formula); they do not replace clinical judgement, local protocols or senior review.
"""
import math
from datetime import datetime

# ---------------------------------------------------------------- body regions (Lund–Browder, % of total body surface)
# Age bands: 0 = under 1, 1 = 1–4, 2 = 5–9, 3 = 10–14, 4 = 15, 5 = adult (16+). Values are for the WHOLE region
# (front + back) of ONE side where there is a left and right.
AGE_BANDS = (1, 5, 10, 15, 16)          # upper bounds (exclusive) of bands 0..4; 16+ is band 5
LUND_BROWDER = {
    'head':      (19, 17, 13, 11, 9, 7),
    'neck':      (2, 2, 2, 2, 2, 2),
    'chest':     (6.5,) * 6,            # anterior trunk 13 split upper / lower
    'abdomen':   (6.5,) * 6,
    'upper_back': (6.5,) * 6,           # posterior trunk 13 split upper / lower
    'lower_back': (6.5,) * 6,
    'buttock':   (2.5,) * 6,
    'genitalia': (1,) * 6,
    'upper_arm': (4,) * 6,
    'forearm':   (3,) * 6,
    'hand':      (2.5,) * 6,
    'thigh':     (5.5, 6.5, 8, 8.5, 9, 9.5),
    'leg':       (5, 5, 5.5, 6, 6.5, 7),
    'foot':      (3.5,) * 6,
}
PAIRED = {'buttock', 'upper_arm', 'forearm', 'hand', 'thigh', 'leg', 'foot'}
# Which views a region can be seen (and burned) from. One-view regions carry their whole area on that view.
VIEWS = {
    'head': ('front', 'back'), 'neck': ('front', 'back'), 'chest': ('front',), 'abdomen': ('front',),
    'upper_back': ('back',), 'lower_back': ('back',), 'buttock': ('back',), 'genitalia': ('front',),
    'upper_arm': ('front', 'back'), 'forearm': ('front', 'back'), 'hand': ('front', 'back'),
    'thigh': ('front', 'back'), 'leg': ('front', 'back'), 'foot': ('front', 'back'),
}
REGION_LABELS = {
    'head': 'Head', 'neck': 'Neck', 'chest': 'Chest', 'abdomen': 'Abdomen', 'upper_back': 'Upper back',
    'lower_back': 'Lower back', 'buttock': 'Buttock', 'genitalia': 'Genitalia', 'upper_arm': 'Upper arm',
    'forearm': 'Forearm', 'hand': 'Hand', 'thigh': 'Thigh', 'leg': 'Lower leg', 'foot': 'Foot',
}

BURN_DEPTHS = {
    'superficial': 'Superficial (red, no blisters)',
    'superficial_partial': 'Superficial partial thickness (blisters, painful)',
    'deep_partial': 'Deep partial thickness (blotchy, less painful)',
    'full': 'Full thickness (white/leathery, painless)',
}
BURN_CAUSES = ['flame', 'scald', 'contact', 'electrical', 'chemical', 'friction', 'other']

SPINE_LEVELS = [f'C{i}' for i in range(1, 8)] + [f'T{i}' for i in range(1, 13)] + [f'L{i}' for i in range(1, 6)] + ['S']
ASIA = {
    'A': 'Complete: no movement or feeling below the injury',
    'B': 'Sensory incomplete: some feeling, no movement below the injury',
    'C': 'Motor incomplete: some movement, most key muscles below grade 3',
    'D': 'Motor incomplete: most key muscles below the injury grade 3 or more',
    'E': 'Normal movement and feeling',
}
SPINE_TYPES = ['fracture', 'dislocation', 'cord_contusion', 'central_cord', 'disc', 'ligament', 'unknown']
# Fraction of nerve signal that gets past the lesion, per ASIA grade (drives the animation and limb shading).
ASIA_PASS = {'A': 0.0, 'B': 0.15, 'C': 0.4, 'D': 0.75, 'E': 1.0}

INJURY_TYPES = {
    'fracture': 'Fracture', 'dislocation': 'Dislocation', 'laceration': 'Laceration', 'abrasion': 'Abrasion',
    'contusion': 'Bruise / contusion', 'penetrating': 'Penetrating wound', 'crush': 'Crush injury',
    'amputation': 'Amputation', 'sprain': 'Sprain / strain',
}
SEVERITIES = ['minor', 'moderate', 'severe']
BLEEDING = ['none', 'oozing', 'active']
PUPILS = ['equal', 'unequal', 'fixed']

MAX_BURNS, MAX_INJURIES = 40, 30


# ---------------------------------------------------------------- helpers
def _num(v, lo, hi, default=None, digits=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x:                                      # NaN
        return default
    x = max(lo, min(hi, x))
    return round(x, digits) if digits is not None else x


def rnd(x, d=0):
    """Round half up. Written the same way in injury-figure.js so both sides give identical numbers."""
    m = 10 ** d
    return math.floor(x * m + 0.5) / m


def fmt(x):
    """Numbers in messages, the way JavaScript's String() prints them (18.0 -> '18', 18.5 -> '18.5')."""
    return str(int(x)) if float(x).is_integer() else str(x)


def _int(v, lo, hi, default=None):
    x = _num(v, lo, hi, None)
    return default if x is None else int(round(x))


def _pick(v, allowed, default):
    return v if v in allowed else default


def _txt(v, n=200):
    return str(v or '').strip()[:n]


def age_band(age):
    if age is None:
        return 5
    for i, hi in enumerate(AGE_BANDS):
        if age < hi:
            return i
    return 5


def region_area(region, view, age):
    """% of total body surface for one region, one side (left/right), one view (front/back)."""
    total = LUND_BROWDER[region][age_band(age)]
    return total / len(VIEWS[region])


# ---------------------------------------------------------------- cleaning
def clean_assessment(raw):
    """Return a safe, normalised copy of what the clinician entered. Unknown keys are dropped."""
    raw = raw if isinstance(raw, dict) else {}
    out = {'burns': [], 'injuries': [], 'spine': None, 'head': None, 'notes': _txt(raw.get('notes'), 2000)}

    b = raw.get('burn') if isinstance(raw.get('burn'), dict) else {}
    out['burn'] = {
        'cause': _pick(b.get('cause'), BURN_CAUSES, 'flame'),
        'time': _clean_dt(b.get('time')),
        'inhalation': bool(b.get('inhalation')),
        'given_ml': _int(b.get('given_ml'), 0, 50000, 0),
    }
    for e in (raw.get('burns') or [])[:MAX_BURNS]:
        if not isinstance(e, dict) or e.get('region') not in LUND_BROWDER:
            continue
        view = _pick(e.get('view'), VIEWS[e['region']], VIEWS[e['region']][0])
        side = _pick(e.get('side'), ('left', 'right'), 'left') if e['region'] in PAIRED else ''
        pct = _int(e.get('pct'), 1, 100, None)
        if pct is None:
            continue
        out['burns'].append({'region': e['region'], 'side': side, 'view': view,
                             'depth': _pick(e.get('depth'), BURN_DEPTHS, 'superficial_partial'), 'pct': pct,
                             'circumferential': bool(e.get('circumferential'))})

    for e in (raw.get('injuries') or [])[:MAX_INJURIES]:
        if not isinstance(e, dict) or e.get('region') not in LUND_BROWDER or e.get('type') not in INJURY_TYPES:
            continue
        out['injuries'].append({
            'type': e['type'], 'region': e['region'],
            'side': _pick(e.get('side'), ('left', 'right'), 'left') if e['region'] in PAIRED else '',
            'view': _pick(e.get('view'), VIEWS[e['region']], VIEWS[e['region']][0]),
            'severity': _pick(e.get('severity'), SEVERITIES, 'moderate'),
            'bleeding': _pick(e.get('bleeding'), BLEEDING, 'none'),
            'open': bool(e.get('open')) if e['type'] == 'fracture' else False,
            'note': _txt(e.get('note'), 160),
        })

    s = raw.get('spine')
    if isinstance(s, dict) and s.get('level') in SPINE_LEVELS:
        out['spine'] = {'level': s['level'], 'asia': _pick(s.get('asia'), ASIA, 'A'),
                        'type': _pick(s.get('type'), SPINE_TYPES, 'fracture'),
                        'immobilised': bool(s.get('immobilised', True))}

    h = raw.get('head')
    if isinstance(h, dict) and any(h.get(k) not in (None, '') for k in ('eye', 'verbal', 'motor')):
        out['head'] = {'eye': _int(h.get('eye'), 1, 4, 4), 'verbal': _int(h.get('verbal'), 1, 5, 5),
                       'motor': _int(h.get('motor'), 1, 6, 6), 'pupils': _pick(h.get('pupils'), PUPILS, 'equal'),
                       'loc': bool(h.get('loc'))}
    return out


def _clean_dt(v):
    v = _txt(v, 40)
    if not v:
        return ''
    try:
        return datetime.strptime(v[:16].replace(' ', 'T'), '%Y-%m-%dT%H:%M').strftime('%Y-%m-%dT%H:%M')
    except ValueError:
        return ''


# ---------------------------------------------------------------- computing
def spinal_effects(level, asia):
    """Which regions lose function below the lesion, and the clinical risks that follow from the level."""
    i = SPINE_LEVELS.index(level)
    passing = ASIA_PASS[asia]
    if asia == 'E':
        affected = []
    elif i <= SPINE_LEVELS.index('C4'):
        affected = ['upper_arm', 'forearm', 'hand', 'chest', 'abdomen', 'upper_back', 'lower_back', 'buttock', 'genitalia', 'thigh', 'leg', 'foot']
    elif i <= SPINE_LEVELS.index('C7'):
        affected = ['forearm', 'hand', 'chest', 'abdomen', 'upper_back', 'lower_back', 'buttock', 'genitalia', 'thigh', 'leg', 'foot']
    elif i <= SPINE_LEVELS.index('T6'):
        affected = ['abdomen', 'lower_back', 'buttock', 'genitalia', 'thigh', 'leg', 'foot']
    elif i <= SPINE_LEVELS.index('T12'):
        affected = ['buttock', 'genitalia', 'thigh', 'leg', 'foot']
    elif i <= SPINE_LEVELS.index('L3'):
        affected = ['leg', 'foot', 'genitalia']
    elif i <= SPINE_LEVELS.index('L5'):
        affected = ['foot', 'genitalia']
    else:
        affected = ['genitalia']
    cervical, high = level.startswith('C'), i <= SPINE_LEVELS.index('T6')
    if asia == 'E':
        pattern = 'No loss of function'
    elif cervical:
        pattern = 'Tetraplegia (arms and legs)' if asia in 'AB' else 'Incomplete tetraplegia'
    elif i <= SPINE_LEVELS.index('L1'):
        pattern = 'Paraplegia (legs and trunk)' if asia in 'AB' else 'Incomplete paraplegia'
    else:
        pattern = 'Cauda equina / nerve root injury'
    return {'affected': affected, 'pass': passing, 'pattern': pattern, 'cervical': cervical,
            'breathing_risk': asia in 'ABC' and i <= SPINE_LEVELS.index('C5'),
            'ventilation_likely': asia in 'AB' and i <= SPINE_LEVELS.index('C3'),
            'neurogenic_shock_risk': asia in 'ABC' and high, 'dysreflexia_risk': asia in 'ABCD' and high,
            'below_cord': i > SPINE_LEVELS.index('L1')}


def compute(data, *, age=None, weight_kg=None, vitals=None, now=None):
    """Derived figures and alerts from a cleaned assessment. `vitals` may hold systolic, heart_rate, spo2 …"""
    vitals = vitals or {}
    weight = _num(weight_kg, 1, 400, None)
    areas = {}                                     # (region, side, view) -> % of that surface, capped at 100
    by_depth = {k: 0.0 for k in BURN_DEPTHS}
    for e in data.get('burns', []):
        key = (e['region'], e['side'], e['view'])
        already = areas.get(key, 0)
        pct = min(e['pct'], 100 - already)
        if pct <= 0:
            continue
        areas[key] = already + pct
        by_depth[e['depth']] += region_area(e['region'], e['view'], age) * pct / 100
    by_depth = {k: rnd(v, 1) for k, v in by_depth.items()}
    tbsa = rnd(min(100.0, by_depth['superficial_partial'] + by_depth['deep_partial'] + by_depth['full']), 1)   # erythema is not counted
    child = age is not None and age < 16
    threshold = 10 if child else 15
    fluids = None
    if tbsa > 0 and weight:
        total = int(rnd(4 * weight * tbsa))
        first = int(rnd(total / 2))
        second = total - first
        fluids = {'total_24h': total, 'first_8h': first, 'next_16h': second,
                  'rate_first_ml_h': int(rnd(first / 8)), 'rate_next_ml_h': int(rnd(second / 16)),
                  'urine_target_ml_h': int(rnd((1.0 if child and weight < 30 else 0.5) * weight)),
                  'resuscitation_needed': tbsa >= threshold, 'threshold': threshold}
        burn = data.get('burn') or {}
        if burn.get('time'):
            try:
                started = datetime.strptime(burn['time'], '%Y-%m-%dT%H:%M')
                elapsed = max(0.0, ((now or datetime.now()) - started).total_seconds() / 3600)
                fluids['hours_since_burn'] = rnd(elapsed, 1)
                given = burn.get('given_ml') or 0
                if elapsed < 8:
                    fluids['catch_up_ml_h'] = int(rnd(max(0, first - given) / max(0.5, 8 - elapsed)))
                    fluids['phase'] = 'first 8 hours'
                elif elapsed < 24:
                    fluids['catch_up_ml_h'] = int(rnd(max(0, total - given) / max(0.5, 24 - elapsed)))
                    fluids['phase'] = 'next 16 hours'
                else:
                    fluids['phase'] = 'after 24 hours'
            except ValueError:
                pass

    alerts = []
    if tbsa >= threshold:
        alerts.append({'level': 'high', 'text': f'Major burn: {fmt(tbsa)}% of body surface. Start formal fluid resuscitation and refer to a burns unit.'})
    elif tbsa > 0:
        alerts.append({'level': 'info', 'text': f'Burns cover {fmt(tbsa)}% of body surface (not counting simple redness).'})
    if tbsa > 0 and not weight:
        alerts.append({'level': 'warn', 'text': 'Enter the weight to calculate fluids.'})
    if (data.get('burn') or {}).get('inhalation'):
        alerts.append({'level': 'high', 'text': 'Possible inhalation injury: watch the airway closely; early senior anaesthetic review.'})
    for e in data.get('burns', []):
        if e.get('circumferential') and e['depth'] in ('deep_partial', 'full'):
            alerts.append({'level': 'high', 'text': f'Deep circumferential burn of the {REGION_LABELS[e["region"]].lower()}: check circulation and breathing; escharotomy may be needed.'})
    if any(e['region'] in ('head', 'neck', 'hand', 'foot', 'genitalia') and e['depth'] != 'superficial' for e in data.get('burns', [])):
        alerts.append({'level': 'warn', 'text': 'Burns to the face, hands, feet or genitals need specialist burns care.'})

    spine = None
    if data.get('spine'):
        s = data['spine']
        spine = spinal_effects(s['level'], s['asia'])
        sbp, hr = _num(vitals.get('systolic'), 0, 400), _num(vitals.get('heart_rate'), 0, 400)
        spine['neurogenic_shock'] = bool(spine['neurogenic_shock_risk'] and sbp is not None and hr is not None and sbp < 90 and hr < 60)
        if spine['neurogenic_shock']:
            alerts.append({'level': 'high', 'text': f'Low blood pressure ({fmt(sbp)}) with slow pulse ({fmt(hr)}) after a {s["level"]} injury: likely neurogenic shock.'})
        if spine['ventilation_likely']:
            alerts.append({'level': 'high', 'text': f'{s["level"]} complete injury: breathing muscles are affected; prepare for ventilation.'})
        elif spine['breathing_risk']:
            alerts.append({'level': 'warn', 'text': f'{s["level"]} injury can weaken breathing: monitor breathing effort and vital capacity.'})
        if spine['cervical'] and not s.get('immobilised'):
            alerts.append({'level': 'high', 'text': 'Cervical injury without immobilisation: apply a collar and log-roll.'})
        if spine['dysreflexia_risk']:
            alerts.append({'level': 'info', 'text': 'Injury at or above T6: watch for autonomic dysreflexia (sudden high blood pressure, headache).'})

    head = None
    if data.get('head'):
        h = data['head']
        gcs = h['eye'] + h['verbal'] + h['motor']
        severity = 'mild' if gcs >= 13 else 'moderate' if gcs >= 9 else 'severe'
        head = {'gcs': gcs, 'severity': severity}
        if gcs <= 8:
            alerts.append({'level': 'high', 'text': f'GCS {gcs}: severe head injury. Protect the airway.'})
        elif gcs <= 12:
            alerts.append({'level': 'warn', 'text': f'GCS {gcs}: moderate head injury. CT and frequent neuro checks.'})
        if h['pupils'] in ('unequal', 'fixed'):
            alerts.append({'level': 'high', 'text': f'Pupils {h["pupils"]}: possible raised pressure in the skull. Urgent senior review.'})

    for e in data.get('injuries', []):
        name = f'{(e["side"] + " ") if e["side"] else ""}{REGION_LABELS[e["region"]].lower()}'
        if e['bleeding'] == 'active':
            alerts.append({'level': 'high', 'text': f'Active bleeding from the {name}: apply pressure.'})
        if e['type'] == 'fracture' and e.get('open'):
            alerts.append({'level': 'high', 'text': f'Open fracture of the {name}: antibiotics, tetanus and urgent orthopaedic review.'})
        if e['type'] == 'amputation':
            alerts.append({'level': 'high', 'text': f'Amputation at the {name}: control bleeding and preserve the part.'})
    if _num(vitals.get('spo2'), 0, 100, 100) < 92:
        alerts.append({'level': 'high', 'text': f'Oxygen saturation {fmt(_num(vitals.get("spo2"), 0, 100))}%: give oxygen.'})

    order = {'high': 0, 'warn': 1, 'info': 2}
    alerts.sort(key=lambda a: order[a['level']])
    return {'tbsa': tbsa, 'by_depth': by_depth, 'fluids': fluids, 'spine': spine, 'head': head, 'alerts': alerts,
            'counts': {'burns': len(data.get('burns', [])), 'injuries': len(data.get('injuries', []))}}


def summary(computed, data):
    """One line for chips and the bed page."""
    bits = []
    if computed.get('tbsa'):
        bits.append(f'Burns {fmt(computed["tbsa"])}% TBSA')
    if data.get('spine'):
        bits.append(f'{data["spine"]["level"]} spinal injury, ASIA {data["spine"]["asia"]}')
    if computed.get('head'):
        bits.append(f'Head injury, GCS {computed["head"]["gcs"]}')
    n = len(data.get('injuries', []))
    if n:
        bits.append(f'{n} other injur{"y" if n == 1 else "ies"}')
    return ' · '.join(bits) or 'No injuries recorded'


def catalogue():
    """Everything the editor needs to build its menus (serialised into the page)."""
    return {'regions': REGION_LABELS, 'views': VIEWS, 'paired': sorted(PAIRED), 'lund_browder': LUND_BROWDER,
            'age_bands': AGE_BANDS, 'depths': BURN_DEPTHS, 'causes': BURN_CAUSES, 'levels': SPINE_LEVELS,
            'asia': ASIA, 'asia_pass': ASIA_PASS, 'spine_types': SPINE_TYPES, 'injury_types': INJURY_TYPES,
            'severities': SEVERITIES, 'bleeding': BLEEDING, 'pupils': PUPILS}
