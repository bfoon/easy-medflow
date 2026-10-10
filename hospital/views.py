import json
from datetime import timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (VITAL_FIELDS, AdmissionForm, AllergyForm, ConditionForm, EncounterForm, FormDefinitionForm,
                    LabOrderForm, PatientForm, PrescriptionForm, ReferralForm, TicketForm, WorkflowDefinitionForm)
from .models import (Admission, Attendance, AuditEvent, Bed, Department, Encounter, FormDefinition, FormSubmission,
                     LabOrder, Medication, Patient, Prescription, QueueTicket, Referral, Signature, Ward,
                     WorkflowDefinition, WorkflowRun)
from .services import advance_workflow, assign_bed, availability, discharge, dispense, prescription_warnings, sign_document

# Staff accounts are provisioned by administrators; there is no public signup.
ROLES = {
    'clinical': {'doctor', 'nurse', 'admin'},
    'reception': {'reception', 'nurse', 'admin'},
    'pharmacy': {'pharmacy', 'admin'},
    'lab': {'lab', 'doctor', 'admin'},
    'beds': {'nurse', 'admin', 'management'},
    'studio': {'admin', 'management'},
    'all': {'admin', 'doctor', 'nurse', 'reception', 'lab', 'pharmacy', 'finance', 'management'},
}


def role_of(user):
    if user.is_superuser:
        return 'admin'
    p = getattr(user, 'hospital_staff', None)
    return p.role if p and p.active else None


def authorize(request, role='all'):
    if request.user.is_superuser:
        return
    p = getattr(request.user, 'hospital_staff', None)
    if not p or not p.active or p.role not in ROLES[role]:
        raise PermissionDenied('Your account is not authorized for this module.')


def audit(request, action, target, details=None):
    AuditEvent.objects.create(actor=request.user, action=action, target=target, details=details or {},
                              ip_address=request.META.get('REMOTE_ADDR'))


