"""Operating theatre rules: the patient pathway, the WHO Surgical Safety Checklist, scheduling clashes, pre-operative
readiness (including the patient's latest blood results) and the recovery (Aldrete) score.

The pathway is enforced here, on the server, so it cannot be skipped from the browser:

    requested → scheduled → ready → in_theatre → operating → recovery → completed
                 ↘ postponed / cancelled (with a reason)

* scheduled  needs a room and a start time that clash with nothing (room, surgeon, anaesthetist, patient)
* ready      needs every ward pre-op check answered (consent and site marking cannot be "not applicable")
* in_theatre needs the WHO "Sign in" (before anaesthesia)
* operating  needs the WHO "Time out" (before the skin incision)
* recovery   needs the WHO "Sign out" and the name of the procedure performed
* completed  needs where the patient goes, and an Aldrete score of 9 or more (or a recorded reason)

Teaching and documentation aid. Follow local theatre policies; the checklist does not replace clinical judgement.
"""
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

TURNOVER_MIN = 15                     # cleaning and set-up between two cases in the same room
FOOD_HOURS, CLEAR_HOURS = 6, 2        # usual fasting before anaesthesia

PATH = ['requested', 'scheduled', 'ready', 'in_theatre', 'operating', 'recovery', 'completed']
TRANSITIONS = {
    'requested': {'scheduled', 'cancelled'},
    'scheduled': {'ready', 'requested', 'postponed', 'cancelled'},
    'postponed': {'scheduled', 'requested', 'cancelled'},
    'ready': {'in_theatre', 'scheduled', 'postponed', 'cancelled'},
    'in_theatre': {'operating', 'cancelled'},          # abandoned before incision (e.g. anaesthetic problem)
    'operating': {'recovery'},
    'recovery': {'completed'},
    'completed': set(), 'cancelled': set(),
}
ACTIVE = ('in_theatre', 'operating', 'recovery')
BOOKED = ('scheduled', 'ready', 'in_theatre', 'operating', 'recovery', 'completed')

# ------------------------------------------------------------------ ward pre-operative checks
PREOP = [
    ('consent', 'Consent signed and in the notes', False),
    ('id_band', 'Identity band on and correct', False),
    ('site_marked', 'Operation site marked with an arrow', True),
    ('allergies', 'Allergies checked and recorded', False),
    ('fasted', 'Fasting confirmed', True),
    ('bloods', 'Blood results reviewed', True),
    ('crossmatch', 'Blood grouped and cross-matched', True),
    ('pregnancy', 'Pregnancy test done (women 12–50)', True),
    ('meds', 'Usual medicines / premedication given as planned', True),
    ('prostheses', 'Jewellery, dentures, contact lenses and prostheses removed', True),
]
PREOP_LABELS = {k: l for k, l, _ in PREOP}

# ------------------------------------------------------------------ WHO Surgical Safety Checklist (2009)
CHECKLIST = {
    'sign_in': {'title': 'Sign in', 'when': 'Before induction of anaesthesia', 'items': [
        ('identity', 'Patient has confirmed identity, site, procedure and consent', False),
        ('site', 'Site marked', True),
        ('machine', 'Anaesthesia machine and medication check complete', False),
        ('oximeter', 'Pulse oximeter on the patient and working', False),
        ('allergy', 'Known allergy reviewed with the team', False),
        ('airway', 'Difficult airway / aspiration risk: equipment and help available', True),
        ('blood_loss', 'Risk of more than 500 mL blood loss (7 mL/kg in children): IV access and fluids planned', True),
    ]},
    'time_out': {'title': 'Time out', 'when': 'Before skin incision', 'items': [
        ('team', 'All team members introduced by name and role', False),
        ('confirm', 'Surgeon, anaesthetist and nurse confirm patient, site and procedure', False),
        ('antibiotic', 'Antibiotic prophylaxis given within the last 60 minutes', True),
        ('surgeon_events', 'Surgeon: critical or unexpected steps, duration, expected blood loss', False),
        ('anaesthesia_events', 'Anaesthetist: patient-specific concerns', False),
        ('nursing_events', 'Nursing: sterility confirmed, equipment issues or concerns', False),
        ('imaging', 'Essential imaging displayed', True),
    ]},
    'sign_out': {'title': 'Sign out', 'when': 'Before the patient leaves the operating room', 'items': [
        ('recorded', 'Name of the procedure recorded', False),
        ('counts', 'Instrument, swab and needle counts correct', False),
        ('specimen', 'Specimens labelled (including the patient name)', True),
        ('equipment', 'Equipment problems addressed', True),
        ('recovery', 'Key concerns for recovery and management reviewed', False),
    ]},
}
PHASE_FOR = {'in_theatre': 'sign_in', 'operating': 'time_out', 'recovery': 'sign_out'}
ANSWERS = ('yes', 'na')


