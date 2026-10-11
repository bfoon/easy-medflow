import json
import re
from decimal import Decimal
from datetime import date, timedelta

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
                    LabOrderForm, PatientForm, ImagingOrderForm, ReferralNetworkForm, PrescriptionForm, PrescriptionItemFormSet, ReferralForm, TicketForm, WorkflowDefinitionForm)
from .models import (Location, MedicationAdministration, QueueReset, Invoice, InvoiceLine, Payment, Tariff, NetworkFacility, ReferralTask, Specialist, SpecialistSlot, MODALITIES, ImagingImage, ImagingOrder, StockRequest, FREQUENCIES, LabRequest, PrescriptionItem, BODY_SYSTEMS, LabCategory, LabParameter, LabResultValue, LabTest, StaffProfile,
                     Admission, Attendance, AuditEvent, Bed, Department, Encounter, FormDefinition, FormSubmission,
                     LabOrder, Medication, Patient, Prescription, QueueTicket, Referral, Signature, Ward,
                     WorkflowDefinition, WorkflowRun)
from .services import (capture_charges, open_invoice_for, record_payment, advance_workflow, anonymised_case, assign_bed, availability, case_from_token, discharge, dispense, prescription_check,
                       prescription_warnings, receive_stock, sign_document, similar_cases)

# Staff accounts are provisioned by administrators; there is no public signup.
ROLES = {
    'clinical': {'doctor', 'nurse', 'admin'},
    'reception': {'reception', 'nurse', 'admin'},
    'pharmacy': {'pharmacy', 'admin'},
    'lab': {'lab', 'doctor', 'admin'},
    'beds': {'nurse', 'admin', 'management'},
    'studio': {'admin', 'management'},
    'imaging': {'radiology', 'doctor', 'admin'},
    'all': {'admin', 'doctor', 'nurse', 'reception', 'lab', 'radiology', 'pharmacy', 'finance', 'management'},
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


def is_embed(request):
    return request.GET.get('embed') == '1' or request.POST.get('embed') == '1'


def finish(request, url, message):
    """After a successful save: inside the slide-out panel, tell the parent page to close and refresh; otherwise redirect."""
    if is_embed(request):
        return render(request, 'hospital/embed_done.html', {'message': message})
    messages.success(request, message)
    return redirect(url)


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
            return finish(request, return_to(obj) if callable(return_to) else return_to, f'{title} saved.')
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
        {'key': 'lab', 'label': 'Lab requests pending', 'value': LabRequest.objects.filter(orders__status__in=['ordered', 'collected', 'processing']).distinct().count(), 'url': reverse('labs')},
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
    'complete_encounter': 'completed a visit', 'lab_acknowledge': 'reviewed a lab finding', 'bed_ready': 'readied a bed', 'prescribing_warning_review': 'reviewed Rx safety',
}


@login_required
def dashboard(request):
    if partner_facility(request.user):
        return redirect('network_inbox')
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
        'critical_values': LabResultValue.objects.filter(flag__in=['LL', 'HH'], acknowledged_at__isnull=True)
            .select_related('parameter', 'order__encounter__patient').order_by('-created_at')[:5],
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
    prescriptions = Prescription.objects.filter(encounter__patient=p).prefetch_related('items__medication').order_by('-created_at')[:100]
    labs = LabOrder.objects.filter(encounter__patient=p).select_related('test', 'request').order_by('-created_at')[:100]
    lab_reqs = list(lab_requests_qs().filter(encounter__patient=p).order_by('-created_at')[:50])
    referrals = Referral.objects.filter(encounter__patient=p).order_by('-created_at')
    admissions = list(Admission.objects.filter(encounter__patient=p).select_related('bed__ward').order_by('-admitted_at'))
    # One merged, reverse-chronological timeline across every clinical record type.
    timeline = (
        [{'when': e.created_at, 'kind': 'visit', 'title': e.reason, 'meta': e.get_status_display(), 'url': reverse('encounter_detail', args=[e.pk])} for e in encounters] +
        [{'when': x.created_at, 'kind': 'rx', 'title': ', '.join(str(i.medication) for i in x.items.all()) or x.number, 'meta': f'{x.number} · {x.get_state_display()}'} for x in prescriptions] +
        [{'when': r.created_at, 'kind': 'lab', 'title': ', '.join(o.test.name for o in r.orders.all()), 'meta': f'{r.number} · {r.get_priority_display()} · {r.stage.title()}', 'flag': any(o.abnormal for o in r.orders.all())} for r in lab_reqs] +
        [{'when': x.created_at, 'kind': 'referral', 'title': f'Referral to {x.destination}', 'meta': x.get_status_display()} for x in referrals] +
        [{'when': x.created_at, 'kind': 'imaging', 'title': f'{x.get_modality_display()} · {x.region}', 'meta': f'{x.number} · {x.get_status_display()}', 'flag': x.abnormal, 'url': reverse('imaging_detail', args=[x.pk])}
         for x in ImagingOrder.objects.filter(encounter__patient=p).exclude(status='cancelled')] +
        [{'when': x.admitted_at, 'kind': 'admission', 'title': f'Admitted to {x.bed}', 'meta': 'Discharged' if x.discharged_at else 'Current'} for x in admissions]
    )
    timeline.sort(key=lambda x: x['when'], reverse=True)
    latest = next((e for e in encounters if e.vitals), None)
    vitals = [(lbl, unit, latest.vitals.get(k)) for k, lbl, unit, _ in VITAL_FIELDS if latest.vitals.get(k)] if latest else []
    return render(request, 'hospital/chart.html', {
        'p': p, 'allergies': p.allergies.order_by('status', '-created_at'), 'conditions': p.conditions.order_by('status', '-created_at'),
        'encounters': encounters, 'prescriptions': prescriptions, 'labs': labs, 'referrals': referrals, 'admissions': admissions,
        'lab_reqs': lab_reqs, 'submissions': p.submissions.select_related('definition').prefetch_related('signature_set').order_by('-created_at'),
        'available_forms': FormDefinition.objects.filter(published=True), 'timeline': timeline[:40],
        'vitals': vitals, 'vitals_at': latest.created_at if latest else None,
        'open_encounter': next((e for e in encounters if e.status == 'open'), None),
        'current_admission': next((a for a in admissions if not a.discharged_at), None),
        'imaging': ImagingOrder.objects.filter(encounter__patient=p).exclude(status='cancelled').prefetch_related('images').order_by('-created_at')[:30],
        **similar_context(p, encounters),
        'billing': billing_context(p, encounters),
    })


def billing_context(p, encounters):
    invs = list(Invoice.objects.filter(patient=p).exclude(status='void').prefetch_related('lines', 'payments').order_by('-created_at')[:6])
    return {'invoices': invs, 'balance': sum(i.balance for i in invs if i.status in ('issued', 'partial')),
            'encounter': next((e for e in encounters if e.status == 'open'), None) or (encounters[0] if encounters else None)}


def similar_context(p, encounters):
    """Pick the diagnosis to compare: the open visit's, else the most recent one recorded."""
    enc = next((e for e in encounters if e.status == 'open' and e.diagnosis), None) or next((e for e in encounters if e.diagnosis), None)
    if not enc:
        return {'similar': None}
    return {'similar': similar_cases(p, enc.diagnosis), 'similar_dx': enc.diagnosis}


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
    rx = e.prescriptions.prefetch_related('items__medication').select_related('signed_by')
    return render(request, 'hospital/encounter.html', {
        'e': e, 'p': e.patient, 'labs': e.labs.select_related('test').prefetch_related('values__parameter'), 'referrals': e.referrals.all(),
        'prescriptions': [(x, prescription_check(x)) for x in rx],
        'lab_reqs': lab_requests_qs().filter(encounter=e),
        'allergies': e.patient.allergies.filter(status='active'), 'admissions': e.admissions.select_related('bed'),
        'vitals': [(lbl, unit, e.vitals.get(k)) for k, lbl, unit, _ in VITAL_FIELDS if e.vitals.get(k)],
        'can_sign': role_of(request.user) in ('doctor', 'admin'),
        'imaging': e.imaging.exclude(status='cancelled').prefetch_related('images'), 'outcomes': Encounter.OUTCOMES,
        'review': __import__('hospital.clinical', fromlist=['clinical_review']).clinical_review(e), 'ai_on': __import__('hospital.clinical', fromlist=['ai_enabled']).ai_enabled(),
        **similar_context(e.patient, [e] + list(e.patient.encounters.exclude(pk=e.pk).order_by('-created_at')[:20])),
    })


@login_required
@require_POST
def encounter_complete(request, pk):
    authorize(request, 'clinical')
    with transaction.atomic():
        e = get_object_or_404(Encounter.objects.select_for_update(), pk=pk)
        if e.status != 'open':
            return HttpResponseBadRequest('Encounter already closed')
        e.status = 'completed'; e.completed_at = timezone.now()
        e.outcome = request.POST.get('outcome') if request.POST.get('outcome') in dict(Encounter.OUTCOMES) else ''
        e.outcome_notes = request.POST.get('outcome_notes', '')[:300]
        e.save(update_fields=['status', 'completed_at', 'outcome', 'outcome_notes', 'updated_at'])
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
    rows = list(Referral.objects.select_related('encounter__patient', 'specialist', 'slot').annotate(open_tasks=Count('tasks', filter=Q(tasks__status='open'))).order_by('-created_at')[:150])
    for r in rows:
        r.next_states = REFERRAL_FLOW.get(r.status, [])
        idx = REFERRAL_STAGES.index(r.status) if r.status in REFERRAL_STAGES else -1
        r.track = [{'name': s, 'state': 'done' if idx > i else 'current' if idx == i else 'todo'} for i, s in enumerate(REFERRAL_STAGES)]
    counts = {u: sum(1 for r in rows if r.urgency == u and r.status not in ('completed', 'cancelled', 'declined')) for u in ('emergency', 'urgent', 'routine')}
    return render(request, 'hospital/referrals.html', {'rows': rows, 'counts': counts})


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

def lab_requests_qs():
    from django.db.models import Prefetch
    return (LabRequest.objects.select_related('encounter__patient', 'requested_by')
            .prefetch_related(Prefetch('orders', queryset=LabOrder.objects.select_related('test__category').prefetch_related('values__parameter').order_by('id'))))


@login_required
def labs(request):
    """The lab board: one card per patient request, holding all of its tests."""
    authorize(request)
    reqs = [r for r in lab_requests_qs().order_by('created_at')[:300]]
    lanes = [('ordered', 'Awaiting collection'), ('collected', 'Specimen collected'), ('processing', 'Processing'), ('resulted', 'Awaiting verification')]
    rank = {'stat': 0, 'urgent': 1, 'routine': 2}
    board = [{'key': k, 'label': lbl, 'requests': sorted([r for r in reqs if r.stage == k], key=lambda r: (rank[r.priority], r.created_at))} for k, lbl in lanes]
    done = sorted([r for r in reqs if r.stage == 'verified'], key=lambda r: r.updated_at, reverse=True)[:20]
    return render(request, 'hospital/labs.html', {'board': board, 'done': done})


@login_required
def lab_new(request):
    """Order several catalogue tests for one patient as a single lab request."""
    authorize(request, 'clinical')
    encounters = Encounter.objects.filter(status='open').select_related('patient').order_by('-created_at')[:300]
    categories = LabCategory.objects.prefetch_related(models_prefetch_tests()).all()
    selected_enc = request.POST.get('encounter') or request.GET.get('encounter', '')
    if request.method == 'POST':
        enc = Encounter.objects.filter(pk=selected_enc, status='open').first()
        tests = list(LabTest.objects.filter(pk__in=request.POST.getlist('tests'), active=True))
        priority = request.POST.get('priority') if request.POST.get('priority') in dict(LabRequest.PRIORITY) else 'routine'
        if not enc or not tests:
            messages.error(request, 'Choose an open visit and at least one test.')
        else:
            with transaction.atomic():
                lr = LabRequest.objects.create(encounter=enc, requested_by=request.user, priority=priority,
                                               clinical_notes=request.POST.get('clinical_notes', '')[:2000])
                for t in tests:
                    LabOrder.objects.create(encounter=enc, request=lr, test=t)
                audit(request, 'create', f'hospital.LabRequest:{lr.pk}', {'tests': len(tests)})
            return finish(request, request.POST.get('next') or reverse('lab_request_detail', args=[lr.pk]),
                          f'Lab request {lr.number}: {len(tests)} test{"s" if len(tests) > 1 else ""} for {enc.patient.full_name}.')
    return render(request, 'hospital/lab_order_form.html', {'encounters': encounters, 'categories': categories, 'priorities': LabRequest.PRIORITY,
                                                            'selected_enc': str(selected_enc), 'selected': request.POST.getlist('tests') or request.GET.getlist('test')})


