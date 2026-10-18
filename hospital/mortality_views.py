"""Mortality pages: the mortuary & mortality board, the archive of deceased patients, the death record, the WHO
certificate, autopsy, the M&M review and study cases in the clinical library (see hospital/mortality.py)."""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import mortality as MT
from .access import can_mortality, filter_patients, has, require
from .models import Autopsy, BODY_SYSTEMS, DeathRecord, MortalityReview, Patient, StudyCase
from .views import audit, authorize, role_of


ORGAN_ICONS = {'brain': 'bi-lightbulb', 'thyroid': 'bi-shield', 'lungs': 'bi-wind', 'heart': 'bi-heart-pulse', 'blood': 'bi-droplet',
               'liver': 'bi-hexagon', 'stomach': 'bi-cup-hot', 'pancreas': 'bi-diagram-2', 'kidneys': 'bi-water', 'bladder': 'bi-moisture',
               'reproductive': 'bi-gender-ambiguous', 'bone': 'bi-bricks', 'immune': 'bi-virus'}


def _organs(rows):
    return [{**r, 'icon': ORGAN_ICONS.get(r['key'], 'bi-circle')} for r in rows]


def _need_any(request):
    authorize(request)
    if not can_mortality(request.user):
        raise PermissionDenied('Your access does not include mortality and the mortuary.')


def _errors(request, exc):
    for m in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
        messages.error(request, m)


def _back(death, anchor=''):
    return redirect(reverse('death_detail', args=[death.pk]) + (f'#{anchor}' if anchor else ''))


# ------------------------------------------------------------------ the board
@login_required
def index(request):
    _need_any(request)
    live = DeathRecord.objects.exclude(status='revoked').select_related('patient', 'certified_by', 'encounter')
    board = list(live.filter(body_status__in=['ward', 'mortuary', 'autopsy']).prefetch_related('autopsies').order_by('-rapid_release', 'died_at'))
    for d in board:
        d.open_autopsy = next((a for a in d.autopsies.all() if a.open), None)
    open_autopsies = Autopsy.objects.filter(status__in=MT.OPEN_AUTOPSY).select_related('death__patient', 'pathologist').order_by('created_at')
    return render(request, 'hospital/mortality/index.html', {
        's': MT.stats(), 'alerts': MT.alerts()[:14], 'recent': live.order_by('-died_at')[:15], 'board': board,
        'autopsies': open_autopsies, 'tab': request.GET.get('tab', 'overview'),
        'drafts': StudyCase.objects.filter(status='draft').exclude(death__status='revoked').select_related('death__patient')[:12],
    })


@login_required
def archive(request):
    """Deceased patients: removed from the active lists, their records kept in full."""
    authorize(request)
    if not (can_mortality(request.user) or has(request.user, 'all_patients')):
        raise PermissionDenied('Your access does not include the archive of deceased patients.')
    q = request.GET.get('q', '').strip()[:100]
    year = request.GET.get('year', '')
    qs = Patient.objects.filter(deceased_at__isnull=False).order_by('-deceased_at')
    if q:
        qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(mrn__icontains=q))
    if year.isdigit():
        qs = qs.filter(deceased_at__year=int(year))
    total = qs.count()
    deaths = {d.patient_id: d for d in DeathRecord.objects.exclude(status='revoked').filter(patient__in=qs[:200]).select_related('study_case')}
    rows = []
    openable = filter_patients(request, Patient.objects.filter(pk__in=[p.pk for p in qs[:200]])).values_list('pk', flat=True)
    openable = set(openable)
    for p in qs[:200]:
        rows.append({'p': p, 'd': deaths.get(p.pk), 'open': p.pk in openable})
    years = sorted({d.year for d in Patient.objects.filter(deceased_at__isnull=False).dates('deceased_at', 'year')}, reverse=True)
    audit(request, 'archive_list', 'patients:deceased', {'q': q[:40]})
    return render(request, 'hospital/mortality/archive.html', {'rows': rows, 'q': q, 'total': total, 'years': years, 'year': year})