def _txt(v, n=200):
    return str(v or '').strip()[:n]


def _num(v, lo, hi):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return max(lo, min(hi, x))


# ------------------------------------------------------------------ pre-op
def preop_items(case):
    """The ward checks that apply to this case: (key, label, may_be_na)."""
    p = case.patient if case.patient_id else case.encounter.patient
    out = []
    for key, label, na in PREOP:
        if key == 'site_marked' and not case.side:
            continue
        if key == 'crossmatch' and not case.blood_units:
            continue
        if key == 'pregnancy' and not (p.sex == 'F' and p.age is not None and 12 <= p.age <= 50):
            continue
        out.append((key, label, na and key not in ('site_marked',)))
    return out


def clean_preop(raw, case):
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key, _, na in preop_items(case):
        v = raw.get(key)
        out[key] = v if v == 'yes' or (v == 'na' and na) else ''
    return out


def fasting(case, now=None):
    """Hours since food and clear fluids, and whether the usual 6 h / 2 h rule is met."""
    now = now or timezone.now()
    out = {'food_hours': None, 'clear_hours': None, 'ok': None}
    if case.fasting_since:
        out['food_hours'] = round(max(0.0, (now - case.fasting_since).total_seconds() / 3600), 1)
    if case.clear_fluids_since:
        out['clear_hours'] = round(max(0.0, (now - case.clear_fluids_since).total_seconds() / 3600), 1)
    if out['food_hours'] is not None:
        out['ok'] = out['food_hours'] >= FOOD_HOURS and (out['clear_hours'] is None or out['clear_hours'] >= CLEAR_HOURS)
    return out


def latest_labs(patient, days=30):
    """The patient's most recent results that matter before an operation (numbers only)."""
    from .models import LabResultValue
    since = timezone.now() - timedelta(days=days)
    out = {}
    qs = (LabResultValue.objects.filter(order__encounter__patient=patient, value_number__isnull=False, parameter__code__in=['HB', 'K', 'PLT', 'INR', 'A1C', 'FBG'],
                                        created_at__gte=since).select_related('parameter').order_by('-created_at'))
    for v in qs:
        code = v.parameter.code
        if code not in out:
            out[code] = {'value': float(v.value_number), 'unit': v.parameter.unit, 'name': v.parameter.name, 'at': v.created_at.isoformat()}
    return out


