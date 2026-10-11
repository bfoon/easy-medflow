"""Hospital health intelligence: aggregate, anonymous indicators for planning and public-health decisions.

Everything here is counts and rates over groups of patients; no individual is identifiable from the output.
"""
from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .services import _diagnosis_term

ANTIBIOTICS = ('amoxicillin', 'ceftriaxone', 'ciprofloxacin', 'azithromycin', 'co-trimoxazole', 'metronidazole', 'doxycycline')
LABELS = {'malaria': 'Malaria', 'respiratory': 'Respiratory infection', 'pneumonia': 'Pneumonia', 'gastroenteritis': 'Gastroenteritis',
          'hypertension': 'Hypertension', 'diabetes': 'Diabetes', 'urinary': 'Urinary infection', 'anaemia': 'Anaemia', 'gastritis': 'Gastritis',
          'pregnancy': 'Antenatal', 'febrile': 'Febrile illness', 'dehydration': 'Dehydration', 'coronary': 'Heart disease', 'typhoid': 'Typhoid',
          'tuberculosis': 'Tuberculosis', 'meningitis': 'Meningitis', 'cholelithiasis': 'Gallstones', 'eclampsia': 'Pre-eclampsia', 'operative': 'Post-operative care', 'iron': 'Iron-deficiency anaemia', 'ischaemic': 'Stroke', 'absence': 'Epilepsy'}


def _label(term):
    return LABELS.get(term, term.capitalize())