# ------------------------------------------------------------------ recording a death
@login_required
def death_new(request, pk):
    authorize(request)
    require(request, 'mortality', 'Your access does not include recording a death.')
    p = get_object_or_404(Patient, pk=pk)
    existing = p.death_record
    if existing:
        return redirect('death_detail', pk=existing.pk)
    if request.method == 'POST':
        if request.POST.get('confirm_name', '').strip().lower() != p.last_name.strip().lower():
            messages.error(request, 'Type the patient’s family name to confirm that this is the right person.')
        else:
            try:
                d, summary = MT.record_death(p, request.user, request.POST)
                done = ', '.join(f'{n} {k}' for k, n in summary.items()) or 'nothing else was open'
                messages.success(request, f'Death recorded for {p.full_name}. The patient is archived: {done}.')
                return redirect('death_detail', pk=d.pk)
            except ValidationError as e:
                _errors(request, e)
    adm = p.encounters.filter(admissions__discharged_at__isnull=True).first()
    current_adm = adm.admissions.filter(discharged_at__isnull=True).select_related('bed__ward').first() if adm else None
    preview = {
        'visits': p.encounters.filter(status='open').count(),
        'admission': current_adm,
        'tickets': p.tickets.filter(status__in=['waiting', 'called', 'in_service']).count(),
        'labs': __import__('hospital.models', fromlist=['LabOrder']).LabOrder.objects.filter(encounter__patient=p, status='ordered').count(),
        'rx': __import__('hospital.models', fromlist=['Prescription']).Prescription.objects.filter(encounter__patient=p, state__in=['draft', 'signed', 'partial']).count(),
        'ops': p.operations.filter(status__in=['requested', 'scheduled', 'ready', 'postponed']).count(),
        'enrolments': p.enrolments.filter(status__in=['active', 'paused', 'lost']).select_related('programme'),
    }
    return render(request, 'hospital/mortality/record.html', {
        'p': p, 'preview': preview, 'places': DeathRecord.PLACE, 'checks': DeathRecord.VERIFY_CHECKS, 'core': MT.CORE_CHECKS,
        'resus': [c for c in DeathRecord._meta.get_field('resuscitation').choices if c[0]], 'v': request.POST,
        'checked': [k for k, _ in DeathRecord.VERIFY_CHECKS if request.POST.get(f'check_{k}')],
        'now': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
        'place_default': request.POST.get('place_detail', '') if request.method == 'POST' else (str(current_adm.bed) if current_adm else ''),
        'suggest_place': 'icu' if current_adm and current_adm.bed.kind == 'icu' else ('maternity' if current_adm and current_adm.bed.kind == 'maternity' else 'ward' if current_adm else 'emergency'),
    })


# ------------------------------------------------------------------ the death record
def _death(pk):
    return get_object_or_404(DeathRecord.objects.select_related('patient__location', 'encounter__department', 'pronounced_by', 'certified_by',
                                                                  'released_by', 'nok_informed_by', 'admission__bed__ward'), pk=pk)


@login_required
def death_detail(request, pk):
    _need_any(request)
    d = _death(pk)
    audit(request, 'death_view', f'patient:{d.patient_id}', {'death': d.pk})
    autopsies = list(d.autopsies.select_related('pathologist', 'requested_by', 'signed_by'))
    review = getattr(d, 'review', None)
    sc = getattr(d, 'study_case', None)
    U = get_user_model()
    return render(request, 'hospital/mortality/detail.html', {
        'd': d, 'p': d.patient, 'journey': MT.journey(d), 'autopsies': autopsies, 'review': review, 'sc': sc,
        'open_autopsy': next((a for a in autopsies if a.open), None), 'kinds': Autopsy.KIND, 'consents': DeathRecord.CONSENT,
        'checks': DeathRecord.VERIFY_CHECKS, 'study_checks': MT.STUDY_CHECKS,
        'can': {'record': has(request.user, 'mortality'), 'certify': has(request.user, 'death_certify'),
                'autopsy': has(request.user, 'autopsy'), 'review': has(request.user, 'mortality_review'),
                'revoke': role_of(request.user) == 'admin'},
        'pathologists': U.objects.filter(Q(hospital_staff__role__in=['lab', 'doctor', 'admin'], hospital_staff__active=True)).order_by('first_name')[:60],
        'now': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
    })


