"""Bedside equipment and observations for an inpatient.

`clean_devices` normalises what the nurse enters; `derive` turns it into the numbers the animated bed scene uses
(drops per minute in the drip chamber, time until the bag empties, estimated oxygen percentage, urine output per kg).
`news2` scores a set of observations (Royal College of Physicians NEWS2, SpO2 scale 1).

The JavaScript scene (static/hospital/js/bedside.js) mirrors `derive` and `news2` for live preview while typing; the
server's values are what get saved and shown on reload. Tests: tests.BedsideTests.
"""
from .injury import _int, _num, _pick, _txt, fmt, rnd

IV_FLUIDS = {
    'saline': 'Sodium chloride 0.9%', 'ringers': "Ringer's lactate / Hartmann's", 'dextrose5': 'Dextrose 5%',
    'dextrose_saline': 'Dextrose 4% / saline 0.18%', 'blood': 'Packed red cells', 'plasma': 'Fresh frozen plasma',
    'other': 'Other (see notes)',
}
IV_SITES = {
    'hand_l': 'Back of left hand', 'hand_r': 'Back of right hand', 'forearm_l': 'Left forearm',
    'forearm_r': 'Right forearm', 'acf_l': 'Left elbow crease', 'acf_r': 'Right elbow crease', 'central': 'Central line (neck)',
}
DROP_FACTORS = (10, 15, 20, 60)
O2_DEVICES = {
    'nasal': 'Nasal cannula', 'mask': 'Simple face mask', 'nrb': 'Non-rebreather mask (reservoir bag)',
    'venturi': 'Venturi mask', 'hfnc': 'High-flow nasal cannula',
}
O2_LIMITS = {'nasal': (0.5, 6), 'mask': (5, 10), 'nrb': (10, 15), 'venturi': (2, 15), 'hfnc': (10, 60)}
NG_PURPOSES = {'feeding': 'Feeding', 'drainage': 'Free drainage / decompression'}


def clean_devices(raw):
    raw = raw if isinstance(raw, dict) else {}
    g = lambda k: raw.get(k) if isinstance(raw.get(k), dict) else {}
    iv, o2, cath, ng, tr, cd, bed, cuff = g('iv'), g('oxygen'), g('catheter'), g('ng_tube'), g('traction'), g('chest_drain'), g('bed'), g('bp_cuff')
    bag = _int(iv.get('bag_ml'), 50, 3000, 1000)
    device = _pick(o2.get('device'), O2_DEVICES, 'nasal')
    lo, hi = O2_LIMITS[device]
    return {
        'iv': {'on': bool(iv.get('on')), 'fluid': _pick(iv.get('fluid'), IV_FLUIDS, 'saline'), 'bag_ml': bag,
               'remaining_ml': _int(iv.get('remaining_ml'), 0, bag, bag), 'rate_ml_h': _num(iv.get('rate_ml_h'), 0, 999, 0, 1),
               'drop_factor': int(iv.get('drop_factor')) if str(iv.get('drop_factor')) in map(str, DROP_FACTORS) else 20,
               'site': _pick(iv.get('site'), IV_SITES, 'hand_l'), 'pump': bool(iv.get('pump')), 'note': _txt(iv.get('note'), 120)},
        'oxygen': {'on': bool(o2.get('on')), 'device': device, 'flow_l_min': _num(o2.get('flow_l_min'), lo, hi, lo, 1),
                   'fio2': _int(o2.get('fio2'), 21, 100, 28 if device == 'venturi' else 40)},
        'monitor': {'on': bool(g('monitor').get('on', True)), 'sound': bool(g('monitor').get('sound'))},
        'pulse_ox': {'on': bool(g('pulse_ox').get('on', True))},
        'bp_cuff': {'on': bool(cuff.get('on', True)), 'interval_min': _int(cuff.get('interval_min'), 5, 240, 60)},
        'catheter': {'on': bool(cath.get('on')), 'bag_ml': _int(cath.get('bag_ml'), 0, 2000, 0),
                     'output_ml_h': _int(cath.get('output_ml_h'), 0, 1000, 0)},
        'ng_tube': {'on': bool(ng.get('on')), 'purpose': _pick(ng.get('purpose'), NG_PURPOSES, 'feeding'),
                    'feed_ml_h': _int(ng.get('feed_ml_h'), 0, 300, 0)},
        'collar': {'on': bool(g('collar').get('on'))},
        'traction': {'on': bool(tr.get('on')), 'limb': _pick(tr.get('limb'), ('left', 'right'), 'right'),
                     'weight_kg': _num(tr.get('weight_kg'), 1, 15, 4, 1)},
        'chest_drain': {'on': bool(cd.get('on')), 'side': _pick(cd.get('side'), ('left', 'right'), 'right'),
                        'bubbling': bool(cd.get('bubbling')), 'drainage_ml': _int(cd.get('drainage_ml'), 0, 3000, 0)},
        'bed': {'head_deg': _int(bed.get('head_deg'), 0, 80, 30), 'rails': bool(bed.get('rails', True))},
    }


def fio2_estimate(o2):
    """Approximate inspired oxygen % for the chosen device and flow. Rough bedside figures, not a measurement."""
    if not o2.get('on'):
        return 21
    d, f = o2['device'], o2['flow_l_min']
    if d == 'nasal':
        return min(44, int(rnd(21 + 4 * f)))
    if d == 'mask':
        return min(60, int(rnd(35 + (f - 5) * 5)))
    if d == 'nrb':
        return min(90, int(rnd(60 + (f - 10) * 5)))
    return o2.get('fio2', 40)                       # venturi / high flow: set on the device