def edit_page(request, formclass, title, return_to, role='all', save=None, template='hospital/form.html',
              subtitle='', extra=None):
    """Generic create page. GET parameters prefill the form, e.g. ?patient=4 from the chart."""
    authorize(request, role)
    initial = {k: v for k, v in request.GET.items()}
    form = formclass(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                obj = save(form) if save else form.save()
            audit(request, 'create', f'{obj._meta.label}:{obj.pk}')
            messages.success(request, f'{title} saved.')
            return redirect(return_to(obj) if callable(return_to) else return_to)
        except (ValidationError, ValueError) as exc:
            form.add_error(None, '; '.join(exc.messages) if hasattr(exc, 'messages') else str(exc))
    ctx = {'form': form, 'title': title, 'subtitle': subtitle}
    ctx.update(extra or {})
    return render(request, template, ctx)


# ---------------------------------------------------------------- dashboard + live data

def hospital_snapshot():
    today = timezone.localdate()
    tickets_today = QueueTicket.objects.filter(created_at__date=today)
    waiting = QueueTicket.objects.filter(status='waiting').count()
    beds_total = Bed.objects.count()
    beds_occupied = Bed.objects.filter(state='occupied').count()
    flow = [
        {'key': 'arrived', 'label': 'Arrived today', 'value': tickets_today.count(), 'url': reverse('queue')},
        {'key': 'waiting', 'label': 'Waiting', 'value': waiting, 'url': reverse('queue')},
        {'key': 'consult', 'label': 'With a clinician', 'value': QueueTicket.objects.filter(status__in=['called', 'in_service']).count(), 'url': reverse('queue')},
        {'key': 'lab', 'label': 'Lab pending', 'value': LabOrder.objects.filter(status__in=['ordered', 'collected', 'processing']).count(), 'url': reverse('labs')},
        {'key': 'pharmacy', 'label': 'Rx to dispense', 'value': Prescription.objects.filter(state='signed').count(), 'url': reverse('pharmacy')},
        {'key': 'admitted', 'label': 'Admitted', 'value': Admission.objects.filter(discharged_at__isnull=True).count(), 'url': reverse('beds')},
    ]
    # The "hospital pulse": resting 64 bpm, rising with waiting-room load. A mood indicator, not a clinical metric.
    urgent = QueueTicket.objects.filter(status='waiting', priority__lte=2).count()
    bpm = min(64 + waiting * 3 + urgent * 8, 160)
    mood = 'Calm' if bpm < 85 else 'Busy' if bpm < 115 else 'Surging'
    return {
        'flow': flow, 'waiting': waiting, 'urgent': urgent, 'bpm': bpm, 'mood': mood,
        'beds_total': beds_total, 'beds_occupied': beds_occupied,
        'beds_free': Bed.objects.filter(state='available').count(),
        'occupancy': round(beds_occupied * 100 / beds_total) if beds_total else 0,
        'served_today': tickets_today.filter(status='completed').count(),
        'time': timezone.localtime().strftime('%H:%M:%S'),
    }


ACTION_LABELS = {
    'create': 'created', 'queue_transition': 'moved a ticket', 'dispense': 'dispensed',
    'esign': 'e-signed', 'discharge': 'discharged', 'attendance': 'logged attendance', 'workflow_action': 'acted on a workflow',
    'submit_form': 'submitted a form', 'lab_update': 'updated a lab order', 'referral_update': 'updated a referral',
    'complete_encounter': 'completed a visit', 'bed_ready': 'readied a bed', 'prescribing_warning_review': 'reviewed Rx safety',
}


@login_required
def dashboard(request):
    authorize(request)
    snap = hospital_snapshot()
    today = timezone.localdate()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    counts = {}
    for t in QueueTicket.objects.filter(created_at__date__gte=days[0]).values_list('created_at', flat=True):
        d = timezone.localtime(t).date()
        counts[d] = counts.get(d, 0) + 1
    week = [{'label': d.strftime('%a'), 'value': counts.get(d, 0), 'today': d == today} for d in days]
    peak = max([w['value'] for w in week] + [1])
    for w in week:
        w['pct'] = max(4, round(w['value'] * 100 / peak))
    departments = (Department.objects.annotate(
        waiting=Count('queueticket', filter=Q(queueticket__status='waiting')),
        active=Count('queueticket', filter=Q(queueticket__status__in=['called', 'in_service'])))
        .filter(Q(waiting__gt=0) | Q(active__gt=0)).order_by('-waiting')[:6])
    dept_peak = max([d.waiting + d.active for d in departments] + [1])
    for d in departments:
        d.pct = round((d.waiting + d.active) * 100 / dept_peak)
    low_stock = [(m, availability(m)) for m in Medication.objects.filter(active=True)]
    low_stock = sorted([x for x in low_stock if x[1] <= x[0].reorder_level], key=lambda x: x[1])[:5]
    activity = [{'e': e, 'label': ACTION_LABELS.get(e.action, e.action.replace('_', ' '))}
                for e in AuditEvent.objects.select_related('actor').exclude(action='view_chart')[:8]]
    hour = timezone.localtime().hour
    greeting = 'Good morning' if hour < 12 else 'Good afternoon' if hour < 18 else 'Good evening'
    return render(request, 'hospital/dashboard.html', {
        **snap, 'week': week, 'departments': departments, 'low_stock': low_stock, 'activity': activity,
        'greeting': greeting, 'urgent_tickets': QueueTicket.objects.filter(status='waiting', priority__lte=2)
        .select_related('patient', 'department').order_by('priority', 'created_at')[:4],
        'patients_total': Patient.objects.count(),
        'referrals_open': Referral.objects.exclude(status__in=['completed', 'cancelled', 'declined']).count(),
        'on_duty': Attendance.objects.filter(clock_out__isnull=True).count(),
    })


@login_required
def api_pulse(request):
    authorize(request)
    return JsonResponse(hospital_snapshot())


@login_required
def api_search(request):
    authorize(request)
    q = request.GET.get('q', '').strip()[:60]
    if len(q) < 2:
        return JsonResponse({'results': []})
    qs = Patient.objects.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(mrn__icontains=q) | Q(phone__icontains=q))[:8]
    return JsonResponse({'results': [{'name': p.full_name, 'mrn': p.mrn, 'initials': p.initials, 'age': p.age,
                                      'url': reverse('patient_chart', args=[p.pk])} for p in qs]})


# ---------------------------------------------------------------- patients

@login_required
def patients(request):
    authorize(request)
    q = request.GET.get('q', '').strip()[:100]
    qs = Patient.objects.annotate(allergy_count=Count('allergies', filter=Q(allergies__status='active'), distinct=True),
                                  visit_count=Count('encounters', distinct=True)).order_by('-created_at')
    if q:
        qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(mrn__icontains=q) | Q(phone__icontains=q))
    admitted = set(Admission.objects.filter(discharged_at__isnull=True).values_list('encounter__patient_id', flat=True))
    return render(request, 'hospital/patients.html', {'rows': qs[:120], 'q': q, 'admitted': admitted, 'total': Patient.objects.count()})


@login_required
def patient_new(request):
    return edit_page(request, PatientForm, 'Register patient', lambda o: reverse('patient_chart', args=[o.pk]), 'reception',
                     subtitle='A medical record number is assigned automatically.')


