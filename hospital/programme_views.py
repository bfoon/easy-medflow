"""Care programmes: the list, a programme's dashboard (today, missed and tracing, patients, plan, team, insights,
outbox), enrolment pages, recording visits, tracing, reminders and the optional de-identified AI. See programmes.py."""
from datetime import date, timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.forms import inlineformset_factory
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import programmes as P
from .forms import StyledModelForm
from .models import Patient
from .models_programmes import (Enrolment, Programme, ProgrammeAIRun, ProgrammeMember, ProgrammeMessage, ProgrammeStep, ProgrammeVisit,
                                TracingAttempt)
from .views import audit, authorize, finish

U = get_user_model()


def staff_qs(roles=('doctor', 'nurse', 'admin', 'pharmacy', 'management')):
    return U.objects.filter(Q(hospital_staff__role__in=roles, hospital_staff__active=True) | Q(is_superuser=True)).order_by('first_name', 'username').distinct()


class StaffChoice(forms.ModelChoiceField):
    def label_from_instance(self, u):
        role = getattr(getattr(u, 'hospital_staff', None), 'role', '')
        return f"{u.get_full_name() or u.username}{f' · {role}' if role else ''}"


class StaffMulti(forms.ModelMultipleChoiceField):
    def label_from_instance(self, u):
        return u.get_full_name() or u.username


def _programme(request, pk, manage=False):
    if not P.can_manage(request.user):
        authorize(request, 'programmes')
    p = get_object_or_404(Programme, pk=pk)
    if manage and not P.can_manage(request.user, p):
        raise PermissionDenied('Only the programme lead or a programme administrator can change this programme.')
    if not (P.can_manage(request.user, p) or P.is_member(request.user, p)):
        raise PermissionDenied('You are not part of the care team of this programme.')
    return p


def _enrolment(request, pk):
    e = get_object_or_404(Enrolment.objects.select_related('programme', 'patient', 'clinician', 'nurse'), pk=pk)
    _programme(request, e.programme_id)
    return e


def _guard(request):
    if not (request.user.is_superuser or P.can_manage(request.user)):
        authorize(request, 'programmes')


# ------------------------------------------------------------------ list
@login_required
def index(request):
    _guard(request)
    P.ensure_swept()
    progs = list(P.visible_programmes(request.user).select_related('lead'))
    team = dict(ProgrammeMember.objects.filter(programme__in=progs).values('programme').annotate(n=Count('pk')).values_list('programme', 'n'))
    for p in progs:
        p.n_team = team.get(p.pk, 0)
    cards = [{'p': p, 's': P.stats(p)} for p in progs]
    mine = (ProgrammeVisit.objects.filter(status='missed', enrolment__status__in=['active', 'lost'])
            .filter(Q(enrolment__clinician=request.user) | Q(enrolment__nurse=request.user)).count())
    return render(request, 'hospital/programmes/index.html', {'cards': cards, 'templates': P.TEMPLATES, 'can_create': P.can_manage(request.user), 'mine_missed': mine,
                                                              'outbox': ProgrammeMessage.objects.filter(enrolment__programme__in=progs, status__in=['pending', 'failed']).count()})


@login_required
@require_POST
def create(request):
    if not P.can_manage(request.user):
        raise PermissionDenied('Only programme administrators can create programmes.')
    key = request.POST.get('template', 'blank')
    name = (request.POST.get('name') or '').strip()
    if key in P.TEMPLATES:
        p = P.create_from_template(key, request.user, **({'name': name} if name else {}))
    else:
        p = Programme.objects.create(name=name or 'New programme', created_by=request.user, lead=request.user)
        ProgrammeMember.objects.create(programme=p, user=request.user, role='lead')
    audit(request, 'programme_create', f'programme:{p.pk}', {'template': key})
    return redirect(reverse('programme_edit', args=[p.pk]) + '?new=1')