@login_required
def death_certificate(request, pk):
    authorize(request)
    require(request, 'death_certify', 'Only staff allowed to certify deaths can write the certificate.')
    d = _death(pk)
    if request.method == 'POST':
        try:
            MT.certify(d, request.user, request.POST)
            messages.success(request, 'Certificate signed. A draft study case has been prepared for the library.' if d.teaching_consent != 'declined'
                             else 'Certificate signed.')
            return _back(d, 'certificate')
        except ValidationError as e:
            _errors(request, e)
    v = request.POST if request.method == 'POST' else None
    enc = d.encounter
    hints = []
    if enc and enc.diagnosis:
        hints.append(enc.diagnosis)
    hints += [c.name for c in d.patient.conditions.filter(status='active')[:6]]
    return render(request, 'hospital/mortality/certificate_form.html', {
        'd': d, 'p': d.patient, 'v': v, 'manners': DeathRecord.MANNER, 'maternal_choices': [m for m in DeathRecord.MATERNAL if m[0]],
        'ask_maternal': d.patient.sex == 'F' and 10 <= (d.patient.age or 0) <= 54, 'hints': list(dict.fromkeys(hints))[:8],
        'lines': [(k, v.get(f'cause_{k}', ''), v.get(f'interval_{k}', '')) if v is not None else (k, getattr(d, f'cause_{k}'), getattr(d, f'interval_{k}'))
                  for k in 'abcd'],
    })


@login_required
def death_print(request, pk):
    _need_any(request)
    d = _death(pk)
    if not d.certified:
        messages.error(request, 'The certificate has not been written yet.')
        return _back(d)
    audit(request, 'death_certificate_print', f'patient:{d.patient_id}', {'death': d.pk})
    import segno
    from django.utils.safestring import mark_safe
    url = request.build_absolute_uri(reverse('death_verify', args=[d.verify_token]))
    return render(request, 'hospital/mortality/certificate_print.html', {
        'd': d, 'p': d.patient, 'verify_url': url, 'intact': MT.certificate_hash(d) == d.content_hash,
        'qr': mark_safe(segno.make(url, error='m').svg_inline(scale=3, dark='#0F2C3F', light='#ffffff', border=1)),
    })


def death_verify(request, token):
    """Public: is this a genuine certificate from this hospital, unchanged since signing? Shows no cause of death."""
    d = DeathRecord.objects.filter(verify_token=token).select_related('patient', 'certified_by').first()
    ok = bool(d and d.certified and d.status != 'revoked' and MT.certificate_hash(d) == d.content_hash)
    return render(request, 'hospital/mortality/verify.html', {'d': d, 'ok': ok})


@login_required
@require_POST
def death_family(request, pk):
    authorize(request)
    require(request, 'mortality')
    d = _death(pk)
    try:
        MT.inform_family(d, request.user, request.POST)
        messages.success(request, 'Family details saved.')
    except ValidationError as e:
        _errors(request, e)
    return _back(d, 'family')


@login_required
@require_POST
def death_body(request, pk):
    authorize(request)
    require(request, 'mortality')
    d = _death(pk)
    action = request.POST.get('action', '')
    try:
        MT.move_body(d, request.user, action, request.POST)
        messages.success(request, {'mortuary': f'Body placed in {d.mortuary_slot or request.POST.get("mortuary_slot")}.',
                                   'release': 'Body released. The release is recorded on the death record.'}.get(action, 'Saved.'))
    except ValidationError as e:
        _errors(request, e)
    return _back(d, 'body')


@login_required
@require_POST
def death_revoke(request, pk):
    authorize(request)
    if role_of(request.user) != 'admin':
        raise PermissionDenied('Only a hospital administrator can mark a death record as entered in error.')
    d = _death(pk)
    try:
        _d, restored = MT.revoke(d, request.user, request.POST.get('reason', ''))
        messages.warning(request, f'{d.number} marked as entered in error and {d.patient.full_name} restored to the active record. '
                                  'Care-programme enrolments and reminders were restored; cancelled clinical orders were not — re-order what is still needed.')
        return redirect('patient_chart', pk=d.patient_id)
    except ValidationError as e:
        _errors(request, e)
        return _back(d)


# ------------------------------------------------------------------ autopsy
@login_required
@require_POST
def autopsy_new(request, pk):
    authorize(request)
    if not (has(request.user, 'mortality') or has(request.user, 'death_certify')):
        raise PermissionDenied('Your access does not include requesting an autopsy.')
    d = _death(pk)
    try:
        a = MT.request_autopsy(d, request.user, request.POST)
        messages.success(request, f'{a.number} requested. Pathology has been notified.' + (' Next: record the family’s consent.' if a.status == 'requested' and a.kind != 'verbal' else ''))
        return redirect('autopsy_detail', pk=a.pk)
    except ValidationError as e:
        _errors(request, e)
        return _back(d, 'autopsy')


