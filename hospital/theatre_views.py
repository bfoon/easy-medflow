"""Operating theatre pages: the day board, booking an operation or procedure, and the case page where the team moves the
patient through pre-op checks, the WHO Surgical Safety Checklist, the operation note and recovery.

Every change is checked by hospital/theatre.py on the server and audited. The case page sends JSON and redraws from the
server's answer, so what is shown is always what was saved.
"""
import json
from datetime import date, datetime

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import theatre as T
from .forms import StyledModelForm
from .models import Encounter, OperatingRoom, ProcedureType, SurgicalCase
from .views import ROLES, audit, authorize, finish, role_of

ROLES['theatre'] = {'doctor', 'nurse', 'admin'}
ROLES['theatre_view'] = {'doctor', 'nurse', 'admin', 'management'}
NOTE_ROLES = {'doctor', 'admin'}      # standard roles; administrators can give or remove 'operation_note' per group


def can_note(user):
    from .access import has
    return has(user, 'operation_note')


def staff_choices(roles):
    U = get_user_model()
    return U.objects.filter(Q(hospital_staff__role__in=roles, hospital_staff__active=True) | Q(is_superuser=True)).order_by('first_name', 'username').distinct()


class StaffChoice(forms.ModelChoiceField):
    def label_from_instance(self, u):
        return u.get_full_name() or u.username


class SurgicalCaseForm(StyledModelForm):
    surgeon = StaffChoice(queryset=None, required=False)
    assistant = StaffChoice(queryset=None, required=False)
    anaesthetist = StaffChoice(queryset=None, required=False)
    scrub_nurse = StaffChoice(queryset=None, required=False)

    class Meta:
        model = SurgicalCase
        fields = ['encounter', 'procedure_type', 'procedure', 'specialty', 'side', 'site', 'indication', 'urgency', 'room', 'scheduled_start',
                  'est_minutes', 'anaesthesia', 'asa', 'blood_units', 'surgeon', 'assistant', 'anaesthetist', 'scrub_nurse']
        labels = {'encounter': 'Visit', 'procedure': 'Procedure name (if not in the catalogue, or to add detail)', 'room': 'Theatre',
                  'scheduled_start': 'Start', 'indication': 'Indication / diagnosis'}
        widgets = {'scheduled_start': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
                   'indication': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        enc = Encounter.objects.filter(status='open').select_related('patient')
        if self.instance.pk:
            enc = Encounter.objects.filter(pk=self.instance.encounter_id).select_related('patient')
        self.fields['encounter'].queryset = enc
        self.fields['procedure_type'].queryset = ProcedureType.objects.filter(active=True)
        self.fields['room'].queryset = OperatingRoom.objects.filter(active=True)
        self.fields['surgeon'].queryset = self.fields['assistant'].queryset = self.fields['anaesthetist'].queryset = staff_choices(['doctor', 'specialist'])
        self.fields['scrub_nurse'].queryset = staff_choices(['nurse'])
        self.fields['scheduled_start'].help_text = 'Leave the theatre and start empty to put the case on the waiting list.'
        for name, f in self.fields.items():   # styled again: the staff fields were replaced above
            if isinstance(f.widget, forms.Select):
                f.widget.attrs['class'] = 'form-select'
        self.fields['procedure_type'].widget.attrs['data-procedures'] = json.dumps({
            p.pk: {'minutes': p.default_minutes, 'anaesthesia': p.default_anaesthesia, 'specialty': p.specialty, 'side': p.needs_side}
            for p in self.fields['procedure_type'].queryset})

    def clean(self):
        d = super().clean()
        pt = d.get('procedure_type')
        if not pt and not (d.get('procedure') or '').strip():
            self.add_error('procedure_type', 'Choose a procedure, or type its name below.')
        if pt and pt.needs_side and not d.get('side'):
            self.add_error('side', f'{pt.name}: state the side.')
        if bool(d.get('room')) != bool(d.get('scheduled_start')):
            self.add_error('scheduled_start' if d.get('room') else 'room', 'Give both a theatre and a start time, or neither.')
        if not d.get('est_minutes'):
            d['est_minutes'] = pt.default_minutes if pt else 60
        return d


def _parse_day(v):
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        return timezone.localdate()


@login_required
def board(request):
    authorize(request, 'theatre_view')
    day = _parse_day(request.GET.get('date'))
    from datetime import timedelta
    legend = [(k, l) for k, l in SurgicalCase.STATUS if k in ('scheduled', 'ready', 'in_theatre', 'operating', 'recovery', 'completed')]
    from .access import has
    return render(request, 'hospital/theatre/board.html', {'day': day, 'prev': day - timedelta(days=1), 'next': day + timedelta(days=1), 'legend': legend,
                                                           'boot': T.board(day), 'can_book': has(request.user, 'theatre')})


@login_required
def api_board(request):
    authorize(request, 'theatre_view')
    return JsonResponse(T.board(_parse_day(request.GET.get('date'))))


def _save_booking(form, user, case=None):
    """Save a new or edited booking. A theatre and start time means it is scheduled (after the clash check)."""
    c = form.save(commit=False)
    if case is None:
        c.requested_by = user
        c.status = 'requested'
    c.save()
    if c.room_id and c.scheduled_start and c.status in ('requested', 'postponed'):
        T.advance(c, 'scheduled', user)
    elif c.status in ('scheduled', 'ready'):
        if not (c.room_id and c.scheduled_start):
            raise ValidationError('A scheduled case needs a theatre and a start time. Use “Back to waiting list” to unschedule it.')
        found = T.clashes(c, c.room, c.scheduled_start, c.est_minutes)
        if found:
            raise ValidationError(found)
    return c


@login_required
def case_new(request):
    authorize(request, 'theatre')
    initial = {k: v for k, v in request.GET.items()}
    if initial.get('procedure_type'):
        pt = ProcedureType.objects.filter(pk=initial['procedure_type']).first()
        if pt:
            initial.setdefault('est_minutes', pt.default_minutes); initial.setdefault('anaesthesia', pt.default_anaesthesia)
            initial.setdefault('specialty', pt.specialty)
    form = SurgicalCaseForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                c = _save_booking(form, request.user)
            audit(request, 'theatre_book', f'surgical_case:{c.pk}', {'status': c.status, 'room': c.room_id})
            return finish(request, reverse('theatre_case', args=[c.pk]), f'{c.number} booked.')
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, 'hospital/theatre/form.html', {'form': form, 'title': 'Book an operation or procedure',
                                                          'subtitle': 'Put it on the theatre schedule, or on the waiting list without a time.'})


