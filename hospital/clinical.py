"""Clinical decision support.

Three layers, all advisory and all requiring clinician judgement:
  1. Allergy screening by drug class, not just by name (a penicillin allergy flags amoxicillin).
  2. Rule-based safety review: risky medicine/result combinations, missing work-up, results that do not fit the diagnosis.
  3. Suggestions from this hospital's own completed visits (anonymous aggregates, small groups hidden).

`deidentified_context()` builds the minimum-necessary, de-identified view of a visit that a future AI service may
receive. `ai_review()` calls that service only when it is configured; until then the rule-based review stands alone.
"""
import re
from datetime import timedelta

from django.utils import timezone

DISCLAIMER = ('Decision support only. These checks are rule-based and incomplete; they do not replace clinical '
              'judgement, local guidelines or pharmacist review.')

# ------------------------------------------------------------------ allergy classes
DRUG_CLASSES = {
    'penicillin': ['penicillin', 'amoxicillin', 'ampicillin', 'co-amoxiclav', 'flucloxacillin', 'benzylpenicillin', 'cloxacillin'],
    'cephalosporin': ['ceftriaxone', 'cefuroxime', 'cefalexin', 'cephalexin', 'cefixime', 'cefotaxime'],
    'nsaid': ['ibuprofen', 'aspirin', 'diclofenac', 'naproxen', 'indometacin', 'acetylsalicylic'],
    'sulfonamide': ['sulfonamide', 'sulfamethoxazole', 'co-trimoxazole', 'cotrimoxazole', 'sulfadoxine', 'sulfa'],
    'artemisinin': ['artemether', 'lumefantrine', 'artesunate', 'artemisinin'],
    'macrolide': ['erythromycin', 'azithromycin', 'clarithromycin'],
}
# Allergy to the first class means caution (not certainty) with the second.
CROSS_REACTIVE = {'penicillin': ['cephalosporin']}


def _classes_of(text):
    t = (text or '').casefold()
    return {cls for cls, members in DRUG_CLASSES.items() if cls in t or any(m in t for m in members)}


def allergy_matches(allergies, medication):
    """Match a medicine against documented allergies: same name, same drug class, or known cross-reactivity."""
    names = f'{medication.name} {medication.generic_name}'.casefold()
    med_classes = _classes_of(names)
    hits, cautions = [], []
    for a in allergies:
        sub = (a.get('substance') or '').strip()
        if not sub:
            continue
        sub_cf, allergy_classes = sub.casefold(), _classes_of(sub)
        if sub_cf in names or any(w in names for w in sub_cf.split() if len(w) > 4):
            hits.append({**a, 'match': 'name', 'note': f'{medication.name} matches the recorded allergy to {sub}.'})
        elif allergy_classes & med_classes:
            cls = sorted(allergy_classes & med_classes)[0]
            hits.append({**a, 'match': 'class', 'note': f'{medication.name} is a {cls}; the patient is allergic to {sub} (same class).'})
        else:
            for ac in allergy_classes:
                for cross in CROSS_REACTIVE.get(ac, []):
                    if cross in med_classes:
                        cautions.append({**a, 'match': 'cross', 'note': f'{medication.name} is a {cross}. Some patients allergic to {sub} ({ac}) react to it; check the reaction type.'})
    return hits, cautions


# ------------------------------------------------------------------ helpers
CARDIAC_TERMS = ('coronary', 'acs', 'myocard', 'cardiac', 'heart', 'angina', 'stemi', 'infarct')
FLAG_BAD = {'H', 'L', 'HH', 'LL', 'A'}


def _latest_values(patient, days=120):
    from .models import LabResultValue
    out = {}
    for v in (LabResultValue.objects.filter(order__encounter__patient=patient, order__status__in=['resulted', 'verified'],
                                            order__resulted_at__gte=timezone.now() - timedelta(days=days))
              .select_related('parameter').order_by('order__resulted_at')):
        out[v.parameter.code] = v                     # later results overwrite earlier ones
    return out


def _finding(level, kind, title, detail, actions=None):
    return {'level': level, 'kind': kind, 'title': title, 'detail': detail, 'actions': actions or []}


def _has(text, *words):
    t = (text or '').lower()
    return any(w in t for w in words)