# ------------------------------------------------------------------ edit: settings, team, plan
class ProgrammeForm(StyledModelForm):
    lead = StaffChoice(queryset=None, required=False)
    doctors = StaffMulti(queryset=None, required=False, label='Doctors in the team', widget=forms.SelectMultiple(attrs={'size': 6}))
    nurses = StaffMulti(queryset=None, required=False, label='Nurses / midwives in the team', widget=forms.SelectMultiple(attrs={'size': 6}))
    others = StaffMulti(queryset=None, required=False, label='Other team members (pharmacy, data, management)', widget=forms.SelectMultiple(attrs={'size': 4}))
    measures = forms.MultipleChoiceField(choices=[(k, f'{v[0]}{f" ({v[1]})" if v[1] else ""}') for k, v in P.MEASURES.items()], required=False,
                                         widget=forms.CheckboxSelectMultiple, label='Recorded at each visit')

    class Meta:
        model = Programme
        fields = ['name', 'kind', 'description', 'color', 'icon', 'active', 'lead', 'anchor', 'measures', 'reminder_days', 'grace_days', 'escalate_days',
                  'ltfu_days', 'discreet', 'reminder_text', 'missed_text', 'ai_enabled']
        widgets = {'description': forms.Textarea(attrs={'rows': 2}), 'color': forms.TextInput(attrs={'type': 'color'})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields['lead'].queryset = staff_qs()
        self.fields['doctors'].queryset = staff_qs(('doctor',))
        self.fields['nurses'].queryset = staff_qs(('nurse',))
        self.fields['others'].queryset = staff_qs(('pharmacy', 'management', 'admin', 'reception', 'lab'))
        if self.instance.pk:
            mem = list(self.instance.members.select_related('user__hospital_staff'))
            role_of = lambda m: getattr(getattr(m.user, 'hospital_staff', None), 'role', '')
            self.initial['doctors'] = [m.user_id for m in mem if role_of(m) == 'doctor']
            self.initial['nurses'] = [m.user_id for m in mem if role_of(m) == 'nurse']
            self.initial['others'] = [m.user_id for m in mem if role_of(m) not in ('doctor', 'nurse')]
        from .medical_ai import enabled
        if not enabled():
            self.fields['ai_enabled'].help_text += '. AI is not connected on this server yet, so this has no effect until an administrator configures it.'
        self.fields['measures'].widget.attrs.pop('class', None)


StepFormSet = inlineformset_factory(Programme, ProgrammeStep, extra=2, can_delete=True,
                                    fields=['order', 'name', 'kind', 'offset_days', 'repeat_days', 'until_days', 'items', 'medicine', 'days_supply'],
                                    widgets={'items': forms.TextInput(attrs={'placeholder': 'BCG, OPV 0'})})


def _sync_team(p, form):
    wanted = {}
    for key, role in (('doctors', 'doctor'), ('nurses', 'nurse'), ('others', 'data')):
        for u in form.cleaned_data.get(key) or []:
            wanted.setdefault(u.pk, role)
    if p.lead_id:
        wanted[p.lead_id] = 'lead'
    for m in p.members.all():
        if m.user_id not in wanted:
            m.delete()
    have = {m.user_id: m for m in p.members.all()}
    for uid, role in wanted.items():
        if uid in have:
            m = have[uid]
            if role == 'lead' and m.role != 'lead':
                m.role = 'lead'; m.save(update_fields=['role', 'updated_at'])
        else:
            ProgrammeMember.objects.create(programme=p, user_id=uid, role=role)


@login_required
def edit(request, pk):
    p = _programme(request, pk, manage=True)
    form = ProgrammeForm(request.POST or None, instance=p)
    steps = StepFormSet(request.POST or None, instance=p, prefix='steps')
    for f in steps.forms:                      # items are typed as "BCG, OPV 0" and stored as a list
        if not request.POST and f.instance.pk:
            f.initial['items'] = ', '.join(f.instance.items or [])
    if request.method == 'POST':
        for f in steps.forms:
            raw = f.data.get(f.add_prefix('items'), '')
            if isinstance(raw, str) and not raw.strip().startswith('['):
                f.data = f.data.copy(); f.data[f.add_prefix('items')] = __import__('json').dumps([x.strip() for x in raw.split(',') if x.strip()])
        if form.is_valid() and steps.is_valid():
            with transaction.atomic():
                p = form.save()
                _sync_team(p, form)
                steps.save()
            audit(request, 'programme_edit', f'programme:{p.pk}', {'ai': p.ai_enabled, 'steps': p.steps.count(), 'team': p.members.count()})
            return finish(request, reverse('programme_detail', args=[p.pk]), f'{p.name} saved.')
    return render(request, 'hospital/programmes/edit.html', {'p': p, 'form': form, 'steps': steps, 'new': request.GET.get('new')})


# ------------------------------------------------------------------ the programme dashboard
TABS = [('today', 'Today & this week', 'calendar-check'), ('missed', 'Missed & tracing', 'telephone-outbound'), ('patients', 'Patients', 'people'),
        ('plan', 'Visit plan', 'diagram-3'), ('team', 'Care team', 'person-badge'), ('insights', 'Insights', 'lightbulb'), ('outbox', 'Reminders', 'chat-dots')]


@login_required
def detail(request, pk):
    p = _programme(request, pk)
    P.ensure_swept()
    tab = request.GET.get('tab') or 'today'
    today = timezone.localdate()
    ctx = {'p': p, 'tab': tab, 'tabs': TABS, 's': P.stats(p), 'today': today, 'can_manage': P.can_manage(request.user, p),
           'ai_on': P.ai_allowed(p), 'ai_switch': p.ai_enabled, 'sms_gateway': bool(getattr(__import__('django.conf', fromlist=['settings']).settings, 'PROGRAMME_SMS_URL', '')), 'measures': [(k, P.MEASURES[k]) for k in (p.measures or []) if k in P.MEASURES]}
    vq = ProgrammeVisit.objects.filter(enrolment__programme=p).select_related('enrolment__patient', 'enrolment__clinician', 'enrolment__nurse')
    if tab == 'today':
        ctx['due_today'] = vq.filter(due__lte=today, status__in=['scheduled', 'reminded'], enrolment__status='active').order_by('due')
        ctx['due_week'] = vq.filter(due__gt=today, due__lte=today + timedelta(days=7), status__in=['scheduled', 'reminded'], enrolment__status='active')
        ctx['attended_today'] = vq.filter(attended_on=today, status='attended')
    elif tab == 'missed':
        rows = []
        for v in vq.filter(status='missed', enrolment__status__in=['active', 'lost']).prefetch_related('enrolment__tracing').order_by('due'):
            last = [t for t in v.enrolment.tracing.all() if t.visit_id == v.pk][:1]       # tracing for this miss, not an older one
            rows.append({'v': v, 'late': (today - v.due).days, 'last': last[0] if last else None, 'risk': P.risk(v.enrolment)})
        ctx['rows'] = rows
        ctx['methods'], ctx['outcomes'], ctx['reasons'] = TracingAttempt.METHOD, TracingAttempt.OUTCOME, P.MISS_REASONS
    elif tab == 'patients':
        st = request.GET.get('status') or 'open'
        qs = p.enrolments.select_related('patient', 'clinician', 'nurse').prefetch_related('visits', 'tracing')
        qs = qs.filter(status__in=['active', 'paused', 'lost']) if st == 'open' else qs.filter(status=st) if st != 'all' else qs
        q = (request.GET.get('q') or '').strip()
        if q:
            qs = qs.filter(Q(patient__first_name__icontains=q) | Q(patient__last_name__icontains=q) | Q(patient__mrn__icontains=q))
        rows = []
        for e in qs[:400]:
            vs = list(e.visits.all())
            nxt = min((v for v in vs if v.status in P.OPEN), key=lambda v: v.due, default=None)
            rows.append({'e': e, 'next': nxt, 'risk': P.risk(e, vs, list(e.tracing.all()))})
        order = {'high': 0, 'medium': 1, 'low': 2}
        rows.sort(key=lambda r: (order[r['risk'][0]], r['next'].due if r['next'] else date.max))
        ctx.update(rows=rows, st=st, q=q, statuses=Enrolment.STATUS)
    elif tab == 'team':
        docs = {r['clinician']: r['n'] for r in p.enrolments.filter(status__in=['active', 'lost']).values('clinician').annotate(n=Count('pk'))}
        nurses = {r['nurse']: r['n'] for r in p.enrolments.filter(status__in=['active', 'lost']).values('nurse').annotate(n=Count('pk'))}
        members = list(p.members.select_related('user__hospital_staff'))
        for m in members:
            m.n_doc, m.n_nurse = docs.get(m.user_id, 0), nurses.get(m.user_id, 0)
        ctx['members'] = members
        ctx['roles'] = ProgrammeMember.ROLE
        ctx['addable'] = staff_qs().exclude(pk__in=p.members.values('user_id'))
    elif tab == 'insights':
        ctx['patterns'] = P.patterns(p)
        feed = ai_feed_data(p, request.user)
        ctx['feed'], ctx['summary'] = feed, feed['summary']
        ctx['last_day'] = P.last_visit_day(p, today)
        ctx['summary_hour'] = P.SUMMARY_HOUR
        ctx['qa_suggestions'] = QA_SUGGESTIONS.get(p.kind, QA_SUGGESTIONS['other'])
    elif tab == 'outbox':
        ctx['reminders'] = [{'m': m, 'links': P.send_links(m)} for m in
                           ProgrammeMessage.objects.filter(enrolment__programme=p).select_related('enrolment__patient', 'visit').order_by('status', '-created_at')[:150]]
    return render(request, 'hospital/programmes/detail.html', ctx)


@login_required
@require_POST
def team_act(request, pk):
    p = _programme(request, pk, manage=True)
    act = request.POST.get('act')
    if act == 'add':
        u = get_object_or_404(staff_qs(), pk=request.POST.get('user'))
        ProgrammeMember.objects.get_or_create(programme=p, user=u, defaults={'role': request.POST.get('role') or 'nurse'})
    elif act in ('role', 'notify', 'remove'):
        m = get_object_or_404(ProgrammeMember, pk=request.POST.get('member'), programme=p)
        if act == 'role' and request.POST.get('role') in dict(ProgrammeMember.ROLE):
            m.role = request.POST['role']; m.save(update_fields=['role', 'updated_at'])
        elif act == 'notify':
            m.notify = not m.notify; m.save(update_fields=['notify', 'updated_at'])
        elif act == 'remove':
            m.delete()
    audit(request, 'programme_team', f'programme:{p.pk}', {'act': act})
    return redirect(reverse('programme_detail', args=[p.pk]) + '?tab=team')


# ------------------------------------------------------------------ enrolling patients
class EnrolForm(StyledModelForm):
    clinician = StaffChoice(queryset=None, required=False, label='Responsible doctor')
    nurse = StaffChoice(queryset=None, required=False, label='Responsible nurse')

    class Meta:
        model = Enrolment
        fields = ['enrolled_on', 'anchor_date', 'clinician', 'nurse', 'channel', 'consent_reminders', 'contact_phone', 'notes']
        widgets = {'enrolled_on': forms.DateInput(attrs={'type': 'date'}), 'anchor_date': forms.DateInput(attrs={'type': 'date'}),
                   'notes': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, programme, *a, **kw):
        super().__init__(*a, **kw)
        team = programme.members.values('user_id')
        self.fields['clinician'].queryset = staff_qs(('doctor', 'admin')).filter(Q(pk__in=team) | Q(hospital_staff__role='doctor'))
        self.fields['nurse'].queryset = staff_qs(('nurse',))
        label = dict(Programme.ANCHOR).get(programme.anchor)
        if programme.anchor == 'enrolment':
            self.fields.pop('anchor_date')
        else:
            self.fields['anchor_date'].label = label
            self.fields['anchor_date'].help_text = 'The visit plan is counted from this day' + (' (filled from the date of birth if left blank)' if programme.anchor == 'dob' else '')
            self.fields['anchor_date'].required = programme.anchor == 'lmp'


@login_required
def enrol(request, pk):
    p = _programme(request, pk)
    patient = Patient.objects.filter(pk=request.POST.get('patient') or request.GET.get('patient')).first()
    form = EnrolForm(p, request.POST or None, initial={'clinician': request.user if getattr(getattr(request.user, 'hospital_staff', None), 'role', '') == 'doctor' else None,
                                                       'nurse': request.user if getattr(getattr(request.user, 'hospital_staff', None), 'role', '') == 'nurse' else None})
    error = ''
    if request.method == 'POST':
        if not patient:
            error = 'Choose the patient to enrol.'
        elif form.is_valid():
            data = form.cleaned_data
            if p.anchor == 'dob' and not data.get('anchor_date'):
                data['anchor_date'] = patient.dob
            try:
                e = P.enrol(p, patient, request.user, **data)
                audit(request, 'programme_enrol', f'enrolment:{e.pk}', {'programme': p.pk, 'patient': patient.pk})
                return finish(request, reverse('programme_enrolment', args=[e.pk]), f'{patient.full_name} enrolled in {p.name}.')
            except IntegrityError:
                error = f'{patient.full_name} is already enrolled in {p.name}.'
    return render(request, 'hospital/programmes/enrol.html', {'p': p, 'form': form, 'patient': patient, 'error': error,
                                                              'search_url': reverse('programme_patient_search', args=[p.pk])})


@login_required
@require_GET
def patient_search(request, pk):
    p = _programme(request, pk)
    q = (request.GET.get('q') or '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    from .phones import is_phone_query, phone_q
    cond = Q(mrn__icontains=q)
    for w in q.split():
        cond |= Q(first_name__icontains=w) | Q(last_name__icontains=w)
    if is_phone_query(q):
        cond |= phone_q(q)
    enrolled = set(p.enrolments.filter(status__in=['active', 'paused', 'lost']).values_list('patient_id', flat=True))
    out = [{'id': x.pk, 'name': x.full_name, 'mrn': x.mrn, 'age': x.age, 'sex': x.get_sex_display(), 'enrolled': x.pk in enrolled}
           for x in Patient.objects.filter(cond, deceased_at__isnull=True).order_by('first_name')[:12]]
    return JsonResponse({'results': out})


@login_required
def eligible(request, pk):
    p = _programme(request, pk)
    if request.method == 'POST':
        ids = [int(x) for x in request.POST.getlist('patient') if x.isdigit()]
        n = 0
        for pat in Patient.objects.filter(pk__in=ids):
            try:
                P.enrol(p, pat, request.user, anchor_date=pat.dob if p.anchor == 'dob' else None,
                        clinician=request.user if getattr(getattr(request.user, 'hospital_staff', None), 'role', '') == 'doctor' else None)
                n += 1
            except IntegrityError:
                pass
        audit(request, 'programme_enrol_bulk', f'programme:{p.pk}', {'count': n})
        return finish(request, reverse('programme_detail', args=[p.pk]) + '?tab=patients', f'{n} patient{"s" if n != 1 else ""} enrolled.')
    return render(request, 'hospital/programmes/eligible.html', {'p': p, 'rows': P.eligible(p)})


# ------------------------------------------------------------------ one enrolment
@login_required
def enrolment(request, pk):
    e = _enrolment(request, pk)
    visits = list(e.visits.select_related('recorded_by', 'step').order_by('due'))
    tracing = list(e.tracing.select_related('by', 'visit'))
    level, score, why = P.risk(e, visits, tracing)
    bp = [(v.attended_on or v.due, P._bp(v.measures.get('bp'))) for v in visits if v.status == 'attended' and P._bp(v.measures.get('bp'))]
    series = {}
    for k in ('weight', 'viral_load', 'hba1c', 'glucose', 'muac', 'adherence', 'phq9', 'hb'):
        pts = [(v.attended_on or v.due, P._num(v.measures.get(k))) for v in visits if v.status == 'attended' and P._num(v.measures.get(k)) is not None]
        if len(pts) >= 2:
            series[k] = pts
    today = timezone.localdate()
    upcoming = [v for v in visits if v.status in P.OPEN]
    return render(request, 'hospital/programmes/enrolment.html', {
        'e': e, 'p': e.programme, 'pt': e.patient, 'visits': visits, 'tracing': tracing, 'risk': (level, score, why), 'today': today,
        'upcoming': upcoming, 'history': [v for v in visits if v.status not in P.OPEN][::-1], 'bp': bp,
        'series': [(P.MEASURES[k][0], P.MEASURES[k][1], pts) for k, pts in series.items()],
        'latest': [(P.MEASURES[k][0], P.MEASURES[k][1], val, when) for k, (val, when) in P.latest_measures(visits).items() if k in P.MEASURES],
        'reminders': [{'m': m, 'links': P.send_links(m)} for m in e.messages.all()[:10]],
        'statuses': Enrolment.STATUS, 'channels': Enrolment.CHANNEL, 'methods': TracingAttempt.METHOD, 'outcomes': TracingAttempt.OUTCOME, 'reasons': P.MISS_REASONS,
        'ai_on': P.ai_allowed(e.programme), 'ai_switch': e.programme.ai_enabled, 'last_ai': e.ai_runs.first(), 'can_manage': P.can_manage(request.user, e.programme),
        'given_count': sum(len(v.items_done or []) for v in visits), 'planned_count': sum(len(v.items_planned or []) for v in visits if v.status != 'cancelled'),
    })


class VisitForm(forms.Form):
    attended_on = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}), label='Came on')
    days_supply = forms.IntegerField(required=False, min_value=1, max_value=365, label='Days of medicine given',
                                     widget=forms.NumberInput(attrs={'class': 'form-control'}), help_text='The next refill is planned for when it runs out')
    next_due = forms.DateField(required=False, label='Next visit on (optional)', widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
                               help_text='Leave blank to follow the plan')
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}), label='Note (care team only, never sent to AI)')


