"""Everything a ward page needs, computed in one place so the ward page, the overview, the printed handover sheet and the
nurses' station screen always agree.

Per bed: the patient, length of stay, latest observations with their NEWS2 score, when the next observations are due
(by NEWS2: score 0 → 12-hourly, 1–4 → 4-hourly, a single 3 or 5–6 → hourly, 7+ → every 15 minutes), medicines late
today, pending lab requests, allergies, and whether the patient fits the ward (sex, age group).
"""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

OBS_INTERVAL = {'high': 15, 'medium': 60, 'low-medium': 60}      # minutes; low risk: 12 h if 0, else 4 h
LONG_STAY_DAYS = 7
CLEANING_SLOW_HOURS = 2
ACUITY = [('critical', 'NEWS2 7+'), ('urgent', 'NEWS2 5–6 or a single 3'), ('watch', 'NEWS2 1–4'), ('stable', 'NEWS2 0'), ('unknown', 'No observations yet')]


def _dur(mins):
    return f'{mins} min' if mins < 60 else f'{mins // 60} h {mins % 60:02d}' if mins < 24 * 60 else f'{mins // 1440} d'


def obs_interval(score):
    if not score:
        return 12 * 60 if score == 0 else None
    return OBS_INTERVAL.get(score['risk']) or (12 * 60 if score['total'] == 0 else 4 * 60)


def acuity(score):
    if score is None:
        return 'unknown'
    return {'high': 'critical', 'medium': 'urgent', 'low-medium': 'urgent'}.get(score['risk'], 'stable' if score['total'] == 0 else 'watch')


def fit(ward, patient):
    """Reasons the patient does not fit the ward's policy (shown, never enforced: the nurse in charge decides)."""
    out = []
    if ward.sex_policy == 'female' and patient.sex == 'M':
        out.append('Man on a women-only ward')
    if ward.sex_policy == 'male' and patient.sex == 'F':
        out.append('Woman on a men-only ward')
    age = patient.age
    if age is not None:
        if ward.age_group == 'adult' and age < 16:
            out.append(f'Child ({age} y) on an adult ward')
        if ward.age_group == 'children' and age >= 16:
            out.append(f'Adult ({age} y) on a children\'s ward')
        if ward.age_group == 'neonates' and age >= 1:
            out.append('Not a newborn')
    return out