@login_required
def patient_chart(request, pk):
    authorize(request)
    p = get_object_or_404(Patient, pk=pk)
    audit(request, 'view_chart', f'patient:{p.pk}')
    encounters = list(p.encounters.select_related('clinician', 'department').order_by('-created_at')[:50])
    prescriptions = Prescription.objects.filter(encounter__patient=p).select_related('medication').order_by('-created_at')[:100]
    labs = LabOrder.objects.filter(encounter__patient=p).select_related('test').order_by('-created_at')[:100]
    referrals = Referral.objects.filter(encounter__patient=p).order_by('-created_at')
    admissions = list(Admission.objects.filter(encounter__patient=p).select_related('bed__ward').order_by('-admitted_at'))
    # One merged, reverse-chronological timeline across every clinical record type.
    timeline = (
        [{'when': e.created_at, 'kind': 'visit', 'title': e.reason, 'meta': e.get_status_display(), 'url': reverse('encounter_detail', args=[e.pk])} for e in encounters] +
        [{'when': x.created_at, 'kind': 'rx', 'title': str(x.medication), 'meta': x.get_state_display()} for x in prescriptions] +
        [{'when': x.created_at, 'kind': 'lab', 'title': x.test.name, 'meta': x.get_status_display(), 'flag': x.abnormal} for x in labs] +
        [{'when': x.created_at, 'kind': 'referral', 'title': f'Referral to {x.destination}', 'meta': x.get_status_display()} for x in referrals] +
        [{'when': x.admitted_at, 'kind': 'admission', 'title': f'Admitted to {x.bed}', 'meta': 'Discharged' if x.discharged_at else 'Current'} for x in admissions]
    )
    timeline.sort(key=lambda x: x['when'], reverse=True)
    latest = next((e for e in encounters if e.vitals), None)
    vitals = [(lbl, unit, latest.vitals.get(k)) for k, lbl, unit, _ in VITAL_FIELDS if latest.vitals.get(k)] if latest else []
    return render(request, 'hospital/chart.html', {
        'p': p, 'allergies': p.allergies.order_by('status', '-created_at'), 'conditions': p.conditions.order_by('status', '-created_at'),
        'encounters': encounters, 'prescriptions': prescriptions, 'labs': labs, 'referrals': referrals, 'admissions': admissions,
        'submissions': p.submissions.select_related('definition').prefetch_related('signature_set').order_by('-created_at'),
        'available_forms': FormDefinition.objects.filter(published=True), 'timeline': timeline[:40],
        'vitals': vitals, 'vitals_at': latest.created_at if latest else None,
        'open_encounter': next((e for e in encounters if e.status == 'open'), None),
        'current_admission': next((a for a in admissions if not a.discharged_at), None),
    })


@login_required
def allergy_new(request, pk):
    p = get_object_or_404(Patient, pk=pk)

    def save(form):
        o = form.save(commit=False); o.patient = p; o.verified_by = request.user; o.save(); return o
    return edit_page(request, AllergyForm, 'Record allergy', reverse('patient_chart', args=[p.pk]), 'clinical', save,
                     subtitle=f'For {p.full_name} · {p.mrn}')


@login_required
def condition_new(request, pk):
    p = get_object_or_404(Patient, pk=pk)

    def save(form):
        o = form.save(commit=False); o.patient = p; o.save(); return o
    return edit_page(request, ConditionForm, 'Add condition', reverse('patient_chart', args=[p.pk]), 'clinical', save,
                     subtitle=f'For {p.full_name} · {p.mrn}')


# ---------------------------------------------------------------- encounters

@login_required
def encounter_new(request):
    def save(form):
        o = form.save(commit=False)
        if not o.clinician_id:
            o.clinician = request.user
        o.save(); return o
    return edit_page(request, EncounterForm, 'New clinical encounter', lambda o: reverse('encounter_detail', args=[o.pk]),
                     'clinical', save, template='hospital/encounter_form.html')


@login_required
def encounter_detail(request, pk):
    authorize(request, 'clinical')
    e = get_object_or_404(Encounter.objects.select_related('patient', 'clinician', 'department'), pk=pk)
    audit(request, 'view_chart', f'encounter:{e.pk}')
    rx = e.prescriptions.select_related('medication')
    return render(request, 'hospital/encounter.html', {
        'e': e, 'p': e.patient, 'labs': e.labs.select_related('test'), 'referrals': e.referrals.all(),
        'prescriptions': [(x, prescription_warnings(e, x.medication, x.quantity)) for x in rx],
        'allergies': e.patient.allergies.filter(status='active'), 'admissions': e.admissions.select_related('bed'),
        'vitals': [(lbl, unit, e.vitals.get(k)) for k, lbl, unit, _ in VITAL_FIELDS if e.vitals.get(k)],
        'can_sign': role_of(request.user) in ('doctor', 'admin'),
    })