def _age_band(p, on):
    if not p.dob:
        return None
    a = on.year - p.dob.year - ((on.month, on.day) < (p.dob.month, p.dob.day))
    return min(a // 10, 8)          # 0-9 … 80+


def health_data(days=90):
    from .models import Admission, Bed, Encounter, LabResultValue, PrescriptionItem, QueueTicket
    now = timezone.now()
    since = now - timedelta(days=days)
    encs = list(Encounter.objects.filter(created_at__gte=since).select_related('patient__location__parent').prefetch_related('prescriptions__items__medication'))
    weeks = max(4, days // 7)
    week_start = lambda dt: (timezone.localtime(dt).date() - timedelta(days=timezone.localtime(dt).weekday()))
    week_keys = sorted({week_start(now - timedelta(weeks=i)) for i in range(weeks)})

    # ---------------- diagnoses and weekly trends
    by_term, weekly = Counter(), defaultdict(Counter)
    for e in encs:
        t = _diagnosis_term(e.diagnosis)
        if t:
            by_term[t] += 1
            weekly[t][week_start(e.created_at)] += 1
    top = [t for t, _ in by_term.most_common(8)]
    diagnoses = [{'key': t, 'label': _label(t), 'n': by_term[t], 'series': [weekly[t].get(w, 0) for w in week_keys]} for t in top]

    # ---------------- outbreak signals: last 7 days against the average week before it
    signals = []
    for t in top:
        recent = sum(1 for e in encs if _diagnosis_term(e.diagnosis) == t and e.created_at >= now - timedelta(days=7))
        prior = [sum(1 for e in encs if _diagnosis_term(e.diagnosis) == t and now - timedelta(days=7 * (k + 1)) <= e.created_at < now - timedelta(days=7 * k)) for k in range(1, 5)]
        base = sum(prior) / 4
        if recent >= 1.6 * max(base, 1) and recent - base >= 6:   # a real jump, not noise
            signals.append({'label': _label(t), 'recent': recent, 'baseline': round(base, 1), 'change': round((recent - base) * 100 / max(base, 1))})

    # ---------------- malaria test positivity per week
    rdt = list(LabResultValue.objects.filter(parameter__code='RDT', order__resulted_at__gte=since).values_list('flag', 'order__resulted_at'))
    pos_w, tot_w = Counter(), Counter()
    for flag, at in rdt:
        if at:
            tot_w[week_start(at)] += 1
            pos_w[week_start(at)] += flag == 'A'
    positivity = [round(pos_w[w] * 100 / tot_w[w]) if tot_w[w] else None for w in week_keys]

    # ---------------- who we see: age/sex pyramid and towns
    seen = {e.patient_id: e for e in encs}
    pyramid = {'M': [0] * 9, 'F': [0] * 9}
    towns, malaria_towns = Counter(), defaultdict(set)
    for e in seen.values():
        b = _age_band(e.patient, timezone.localtime(e.created_at).date())
        if b is not None and e.patient.sex in pyramid:
            pyramid[e.patient.sex][b] += 1
        towns[_town(e.patient)] += 1
    for e in encs:
        if _diagnosis_term(e.diagnosis) == 'malaria':
            malaria_towns[_town(e.patient)].add(e.patient_id)   # people, not visits
    town_rows = [{'town': t, 'patients': n, 'malaria': len(malaria_towns.get(t, ()))} for t, n in towns.most_common(10)]

    # ---------------- outcomes and antibiotic use
    outcome = []
    for t in top[:6]:
        done = [e for e in encs if _diagnosis_term(e.diagnosis) == t and e.outcome]
        if len(done) >= 3:
            ok = sum(e.outcome in ('resolved', 'improved') for e in done)
            outcome.append({'label': _label(t), 'n': len(done), 'rate': round(ok * 100 / len(done))})
    with_rx = [e for e in encs if any(rx.state != 'cancelled' for rx in e.prescriptions.all())]
    abx = lambda e: any(any(a in i.medication.name.lower() for a in ANTIBIOTICS) for rx in e.prescriptions.all() for i in rx.items.all())
    abx_rate = round(sum(abx(e) for e in with_rx) * 100 / len(with_rx)) if with_rx else 0
    resp = [e for e in with_rx if _diagnosis_term(e.diagnosis) in ('respiratory',)]
    resp_abx = round(sum(abx(e) for e in resp) * 100 / len(resp)) if resp else None

    # ---------------- operations
    tickets = list(QueueTicket.objects.filter(created_at__gte=now - timedelta(days=14), called_at__isnull=False).values_list('created_at', 'called_at'))
    wait_by_day = defaultdict(list)
    for c, k in tickets:
        wait_by_day[timezone.localtime(c).date()].append((k - c).total_seconds() / 60)
    wait_days = [timezone.localdate() - timedelta(days=i) for i in range(13, -1, -1)]
    waits = [round(sum(wait_by_day[d]) / len(wait_by_day[d])) if wait_by_day[d] else None for d in wait_days]
    beds_total, beds_occ = Bed.objects.count(), Bed.objects.filter(state='occupied').count()
    adm_w = Counter(week_start(a) for a in Admission.objects.filter(admitted_at__gte=since).values_list('admitted_at', flat=True))

    # ---------------- chronic disease control
    a1c = {}
    for pid, val in LabResultValue.objects.filter(parameter__code='A1C', value_number__isnull=False).order_by('order__resulted_at').values_list('order__encounter__patient_id', 'value_number'):
        a1c[pid] = float(val)            # latest per patient
    controlled = sum(v < 7 for v in a1c.values())
    from .models import Condition
    chronic = {'hypertension': Condition.objects.filter(status='active', name__icontains='hypertension').count(),
               'diabetes': Condition.objects.filter(status='active', name__icontains='diabet').count(),
               'a1c_tested': len(a1c), 'a1c_controlled': controlled}

    # ---------------- advice generated from the indicators
    advice = []
    for s in signals:
        advice.append({'level': 'danger', 'title': f'{s["label"]} rising', 'text': f'{s["recent"]} cases in the last 7 days against about {s["baseline"]} a week before (+{s["change"]}%). Check stock of tests and treatment, alert community health workers, and consider notifying the regional health team.'})
    recent_pos = [p for p in positivity[-3:] if p is not None]
    if recent_pos and sum(recent_pos) / len(recent_pos) >= 40:
        top_town = sorted(((t, len(p)) for t, p in malaria_towns.items()), key=lambda x: -x[1])[:1]
        advice.append({'level': 'warn', 'title': 'High malaria test positivity', 'text': f'About {round(sum(recent_pos) / len(recent_pos))}% of recent malaria tests are positive' + (f', most cases from {top_town[0][0]}' if top_town else '') + '. Bed-net distribution and indoor spraying in hotspot areas are the main levers.'})
    if resp_abx is not None and resp_abx >= 40:
        advice.append({'level': 'warn', 'title': 'Antibiotics for respiratory infections', 'text': f'{resp_abx}% of respiratory infection visits received an antibiotic, although most are viral. A prescribing review and patient information could reduce resistance and cost.'})
    if beds_total and beds_occ / beds_total >= .85:
        advice.append({'level': 'warn', 'title': 'Beds nearly full', 'text': f'{round(beds_occ * 100 / beds_total)}% of beds are occupied. Review discharges early in the day and plan surge capacity.'})
    recent_wait = [w for w in waits[-3:] if w is not None]
    if recent_wait and sum(recent_wait) / len(recent_wait) >= 45:
        advice.append({'level': 'info', 'title': 'Long waits', 'text': f'Average wait to be called is about {round(sum(recent_wait) / len(recent_wait))} minutes in the last 3 days. Consider adding a clinician at peak hours.'})
    if chronic['a1c_tested'] >= 3 and controlled / chronic['a1c_tested'] < .5:
        advice.append({'level': 'info', 'title': 'Diabetes control', 'text': f'Only {controlled} of {chronic["a1c_tested"]} patients with an HbA1c are below 7%. A diabetes clinic with regular follow-up could improve control.'})
    if not advice:
        advice.append({'level': 'ok', 'title': 'No unusual patterns', 'text': 'Indicators are within their usual range for this period.'})

    return {
        'days': days, 'weeks': [w.strftime('%d %b') for w in week_keys], 'visits': len(encs), 'patients': len(seen),
        'diagnoses': diagnoses, 'signals': signals, 'positivity': positivity, 'rdt_total': len(rdt),
        'pyramid': pyramid, 'towns': town_rows, 'town_map': [{'town': t, 'n': n, 'all': n, 'xy': TOWN_COORDS.get(t)} for t, n in towns.most_common(15)], 'outcomes': outcome, 'abx_rate': abx_rate, 'resp_abx': resp_abx,
        'waits': waits, 'wait_days': [d.strftime('%a %d') for d in wait_days], 'beds': {'total': beds_total, 'occupied': beds_occ},
        'admissions': [adm_w.get(w, 0) for w in week_keys], 'chronic': chronic, 'advice': advice,
    }


# ------------------------------------------------------------------ drill-down explorer
TOWN_COORDS = {   # approximate (longitude, latitude), for a stylised map only
    'Banjul': (-16.58, 13.45), 'Serrekunda': (-16.68, 13.43), 'Bakau': (-16.68, 13.48), 'Kololi': (-16.72, 13.45), 'Lamin': (-16.63, 13.37),
    'Brikama': (-16.65, 13.27), 'Gunjur': (-16.75, 13.18), 'Farafenni': (-15.60, 13.57), 'Soma': (-15.53, 13.44), 'Basse': (-14.21, 13.31),
    'Kerewan': (-16.09, 13.49), 'Janjanbureh': (-14.77, 13.54), 'Mansa Konko': (-15.54, 13.47), 'Kuntaur': (-14.89, 13.67), 'Essau': (-16.53, 13.48),
}
AGE_BANDS = ['0–9', '10–19', '20–29', '30–39', '40–49', '50–59', '60–69', '70–79', '80+']


def _town(p):
    """The patient's town: from their linked location (an area counts towards its town), else the end of the address."""
    if p.location_id:
        return p.location.town.name
    return p.address.split(',')[-1].strip() if p.address and ',' in p.address else 'Unknown'


def location_points(encs_in_group, all_encs):
    """Map points: one per linked location, with patients in the group and in total."""
    grp, tot, locs = defaultdict(set), defaultdict(set), {}
    for e in all_encs:
        if e.patient.location_id:
            tot[e.patient.location_id].add(e.patient_id); locs[e.patient.location_id] = e.patient.location
    for e in encs_in_group:
        if e.patient.location_id:
            grp[e.patient.location_id].add(e.patient_id)
    return [{'name': l.name, 'label': str(l), 'town': l.town.name, 'region': l.get_region_display(), 'lat': float(l.latitude), 'lon': float(l.longitude),
             'n': len(grp[lid]), 'all': len(tot[lid])} for lid, l in locs.items() if grp[lid]]


def explore_data(days=90, dx='', town='', age='', sex=''):
    """Indicators for any slice of the population: by diagnosis, town, age band and sex."""
    from .models import Encounter, LabResultValue
    now = timezone.now()
    since = now - timedelta(days=days)
    allenc = list(Encounter.objects.filter(created_at__gte=since).select_related('patient__location__parent')
                  .prefetch_related('prescriptions__items__medication', 'labs__test', 'admissions'))
    def keep(e, skip=None):
        if dx and skip != 'dx' and _diagnosis_term(e.diagnosis) != dx: return False
        if town and skip != 'town' and _town(e.patient) != town: return False
        if age != '' and skip != 'age' and _age_band(e.patient, timezone.localtime(e.created_at).date()) != int(age): return False
        if sex and skip != 'sex' and e.patient.sex != sex: return False
        return True
    encs = [e for e in allenc if keep(e)]
    week_start = lambda dt: (timezone.localtime(dt).date() - timedelta(days=timezone.localtime(dt).weekday()))
    weeks = sorted({week_start(now - timedelta(weeks=i)) for i in range(max(4, days // 7))})
    wk, wk_all = Counter(week_start(e.created_at) for e in encs), Counter(week_start(e.created_at) for e in allenc)
    daily = Counter(timezone.localtime(e.created_at).date().isoformat() for e in encs)
    hours = Counter(timezone.localtime(e.created_at).hour for e in encs)
    # demographics and places (each computed ignoring its own filter, so you can see the alternatives)
    pyramid = {'M': [0] * 9, 'F': [0] * 9}
    for e in {e.patient_id: e for e in allenc if keep(e, 'age') and keep(e, 'sex')}.values():
        b = _age_band(e.patient, timezone.localtime(e.created_at).date())
        if b is not None and e.patient.sex in pyramid:
            pyramid[e.patient.sex][b] += 1
    town_pat, town_all = defaultdict(set), defaultdict(set)
    for e in allenc:
        if keep(e, 'town'):
            town_pat[_town(e.patient)].add(e.patient_id)
        town_all[_town(e.patient)].add(e.patient_id)
    towns = [{'town': t, 'n': len(p), 'all': len(town_all[t]), 'xy': TOWN_COORDS.get(t)} for t, p in sorted(town_pat.items(), key=lambda x: -len(x[1]))]
    dx_mix = Counter(_diagnosis_term(e.diagnosis) for e in allenc if keep(e, 'dx') and _diagnosis_term(e.diagnosis))
    # outcomes, treatments, tests
    outcomes = Counter(e.outcome for e in encs if e.outcome)
    meds, med_ok = Counter(), Counter()
    for e in encs:
        names = {str(i.medication) for rx in e.prescriptions.all() if rx.state != 'cancelled' for i in rx.items.all()}
        for n in names:
            meds[n] += 1
            med_ok[n] += e.outcome in ('resolved', 'improved')
    with_outcome = Counter(str(i.medication) for e in encs if e.outcome for rx in e.prescriptions.all() for i in rx.items.all())
    tests = Counter(o.test.name for e in encs for o in e.labs.all() if o.status != 'cancelled')
    ids = [e.pk for e in encs]
    rdt = list(LabResultValue.objects.filter(parameter__code='RDT', order__encounter_id__in=ids).values_list('flag', 'order__resulted_at'))
    pos, tot = Counter(), Counter()
    for f, at in rdt:
        if at:
            tot[week_start(at)] += 1; pos[week_start(at)] += f == 'A'
    adm = [a for e in encs for a in e.admissions.all()]
    los = [((a.discharged_at or now) - a.admitted_at).total_seconds() / 86400 for a in adm]
    ok = sum(outcomes[k] for k in ('resolved', 'improved'))
    return {
        'filters': {'days': days, 'dx': dx, 'dx_label': _label(dx) if dx else '', 'town': town, 'age': age, 'age_label': AGE_BANDS[int(age)] if age != '' else '', 'sex': sex},
        'summary': {'visits': len(encs), 'patients': len({e.patient_id for e in encs}), 'share': round(len(encs) * 100 / len(allenc)) if allenc else 0,
                    'admitted': len(adm), 'los': round(sum(los) / len(los), 1) if los else None,
                    'improved': round(ok * 100 / sum(outcomes.values())) if outcomes else None,
                    'positivity': round(sum(pos.values()) * 100 / sum(tot.values())) if tot else None},
        'weeks': [w.strftime('%d %b') for w in weeks], 'weekly': [wk.get(w, 0) for w in weeks], 'weekly_all': [wk_all.get(w, 0) for w in weeks],
        'positivity': [round(pos[w] * 100 / tot[w]) if tot[w] else None for w in weeks],
        'daily': daily, 'start': (timezone.localdate() - timedelta(days=days - 1)).isoformat(), 'hours': [hours.get(h, 0) for h in range(24)],
        'pyramid': pyramid, 'bands': AGE_BANDS, 'towns': towns,
        'dx_mix': [{'key': k, 'label': _label(k), 'n': n} for k, n in dx_mix.most_common(12)],
        'outcomes': [{'key': k, 'label': {'resolved': 'Resolved', 'improved': 'Improved', 'no_change': 'No change', 'worsened': 'Worsened', 'referred': 'Referred'}[k], 'n': outcomes[k]}
                     for k in ('resolved', 'improved', 'no_change', 'worsened', 'referred') if outcomes[k]],
        'meds': [{'name': n, 'n': c, 'success': round(med_ok[n] * 100 / with_outcome[n]) if with_outcome[n] else None} for n, c in meds.most_common(10)],
        'tests': [{'name': n, 'n': c} for n, c in tests.most_common(8)],
        'points': location_points(encs, allenc),
    }