def models_prefetch_tests():
    from django.db.models import Prefetch
    return Prefetch('tests', queryset=LabTest.objects.filter(active=True).prefetch_related('parameters'))


@login_required
@require_POST
def lab_request_action(request, pk, step):
    """Move every test in a request forward together: collect, process, verify, or cancel the whole request."""
    authorize(request, 'lab')
    with transaction.atomic():
        lr = get_object_or_404(LabRequest.objects.select_for_update(), pk=pk)
        orders = list(lr.orders.select_for_update())
        now, moved = timezone.now(), 0
        if step == 'collect':
            lr.specimen_id = request.POST.get('specimen_id', '').strip()[:80] or lr.specimen_id or f'SP-{lr.pk:06d}'
            lr.collected_at = now; lr.save(update_fields=['specimen_id', 'collected_at', 'updated_at'])
            for o in orders:
                if o.status == 'ordered':
                    o.status, o.specimen_id, o.performed_by = 'collected', lr.specimen_id, o.performed_by or request.user; o.save(); moved += 1
        elif step == 'process':
            for o in orders:
                if o.status == 'collected':
                    o.status, o.performed_by = 'processing', o.performed_by or request.user; o.save(); moved += 1
        elif step == 'verify':
            for o in orders:
                if o.status == 'resulted':
                    o.status, o.verified_by, o.verified_at = 'verified', request.user, now; o.save(); moved += 1
        elif step == 'cancel':
            for o in orders:
                if o.status not in ('verified', 'cancelled'):
                    o.status = 'cancelled'; o.save(); moved += 1
        else:
            return HttpResponseBadRequest('Unknown step')
        if not moved:
            return HttpResponseBadRequest('Nothing in this request can take that step')
        lr.save(update_fields=['updated_at'])
        audit(request, 'lab_update', f'lab_request:{lr.pk}', {'step': step, 'tests': moved})
    if step == 'process':
        return redirect('lab_results_entry', pk=lr.pk)
    if step == 'verify':
        messages.success(request, f'{moved} result{"s" if moved > 1 else ""} verified and released for {lr.number}.')
    return redirect(request.POST.get('next') or 'labs')


@login_required
@require_POST
def lab_order_cancel(request, pk):
    """Cancel one test inside a request without touching the others."""
    authorize(request, 'lab')
    with transaction.atomic():
        o = get_object_or_404(LabOrder.objects.select_for_update(), pk=pk)
        if o.status in ('verified', 'cancelled'):
            return HttpResponseBadRequest('Cannot cancel')
        o.status = 'cancelled'; o.save()
        audit(request, 'lab_update', f'lab_order:{o.pk}', {'status': 'cancelled'})
    messages.success(request, f'{o.test.name} cancelled.')
    return redirect(request.POST.get('next') or 'labs')


@login_required
def lab_results_entry(request, pk):
    """One results sheet for the whole request: a section per test, a row per parameter."""
    authorize(request, 'lab')
    lr = get_object_or_404(lab_requests_qs(), pk=pk)
    p = lr.encounter.patient
    orders = [o for o in lr.orders.all() if o.status in ('collected', 'processing', 'resulted')]
    if not orders:
        messages.error(request, 'No tests in this request are ready for results. Collect the specimen first.')
        return redirect('labs')
    errors, sections = {}, []
    if request.method == 'POST':
        from decimal import Decimal, InvalidOperation
        submit = request.POST.get('action') == 'submit'
        parsed = {}
        for o in orders:
            for prm in o.test.parameters.all():
                key = f'p_{o.pk}_{prm.pk}'
                raw = request.POST.get(key, '').strip()
                if prm.kind == 'number' and raw:
                    try:
                        parsed[key] = Decimal(raw.replace(',', '.'))
                    except InvalidOperation:
                        errors[key] = 'Enter a number'
                elif prm.kind == 'choice' and raw and raw not in prm.choices:
                    errors[key] = 'Choose a listed option'
                else:
                    parsed[key] = raw[:500]
        if not errors:
            completed, partial, crit = [], [], 0
            with transaction.atomic():
                for o in orders:
                    for prm in o.test.parameters.all():
                        val = parsed.get(f'p_{o.pk}_{prm.pk}')
                        if val in (None, ''):
                            LabResultValue.objects.filter(order=o, parameter=prm).delete(); continue
                        num = val if prm.kind == 'number' else None
                        LabResultValue.objects.update_or_create(order=o, parameter=prm, defaults={
                            'value_number': num, 'value_text': '' if num is not None else val, 'flag': prm.flag_for(val, p.sex), 'entered_by': request.user})
                    o.result = request.POST.get(f'comment_{o.pk}', '')[:4000]
                    o.performed_by = o.performed_by or request.user
                    o.abnormal = o.values.exclude(flag__in=['', 'N']).exists()
                    if o.status == 'collected':
                        o.status = 'processing'
                    required = [prm for prm in o.test.parameters.all() if prm.kind != 'text']
                    filled = all(parsed.get(f'p_{o.pk}_{prm.pk}') not in (None, '') for prm in required)
                    if submit and o.status == 'processing':
                        if filled:
                            o.status, o.resulted_at = 'resulted', timezone.now(); completed.append(o.test.name)
                            crit += o.values.filter(flag__in=['LL', 'HH']).count()
                        elif any(parsed.get(f'p_{o.pk}_{prm.pk}') not in (None, '') for prm in required):
                            partial.append(o.test.name)
                    o.save()
                audit(request, 'lab_update', f'lab_request:{lr.pk}', {'submitted': completed})
            if submit:
                if completed:
                    messages.success(request, f'Submitted for verification: {", ".join(completed)}.')
                if partial:
                    messages.warning(request, f'Saved but not submitted (values missing): {", ".join(partial)}.')
                if crit:
                    messages.warning(request, f'{crit} critical value{"s" if crit > 1 else ""} submitted. Telephone the requesting clinician now and document it.')
                if not completed and not partial:
                    messages.error(request, 'Enter every value of at least one test before submitting, or save as draft.')
                return redirect('labs' if completed and not partial else request.path)
            messages.success(request, 'Draft saved.')
            return redirect(request.path)
    rules = []
    for o in orders:
        existing = {v.parameter_id: v for v in o.values.all()}
        rows = []
        for prm in o.test.parameters.all():
            key = f'p_{o.pk}_{prm.pk}'
            v = existing.get(prm.pk)
            lo, hi = prm.range_for(p.sex)
            rows.append({'p': prm, 'key': key, 'value': request.POST.get(key) if request.method == 'POST' else (v.display if v else ''),
                         'flag': v.flag if v else '', 'error': errors.get(key), 'range': prm.range_label(p.sex)})
            rules.append({'id': key, 'kind': prm.kind, 'lo': _f(lo), 'hi': _f(hi), 'clo': _f(prm.critical_low), 'chi': _f(prm.critical_high), 'abn': prm.abnormal_choices})
        sections.append({'o': o, 'rows': rows})
    return render(request, 'hospital/lab_entry.html', {'lr': lr, 'p': p, 'sections': sections, 'rules': rules,
                                                       'n_values': sum(len(s['rows']) for s in sections)})


def _f(d):
    return float(d) if d is not None else None


@login_required
def lab_mine(request):
    """Requests this technician worked on, newest first."""
    authorize(request, 'lab')
    period = request.GET.get('period', '7')
    qs = lab_requests_qs().filter(orders__performed_by=request.user).distinct().order_by('-updated_at')
    if period != 'all':
        qs = qs.filter(updated_at__gte=timezone.now() - timedelta(days=int(period) if period.isdigit() else 7))
    cat = request.GET.get('category', '')
    if cat:
        qs = qs.filter(orders__test__category__code=cat)
    rows = list(qs[:200])
    tests = [o for r in rows for o in r.orders.all() if o.performed_by_id == request.user.pk]
    stats = {'requests': len(rows), 'tests': len(tests), 'verified': sum(o.status == 'verified' for o in tests),
             'pending': sum(o.status in ('collected', 'processing', 'resulted') for o in tests), 'abnormal': sum(o.abnormal for o in tests)}
    by_cat = {}
    for o in tests:
        k = o.test.category.name if o.test.category else 'Uncategorised'
        by_cat[k] = by_cat.get(k, 0) + 1
    return render(request, 'hospital/lab_mine.html', {'rows': rows, 'stats': stats, 'by_cat': sorted(by_cat.items(), key=lambda x: -x[1]),
                                                      'period': period, 'cat': cat, 'categories': LabCategory.objects.all()})


@login_required
def lab_catalog(request):
    authorize(request)
    return render(request, 'hospital/lab_catalog.html', {'categories': LabCategory.objects.prefetch_related(models_prefetch_tests()),
                                                         'uncategorised': LabTest.objects.filter(category__isnull=True, active=True), 'systems': dict(BODY_SYSTEMS)})


def lab_view_pref(request):
    p = getattr(request.user, 'hospital_staff', None)
    try:
        return p.lab_view if p else request.session.get('lab_view', 'body')
    except Exception:
        return 'body'


@login_required
@require_POST
def set_lab_view(request):
    view = request.POST.get('view')
    if view not in ('body', 'clean'):
        return HttpResponseBadRequest('Unknown view')
    p = StaffProfile.objects.filter(user=request.user).first()
    if p:
        p.lab_view = view; p.save(update_fields=['lab_view', 'updated_at'])
    request.session['lab_view'] = view
    return JsonResponse({'ok': True, 'view': view})


def patient_lab_data(patient):
    """Everything the insights page needs, as plain JSON: per-parameter history plus per-system summaries."""
    orders = (LabOrder.objects.filter(encounter__patient=patient, status__in=['resulted', 'verified'])
              .select_related('test__category').prefetch_related('values__parameter__test', 'values__acknowledged_by').order_by('resulted_at', 'created_at'))
    params, order_list = {}, []
    for o in orders:
        when = o.resulted_at or o.created_at
        cat = o.test.category
        ovals = []
        for v in o.values.all():
            prm = v.parameter
            lo, hi = prm.range_for(patient.sex)
            entry = params.setdefault(prm.pk, {
                'id': prm.pk, 'test_id': o.test_id, 'code': prm.code, 'name': prm.name, 'unit': prm.unit, 'kind': prm.kind, 'system': prm.system, 'test': o.test.name,
                'category': cat.name if cat else 'Other', 'color': cat.color if cat else '#5A6F7D', 'range': prm.range_label(patient.sex),
                'lo': _f(lo), 'hi': _f(hi), 'clo': _f(prm.critical_low), 'chi': _f(prm.critical_high), 'history': []})
            point = {'value_id': v.pk, 'order_id': o.pk, 'date': timezone.localtime(when).strftime('%Y-%m-%d %H:%M'), 'display': v.display,
                     'num': _f(v.value_number), 'flag': v.flag, 'preliminary': o.status != 'verified',
                     'ack': bool(v.acknowledged_at), 'ack_by': (v.acknowledged_by.get_full_name() or v.acknowledged_by.username) if v.acknowledged_by else ''}
            entry['history'].append(point)
            ovals.append({'name': prm.name, 'display': v.display, 'unit': prm.unit, 'flag': v.flag, 'range': entry['range']})
        order_list.append({'id': o.pk, 'test': o.test.name, 'category': cat.name if cat else 'Other', 'color': cat.color if cat else '#5A6F7D',
                           'date': timezone.localtime(when).strftime('%Y-%m-%d %H:%M'), 'status': o.get_status_display(), 'comment': o.result, 'values': ovals})
    for e in params.values():
        e['latest'] = e['history'][-1]
    imaging = [{'id': o.pk, 'number': o.number, 'modality': o.get_modality_display(), 'region': o.region, 'system': o.body_system,
                'status': o.get_status_display(), 'reported': o.status == 'reported', 'abnormal': o.abnormal, 'impression': o.impression,
                'findings': o.findings, 'measurements': o.measurements, 'url': reverse('imaging_detail', args=[o.pk]),
                'date': timezone.localtime(o.reported_at or o.created_at).strftime('%Y-%m-%d %H:%M'),
                'images': [{'url': reverse('imaging_file', args=[i.pk]), 'caption': i.caption} for i in o.images.all()]}
               for o in ImagingOrder.objects.filter(encounter__patient=patient, status__in=['acquired', 'reported']).prefetch_related('images').order_by('-created_at')]
    open_enc = patient.encounters.filter(status='open').order_by('-created_at').first()
    return {'open_encounter': open_enc.pk if open_enc else None, 'lab_new_url': reverse('lab_new'), 'imaging': imaging, 'patient': {'name': patient.full_name, 'sex': patient.sex, 'age': patient.age, 'mrn': patient.mrn},
            'systems': dict(BODY_SYSTEMS), 'params': list(params.values()), 'orders': list(reversed(order_list))}