@login_required
@require_POST
def encounter_complete(request, pk):
    authorize(request, 'clinical')
    with transaction.atomic():
        e = get_object_or_404(Encounter.objects.select_for_update(), pk=pk)
        if e.status != 'open':
            return HttpResponseBadRequest('Encounter already closed')
        e.status = 'completed'; e.completed_at = timezone.now(); e.save(update_fields=['status', 'completed_at', 'updated_at'])
        e.tickets.filter(status__in=['called', 'in_service']).update(status='completed', completed_at=timezone.now())
        audit(request, 'complete_encounter', f'encounter:{e.pk}')
    messages.success(request, 'Visit completed.')
    return redirect('encounter_detail', pk=pk)


# ---------------------------------------------------------------- queue

@login_required
def queue(request):
    authorize(request)
    active = list(QueueTicket.objects.select_related('patient', 'department').exclude(status__in=['completed', 'cancelled']).order_by('priority', 'created_at')[:300])
    dept = request.GET.get('dept', '')
    if dept:
        active = [t for t in active if str(t.department_id) == dept]
    cols = [('waiting', 'Waiting'), ('called', 'Called'), ('in_service', 'In consultation'), ('skipped', 'Skipped')]
    board = [{'key': k, 'label': lbl, 'tickets': [t for t in active if t.status == k]} for k, lbl in cols]
    return render(request, 'hospital/queue.html', {
        'board': board, 'departments': Department.objects.order_by('name'), 'dept': dept,
        'completed_today': QueueTicket.objects.filter(status='completed', completed_at__date=timezone.localdate()).count()})


@login_required
def ticket_new(request):
    def save(form):
        t = form.save(commit=False)
        if not t.encounter_id:
            t.encounter = Encounter.objects.create(patient=t.patient, department=t.department, reason=f'{t.department.name} visit')
        t.full_clean(); t.save(); return t
    return edit_page(request, TicketForm, 'Issue queue ticket', 'queue', 'reception', save,
                     subtitle='Leave “encounter” blank and a new visit opens automatically.')


TICKET_FLOW = {'waiting': {'called', 'cancelled'}, 'called': {'in_service', 'skipped', 'waiting'},
               'in_service': {'completed'}, 'skipped': {'waiting', 'cancelled'}}


@login_required
@require_POST
def ticket_transition(request, pk, state):
    authorize(request, 'reception' if state == 'cancelled' else 'all')
    with transaction.atomic():
        t = get_object_or_404(QueueTicket.objects.select_for_update(), pk=pk)
        if state not in TICKET_FLOW.get(t.status, set()):
            if request.headers.get('x-requested-with') == 'fetch':
                return JsonResponse({'ok': False, 'error': f'A {t.get_status_display().lower()} ticket cannot move there.'}, status=400)
            return HttpResponseBadRequest('Invalid status transition')
        t.status = state
        now = timezone.now()
        if state == 'called':
            t.called_at = now
            counter = request.POST.get('counter', '').strip()[:40]
            if counter:
                t.counter = counter
        if state == 'in_service':
            t.started_at = now
        if state == 'completed':
            t.completed_at = now
        t.save()
        audit(request, 'queue_transition', f'ticket:{t.pk}', {'status': state})
    if request.headers.get('x-requested-with') == 'fetch':
        return JsonResponse({'ok': True, 'status': state})
    return redirect(request.POST.get('next') or 'queue')


def queue_payload():
    now_serving = QueueTicket.objects.filter(status__in=['called', 'in_service']).select_related('department').order_by('-called_at')[:6]
    upcoming = QueueTicket.objects.filter(status='waiting').select_related('department').order_by('priority', 'created_at')[:12]
    return {
        'serving': [{'id': t.pk, 'code': t.display_code or t.ticket_number, 'dept': t.department.name, 'counter': t.counter or t.department.name,
                     'status': t.status, 'called_at': t.called_at.isoformat() if t.called_at else None} for t in now_serving],
        'upcoming': [{'code': t.display_code or t.ticket_number, 'dept': t.department.name, 'priority': t.priority} for t in upcoming],
        'waiting': QueueTicket.objects.filter(status='waiting').count(),
        'time': timezone.localtime().strftime('%H:%M'),
    }


@login_required
def queue_display(request):
    """Full-screen waiting-room board. Shows ticket codes only — never patient names."""
    authorize(request)
    return render(request, 'hospital/queue_display.html', {'initial': queue_payload()})


@login_required
def api_queue(request):
    authorize(request)
    return JsonResponse(queue_payload())


# ---------------------------------------------------------------- referrals

REFERRAL_FLOW = {'draft': ['sent', 'cancelled'], 'sent': ['accepted', 'declined', 'cancelled'],
                 'accepted': ['transferred', 'cancelled'], 'transferred': ['completed'], 'declined': [], 'completed': [], 'cancelled': []}
