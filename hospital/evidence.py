"""Guidance for a lab result once it is reported, from five places, shown together to the doctor:

  1. The hospital's own reference range and flag (LabParameter).
  2. WHO (or other guideline) reference values for the patient's group: age, sex, pregnancy and trimester,
     inflammation, malaria (ReferenceRange, seeded from WHO guidelines and verified by the laboratory).
  3. The hospital's own protocol for that result (ParameterGuidance), then the built-in general guidance.
  4. What clinicians in this hospital did next after the same kind of result, and how those patients did
     (anonymous aggregates; groups smaller than 3 are hidden, as elsewhere in E-MedFlow).
  5. Summaries and links from trusted medical sources, fetched in the background and cached (EvidenceItem):
     WHO fact sheets, MedlinePlus (US National Library of Medicine) and PubMed guidelines/systematic reviews.

Fetching uses the official public APIs of MedlinePlus and NCBI E-utilities. Plain web pages (WHO fact sheets) are
only fetched from domains in MEDICAL_TRUSTED_DOMAINS and only where the site's robots.txt allows it. No patient
data is ever sent: queries are built from the test name and the direction of the result only.
"""
import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from html.parser import HTMLParser

from django.conf import settings
from django.db import transaction
from django.utils import timezone

DIRECTION = {'L': 'L', 'LL': 'L', 'H': 'H', 'HH': 'H', 'A': 'A'}
DIR_WORD = {'L': 'Low', 'H': 'High', 'A': 'Abnormal'}
SUCCESS = {'resolved', 'improved'}


def direction(flag):
    return DIRECTION.get(flag or '', '')


def evidence_key(code, flag_or_dir):
    return f'{code}:{direction(flag_or_dir) or flag_or_dir}'


# ====================================================================== WHO reference values
HB_2024 = ('WHO. Guideline on haemoglobin cutoffs to define anaemia in individuals and populations. Geneva: World Health Organization; 2024.',
           'https://www.who.int/publications/i/item/9789240088542', 2024)
FERR_2020 = ('WHO guideline on use of ferritin concentrations to assess iron status in individuals and populations. Geneva: World Health Organization; 2020.',
             'https://www.who.int/publications/i/item/9789240000124', 2020)
DM_2006 = ('Definition and diagnosis of diabetes mellitus and intermediate hyperglycaemia: report of a WHO/IDF consultation. Geneva: WHO; 2006.',
           'https://www.who.int/publications/i/item/definition-and-diagnosis-of-diabetes-mellitus-and-intermediate-hyperglycaemia', 2006)
A1C_2011 = ('Use of glycated haemoglobin (HbA1c) in the diagnosis of diabetes mellitus: abbreviated report of a WHO consultation. Geneva: WHO; 2011.',
            'https://www.who.int/publications/i/item/use-of-glycated-haemoglobin-(-hba1c)-in-diagnosis-of-diabetes-mellitus', 2011)
MALARIA = ('WHO Guidelines for malaria: definition of severe falciparum malaria. Geneva: World Health Organization.',
           'https://www.who.int/publications/i/item/guidelines-for-malaria', None)

_HB_NOTE = 'Haemoglobin at sea level, not adjusted for altitude or smoking.'


def _hb_bands(normal, mild, moderate):
    """Bands from the top down; a value falls in the first band whose lower limit it reaches."""
    return [{'label': 'No anaemia', 'low': normal, 'tone': 'teal'}, {'label': 'Mild anaemia', 'low': mild, 'tone': 'amber'},
            {'label': 'Moderate anaemia', 'low': moderate, 'tone': 'amber'}, {'label': 'Severe anaemia', 'low': None, 'tone': 'red'}]


def _W(key, code, label, unit, cite, low=None, high=None, kind='interval', sex='', amin=None, amax=None, cond='', bands=None, note=''):
    return dict(seed_key=f'who:{key}', code=code, label=label, unit=unit, low=low, high=high, kind=kind, sex=sex, age_min_months=amin,
                age_max_months=amax, condition=cond, bands=bands or [], note=note, citation_title=cite[0], citation_url=cite[1], citation_year=cite[2])


