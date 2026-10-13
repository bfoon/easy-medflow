"""Dr. Flow on the Lab insights page: a heads-up about the patient's results, and answers to any question about them.

Three parts:
  * heads-up, worked out here with no AI (always available): critical results not yet reviewed, results getting
    worse or newly out of range, results back to normal, out-of-range results waiting for review, tests still in the
    lab (and those waiting too long), abnormal imaging;
  * an AI heads-up: the big picture of all the results together;
  * questions: anything about the results, with the earlier questions and answers kept in mind.

What the AI receives (insights_context): sex and age band; every result with its unit, body system, hospital range
and critical limits, and up to 10 earlier values counted in days ago (no dates); the trend of each result; tests
still in the lab; imaging modality, region, abnormal yes/no and impression with names removed; and, when the patient
has an open visit, clinical.deidentified_context (diagnosis, vitals, allergies, conditions, medicines and pharmacy,
bedside). Lab comments are kept short with the patient's names removed.

Never sent: name, record number, phone, address, date of birth, real dates or times, who reviewed a result, staff
names, image files, or free-text notes. Each answer is stored (LabInsightAsk) with a SHA-256 of what was sent.
"""
import hashlib
import json
from datetime import datetime

from django.utils import timezone

from . import medical_ai
from .dr_flow_context import scrub

ABNORMAL = ('H', 'L', 'HH', 'LL', 'A', 'AA')
CRITICAL = ('HH', 'LL', 'AA')
HISTORY_POINTS = 10

HEADSUP_TASK = """Give the doctor a heads-up about this patient's laboratory results, all of them together.
Use only the de-identified data provided. Start with one sentence: the single most important thing. Then use exactly
these headings:
## Heads-up
(numbered, most urgent first: critical or worsening results, each with what it means and what to do now)
## What the results suggest together
(patterns across tests and body systems, and the likely explanations to consider, common West African causes
included where they fit: malaria, sickle cell disease, TB, HIV, anaemia from worms or diet, kidney disease from
hypertension, diabetes)
## Trends
(what is getting better, what is getting worse, and how fast)
## Suggested next tests
(only tests that would change management, each with a one-line reason; say which are already pending)
## Watch for
(the red flags that should make the team act)
Keep it short enough to read in two minutes. Do not invent results, doses or dates. If important results are
missing or out of date, say so."""

QUESTION_TASK = """The doctor has a question about this patient's laboratory results. Answer it directly and
briefly, using only the de-identified data provided. Name the results you rely on with their values and trend. If
the data cannot answer the question, say what test or information is missing. Keep earlier questions and answers in
mind. Use the heading ## Answer, then ## What to do next if action is needed.

Question: {question}"""


# ------------------------------------------------------------------ helpers
def _days_ago(date_str, now):
    """patient_lab_data gives local 'YYYY-MM-DD HH:MM'; turn it into days ago (1 decimal) so no date leaves the server."""
    try:
        dt = timezone.make_aware(datetime.strptime(date_str, '%Y-%m-%d %H:%M'))
    except (TypeError, ValueError):
        return None
    return round((now - dt).total_seconds() / 86400, 1)


def _outside(v, lo, hi):
    """How far a value is outside the range (0 inside), relative to the range so tests can be compared."""
    if v is None:
        return None
    width = (hi - lo) if lo is not None and hi is not None and hi > lo else (abs(hi or lo or 1) or 1)
    if lo is not None and v < lo:
        return (lo - v) / width
    if hi is not None and v > hi:
        return (v - hi) / width
    return 0.0


def trend(p):
    """'worsening' | 'newly abnormal' | 'improving' | 'back to normal' | 'rising' | 'falling' | 'stable' | None."""
    pts = [h for h in p['history'] if h.get('num') is not None]
    if len(pts) < 2:
        return None
    a, b = pts[-2], pts[-1]
    da, db = _outside(a['num'], p['lo'], p['hi']), _outside(b['num'], p['lo'], p['hi'])
    if da == 0 and db > 0:
        return 'newly abnormal'
    if da > 0 and db == 0:
        return 'back to normal'
    if db > 0 and db > da * 1.1:
        return 'worsening'
    if db > 0 and db < da * 0.9:
        return 'improving'
    base = abs(a['num']) or 1
    change = (b['num'] - a['num']) / base
    return 'rising' if change > 0.05 else 'falling' if change < -0.05 else 'stable'