REFERRAL_STAGES = ['draft', 'sent', 'accepted', 'transferred', 'completed']


@login_required
def referrals(request):
    authorize(request)
    rows = list(Referral.objects.select_related('encounter__patient').order_by('-created_at')[:150])
    for r in rows:
        r.next_states = REFERRAL_FLOW.get(r.status, [])
        idx = REFERRAL_STAGES.index(r.status) if r.status in REFERRAL_STAGES else -1
        r.track = [{'name': s, 'state': 'done' if idx > i else 'current' if idx == i else 'todo'} for i, s in enumerate(REFERRAL_STAGES)]
    counts = {u: sum(1 for r in rows if r.urgency == u and r.status not in ('completed', 'cancelled', 'declined')) for u in ('emergency', 'urgent', 'routine')}
    return render(request, 'hospital/referrals.html', {'rows': rows, 'counts': counts})


@login_required
def referral_new(request):
    def save(form):
        o = form.save(commit=False)
        if o.status == 'sent':
            o.sent_at = timezone.now()
        o.save(); return o
    return edit_page(request, ReferralForm, 'Create referral', 'referrals', 'clinical', save)


@login_required
@require_POST
def referral_transition(request, pk, state):
    authorize(request, 'clinical')
    with transaction.atomic():
        r = get_object_or_404(Referral.objects.select_for_update(), pk=pk)
        if state not in REFERRAL_FLOW.get(r.status, []):
            return HttpResponseBadRequest('Invalid referral transition')
        r.status = state
        if state == 'sent':
            r.sent_at = timezone.now()
        if state == 'completed':
            r.completed_at = timezone.now()
        r.save()
        audit(request, 'referral_update', f'referral:{r.pk}', {'status': state})
    messages.success(request, f'Referral marked {r.get_status_display().lower()}.')
    return redirect('referrals')


# ---------------------------------------------------------------- laboratory

@login_required
def labs(request):
    authorize(request)
    orders = list(LabOrder.objects.select_related('encounter__patient', 'test').order_by('created_at')[:300])
    lanes = [('ordered', 'Ordered'), ('collected', 'Specimen collected'), ('processing', 'Processing'), ('resulted', 'Awaiting verification')]
    board = [{'key': k, 'label': lbl, 'orders': [o for o in orders if o.status == k]} for k, lbl in lanes]
    done = sorted([o for o in orders if o.status == 'verified'], key=lambda o: o.verified_at or o.created_at, reverse=True)[:20]
    return render(request, 'hospital/labs.html', {'board': board, 'done': done})


@login_required
def lab_new(request):
    return edit_page(request, LabOrderForm, 'Order laboratory test', 'labs', 'clinical')


LAB_FLOW = {'collect': ('ordered', 'collected'), 'process': ('collected', 'processing'),
            'result': ('processing', 'resulted'), 'verify': ('resulted', 'verified')}


@login_required
@require_POST
def lab_update(request, pk, step):
    authorize(request, 'lab')
    with transaction.atomic():
        o = get_object_or_404(LabOrder.objects.select_for_update(), pk=pk)
        if step == 'cancel':
            if o.status in ('verified', 'cancelled'):
                return HttpResponseBadRequest('Cannot cancel')
            o.status = 'cancelled'
        elif step in LAB_FLOW and o.status == LAB_FLOW[step][0]:
            if step == 'collect':
                o.specimen_id = request.POST.get('specimen_id', '').strip()[:80] or o.specimen_id or f'SP-{o.pk:06d}'
            if step == 'result':
                result = request.POST.get('result', '').strip()
                if not result:
                    messages.error(request, 'Enter a result before submitting.')
                    return redirect('labs')
                o.result = result[:4000]; o.reference_range = request.POST.get('reference_range', '')[:100]
                o.abnormal = request.POST.get('abnormal') == 'on'; o.resulted_at = timezone.now()
            if step == 'verify':
                o.verified_by = request.user; o.verified_at = timezone.now()
            o.status = LAB_FLOW[step][1]
        else:
            return HttpResponseBadRequest('Invalid lab step')
        o.save()
        audit(request, 'lab_update', f'lab_order:{o.pk}', {'status': o.status})
    return redirect('labs')


# ---------------------------------------------------------------- pharmacy