WHO_SEED = [
    # Haemoglobin (g/dL): WHO 2024 cut-offs and severity
    _W('hb-6-23m', 'HB', 'Anaemia cut-off', 'g/dL', HB_2024, low=10.5, amin=6, amax=24, bands=_hb_bands(10.5, 9.5, 7.0), note=_HB_NOTE),
    _W('hb-24-59m', 'HB', 'Anaemia cut-off', 'g/dL', HB_2024, low=11.0, amin=24, amax=60, bands=_hb_bands(11.0, 10.0, 7.0), note=_HB_NOTE),
    _W('hb-5-11y', 'HB', 'Anaemia cut-off', 'g/dL', HB_2024, low=11.5, amin=60, amax=144, bands=_hb_bands(11.5, 11.0, 8.0), note=_HB_NOTE),
    _W('hb-12-14y', 'HB', 'Anaemia cut-off', 'g/dL', HB_2024, low=12.0, amin=144, amax=180, bands=_hb_bands(12.0, 11.0, 8.0), note=_HB_NOTE),
    _W('hb-women', 'HB', 'Anaemia cut-off', 'g/dL', HB_2024, low=12.0, sex='F', amin=180, cond='not_pregnant', bands=_hb_bands(12.0, 11.0, 8.0), note=_HB_NOTE),
    _W('hb-men', 'HB', 'Anaemia cut-off', 'g/dL', HB_2024, low=13.0, sex='M', amin=180, bands=_hb_bands(13.0, 11.0, 8.0), note=_HB_NOTE),
    _W('hb-preg-t1', 'HB', 'Anaemia cut-off in pregnancy', 'g/dL', HB_2024, low=11.0, sex='F', cond='t1', bands=_hb_bands(11.0, 10.0, 7.0), note=_HB_NOTE),
    _W('hb-preg-t2', 'HB', 'Anaemia cut-off in pregnancy', 'g/dL', HB_2024, low=10.5, sex='F', cond='t2', bands=_hb_bands(10.5, 9.5, 7.0), note=_HB_NOTE),
    _W('hb-preg-t3', 'HB', 'Anaemia cut-off in pregnancy', 'g/dL', HB_2024, low=11.0, sex='F', cond='t3', bands=_hb_bands(11.0, 10.0, 7.0), note=_HB_NOTE),
    _W('hb-preg', 'HB', 'Anaemia cut-off in pregnancy', 'g/dL', HB_2024, low=11.0, sex='F', cond='pregnant', bands=_hb_bands(11.0, 10.0, 7.0),
       note='Trimester not recorded: 1st/3rd-trimester cut-off shown (2nd trimester is 10.5 g/dL). ' + _HB_NOTE),
    # Ferritin (µg/L): WHO 2020
    _W('ferr-u5', 'FERR', 'Iron deficiency (apparently healthy)', 'µg/L', FERR_2020, low=12, kind='threshold', amax=60, cond='no_inflammation'),
    _W('ferr-5plus', 'FERR', 'Iron deficiency (apparently healthy)', 'µg/L', FERR_2020, low=15, kind='threshold', amin=60, cond='no_inflammation'),
    _W('ferr-u5-infl', 'FERR', 'Iron deficiency with infection or inflammation', 'µg/L', FERR_2020, low=30, kind='threshold', amax=60, cond='inflammation'),
    _W('ferr-5plus-infl', 'FERR', 'Iron deficiency with infection or inflammation', 'µg/L', FERR_2020, low=70, kind='threshold', amin=60, cond='inflammation'),
    _W('ferr-overload-f', 'FERR', 'Risk of iron overload (apparently healthy adults)', 'µg/L', FERR_2020, high=150, kind='threshold', sex='F', amin=180,
       cond='no_inflammation'),
    _W('ferr-overload-m', 'FERR', 'Risk of iron overload (apparently healthy adults)', 'µg/L', FERR_2020, high=200, kind='threshold', sex='M', amin=180,
       cond='no_inflammation'),
    # Glucose and HbA1c: WHO diagnostic criteria
    _W('fbg-dm', 'FBG', 'Diabetes criteria (fasting plasma glucose)', 'mmol/L', DM_2006, high=6.0,
       bands=[{'label': 'Diabetes range', 'low': 7.0, 'tone': 'red'}, {'label': 'Impaired fasting glucose', 'low': 6.1, 'tone': 'amber'},
              {'label': 'Normal fasting glucose', 'low': None, 'tone': 'teal'}],
       note='Diabetes needs a repeat test on another day unless there are clear symptoms of hyperglycaemia.'),
    _W('a1c-dm', 'A1C', 'Diabetes diagnostic cut-off', '%', A1C_2011, high=6.4,
       bands=[{'label': 'Consistent with diabetes', 'low': 6.5, 'tone': 'red'}, {'label': 'Below the diagnostic cut-off', 'low': None, 'tone': 'teal'}],
       note='A value below 6.5% does not exclude diabetes. Unreliable with anaemia, haemoglobinopathies (e.g. HbS) and recent transfusion.'),
    # Severe malaria criteria (only shown when malaria is confirmed or diagnosed)
    _W('mal-hb-adult', 'HB', 'Severe malaria criterion: severe anaemia', 'g/dL', MALARIA, low=7.0, kind='threshold', amin=144, cond='malaria',
       note='With a parasite count above 10,000/µL.'),
    _W('mal-hb-child', 'HB', 'Severe malaria criterion: severe anaemia', 'g/dL', MALARIA, low=5.0, kind='threshold', amax=144, cond='malaria',
       note='Children under 12 years, with a parasite count above 10,000/µL.'),
    _W('mal-hct-adult', 'HCT', 'Severe malaria criterion: severe anaemia', '%', MALARIA, low=20, kind='threshold', amin=144, cond='malaria'),
    _W('mal-hct-child', 'HCT', 'Severe malaria criterion: severe anaemia', '%', MALARIA, low=15, kind='threshold', amax=144, cond='malaria'),
    _W('mal-glu', 'FBG', 'Severe malaria criterion: hypoglycaemia', 'mmol/L', MALARIA, low=2.2, kind='threshold', cond='malaria'),
    _W('mal-crea', 'CREA', 'Severe malaria criterion: renal impairment', 'µmol/L', MALARIA, high=265, kind='threshold', cond='malaria'),
    _W('mal-urea', 'UREA', 'Severe malaria criterion: renal impairment', 'mmol/L', MALARIA, high=20, kind='threshold', cond='malaria'),
    _W('mal-tbil', 'TBIL', 'Severe malaria criterion: jaundice', 'µmol/L', MALARIA, high=50, kind='threshold', cond='malaria',
       note='With a parasite count above 100,000/µL.'),
    _W('mal-hco3', 'HCO3', 'Severe malaria criterion: acidosis', 'mmol/L', MALARIA, low=15, kind='threshold', cond='malaria'),
]


def seed_who_references():
    """Add the standard WHO reference values. Idempotent; never overwrites a reference the laboratory has edited."""
    from .models import ReferenceRange
    dec = lambda v: None if v is None else Decimal(str(v))
    added = 0
    for row in WHO_SEED:
        d = dict(row)
        key = d.pop('seed_key')
        d['low'], d['high'] = dec(d['low']), dec(d['high'])
        _, created = ReferenceRange.objects.get_or_create(seed_key=key, defaults={**d, 'source': 'who', 'source_name': 'World Health Organization'})
        added += created
    return added