@login_required
def autopsy_detail(request, pk):
    _need_any(request)
    a = get_object_or_404(Autopsy.objects.select_related('death__patient', 'death__encounter', 'pathologist', 'requested_by', 'signed_by', 'consent_witness'), pk=pk)
    if request.method == 'POST':
        require(request, 'autopsy', 'Only pathology staff can write the autopsy report.')
        try:
            MT.save_autopsy(a, request.POST)
            audit(request, 'autopsy_saved', f'patient:{a.death.patient_id}', {'autopsy': a.pk})
            messages.success(request, 'Autopsy report saved.')
            return redirect('autopsy_detail', pk=a.pk)
        except ValidationError as e:
            _errors(request, e)
    audit(request, 'autopsy_view', f'patient:{a.death.patient_id}', {'autopsy': a.pk})
    d = a.death
    labs = (__import__('hospital.models', fromlist=['LabResultValue']).LabResultValue.objects
            .filter(order__encounter__patient=d.patient, flag__in=['H', 'L', 'HH', 'LL', 'A']).select_related('parameter', 'order__test')
            .order_by('-order__created_at')[:16])
    U = get_user_model()
    return render(request, 'hospital/mortality/autopsy.html', {
        'a': a, 'd': d, 'p': d.patient, 'organs': _organs(a.organ_rows), 'goldman': [(k, l.split(' · ', 1)[-1]) for k, l in Autopsy.GOLDMAN if k],
        'can_write': has(request.user, 'autopsy') and not a.signed and a.status in ('in_progress', 'preliminary'),
        'can_autopsy': has(request.user, 'autopsy'), 'can_consent': has(request.user, 'mortality') or has(request.user, 'autopsy'),
        'labs': labs, 'enc': d.encounter, 'now': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
        'pathologists': U.objects.filter(Q(hospital_staff__role__in=['lab', 'doctor', 'admin'], hospital_staff__active=True)).order_by('first_name')[:60],
        'abnormal_n': sum(1 for o in a.organ_rows if o.get('abnormal')), 'examined_n': sum(1 for o in a.organ_rows if o.get('finding') or o.get('weight_g')),
        'intact': (MT.autopsy_hash(a) == a.content_hash) if a.signed else None,
    })


@login_required
@require_POST
def autopsy_act(request, pk, action):
    authorize(request)
    a = get_object_or_404(Autopsy.objects.select_related('death'), pk=pk)
    if action in ('consent', 'decline'):
        if not (has(request.user, 'mortality') or has(request.user, 'autopsy')):
            raise PermissionDenied('Your access does not include autopsy consent.')
    elif action == 'cancel':
        if not (has(request.user, 'autopsy') or a.requested_by_id == request.user.pk):
            raise PermissionDenied('Only pathology or the requester can cancel.')
    else:
        require(request, 'autopsy', 'Only pathology staff can do this.')
    try:
        MT.autopsy_action(a, request.user, action, request.POST)
        messages.success(request, {'consent': 'Consent recorded.', 'decline': 'Recorded: the family declined the autopsy.',
                                   'schedule': 'Autopsy scheduled.', 'start': 'Autopsy started. The body is marked as in pathology.',
                                   'preliminary': 'Preliminary report issued to the clinical team.',
                                   'sign': 'Autopsy report signed. The study case has been updated.', 'addendum': 'Addendum added.',
                                   'cancel': 'Autopsy cancelled.'}.get(action, 'Saved.'))
    except ValidationError as e:
        _errors(request, e)
    return redirect('autopsy_detail', pk=a.pk)


@login_required
def autopsy_print(request, pk):
    _need_any(request)
    a = get_object_or_404(Autopsy.objects.select_related('death__patient', 'pathologist', 'signed_by'), pk=pk)
    audit(request, 'autopsy_print', f'patient:{a.death.patient_id}', {'autopsy': a.pk})
    return render(request, 'hospital/mortality/autopsy_print.html', {'a': a, 'd': a.death, 'p': a.death.patient, 'organs': a.organ_rows})