@login_required
def pharmacy(request):
    authorize(request)
    stock = []
    for m in Medication.objects.filter(active=True).order_by('name')[:200]:
        qty = availability(m)
        stock.append({'m': m, 'qty': qty, 'pct': min(100, round(qty * 100 / max(m.reorder_level * 3, 1))),
                      'level': 'out' if qty == 0 else 'low' if qty <= m.reorder_level else 'ok'})
    rx = list(Prescription.objects.select_related('encounter__patient', 'medication', 'signed_by').order_by('-created_at')[:150])
    lanes = [('draft', 'Drafts awaiting prescriber', [x for x in rx if x.state == 'draft']),
             ('signed', 'Signed · ready to dispense', [x for x in rx if x.state == 'signed']),
             ('dispensed', 'Dispensed', [x for x in rx if x.state == 'dispensed'][:12])]
    return render(request, 'hospital/pharmacy.html', {'stock': stock, 'lanes': lanes,
                                                      'can_sign': role_of(request.user) in ('doctor', 'admin'),
                                                      'can_dispense': role_of(request.user) in ('pharmacy', 'admin')})


@login_required
def prescription_new(request):
    def save(form):
        p = form.save(commit=False)
        warnings = prescription_warnings(p.encounter, p.medication, p.quantity)
        if not p.allergy_reviewed:
            raise ValidationError('Confirm that you reviewed the allergy history before saving.')
        if warnings['possible_allergy_matches'] and not p.override_reason.strip():
            raise ValidationError('Possible allergy match. Document a clinical justification or choose another medication.')
        p.save()
        audit(request, 'prescribing_warning_review', f'prescription:{p.pk}',
              {'possible_exact_match': bool(warnings['possible_allergy_matches']), 'stock': warnings['inventory_available']})
        return p
    return edit_page(request, PrescriptionForm, 'New prescription', 'pharmacy', 'clinical', save,
                     template='hospital/prescription_form.html', subtitle='Saved as a draft until a prescriber signs it.')


@login_required
def api_rx_check(request):
    """Live safety panel for the prescription form: allergies and stock for the chosen visit + medication."""
    authorize(request, 'clinical')
    try:
        e = Encounter.objects.select_related('patient').get(pk=request.GET.get('encounter'))
        m = Medication.objects.get(pk=request.GET.get('medication'))
        qty = max(1, int(request.GET.get('quantity') or 1))
    except (Encounter.DoesNotExist, Medication.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'ready': False})
    w = prescription_warnings(e, m, qty)
    return JsonResponse({'ready': True, 'patient': e.patient.full_name, 'medication': str(m), **w})


@login_required
@require_POST
def prescription_sign(request, pk):
    authorize(request, 'clinical')
    if role_of(request.user) not in ('doctor', 'admin'):
        raise PermissionDenied('Prescriber role required')
    with transaction.atomic():
        p = get_object_or_404(Prescription.objects.select_for_update().select_related('encounter__patient', 'medication'), pk=pk)
        if p.state != 'draft':
            return HttpResponseBadRequest('Not a draft')
        w = prescription_warnings(p.encounter, p.medication, p.quantity)
        if not p.allergy_reviewed or (w['possible_allergy_matches'] and not p.override_reason.strip()):
            return HttpResponseBadRequest('Allergy review incomplete')
        p.state = 'signed'; p.signed_by = request.user; p.signed_at = timezone.now()
        p.save(update_fields=['state', 'signed_by', 'signed_at'])
        sig = sign_document('prescription', p, request.user, 'Prescriber authorization')
    messages.success(request, f'Prescription signed · SHA-256 {sig.document_hash[:12]}…')
    return redirect(request.POST.get('next') or 'pharmacy')


@login_required
@require_POST
def prescription_dispense(request, pk):
    authorize(request, 'pharmacy')
    try:
        dispense(get_object_or_404(Prescription, pk=pk), request.user)
        messages.success(request, 'Dispensed. Stock was drawn from the earliest-expiring batches first.')
    except ValidationError as e:
        messages.error(request, '; '.join(e.messages))
    return redirect('pharmacy')


# ---------------------------------------------------------------- beds

@login_required
def beds(request):
    authorize(request)
    active = {a.bed_id: a for a in Admission.objects.filter(discharged_at__isnull=True).select_related('encounter__patient', 'bed__ward')}
    wards = []
    for w in Ward.objects.prefetch_related('bed_set').order_by('name'):
        bl = sorted(w.bed_set.all(), key=lambda b: b.code)
        for b in bl:
            b.admission = active.get(b.pk)
        wards.append({'ward': w, 'beds': bl, 'free': sum(1 for b in bl if b.state == 'available'), 'total': len(bl)})
    counts = dict(Bed.objects.values_list('state').annotate(n=Count('id')))
    return render(request, 'hospital/beds.html', {'wards': wards, 'counts': counts, 'admissions': list(active.values())})


@login_required
def admission_new(request):
    def save(form):
        return assign_bed(form.cleaned_data['encounter'], form.cleaned_data['bed'])
    return edit_page(request, AdmissionForm, 'Admit patient', 'beds', 'beds', save)