# ====================================================================== the patient's group
PREG_WORDS = ('pregnan', 'gestation', 'antenatal', 'gravid')
NOT_ONGOING = ('ectopic', 'miscarriage', 'abortion', 'delivered', 'postpartum', 'post-partum', 'post partum', 'not pregnant', 'stillbirth')
WEEKS = re.compile(r'(\d{1,2})\s*(?:weeks?|wks?|/40)\b', re.I)


def _age_months(dob, today):
    if not dob:
        return None
    return (today.year - dob.year) * 12 + today.month - dob.month - (1 if today.day < dob.day else 0)


def patient_context(patient, encounter=None):
    """Facts that pick the right WHO reference: sex, age in months, pregnancy and trimester, inflammation, malaria."""
    from .models import LabResultValue
    now = timezone.now()
    ctx = {'sex': patient.sex, 'age_months': _age_months(patient.dob, timezone.localdate()), 'pregnant': False, 'trimester': None,
           'inflammation': False, 'malaria': False, 'why': []}
    recent = {}
    for v in (LabResultValue.objects.filter(order__encounter__patient=patient, order__status__in=['resulted', 'verified'],
                                            order__resulted_at__gte=now - timedelta(days=30),
                                            parameter__code__in=['CRP', 'WBC', 'HCG', 'RDT', 'DENS', 'SPEC'])
              .select_related('parameter', 'order').order_by('order__resulted_at')):
        recent[v.parameter.code] = v
    fresh = lambda code, days: code in recent and recent[code].order.resulted_at >= now - timedelta(days=days)
    # pregnancy: the latest visit or condition that mentions it, with weeks counted forward to today
    if patient.sex == 'F':
        notes = [(e.created_at, f'{e.diagnosis} {e.reason}') for e in patient.encounters.exclude(status='cancelled')
                 .filter(created_at__gte=now - timedelta(days=300)).order_by('-created_at')[:30]]
        notes += [(c.created_at, c.name) for c in patient.conditions.filter(status='active')]
        notes.sort(key=lambda x: x[0], reverse=True)
        for when, text in notes:
            t = (text or '').lower()
            if not any(w in t for w in PREG_WORDS):
                continue
            if any(w in t for w in NOT_ONGOING):
                break
            m = WEEKS.search(t)
            if m:
                weeks = int(m.group(1)) + (now - when).days // 7
                if weeks <= 42:
                    ctx['pregnant'], ctx['trimester'] = True, 1 if weeks < 14 else 2 if weeks < 28 else 3
                    ctx['why'].append(f'pregnant, about {weeks} weeks (from the record)')
            elif (now - when).days <= 90:
                ctx['pregnant'] = True
                ctx['why'].append('pregnant (from the record; trimester not recorded)')
            break
        if not ctx['pregnant'] and fresh('HCG', 30) and recent['HCG'].value_text == 'Positive':
            ctx['pregnant'] = True
            ctx['why'].append('positive pregnancy test in the last 30 days')
    if (fresh('CRP', 14) and recent['CRP'].flag in ('H', 'HH')) or (fresh('WBC', 14) and recent['WBC'].flag in ('H', 'HH')):
        ctx['inflammation'] = True
        ctx['why'].append('raised CRP or white cells in the last 14 days (infection or inflammation)')
    dx = f'{encounter.diagnosis} {encounter.reason}'.lower() if encounter else ''
    if (fresh('RDT', 14) and recent['RDT'].flag == 'A') or (fresh('DENS', 14) and recent['DENS'].flag in ('H', 'HH')) \
            or (fresh('SPEC', 14) and recent['SPEC'].flag == 'A') or 'malaria' in dx:
        ctx['malaria'] = True
        ctx['why'].append('malaria confirmed or diagnosed')
    return ctx


def _unit(u):
    return (u or '').replace(' ', '').replace('μ', 'µ').lower()


def references_by_code(codes):
    from .models import ReferenceRange
    out = {}
    for r in ReferenceRange.objects.filter(code__in=set(codes)).exclude(status='retired'):
        out.setdefault(r.code, []).append(r)
    return out


def match_references(refs, parameter, value, ctx):
    """WHO references that fit this patient, each compared with the value when the units match."""
    num = value.value_number if value is not None else None
    out = []
    for r in refs:
        if not r.applies(ctx):
            continue
        same = _unit(r.unit) == _unit(parameter.unit)
        band = r.band_for(num) if same and num is not None else None
        out.append({'ref': r, 'label': r.range_label(), 'same_unit': same, 'population': r.population(),
                    'outside': r.outside(num) if same and num is not None else None, 'band': band})
    out.sort(key=lambda w: (w['ref'].kind != 'interval', w['ref'].label))
    return out


def agreement(value, who):
    """Do the hospital range and the WHO reference say the same thing about this value?"""
    intervals = [w for w in who if w['same_unit'] and w['ref'].kind == 'interval' and w['outside'] is not None]
    if not intervals or value.value_number is None:
        return None
    who_out, hosp_out = any(w['outside'] for w in intervals), value.flag in ('L', 'H', 'LL', 'HH')
    high, low = value.flag in ('H', 'HH'), value.flag in ('L', 'LL')
    if not who_out and ((high and all(w['ref'].high is None for w in intervals)) or (low and all(w['ref'].low is None for w in intervals))):
        side = 'upper' if high else 'lower'
        return {'agree': None, 'text': f'WHO gives no {side} limit for this test, so a {"high" if high else "low"} value is judged by the hospital range.'}
    if who_out == hosp_out:
        return {'agree': True, 'text': 'The hospital range and the WHO reference agree.'}
    if hosp_out:
        return {'agree': False, 'text': 'Outside the hospital range but within the WHO reference for this patient group. '
                                        'The hospital range may be analyser- or population-specific; interpret with the clinical picture.'}
    return {'agree': False, 'text': 'Within the hospital range but outside the WHO reference for this patient group. '
                                    'Consider the WHO definition before calling this result normal.'}