@login_required
def patient_labs(request, pk):
    authorize(request, 'clinical')
    p = get_object_or_404(Patient, pk=pk)
    audit(request, 'view_chart', f'patient_labs:{p.pk}')
    pending = LabOrder.objects.filter(encounter__patient=p, status__in=['ordered', 'collected', 'processing']).select_related('test')
    return render(request, 'hospital/lab_insights.html', {'p': p, 'data': patient_lab_data(p), 'view': lab_view_pref(request),
                                                          'pending': pending, 'open_encounter': p.encounters.filter(status='open').first()})


@login_required
@require_POST
def lab_ack(request, pk):
    """A clinician confirms they have seen an out-of-range result."""
    authorize(request, 'clinical')
    with transaction.atomic():
        v = get_object_or_404(LabResultValue.objects.select_for_update(), pk=pk)
        if not v.acknowledged_at:
            v.acknowledged_by, v.acknowledged_at = request.user, timezone.now()
            v.save(update_fields=['acknowledged_by', 'acknowledged_at', 'updated_at'])
            audit(request, 'lab_acknowledge', f'lab_value:{v.pk}', {'flag': v.flag})
    return JsonResponse({'ok': True, 'by': request.user.get_full_name() or request.user.username})


# ---------------------------------------------------------------- pharmacy

@login_required
def pharmacy(request):
    authorize(request)
    stock = []
    for m in Medication.objects.filter(active=True).order_by('name')[:200]:
        qty = availability(m)
        stock.append({'m': m, 'qty': qty, 'pct': min(100, round(qty * 100 / max(m.reorder_level * 3, 1))),
                      'level': 'out' if qty == 0 else 'low' if qty <= m.reorder_level else 'ok'})
    rx = list(Prescription.objects.select_related('encounter__patient', 'signed_by').prefetch_related('items__medication').order_by('-created_at')[:150])
    lanes = [('draft', 'Drafts awaiting prescriber', [x for x in rx if x.state == 'draft']),
             ('signed', 'Signed · ready to dispense', [x for x in rx if x.state in ('signed', 'partial')]),
             ('dispensed', 'Dispensed', [x for x in rx if x.state == 'dispensed'][:12])]
    return render(request, 'hospital/pharmacy.html', {'stock': stock, 'lanes': lanes,
                                                      'can_sign': role_of(request.user) in ('doctor', 'admin'),
                                                      'can_dispense': role_of(request.user) in ('pharmacy', 'admin'),
                                                      'supplier': StockRequest.objects.select_related('medication', 'prescription_item__prescription', 'requested_by').exclude(status__in=['received', 'cancelled'])[:50],
                                                      'supplier_done': StockRequest.objects.select_related('medication').filter(status__in=['received', 'cancelled'])[:10]})


@login_required
def prescription_new(request):
    """One prescription with as many medicine lines as needed."""
    authorize(request, 'clinical')
    form = PrescriptionForm(request.POST or None, initial={k: v for k, v in request.GET.items()})
    formset = PrescriptionItemFormSet(request.POST or None, prefix='items')
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        enc = form.cleaned_data['encounter']
        live = [f for f in formset.forms if f.cleaned_data and f.cleaned_data.get('medication') and not f.cleaned_data.get('DELETE')]
        flagged = [f.cleaned_data['medication'] for f in live if prescription_warnings(enc, f.cleaned_data['medication'], f.cleaned_data['quantity'])['possible_allergy_matches']]
        meds = [f.cleaned_data['medication'].pk for f in live]
        if not live:
            form.add_error(None, 'Add at least one medicine.')
        elif not form.cleaned_data['allergy_reviewed']:
            form.add_error('allergy_reviewed', 'Confirm that you reviewed the allergy history before saving.')
        elif flagged and not form.cleaned_data['override_reason'].strip():
            form.add_error('override_reason', f'Possible allergy match for {", ".join(str(m) for m in flagged)}. Document a clinical justification or remove it.')
        elif len(meds) != len(set(meds)):
            form.add_error(None, 'The same medicine is listed twice. Combine it into one line.')
        else:
            with transaction.atomic():
                p = form.save()
                for i, f in enumerate(live):
                    item = f.save(commit=False); item.prescription = p; item.sort_order = i; item.save()
                audit(request, 'create', f'hospital.Prescription:{p.pk}', {'lines': len(live), 'possible_allergy_match': bool(flagged)})
            return finish(request, request.POST.get('next') or reverse('prescription_detail', args=[p.pk]),
                          f'Prescription {p.number} saved as a draft with {len(live)} medicine{"s" if len(live) > 1 else ""}.')
    meds = {m.pk: {'form': m.form, 'strength': m.strength, 'name': str(m)} for m in Medication.objects.filter(active=True)}
    return render(request, 'hospital/prescription_form.html', {
        'form': form, 'formset': formset, 'title': 'New prescription', 'meds': meds,
        'per_day': {c: n for c, _, n in FREQUENCIES}, 'subtitle': 'Add each medicine as its own line. Saved as a draft until a prescriber signs it.'})


@login_required
def api_rx_check(request):
    """Live safety check for one prescription line: allergies and stock for the chosen visit + medication."""
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
        p = get_object_or_404(Prescription.objects.select_for_update().select_related('encounter__patient'), pk=pk)
        if p.state != 'draft':
            return HttpResponseBadRequest('Not a draft')
        check = prescription_check(p)
        if not check['lines'] or not p.allergy_reviewed or (check['any_allergy'] and not p.override_reason.strip()):
            return HttpResponseBadRequest('Allergy review incomplete')
        p.state = 'signed'; p.signed_by = request.user; p.signed_at = timezone.now()
        p.save(update_fields=['state', 'signed_by', 'signed_at'])
        sig = sign_document('prescription', p, request.user, 'Prescriber authorization')
    messages.success(request, f'{p.number} signed · SHA-256 {sig.document_hash[:12]}…')
    return redirect(request.POST.get('next') or 'pharmacy')


@login_required
@require_POST
def prescription_dispense(request, pk):
    authorize(request, 'pharmacy')
    try:
        p = dispense(get_object_or_404(Prescription, pk=pk), request.user)
        messages.success(request, f'{p.number} dispensed. Stock was drawn from the earliest-expiring batches first.')
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
    if not request.user.is_authenticated:     # signed-out visitors (e.g. an expired ticket link) get a plain page
        return render(request, 'hospital/error_public.html', {'code': 404, 'title': 'Not found', 'message': 'This link is not valid or has expired.'}, status=404)
    return render(request, 'hospital/error.html', {'code': 404, 'title': 'Record not found',
                                                   'message': 'The page or record you followed does not exist or was removed.'}, status=404)


# ---------------------------------------------------------------- detail pages: lab requests & prescriptions

@login_required
def lab_request_detail(request, pk):
    authorize(request)
    lr = get_object_or_404(lab_requests_qs(), pk=pk)
    audit(request, 'view_chart', f'lab_request:{lr.pk}')
    return render(request, 'hospital/lab_request.html', {'lr': lr, 'p': lr.encounter.patient,
                                                         'can_lab': role_of(request.user) in ROLES['lab'], 'sex': lr.encounter.patient.sex})


def rx_qs():
    return Prescription.objects.select_related('encounter__patient', 'signed_by').prefetch_related('items__medication', 'items__dispenses', 'items__stock_requests')


@login_required
def prescription_detail(request, pk):
    authorize(request)
    p = get_object_or_404(rx_qs(), pk=pk)
    check = prescription_check(p)
    lines = []
    for line in check['lines']:
        i = line['item']
        lines.append({**line, 'owed': max(0, i.quantity - i.dispensed_quantity), 'open_request': next((r for r in i.stock_requests.all() if r.status in ('requested', 'ordered')), None)})
    role = role_of(request.user)
    return render(request, 'hospital/prescription_detail.html', {
        'p': p, 'patient': p.encounter.patient, 'lines': lines, 'check': check, 'unavailable': [l for l in lines if l['item'].availability == 'unavailable'],
        'can_sign': role in ('doctor', 'admin'), 'can_dispense': role in ('pharmacy', 'admin'), 'can_edit': role in ROLES['clinical'] and p.state == 'draft',
        'can_manage': role in ('pharmacy', 'doctor', 'admin')})


@login_required
def prescription_edit(request, pk):
    """Change a draft prescription: add, remove or adjust medicine lines."""
    authorize(request, 'clinical')
    p = get_object_or_404(Prescription, pk=pk)
    if p.state != 'draft':
        messages.error(request, 'Only draft prescriptions can be changed. Signed prescriptions are part of the record.')
        return redirect('prescription_detail', pk=pk)
    form = PrescriptionForm(request.POST or None, instance=p)
    form.fields['encounter'].disabled = True
    formset = PrescriptionItemFormSet(request.POST or None, instance=p, prefix='items')
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        live = [f for f in formset.forms if f.cleaned_data and f.cleaned_data.get('medication') and not f.cleaned_data.get('DELETE')]
        flagged = [f.cleaned_data['medication'] for f in live if prescription_warnings(p.encounter, f.cleaned_data['medication'], f.cleaned_data['quantity'])['possible_allergy_matches']]
        meds = [f.cleaned_data['medication'].pk for f in live]
        if not live:
            form.add_error(None, 'A prescription needs at least one medicine.')
        elif not form.cleaned_data['allergy_reviewed']:
            form.add_error('allergy_reviewed', 'Confirm that you reviewed the allergy history before saving.')
        elif flagged and not form.cleaned_data['override_reason'].strip():
            form.add_error('override_reason', f'Possible allergy match for {", ".join(str(m) for m in flagged)}. Document a clinical justification or remove it.')
        elif len(meds) != len(set(meds)):
            form.add_error(None, 'The same medicine is listed twice. Combine it into one line.')
        else:
            with transaction.atomic():
                form.save()
                for f in formset.forms:
                    if f.cleaned_data.get('DELETE') and f.instance.pk:
                        f.instance.delete()
                for i, f in enumerate(live):
                    item = f.save(commit=False); item.prescription = p; item.sort_order = i; item.save()
                audit(request, 'update', f'hospital.Prescription:{p.pk}', {'lines': len(live)})
            return finish(request, reverse('prescription_detail', args=[p.pk]), f'{p.number} updated.')
    meds = {m.pk: {'form': m.form, 'strength': m.strength, 'name': str(m)} for m in Medication.objects.filter(active=True)}
    return render(request, 'hospital/prescription_form.html', {
        'form': form, 'formset': formset, 'title': f'Edit {p.number}', 'meds': meds, 'editing': p,
        'per_day': {c: n for c, _, n in FREQUENCIES}, 'subtitle': f'{p.encounter.patient.full_name} · still a draft, so lines can be changed.'})