@login_required
@require_POST
def admission_discharge(request, pk):
    authorize(request, 'beds')
    try:
        discharge(get_object_or_404(Admission, pk=pk)); audit(request, 'discharge', f'admission:{pk}')
        messages.success(request, 'Patient discharged. The bed is now marked for cleaning.')
    except ValidationError as e:
        messages.error(request, '; '.join(e.messages))
    return redirect('beds')


@login_required
@require_POST
def bed_ready(request, pk):
    authorize(request, 'beds')
    with transaction.atomic():
        b = get_object_or_404(Bed.objects.select_for_update(), pk=pk)
        if b.state not in ('cleaning', 'maintenance'):
            return HttpResponseBadRequest('Bed is not being cleaned')
        b.state = 'available'; b.save(update_fields=['state', 'updated_at'])
        audit(request, 'bed_ready', f'bed:{b.pk}')
    messages.success(request, f'Bed {b.code} is ready for the next patient.')
    return redirect('beds')


# ---------------------------------------------------------------- attendance

@login_required
def attendance(request):
    authorize(request)
    if request.method == 'POST':
        with transaction.atomic():
            active = Attendance.objects.select_for_update().filter(staff=request.user, clock_out__isnull=True).order_by('-clock_in').first()
            action = request.POST.get('action')
            if action == 'in' and not active:
                Attendance.objects.create(staff=request.user, note=request.POST.get('note', '')[:250])
                messages.success(request, 'Clocked in. Have a good shift.')
            elif action == 'out' and active:
                active.clock_out = timezone.now(); active.save(update_fields=['clock_out'])
                messages.success(request, 'Clocked out.')
            audit(request, 'attendance', f'employee:{request.user.pk}', {'action': action})
        return redirect('attendance')
    active = Attendance.objects.filter(staff=request.user, clock_out__isnull=True).order_by('-clock_in').first()
    recent = list(Attendance.objects.filter(staff=request.user).order_by('-clock_in')[:14])
    week_start = timezone.now() - timedelta(days=7)
    for a in recent:
        a.hours = round(((a.clock_out or timezone.now()) - a.clock_in).total_seconds() / 3600, 1)
    on_duty = Attendance.objects.filter(clock_out__isnull=True).select_related('staff', 'staff__hospital_staff').order_by('clock_in')
    return render(request, 'hospital/attendance.html', {
        'active': active, 'recent': recent, 'on_duty': on_duty,
        'week_hours': round(sum(a.hours for a in recent if a.clock_in >= week_start), 1)})


# ---------------------------------------------------------------- forms & workflow studio

FIELD_TYPES = ['text', 'textarea', 'date', 'number', 'checkbox', 'select']


@login_required
def studio(request):
    authorize(request)
    runs = list(WorkflowRun.objects.filter(status='open').select_related('definition', 'submission__patient', 'submission__definition')[:50])
    for r in runs:
        steps = r.definition.steps if isinstance(r.definition.steps, list) else []
        r.step_list = [{'name': s.get('name'), 'role': s.get('role'),
                        'state': 'done' if i < r.step_index else 'current' if i == r.step_index else 'todo'} for i, s in enumerate(steps)]
    return render(request, 'hospital/studio.html', {
        'forms': FormDefinition.objects.annotate(n=Count('submissions')).order_by('name'),
        'workflows': WorkflowDefinition.objects.order_by('name'),
        'submissions': FormSubmission.objects.select_related('definition', 'patient').prefetch_related('signature_set').order_by('-created_at')[:30],
        'runs': runs, 'patients': Patient.objects.order_by('last_name')[:300],
        'signatures': Signature.objects.select_related('signer').order_by('-signed_at')[:8],
    })


@login_required
def form_definition_new(request):
    def save(form):
        obj = form.save(commit=False)
        fields = obj.schema.get('fields', []) if isinstance(obj.schema, dict) else None
        if not isinstance(fields, list) or not fields or len(fields) > 60:
            raise ValidationError('Add between 1 and 60 fields.')
        keys = set()
        for f in fields:
            if not isinstance(f, dict) or f.get('type') not in FIELD_TYPES or not isinstance(f.get('key'), str) or not f['key'].isidentifier() or f['key'] in keys:
                label = f.get('label', '?') if isinstance(f, dict) else '?'
                raise ValidationError(f'Field “{label}” has an invalid or duplicate key.')
            keys.add(f['key'])
            if f['type'] == 'select' and (not isinstance(f.get('options'), list) or not f['options'] or len(f['options']) > 100 or any(not isinstance(o, str) for o in f['options'])):
                raise ValidationError(f'Select field “{f.get("label")}” needs at least one option.')
        obj.save(); return obj
    return edit_page(request, FormDefinitionForm, 'Design a form', 'studio', 'studio', save,
                     template='hospital/form_builder.html', extra={'field_types': FIELD_TYPES})


