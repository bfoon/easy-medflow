"""Find patients fast: free text across the whole record, plus filters by disease category and situation.

Every word typed must match something about the patient (name, number, phone, diagnosis, condition, allergy,
medicine, test, scan or town), so "malaria brikama" or "femur fracture" narrow the list rather than widen it.
"""
import re
from collections import defaultdict
from datetime import timedelta

from django.db.models import Max, Q
from django.utils import timezone

from .categories import INFO, classify

AGE_BANDS = [('child', 'Under 18', 0, 17), ('adult', '18–64', 18, 64), ('older', '65 and over', 65, 200)]
STATUS = [('inpatient', 'Admitted now'), ('queue', 'In the queue'), ('open', 'Open visit'), ('critical', 'Unreviewed abnormal results'),
          ('allergy', 'Has allergies'), ('mine', 'My patients')]


NEGATION = re.compile(r'\b(no|not|without|negative for|nil|absent|free of)\b(?:\W+\w+){0,4}?\W+$', re.I)


def _positive_mention(text, tok):
    """True if the word appears at least once without a negation shortly before it (e.g. 'no ... fracture')."""
    for m in re.finditer(re.escape(tok), text, re.I):
        before = text[max(0, m.start() - 60):m.start()]
        before = re.split(r'[.;]', before)[-1]          # negation does not cross a sentence
        if not NEGATION.search(before):
            return True
    return False


def _token_matches(tok):
    """Patient ids matching one word, each with the reason it matched."""
    from .models import Allergy, Condition, Encounter, ImagingOrder, LabOrder, Patient, PrescriptionItem
    hits = defaultdict(str)
    def add(qs, label):
        for row in qs[:400]:
            pid, val = row if isinstance(row, tuple) else (row, None)   # (patient id, what matched) or just the id
            if pid not in hits:
                hits[pid] = f'{label}: {val}' if val else label
    digits = re.sub(r'\D', '', tok)
    add(Patient.objects.filter(mrn__iexact=tok).values_list('pk', flat=True), 'Patient number')
    add(Patient.objects.filter(Q(first_name__icontains=tok) | Q(last_name__icontains=tok)).values_list('pk', flat=True), 'Name')
    add(Patient.objects.filter(mrn__icontains=tok).values_list('pk', flat=True), 'Patient number')
    if len(digits) >= 5:
        add(Patient.objects.filter(phone__icontains=digits[-7:]).values_list('pk', flat=True), 'Phone')
    if len(tok) >= 3:
        add(Encounter.objects.filter(Q(diagnosis__icontains=tok) | Q(reason__icontains=tok)).order_by('-created_at').values_list('patient_id', 'diagnosis'), 'Diagnosis')
        add(Condition.objects.filter(name__icontains=tok).values_list('patient_id', 'name'), 'Condition')
        add(Allergy.objects.filter(substance__icontains=tok, status='active').values_list('patient_id', 'substance'), 'Allergy')
        add(PrescriptionItem.objects.filter(medication__name__icontains=tok).values_list('prescription__encounter__patient_id', 'medication__name'), 'Medicine')
        add(LabOrder.objects.filter(test__name__icontains=tok).values_list('encounter__patient_id', 'test__name'), 'Test')
        # scan reports often say what was NOT found ("no cervical spine fracture"); only count positive mentions
        add(ImagingOrder.objects.filter(region__icontains=tok).values_list('encounter__patient_id', 'region'), 'Scan')
        for pid, region, text in ImagingOrder.objects.filter(impression__icontains=tok).values_list('encounter__patient_id', 'region', 'impression')[:400]:
            if pid not in hits and _positive_mention(text, tok):
                hits[pid] = f'Scan: {region}'
        add(Patient.objects.filter(Q(location__name__icontains=tok) | Q(location__parent__name__icontains=tok) | Q(address__icontains=tok)).values_list('pk', flat=True), 'Lives in')
    return hits