# ------------------------------------------------------------------ the de-identified context
def insights_context(patient, data=None, include_visit=True):
    from .clinical import _age_band
    from .models import LabOrder
    from .views import patient_lab_data
    now = timezone.now()
    data = data if data is not None else patient_lab_data(patient)
    results = []
    for p in data['params']:
        hist = p['history'][-HISTORY_POINTS:]
        results.append({
            'test': p['test'], 'result': p['name'], 'unit': p['unit'] or None, 'body_system': p['system'] or None,
            'hospital_range': p['range'] or None, 'critical_low': p['clo'], 'critical_high': p['chi'],
            'latest': {'value': p['latest']['display'], 'flag': p['latest']['flag'] or 'normal', 'days_ago': _days_ago(p['latest']['date'], now),
                       'reviewed_by_a_clinician': p['latest']['ack'], 'preliminary': p['latest']['preliminary']},
            'trend': trend(p),
            'earlier': [{'value': h['display'], 'flag': h['flag'] or 'normal', 'days_ago': _days_ago(h['date'], now)} for h in hist[:-1]],
        })
    pending = [{'test': o.test.name, 'status': o.get_status_display(), 'days_waiting': round((now - o.created_at).total_seconds() / 86400, 1)}
               for o in LabOrder.objects.filter(encounter__patient=patient, status__in=['ordered', 'collected', 'processing']).select_related('test')[:20]]
    comments = [{'test': o['test'], 'days_ago': _days_ago(o['date'], now), 'lab_comment': scrub(o['comment'], patient, 200)}
                for o in data['orders'] if o.get('comment')][:10]
    imaging = [{'modality': i['modality'], 'region': scrub(i['region'], patient, 80), 'status': i['status'], 'abnormal': i['abnormal'],
                'impression': scrub(i['impression'], patient, 400) or None, 'days_ago': _days_ago(i['date'], now)} for i in data['imaging'][:8]]
    ctx = {'patient': {'sex': patient.sex, 'age_band': _age_band(patient)},
           'results': results, 'tests_still_in_the_lab': pending, 'lab_comments': comments, 'imaging': imaging}
    if include_visit:
        enc = patient.encounters.filter(status='open').order_by('-created_at').first()
        if enc:
            from .clinical import deidentified_context
            visit = deidentified_context(enc)
            visit.pop('patient', None)
            visit.pop('labs', None)            # already above, with more history
            ctx['open_visit'] = visit
        else:
            ctx['background'] = {'allergies': [a.substance for a in patient.allergies.filter(status='active')],
                                 'conditions': [c.name for c in patient.conditions.filter(status='active')]}
    return ctx


def digest(ctx):
    return hashlib.sha256(json.dumps(ctx, sort_keys=True, default=str).encode()).hexdigest()