@login_required
def visit_record(request, pk):
    v = get_object_or_404(ProgrammeVisit.objects.select_related('enrolment__programme', 'enrolment__patient'), pk=pk)
    e = _enrolment(request, v.enrolment_id)
    if v.status in ('attended', 'cancelled'):
        return finish(request, reverse('programme_enrolment', args=[e.pk]), 'This visit is already closed.')
    form = VisitForm(request.POST or None, initial={'attended_on': timezone.localdate(), 'days_supply': v.days_supply})
    measures = [(k, P.MEASURES[k]) for k in (e.programme.measures or []) if k in P.MEASURES]
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        vals = {k: request.POST.get(f'm_{k}', '').strip() for k, _ in measures}
        bad = [P.MEASURES[k][0] for k, x in vals.items() if x and P.MEASURES[k][2] == 'number' and P._num(x) is None]
        bad += [P.MEASURES['bp'][0]] if vals.get('bp') and not P._bp(vals['bp']) else []
        if bad:
            form.add_error(None, 'Please check: ' + ', '.join(bad) + '.')
        else:
            enc = e.patient.encounters.filter(status='open').order_by('-created_at').first()
            res = P.record_visit(v, request.user, d['attended_on'], request.POST.getlist('items'), vals, d.get('days_supply'), d.get('note', ''), enc, d.get('next_due'))
            audit(request, 'programme_visit', f'programme_visit:{v.pk}', {'enrolment': e.pk, 'returned': res['returned']})
            msg = f'Visit recorded for {e.patient.full_name}.' + (' Welcome back: the patient is in care again.' if res['returned'] else '')
            if res['planned']:
                msg += ' Next: ' + ', '.join(f"{x.title} on {x.due.strftime('%d %b')}" for x in res['planned'][:2]) + '.'
            return finish(request, reverse('programme_enrolment', args=[e.pk]), msg)
    last = P.latest_measures(list(e.visits.all()))
    fields = [{'key': k, 'label': m[0], 'unit': m[1], 'kind': m[2], 'placeholder': m[3], 'choices': m[2][7:].split('|') if m[2].startswith('choice:') else None,
               'value': request.POST.get(f'm_{k}', ''), 'last': last.get(k)} for k, m in measures]
    return render(request, 'hospital/programmes/visit.html', {'v': v, 'e': e, 'form': form, 'fields': fields})