def readiness(case, now=None, labs=None):
    """Everything that decides whether the patient can go to theatre, with warnings drawn from the real values."""
    items = preop_items(case)
    pre = clean_preop(case.preop, case)
    missing = [PREOP_LABELS[k] for k, _, _ in items if not pre.get(k)]
    fast = fasting(case, now)
    labs = latest_labs(case.patient) if labs is None else labs
    warnings = []
    emergency = case.urgency == 'immediate'
    if fast['ok'] is False:
        warnings.append({'level': 'warn' if emergency else 'high',
                         'text': f"Not fasted long enough (food {fast['food_hours']} h"
                                 + (f", clear fluids {fast['clear_hours']} h" if fast['clear_hours'] is not None else '')
                                 + f"; usual minimum {FOOD_HOURS} h / {CLEAR_HOURS} h)." + (' Plan a rapid-sequence induction.' if emergency else '')})
    hb, k, plt, inr = (labs.get(c, {}).get('value') for c in ('HB', 'K', 'PLT', 'INR'))
    glu = labs.get('FBG', {}).get('value')
    if hb is not None and hb < 8:
        warnings.append({'level': 'high', 'text': f'Haemoglobin {hb:g} g/dL: correct anaemia or have blood ready.'})
    elif hb is not None and hb < 10 and case.blood_units:
        warnings.append({'level': 'warn', 'text': f'Haemoglobin {hb:g} g/dL with blood loss expected: confirm cross-matched blood is in the fridge.'})
    if k is not None and (k < 3.0 or k > 5.5):
        warnings.append({'level': 'high', 'text': f'Potassium {k:g} mmol/L: risk of heart rhythm problems under anaesthesia; correct first.'})
    if plt is not None and plt < 80:
        warnings.append({'level': 'high', 'text': f'Platelets {plt:g} ×10⁹/L: bleeding risk' + ('; spinal / epidural not advised below 80.' if case.anaesthesia in ('spinal', 'epidural') else '.')})
    if inr is not None and inr > 1.5:
        warnings.append({'level': 'high', 'text': f'INR {inr:g}: clotting is slow' + ('; spinal / epidural is unsafe.' if case.anaesthesia in ('spinal', 'epidural') else '; correct before surgery.')})
    if glu is not None and glu > 15:
        warnings.append({'level': 'warn', 'text': f'Glucose {glu:g} mmol/L: poorly controlled; start a variable-rate insulin plan.'})
    if case.asa and case.asa >= 4:
        warnings.append({'level': 'warn', 'text': f'ASA {case.asa}: high anaesthetic risk; senior anaesthetist and a post-op HDU/ICU bed.'})
    allergies = list(case.patient.allergies.filter(status='active').values_list('substance', flat=True))
    return {'items': [{'key': k, 'label': l, 'na': na, 'value': pre.get(k, '')} for k, l, na in items], 'missing': missing,
            'complete': not missing, 'fasting': fast, 'labs': labs, 'warnings': warnings, 'allergies': allergies}


# ------------------------------------------------------------------ WHO checklist
def clean_phase(phase, raw):
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key, _, na in CHECKLIST[phase]['items']:
        v = raw.get(key)
        out[key] = v if v == 'yes' or (v == 'na' and na) else ''
    return out


def phase_done(case, phase):
    data = (case.checklist or {}).get(phase) or {}
    items = data.get('items') or {}
    return bool(data.get('at')) and all(items.get(k) in ANSWERS for k, _, _ in CHECKLIST[phase]['items'])


def save_phase(case, phase, raw, user, now=None, extra=None):
    """Record one phase of the WHO checklist. All items must be answered; it is signed with the user and time."""
    if phase not in CHECKLIST:
        raise ValidationError('Unknown checklist phase.')
    order = list(CHECKLIST)
    i = order.index(phase)
    if i and not phase_done(case, order[i - 1]):
        raise ValidationError(f'Complete “{CHECKLIST[order[i - 1]]["title"]}” first.')
    allowed = {'sign_in': ('ready', 'in_theatre'), 'time_out': ('in_theatre',), 'sign_out': ('operating',)}[phase]
    if case.status not in allowed:
        raise ValidationError(f'“{CHECKLIST[phase]["title"]}” is done {CHECKLIST[phase]["when"].lower()}.')
    items = clean_phase(phase, raw)
    missing = [label for key, label, _ in CHECKLIST[phase]['items'] if not items[key]]
    if missing:
        raise ValidationError('Answer every item before signing: ' + '; '.join(missing[:3]) + ('…' if len(missing) > 3 else ''))
    cl = dict(case.checklist or {})
    cl[phase] = {'items': items, 'at': (now or timezone.now()).isoformat(), 'by': user.get_full_name() or user.username, 'by_id': user.pk}
    extra = extra if isinstance(extra, dict) else {}
    if phase == 'time_out':
        t = _txt(extra.get('antibiotic_time'), 5)
        cl[phase]['antibiotic_time'] = t if len(t) == 5 and t[2] == ':' and t.replace(':', '').isdigit() else ''
    if phase == 'sign_out':
        cl[phase]['counts_note'] = _txt(extra.get('counts_note'), 200)
    case.checklist = cl
    return cl[phase]