# ------------------------------------------------------------------ rule-based review
def clinical_review(encounter, proposed_meds=(), proposed_tests=()):
    """Return a list of findings for this visit, including medicines and tests being added right now."""
    from django.urls import reverse
    from .models import LabTest, PrescriptionItem
    p = encounter.patient
    dx = f'{encounter.diagnosis} {encounter.reason}'
    conditions = ' '.join(p.conditions.filter(status='active').values_list('name', flat=True))
    allergies = list(p.allergies.filter(status='active').values('substance', 'reaction', 'severity'))
    vals = _latest_values(p)
    flag = lambda c: vals[c].flag if c in vals else ''
    shown = lambda c: f'{vals[c].display} {vals[c].parameter.unit}'.strip() if c in vals else ''
    current = list(PrescriptionItem.objects.filter(prescription__encounter__patient=p, prescription__state__in=['draft', 'signed', 'partial', 'dispensed'],
                                                   prescription__created_at__gte=timezone.now() - timedelta(days=30)).select_related('medication'))
    meds = {i.medication.pk: i.medication for i in current}
    meds.update({m.pk: m for m in proposed_meds})
    ordered = set(encounter.labs.exclude(status='cancelled').values_list('test__code', flat=True)) | {t.code for t in proposed_tests}
    recent_tests = ordered | set(vals.keys()) | set(LabTest.objects.filter(laborder__encounter__patient=p, laborder__created_at__gte=timezone.now() - timedelta(days=90)).values_list('code', flat=True))
    lab_url = reverse('lab_new') + f'?encounter={encounter.pk}'
    F = []

    # 1. allergies, by name and by class
    for m in meds.values():
        hits, cautions = allergy_matches(allergies, m)
        for h in hits:
            F.append(_finding('danger', 'allergy', f'Allergy: {m.name}', h['note'] + (f" Reaction recorded: {h['reaction']} ({h['severity']})." if h.get('reaction') else '')))
        for c in cautions:
            F.append(_finding('warn', 'allergy', f'Possible cross-reaction: {m.name}', c['note']))
    # 2. medicine + result / condition combinations
    names = {m.name.lower(): m for m in meds.values()}
    if 'metformin' in names and flag('CREA') in ('H', 'HH'):
        F.append(_finding('warn', 'contra', 'Metformin with raised creatinine', f'Creatinine {shown("CREA")}. Check eGFR: reduce the dose below 45 and stop below 30 mL/min/1.73m².'))
    nsaids = [n for n in names if _classes_of(n) & {'nsaid'}]
    if nsaids and (flag('CREA') in ('H', 'HH') or flag('K') in ('H', 'HH')):
        F.append(_finding('warn', 'contra', f'{names[nsaids[0]].name} with abnormal kidney results', 'NSAIDs can worsen kidney function and raise potassium. Prefer paracetamol.'))
    risky = [w for w in ('hypertension', 'heart failure', 'pregnancy', 'peptic ulcer') if _has(conditions + ' ' + dx, w.split()[0][:7])]
    if nsaids and risky:
        F.append(_finding('warn', 'contra', f'{names[nsaids[0]].name} with {" and ".join(risky)}', 'NSAIDs raise blood pressure, worsen heart failure and are avoided in later pregnancy and peptic ulcer disease.'))
    if 'amoxicillin' in names and _has(dx, 'upper respiratory', 'urti', 'common cold', 'viral'):
        F.append(_finding('info', 'stewardship', 'Antibiotic for a likely viral infection', 'Most upper respiratory infections are viral and resolve without antibiotics. Check the similar-cases outcomes before prescribing.'))
    # 3. critical results that nobody has looked at
    for code, v in vals.items():
        if v.flag in ('HH', 'LL') and not v.acknowledged_at:
            F.append(_finding('danger', 'result', f'Critical {v.parameter.name}: {shown(code)}', 'Not yet marked reviewed. Confirm the result and act on it.',
                              [{'label': 'Open lab insights', 'url': reverse('patient_labs', args=[p.pk])}]))
    if flag('K') == 'HH':
        F.append(_finding('danger', 'result', 'High potassium', 'Get an ECG now, repeat the sample to exclude haemolysis, and treat per hyperkalaemia protocol.'))
    # 4. work-up that seems to be missing
    def missing(title, detail, *codes):
        if not set(codes) & recent_tests:
            tests = LabTest.objects.filter(code__in=codes, active=True)
            F.append(_finding('warn', 'missing', title, detail, [{'label': f'Order {t.name}', 'url': f'{lab_url}&test={t.pk}'} for t in tests[:2]]))
    if _has(dx, 'malaria'):
        missing('Malaria not confirmed by a test', 'Test before treating: a malaria RDT or blood film is recommended before antimalarials.', 'MAL', 'MPS')
    if _has(dx, 'urinary', 'uti'):
        missing('No urinalysis for a urinary infection', 'A urine dipstick or culture supports the diagnosis and guides antibiotics.', 'UA')
    if _has(dx + conditions, 'diabet'):
        missing('No recent glucose or HbA1c', 'Diabetes care needs a glucose or HbA1c within the last 3 months.', 'HBA1C', 'GLU')
    if _has(dx, 'anaemia', 'anemia', 'pallor'):
        missing('No haemoglobin for suspected anaemia', 'Confirm with a haemoglobin or full blood count.', 'HB', 'CBC')
    if _has(dx, 'chest pain', 'acs', 'coronary') :
        missing('No troponin for chest pain', 'A troponin (repeated) is needed to exclude a heart attack.', 'TROP')
    # 5. results that do not fit the working diagnosis (possible misdiagnosis)
    if _has(dx, 'malaria') and 'RDT' in vals and vals['RDT'].flag == 'N' and not ('DENS' in vals and vals['DENS'].flag in FLAG_BAD):
        F.append(_finding('danger', 'mismatch', 'Malaria test negative', f'The malaria RDT is {vals["RDT"].display} but the diagnosis is malaria. Consider other causes of fever (e.g. typhoid, UTI, pneumonia, viral illness).'))
    if flag('TNI') in ('H', 'HH') and not _has(dx + conditions, *CARDIAC_TERMS):
        F.append(_finding('warn', 'mismatch', 'Raised troponin not reflected in the diagnosis', f'Troponin {shown("TNI")}. Consider acute coronary syndrome, myocarditis or other cardiac injury.'))
    if flag('FBG') in ('H', 'HH') and not _has(dx + conditions, 'diabet'):
        F.append(_finding('info', 'mismatch', 'High glucose without a diabetes diagnosis', f'Fasting glucose {shown("FBG")}. Consider diabetes; confirm with HbA1c.'))
    if flag('HB') in ('L', 'LL') and not _has(dx + conditions, 'anaemia', 'anemia', 'bleed'):
        F.append(_finding('info', 'mismatch', 'Low haemoglobin not explained by the diagnosis', f'Haemoglobin {shown("HB")}. Consider anaemia work-up (iron studies, blood film).'))
    if 'MTB' in vals and vals['MTB'].flag == 'A' and not _has(dx + conditions, 'tuberc', 'tb'):
        F.append(_finding('danger', 'mismatch', 'TB detected but not in the diagnosis', 'GeneXpert detected M. tuberculosis. Start TB treatment pathway and notify per national programme.'))
    order = {'danger': 0, 'warn': 1, 'info': 2}
    return sorted(F, key=lambda f: order[f['level']])