@login_required
def workflow_definition_new(request):
    def save(form):
        obj = form.save(commit=False)
        if not isinstance(obj.steps, list) or not 1 <= len(obj.steps) <= 20:
            raise ValidationError('Add between 1 and 20 approval steps.')
        for s in obj.steps:
            if not isinstance(s, dict) or s.get('role') not in ROLES['all'] or not isinstance(s.get('name'), str) or not s['name'].strip():
                raise ValidationError('Every step needs a name and a valid staff role.')
        obj.save(); return obj
    return edit_page(request, WorkflowDefinitionForm, 'Design an approval workflow', 'studio', 'studio', save,
                     template='hospital/workflow_builder.html', extra={'roles': sorted(ROLES['all'])})


@login_required
def fill_form_pick(request):
    authorize(request, 'clinical')
    try:
        return redirect('fill_form', pk=int(request.GET.get('form')), patient_id=int(request.GET.get('patient')))
    except (TypeError, ValueError):
        messages.error(request, 'Choose both a form and a patient.')
        return redirect('studio')


@login_required
def fill_form(request, pk, patient_id):
    authorize(request, 'clinical')
    definition = get_object_or_404(FormDefinition, pk=pk, published=True)
    patient = get_object_or_404(Patient, pk=patient_id)
    dynamic = {}
    for fld in definition.schema.get('fields', []):
        key, typ, label, req = fld['key'], fld['type'], fld.get('label', fld['key']), bool(fld.get('required'))
        if typ == 'checkbox':
            f = forms.BooleanField(label=label, required=False)
        elif typ == 'select':
            f = forms.ChoiceField(label=label, choices=[(x, x) for x in fld.get('options', [])], required=req)
        elif typ == 'number':
            f = forms.DecimalField(label=label, required=req)
        elif typ == 'date':
            f = forms.DateField(label=label, required=req, widget=forms.DateInput(attrs={'type': 'date'}))
        else:
            f = forms.CharField(label=label, required=req, max_length=4000,
                                widget=forms.Textarea(attrs={'rows': 3}) if typ == 'textarea' else forms.TextInput)
        f.widget.attrs['class'] = 'form-check-input' if typ == 'checkbox' else 'form-select' if typ == 'select' else 'form-control'
        dynamic[key] = f
    DynamicForm = type('DynamicForm', (forms.Form,), dynamic)
    form = DynamicForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            s = FormSubmission.objects.create(definition=definition, patient=patient,
                                              values=json.loads(json.dumps(form.cleaned_data, default=str)),
                                              schema_snapshot=definition.schema, submitted_by=request.user)
            workflow_id = request.POST.get('workflow')
            if workflow_id:
                WorkflowRun.objects.create(definition=get_object_or_404(WorkflowDefinition, pk=workflow_id, active=True), submission=s)
            audit(request, 'submit_form', f'form_submission:{s.pk}')
        messages.success(request, f'{definition.name} submitted.')
        return redirect('patient_chart', pk=patient.pk)
    return render(request, 'hospital/form.html', {'form': form, 'title': definition.name, 'subtitle': f'For {patient.full_name} · {patient.mrn}',
                                                  'workflows': WorkflowDefinition.objects.filter(active=True)})


@login_required
@require_POST
def submission_sign(request, pk):
    authorize(request, 'clinical')
    sub = get_object_or_404(FormSubmission, pk=pk)
    if sub.status == 'rejected':
        return HttpResponseBadRequest('Cannot sign rejected submission')
    if Signature.objects.filter(submission=sub).exists():
        return HttpResponseBadRequest('Already signed')
    sig = sign_document('form', sub, request.user, 'Reviewed and signed')
    messages.success(request, f'Signed · SHA-256 {sig.document_hash[:12]}…')
    return redirect(request.POST.get('next') or reverse('patient_chart', args=[sub.patient_id]))


@login_required
@require_POST
def workflow_act(request, pk, action):
    authorize(request)
    try:
        advance_workflow(get_object_or_404(WorkflowRun, pk=pk), request.user, action, request.POST.get('comment', '')[:1000])
        audit(request, 'workflow_action', f'workflow_run:{pk}', {'action': action})
        messages.success(request, 'Step approved.' if action == 'approve' else 'Submission rejected.')
    except ValidationError as e:
        messages.error(request, '; '.join(e.messages))
    return redirect('studio')


def error_403(request, exception=None):
    return render(request, 'hospital/error.html', {'code': 403, 'title': 'This area is restricted',
                                                   'message': str(exception) if exception else 'Your role does not include access to this module. Ask an administrator to update your staff profile.'}, status=403)


def error_404(request, exception=None):
    return render(request, 'hospital/error.html', {'code': 404, 'title': 'Record not found',
                                                   'message': 'The page or record you followed does not exist or was removed.'}, status=404)
