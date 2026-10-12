"""Laboratory management: quality control (Westgard rules), turnaround times, specimen reception and rejection,
critical-value call-backs, delta checks and the lab command-centre figures."""
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .models import (Analyzer, AnalyzerLog, AuditEvent, CriticalCall, LabOrder, LabRequest, LabResultValue, QCMaterial, QCRun, Reagent)

# ------------------------------------------------------------------ Westgard multi-rule QC
def westgard(material, value):
    """Evaluate a new control value against the material's mean/SD and its recent runs.
    Returns (status, rules). 1-2s is a warning; 1-3s, 2-2s, R-4s, 4-1s and 10x reject the run."""
    mean, sd = float(material.mean), float(material.sd) or 1.0
    z = (float(value) - mean) / sd
    prev = [(float(r.value) - mean) / sd for r in material.runs.order_by('-created_at')[:9]]
    seq = [z] + prev                                                     # newest first
    rules = []
    if abs(z) > 3:
        rules.append('1-3s')
    if len(seq) >= 2 and ((seq[0] > 2 and seq[1] > 2) or (seq[0] < -2 and seq[1] < -2)):
        rules.append('2-2s')
    if len(seq) >= 2 and ((seq[0] > 2 and seq[1] < -2) or (seq[0] < -2 and seq[1] > 2)):
        rules.append('R-4s')
    if len(seq) >= 4 and (all(x > 1 for x in seq[:4]) or all(x < -1 for x in seq[:4])):
        rules.append('4-1s')
    if len(seq) >= 10 and (all(x > 0 for x in seq[:10]) or all(x < 0 for x in seq[:10])):
        rules.append('10x')
    if rules:
        return 'rejected', rules
    if abs(z) > 2:
        return 'warning', ['1-2s']
    return 'accepted', []


@transaction.atomic
def record_qc(material, value, user, comment=''):
    status, rules = westgard(material, value)
    run = QCRun.objects.create(material=material, value=Decimal(str(value)), status=status, rules=', '.join(rules), comment=comment[:200], by=user)
    a = material.analyzer
    if status == 'rejected' and a.status == 'online':
        a.status, a.status_note = 'qc_hold', f'QC failed ({", ".join(rules)}) on {material.parameter.name} {material.level}'
        a.save(update_fields=['status', 'status_note', 'updated_at'])
        AnalyzerLog.objects.create(analyzer=a, kind='status', note=f'Put on QC hold: {a.status_note}', by=user)
    elif status != 'rejected' and a.status == 'qc_hold' and not _failing_today(a):
        a.status, a.status_note = 'online', 'QC passed'
        a.save(update_fields=['status', 'status_note', 'updated_at'])
        AnalyzerLog.objects.create(analyzer=a, kind='status', note='Back online: QC passed', by=user)
    return run


def _failing_today(analyzer):
    """True if any material's latest run today was rejected."""
    today = timezone.localdate()
    for m in analyzer.qc_materials.filter(active=True):
        last = m.runs.filter(created_at__date=today).order_by('-created_at').first()
        if last and last.status == 'rejected':
            return True
    return False


def qc_light(analyzer):
    """green / amber / red / grey for today's QC on this analyser."""
    today = timezone.localdate()
    states = []
    for m in analyzer.qc_materials.filter(active=True):
        last = m.runs.filter(created_at__date=today).order_by('-created_at').first()
        states.append(last.status if last else 'missing')
    if not states:
        return 'grey'
    if 'rejected' in states:
        return 'red'
    if 'missing' in states or 'warning' in states:
        return 'amber'
    return 'green'


# ------------------------------------------------------------------ turnaround time
def tat_target(order):
    return timedelta(hours=order.test.turnaround_hours or 24)


def tat_minutes(order):
    """Collection (or ordering) to result, in minutes; None if not resulted."""
    start = (order.request.collected_at if order.request_id and order.request.collected_at else order.created_at)
    if not order.resulted_at:
        return None
    m = (order.resulted_at - start).total_seconds() / 60
    return m if m >= 0 else None                         # ignore impossible times (e.g. imported or back-entered results)


def overdue_orders(limit=40):
    now = timezone.now()
    rows = []
    for o in LabOrder.objects.filter(status__in=['ordered', 'collected', 'processing']).select_related('test', 'request', 'encounter__patient')[:500]:
        start = o.request.collected_at if o.request_id and o.request.collected_at else o.created_at
        due = start + tat_target(o)
        if o.request_id and o.request.priority == 'stat':
            due = start + timedelta(hours=1)
        if now > due:
            rows.append({'o': o, 'late_min': int((now - due).total_seconds() / 60), 'due': due})
    return sorted(rows, key=lambda r: -r['late_min'])[:limit]


# ------------------------------------------------------------------ specimens
@transaction.atomic
def receive_specimen(lr, user):
    lr = LabRequest.objects.select_for_update().get(pk=lr.pk)
    if lr.received_at:
        return False
    lr.received_at, lr.received_by = timezone.now(), user
    if not lr.collected_at:
        lr.collected_at = lr.received_at
    lr.save(update_fields=['received_at', 'received_by', 'collected_at', 'updated_at'])
    lr.orders.filter(status='ordered').update(status='collected')
    AuditEvent.objects.create(actor=user, action='specimen_received', target=f'lab_request:{lr.pk}')
    return True