@login_required
@require_POST
def visit_act(request, pk):
    v = get_object_or_404(ProgrammeVisit, pk=pk)
    e = _enrolment(request, v.enrolment_id)
    act = request.POST.get('act')
    if act == 'reschedule':
        try:
            new = date.fromisoformat(request.POST.get('due', ''))
        except ValueError:
            return HttpResponseBadRequest('A new date is needed')
        P.reschedule(v, new)
        msg = f'Moved to {new.strftime("%d %b")}.'
    elif act == 'cancel':
        v.status = 'cancelled'; v.save(update_fields=['status', 'updated_at'])
        P.plan(e)
        msg = 'Visit cancelled.'
    elif act == 'remind':
        m = P.queue_message(v, 'reminder') or v.messages.filter(kind='reminder').first()
        msg = 'Reminder ready in the outbox.' if m and m.status == 'pending' else 'Reminder sent.' if m and m.status == 'sent' else 'The patient has not agreed to reminders.'
    else:
        return HttpResponseBadRequest('Unknown action')
    audit(request, 'programme_visit_' + act, f'programme_visit:{v.pk}', {})
    return finish(request, request.POST.get('next') or reverse('programme_enrolment', args=[e.pk]), msg)


@login_required
@require_POST
def trace(request, pk):
    e = _enrolment(request, pk)
    outcome = request.POST.get('outcome')
    if outcome not in dict(TracingAttempt.OUTCOME):
        return HttpResponseBadRequest('Choose what happened')
    v = e.visits.filter(pk=request.POST.get('visit')).first() or e.visits.filter(status='missed').order_by('due').first()
    t = TracingAttempt.objects.create(enrolment=e, visit=v, method=request.POST.get('method') or 'call', outcome=outcome,
                                      reason=request.POST.get('reason', '') if request.POST.get('reason', '') in P.MISS_REASON_LABEL else '',
                                      note=(request.POST.get('note') or '')[:300], by=request.user)
    msg = 'Tracing recorded.'
    if outcome == 'rescheduled' and v and request.POST.get('due'):
        try:
            P.reschedule(v, date.fromisoformat(request.POST['due']))
            msg = f'New date agreed: {v.due.strftime("%d %b")}.'
        except ValueError:
            pass
    elif outcome == 'died':
        P.set_status(e, 'died')
        msg = 'Recorded. The enrolment is closed and planned visits are cancelled.'
    audit(request, 'programme_trace', f'enrolment:{e.pk}', {'outcome': outcome, 'tracing': t.pk})
    return finish(request, request.POST.get('next') or reverse('programme_enrolment', args=[e.pk]), msg)