# ------------------------------------------------------------------ suggestions from this hospital's data
def treatment_suggestions(encounter, min_cases=3):
    """What clinicians here usually ordered and prescribed for a similar diagnosis, and how those patients did."""
    from collections import Counter, defaultdict
    from .models import Encounter
    from .services import _diagnosis_term, SUCCESS
    term = _diagnosis_term(encounter.diagnosis or encounter.reason)
    if not term:
        return {'term': '', 'n': 0, 'tests': [], 'meds': []}
    cases = list(Encounter.objects.filter(status='completed', diagnosis__icontains=term).exclude(pk=encounter.pk)
                 .prefetch_related('labs__test', 'prescriptions__items__medication'))
    n = len(cases)
    if n < min_cases:
        return {'term': term, 'n': n, 'tests': [], 'meds': []}
    tests, meds, med_ok, how = Counter(), Counter(), Counter(), defaultdict(Counter)
    test_obj, med_obj = {}, {}
    for e in cases:
        for t in {o.test for o in e.labs.all() if o.status != 'cancelled'}:
            tests[t.pk] += 1; test_obj[t.pk] = t
        seen = set()
        for rx in e.prescriptions.all():
            for i in rx.items.all():
                if i.medication_id in seen:
                    continue
                seen.add(i.medication_id); meds[i.medication_id] += 1; med_obj[i.medication_id] = i.medication
                how[i.medication_id][(str(i.units_per_dose.normalize()), i.frequency, i.duration_days, i.dose, i.route)] += 1
                if e.outcome in SUCCESS:
                    med_ok[i.medication_id] += 1
    out_tests = [{'id': k, 'name': test_obj[k].name, 'code': test_obj[k].code, 'n': c, 'pct': round(c * 100 / n)} for k, c in tests.most_common(6) if c >= min_cases]
    out_meds = []
    for k, c in meds.most_common(6):
        if c < min_cases:
            continue
        (units, freq, days, dose, route), _ = how[k].most_common(1)[0]
        out_meds.append({'id': k, 'name': str(med_obj[k]), 'n': c, 'pct': round(c * 100 / n), 'success': round(med_ok[k] * 100 / c),
                         'units': units, 'frequency': freq, 'days': days, 'dose': dose, 'route': route})
    return {'term': term, 'n': n, 'tests': out_tests, 'meds': out_meds}