@login_required
@require_POST
def rx_item_availability(request, pk, action):
    """When a medicine is out of stock: order it from the supplier, or record that the patient was told to get it elsewhere."""
    authorize(request)
    if role_of(request.user) not in ('pharmacy', 'doctor', 'admin'):
        raise PermissionDenied('Pharmacy or prescriber role required')
    with transaction.atomic():
        item = get_object_or_404(PrescriptionItem.objects.select_for_update().select_related('prescription', 'medication'), pk=pk)
        if item.prescription.state in ('dispensed', 'cancelled') or item.is_dispensed:
            return HttpResponseBadRequest('This medicine has already been handled')
        if action == 'order':
            shortfall = max(1, item.quantity - item.dispensed_quantity - availability(item.medication))
            qty = max(shortfall, int(request.POST.get('quantity') or 0) or 0)
            StockRequest.objects.create(medication=item.medication, quantity=qty, prescription_item=item, requested_by=request.user,
                                        reason=f'Needed for {item.prescription.number}')
            item.availability = 'ordered'; item.save(update_fields=['availability', 'updated_at'])
            msg = f'{item.medication} ordered from the supplier ({qty}). The line will be dispensed when stock arrives.'
        elif action == 'unavailable':
            item.availability = 'unavailable'
            item.availability_note = request.POST.get('note', '').strip()[:300] or 'Not available at this pharmacy. Please buy from a community pharmacy.'
            item.patient_informed_at, item.patient_informed_by = timezone.now(), request.user
            item.save(update_fields=['availability', 'availability_note', 'patient_informed_at', 'patient_informed_by', 'updated_at'])
            msg = f'Recorded: patient informed that {item.medication} is not available here.'
        elif action == 'clear':
            item.availability = ''; item.save(update_fields=['availability', 'updated_at'])
            msg = f'{item.medication} is back to normal dispensing.'
        else:
            return HttpResponseBadRequest('Unknown action')
        audit(request, 'rx_availability', f'prescription_item:{item.pk}', {'action': action})
    messages.success(request, msg)
    return redirect('prescription_detail', pk=item.prescription_id)


@login_required
@require_POST
def stock_request_new(request, med_pk):
    authorize(request, 'pharmacy')
    m = get_object_or_404(Medication, pk=med_pk)
    qty = int(request.POST.get('quantity') or m.reorder_level * 3)
    StockRequest.objects.create(medication=m, quantity=max(1, qty), requested_by=request.user, reason='Reorder (stock low)')
    messages.success(request, f'Supplier order raised for {m} × {qty}.')
    return redirect(reverse('pharmacy') + '#supplier')


@login_required
@require_POST
def stock_request_action(request, pk, action):
    authorize(request, 'pharmacy')
    sr = get_object_or_404(StockRequest, pk=pk)
    if action == 'ordered' and sr.status == 'requested':
        sr.status = 'ordered'; sr.save(update_fields=['status', 'updated_at']); messages.success(request, f'Marked as ordered: {sr.medication}.')
    elif action == 'cancel' and sr.status in ('requested', 'ordered'):
        sr.status = 'cancelled'; sr.save(update_fields=['status', 'updated_at'])
        if sr.prescription_item_id:
            PrescriptionItem.objects.filter(pk=sr.prescription_item_id, availability='ordered').update(availability='')
        messages.success(request, 'Supplier order cancelled.')
    elif action == 'receive':
        from datetime import date as _date
        try:
            expiry = _date.fromisoformat(request.POST.get('expiry', ''))
            qty = int(request.POST.get('quantity') or sr.quantity)
            batch_no = request.POST.get('batch_number', '').strip()[:100]
            if not batch_no or qty < 1 or expiry <= timezone.localdate():
                raise ValueError
            receive_stock(sr, request.user, batch_no, expiry, qty)
            messages.success(request, f'{qty} × {sr.medication} received into stock. Waiting prescriptions can now be dispensed.')
        except (ValueError, ValidationError):
            messages.error(request, 'Enter a batch number, a future expiry date and a quantity.')
    else:
        return HttpResponseBadRequest('Invalid action')
    return redirect(reverse('pharmacy') + '#supplier')


# ---------------------------------------------------------------- imaging

ALLOWED_IMAGE_EXT = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}


@login_required
def imaging_list(request):
    authorize(request)
    orders = list(ImagingOrder.objects.select_related('encounter__patient', 'requested_by').prefetch_related('images').exclude(status='cancelled').order_by('created_at')[:300])
    rank = {'stat': 0, 'urgent': 1, 'routine': 2}
    lanes = [('requested', 'Waiting for imaging'), ('acquired', 'Images taken · awaiting report')]
    board = [{'key': k, 'label': l, 'orders': sorted([o for o in orders if o.status == k], key=lambda o: (rank[o.priority], o.created_at))} for k, l in lanes]
    reported = sorted([o for o in orders if o.status == 'reported'], key=lambda o: o.reported_at or o.created_at, reverse=True)[:30]
    return render(request, 'hospital/imaging.html', {'board': board, 'reported': reported})


@login_required
def imaging_new(request):
    def save(form):
        o = form.save(commit=False); o.requested_by = request.user; o.save(); return o
    return edit_page(request, ImagingOrderForm, 'Imaging request', lambda o: reverse('imaging_detail', args=[o.pk]), 'clinical', save,
                     template='hospital/imaging_form.html', subtitle='X-ray, CT, MRI, ultrasound, ECG or echo.')


@login_required
def imaging_detail(request, pk):
    authorize(request)
    o = get_object_or_404(ImagingOrder.objects.select_related('encounter__patient', 'requested_by', 'reported_by').prefetch_related('images'), pk=pk)
    audit(request, 'view_chart', f'imaging:{o.pk}')
    return render(request, 'hospital/imaging_detail.html', {'o': o, 'p': o.encounter.patient, 'can_image': role_of(request.user) in ROLES['imaging']})


@login_required
@require_POST
def imaging_upload(request, pk):
    authorize(request, 'imaging')
    o = get_object_or_404(ImagingOrder, pk=pk)
    if o.status == 'cancelled':
        return HttpResponseBadRequest('Study cancelled')
    import os
    from PIL import Image, UnidentifiedImageError
    files, saved = request.FILES.getlist('images'), 0
    for f in files[:20]:
        ext = os.path.splitext(f.name)[1].lower()
        if ext not in ALLOWED_IMAGE_EXT or f.size > 15 * 1024 * 1024 or o.images.count() >= 40:
            messages.error(request, f'{f.name}: use JPG, PNG or WEBP up to 15 MB.'); continue
        try:  # confirm it is really an image, not a renamed file
            Image.open(f).verify(); f.seek(0)
        except (UnidentifiedImageError, OSError, SyntaxError):
            messages.error(request, f'{f.name} is not a valid image.'); continue
        ImagingImage.objects.create(order=o, file=f, caption=request.POST.get('caption', '')[:120], uploaded_by=request.user); saved += 1
    if saved:
        if o.status == 'requested':
            o.status = 'acquired'; o.performed_by = request.user; o.save(update_fields=['status', 'performed_by', 'updated_at'])
        audit(request, 'imaging_upload', f'imaging:{o.pk}', {'images': saved})
        messages.success(request, f'{saved} image{"s" if saved > 1 else ""} added.')
    return redirect('imaging_detail', pk=o.pk)


@login_required
@require_POST
def imaging_report(request, pk):
    authorize(request, 'imaging')
    o = get_object_or_404(ImagingOrder, pk=pk)
    if o.status == 'cancelled':
        return HttpResponseBadRequest('Study cancelled')
    try:
        meas = json.loads(request.POST.get('measurements') or '[]')
        meas = [{'label': str(m.get('label', ''))[:60], 'value': str(m.get('value', ''))[:30], 'unit': str(m.get('unit', ''))[:20], 'abnormal': bool(m.get('abnormal'))}
                for m in meas if isinstance(m, dict) and m.get('label')][:20]
    except (ValueError, AttributeError):
        meas = []
    o.findings = request.POST.get('findings', '')[:8000]; o.impression = request.POST.get('impression', '')[:2000]
    o.measurements = meas; o.abnormal = request.POST.get('abnormal') == 'on' or any(m['abnormal'] for m in meas)
    if request.POST.get('action') == 'final':
        if not o.impression.strip():
            messages.error(request, 'Write an impression before finalising the report.')
            o.save(); return redirect('imaging_detail', pk=o.pk)
        o.status, o.reported_by, o.reported_at = 'reported', request.user, timezone.now()
    o.save()
    audit(request, 'imaging_report', f'imaging:{o.pk}', {'final': o.status == 'reported', 'abnormal': o.abnormal})
    messages.success(request, 'Report finalised and released.' if o.status == 'reported' else 'Report draft saved.')
    return redirect('imaging_detail', pk=o.pk)


@login_required
@require_POST
def imaging_cancel(request, pk):
    authorize(request, 'clinical')
    o = get_object_or_404(ImagingOrder, pk=pk)
    if o.status == 'reported':
        return HttpResponseBadRequest('Reported studies cannot be cancelled')
    o.status = 'cancelled'; o.save(update_fields=['status', 'updated_at'])
    messages.success(request, f'{o.number} cancelled.')
    return redirect('imaging')


@login_required
def imaging_file(request, pk):
    """Serve a scan only to signed-in, authorised staff. Patient images are never public files."""
    authorize(request)
    import os
    from django.http import FileResponse, Http404
    img = get_object_or_404(ImagingImage, pk=pk)
    ext = os.path.splitext(img.file.name)[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise Http404
    try:
        resp = FileResponse(img.file.open('rb'), content_type=ALLOWED_IMAGE_EXT[ext])
    except FileNotFoundError:
        raise Http404
    resp['Cache-Control'] = 'private, max-age=3600'
    resp['Content-Disposition'] = 'inline'
    return resp


# ---------------------------------------------------------------- anonymised similar cases

@login_required
def case_detail(request, token):
    authorize(request, 'clinical')
    eid = case_from_token(token)
    viewer = Patient.objects.filter(pk=request.GET.get('patient')).first()
    data = anonymised_case(eid, viewer) if eid and viewer else None
    if not data:
        return JsonResponse({'ok': False, 'error': 'This case is not available.'}, status=404)
    if data['encounter_id']:
        data['url'] = reverse('encounter_detail', args=[data['encounter_id']])
    audit(request, 'view_similar_case', 'case', {'own': data['own']})
    return JsonResponse({'ok': True, **data})


# ---------------------------------------------------------------- referral & specialist network

PREOP_CHECKLIST = [
    ('sender', 'test', 'Full blood count', 'CBC'), ('sender', 'test', 'Renal function', 'RFT'), ('sender', 'test', 'Blood group & rhesus', 'BGRP'),
    ('sender', 'form', 'Procedure consent signed', None), ('sender', 'document', 'Send current medication list and allergies', None),
    ('sender', 'preparation', 'Fasting instructions given to patient (nothing to eat 6 h, clear fluids until 2 h)', None),
    ('receiver', 'preparation', 'Theatre / procedure slot confirmed', None), ('receiver', 'preparation', 'Anaesthetic pre-assessment booked', None),
    ('receiver', 'preparation', 'Blood products cross-matched and reserved', None),
]


def partner_facility(user):
    p = getattr(user, 'hospital_staff', None)
    return p.facility if p and p.active and p.role == 'partner' else None


def referral_side(request, ref):
    """'sender' for hospital staff, 'receiver' for the partner facility it was sent to. Anyone else is refused."""
    fac = partner_facility(request.user)
    if fac:
        if ref.facility_id == fac.pk and ref.status != 'draft':
            return 'receiver'
        raise PermissionDenied('This referral was not sent to your facility.')
    authorize(request)
    return 'sender'


def next_free_slots(specialists, days=14):
    now = timezone.now()
    free = (SpecialistSlot.objects.filter(specialist__in=specialists, start__gte=now, start__lte=now + timedelta(days=days), referral__isnull=True)
            .order_by('start'))
    first = {}
    for sl in free:
        first.setdefault(sl.specialist_id, sl)
    counts = dict(free.order_by().values_list('specialist').annotate(n=Count('id')))  # clear the time ordering, or each slot becomes its own group
    return first, counts


@login_required
def network_specialists(request):
    authorize(request, 'clinical')
    qs = Specialist.objects.filter(active=True, facility__accepts_referrals=True).select_related('facility')
    q, spec, fac, sort = request.GET.get('q', '').strip(), request.GET.get('speciality', ''), request.GET.get('facility', ''), request.GET.get('sort', 'rating')
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(speciality__icontains=q) | Q(facility__name__icontains=q) | Q(bio__icontains=q))
    if spec:
        qs = qs.filter(speciality=spec)
    if fac:
        qs = qs.filter(facility_id=fac)
    rows = list(qs)
    first, counts = next_free_slots(rows)
    for s in rows:
        s.next_slot, s.free_count = first.get(s.pk), counts.get(s.pk, 0)
        s.stars = round(float(s.rating) * 2) / 2
    if sort == 'soonest':
        rows.sort(key=lambda s: (s.next_slot is None, s.next_slot.start if s.next_slot else timezone.now()))
    elif sort == 'name':
        rows.sort(key=lambda s: s.name)
    top = sorted([s for s in rows if s.reviews >= 5], key=lambda s: (-s.rating, -s.reviews))[:4]
    return render(request, 'hospital/network_specialists.html', {
        'rows': rows, 'top': top, 'q': q, 'spec': spec, 'fac': fac, 'sort': sort, 'encounter': request.GET.get('encounter', ''),
        'specialities': Specialist.objects.filter(active=True).values_list('speciality', flat=True).distinct().order_by('speciality'),
        'facilities': NetworkFacility.objects.filter(accepts_referrals=True)})