# ------------------------------------------------------------------ scheduling
def clashes(case, room, start, minutes):
    """Bookings that overlap this one in the same room (with turnover), or for the same surgeon, anaesthetist or patient."""
    from .models import SurgicalCase
    if not start:
        return []
    end = start + timedelta(minutes=minutes)
    qs = SurgicalCase.objects.filter(status__in=BOOKED, scheduled_start__isnull=False,
                                     scheduled_start__lt=end + timedelta(minutes=TURNOVER_MIN),
                                     scheduled_start__gte=start - timedelta(hours=24)).select_related('room', 'patient')
    if case.pk:
        qs = qs.exclude(pk=case.pk)
    out = []
    for o in qs:
        o_end = o.scheduled_start + timedelta(minutes=o.est_minutes)
        if o_end + timedelta(minutes=TURNOVER_MIN) <= start:
            continue
        when = timezone.localtime(o.scheduled_start).strftime('%H:%M')
        if room and o.room_id == room.pk:
            out.append(f'{room} is booked from {when} for {o.title} ({o.number}), including {TURNOVER_MIN} min turnover.')
        overlap = o.scheduled_start < end and o_end > start
        if overlap and case.surgeon_id and o.surgeon_id == case.surgeon_id:
            out.append(f'The surgeon is already operating at {when} ({o.number}).')
        if overlap and case.anaesthetist_id and o.anaesthetist_id == case.anaesthetist_id:
            out.append(f'The anaesthetist is already in theatre at {when} ({o.number}).')
        if overlap and o.patient_id == case.encounter.patient_id:
            out.append(f'The patient already has {o.title} at {when} ({o.number}).')
    return out


# ------------------------------------------------------------------ recovery
def aldrete(obs, baseline_sbp=None):
    """Modified Aldrete score (0–10). Circulation and oxygen are worked out from the measured blood pressure and SpO2."""
    parts = {}
    for k in ('activity', 'respiration', 'consciousness'):
        v = obs.get(k)
        parts[k] = int(v) if v in (0, 1, 2) else None
    sbp, spo2 = obs.get('systolic'), obs.get('spo2')
    if sbp is not None and baseline_sbp:
        diff = abs(sbp - baseline_sbp) / baseline_sbp * 100
        parts['circulation'] = 2 if diff <= 20 else 1 if diff < 50 else 0
    else:
        parts['circulation'] = obs.get('circulation') if obs.get('circulation') in (0, 1, 2) else None
    if spo2 is not None:
        parts['oxygen'] = 2 if spo2 >= 92 and not obs.get('on_oxygen') else 1 if spo2 >= 90 else 0
    else:
        parts['oxygen'] = None
    known = [v for v in parts.values() if v is not None]
    total = sum(known) if len(known) == 5 else None
    return {'parts': parts, 'total': total, 'fit': total is not None and total >= 9}


def clean_recovery_obs(raw, baseline_sbp=None, now=None):
    raw = raw if isinstance(raw, dict) else {}

    def iv(k, lo, hi):
        x = _num(raw.get(k), lo, hi)
        return None if x is None else int(round(x))
    obs = {'at': (now or timezone.now()).isoformat(), 'heart_rate': iv('heart_rate', 20, 250), 'systolic': iv('systolic', 40, 260),
           'diastolic': iv('diastolic', 20, 160), 'spo2': iv('spo2', 50, 100), 'resp_rate': iv('resp_rate', 4, 60),
           'temperature_c': _num(raw.get('temperature_c'), 30, 43), 'pain': iv('pain', 0, 10), 'on_oxygen': bool(raw.get('on_oxygen')),
           'nausea': bool(raw.get('nausea')), 'activity': iv('activity', 0, 2), 'respiration': iv('respiration', 0, 2),
           'consciousness': iv('consciousness', 0, 2), 'circulation': iv('circulation', 0, 2)}
    if obs['temperature_c'] is not None:
        obs['temperature_c'] = round(obs['temperature_c'], 1)
    if obs['systolic'] is None and obs['spo2'] is None and obs['heart_rate'] is None:
        raise ValidationError('Enter at least the blood pressure, pulse or oxygen saturation.')
    score = aldrete(obs, baseline_sbp)
    obs['aldrete'] = score['total']
    obs['parts'] = score['parts']
    alerts = []
    if obs['spo2'] is not None and obs['spo2'] < 90:
        alerts.append('Oxygen saturation below 90%: airway, oxygen and call the anaesthetist.')
    if obs['systolic'] is not None and obs['systolic'] < 90:
        alerts.append('Systolic pressure below 90: look for bleeding; give fluids.')
    if obs['heart_rate'] is not None and obs['heart_rate'] > 120:
        alerts.append('Pulse above 120: pain, bleeding or low fluids?')
    if obs['pain'] is not None and obs['pain'] >= 7:
        alerts.append('Severe pain: give analgesia and reassess in 15 minutes.')
    if obs['temperature_c'] is not None and obs['temperature_c'] < 36:
        alerts.append('Temperature below 36 °C: warm the patient.')
    obs['alerts'] = alerts
    return obs