def derive(dev, *, weight_kg=None):
    """Numbers for the animation and the warnings shown beside it."""
    iv, cath = dev['iv'], dev['catheter']
    rate, df = iv['rate_ml_h'], iv['drop_factor']
    dpm = rnd(rate * df / 60, 1) if iv['on'] else 0
    hours_left = rnd(iv['remaining_ml'] / rate, 1) if iv['on'] and rate > 0 else None
    weight = _num(weight_kg, 1, 400, None)
    uo_per_kg = rnd(cath['output_ml_h'] / weight, 2) if cath['on'] and weight else None
    warnings = []
    if iv['on'] and rate == 0:
        warnings.append('IV is up but the rate is 0 mL/h.')
    if iv['on'] and iv['remaining_ml'] < 50:
        warnings.append(f'IV bag nearly empty ({iv["remaining_ml"]} mL left).')
    elif hours_left is not None and hours_left < 1:
        warnings.append(f'IV bag runs out in about {fmt(rnd(hours_left * 60))} minutes.')
    if iv['on'] and not iv['pump'] and dpm > 100:
        warnings.append(f'{fmt(dpm)} drops/min is too fast to count by gravity: use an infusion pump.')
    if uo_per_kg is not None and uo_per_kg < 0.5:
        warnings.append(f'Urine output {fmt(uo_per_kg)} mL/kg/h is below 0.5: check fluids and the catheter.')
    if cath['on'] and cath['bag_ml'] >= 1500:
        warnings.append('Urine bag is nearly full: empty and record.')
    if dev['chest_drain']['on'] and dev['chest_drain']['bubbling']:
        warnings.append('Chest drain is bubbling: air leak from the lung. Do not clamp.')
    return {'drops_per_min': dpm, 'hours_left': hours_left, 'fio2': fio2_estimate(dev['oxygen']),
            'urine_ml_kg_h': uo_per_kg, 'warnings': warnings}


# ---------------------------------------------------------------- NEWS2
def _band(v, bands):
    for limit, score in bands:
        if v <= limit:
            return score
    return bands[-1][1]


def news2(obs):
    """{'total', 'parts', 'risk'} or None when nothing scorable was entered. Missing values score 0 but are listed."""
    parts, missing = {}, []
    rr, spo2, sbp, hr, t = (obs.get(k) for k in ('resp_rate', 'spo2', 'systolic', 'heart_rate', 'temperature_c'))
    if rr is not None:
        parts['resp_rate'] = _band(rr, [(8, 3), (11, 1), (20, 0), (24, 2), (999, 3)])
    else:
        missing.append('resp_rate')
    if spo2 is not None:
        parts['spo2'] = _band(spo2, [(91, 3), (93, 2), (95, 1), (100, 0)])
    else:
        missing.append('spo2')
    parts['oxygen'] = 2 if obs.get('on_oxygen') else 0
    if sbp is not None:
        parts['systolic'] = _band(sbp, [(90, 3), (100, 2), (110, 1), (219, 0), (999, 3)])
    else:
        missing.append('systolic')
    if hr is not None:
        parts['heart_rate'] = _band(hr, [(40, 3), (50, 1), (90, 0), (110, 1), (130, 2), (999, 3)])
    else:
        missing.append('heart_rate')
    parts['consciousness'] = 0 if (obs.get('consciousness') or 'A') == 'A' else 3
    if t is not None:
        parts['temperature_c'] = _band(float(t), [(35.0, 3), (36.0, 1), (38.0, 0), (39.0, 1), (99, 2)])
    else:
        missing.append('temperature_c')
    if len(missing) == 5:
        return None
    total = sum(parts.values())
    risk = 'high' if total >= 7 else 'medium' if total >= 5 else 'low-medium' if 3 in parts.values() else 'low'
    response = {'high': 'Emergency response: continuous monitoring and urgent clinical review',
                'medium': 'Urgent review by a clinician; observations at least hourly',
                'low-medium': 'A single parameter scores 3: urgent ward review',
                'low': 'Routine observations (at least every 4–6 hours if score 1–4, 12-hourly if 0)'}[risk]
    return {'total': total, 'parts': parts, 'risk': risk, 'response': response, 'missing': missing}


def clean_observation(raw):
    raw = raw if isinstance(raw, dict) else {}
    out = {'heart_rate': _int(raw.get('heart_rate'), 20, 250), 'systolic': _int(raw.get('systolic'), 40, 280),
           'diastolic': _int(raw.get('diastolic'), 20, 180), 'resp_rate': _int(raw.get('resp_rate'), 3, 70),
           'spo2': _int(raw.get('spo2'), 50, 100), 'temperature_c': _num(raw.get('temperature_c'), 30, 43, None, 1),
           'consciousness': _pick(raw.get('consciousness'), ('A', 'C', 'V', 'P', 'U'), 'A'),
           'on_oxygen': bool(raw.get('on_oxygen'))}
    if out['systolic'] is not None and out['diastolic'] is not None and out['diastolic'] >= out['systolic']:
        raise ValueError('The lower blood pressure number must be smaller than the upper one.')
    if all(out[k] is None for k in ('heart_rate', 'systolic', 'resp_rate', 'spo2', 'temperature_c')):
        raise ValueError('Enter at least one observation.')
    return out


def catalogue():
    return {'fluids': IV_FLUIDS, 'sites': IV_SITES, 'drop_factors': DROP_FACTORS, 'o2_devices': O2_DEVICES,
            'o2_limits': O2_LIMITS, 'ng_purposes': NG_PURPOSES}