@login_required
def specialist_detail(request, pk):
    authorize(request, 'clinical')
    s = get_object_or_404(Specialist.objects.select_related('facility'), pk=pk)
    now, start = timezone.now(), timezone.localdate()
    slots = list(s.slots.filter(start__gte=now, start__lte=now + timedelta(days=14)).select_related('referral'))
    days = []
    for i in range(14):
        d = start + timedelta(days=i)
        day_slots = [sl for sl in slots if timezone.localtime(sl.start).date() == d]
        days.append({'date': d, 'slots': day_slots, 'free': sum(1 for sl in day_slots if not sl.is_booked)})
    return render(request, 'hospital/specialist_detail.html', {'s': s, 'days': days, 'encounter': request.GET.get('encounter', ''),
                                                               'free_total': sum(d['free'] for d in days), 'stars': round(float(s.rating) * 2) / 2,
                                                               'colleagues': s.facility.specialists.filter(active=True).exclude(pk=s.pk)[:6]})


@login_required
def network_facilities(request):
    authorize(request, 'clinical')
    facs = NetworkFacility.objects.annotate(n_spec=Count('specialists', filter=Q(specialists__active=True), distinct=True),
                                            n_ref=Count('referrals', distinct=True)).order_by('name')
    return render(request, 'hospital/network_facilities.html', {'facilities': facs})


@login_required
def api_specialist_slots(request, pk):
    authorize(request, 'clinical')
    s = get_object_or_404(Specialist, pk=pk)
    now = timezone.now()
    free = s.slots.filter(start__gte=now, start__lte=now + timedelta(days=21), referral__isnull=True)[:60]
    return JsonResponse({'facility': s.facility_id, 'speciality': s.speciality, 'slots': [
        {'id': sl.pk, 'label': timezone.localtime(sl.start).strftime('%a %d %b · %H:%M'), 'mode': sl.get_mode_display(), 'day': timezone.localtime(sl.start).strftime('%Y-%m-%d')} for sl in free]})


@login_required
def referral_new(request):
    """Refer to a network facility (optionally a specialist and a booked slot) or to an outside destination."""
    authorize(request, 'clinical')
    form = ReferralNetworkForm(request.POST or None, initial={k: v for k, v in request.GET.items()})
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            r = form.save(commit=False)
            slot = form.cleaned_data.get('slot_id')
            if slot:
                slot = SpecialistSlot.objects.select_for_update().get(pk=slot.pk)
                if slot.is_booked:
                    form.add_error(None, 'That slot was just taken. Choose another.')
                    return render(request, 'hospital/referral_form.html', {'form': form, 'title': 'Create referral'})
                r.slot = slot
            if r.facility_id:
                r.destination = r.facility.name
                r.contact = r.contact or r.facility.phone
            if r.specialist_id and not r.speciality:
                r.speciality = r.specialist.speciality
            if form.cleaned_data.get('send_now'):
                r.status, r.sent_at = 'sent', timezone.now()
            r.save()
            if r.kind == 'operation':
                tests = {t.code: t for t in LabTest.objects.filter(code__in=[c for *_, c in PREOP_CHECKLIST if c])}
                for side, kind, title, code in PREOP_CHECKLIST:
                    ReferralTask.objects.create(referral=r, requested_by_side='receiver' if side == 'sender' else 'sender', assigned_to_side=side,
                                                kind=kind, title=title, lab_test=tests.get(code), due=r.planned_date, created_by=request.user)
            audit(request, 'create', f'hospital.Referral:{r.pk}', {'facility': r.facility_id, 'slot': r.slot_id})
        msg = f'Referral {r.number} {"sent to" if r.status == "sent" else "drafted for"} {r.destination}' + (f', booked {timezone.localtime(r.slot.start):%a %d %b %H:%M}' if r.slot else '') + '.'
        return finish(request, reverse('referral_detail', args=[r.pk]), msg)
    return render(request, 'hospital/referral_form.html', {'form': form, 'title': 'Create referral'})


@login_required
def referral_detail(request, pk):
    r = get_object_or_404(Referral.objects.select_related('encounter__patient', 'facility', 'specialist', 'slot'), pk=pk)
    side = referral_side(request, r)
    audit(request, 'view_chart', f'referral:{r.pk}', {'side': side})
    rank = {'open': 0, 'done': 1, 'cancelled': 2}   # open work first, overdue and soonest-due at the top
    tasks = sorted(r.tasks.select_related('lab_test', 'form', 'created_by', 'completed_by'),
                   key=lambda t: (rank[t.status], not t.overdue, t.due or date.max, t.pk))
    actions = [s for s in REFERRAL_FLOW.get(r.status, []) if (s in ('accepted', 'declined') and side == 'receiver') or (s not in ('accepted', 'declined') and side == 'sender')]
    stages = ['draft', 'sent', 'accepted', 'transferred', 'completed']
    idx = stages.index(r.status) if r.status in stages else -1
    return render(request, 'hospital/referral_detail.html', {
        'r': r, 'p': r.encounter.patient, 'side': side, 'actions': actions,
        'for_sender': [t for t in tasks if t.assigned_to_side == 'sender'], 'for_receiver': [t for t in tasks if t.assigned_to_side == 'receiver'],
        'track': [{'name': s, 'state': 'done' if idx > i else 'current' if idx == i else 'todo'} for i, s in enumerate(stages)],
        'task_kinds': ReferralTask.KIND, 'lab_tests': LabTest.objects.filter(active=True).order_by('name'),
        'forms': FormDefinition.objects.filter(published=True), 'open_encounter': r.encounter if r.encounter.status == 'open' else r.encounter.patient.encounters.filter(status='open').first()})


@login_required
@require_POST
def referral_status(request, pk, state):
    with transaction.atomic():
        r = get_object_or_404(Referral.objects.select_for_update(), pk=pk)
        side = referral_side(request, r)
        allowed = REFERRAL_FLOW.get(r.status, [])
        if state not in allowed or (state in ('accepted', 'declined')) != (side == 'receiver'):
            return HttpResponseBadRequest('That step is not available to you')
        if state == 'sent' and r.facility_id and not r.consent_to_share:
            messages.error(request, 'Record the patient\'s consent to share their records before sending to a network facility.')
            return redirect('referral_detail', pk=pk)
        r.status = state
        if state == 'sent':
            r.sent_at = timezone.now()
        if state == 'accepted':
            r.accepted_by = request.user.get_full_name() or request.user.username
        if state == 'completed':
            r.completed_at = timezone.now()
        if state in ('declined', 'cancelled') and r.slot_id:
            r.slot = None   # release the booked slot for other patients
        r.save()
        audit(request, 'referral_update', f'referral:{r.pk}', {'status': state, 'side': side})
    messages.success(request, f'Referral marked {r.get_status_display().lower()}.')
    return redirect('referral_detail', pk=pk)


@login_required
@require_POST
def referral_consent(request, pk):
    authorize(request, 'clinical')
    r = get_object_or_404(Referral, pk=pk)
    r.consent_to_share = True; r.save(update_fields=['consent_to_share', 'updated_at'])
    audit(request, 'referral_consent', f'referral:{r.pk}')
    messages.success(request, 'Consent to share records recorded.')
    return redirect('referral_detail', pk=pk)


@login_required
@require_POST
def referral_task_add(request, pk):
    r = get_object_or_404(Referral, pk=pk)
    side = referral_side(request, r)
    if side == 'sender':
        authorize(request, 'clinical')
    title = request.POST.get('title', '').strip()[:200]
    kind = request.POST.get('kind') if request.POST.get('kind') in dict(ReferralTask.KIND) else 'other'
    if not title:
        messages.error(request, 'Give the request a title.')
        return redirect('referral_detail', pk=pk)
    from datetime import date as _date
    try:
        due = _date.fromisoformat(request.POST.get('due', '')) if request.POST.get('due') else None
    except ValueError:
        due = None
    ReferralTask.objects.create(referral=r, requested_by_side=side, assigned_to_side='receiver' if side == 'sender' else 'sender', kind=kind, title=title,
                                details=request.POST.get('details', '')[:2000], due=due, created_by=request.user,
                                lab_test=LabTest.objects.filter(pk=request.POST.get('lab_test') or 0).first(),
                                form=FormDefinition.objects.filter(pk=request.POST.get('form') or 0, published=True).first())
    audit(request, 'referral_task', f'referral:{r.pk}', {'side': side, 'kind': kind})
    messages.success(request, 'Request sent to the ' + ('receiving facility.' if side == 'sender' else 'referring hospital.'))
    return redirect('referral_detail', pk=pk)


@login_required
@require_POST
def referral_task_update(request, pk, action):
    t = get_object_or_404(ReferralTask.objects.select_related('referral__encounter', 'lab_test'), pk=pk)
    side = referral_side(request, t.referral)
    if t.status != 'open':
        return HttpResponseBadRequest('Already closed')
    if action == 'order_test' and side == 'sender' and t.lab_test:
        authorize(request, 'clinical')
        enc = t.referral.encounter if t.referral.encounter.status == 'open' else t.referral.encounter.patient.encounters.filter(status='open').first()
        if not enc:
            messages.error(request, 'Open a visit for the patient before ordering the test.')
            return redirect('referral_detail', pk=t.referral_id)
        lr = LabRequest.objects.create(encounter=enc, requested_by=request.user, priority='urgent', clinical_notes=f'Requested by {t.referral.destination} for referral {t.referral.number}')
        LabOrder.objects.create(encounter=enc, request=lr, test=t.lab_test)
        t.response = f'Ordered as {lr.number}'; t.save(update_fields=['response', 'updated_at'])
        messages.success(request, f'{t.lab_test.name} ordered ({lr.number}). Mark the request done when the result is ready.')
        return redirect('referral_detail', pk=t.referral_id)
    if action == 'done' and t.assigned_to_side == side:
        t.status, t.completed_by, t.completed_at = 'done', request.user, timezone.now()
        t.response = (request.POST.get('response', '').strip()[:2000] or t.response)
    elif action == 'cancel' and t.requested_by_side == side:
        t.status = 'cancelled'
    else:
        return HttpResponseBadRequest('Not allowed')
    t.save()
    audit(request, 'referral_task', f'referral_task:{t.pk}', {'action': action, 'side': side})
    messages.success(request, 'Request updated.')
    return redirect('referral_detail', pk=t.referral_id)


@login_required
def referral_summary(request, pk):
    """The patient record shared with the receiving facility: only with consent, only once sent."""
    r = get_object_or_404(Referral.objects.select_related('encounter__patient', 'facility', 'specialist', 'slot'), pk=pk)
    side = referral_side(request, r)
    if side == 'receiver' and not r.shared:
        raise PermissionDenied('The patient has not consented to sharing their records with your facility.')
    p = r.encounter.patient
    audit(request, 'view_shared_record', f'referral:{r.pk}', {'side': side})
    values = (LabResultValue.objects.filter(order__encounter__patient=p, order__status__in=['resulted', 'verified'])
              .select_related('parameter', 'order__test').order_by('-order__resulted_at')[:40])
    meds = PrescriptionItem.objects.filter(prescription__encounter__patient=p).exclude(prescription__state='cancelled').select_related('medication', 'prescription').order_by('-prescription__created_at')[:15]
    return render(request, 'hospital/referral_summary.html', {
        'r': r, 'p': p, 'side': side, 'allergies': p.allergies.filter(status='active'), 'conditions': p.conditions.filter(status='active'),
        'values': values, 'meds': meds, 'imaging': ImagingOrder.objects.filter(encounter__patient=p, status='reported').order_by('-reported_at')[:8],
        'encounter': r.encounter, 'vitals': [(lbl, unit, r.encounter.vitals.get(k)) for k, lbl, unit, _ in VITAL_FIELDS if r.encounter.vitals.get(k)]})


