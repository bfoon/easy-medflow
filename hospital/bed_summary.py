"""Dr. Flow on the bed page: a summary of the patient in this bed, with no personal data sent to the AI.

Two parts:
  * quick facts, worked out here on the server with no AI at all (always available): day of stay, NEWS2 and its
    trend, oxygen, device warnings, doses late or missed, tests still in the lab, allergies, medicines out of stock;
  * a handover summary written by the AI (SBAR: situation, background, assessment, recommendations, watch for).

What the AI receives is `clinical.deidentified_context` (sex, age band, diagnosis, vitals, allergies, conditions,
results, imaging impressions, rule-based findings, and the de-identified pharmacy and bedside sections from
dr_flow_context.py) plus the stay: days since admission, bed type, today's medication chart counts, tests and imaging
still pending, and the injury/burn summary with names removed.

Never sent: name, record number, phone, address, date of birth, real dates or times, ward name, bed code, staff names,
or free-text notes (reason for visit, symptoms, nursing or discharge notes). Each summary is stored (BedSummary) with
a SHA-256 of exactly what was sent, for audit. The page can show that exact context before anything is sent.
"""
import hashlib
import json
from datetime import timedelta

from django.utils import timezone

from . import medical_ai
from .dr_flow_context import scrub

SUMMARY_TASK = """Write a handover summary of this inpatient for the next doctor or nurse on the ward.
Use only the de-identified data provided. Start with one sentence that sums the patient up. Then use exactly these
headings:
## Situation
(why they are here now, how they are today: NEWS2 and its trend, oxygen, anything urgent first)
## Background
(relevant conditions, allergies, key results and imaging, day of stay)
## Assessment
(is the patient improving, stable or getting worse, and why; device warnings; missed or late doses; medicines out of
stock)
## Recommendations
(numbered, practical, for the next shift: what to check, chase, repeat or escalate, each with a one-line reason)
## Watch for
(the red flags that should make the team escalate)
Keep it short enough to read in one minute. Do not invent findings, doses or dates. If something important is missing
(no observations today, no weight, no recent results), say so under Recommendations."""


# ------------------------------------------------------------------ context
def stay_context(admission):
    """What the bed page adds to the visit context: the stay, today's chart and what is still pending."""
    from .models import ImagingOrder, LabOrder
    from .views import medication_chart
    e, p, now = admission.encounter, admission.encounter.patient, timezone.now()
    _rows, counts = medication_chart(p, admission.admitted_at)
    pending_tests = sorted(set(LabOrder.objects.filter(encounter__patient=p, status__in=['ordered', 'collected', 'processing'])
                               .values_list('test__name', flat=True)))[:15]
    pending_imaging = [f'{o.get_modality_display()} {scrub(o.region, p, 80)}'
                       for o in ImagingOrder.objects.filter(encounter__patient=p, status__in=['requested', 'acquired'])[:10]]
    ctx = {'days_since_admission': round((now - admission.admitted_at).total_seconds() / 86400, 1),
           'bed_type': admission.bed.get_kind_display(),
           'medication_chart_today': counts,
           'lab_tests_still_pending': pending_tests,
           'imaging_still_pending': pending_imaging}
    try:
        from .care_views import latest_injury
        from . import injury as I
        inj = latest_injury(p)
        if inj:
            ctx['injury_or_burn_summary'] = scrub(I.summary(inj.computed, inj.data), p, 400)
    except Exception:            # an injury record that cannot be summarised must never block the handover
        pass
    return ctx


def summary_context(admission):
    from .clinical import deidentified_context
    ctx = deidentified_context(admission.encounter)
    ctx['this_stay'] = stay_context(admission)
    return ctx


def digest(ctx):
    return hashlib.sha256(json.dumps(ctx, sort_keys=True, default=str).encode()).hexdigest()