@login_required
@require_POST
def enrolment_status(request, pk):
    e = _enrolment(request, pk)
    st = request.POST.get('status')
    if st not in dict(Enrolment.STATUS):
        return HttpResponseBadRequest('Unknown status')
    if st in ('active', 'paused', 'lost') and Enrolment.objects.filter(programme=e.programme, patient=e.patient, status__in=['active', 'paused', 'lost']).exclude(pk=e.pk).exists():
        return HttpResponseBadRequest('The patient already has an open enrolment in this programme')
    P.set_status(e, st)
    audit(request, 'programme_status', f'enrolment:{e.pk}', {'status': st})
    return finish(request, reverse('programme_enrolment', args=[e.pk]), f'Status: {e.get_status_display()}.')


@login_required
@require_POST
def enrolment_team(request, pk):
    e = _enrolment(request, pk)
    for f in ('clinician', 'nurse'):
        if f in request.POST:
            setattr(e, f, staff_qs().filter(pk=request.POST.get(f)).first())
    if request.POST.get('channel') in dict(Enrolment.CHANNEL):
        e.channel = request.POST['channel']
    e.save()
    audit(request, 'programme_assign', f'enrolment:{e.pk}', {'clinician': e.clinician_id, 'nurse': e.nurse_id})
    return finish(request, reverse('programme_enrolment', args=[e.pk]), 'Care team updated.')