@login_required
def network_inbox(request):
    """Home page for partner facilities: referrals sent to them, with open preparation requests."""
    fac = partner_facility(request.user)
    if not fac:
        return redirect('referrals')
    rows = list(Referral.objects.filter(facility=fac).exclude(status='draft').select_related('encounter__patient', 'specialist', 'slot')
                .annotate(open_for_me=Count('tasks', filter=Q(tasks__status='open', tasks__assigned_to_side='receiver')),
                          open_for_them=Count('tasks', filter=Q(tasks__status='open', tasks__assigned_to_side='sender'))).order_by('-sent_at'))
    return render(request, 'hospital/network_inbox.html', {'fac': fac, 'rows': rows,
                                                           'new': [r for r in rows if r.status == 'sent'], 'active': [r for r in rows if r.status in ('accepted', 'transferred')],
                                                           'closed': [r for r in rows if r.status in ('completed', 'declined', 'cancelled')][:20]})


# ---------------------------------------------------------------- bed detail

@login_required
def bed_detail(request, pk):
    authorize(request)
    b = get_object_or_404(Bed.objects.select_related('ward'), pk=pk)
    adms = list(Admission.objects.filter(bed=b).select_related('encounter__patient', 'encounter__clinician').order_by('-admitted_at')[:30])
    current = next((a for a in adms if not a.discharged_at), None)
    now = timezone.now()
    for a in adms:
        a.los_hours = ((a.discharged_at or now) - a.admitted_at).total_seconds() / 3600
        a.los_days = round(a.los_hours / 24, 1)
    past = [a for a in adms if a.discharged_at]
    window = now - timedelta(days=30)
    occupied_hours = sum(max(0, ((a.discharged_at or now) - max(a.admitted_at, window)).total_seconds() / 3600) for a in adms if (a.discharged_at or now) > window)
    # day-by-day occupancy strip for the last 30 days
    strip = []
    for i in range(29, -1, -1):
        d0 = timezone.make_aware(timezone.datetime.combine(timezone.localdate() - timedelta(days=i), timezone.datetime.min.time()))
        d1 = d0 + timedelta(days=1)
        occ = any(a.admitted_at < d1 and (a.discharged_at or now) > d0 for a in adms)
        strip.append({'date': d0, 'occ': occ})
    ctx = {'b': b, 'current': current, 'history': adms, 'strip': strip,
           'stats': {'uses': len(adms), 'avg_los': round(sum(a.los_days for a in past) / len(past), 1) if past else None,
                     'occupancy': round(occupied_hours * 100 / (30 * 24))},
           'events': AuditEvent.objects.filter(target__in=[f'bed:{b.pk}'] + [f'admission:{a.pk}' for a in adms]).select_related('actor')[:15],
           'neighbours': Bed.objects.filter(ward=b.ward).order_by('code')}
    if current:
        e = current.encounter
        ctx.update({'e': e, 'p': e.patient, 'allergies': e.patient.allergies.filter(status='active'),
                    'vitals': [(lbl, unit, e.vitals.get(k)) for k, lbl, unit, _ in VITAL_FIELDS if e.vitals.get(k)],
                    'meds': PrescriptionItem.objects.filter(prescription__encounter__patient=e.patient, prescription__state__in=['signed', 'partial', 'dispensed'],
                                                            prescription__created_at__gte=current.admitted_at - timedelta(days=1)).select_related('medication')[:10],
                    'pending_labs': lab_requests_qs().filter(encounter__patient=e.patient, orders__status__in=['ordered', 'collected', 'processing']).distinct()[:5],
                    'stay_pct': min(100, round(current.los_days * 100 / 7))})
        ctx['mar'], ctx['mar_counts'] = medication_chart(e.patient, current.admitted_at)
    return render(request, 'hospital/bed_detail.html', ctx)


@login_required
@require_POST
def bed_maintenance(request, pk):
    authorize(request, 'beds')
    with transaction.atomic():
        b = get_object_or_404(Bed.objects.select_for_update(), pk=pk)
        if b.state != 'available':
            return HttpResponseBadRequest('Only an empty, clean bed can be taken out of service')
        b.state = 'maintenance'; b.save(update_fields=['state', 'updated_at'])
        audit(request, 'bed_maintenance', f'bed:{b.pk}', {'reason': request.POST.get('reason', '')[:200]})
    messages.success(request, f'Bed {b.code} taken out of service.')
    return redirect('bed_detail', pk=pk)


# ---------------------------------------------------------------- finance

ROLES['billing'] = {'finance', 'reception', 'admin'}
ROLES['finance_admin'] = {'finance', 'admin'}


def money(v):
    return Decimal(v or 0).quantize(Decimal('0.01'))


def invoices_qs():
    return Invoice.objects.select_related('patient', 'encounter').prefetch_related('lines', 'payments')


@login_required
def finance_dashboard(request):
    authorize(request, 'billing')
    today = timezone.localdate()
    pays = list(Payment.objects.filter(voided=False, received_at__date__gte=today - timedelta(days=13)).select_related('invoice__patient', 'received_by'))
    days = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        days.append({'label': d.strftime('%a %d'), 'value': sum(p.amount for p in pays if timezone.localtime(p.received_at).date() == d), 'today': d == today})
    peak = max([d['value'] for d in days] + [Decimal(1)])
    for d in days:
        d['pct'] = max(3, round(d['value'] * 100 / peak))
    today_pays = [p for p in pays if timezone.localtime(p.received_at).date() == today]
    methods = {}
    for p in today_pays:
        methods[p.get_method_display()] = methods.get(p.get_method_display(), 0) + p.amount
    open_invs = list(invoices_qs().filter(status__in=['issued', 'partial']))
    aging = {'0–30 days': Decimal(0), '31–60 days': Decimal(0), 'Over 60 days': Decimal(0)}
    for inv in open_invs:
        age = (today - timezone.localtime(inv.issued_at or inv.created_at).date()).days
        aging['0–30 days' if age <= 30 else '31–60 days' if age <= 60 else 'Over 60 days'] += inv.balance
    by_cat = {}
    for l in InvoiceLine.objects.filter(invoice__status__in=['issued', 'partial', 'paid'], invoice__issued_at__date__gte=today - timedelta(days=29)):
        by_cat[l.get_category_display()] = by_cat.get(l.get_category_display(), 0) + l.total
    cat_total = sum(by_cat.values()) or 1
    return render(request, 'hospital/finance.html', {
        'today_total': sum(p.amount for p in today_pays), 'today_count': len(today_pays), 'week_total': sum(d['value'] for d in days[-7:]),
        'outstanding': sum(i.balance for i in open_invs), 'open_count': len(open_invs), 'drafts': Invoice.objects.filter(status='draft').count(),
        'days': days, 'methods': sorted(methods.items(), key=lambda x: -x[1]), 'aging': aging.items(),
        'by_cat': [(k, v, round(v * 100 / cat_total)) for k, v in sorted(by_cat.items(), key=lambda x: -x[1])],
        'recent': sorted(pays, key=lambda p: p.received_at, reverse=True)[:12],
        'biggest': sorted(open_invs, key=lambda i: -i.balance)[:8]})


@login_required
def invoice_list(request):
    authorize(request, 'billing')
    status, q = request.GET.get('status', ''), request.GET.get('q', '').strip()
    qs = invoices_qs()
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(Q(patient__first_name__icontains=q) | Q(patient__last_name__icontains=q) | Q(patient__mrn__icontains=q))
    return render(request, 'hospital/invoices.html', {'rows': qs[:300], 'status': status, 'q': q, 'statuses': Invoice.STATUS})


@login_required
def invoice_for_encounter(request, pk):
    """Open (or start) the bill for a visit and pull in its charges."""
    authorize(request, 'billing')
    e = get_object_or_404(Encounter, pk=pk)
    inv = open_invoice_for(e, request.user)
    n = capture_charges(inv)
    if n:
        messages.success(request, f'{n} charge{"s" if n > 1 else ""} added to {inv.number}.')
    return redirect('invoice_detail', pk=inv.pk)


@login_required
def invoice_detail(request, pk):
    authorize(request, 'billing')
    inv = get_object_or_404(invoices_qs().select_related('created_by'), pk=pk)
    lines = list(inv.lines.all())
    groups = {}
    for l in lines:
        groups.setdefault(l.get_category_display(), []).append(l)
    return render(request, 'hospital/invoice_detail.html', {
        'inv': inv, 'p': inv.patient, 'groups': [(k, v, sum(x.total for x in v)) for k, v in groups.items()],
        'payments': inv.payments.select_related('received_by'), 'tariffs': Tariff.objects.filter(active=True),
        'methods': Payment.METHOD, 'can_admin': role_of(request.user) in ROLES['finance_admin'],
        'editable': inv.status == 'draft', 'other_open': inv.patient.invoices.filter(status__in=['issued', 'partial']).exclude(pk=inv.pk)})


def _inv_for_change(request, pk, allowed=('draft',)):
    inv = get_object_or_404(Invoice.objects.select_for_update(), pk=pk)
    if inv.status not in allowed:
        raise ValidationError(f'This action is not possible on a {inv.get_status_display().lower()} bill.')
    return inv


def _finance_action(fn):
    """Run a bill-changing action; show validation problems as messages and return to the bill."""
    from functools import wraps

    @wraps(fn)
    def inner(request, pk, *a, **kw):
        authorize(request, 'billing')
        try:
            with transaction.atomic():
                msg = fn(request, pk, *a, **kw)
            if msg:
                messages.success(request, msg)
        except ValidationError as e:
            messages.error(request, '; '.join(e.messages))
        return redirect(request.POST.get('next') or reverse('invoice_detail', args=[pk]))
    return login_required(require_POST(inner))


@_finance_action
def invoice_capture(request, pk):
    inv = _inv_for_change(request, pk, ('draft', 'issued', 'partial'))
    n = capture_charges(inv)
    inv.refresh_status(); inv.save()
    return f'{n} new charge{"s" if n != 1 else ""} added.' if n else 'Everything for this visit is already billed.'


@_finance_action
def invoice_add_line(request, pk):
    inv = _inv_for_change(request, pk)
    t = Tariff.objects.filter(pk=request.POST.get('tariff') or 0, active=True).first()
    try:
        qty = Decimal(request.POST.get('quantity') or 1)
        price = Decimal(request.POST.get('unit_price')) if request.POST.get('unit_price') else (t.amount if t else None)
    except Exception:
        raise ValidationError('Enter a valid quantity and price.')
    desc = (request.POST.get('description') or '').strip() or (t.name if t else '')
    if not desc or price is None or price < 0 or qty <= 0:
        raise ValidationError('Choose a price-list item or enter a description and price.')
    InvoiceLine.objects.create(invoice=inv, category=t.category if t and t.category in dict(InvoiceLine.CATEGORY) else (request.POST.get('category') or 'other'),
                               description=desc[:200], quantity=qty, unit_price=price)
    audit(request, 'invoice_line', f'invoice:{inv.pk}', {'description': desc})
    return f'Added: {desc}.'


@_finance_action
def invoice_remove_line(request, pk, line_pk):
    inv = _inv_for_change(request, pk)
    inv.lines.filter(pk=line_pk).delete()
    return 'Line removed.'