@login_required
def case_edit(request, pk):
    authorize(request, 'theatre')
    c = get_object_or_404(SurgicalCase.objects.select_related('encounter__patient'), pk=pk)
    if c.status not in ('requested', 'scheduled', 'ready', 'postponed'):
        raise PermissionDenied('The booking can no longer be changed once the patient is in theatre.')
    form = SurgicalCaseForm(request.POST or None, instance=c)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                c = _save_booking(form, request.user, case=c)
            audit(request, 'theatre_edit', f'surgical_case:{c.pk}', {'room': c.room_id, 'start': c.scheduled_start.isoformat() if c.scheduled_start else None})
            return finish(request, reverse('theatre_case', args=[c.pk]), f'{c.number} updated.')
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, 'hospital/theatre/form.html', {'form': form, 'title': f'Change booking · {c.number}', 'subtitle': c.title})


def _local(dt):
    return timezone.localtime(dt).strftime('%Y-%m-%dT%H:%M') if dt else ''


def case_state(c, user):
    p = c.patient
    name = lambda u: (u.get_full_name() or u.username) if u else ''
    return {
        'id': c.pk, 'number': c.number, 'title': c.title, 'status': c.status, 'status_label': c.get_status_display(),
        'urgency': c.urgency, 'urgency_label': c.get_urgency_display(), 'side': c.side, 'site': c.site, 'indication': c.indication,
        'specialty': c.get_specialty_display(), 'anaesthesia': c.get_anaesthesia_display(), 'asa': c.asa, 'blood_units': c.blood_units,
        'patient': {'name': p.full_name, 'mrn': p.mrn, 'age': p.age, 'sex': p.sex, 'initials': p.initials, 'url': reverse('patient_chart', args=[p.pk])},
        'room': str(c.room) if c.room_id else '', 'start': T._iso(c.scheduled_start), 'minutes': c.est_minutes,
        'team': {'surgeon': name(c.surgeon), 'assistant': name(c.assistant), 'anaesthetist': name(c.anaesthetist), 'scrub': name(c.scrub_nurse)},
        'readiness': T.readiness(c), 'fasting_since': _local(c.fasting_since), 'clear_fluids_since': _local(c.clear_fluids_since),
        'checklist': c.checklist or {}, 'phase_done': {ph: T.phase_done(c, ph) for ph in T.CHECKLIST},
        'times': {k: T._iso(getattr(c, k)) for k in ('in_room_at', 'anaesthesia_at', 'incision_at', 'closure_at', 'out_room_at', 'recovery_out_at')},
        'note': {'procedure_performed': c.procedure_performed, 'by': name(c.note_by), 'at': T._iso(c.note_at)},
        'recovery': c.recovery or [], 'baseline_sbp': T.baseline_sbp(c),
        'discharge_to': c.get_discharge_to_display() if c.discharge_to else '', 'discharge_override': c.discharge_override,
        'cancel_reason': c.cancel_reason, 'next': sorted(T.TRANSITIONS.get(c.status, set())),
        'can': {'act': __import__('hospital.access', fromlist=['has']).has(user, 'theatre'), 'note': can_note(user), 'edit': __import__('hospital.access', fromlist=['has']).has(user, 'theatre') and c.status in ('requested', 'scheduled', 'ready', 'postponed')},
        'now': T._iso(timezone.now()),
    }