# ------------------------------------------------------------------ the heads-up (no AI)
def headsup(patient, data=None):
    """Short lines, most urgent first. Each line can point at a result (param id) for the page to open."""
    from .models import LabOrder
    from .views import patient_lab_data
    now = timezone.now()
    data = data if data is not None else patient_lab_data(patient)
    lines = []
    add = lambda level, icon, text, param=None: lines.append({'level': level, 'icon': icon, 'text': text, 'param': param})
    val = lambda p: f"{p['name']} {p['latest']['display']} {p['unit'] or ''}".strip()
    params = data['params']

    for p in params:
        if p['latest']['flag'] in CRITICAL and not p['latest']['ack']:
            add('danger', 'exclamation-octagon-fill', f"Critical, not yet reviewed: {val(p)}.", p['id'])
    for p in params:
        t = trend(p)
        if t == 'worsening' and p['latest']['flag'] not in CRITICAL:
            add('warn', 'graph-down-arrow' if (p['latest'].get('num') or 0) < (p['lo'] or 0) else 'graph-up-arrow', f"Getting worse: {val(p)}.", p['id'])
        elif t == 'newly abnormal' and p['latest']['flag'] not in CRITICAL:
            add('warn', 'exclamation-triangle', f"Newly out of range: {val(p)}.", p['id'])
    unreviewed = [p for p in params if p['latest']['flag'] in ABNORMAL and not p['latest']['ack']]
    if unreviewed:
        add('warn', 'eye', f"{len(unreviewed)} out-of-range result{'s' if len(unreviewed) != 1 else ''} waiting for review.")
    systems = sorted({data['systems'].get(p['system'], p['system']) for p in params if p['latest']['flag'] in ABNORMAL and p['system']})
    if systems:
        add('info', 'diagram-3', 'Body systems affected: ' + ', '.join(systems[:5]) + '.')
    back = [p for p in params if trend(p) == 'back to normal']
    for p in back[:2]:
        add('good', 'check2-circle', f"Back to normal: {val(p)}.", p['id'])
    pend = list(LabOrder.objects.filter(encounter__patient=patient, status__in=['ordered', 'collected', 'processing']).select_related('test'))
    slow = [o for o in pend if (now - o.created_at).total_seconds() > 2 * 86400]
    if slow:
        add('warn', 'hourglass-split', f"Waiting over 2 days in the lab: {', '.join(sorted({o.test.name for o in slow})[:3])}.")
    elif pend:
        add('info', 'hourglass', f"Still in the lab: {', '.join(sorted({o.test.name for o in pend})[:4])}.")
    abn_img = [i for i in data['imaging'] if i['abnormal']]
    if abn_img:
        add('warn', 'image', f"Abnormal imaging: {abn_img[0]['modality']} {abn_img[0]['region']}" + (f" and {len(abn_img) - 1} more" if len(abn_img) > 1 else '') + '.')
    latest = max((_days_ago(p['latest']['date'], now) or 0 for p in params), default=None)
    if not params:
        add('info', 'droplet', 'No results yet for this patient.')
    elif latest is not None and min(_days_ago(p['latest']['date'], now) or 0 for p in params) > 30:
        add('info', 'calendar-x', 'The newest result is over a month old.')
    order = {'danger': 0, 'warn': 1, 'info': 2, 'good': 3}
    lines.sort(key=lambda x: order[x['level']])
    return lines[:10]


# ------------------------------------------------------------------ the worker
def run(pk):
    from .models import LabInsightAsk
    a = LabInsightAsk.objects.select_related('patient').get(pk=pk)
    if a.status not in ('queued', 'running'):
        return a
    prov = medical_ai.provider()
    a.status, a.model_name = 'running', medical_ai.model_name() if prov in ('anthropic', 'openai') else 'endpoint'
    a.save(update_fields=['status', 'model_name', 'updated_at'])
    try:
        if not medical_ai.enabled():
            raise RuntimeError('AI is not configured')
        ctx = insights_context(a.patient)
        if a.kind == 'question':
            earlier = (LabInsightAsk.objects.filter(patient=a.patient, status='done', created_at__lt=a.created_at)
                       .order_by('-created_at')[:6])
            ctx['earlier_questions'] = [{'asked': scrub(e.question, a.patient, 300) if e.kind == 'question' else 'Heads-up on all results',
                                         'answer': e.text[:800]} for e in reversed(earlier)]
            task = QUESTION_TASK.format(question=scrub(a.question, a.patient, 500))
        else:
            task = HEADSUP_TASK
        a.context_digest = digest(ctx)
        text, _sources, _ = medical_ai._ask(ctx, f'lab_insights_{a.kind}', task, system=medical_ai.GENERAL_SYSTEM_PROMPT)
        if not (text or '').strip():
            raise RuntimeError('The AI service returned no text')
        a.text, a.status = text.strip(), 'done'
    except Exception as exc:
        a.status, a.error = 'failed', f'{exc.__class__.__name__}: {exc}'[:500]
    a.finished_at = timezone.now()
    a.save()
    return a


def serialize(a):
    from .templatetags.evidence_tags import simple_md
    status = 'running' if a.busy else 'failed' if a.status in ('queued', 'running') else a.status
    return {'id': a.pk, 'kind': a.kind, 'question': a.question, 'status': status, 'html': str(simple_md(a.text)) if a.text else '',
            'text': a.text, 'error': 'The AI did not answer. Try again in a moment.' if status == 'failed' else '', 'model': a.model_name,
            'helpful': a.helpful, 'by': (a.requested_by.get_full_name() or a.requested_by.get_username()) if a.requested_by_id else '',
            'at': timezone.localtime(a.created_at).strftime('%d %b %H:%M'), 'minutes_ago': int((timezone.now() - a.created_at).total_seconds() // 60)}