# ------------------------------------------------------------------ reminders outbox
@login_required
@require_POST
def message_act(request, pk):
    m = get_object_or_404(ProgrammeMessage.objects.select_related('enrolment'), pk=pk)
    _programme(request, m.enrolment.programme_id)
    act = request.POST.get('act')
    if act == 'sent':
        m.status, m.sent_at, m.sent_by = 'sent', timezone.now(), request.user
    elif act == 'skip':
        m.status = 'skipped'
    elif act == 'retry':
        P.dispatch(m)
    m.save()
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'ok': True, 'status': m.get_status_display()})
    return redirect(request.POST.get('next') or reverse('programme_detail', args=[m.enrolment.programme_id]) + '?tab=outbox')


# ------------------------------------------------------------------ AI (per programme switch, de-identified only)
def _ai_json(r):
    from .templatetags.evidence_tags import simple_md
    if r is None:
        return None
    status = 'running' if r.busy else ('failed' if r.status in ('queued', 'running') else r.status)
    return {'id': r.pk, 'kind': r.kind, 'status': status, 'html': str(simple_md(r.text)) if r.text else '',
            'error': r.error if status in ('failed', 'blocked') else '', 'question': r.question, 'auto': r.auto,
            'covers': r.covers_day.strftime('%a %d %b') if r.covers_day else '',
            'at': timezone.localtime(r.created_at).strftime('%d %b %H:%M'), 'by': (r.requested_by.get_full_name() or r.requested_by.username) if r.requested_by_id else ''}