@login_required
def case_detail(request, pk):
    authorize(request, 'theatre_view')
    c = get_object_or_404(SurgicalCase.objects.select_related('encounter__patient', 'room', 'surgeon', 'assistant', 'anaesthetist', 'scrub_nurse', 'procedure_type'), pk=pk)
    audit(request, 'view_chart', f'surgical_case:{c.pk}')
    return render(request, 'hospital/theatre/case.html', {
        'c': c, 'p': c.patient, 'e': c.encounter, 'boot': {'state': case_state(c, request.user), 'catalogue': T.catalogue(),
                                                           'discharge_to': [x for x in SurgicalCase.DISCHARGE_TO if x[0]],
                                                           'urls': {'action': reverse('theatre_action', args=[c.pk]), 'preop': reverse('theatre_preop', args=[c.pk]),
                                                                    'checklist': f'/theatre/cases/{c.pk}/checklist/', 'recovery': reverse('theatre_recovery', args=[c.pk])}},
        'can_note': can_note(request.user) and c.status in ('operating', 'recovery', 'completed'),
        'wounds': SurgicalCase.WOUND, 'bill_url': reverse('invoice_for_encounter', args=[c.encounter_id]),
        'drflow': __import__('hospital.access', fromlist=['has']).has(request.user, 'drflow'),
    })


def _json(request):
    try:
        d = json.loads(request.body.decode('utf-8') or '{}')
    except (ValueError, UnicodeDecodeError):
        return None
    return d if isinstance(d, dict) else None


def _answer(fn):
    """Run a JSON action on a locked case; answer with the fresh state or the rule that stopped it."""
    @login_required
    @require_POST
    def view(request, pk, **kw):
        authorize(request, 'theatre')
        data = _json(request)
        if data is None:
            return JsonResponse({'ok': False, 'error': 'The data sent was not valid JSON.'}, status=400)
        try:
            with transaction.atomic():
                c = get_object_or_404(SurgicalCase.objects.select_for_update().select_related('encounter__patient'), pk=pk)
                detail = fn(request, c, data, **kw)
        except ValidationError as exc:
            return JsonResponse({'ok': False, 'error': ' '.join(exc.messages)}, status=400)
        c = SurgicalCase.objects.select_related('encounter__patient', 'room', 'surgeon', 'assistant', 'anaesthetist', 'scrub_nurse').get(pk=pk)
        return JsonResponse({'ok': True, 'detail': detail or {}, 'state': case_state(c, request.user)})
    return view