# ------------------------------------------------------------------ M&M review and study case
@login_required
def death_review(request, pk):
    authorize(request)
    require(request, 'mortality_review', 'Your access does not include mortality reviews.')
    d = _death(pk)
    r = MortalityReview.objects.filter(death=d).first()
    if request.method == 'POST':
        try:
            MT.save_review(d, request.user, request.POST, finalise=request.POST.get('finalise') == '1')
            messages.success(request, 'Review finalised.' if request.POST.get('finalise') == '1' else 'Review saved as a draft.')
            return _back(d, 'review')
        except ValidationError as e:
            _errors(request, e)
    a = d.autopsies.filter(status='final').first()
    if request.method == 'POST':
        actions = [{'text': request.POST.get(f'action_{i}_text', ''), 'owner': request.POST.get(f'action_{i}_owner', ''),
                    'due': request.POST.get(f'action_{i}_due', ''), 'done': bool(request.POST.get(f'action_{i}_done'))} for i in range(6)]
    else:
        actions = list(r.actions) if r else []
        actions += [{}] * (6 - len(actions))
    return render(request, 'hospital/mortality/review.html', {
        'd': d, 'p': d.patient, 'r': r, 'a': a, 'preventable': [x for x in MortalityReview.PREVENTABLE if x[0]],
        'delays': MortalityReview.DELAYS, 'factors': MortalityReview.FACTORS, 'actions': actions[:6],
        'snap': MT.build_snapshot(d), 'v': request.POST if request.method == 'POST' else None,
        'sel_delays': request.POST.getlist('delays') if request.method == 'POST' else (r.delays if r else []),
        'sel_factors': request.POST.getlist('factors') if request.method == 'POST' else (r.factors if r else []),
    })


@login_required
@require_POST
def study_case_manage(request, pk):
    authorize(request)
    require(request, 'mortality_review', 'Your access does not include publishing study cases.')
    d = _death(pk)
    action = request.POST.get('action', '')
    try:
        if action == 'build':
            sc = MT.ensure_study_case(d)
            if not sc:
                raise ValidationError('A study case cannot be made: the family declined teaching use.')
            messages.success(request, f'{sc.code} prepared as a draft. Check the anonymised preview, then publish.')
        else:
            sc = get_object_or_404(StudyCase, death=d)
            if action == 'refresh':
                MT.refresh_case(sc); messages.success(request, 'Draft rebuilt from the current record.')
            elif action == 'publish':
                MT.publish_case(sc, request.user, request.POST); messages.success(request, f'{sc.code} published in the clinical library.')
            elif action == 'withdraw':
                MT.withdraw_case(sc, request.user, request.POST.get('reason', '')); messages.warning(request, f'{sc.code} withdrawn from the library.')
            elif action == 'redraft':
                MT.redraft_case(sc, request.user); messages.success(request, f'{sc.code} is a draft again.')
            else:
                raise ValidationError('Unknown action.')
    except ValidationError as e:
        _errors(request, e)
    return _back(d, 'library')


# ------------------------------------------------------------------ study cases in the clinical library
@login_required
def library_cases(request):
    authorize(request)
    require(request, 'library', 'Your access does not include the clinical library.')
    q = request.GET.get('q', '').strip()[:60]
    slug = request.GET.get('dx', '')[:80]
    cases = list(MT.published_cases(slug or None, q)[:120])
    from . import library as L
    return render(request, 'hospital/library/cases.html', {'cases': cases, 'q': q, 'slug': slug,
                                                            'slug_title': L.DISEASES[slug][0] if slug in L.DISEASES else '',
                                                            'goldman': dict(Autopsy.GOLDMAN)})


@login_required
def library_case(request, code):
    authorize(request)
    require(request, 'library', 'Your access does not include the clinical library.')
    sc = get_object_or_404(StudyCase.objects.select_related('death'), code=code[:20])
    preview = sc.status != 'published'
    if preview and not has(request.user, 'mortality_review'):
        raise Http404
    if sc.death.status == 'revoked':
        raise Http404
    snap = MT.build_snapshot(sc.death) if sc.status == 'draft' else sc.snapshot
    if not preview:
        StudyCase.objects.filter(pk=sc.pk).update(views=sc.views + 1)
    audit(request, 'study_case_view', f'study_case:{sc.pk}', {'code': sc.code})
    from . import library as L
    organ_keys = {o['key']: o for o in (snap.get('autopsy') or {}).get('organs', [])}
    return render(request, 'hospital/library/case.html', {
        'sc': sc, 's': snap, 'preview': preview, 'disease': L.DISEASES[sc.slug][0] if sc.slug in L.DISEASES else '',
        'body': _organs([{'key': k, 'label': lbl, **organ_keys.get(k, {})} for k, lbl in BODY_SYSTEMS]),
        'related': StudyCase.objects.filter(status='published', slug=sc.slug).exclude(pk=sc.pk)[:5] if sc.slug else [],
    })