# ------------------------------------------------------------------ quick facts (no AI)
def quick_facts(admission):
    """Short lines for the bed page, safety first. Worked out from the same de-identified data the AI would get."""
    from .dr_flow_context import bedside_context, pharmacy_context
    e, p = admission.encounter, admission.encounter.patient
    lines = []
    add = lambda level, icon, text: lines.append({'level': level, 'icon': icon, 'text': text})
    bd = bedside_context(e) or {}
    ph = pharmacy_context(e) or {}
    stay = stay_context(admission)

    obs = bd.get('observations_last_24h') or []
    if obs:
        last = obs[0]
        n = last.get('news2')
        trend = ''
        older = next((o.get('news2') for o in obs[1:] if o.get('news2') is not None), None)
        if n is not None and older is not None:
            trend = ' and rising' if n > older else ' and falling' if n < older else ', unchanged'
        if n is not None:
            add('danger' if n >= 7 else 'warn' if n >= 5 else 'info', 'activity',
                f'NEWS2 {n}{trend} ({last["hours_ago"]} h ago).' + (' Urgent review needed.' if n >= 7 else ' Increase monitoring.' if n >= 5 else ''))
        if last.get('spo2') is not None and last['spo2'] < 92:
            add('danger', 'lungs', f'SpO2 {last["spo2"]}%{" on oxygen" if last.get("on_oxygen") else " on air"}.')
    elif bd.get('admitted'):
        add('warn', 'clipboard-x', 'No observations recorded in the last 24 hours.')

    for w in (bd.get('device_warnings') or [])[:3]:
        add('warn', 'exclamation-triangle', w)
    o2 = (bd.get('devices') or {}).get('oxygen')
    if o2:
        add('info', 'wind', f"On oxygen: {o2['device']}, {o2['flow_l_min']} L/min.")

    c = stay.get('medication_chart_today') or {}
    if c.get('late'):
        add('warn', 'alarm', f"{c['late']} dose{'s' if c['late'] != 1 else ''} late today.")
    missed = sum((m.get('doses_last_48h') or {}).get(k, 0) for m in ph.get('current_and_recent_medicines', []) for k in ('missed', 'refused', 'held'))
    if missed:
        add('warn', 'capsule', f'{missed} dose{"s" if missed != 1 else ""} missed, refused or held in the last 48 hours.')
    out = sorted({m['medicine'] for m in ph.get('current_and_recent_medicines', [])
                  if m.get('pharmacy_stock_now') == 'out of stock' and m.get('dispensed') != 'fully'})
    if out:
        add('warn', 'box-seam', 'Out of stock in the pharmacy: ' + ', '.join(out[:3]) + '.')

    if ph.get('allergies'):
        add('danger', 'exclamation-octagon', 'Allergies: ' + ', '.join(a['substance'] for a in ph['allergies'][:4]) + '.')
    if stay['lab_tests_still_pending']:
        add('info', 'droplet-half', 'Still in the lab: ' + ', '.join(stay['lab_tests_still_pending'][:4]) + '.')
    if stay['imaging_still_pending']:
        add('info', 'image', 'Imaging pending: ' + ', '.join(stay['imaging_still_pending'][:3]) + '.')
    add('info', 'calendar3', f"Day {int(stay['days_since_admission']) + 1} of the stay · {stay['bed_type']} bed.")
    order = {'danger': 0, 'warn': 1, 'info': 2}
    return sorted(lines, key=lambda x: order[x['level']])[:9]


# ------------------------------------------------------------------ the worker
def run(pk):
    from .models import BedSummary
    s = BedSummary.objects.select_related('admission__encounter__patient', 'admission__bed').get(pk=pk)
    if s.status not in ('queued', 'running'):
        return s
    prov = medical_ai.provider()
    s.status, s.model_name = 'running', medical_ai.model_name() if prov in ('anthropic', 'openai') else 'endpoint'
    s.save(update_fields=['status', 'model_name', 'updated_at'])
    try:
        if not medical_ai.enabled():
            raise RuntimeError('AI is not configured')
        ctx = summary_context(s.admission)
        s.context_digest = digest(ctx)
        text, _sources, _ = medical_ai._ask(ctx, 'bed_summary', SUMMARY_TASK, system=medical_ai.GENERAL_SYSTEM_PROMPT)
        if not (text or '').strip():
            raise RuntimeError('The AI service returned no text')
        s.text, s.status = text.strip(), 'done'
    except Exception as exc:
        s.status, s.error = 'failed', f'{exc.__class__.__name__}: {exc}'[:500]
    s.finished_at = timezone.now()
    s.save()
    return s


def serialize(s):
    from .templatetags.evidence_tags import simple_md
    if s is None:
        return None
    status = 'running' if s.busy else 'failed' if s.status in ('queued', 'running') else s.status   # a job stuck 10 min has died
    return {'id': s.pk, 'status': status, 'html': str(simple_md(s.text)) if s.text else '', 'text': s.text,
            'error': 'The AI did not answer. Try again in a moment.' if status == 'failed' else '', 'model': s.model_name,
            'helpful': s.helpful, 'by': (s.requested_by.get_full_name() or s.requested_by.get_username()) if s.requested_by_id else '',
            'at': timezone.localtime(s.created_at).strftime('%d %b %H:%M'),
            'minutes_ago': int((timezone.now() - s.created_at).total_seconds() // 60)}