def who_for_request(lr):
    """{value_id: [matching WHO references]} for every reported value in a lab request (for tables and reports)."""
    p = lr.encounter.patient
    ctx = patient_context(p, lr.encounter)
    vals = [v for o in lr.orders.all() if o.status in ('resulted', 'verified') for v in o.values.all()]
    refs = references_by_code(v.parameter.code for v in vals)
    return {v.pk: match_references(refs.get(v.parameter.code, []), v.parameter, v, ctx) for v in vals}, ctx


# ====================================================================== what clinicians here did next
def practice_after(parameter, flag, exclude_patient=None, days=7, min_group=3, limit=400):
    """After the same kind of result in other patients: tests ordered and medicines prescribed within `days`, and how
    the visit ended. Anonymous counts only; every item needs at least `min_group` patients."""
    from .models import LabOrder, LabResultValue, PrescriptionItem
    d = direction(flag)
    flags = {'L': ['L', 'LL'], 'H': ['H', 'HH'], 'A': ['A']}.get(d)
    if not flags:
        return None
    qs = (LabResultValue.objects.filter(parameter__code=parameter.code, parameter__unit=parameter.unit, flag__in=flags,
                                        order__status__in=['resulted', 'verified'], order__resulted_at__isnull=False)
          .select_related('order__encounter').order_by('-order__resulted_at'))
    if exclude_patient is not None:
        qs = qs.exclude(order__encounter__patient=exclude_patient)
    cases, seen = [], set()
    for v in qs[:limit]:
        e = v.order.encounter
        if e.patient_id in seen:          # one case per patient: the most recent such result
            continue
        seen.add(e.patient_id)
        cases.append((e, v.order.resulted_at))
    n = len(cases)
    empty = {'n': n, 'days': days, 'tests': [], 'meds': [], 'outcomes': [], 'min_group': min_group}
    if n < min_group:
        return empty
    start, end = min(t for _, t in cases), max(t for _, t in cases) + timedelta(days=days)
    pids = [e.patient_id for e, _ in cases]
    orders, items = {}, {}
    for pid, code, name, when in (LabOrder.objects.filter(encounter__patient_id__in=pids, created_at__gt=start, created_at__lte=end)
                                  .exclude(status='cancelled').values_list('encounter__patient_id', 'test__code', 'test__name', 'created_at')):
        orders.setdefault(pid, []).append((code, name, when))
    for pid, mid, name, strength, when in (PrescriptionItem.objects.filter(prescription__encounter__patient_id__in=pids, prescription__created_at__gt=start,
                                                                          prescription__created_at__lte=end).exclude(prescription__state='cancelled')
                                           .values_list('prescription__encounter__patient_id', 'medication_id', 'medication__name',
                                                        'medication__strength', 'prescription__created_at')):
        items.setdefault(pid, []).append((mid, f'{name} {strength}'.strip(), when))
    tests, meds, med_ok, outcomes, names = Counter(), Counter(), Counter(), Counter(), {}
    for e, t in cases:
        stop = t + timedelta(days=days)
        got_tests, got_meds = set(), set()
        for code, nm, w in orders.get(e.patient_id, []):
            if t < w <= stop:
                got_tests.add(code)
                names[('t', code)] = nm
        for mid, nm, w in items.get(e.patient_id, []):
            if t < w <= stop:
                got_meds.add(mid)
                names[('m', mid)] = nm
        for code in got_tests:
            tests[code] += 1
        for mid in got_meds:
            meds[mid] += 1
            med_ok[mid] += e.outcome in SUCCESS
        if e.outcome:
            outcomes[e.get_outcome_display()] += 1
    pct = lambda c: round(c * 100 / n)
    return {**empty,
            'tests': [{'code': c, 'name': names[('t', c)], 'n': k, 'pct': pct(k)} for c, k in tests.most_common(6) if k >= min_group],
            'meds': [{'id': m, 'name': names[('m', m)], 'n': k, 'pct': pct(k), 'success': round(med_ok[m] * 100 / k)}
                     for m, k in meds.most_common(6) if k >= min_group],
            'outcomes': [{'label': lbl, 'n': k, 'pct': pct(k)} for lbl, k in outcomes.most_common() if k >= min_group]}


# ====================================================================== trusted online sources
DEFAULT_TRUSTED_DOMAINS = ['who.int', 'nih.gov', 'medlineplus.gov', 'cdc.gov', 'nice.org.uk', 'msf.org', 'cochranelibrary.com',
                           'bmj.com', 'thelancet.com', 'nejm.org']

# LOINC codes for MedlinePlus Connect lab-test pages (only where the mapping is unambiguous)
LOINC = {'HB': '718-7', 'WBC': '6690-2', 'PLT': '777-3', 'RBC': '789-8', 'HCT': '4544-3', 'MCV': '787-2', 'ESR': '4537-7', 'FBG': '1558-6',
         'A1C': '4548-4', 'ALT': '1742-6', 'AST': '1920-8', 'ALP': '6768-6', 'TBIL': '1975-2', 'ALB': '1751-7', 'CREA': '2160-0',
         'UREA': '3094-0', 'NA': '2951-2', 'K': '2823-3', 'CL': '2075-0', 'CRP': '1988-5', 'URIC': '3084-1', 'CA': '17861-6',
         'PHOS': '2777-1', 'TNI': '10839-9', 'CKMB': '13969-1', 'BNP': '30934-4', 'TC': '2093-3', 'LDL': '13457-7', 'HDL': '2085-9',
         'TG': '2571-8', 'TSH': '3016-3', 'FT4': '3024-7', 'PSA': '2857-1', 'FERR': '2276-4', 'PT': '5902-2', 'INR': '6301-6',
         'APTT': '3173-2', 'RETIC': '4679-7', 'LIPA': '3040-3', 'AMY': '1798-8', 'HBS': '5196-1', 'PO2': '2703-7', 'PCO2': '2019-8'}