# ------------------------------------------------------------------ AI boundary
def _age_band(p):
    if p.age is None:
        return 'unknown'
    return 'under 5' if p.age < 5 else '5-17' if p.age < 18 else f'{p.age // 10 * 10}-{p.age // 10 * 10 + 9}'


def deidentified_context(encounter):
    """Minimum-necessary clinical context with no direct identifiers: no name, record number, phone, address,
    date of birth or real dates (days are counted relative to this visit). Free-text notes are excluded because
    they can contain names; structured findings are sent instead. Includes the de-identified pharmacy and bedside
    sections from dr_flow_context (medicines, doses given, stock status, bed type, devices, observations)."""
    p, start = encounter.patient, encounter.created_at
    rel = lambda dt: (dt - start).days if dt else None
    vals = []
    from .models import LabResultValue, ImagingOrder, PrescriptionItem
    for v in (LabResultValue.objects.filter(order__encounter__patient=p, order__status__in=['resulted', 'verified'])
              .select_related('parameter', 'order').order_by('order__resulted_at')[:200]):
        vals.append({'test': v.parameter.name, 'value': v.display, 'unit': v.parameter.unit, 'flag': v.flag,
                     'reference': v.parameter.range_label(p.sex), 'day': rel(v.order.resulted_at or v.order.created_at)})
    from .dr_flow_context import care_context, scrub
    care = care_context(encounter)          # pharmacy and bedside, de-identified (see dr_flow_context.py)
    ctx = {
        'patient': {'sex': p.sex, 'age_band': _age_band(p), 'blood_group': p.blood_group or None},
        'visit': {'department': str(encounter.department or ''), 'status': encounter.status, 'diagnosis': scrub(encounter.diagnosis, p, 300),
                  'vitals': encounter.vitals},
        'allergies': [{'substance': a.substance, 'severity': a.severity} for a in p.allergies.filter(status='active')],
        'conditions': [scrub(c, p, 120) for c in p.conditions.filter(status='active').values_list('name', flat=True)],
        'medicines': [{'medicine': str(i.medication), 'directions': scrub(i.directions, p, 300), 'day': rel(i.prescription.created_at)}
                      for i in PrescriptionItem.objects.filter(prescription__encounter__patient=p).exclude(prescription__state='cancelled')
                      .select_related('medication', 'prescription').order_by('-prescription__created_at')[:40]],
        'lab_results': vals,
        'imaging': [{'study': f'{o.get_modality_display()} {scrub(o.region, p, 80)}', 'impression': scrub(o.impression, p, 800), 'abnormal': o.abnormal, 'day': rel(o.reported_at)}
                    for o in ImagingOrder.objects.filter(encounter__patient=p, status='reported')],
        'rule_based_findings': [{'level': f['level'], 'title': f['title']} for f in clinical_review(encounter)],
    }
    if 'pharmacy' in care:
        ctx.pop('medicines')                # the pharmacy section is fuller (dispensing, doses given, stock)
    ctx.update(care)
    return ctx


def ai_enabled():
    """AI is on when CLINICAL_AI_ENABLED is set and a provider is configured (an Anthropic API key or an endpoint)."""
    from .medical_ai import enabled
    return enabled()


def ai_review(encounter):
    """Send the de-identified context to the configured AI service. Returns None while AI is not configured.
    Any answer is an unverified suggestion for a licensed clinician to review. See medical_ai.py."""
    from .medical_ai import review_encounter
    return review_encounter(encounter)