def _ai_target(request, kind, pk):
    if kind in ('cohort', 'question'):
        return _programme(request, pk), None
    if kind == 'patient':
        e = _enrolment(request, pk)
        return e.programme, e
    raise PermissionDenied('Unknown kind')


def _ai_visible(request, r):
    """Summaries and follow-up plans: the whole care team. A question: only the person who asked it."""
    _programme(request, r.programme_id)
    if r.kind == 'question' and r.requested_by_id != request.user.pk:
        raise PermissionDenied('Questions are private to the person who asked them.')


QUESTIONS_PER_DAY = 30
QA_SUGGESTIONS = {
    'hiv': ['How can we improve viral suppression?', 'Would multi-month dispensing help our retention?', 'What do the reasons for missed refills suggest?'],
    'hypertension': ['How many patients are controlled, and what would help the rest?', 'Which day of the week should we avoid?', 'What do the reasons for missed visits suggest?'],
    'diabetes': ['How is HbA1c control trending?', 'What would help patients who miss refills?', 'Which checks are most overdue?'],
    'immunisation': ['Which vaccine visit is missed most?', 'How can we reduce drop-out between Penta 1 and Penta 3?', 'What helps carers come on time?'],
    'antenatal': ['Which contact is missed most?', 'How can we get more women to 8 contacts?', 'What do the reasons for missed contacts suggest?'],
    'other': ['What should we focus on this week?', 'What do the reasons for missed visits suggest?', 'How does our retention compare with good practice?'],
}