@_finance_action
def invoice_update(request, pk):
    inv = _inv_for_change(request, pk, ('draft', 'issued'))
    if inv.payments.filter(voided=False).exists():
        raise ValidationError('Discount and insurance cannot change after a payment has been taken.')
    try:
        disc = money(request.POST.get('discount') or 0); cover = int(request.POST.get('insurance_cover') or 0)
    except Exception:
        raise ValidationError('Enter numbers for the discount and insurance cover.')
    reason = request.POST.get('discount_reason', '').strip()[:200]
    if disc > 0 and not reason:
        raise ValidationError('Give a reason for the discount.')
    if disc > 0 and role_of(request.user) not in ROLES['finance_admin']:
        raise PermissionDenied('Only finance staff can give a discount.')
    if not 0 <= cover <= 100 or disc < 0 or disc > inv.subtotal:
        raise ValidationError('Discount must be between 0 and the bill total, and cover between 0 and 100%.')
    inv.discount, inv.discount_reason, inv.insurance_cover = disc, reason, cover
    inv.insurer, inv.policy_number = request.POST.get('insurer', '')[:120], request.POST.get('policy_number', '')[:60]
    inv.save()
    audit(request, 'invoice_update', f'invoice:{inv.pk}', {'discount': str(disc), 'cover': cover})
    return 'Bill updated.'


@_finance_action
def invoice_issue(request, pk):
    inv = _inv_for_change(request, pk)
    if not inv.lines.exists():
        raise ValidationError('Add at least one charge before issuing the bill.')
    inv.status, inv.issued_at = 'issued', timezone.now()
    inv.due_date = inv.due_date or timezone.localdate() + timedelta(days=30)
    inv.refresh_status(); inv.save()
    audit(request, 'invoice_issue', f'invoice:{inv.pk}', {'total': str(inv.total)})
    return f'{inv.number} issued for D{inv.total}.'


@_finance_action
def invoice_void(request, pk):
    if role_of(request.user) not in ROLES['finance_admin']:
        raise PermissionDenied('Only finance staff can void a bill.')
    inv = _inv_for_change(request, pk, ('draft', 'issued'))
    reason = request.POST.get('reason', '').strip()[:200]
    if not reason:
        raise ValidationError('Give a reason for voiding the bill.')
    if inv.payments.filter(voided=False).exists():
        raise ValidationError('Void the payments first.')
    inv.status, inv.void_reason = 'void', reason; inv.save()
    audit(request, 'invoice_void', f'invoice:{inv.pk}', {'reason': reason})
    return f'{inv.number} voided. Its charges can be billed again on a new bill.'


@_finance_action
def payment_new(request, pk):
    inv = get_object_or_404(Invoice, pk=pk)
    method = request.POST.get('method') if request.POST.get('method') in dict(Payment.METHOD) else None
    if not method:
        raise ValidationError('Choose how the patient paid.')
    try:
        amount = money(request.POST.get('amount'))
    except Exception:
        raise ValidationError('Enter the amount received.')
    pay = record_payment(inv, amount, method, request.POST.get('reference', ''), request.user)
    inv.refresh_from_db()
    return f'Received D{pay.amount} by {pay.get_method_display()} · receipt {pay.receipt_number}.' + (' Bill fully paid.' if inv.status == 'paid' else f' Balance D{inv.balance}.')


@login_required
@require_POST
def payment_void(request, pk):
    authorize(request, 'finance_admin')
    with transaction.atomic():
        pay = get_object_or_404(Payment.objects.select_for_update().select_related('invoice'), pk=pk)
        reason = request.POST.get('reason', '').strip()[:200]
        if pay.voided or not reason:
            messages.error(request, 'Give a reason to void this payment.')
            return redirect('invoice_detail', pk=pay.invoice_id)
        pay.voided, pay.void_reason = True, reason; pay.save()
        inv = pay.invoice; inv.refresh_status(); inv.save()
        audit(request, 'payment_void', f'payment:{pay.pk}', {'reason': reason, 'amount': str(pay.amount)})
    messages.success(request, f'Payment {pay.receipt_number} voided.')
    return redirect('invoice_detail', pk=pay.invoice_id)


@login_required
def payment_receipt(request, pk):
    authorize(request, 'billing')
    pay = get_object_or_404(Payment.objects.select_related('invoice__patient', 'received_by'), pk=pk)
    return render(request, 'hospital/receipt.html', {'pay': pay, 'inv': pay.invoice, 'p': pay.invoice.patient})


@login_required
def tariff_list(request):
    authorize(request, 'billing')
    return render(request, 'hospital/tariffs.html', {
        'tariffs': Tariff.objects.all(), 'tests': LabTest.objects.filter(active=True).select_related('category').order_by('category__sort_order', 'name'),
        'meds': Medication.objects.filter(active=True).order_by('name')})


# ---------------------------------------------------------------- decision support

@login_required
def api_clinical(request):
    """Live decision support for the prescribing and test-ordering forms."""
    authorize(request, 'clinical')
    from .clinical import clinical_review, treatment_suggestions, ai_enabled
    e = Encounter.objects.select_related('patient').filter(pk=request.GET.get('encounter') or 0).first()
    if not e:
        return JsonResponse({'ready': False})
    ids = lambda key: [int(x) for x in request.GET.get(key, '').split(',') if x.isdigit()][:40]
    meds = list(Medication.objects.filter(pk__in=ids('meds')))
    tests = list(LabTest.objects.filter(pk__in=ids('tests')))
    p = e.patient
    return JsonResponse({'ready': True, 'patient': p.full_name, 'diagnosis': e.diagnosis or e.reason,
                         'allergies': list(p.allergies.filter(status='active').values('substance', 'reaction', 'severity')),
                         'findings': clinical_review(e, meds, tests), 'suggestions': treatment_suggestions(e), 'ai': ai_enabled()})


@login_required
def ai_context_preview(request, pk):
    """Exactly what an AI service would receive for this visit: de-identified, for transparency and audit."""
    authorize(request, 'clinical')
    from .clinical import deidentified_context, ai_enabled
    e = get_object_or_404(Encounter.objects.select_related('patient'), pk=pk)
    ctx = deidentified_context(e)
    audit(request, 'ai_context_preview', f'encounter:{e.pk}')
    return render(request, 'hospital/ai_context.html', {'e': e, 'p': e.patient, 'json': json.dumps(ctx, indent=2, default=str), 'enabled': ai_enabled()})


@login_required
def patient_story(request, pk):
    """Plays the whole medical record back in time order."""
    authorize(request, 'clinical')
    p = get_object_or_404(Patient, pk=pk)
    audit(request, 'view_chart', f'patient_story:{p.pk}')
    ev = []
    ts = lambda dt: timezone.localtime(dt).isoformat()
    for e in p.encounters.select_related('department').order_by('created_at'):
        v = e.vitals or {}
        ev.append({'t': ts(e.created_at), 'kind': 'visit', 'title': e.reason, 'detail': e.diagnosis, 'outcome': e.get_outcome_display() if e.outcome else '',
                   'dept': str(e.department or ''), 'vitals': {k: v.get(k) for k in ('bp', 'heart_rate', 'temperature_c', 'spo2') if v.get(k)},
                   'url': reverse('encounter_detail', args=[e.pk])})
    for r in lab_requests_qs().filter(encounter__patient=p, orders__status__in=['resulted', 'verified']).distinct():
        vals = []
        for o in r.orders.all():
            if o.status not in ('resulted', 'verified'):
                continue
            for x in o.values.all():
                vals.append({'code': x.parameter.code, 'name': x.parameter.name, 'value': x.display, 'num': _f(x.value_number), 'unit': x.parameter.unit,
                             'flag': x.flag, 'system': x.parameter.system, 'lo': _f(x.parameter.range_for(p.sex)[0]), 'hi': _f(x.parameter.range_for(p.sex)[1])})
        when = max((o.resulted_at or o.created_at) for o in r.orders.all() if o.status in ('resulted', 'verified'))
        ev.append({'t': ts(when), 'kind': 'lab', 'title': ', '.join(o.test.name for o in r.orders.all() if o.status in ('resulted', 'verified')), 'values': vals,
                   'url': reverse('lab_request_detail', args=[r.pk])})
    for rx in Prescription.objects.filter(encounter__patient=p).exclude(state='cancelled').prefetch_related('items__medication').order_by('created_at'):
        ev.append({'t': ts(rx.created_at), 'kind': 'rx', 'title': ', '.join(str(i.medication) for i in rx.items.all()) or rx.number,
                   'lines': [i.directions for i in rx.items.all()], 'url': reverse('prescription_detail', args=[rx.pk])})
    for o in ImagingOrder.objects.filter(encounter__patient=p, status__in=['acquired', 'reported']).prefetch_related('images'):
        img = o.images.first()
        ev.append({'t': ts(o.reported_at or o.created_at), 'kind': 'imaging', 'title': f'{o.get_modality_display()} · {o.region}', 'detail': o.impression,
                   'abnormal': o.abnormal, 'system': o.body_system, 'image': reverse('imaging_file', args=[img.pk]) if img else '', 'url': reverse('imaging_detail', args=[o.pk])})
    for a in Admission.objects.filter(encounter__patient=p).select_related('bed__ward', 'encounter'):
        ev.append({'t': ts(a.admitted_at), 'kind': 'admission', 'title': f'Admitted to {a.bed.ward} · {a.bed.code}', 'detail': a.encounter.diagnosis,
                   'until': ts(a.discharged_at) if a.discharged_at else None, 'url': reverse('bed_detail', args=[a.bed_id])})
    for r in Referral.objects.filter(encounter__patient=p).exclude(status='draft'):
        ev.append({'t': ts(r.sent_at or r.created_at), 'kind': 'referral', 'title': f'Referred to {r.destination}', 'detail': r.speciality, 'url': reverse('referral_detail', args=[r.pk])})
    for a in p.allergies.all():
        ev.append({'t': ts(a.created_at), 'kind': 'allergy', 'title': f'Allergy recorded: {a.substance}', 'detail': f'{a.reaction} · {a.severity}'})
    ev.sort(key=lambda x: x['t'])
    return render(request, 'hospital/story.html', {'p': p, 'events': ev, 'systems': dict(BODY_SYSTEMS)})


# ---------------------------------------------------------------- QR access, check-in, queue numbering

@login_required
def patient_qr(request, mrn):
    """Target of the patient QR code: opens the record after sign-in. Partners and unknown numbers get nothing."""
    authorize(request)
    p = get_object_or_404(Patient, mrn__iexact=mrn)
    audit(request, 'qr_open', f'patient:{p.pk}')
    return redirect('patient_chart', pk=p.pk)