# What the result points to, in words a medical search engine understands
SEARCH_TERMS = {
    'HB:L': 'anemia', 'HB:H': 'polycythemia', 'WBC:H': 'leukocytosis', 'WBC:L': 'leukopenia neutropenia', 'PLT:L': 'thrombocytopenia',
    'PLT:H': 'thrombocytosis', 'MCV:L': 'microcytic anemia', 'MCV:H': 'macrocytic anemia', 'HCT:L': 'anemia', 'RBC:L': 'anemia',
    'ESR:H': 'erythrocyte sedimentation rate elevated', 'RDT:A': 'malaria', 'DENS:H': 'severe malaria', 'SPEC:A': 'malaria',
    'SICK:A': 'sickle cell disease', 'HBGENO:A': 'sickle cell disease', 'HBS:H': 'sickle cell disease', 'G6PD:A': 'G6PD deficiency',
    'FERR:L': 'iron deficiency anemia', 'FERR:H': 'hyperferritinemia', 'RETIC:H': 'hemolytic anemia', 'BLAST:H': 'acute leukemia',
    'PBFM:A': 'anemia peripheral blood film', 'INR:H': 'coagulopathy', 'PT:H': 'coagulopathy', 'APTT:H': 'coagulopathy',
    'FBG:H': 'diabetes mellitus hyperglycemia', 'FBG:L': 'hypoglycemia', 'A1C:H': 'type 2 diabetes', 'ALT:H': 'elevated liver enzymes',
    'AST:H': 'elevated liver enzymes', 'ALP:H': 'alkaline phosphatase elevated cholestasis', 'TBIL:H': 'jaundice hyperbilirubinemia',
    'ALB:L': 'hypoalbuminemia', 'CREA:H': 'acute kidney injury', 'UREA:H': 'acute kidney injury', 'NA:L': 'hyponatremia',
    'NA:H': 'hypernatremia', 'K:H': 'hyperkalemia', 'K:L': 'hypokalemia', 'CRP:H': 'C-reactive protein elevated infection',
    'URIC:H': 'gout hyperuricemia', 'CA:H': 'hypercalcemia', 'CA:L': 'hypocalcemia', 'PHOS:L': 'hypophosphatemia',
    'VITD:L': 'vitamin D deficiency', 'TNI:H': 'acute myocardial infarction troponin', 'CKMB:H': 'myocardial infarction',
    'BNP:H': 'heart failure', 'TC:H': 'hypercholesterolemia', 'LDL:H': 'hypercholesterolemia', 'HDL:L': 'dyslipidemia',
    'TG:H': 'hypertriglyceridemia', 'TSH:H': 'hypothyroidism', 'TSH:L': 'hyperthyroidism', 'FT4:H': 'hyperthyroidism',
    'FT4:L': 'hypothyroidism', 'PSA:H': 'prostate-specific antigen elevated', 'NIT:A': 'urinary tract infection',
    'LEU:A': 'urinary tract infection', 'PRO:A': 'proteinuria', 'UBLD:A': 'hematuria', 'UGLU:A': 'glycosuria diabetes',
    'HIV:A': 'HIV infection', 'HBS:A': 'hepatitis B', 'MTB:A': 'pulmonary tuberculosis', 'AFB:A': 'pulmonary tuberculosis',
    'RIF:A': 'rifampicin-resistant tuberculosis', 'HPYL:A': 'Helicobacter pylori infection', 'OVA:A': 'intestinal helminth infection',
    'FOB:A': 'gastrointestinal bleeding', 'RF:A': 'rheumatoid arthritis', 'CWBC:H': 'bacterial meningitis', 'CPRO:H': 'meningitis',
    'CGLU:L': 'bacterial meningitis', 'PO2:L': 'hypoxemia', 'SAO2:L': 'hypoxemia', 'HCO3:L': 'metabolic acidosis',
    'PCO2:H': 'respiratory acidosis hypercapnia', 'LIPA:H': 'acute pancreatitis', 'AMY:H': 'acute pancreatitis', 'APP:A': 'urinary tract infection',
}

WHO_FS = 'https://www.who.int/news-room/fact-sheets/detail/'
WHO_FACT_SHEETS = {
    **{k: [WHO_FS + 'anaemia'] for k in ('HB:L', 'HCT:L', 'RBC:L', 'FERR:L', 'MCV:L')},
    **{k: [WHO_FS + 'diabetes'] for k in ('FBG:H', 'A1C:H', 'UGLU:A')},
    **{k: [WHO_FS + 'malaria'] for k in ('RDT:A', 'DENS:H', 'SPEC:A')},
    **{k: [WHO_FS + 'tuberculosis'] for k in ('MTB:A', 'AFB:A', 'RIF:A')},
    'HIV:A': [WHO_FS + 'hiv-aids'], 'HBS:A': [WHO_FS + 'hepatitis-b'],
    **{k: [WHO_FS + 'cardiovascular-diseases-(cvds)'] for k in ('TNI:H', 'CKMB:H', 'TC:H', 'LDL:H')},
    **{k: [WHO_FS + 'meningitis'] for k in ('CWBC:H', 'CPRO:H', 'CGLU:L')},
    'OVA:A': [WHO_FS + 'soil-transmitted-helminth-infections'],
}
SOURCE_RANK = {'who': 0, 'medlineplus': 1, 'pubmed': 2, 'other': 3}


def fetch_enabled():
    return bool(getattr(settings, 'MEDICAL_EVIDENCE_FETCH', False))


def trusted_domains():
    return [d.strip().lower().lstrip('.') for d in (getattr(settings, 'MEDICAL_TRUSTED_DOMAINS', None) or DEFAULT_TRUSTED_DOMAINS) if d.strip()]


def is_trusted(url):
    host = (urllib.parse.urlparse(url).hostname or '').lower()
    return bool(host) and any(host == d or host.endswith('.' + d) for d in trusted_domains())