@login_required
@require_POST
def ai_ask(request, kind, pk):
    from .evidence_views import _dispatch
    from .tasks import programme_ai_task
    p, e = _ai_target(request, kind, pk)
    if not P.ai_allowed(p):
        return JsonResponse({'ok': False, 'error': 'AI is switched off for this programme.'}, status=403)
    q = ''
    if kind == 'question':
        q = ' '.join((request.POST.get('q') or '').split())[:500]
        if len(q) < 3:
            return JsonResponse({'ok': False, 'error': 'Type a question first.'}, status=400)
        try:
            P.check_question(p, q)                    # before anything is saved or sent
        except P.PIIBlocked as exc:
            audit(request, 'programme_ai_blocked', f'programme:{p.pk}', {'kind': kind})   # the question itself is not logged
            return JsonResponse({'ok': False, 'privacy': True, 'error': str(exc).replace('Not sent: the request', 'Not sent: your question')
                                 + ' Ask about the programme without details that could identify a patient.'}, status=400)
        today = ProgrammeAIRun.objects.filter(programme=p, kind='question', requested_by=request.user, created_at__date=timezone.localdate()).count()
        if today >= QUESTIONS_PER_DAY:
            return JsonResponse({'ok': False, 'error': f'You have asked {QUESTIONS_PER_DAY} questions today. Try again tomorrow.'}, status=429)
    else:
        busy = ProgrammeAIRun.objects.filter(programme=p, enrolment=e, kind=kind, status__in=['queued', 'running']).first()
        if busy and busy.busy:
            return JsonResponse({'ok': True, 'run': _ai_json(busy)})
    r = ProgrammeAIRun.objects.create(programme=p, enrolment=e, kind=kind, requested_by=request.user, question=q,
                                      covers_day=P.last_visit_day(p, timezone.localdate()) if kind == 'cohort' else None)
    audit(request, 'programme_ai', f'programme:{p.pk}', {'kind': kind, 'enrolment': e.pk if e else None, 'run': r.pk})
    _dispatch(programme_ai_task, r.pk)
    r.refresh_from_db()
    return JsonResponse({'ok': True, 'run': _ai_json(r)})


@login_required
@require_GET
def ai_status(request, pk):
    r = get_object_or_404(ProgrammeAIRun.objects.select_related('requested_by'), pk=pk)
    _ai_visible(request, r)
    return JsonResponse({'ok': True, 'run': _ai_json(r)})


@login_required
@require_POST
def ai_forget(request, pk):
    """Delete one of your own questions and its answer."""
    r = get_object_or_404(ProgrammeAIRun, pk=pk, kind='question')
    _ai_visible(request, r)
    r.delete()
    return JsonResponse({'ok': True})


def ai_feed_data(p, user):
    runs = ProgrammeAIRun.objects.filter(programme=p).select_related('requested_by')
    summaries = list(runs.filter(kind='cohort').exclude(status='failed')[:15])
    current = next((r for r in summaries if r.status == 'done'), None)
    pending = next((r for r in summaries if r.busy), None)
    return {'summary': _ai_json(current), 'pending': _ai_json(pending) if pending and (not current or pending.created_at > current.created_at) else None,
            'history': [_ai_json(r) for r in summaries if r.status == 'done'][:10],
            'questions': [_ai_json(r) for r in runs.filter(kind='question', requested_by=user)[:20]]}


@login_required
@require_GET
def ai_feed(request, pk):
    p = _programme(request, pk)
    return JsonResponse({'ok': True, 'ai_on': P.ai_allowed(p), **ai_feed_data(p, request.user)})


@login_required
@require_GET
def ai_context(request, kind, pk):
    """Exactly what the AI would receive, and the privacy check's verdict. Nothing is sent here."""
    p, e = _ai_target(request, kind, pk)
    r = ProgrammeAIRun(programme=p, enrolment=e, kind=kind, question=(request.GET.get('q') or '')[:500])
    ctx, patients = P.ai_context(r)
    try:
        P.firewall(ctx, patients)
        verdict = 'Passed: no names, record numbers, phones, emails, addresses, birth dates or real dates found.'
        ok = True
    except P.PIIBlocked as exc:
        verdict, ok = str(exc), False
    return JsonResponse({'ok': ok, 'verdict': verdict, 'ai_on': P.ai_allowed(p), 'context': ctx})


# ------------------------------------------------------------------ the patient chart panel
def chart_panel(user, patient):
    """Programmes on the chart: the patient's enrolments (with the next visit) and where they could be enrolled."""
    from .access import has
    if not (has(user, 'programmes') or P.can_manage(user)):
        return None
    mine = set(P.visible_programmes(user).values_list('pk', flat=True))
    rows = []
    for e in patient.enrolments.select_related('programme').prefetch_related(Prefetch('visits', queryset=ProgrammeVisit.objects.order_by('due'))):
        nxt = next((v for v in e.visits.all() if v.status in P.OPEN), None)
        rows.append({'e': e, 'next': nxt, 'risk': P.risk(e) if e.open else None, 'mine': e.programme_id in mine})
    open_ids = {r['e'].programme_id for r in rows if r['e'].open}
    can_enrol = [x for x in Programme.objects.filter(pk__in=mine, active=True) if x.pk not in open_ids]
    return {'rows': rows, 'can_enrol': can_enrol}