@_answer
def case_action(request, c, data):
    to = str(data.get('to', ''))
    before = c.status
    T.advance(c, to, request.user, reason=data.get('reason', ''), discharge_to=data.get('discharge_to', ''), override=data.get('override', ''))
    audit(request, 'theatre_status', f'surgical_case:{c.pk}', {'from': before, 'to': to, 'reason': c.cancel_reason if to in ('cancelled', 'postponed') else ''})


def _dt(v):
    v = str(v or '').strip()[:16]
    if not v:
        return None
    try:
        return timezone.make_aware(datetime.strptime(v, '%Y-%m-%dT%H:%M'))
    except ValueError:
        raise ValidationError('Enter the time as date and hour.')


@_answer
def case_preop(request, c, data):
    if c.status not in ('requested', 'scheduled', 'ready', 'postponed'):
        raise ValidationError('Pre-op checks are closed once the patient is in theatre.')
    c.preop = T.clean_preop(data.get('preop'), c)
    c.fasting_since, c.clear_fluids_since = _dt(data.get('fasting_since')), _dt(data.get('clear_fluids_since'))
    if c.fasting_since and c.fasting_since > timezone.now():
        raise ValidationError('The last meal cannot be in the future.')
    if c.status == 'ready' and not T.readiness(c)['complete']:
        c.status = 'scheduled'          # a check was taken back: no longer ready
    c.save()
    audit(request, 'theatre_preop', f'surgical_case:{c.pk}', {'done': sorted(k for k, v in c.preop.items() if v)})


@_answer
def case_checklist(request, c, data, phase=''):
    T.save_phase(c, phase, data.get('items'), request.user, extra=data)
    c.save(update_fields=['checklist', 'updated_at'])
    audit(request, 'who_checklist', f'surgical_case:{c.pk}', {'phase': phase})


@_answer
def case_recovery(request, c, data):
    if c.status != 'recovery':
        raise ValidationError('Recovery observations are recorded while the patient is in recovery.')
    obs = T.clean_recovery_obs(data, T.baseline_sbp(c))
    obs['by'] = request.user.get_full_name() or request.user.username
    c.recovery = (c.recovery or []) + [obs]
    c.recovery = c.recovery[-60:]
    c.save(update_fields=['recovery', 'updated_at'])
    audit(request, 'recovery_obs', f'surgical_case:{c.pk}', {'aldrete': obs['aldrete']})
    return {'alerts': obs['alerts']}


@login_required
@require_POST
def case_note(request, pk):
    if not can_note(request.user):
        raise PermissionDenied('Your access does not include writing operation notes.')
    c = get_object_or_404(SurgicalCase, pk=pk)
    if c.status not in ('operating', 'recovery', 'completed'):
        raise PermissionDenied('The operation note is written once the operation has started.')
    P = request.POST
    c.procedure_performed = P.get('procedure_performed', '').strip()[:300]
    for f, n in (('findings', 4000), ('complications', 2000), ('post_op_plan', 3000)):
        setattr(c, f, P.get(f, '').strip()[:n])
    for f, n in (('specimens', 300), ('implants', 300), ('drains', 200), ('closure', 200)):
        setattr(c, f, P.get(f, '').strip()[:n])
    c.wound_class = P.get('wound_class') if P.get('wound_class') in dict(SurgicalCase.WOUND) else ''
    try:
        c.blood_loss_ml = max(0, min(20000, int(P.get('blood_loss_ml') or 0))) if P.get('blood_loss_ml', '').strip() else None
    except ValueError:
        c.blood_loss_ml = None
    amended = bool(c.note_at)
    c.note_by, c.note_at = request.user, timezone.now()
    c.save()
    audit(request, 'operation_note_amend' if amended else 'operation_note', f'surgical_case:{c.pk}', {})
    return redirect(reverse('theatre_case', args=[c.pk]) + '#note')