def search_patients(user, q='', cats=(), dept='', status=(), age='', sex='', town='', days='', sort='relevance', limit=60):
    from .models import Admission, Department, Encounter, LabResultValue, Patient, QueueTicket
    qs = Patient.objects.all()
    reasons = {}
    tokens = [t for t in re.split(r'\s+', (q or '').strip()) if t][:6]
    if tokens:
        ids = None
        for tok in tokens:
            m = _token_matches(tok)
            ids = set(m) if ids is None else ids & set(m)
            for pid, why in m.items():
                reasons.setdefault(pid, []).append(why)
        qs = qs.filter(pk__in=ids or [])
    # situation filters
    if days in ('7', '30', '90', '365'):
        qs = qs.filter(encounters__created_at__gte=timezone.now() - timedelta(days=int(days)))
    if dept:
        qs = qs.filter(encounters__department_id=dept)
    if sex in ('M', 'F'):
        qs = qs.filter(sex=sex)
    band = next((b for b in AGE_BANDS if b[0] == age), None)
    if band:
        today = timezone.localdate()
        qs = qs.filter(dob__lte=today.replace(year=today.year - band[2]), dob__gt=today.replace(year=today.year - band[3] - 1))
    if town:
        qs = qs.filter(Q(location__name__iexact=town) | Q(location__parent__name__iexact=town))
    st = set(status)
    if 'inpatient' in st:
        qs = qs.filter(encounters__admissions__discharged_at__isnull=True, encounters__admissions__isnull=False)
    if 'queue' in st:
        qs = qs.filter(tickets__status__in=['waiting', 'called', 'in_service'])
    if 'open' in st:
        qs = qs.filter(encounters__status='open')
    if 'critical' in st:
        qs = qs.filter(encounters__labs__values__flag__in=['H', 'L', 'HH', 'LL', 'A'], encounters__labs__values__acknowledged_at__isnull=True)
    if 'allergy' in st:
        qs = qs.filter(allergies__status='active')
    if 'mine' in st:
        qs = qs.filter(encounters__clinician=user)
    base = qs.distinct()
    # category facet counts are computed before the category filter, so other categories stay visible
    def cat_ids(qs_):
        rows = Encounter.objects.filter(patient__in=qs_).exclude(category='').values_list('patient_id', 'category')
        rows = list(rows) + list(Patient.objects.filter(pk__in=qs_, conditions__status='active').exclude(conditions__category='').values_list('pk', 'conditions__category'))
        by_cat = defaultdict(set)
        for pid, c in rows:
            by_cat[c].add(pid)
        return by_cat
    by_cat = cat_ids(base.values('pk'))
    if cats:
        keep = set().union(*(by_cat.get(c, set()) for c in cats))
        qs = base.filter(pk__in=keep)
    else:
        qs = base
    total = qs.count()
    qs = qs.annotate(last_seen=Max('encounters__created_at')).select_related('location__parent')
    if sort == 'name':
        qs = qs.order_by('last_name', 'first_name')
    else:
        qs = qs.order_by('-last_seen', 'last_name')
    rows = list(qs[:limit * 3 if tokens and sort == 'relevance' else limit])
    if tokens and sort == 'relevance':   # exact number, then name matches, then everything else; most recent first within each
        rank = lambda p: (0 if any(r.startswith('Patient number') for r in reasons.get(p.pk, [])) else 1 if all(r == 'Name' for r in reasons.get(p.pk, [])) else 2)
        rows = sorted(rows, key=rank)[:limit]
    # enrich the visible rows
    pids = [p.pk for p in rows]
    last = {}
    for e in Encounter.objects.filter(patient_id__in=pids).select_related('department').order_by('patient_id', '-created_at'):
        last.setdefault(e.patient_id, e)
    beds = {a.encounter.patient_id: a.bed for a in Admission.objects.filter(discharged_at__isnull=True, encounter__patient_id__in=pids).select_related('bed', 'encounter')}
    tickets = {t.patient_id: t for t in QueueTicket.objects.filter(patient_id__in=pids, status__in=['waiting', 'called', 'in_service'])}
    flagged = defaultdict(int)
    for pid in LabResultValue.objects.filter(order__encounter__patient_id__in=pids, flag__in=['H', 'L', 'HH', 'LL', 'A'], acknowledged_at__isnull=True).values_list('order__encounter__patient_id', flat=True):
        flagged[pid] += 1
    allergies = defaultdict(list)
    from .models import Allergy
    for pid, sub in Allergy.objects.filter(patient_id__in=pids, status='active').values_list('patient_id', 'substance'):
        allergies[pid].append(sub)
    pcats = defaultdict(set)
    for c, ids in by_cat.items():
        for pid in ids & set(pids):
            pcats[pid].add(c)
    # when filtering by category, show the visit that put each patient in it
    cat_hit = {}
    if cats:
        for e in Encounter.objects.filter(patient_id__in=pids, category__in=cats).order_by('-created_at').only('patient_id', 'diagnosis', 'created_at', 'category'):
            cat_hit.setdefault(e.patient_id, e)
    results = []
    for p in rows:
        e = last.get(p.pk)
        results.append({'p': p, 'last': e, 'last_cat': INFO.get(e.category) if e and e.category else None, 'bed': beds.get(p.pk), 'ticket': tickets.get(p.pk),
                        'flagged': flagged.get(p.pk, 0), 'allergies': allergies.get(p.pk, []), 'why': list(dict.fromkeys(reasons.get(p.pk, [])))[:3],
                        'cat_hit': cat_hit.get(p.pk), 'cat_hit_info': INFO.get(cat_hit[p.pk].category) if p.pk in cat_hit else None,
                        'cats': [INFO[c] for c in sorted(pcats.get(p.pk, ()), key=lambda c: (c not in cats, c)) if c in INFO]})   # selected categories first
    facets = sorted(({**INFO[c], 'n': len(ids)} for c, ids in by_cat.items() if c in INFO), key=lambda f: -f['n'])
    return {'results': results, 'total': total, 'facets': facets, 'departments': Department.objects.order_by('name')}


def category_suggestions(q):
    """Categories whose name, or whose classification of the typed words, matches what was typed."""
    ql = q.lower().strip()
    if len(ql) < 3:
        return []
    out = [INFO[k] for k in INFO if ql in INFO[k]['label'].lower()]
    guess = classify(q)
    if guess and guess != 'other' and INFO[guess] not in out:
        out.append(INFO[guess])
    return out[:3]