def visiting(ward, now=None):
    """{'state': 'open'|'soon'|'closed'|'none', 'label'}"""
    if not (ward.visiting_from and ward.visiting_to):
        return {'state': 'none', 'label': 'Visiting hours not set'}
    t = timezone.localtime(now or timezone.now())
    cur = t.time()
    f, to = ward.visiting_from, ward.visiting_to
    is_open = f <= cur < to if f < to else (cur >= f or cur < to)
    if is_open:
        return {'state': 'open', 'label': f'Visiting now · until {to:%H:%M}'}
    start = t.replace(hour=f.hour, minute=f.minute, second=0, microsecond=0)
    if start < t:
        start += timedelta(days=1)
    mins = int((start - t).total_seconds() // 60)
    if mins <= 90:
        return {'state': 'soon', 'label': f'Visiting opens in {mins} min ({f:%H:%M})'}
    return {'state': 'closed', 'label': f'Visiting {f:%H:%M}–{to:%H:%M}'}


def _late_meds(patient, since):
    from .views import medication_chart
    try:
        _, counts = medication_chart(patient, since)
        return counts.get('late', 0), counts.get('due', 0)
    except Exception:
        return 0, 0


def snapshot(ward, *, light=False):
    """The ward right now. light=True skips the per-patient medicine chart (for the overview of all wards)."""
    from .bedside import news2
    from .models import Admission, Allergy, BedsideObservation, LabOrder
    now = timezone.now()
    beds = sorted(ward.bed_set.all(), key=lambda b: b.code)
    adms = {a.bed_id: a for a in Admission.objects.filter(bed__ward=ward, discharged_at__isnull=True)
            .select_related('encounter__patient', 'encounter__clinician')}
    latest = {}
    for o in BedsideObservation.objects.filter(admission__in=adms.values()).order_by('admission_id', '-taken_at'):
        latest.setdefault(o.admission_id, o)
    patients = [a.encounter.patient_id for a in adms.values()]
    allergies = dict(Allergy.objects.filter(patient_id__in=patients, status='active').values_list('patient_id').annotate(n=Count('id')))
    labs = dict(LabOrder.objects.filter(encounter__patient_id__in=patients, status__in=['ordered', 'collected', 'processing'])
                .values_list('encounter__patient_id').annotate(n=Count('request', distinct=True)))
    rows = []
    for b in beds:
        a = adms.get(b.pk)
        r = {'bed': b, 'a': a}
        if a:
            p = a.encounter.patient
            o = latest.get(a.pk)
            score = news2(o.as_dict()) if o else None
            iv = obs_interval(score)
            due = (o.taken_at + timedelta(minutes=iv)) if (o and iv) else (a.admitted_at + timedelta(hours=1))
            late, med_due = (0, 0) if light else _late_meds(p, a.admitted_at)
            stay = (now - a.admitted_at).total_seconds() / 86400
            mins = int((due - now).total_seconds() // 60)
            label = ('none yet' if not o else f'{_dur(-mins)} late') if mins < 0 else f'in {_dur(mins)}'
            r.update({'p': p, 'obs': o, 'news': score, 'acuity': acuity(score), 'obs_due': due, 'obs_overdue': due < now,
                      'obs_due_min': mins, 'obs_label': label, 'meds_late': late, 'meds_due': med_due,
                      'labs': labs.get(p.pk, 0), 'allergies': allergies.get(p.pk, 0), 'stay_days': stay, 'long_stay': stay >= LONG_STAY_DAYS,
                      'misfit': fit(ward, p), 'clinician': a.encounter.clinician})
        else:
            idle = (now - b.updated_at).total_seconds() / 3600 if b.updated_at else 0
            r.update({'idle_hours': idle, 'slow_clean': b.state == 'cleaning' and idle >= CLEANING_SLOW_HOURS})
        rows.append(r)
    occ = [r for r in rows if r['a']]
    total = len(beds)
    stats = {'total': total, 'occupied': len(occ), 'free': sum(r['bed'].state == 'available' for r in rows),
             'cleaning': sum(r['bed'].state == 'cleaning' for r in rows), 'maintenance': sum(r['bed'].state == 'maintenance' for r in rows),
             'pct': round(len(occ) * 100 / total) if total else 0,
             'avg_stay': round(sum(r['stay_days'] for r in occ) / len(occ), 1) if occ else None,
             'acuity': {k: sum(r.get('acuity') == k for r in occ) for k, _ in ACUITY},
             'overdue': sum(r['obs_overdue'] for r in occ), 'meds_late': sum(r['meds_late'] for r in occ),
             'female': sum(r['p'].sex == 'F' for r in occ), 'male': sum(r['p'].sex == 'M' for r in occ)}
    return {'ward': ward, 'rows': rows, 'stats': stats, 'attention': attention(rows), 'visiting': visiting(ward)}


def attention(rows):
    """What needs someone now, most urgent first."""
    out = []
    for r in rows:
        b = r['bed']
        if r['a']:
            p, s = r['p'], r['news']
            if s and s['risk'] in ('high', 'medium', 'low-medium'):
                out.append((0 if s['risk'] == 'high' else 1, 'red' if s['risk'] == 'high' else 'amber', 'bi-activity', b, p, f'NEWS2 {s["total"]} · {s["response"]}'))
            if r['obs_overdue']:
                out.append((2, 'amber', 'bi-alarm', b, p, f'Observations {r["obs_label"]}' if r['obs'] else 'No observations since admission'))
            if r['meds_late']:
                out.append((2, 'amber', 'bi-capsule', b, p, f'{r["meds_late"]} medicine dose{"s" if r["meds_late"] != 1 else ""} late'))
            for m in r['misfit']:
                out.append((3, 'plum', 'bi-signpost-split', b, p, m))
            if r['long_stay']:
                out.append((4, 'indigo', 'bi-calendar2-week', b, p, f'In hospital {r["stay_days"]:.0f} days: discharge plan?'))
        elif r.get('slow_clean'):
            out.append((3, 'amber', 'bi-stars', b, None, f'Cleaning for {r["idle_hours"]:.0f} h: bed not back in use'))
    out.sort(key=lambda x: x[0])
    return [{'tone': t, 'icon': i, 'bed': b, 'p': p, 'text': txt} for _, t, i, b, p, txt in out]


def history(ward, days=14):
    """Daily occupied beds, admissions and discharges for the chart."""
    from .models import Admission
    now = timezone.now()
    start = timezone.make_aware(timezone.datetime.combine(timezone.localdate() - timedelta(days=days - 1), timezone.datetime.min.time()))
    adms = list(Admission.objects.filter(bed__ward=ward).filter(Q(discharged_at__isnull=True) | Q(discharged_at__gte=start))
                .values_list('admitted_at', 'discharged_at'))
    total = ward.bed_set.count() or 1
    out = []
    for i in range(days):
        d0 = start + timedelta(days=i)
        d1 = d0 + timedelta(days=1)
        occ = sum(1 for a, d in adms if a < d1 and (d or now) > d0)
        out.append({'date': d0, 'occupied': occ, 'pct': round(occ * 100 / total), 'in': sum(1 for a, _ in adms if d0 <= a < d1),
                    'out': sum(1 for _, d in adms if d and d0 <= d < d1)})
    return out


def today_moves(ward):
    from .models import Admission
    d0 = timezone.make_aware(timezone.datetime.combine(timezone.localdate(), timezone.datetime.min.time()))
    qs = Admission.objects.filter(bed__ward=ward)
    return {'admitted': qs.filter(admitted_at__gte=d0).count(), 'discharged': qs.filter(discharged_at__gte=d0).count()}


def bulk_beds(ward, count, kind, prefix=''):
    """Add beds with the next free codes, e.g. MW-07, MW-08 …"""
    import re

    from .models import Bed
    prefix = (prefix or ward.short).upper()[:12]
    used = set(Bed.objects.values_list('code', flat=True))
    nums = [int(m.group(1)) for c in used for m in [re.match(rf'^{re.escape(prefix)}-(\d+)$', c)] if m]
    n, made = (max(nums) if nums else 0), []
    while len(made) < count:
        n += 1
        code = f'{prefix}-{n:02d}'
        if code not in used:
            made.append(Bed.objects.create(ward=ward, code=code, kind=kind))
    return made