def baseline_sbp(case):
    try:
        return int(str((case.encounter.vitals or {}).get('bp', '')).split('/')[0])
    except (ValueError, IndexError):
        return None


# ------------------------------------------------------------------ moving along the pathway
def advance(case, to, user, *, reason='', discharge_to='', override='', now=None):
    """Move a case to the next state, checking the rules above. Saves the case and returns it."""
    now = now or timezone.now()
    if to not in TRANSITIONS.get(case.status, set()):
        raise ValidationError(f'A case that is “{case.get_status_display()}” cannot move to “{dict(case.STATUS).get(to, to)}”.')
    if to in ('cancelled', 'postponed'):
        if not _txt(reason):
            raise ValidationError('Give a reason.')
        case.cancel_reason = _txt(reason)
    if to == 'scheduled':
        if not case.room_id or not case.scheduled_start:
            raise ValidationError('Choose a theatre and a start time first.')
        found = clashes(case, case.room, case.scheduled_start, case.est_minutes)
        if found:
            raise ValidationError(found)
    if to == 'requested':
        case.scheduled_start = None
    if to == 'ready':
        r = readiness(case, now)
        if r['missing']:
            raise ValidationError('Pre-op checks still to do: ' + '; '.join(r['missing']))
    if to in PHASE_FOR and not phase_done(case, PHASE_FOR[to]):
        raise ValidationError(f'Complete the WHO “{CHECKLIST[PHASE_FOR[to]]["title"]}” first ({CHECKLIST[PHASE_FOR[to]]["when"].lower()}).')
    if to == 'recovery' and not (case.procedure_performed or '').strip():
        raise ValidationError('Write the operation note (at least the procedure performed) before the patient leaves theatre.')
    if to == 'completed':
        if discharge_to not in dict(case.DISCHARGE_TO) or not discharge_to:
            raise ValidationError('Choose where the patient goes from recovery.')
        last = (case.recovery or [None])[-1]
        if not (last and last.get('aldrete') is not None and last['aldrete'] >= 9) and not _txt(override):
            raise ValidationError('The last Aldrete score is below 9 (or not recorded). Record observations, or give a reason to discharge anyway.')
        case.discharge_to, case.discharge_override = discharge_to, _txt(override)
    stamp = {'in_theatre': ('in_room_at', 'anaesthesia_at'), 'operating': ('incision_at',), 'recovery': ('closure_at', 'out_room_at'),
             'completed': ('recovery_out_at',)}.get(to, ())
    for f in stamp:
        if not getattr(case, f):
            setattr(case, f, now)
    case.status = to
    case.save()
    return case


# ------------------------------------------------------------------ board
def _iso(dt):
    return timezone.localtime(dt).isoformat() if dt else None


def case_card(c):
    return {'id': c.pk, 'number': c.number, 'title': c.title, 'status': c.status, 'status_label': c.get_status_display(),
            'urgency': c.urgency, 'urgency_label': c.get_urgency_display().split(' · ')[0], 'specialty': c.get_specialty_display(),
            'patient': c.patient.full_name, 'mrn': c.patient.mrn, 'age': c.patient.age, 'sex': c.patient.sex,
            'room': c.room_id, 'start': _iso(c.scheduled_start), 'minutes': c.est_minutes,
            'surgeon': (c.surgeon.get_full_name() or c.surgeon.username) if c.surgeon_id else '',
            'anaesthesia': c.get_anaesthesia_display(), 'asa': c.asa,
            'times': {k: _iso(getattr(c, k)) for k in ('in_room_at', 'anaesthesia_at', 'incision_at', 'closure_at', 'out_room_at', 'recovery_out_at')},
            'checklist': {p: phase_done(c, p) for p in CHECKLIST}, 'url': f'/theatre/cases/{c.pk}/'}