def user_agent():
    return f'E-MedFlow/1.0 (clinical reference fetcher; {getattr(settings, "SITE_URL", "")})'


def search_term(code, d, name=''):
    return SEARCH_TERMS.get(f'{code}:{d}') or f'{DIR_WORD.get(d, "abnormal").lower()} {name or code}'.strip()


def strip_tags(s):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', s or '')).split())


def _clip(s, n):
    s = ' '.join((s or '').split())
    return s if len(s) <= n else s[:n - 1].rsplit(' ', 1)[0] + '…'


def http_get(url, accept='*/*', timeout=15, robots=False):
    """GET from a trusted domain only. `robots=True` (plain web pages) also obeys the site's robots.txt."""
    if not url.startswith('https://') or not is_trusted(url):
        raise ValueError(f'Not a trusted HTTPS source: {url}')
    if robots and not robots_allow(url):
        raise PermissionError('robots.txt does not allow fetching this page')
    req = urllib.request.Request(url, headers={'User-Agent': user_agent(), 'Accept': accept})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(3_000_000)
        charset = r.headers.get_content_charset() or 'utf-8'
    return raw.decode(charset, 'replace')


_ROBOTS = {}


def robots_allow(url):
    parts = urllib.parse.urlparse(url)
    base = f'{parts.scheme}://{parts.netloc}'
    cached = _ROBOTS.get(base)
    if cached is None or (timezone.now() - cached[1]).total_seconds() > 86400:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(base + '/robots.txt', headers={'User-Agent': user_agent()})
            with urllib.request.urlopen(req, timeout=10) as r:
                rp.parse(r.read(500_000).decode('utf-8', 'replace').splitlines())
        except urllib.error.HTTPError as exc:
            rp.parse([] if exc.code in (404, 410) else ['User-agent: *', 'Disallow: /'])   # no robots.txt = allowed; 401/403 = not
        except Exception:
            return False                       # unreachable: try again next time
        cached = _ROBOTS[base] = (rp, timezone.now())
    return cached[0].can_fetch(user_agent(), url)