@transaction.atomic
def reject_specimen(lr, user, reason):
    """Reject the specimen: tests go back to 'ordered' for a new sample, and the requester is told why."""
    from .notify import notify
    lr = LabRequest.objects.select_for_update(of=('self',)).select_related('encounter__patient', 'requested_by').get(pk=lr.pk)
    lr.rejection_reason, lr.rejected_at = reason, timezone.now()
    lr.received_at = lr.collected_at = None; lr.specimen_id = ''; lr.recollect_count += 1
    lr.save()
    lr.orders.exclude(status__in=['cancelled', 'verified']).update(status='ordered')
    AuditEvent.objects.create(actor=user, action='specimen_rejected', target=f'lab_request:{lr.pk}', details={'reason': reason})
    who = [lr.requested_by, lr.encounter.clinician]
    notify(who, f'Specimen rejected · {lr.number}', f'{lr.get_rejection_reason_display()}. Please collect a new sample.', reverse('lab_request_detail', args=[lr.pk]), 'lab_rejected')
    return lr


# ------------------------------------------------------------------ critical values
def register_criticals(lr, user):
    """For each new critical value: a call-back task for the lab, and a bell/email alert to the requesting clinician."""
    from .notify import notify
    made = 0
    for v in LabResultValue.objects.filter(order__request=lr, flag__in=['LL', 'HH'], critical_call__isnull=True).select_related('parameter', 'order__encounter__patient'):
        CriticalCall.objects.create(value=v)
        made += 1
    if made:
        lr = LabRequest.objects.select_related('encounter', 'requested_by').get(pk=lr.pk)
        notify([lr.requested_by, lr.encounter.clinician], f'Critical result · {lr.number}', f'{made} critical value{"s" if made > 1 else ""}. The lab will phone you; open the result now.',
               reverse('lab_request_detail', args=[lr.pk]), 'lab_critical')
    return made


# ------------------------------------------------------------------ delta check
DELTA_LIMIT = {'HB': 20, 'PLT': 50, 'WBC': 50, 'K': 20, 'NA': 5, 'CREA': 50, 'GLU': 50, 'FBG': 50, 'INR': 50, 'TNI': 100}


def previous_values(patient, before_order):
    """Most recent earlier value per parameter for this patient (for the delta check on the result sheet)."""
    out = {}
    for v in (LabResultValue.objects.filter(order__encounter__patient=patient, order__status__in=['resulted', 'verified'], value_number__isnull=False)
              .exclude(order=before_order).select_related('parameter', 'order').order_by('order__resulted_at')):
        out[v.parameter_id] = v
    return out


def delta(prev, new_value, code):
    """Percentage change and whether it exceeds the parameter's delta limit."""
    try:
        a, b = float(prev), float(new_value)
    except (TypeError, ValueError):
        return None, False
    if not a:
        return None, False
    pct = (b - a) / abs(a) * 100
    return round(pct), abs(pct) >= DELTA_LIMIT.get(code, 60)


# ------------------------------------------------------------------ command centre
def dashboard():
    now = timezone.now()
    today = timezone.localdate()
    reqs_today = LabRequest.objects.filter(created_at__date=today)
    orders = LabOrder.objects.filter(created_at__gte=now - timedelta(days=7)).select_related('test__category', 'request')
    stage = Counter()
    for o in LabOrder.objects.filter(status__in=['ordered', 'collected', 'processing', 'resulted']):
        stage[o.status] += 1
    done_today = [o for o in orders if o.resulted_at and timezone.localtime(o.resulted_at).date() == today]
    tats = sorted(t for t in (tat_minutes(o) for o in done_today) if t is not None)
    median = tats[len(tats) // 2] if tats else None
    within = sum(1 for o in done_today if tat_minutes(o) is not None and tat_minutes(o) <= tat_target(o).total_seconds() / 60)
    hours = [0] * 24
    for o in done_today:
        hours[timezone.localtime(o.resulted_at).hour] += 1
    by_section = defaultdict(list)
    for o in orders:
        t = tat_minutes(o)
        if t is not None:
            by_section[o.test.category.name if o.test.category else 'Other'].append(t)
    sections = sorted(({'name': k, 'n': len(v), 'median': sorted(v)[len(v) // 2]} for k, v in by_section.items()), key=lambda x: -x['n'])
    rej7 = LabRequest.objects.filter(rejected_at__gte=now - timedelta(days=7))
    recv7 = LabRequest.objects.filter(created_at__gte=now - timedelta(days=7)).count()   # every specimen expected in the period
    analyzers = [{'a': a, 'light': qc_light(a)} for a in Analyzer.objects.all()]
    reagents = Reagent.objects.filter(Q(expiry__lte=today + timedelta(days=21)) | Q(quantity__lte=0) | Q(quantity__lte=models_F('reorder_level')))
    return {
        'received_today': reqs_today.filter(received_at__isnull=False).count(), 'requests_today': reqs_today.count(),
        'stage': [('Waiting for sample', stage['ordered']), ('Sample collected', stage['collected']), ('In analysis', stage['processing']), ('Awaiting verification', stage['resulted'])],
        'stat_open': LabOrder.objects.filter(request__priority='stat', status__in=['ordered', 'collected', 'processing']).count(),
        'overdue': overdue_orders(), 'median_tat': round(median) if median is not None else None, 'done_today': len(done_today),
        'within_tat': round(within * 100 / len(done_today)) if done_today else None, 'hours': hours, 'sections': sections,
        'rejection_rate': round(rej7.count() * 100 / recv7) if recv7 else 0, 'rejections': Counter(r.get_rejection_reason_display() for r in rej7).most_common(),
        'analyzers': analyzers, 'reagents': reagents[:12],
        'critical_pending': CriticalCall.objects.filter(called_at__isnull=True).select_related('value__parameter', 'value__order__encounter__patient', 'value__order__request')[:20],
    }


def models_F(name):
    from django.db.models import F
    return F(name)