def board(day, now=None):
    """Everything the theatre board draws for one day: rooms, cases on the timeline, the waiting list and the numbers."""
    from .models import OperatingRoom, SurgicalCase
    now = now or timezone.now()
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, datetime.min.time()), tz)
    end = start + timedelta(days=1)
    rooms = list(OperatingRoom.objects.filter(active=True))
    base = SurgicalCase.objects.select_related('patient', 'room', 'surgeon', 'encounter')
    cases = list(base.filter(scheduled_start__gte=start, scheduled_start__lt=end).exclude(status__in=['cancelled', 'requested', 'postponed']))
    if day == timezone.localdate(now):    # include anything still running from earlier (e.g. a long case past midnight)
        ids = {c.pk for c in cases}
        cases += [c for c in base.filter(status__in=ACTIVE) if c.pk not in ids]
    rank = {'immediate': 0, 'urgent': 1, 'expedited': 2, 'elective': 3}
    waiting = sorted(base.filter(status__in=['requested', 'postponed']), key=lambda c: (rank[c.urgency], c.created_at))
    session_min = {r.pk: max(60, (datetime.combine(day, r.session_end) - datetime.combine(day, r.session_start)).seconds // 60) for r in rooms}
    booked = {r.pk: sum(c.est_minutes for c in cases if c.room_id == r.pk) for r in rooms}
    done = [c for c in cases if c.status == 'completed']
    overruns = [c for c in cases if c.incision_at and c.status in ('operating',) and (now - c.in_room_at).total_seconds() / 60 > c.est_minutes * 1.25]
    cancelled_today = SurgicalCase.objects.filter(status='cancelled', scheduled_start__gte=start, scheduled_start__lt=end).count()
    return {
        'date': day.isoformat(), 'now': _iso(now),
        'rooms': [{'id': r.pk, 'name': r.name, 'kind': r.get_kind_display(), 'session': [r.session_start.strftime('%H:%M'), r.session_end.strftime('%H:%M')],
                   'utilisation': min(150, round(booked[r.pk] * 100 / session_min[r.pk]))} for r in rooms],
        'cases': [case_card(c) for c in sorted(cases, key=lambda c: c.scheduled_start or now)],
        'waiting': [dict(case_card(c), waited_h=round((now - c.created_at).total_seconds() / 3600, 1), reason=c.cancel_reason) for c in waiting],
        'kpi': {'booked': len(cases), 'active': sum(1 for c in cases if c.status in ACTIVE), 'done': len(done),
                'waiting': len(waiting), 'emergencies': sum(1 for c in waiting if c.urgency in ('immediate', 'urgent')),
                'cancelled': cancelled_today, 'overruns': len(overruns),
                'utilisation': round(sum(booked.values()) * 100 / max(1, sum(session_min.values())))},
    }


def billing_lines(case):
    """(category, description, quantity, unit price, source) for a case that has started, for capture_charges."""
    from .models import Tariff
    import math
    if case.status not in ('operating', 'recovery', 'completed'):
        return []
    out = []
    if case.procedure_type_id and case.procedure_type.price:
        out.append(('procedure', f'{case.title} · {case.number}', 1, case.procedure_type.price, f'surgery:{case.pk}'))
    t = Tariff.objects.filter(code=f'anaesthesia-{case.anaesthesia}', active=True).first()
    if t:
        out.append(('procedure', f'{t.name} · {case.number}', 1, t.amount, f'anaesthesia:{case.pk}'))
    t = Tariff.objects.filter(code='theatre-hour', active=True).first()
    if t and case.in_room_at and case.out_room_at:
        hours = max(1, math.ceil((case.out_room_at - case.in_room_at).total_seconds() / 3600))
        out.append(('procedure', f'{t.name} · {case.room or "theatre"} · {hours} h', hours, t.amount, f'theatre:{case.pk}'))
    return out


def catalogue():
    return {'checklist': {k: {'title': v['title'], 'when': v['when'], 'items': [{'key': a, 'label': b, 'na': c} for a, b, c in v['items']]}
                          for k, v in CHECKLIST.items()},
            'path': PATH, 'transitions': {k: sorted(v) for k, v in TRANSITIONS.items()}}


def active_count(day=None):
    """Cases for today that are not finished yet (for the navigation badge)."""
    from .models import SurgicalCase
    day = day or timezone.localdate()
    return SurgicalCase.objects.filter(Q(status__in=ACTIVE) | Q(status__in=['scheduled', 'ready'], scheduled_start__date=day)).count()