class _PageText(HTMLParser):
    """Readable text of a page in document order: (tag, text) for titles, headings, paragraphs and list items."""
    BLOCK = {'title', 'h1', 'h2', 'h3', 'p', 'li'}
    SKIP = {'script', 'style', 'nav', 'footer', 'noscript', 'svg', 'form', 'button'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.meta, self._buf, self._skip = [], {}, None, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta':
            k = (a.get('name') or a.get('property') or '').lower()
            if k in ('description', 'og:description', 'og:title'):
                self.meta[k] = a.get('content') or ''
        elif tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK and not self._skip:
            self._flush()
            self._buf = (tag, [])

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._buf is not None and not self._skip:
            self._buf[1].append(data)

    def _flush(self):
        if self._buf:
            t = ' '.join(''.join(self._buf[1]).split())
            if t:
                self.blocks.append((self._buf[0], t))
        self._buf = None

    def close(self):
        super().close()
        self._flush()


def page_summary(page_html):
    p = _PageText()
    p.feed(page_html)
    p.close()
    title = next((t for tag, t in p.blocks if tag == 'h1'), '') or p.meta.get('og:title') or next((t for tag, t in p.blocks if tag == 'title'), '')
    facts, in_facts = [], False
    for tag, t in p.blocks:
        if tag in ('h2', 'h3'):
            if in_facts:
                break
            in_facts = 'key fact' in t.lower()
        elif in_facts and tag in ('li', 'p'):
            facts.append(t)
    paras = [t for tag, t in p.blocks if tag == 'p' and len(t) > 60][:4]
    desc = p.meta.get('description') or p.meta.get('og:description') or ''
    main = ' '.join([title] + facts[:8] + paras[:4])
    return {'title': title, 'description': desc, 'facts': facts[:8], 'paragraphs': paras, 'fingerprint': hashlib.sha256(main.encode()).hexdigest()}


# ---------------------------------------------------------------------- one function per source
def medlineplus_lab_test(loinc):
    """MedlinePlus Connect (US National Library of Medicine): the consumer page for a lab test, by LOINC code."""
    q = urllib.parse.urlencode({'mainSearchCriteria.v.cs': '2.16.840.1.113883.6.1', 'mainSearchCriteria.v.c': loinc,
                                'knowledgeResponseType': 'application/json', 'informationRecipient.languageCode.c': 'en'})
    data = json.loads(http_get(f'https://connect.medlineplus.gov/service?{q}', accept='application/json'))
    val = lambda x: (x.get('_value') if isinstance(x, dict) else x) or ''
    out = []
    for e in (data.get('feed') or {}).get('entry') or []:
        links = e.get('link') or []
        links = links if isinstance(links, list) else [links]
        url = next((l.get('href') for l in links if isinstance(l, dict) and l.get('href')), '')
        if url and is_trusted(url):
            out.append({'source': 'medlineplus', 'kind': 'lab test', 'title': strip_tags(val(e.get('title'))), 'url': url,
                        'summary': _clip(strip_tags(val(e.get('summary'))), 700)})
    return out[:2]


def medlineplus_topics(term, n=3):
    """MedlinePlus health topics for the condition the result points to (NLM web service, XML)."""
    q = urllib.parse.urlencode({'db': 'healthTopics', 'term': term, 'retmax': n})
    root = ET.fromstring(http_get(f'https://wsearch.nlm.nih.gov/ws/query?{q}', accept='text/xml'))
    out = []
    for doc in root.iter('document'):
        content = {c.get('name'): ''.join(c.itertext()) for c in doc.findall('content')}
        url = doc.get('url') or ''
        if url and is_trusted(url):
            out.append({'source': 'medlineplus', 'kind': 'health topic', 'title': strip_tags(content.get('title')), 'url': url,
                        'summary': _clip(strip_tags(content.get('FullSummary') or content.get('snippet')), 700)})
    return out[:n]


def pubmed_guidelines(term, n=4):
    """Recent guidelines, systematic reviews and meta-analyses from PubMed (NCBI E-utilities), with a short abstract."""
    base = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
    common = {'tool': 'emedflow', 'email': getattr(settings, 'NCBI_EMAIL', '') or ''}
    if getattr(settings, 'NCBI_API_KEY', ''):
        common['api_key'] = settings.NCBI_API_KEY
    query = (f'({term}) AND (guideline[pt] OR practice guideline[pt] OR systematic review[pt] OR meta-analysis[pt]) '
             f'AND english[la] AND hasabstract')
    s = json.loads(http_get(base + 'esearch.fcgi?' + urllib.parse.urlencode({**common, 'db': 'pubmed', 'term': query, 'retmode': 'json',
                                                                            'retmax': n, 'sort': 'relevance', 'datetype': 'pdat',
                                                                            'reldate': 365 * 6}), accept='application/json'))
    ids = (s.get('esearchresult') or {}).get('idlist') or []
    if not ids:
        return []
    summ = json.loads(http_get(base + 'esummary.fcgi?' + urllib.parse.urlencode({**common, 'db': 'pubmed', 'id': ','.join(ids), 'retmode': 'json'}),
                               accept='application/json')).get('result') or {}
    abstracts = {}
    try:
        root = ET.fromstring(http_get(base + 'efetch.fcgi?' + urllib.parse.urlencode({**common, 'db': 'pubmed', 'id': ','.join(ids), 'retmode': 'xml'}),
                                      accept='text/xml'))
        for art in root.iter('PubmedArticle'):
            pmid = art.findtext('.//PMID') or ''
            abstracts[pmid] = ' '.join(''.join(a.itertext()) for a in art.iter('AbstractText'))
    except Exception:
        pass                                   # titles alone are still useful
    out = []
    for pmid in ids:
        r = summ.get(pmid) or {}
        if not r.get('title'):
            continue
        types = [t for t in r.get('pubtype') or [] if t in ('Practice Guideline', 'Guideline', 'Systematic Review', 'Meta-Analysis')]
        meta = ' · '.join(x for x in [r.get('source') or '', r.get('pubdate') or '', ', '.join(types)] if x)
        out.append({'source': 'pubmed', 'kind': (types[0] if types else 'review').lower(), 'title': strip_tags(r['title']),
                    'url': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/', 'published': (r.get('pubdate') or '')[:40],
                    'summary': _clip((meta + '. ' if meta else '') + strip_tags(abstracts.get(pmid, '')), 900)})
    return out


def who_fact_sheet(url):
    """A WHO fact sheet: title, description and its 'Key facts' (robots.txt respected)."""
    s = page_summary(http_get(url, accept='text/html', robots=True))
    summary = ' '.join(s['facts']) or s['description'] or ' '.join(s['paragraphs'][:2])
    return [{'source': 'who', 'kind': 'fact sheet', 'title': s['title'] or 'WHO fact sheet', 'url': url, 'summary': _clip(summary, 1200)}]


# ---------------------------------------------------------------------- background refresh
def refresh_evidence(key, code='', name='', unit=''):
    """Fetch every source for one key and replace the cached items of each source that answered."""
    from .models import EvidenceFetch, EvidenceItem
    f, _ = EvidenceFetch.objects.get_or_create(key=key, defaults={'code': code or key.split(':')[0], 'name': name, 'unit': unit})
    f.code, f.name, f.unit = code or f.code, name or f.name, unit or f.unit
    f.status = 'running'
    f.save()
    d = key.split(':')[1] if ':' in key else ''
    term = search_term(f.code, d, f.name)
    jobs = []
    if f.code in LOINC:
        jobs.append(('medlineplus', lambda: medlineplus_lab_test(LOINC[f.code])))
    jobs.append(('medlineplus', lambda: medlineplus_topics(term)))
    jobs.append(('pubmed', lambda: pubmed_guidelines(term)))
    for url in WHO_FACT_SHEETS.get(key, []):
        jobs.append(('who', lambda url=url: who_fact_sheet(url)))
    found, errors, answered = [], [], set()
    for src, fn in jobs:
        try:
            found += fn()
            answered.add(src)
        except Exception as exc:
            errors.append(f'{src}: {exc.__class__.__name__}')
    kept = 0
    with transaction.atomic():
        if answered:
            EvidenceItem.objects.filter(key=key, source__in=answered).delete()
        seen = set()
        for i, it in enumerate(sorted(found, key=lambda x: SOURCE_RANK.get(x['source'], 9))):
            url = it['url'][:600]
            if url in seen or not it.get('title'):
                continue
            seen.add(url)
            EvidenceItem.objects.update_or_create(key=key, url=url, defaults={
                'source': it['source'], 'kind': it.get('kind', '')[:30], 'title': it['title'][:400], 'summary': it.get('summary', ''),
                'published': it.get('published', '')[:40], 'rank': i, 'fetched_at': timezone.now()})
            kept += 1
    f.status = 'done' if answered else 'failed'
    f.items, f.error, f.last_run_at = kept, '; '.join(errors)[:500], timezone.now()
    f.save()
    return f


def queue_refresh(code, d, name='', unit='', force=False, inline_fallback=False):
    """Ask the background worker to (re)fetch sources for one result type. Returns the EvidenceFetch row, or None
    when fetching is switched off."""
    from .models import EvidenceFetch
    if not fetch_enabled() or d not in ('L', 'H', 'A'):
        return None
    key = f'{code}:{d}'
    f, created = EvidenceFetch.objects.get_or_create(key=key, defaults={'code': code, 'name': name, 'unit': unit})
    if not created and not force and (f.busy or (f.status == 'done' and not f.stale)):
        return f
    f.status, f.error = 'queued', ''
    f.save(update_fields=['status', 'error', 'updated_at'])
    try:
        from .tasks import refresh_evidence_task
        refresh_evidence_task.apply_async(args=[key, code, name, unit], retry=False)
    except Exception:
        if inline_fallback:
            return refresh_evidence(key, code, name, unit)
        f.status, f.error = 'failed', 'Background worker unavailable; use Refresh sources to fetch now.'
        f.save(update_fields=['status', 'error', 'updated_at'])
    return f


def prefetch_for_request(lr):
    """Called when results are submitted: start fetching sources for every abnormal result, so they are ready when
    the doctor opens the request. Never blocks and never fails the save."""
    if not fetch_enabled():
        return 0
    n, done = 0, set()
    try:
        for o in lr.orders.all():
            if o.status not in ('resulted', 'verified'):
                continue
            for v in o.values.select_related('parameter'):
                d = direction(v.flag)
                if d and (v.parameter.code, d) not in done:
                    done.add((v.parameter.code, d))
                    queue_refresh(v.parameter.code, d, v.parameter.name, v.parameter.unit)
                    n += 1
    except Exception:
        return n
    return n


def check_reference_sources():
    """Re-read the page each WHO reference cites. A page that has changed puts its references on 'review' so the
    laboratory re-checks the values; a page that has gone (404/410) is noted. Unreachable pages are left alone."""
    from .models import ReferenceRange
    changed = 0
    by_url = {}
    for r in ReferenceRange.objects.exclude(status='retired').exclude(citation_url=''):
        by_url.setdefault(r.citation_url, []).append(r)
    for url, refs in by_url.items():
        try:
            fp = page_summary(http_get(url, accept='text/html', robots=True))['fingerprint']
            note = ''
        except urllib.error.HTTPError as exc:
            fp, note = None, f'Cited page returned HTTP {exc.code}' if exc.code in (404, 410) else ''
        except Exception:
            continue
        for r in refs:
            fields = ['source_checked_at', 'updated_at']
            r.source_checked_at = timezone.now()
            if note:
                r.source_note, r.status = note, 'review' if r.status in ('curated', 'verified') else r.status
                fields += ['source_note', 'status']
                changed += 1
            elif fp:
                if r.source_hash and r.source_hash != fp and r.status in ('curated', 'verified'):
                    r.status, r.source_note = 'review', f'Cited page changed on {timezone.localdate():%d %b %Y}: re-check the values'
                    fields += ['status', 'source_note']
                    changed += 1
                r.source_hash = fp
                fields.append('source_hash')
            r.save(update_fields=fields)
    return changed


# ====================================================================== everything for one lab request
def request_guidance(lr, practice=True):
    """Guidance for every reported value in a lab request; abnormal values get protocol, practice and evidence."""
    from .models import EvidenceFetch, EvidenceItem, ParameterGuidance
    p = lr.encounter.patient
    ctx = patient_context(p, lr.encounter)
    vals = [(o, v) for o in lr.orders.all() if o.status in ('resulted', 'verified') for v in o.values.all()]
    refs = references_by_code(v.parameter.code for _, v in vals)
    keys = {evidence_key(v.parameter.code, v.flag) for _, v in vals if direction(v.flag)}
    protocols = {}
    for g in ParameterGuidance.objects.filter(active=True, code__in={v.parameter.code for _, v in vals}):
        protocols.setdefault(f'{g.code}:{g.direction}', []).append(g)
    items_by_key = {}
    for it in EvidenceItem.objects.filter(key__in=keys):
        items_by_key.setdefault(it.key, []).append(it)
    fetch = {f.key: f for f in EvidenceFetch.objects.filter(key__in=keys)}
    from .models import LabResultValue
    prev, first = {}, min((o.resulted_at for o, _ in vals if o.resulted_at), default=None)
    earlier = LabResultValue.objects.filter(order__encounter__patient=p, order__status__in=['resulted', 'verified'],
                                            parameter__code__in={v.parameter.code for _, v in vals}).exclude(order__request=lr)
    if first:
        earlier = earlier.filter(order__resulted_at__lt=first)
    for v in earlier.select_related('parameter', 'order').order_by('order__resulted_at'):
        prev[v.parameter.code] = v                    # later results overwrite earlier ones: the last before this request
    rows = []
    for o, v in vals:
        prm, d = v.parameter, direction(v.flag)
        who = match_references(refs.get(prm.code, []), prm, v, ctx)
        row = {'o': o, 'v': v, 'p': prm, 'dir': d, 'abnormal': v.is_abnormal, 'critical': v.is_critical, 'range': prm.range_label(p.sex),
               'who': who, 'agreement': agreement(v, who), 'prev': prev.get(prm.code), 'key': evidence_key(prm.code, v.flag) if d else '',
               'protocol': protocols.get(f'{prm.code}:{d or "N"}', []), 'evidence': [], 'fetch': None, 'practice': None,
               'term': search_term(prm.code, d, prm.name) if d else ''}
        if d:
            row['evidence'] = sorted(items_by_key.get(row['key'], []), key=lambda i: (SOURCE_RANK.get(i.source, 9), i.rank))
            row['fetch'] = fetch.get(row['key'])
            if practice:
                row['practice'] = practice_after(prm, v.flag, exclude_patient=p)
        rows.append(row)
    rows.sort(key=lambda r: (not r['critical'], not r['abnormal']))
    abnormal = [r for r in rows if r['abnormal']]
    return {'ctx': ctx, 'rows': rows, 'abnormal': abnormal, 'normal': [r for r in rows if not r['abnormal']],
            'any_who': any(r['who'] for r in rows), 'fetch_enabled': fetch_enabled(),
            'pending': any(r['fetch'] and r['fetch'].busy for r in abnormal),
            'missing': [r for r in abnormal if not r['evidence'] and not (r['fetch'] and r['fetch'].busy)]}