def find_patients(q):
    q = (q or '').strip()
    if not q:
        return [], None
    exact = Patient.objects.filter(mrn__iexact=q).first()
    if exact:
        return [exact], exact
    digits = re.sub(r'\D', '', q)
    qs = Patient.objects.all()
    cond = Q(mrn__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
    if len(digits) >= 6:
        cond |= Q(phone__icontains=digits[-7:])
    return list(qs.filter(cond).order_by('last_name')[:15]), None


@login_required
def checkin(request):
    """Returning patients: enter their patient number (or scan their QR), confirm, and issue a queue number."""
    authorize(request, 'reception')
    q = request.GET.get('q', '') or request.POST.get('q', '')
    if request.method == 'POST':
        p = get_object_or_404(Patient, pk=request.POST.get('patient'))
        dept = get_object_or_404(Department, pk=request.POST.get('department'))
        try:
            priority = int(request.POST.get('priority') or 3)
        except ValueError:
            priority = 3
        with transaction.atomic():
            enc = p.encounters.filter(status='open').order_by('-created_at').first()
            if not enc or request.POST.get('new_visit') == 'on':
                enc = Encounter.objects.create(patient=p, department=dept, reason=(request.POST.get('reason') or f'{dept.name} visit')[:255])
            t = QueueTicket.objects.create(patient=p, encounter=enc, department=dept, priority=priority if priority in (1, 2, 3, 4) else 3)
            audit(request, 'checkin', f'ticket:{t.pk}', {'returning': True})
        messages.success(request, f'{p.full_name} checked in · queue number {t.display_code}.')
        return redirect('ticket_slip', pk=t.pk)
    matches, exact = find_patients(q)
    sel = exact or (matches[0] if len(matches) == 1 else None)
    ctx = {'q': q, 'matches': matches, 'sel': sel, 'departments': Department.objects.order_by('name'), 'priorities': QueueTicket.PRIORITY}
    if sel:
        ctx.update({'open_enc': sel.encounters.filter(status='open').first(), 'last_enc': sel.encounters.order_by('-created_at').first(),
                    'allergies': sel.allergies.filter(status='active'), 'waiting_ticket': QueueTicket.objects.filter(patient=sel, status__in=['waiting', 'called', 'in_service']).first(),
                    'owing': sum(i.balance for i in sel.invoices.filter(status__in=['issued', 'partial']))})
    return render(request, 'hospital/checkin.html', ctx)


@login_required
def ticket_slip(request, pk):
    authorize(request)
    t = get_object_or_404(QueueTicket.objects.select_related('patient', 'department'), pk=pk)
    ahead, est = queue_position(t)
    return render(request, 'hospital/ticket_slip.html', {'t': t, 'p': t.patient, 'ahead': ahead, 'est': est, 'share': ticket_share(request, t)})


@login_required
@require_POST
def queue_reset(request):
    authorize(request, 'reception')
    dept = Department.objects.filter(pk=request.POST.get('department') or 0).first()
    QueueReset.objects.create(department=dept, reset_by=request.user)
    audit(request, 'queue_reset', f'department:{dept.pk if dept else "all"}')
    messages.success(request, f'Queue numbers restart from 001 for {dept.name if dept else "all departments"}. Waiting patients keep their numbers.')
    return redirect('queue')


# ---------------------------------------------------------------- medication chart (bed page)

DOSE_HOURS = {'OD': [8], 'BD': [8, 20], 'TDS': [8, 14, 20], 'QDS': [6, 12, 18, 22], 'Q4H': [2, 6, 10, 14, 18, 22], 'Q6H': [0, 6, 12, 18],
              'Q8H': [6, 14, 22], 'Q12H': [8, 20], 'MANE': [7], 'NOCTE': [22]}


def medication_chart(patient, since, day=None):
    """Today's doses for an inpatient: what was given, what is due, what is late, and what is still to come."""
    now = timezone.localtime()
    day = day or now.date()
    d0 = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time()))
    items = (PrescriptionItem.objects.filter(prescription__encounter__patient=patient, prescription__state__in=['signed', 'partial', 'dispensed'],
                                             prescription__created_at__gte=since - timedelta(days=1)).exclude(availability='unavailable')
             .select_related('medication', 'prescription').prefetch_related('administrations__given_by'))
    rows = []
    for it in items:
        start = it.prescription.signed_at or it.prescription.created_at
        end = start + timedelta(days=it.duration_days) if it.frequency not in ('PRN', 'STAT', 'ASDIR') else None
        given = {timezone.localtime(a.scheduled_for).replace(second=0, microsecond=0): a for a in it.administrations.all()}
        slots = []
        if it.frequency in DOSE_HOURS:
            for h in DOSE_HOURS[it.frequency]:
                at = d0 + timedelta(hours=h)
                if at < start - timedelta(hours=1) or (end and at > end):
                    continue
                a = given.get(timezone.localtime(at).replace(second=0, microsecond=0))
                state = a.status if a else ('late' if at < now - timedelta(hours=1) else 'due' if at <= now + timedelta(minutes=60) else 'upcoming')
                slots.append({'at': at, 'state': state, 'adm': a})
        elif it.frequency == 'STAT':
            a = next(iter(given.values()), None)
            slots.append({'at': start, 'state': a.status if a else 'due', 'adm': a})
        prn = [a for a in it.administrations.all() if it.frequency in ('PRN', 'ASDIR') and timezone.localtime(a.given_at).date() == day]
        if not slots and it.frequency not in ('PRN', 'ASDIR', 'STAT'):
            continue                                     # course finished or not started on this day
        rows.append({'item': it, 'slots': slots, 'prn': prn, 'is_prn': it.frequency in ('PRN', 'ASDIR')})
    counts = {'given': sum(s['state'] == 'given' for r in rows for s in r['slots']), 'due': sum(s['state'] == 'due' for r in rows for s in r['slots']),
              'late': sum(s['state'] == 'late' for r in rows for s in r['slots']), 'upcoming': sum(s['state'] == 'upcoming' for r in rows for s in r['slots'])}
    return rows, counts


@login_required
@require_POST
def administer(request, item_pk):
    authorize(request, 'clinical')
    it = get_object_or_404(PrescriptionItem.objects.select_related('medication', 'prescription__encounter'), pk=item_pk)
    status = request.POST.get('status') if request.POST.get('status') in dict(MedicationAdministration.STATUS) else 'given'
    from django.utils.dateparse import parse_datetime
    when = parse_datetime(request.POST.get('scheduled_for') or '') or timezone.now()
    if timezone.is_naive(when):
        when = timezone.make_aware(when)
    when = when.replace(second=0, microsecond=0)
    note = request.POST.get('note', '').strip()[:200]
    if status != 'given' and not note:
        messages.error(request, 'Say why the dose was not given.')
    elif MedicationAdministration.objects.filter(item=it, scheduled_for=when).exists():
        messages.error(request, 'This dose has already been recorded.')
    else:
        MedicationAdministration.objects.create(item=it, scheduled_for=when, status=status, given_by=request.user, note=note)
        audit(request, 'administer', f'prescription_item:{it.pk}', {'status': status})
        messages.success(request, f'{it.medication} · {"given" if status == "given" else dict(MedicationAdministration.STATUS)[status].lower()} at {timezone.localtime().strftime("%H:%M")}.')
    return redirect(request.POST.get('next') or 'beds')


# ---------------------------------------------------------------- hospital health intelligence

@login_required
def health_dashboard(request):
    authorize(request, 'all')
    from .health import health_data
    days = int(request.GET.get('days', 90)) if request.GET.get('days', '90').isdigit() else 90
    days = days if days in (30, 90, 180, 365) else 90
    return render(request, 'hospital/health.html', {'data': health_data(days), 'days': days})


# ---------------------------------------------------------------- queue tickets: thermal print, sharing, public status

def ticket_token(t):
    from django.core import signing
    return signing.dumps(t.pk, salt='medflow.ticket')


def ticket_share(request, t):
    """Text and links for sending a ticket to the patient. The status link shows no name or medical details."""
    from urllib.parse import quote
    status_url = request.build_absolute_uri(reverse('ticket_status', args=[ticket_token(t)]))
    text = (f'MedFlow Hospital · your queue number is {t.display_code} ({t.department}). '
            f'Issued {timezone.localtime(t.created_at):%d %b %H:%M}. Follow your place in the queue: {status_url}')
    digits = re.sub(r'\D', '', t.patient.phone or '')
    if len(digits) == 7:
        digits = '220' + digits                           # local Gambian number
    return {'status_url': status_url, 'text': text,
            'whatsapp': f'https://wa.me/{digits}?text={quote(text)}' if digits else f'https://wa.me/?text={quote(text)}',
            'email': f'mailto:{t.patient.email}?subject={quote("Your queue number " + t.display_code)}&body={quote(text)}', 'has_phone': bool(digits)}


def queue_position(t):
    ahead = QueueTicket.objects.filter(department=t.department, status='waiting').filter(
        Q(priority__lt=t.priority) | Q(priority=t.priority, created_at__lt=t.created_at)).count() if t.status == 'waiting' else 0
    recent = list(QueueTicket.objects.filter(department=t.department, called_at__isnull=False, created_at__gte=timezone.now() - timedelta(days=7))
                  .values_list('created_at', 'called_at')[:200])
    per = (sum((k - c).total_seconds() for c, k in recent) / len(recent) / 60) if recent else 15
    est = round(min(240, max(5, per * .4)) * ahead) if ahead else 0     # rough: average wait split across those ahead
    return ahead, est


@login_required
def ticket_thermal(request, pk):
    """Bare page sized for 80 mm or 58 mm receipt printers; prints itself."""
    authorize(request)
    t = get_object_or_404(QueueTicket.objects.select_related('patient', 'department'), pk=pk)
    width = '58' if request.GET.get('w') == '58' else '80'
    ahead, est = queue_position(t)
    import segno
    from django.utils.safestring import mark_safe
    share = ticket_share(request, t)
    qr = mark_safe(segno.make(share['status_url'], error='m').svg_inline(scale=3 if width == '80' else 2, border=1))
    return render(request, 'hospital/ticket_thermal.html', {'t': t, 'width': width, 'ahead': ahead, 'est': est, 'qr': qr})


def ticket_status(request, token):
    """Public page for the patient's phone: queue number, department, people ahead. No login, no personal details."""
    from django.core import signing
    try:
        pk = signing.loads(token, salt='medflow.ticket', max_age=60 * 60 * 24)
    except signing.BadSignature:
        from django.http import Http404
        raise Http404
    t = get_object_or_404(QueueTicket.objects.select_related('department'), pk=pk)
    ahead, est = queue_position(t)
    return render(request, 'hospital/ticket_status.html', {'t': t, 'ahead': ahead, 'est': est,
                                                           'serving': QueueTicket.objects.filter(department=t.department, status__in=['called', 'in_service']).order_by('-called_at').first()})


@login_required
def health_explore(request):
    """Drill-down: filter by diagnosis, town, age band and sex; every chart recomputes for that slice."""
    authorize(request, 'all')
    from .health import explore_data
    data = explore_data(**_explore_filters(request.GET))
    data.pop('points', None)
    return render(request, 'hospital/health_explore.html', {'data': data})


def _explore_filters(g):
    days = int(g.get('days')) if (g.get('days') or '').isdigit() and int(g.get('days')) in (30, 90, 180, 365) else 90
    age = g.get('age', '') if g.get('age', '').isdigit() and int(g.get('age')) < 9 else ''
    return {'days': days, 'dx': g.get('dx', '')[:40], 'town': g.get('town', '')[:60], 'age': age, 'sex': g.get('sex', '') if g.get('sex') in ('M', 'F') else ''}


@login_required
def health_map_view(request):
    """A real map (OpenStreetMap via Folium) of patients by location for the current filters; shown in an iframe."""
    authorize(request, 'all')
    from django.http import HttpResponse
    from .health import explore_data
    from .maps import health_map
    f = _explore_filters(request.GET)
    data = explore_data(**f)
    resp = HttpResponse(health_map(data['points'], reverse('health_explore'), f, active=f['town']))
    resp['Referrer-Policy'] = 'strict-origin-when-cross-origin'   # tile servers see only this site's origin
    return resp


@login_required
def locations(request):
    """Towns and areas used for patient addresses and maps. Add one by name and click its position on the map."""
    authorize(request, 'all')
    can_edit = role_of(request.user) in ('admin', 'management', 'reception')
    edit = Location.objects.filter(pk=request.GET.get('edit') or 0).first()
    if request.method == 'POST':
        if not can_edit:
            raise PermissionDenied('Only reception, management or admin can change locations.')
        from decimal import Decimal, InvalidOperation
        loc = Location.objects.filter(pk=request.POST.get('id') or 0).first() or Location()
        try:
            loc.name = request.POST.get('name', '').strip()[:120]
            loc.kind = 'area' if request.POST.get('parent') else 'town'
            loc.parent = Location.objects.filter(pk=request.POST.get('parent') or 0, kind='town').first()
            loc.region = loc.parent.region if loc.parent else (request.POST.get('region') if request.POST.get('region') in dict(Location.REGIONS) else 'other')
            loc.latitude, loc.longitude = Decimal(request.POST['latitude']), Decimal(request.POST['longitude'])
            if not loc.name or not (-90 <= loc.latitude <= 90 and -180 <= loc.longitude <= 180):
                raise ValueError
            loc.save()
            audit(request, 'location_save', f'location:{loc.pk}', {'name': loc.name})
            messages.success(request, f'{loc} saved. It can now be chosen for patients and appears on the maps.')
            return redirect('locations')
        except (KeyError, ValueError, InvalidOperation):
            messages.error(request, 'Give a name and click the map (or type latitude and longitude) to place it.')
        except Exception:
            messages.error(request, 'That name already exists here.')
    locs = Location.objects.select_related('parent').annotate(n=Count('patients')).order_by('region', 'parent__name', 'name')
    resp = render(request, 'hospital/locations.html', {
        'tiles': __import__('hospital.maps', fromlist=['tile_layers']).tile_layers(),
        'locs': locs, 'towns': Location.objects.filter(kind='town').order_by('name'), 'regions': Location.REGIONS, 'edit': edit, 'can_edit': can_edit,
        'geo': [{'id': l.pk, 'name': str(l), 'lat': float(l.latitude), 'lon': float(l.longitude), 'kind': l.kind, 'n': l.n} for l in locs]})
    resp['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return resp
