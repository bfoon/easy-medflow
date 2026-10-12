"""E-sign pages: compose, prepare (place fields), sign (staff, external link or in person), track, verify."""
import hashlib
import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import esign as E
from .models import Envelope, EnvelopeRecipient, FormSubmission, Patient, SignatureProfile
from .studio_views import _body, _staff_list
from .views import ROLES, audit, authorize, role_of

ROLES['esign'] = {'admin', 'doctor', 'nurse', 'reception', 'lab', 'radiology', 'pharmacy', 'finance', 'management'}


def _env(request, uid, manage=False):
    env = get_object_or_404(Envelope.objects.select_related('created_by', 'patient', 'submission'), uid=uid)
    u = request.user
    involved = env.created_by_id == u.pk or u.is_superuser or env.recipients.filter(Q(user=u) | Q(host=u)).exists()
    if manage and not (env.created_by_id == u.pk or u.is_superuser or role_of(u) in ('admin', 'management')):
        raise PermissionDenied('Only the sender or a manager can change this envelope.')
    if not involved and not (env.patient_id and role_of(u) in ('doctor', 'nurse', 'admin', 'management')):
        raise PermissionDenied('You are not part of this envelope.')
    return env


@login_required
def home(request):
    authorize(request, 'esign')
    E.sweep()
    u = request.user
    qs = Envelope.objects.select_related('patient', 'created_by').prefetch_related('recipients')
    tab = request.GET.get('tab', 'action')
    lists = {
        'action': qs.filter(status='sent').filter(Q(recipients__user=u, recipients__status__in=['sent', 'viewed']) |
                                                    Q(recipients__role='in_person', recipients__status__in=['sent', 'viewed'], recipients__host=u) |
                                                    Q(recipients__role='in_person', recipients__status__in=['sent', 'viewed'], created_by=u)).distinct(),
        'sent': qs.filter(created_by=u).exclude(status='draft'),
        'drafts': qs.filter(created_by=u, status='draft'),
        'completed': qs.filter(Q(created_by=u) | Q(recipients__user=u), status='completed').distinct(),
    }
    counts = {k: v.count() for k, v in lists.items()}
    return render(request, 'hospital/esign/home.html', {'tab': tab, 'envelopes': lists.get(tab, lists['action'])[:60], 'counts': counts,
                                                        'profile': SignatureProfile.objects.filter(user=u).first()})


@login_required
def compose(request):
    authorize(request, 'esign')
    if request.method == 'POST':
        src = request.POST.get('source', 'upload')
        patient = Patient.objects.filter(pk=request.POST.get('patient') or None).first()
        try:
            recips = json.loads(request.POST.get('recipients') or '[]')
            if not isinstance(recips, list) or not recips:
                raise E.EsignError('Add at least one recipient.')
            U = get_user_model()
            clean = []
            for r in recips[:20]:
                user = U.objects.filter(pk=r.get('user'), is_active=True).first() if r.get('user') else None
                if r.get('role') == 'in_person' and not r.get('name') and patient:
                    r['name'] = patient.full_name
                clean.append({**r, 'user': user, 'host': request.user if r.get('role') == 'in_person' else None})
            signers = [(r.get('name') or (r['user'].get_full_name() or r['user'].username), r.get('relation', '')) for r in clean if r.get('role') != 'cc' and r.get('role') != 'approver']
            blocks = None
            if src == 'upload':
                f = request.FILES.get('document')
                if not f:
                    raise E.EsignError('Choose a PDF to upload.')
                data, name = f.read(E.MAX_PDF_BYTES + 1), f.name
            elif src == 'form':
                sub = get_object_or_404(FormSubmission, pk=request.POST.get('submission'))
                patient = sub.patient
                data, blocks = E.submission_pdf(sub, signers)
                name = f'{sub.definition.slug}.pdf'
            elif src == 'letter':
                title, body = request.POST.get('title', '').strip()[:160], request.POST.get('body', '').strip()[:20000]
                if not title or not body:
                    raise E.EsignError('Write a title and the text of the document.')
                data, blocks = E.letter_pdf(title, body, patient, signers)
                name = f'{title[:40]}.pdf'
            else:
                raise E.EsignError('Choose where the document comes from.')
            env = E.create_envelope(user=request.user, subject=request.POST.get('subject', '').strip() or name, message=request.POST.get('message', ''),
                                    source=src, pdf_bytes=data, name=name, patient=patient, submission=sub if src == 'form' else None,
                                    recipients=clean, expires_days=int(request.POST.get('expires_days') or 14),
                                    require_full_read=request.POST.get('require_full_read') == 'on', request=request)
            if blocks:
                E.auto_place(env, blocks)
            audit(request, 'esign_created', f'envelope:{env.pk}')
            return redirect('esign_prepare', uid=env.uid)
        except ValidationError as e:
            messages.error(request, '; '.join(e.messages))
    subs = FormSubmission.objects.select_related('definition', 'patient').order_by('-created_at')[:80]
    return render(request, 'hospital/esign/compose.html', {
        'patients': Patient.objects.order_by('last_name')[:400], 'submissions': subs,
        'boot': {'staff': _staff_list(), 'me': request.user.pk, 'source': request.GET.get('source', 'upload'),
                 'submission': request.GET.get('submission'), 'patient': request.GET.get('patient'),
                 'roles': dict(EnvelopeRecipient.ROLE), 'merge': list(E.MERGE)}})


@login_required
def prepare(request, uid):
    authorize(request, 'esign')
    env = _env(request, uid, manage=True)
    if request.method == 'POST':
        data = _body(request)
        if data is None:
            return JsonResponse({'ok': False, 'error': 'Invalid data'}, status=400)
        try:
            n = E.save_fields(env, data.get('fields'))
            if data.get('send'):
                E.send(env, request.user, request)
                audit(request, 'esign_sent', f'envelope:{env.pk}')
                return JsonResponse({'ok': True, 'url': reverse('esign_detail', args=[env.uid])})
            return JsonResponse({'ok': True, 'saved': n})
        except ValidationError as e:
            return JsonResponse({'ok': False, 'error': '; '.join(e.messages)}, status=400)
    if env.status != 'draft':
        return redirect('esign_detail', uid=env.uid)
    return render(request, 'hospital/esign/prepare.html', {'env': env, 'boot': {
        'pdf': reverse('esign_file', args=[env.uid, 'original']), 'pages': env.pages, 'sizes': env.page_sizes, 'save_url': request.path,
        'recipients': [{'id': r.pk, 'name': r.name, 'role': r.role, 'color': r.color, 'order': r.order, 'fields': r.needs_fields} for r in env.recipients.all()],
        'fields': [{'id': f.pk, 'recipient': f.recipient_id, 'kind': f.kind, 'page': f.page, 'x': f.x, 'y': f.y, 'w': f.w, 'h': f.h,
                    'required': f.required, 'label': f.label, 'options': f.options} for f in env.fields.all()],
        'kinds': dict(env.fields.model.KIND), 'sizes_default': E.FIELD_SIZES}})


@login_required
def detail(request, uid):
    authorize(request, 'esign')
    env = _env(request, uid)
    ok, problems = E.verify(env)
    recips = list(env.recipients.select_related('user', 'host'))
    order = E.current_order(env) if env.status == 'sent' else None
    can_manage = env.created_by_id == request.user.pk or request.user.is_superuser or role_of(request.user) in ('admin', 'management')
    groups = {}
    for r in recips:
        groups.setdefault(r.order, []).append(r)
    return render(request, 'hospital/esign/detail.html', {
        'env': env, 'groups': sorted(groups.items()), 'current': order, 'events': _labelled(env.events.select_related('recipient', 'actor')),
        'ok': ok, 'problems': problems, 'can_manage': can_manage,
        'in_person': [r for r in recips if r.role == 'in_person' and r.status in ('sent', 'viewed') and (r.host_id in (None, request.user.pk) or request.user.is_superuser or env.created_by_id == request.user.pk)],
        'my_turn': next((r for r in recips if r.user_id == request.user.pk and r.status in ('sent', 'viewed')), None),
        'links': [r for r in recips if not r.user_id and r.role != 'in_person' and r.status in ('sent', 'viewed')] if can_manage else [],
        'site': request.build_absolute_uri('/').rstrip('/'),
    })


EVENT_LABELS = {'created': 'Created', 'sent': 'Sent', 'sent_to': 'Sent to', 'copy_sent': 'Copy sent to', 'viewed': 'Opened', 'signed': 'Signed',
                'approved': 'Approved', 'declined': 'Declined', 'voided': 'Cancelled', 'expired': 'Expired', 'reminded': 'Reminder sent',
                'completed': 'Completed and sealed', 'access_code_ok': 'Access code accepted', 'access_code_wrong': 'Wrong access code'}


def _labelled(events):
    out = list(events)
    for ev in out:
        ev.label = EVENT_LABELS.get(ev.action, ev.action.replace('_', ' ').capitalize())
    return out


@login_required
@require_POST
def act(request, uid, action):
    authorize(request, 'esign')
    env = _env(request, uid, manage=True)
    try:
        if action == 'void':
            reason = request.POST.get('reason', '').strip()
            if len(reason) < 3:
                raise E.EsignError('Give a reason for cancelling.')
            if env.status not in ('draft', 'sent'):
                raise E.EsignError('Only a draft or an envelope that is out for signature can be cancelled.')
            E.void(env, request.user, reason, request)
            if env.run_id:
                from . import flows
                flows.on_envelope(env)
            messages.success(request, 'Envelope cancelled.')
        elif action == 'remind':
            n = E.remind(env, request.user, request)
            messages.success(request, f'Reminder sent to {n} recipient{"s" if n != 1 else ""}.' if n else 'Nobody is waiting to sign.')
        else:
            raise E.EsignError('Unknown action.')
    except ValidationError as e:
        messages.error(request, '; '.join(e.messages))
    return redirect('esign_detail', uid=env.uid)


def _send_file(f, name, download=False):
    if not f:
        raise Http404
    resp = FileResponse(f.open('rb'), content_type='application/pdf', as_attachment=download, filename=name)
    resp['X-Content-Type-Options'] = 'nosniff'
    resp['Cache-Control'] = 'private, no-store'
    return resp


@login_required
def file(request, uid, which):
    authorize(request, 'esign')
    env = _env(request, uid)
    if which == 'certificate':
        from django.http import HttpResponse
        r = HttpResponse(E.certificate(env), content_type='application/pdf')
        r['Content-Disposition'] = f'inline; filename="certificate-{env.short_id}.pdf"'
        return r
    f = env.signed_document if which == 'signed' else env.document
    return _send_file(f, f'{env.short_id}-{which}.pdf', download=request.GET.get('download') == '1')


# ------------------------------------------------------------------ signing (staff, external, in person)
def _rec(token):
    return get_object_or_404(EnvelopeRecipient.objects.select_related('envelope__created_by', 'envelope__patient', 'host', 'user'), token=token)


def sign_page(request, token):
    rec = _rec(token)
    env = rec.envelope
    ok, why = E.can_open(rec, request.user, request.session)
    if not ok:
        if why in ('login', 'in_person'):
            if not request.user.is_authenticated:
                return redirect(f'{reverse("login")}?next={request.path}')
            return render(request, 'hospital/esign/blocked.html', {'env': env, 'message': 'This signing link belongs to someone else. Sign in with the right account.' if why == 'login'
                                                                    else 'In-person signing must be started by the staff member hosting it.'}, status=403)
        return render(request, 'hospital/esign/access_code.html', {'env': env, 'rec': rec})
    if request.method == 'GET':
        E.mark_viewed(rec, request) if rec.status == 'sent' and env.status == 'sent' else None
    others = [{'kind': f.kind, 'page': f.page, 'x': f.x, 'y': f.y, 'w': f.w, 'h': f.h, 'value': f.value, 'color': f.recipient.color,
               'image': (f.recipient.signature_image if f.kind == 'signature' else f.recipient.initials_image if f.kind == 'initials' else '') if f.value else '',
               'name': f.recipient.name} for f in env.fields.exclude(recipient=rec).select_related('recipient')]
    profile = SignatureProfile.objects.filter(user=request.user).first() if request.user.is_authenticated and rec.user_id == request.user.pk else None
    boot = {'token': rec.token, 'pdf': reverse('esign_sign_file', args=[rec.token]), 'pages': env.pages, 'sizes': env.page_sizes,
            'status': rec.status, 'env_status': env.status, 'role': rec.role, 'name': rec.name, 'color': rec.color,
            'require_full_read': env.require_full_read, 'pages_seen': rec.pages_seen, 'act_url': reverse('esign_sign_act', args=[rec.token]),
            'fields': [{'id': f.pk, 'kind': f.kind, 'page': f.page, 'x': f.x, 'y': f.y, 'w': f.w, 'h': f.h, 'required': f.required,
                        'label': f.label, 'options': f.options, 'value': f.value} for f in rec.fields.all()],
            'others': others, 'saved_signature': profile.signature if profile else '', 'saved_initials': profile.initials if profile else '',
            'in_person': rec.role == 'in_person', 'patient_dob': env.patient.dob.strftime('%d %b %Y') if rec.role == 'in_person' and env.patient else '',
            'detail_url': reverse('esign_detail', args=[env.uid]) if request.user.is_authenticated else '',
            'signed_url': reverse('esign_sign_file', args=[rec.token]) + '?signed=1' if env.status == 'completed' else ''}
    return render(request, 'hospital/esign/sign.html', {'env': env, 'rec': rec, 'boot': boot,
                                                       'public': not request.user.is_authenticated or rec.role != 'in_person' and not rec.user_id})


def sign_file(request, token):
    rec = _rec(token)
    ok, _ = E.can_open(rec, request.user, request.session)
    if not ok:
        raise PermissionDenied('Open the signing link first.')
    env = rec.envelope
    if request.GET.get('signed') == '1':
        if env.status != 'completed':
            raise Http404
        return _send_file(env.signed_document, f'{env.short_id}-signed.pdf', download=True)
    return _send_file(env.document, f'{env.short_id}.pdf')


@require_POST
def sign_act(request, token):
    rec = _rec(token)
    data = _body(request)
    if data is None:
        return JsonResponse({'ok': False, 'error': 'Invalid data'}, status=400)
    action = data.get('action')
    try:
        if action == 'code':
            if E.check_access_code(rec, str(data.get('code', ''))[:40], request.session):
                return JsonResponse({'ok': True, 'url': reverse('esign_sign', args=[token])})
            return JsonResponse({'ok': False, 'error': 'That code is not right.'}, status=400)
        ok, _ = E.can_open(rec, request.user, request.session)
        if not ok:
            raise PermissionDenied('You cannot act on this envelope.')
        actor = request.user if request.user.is_authenticated else None
        if action == 'viewed':
            E.mark_viewed(rec, request, data.get('pages') or [])
            return JsonResponse({'ok': True, 'pages_seen': rec.pages_seen})
        if action == 'sign':
            E.sign(rec, request, values={str(k): v for k, v in (data.get('values') or {}).items()}, signature=data.get('signature'),
                   initials=data.get('initials'), identity_check=str(data.get('identity_check', '')), consent=bool(data.get('consent')), actor=actor)
        elif action == 'approve':
            if not data.get('consent'):
                raise E.EsignError('Tick the box to confirm your approval.')
            E.approve(rec, request, actor=actor)
        elif action == 'decline':
            E.decline(rec, request, str(data.get('reason', '')), actor=actor)
        else:
            raise E.EsignError('Unknown action.')
    except ValidationError as e:
        return JsonResponse({'ok': False, 'error': '; '.join(e.messages)}, status=400)
    rec.refresh_from_db()
    rec.envelope.refresh_from_db()
    nxt = None
    if rec.role == 'in_person' or (actor and rec.envelope.created_by_id == actor.pk):
        # hand the device on: the next in-person signer, or back to the envelope page for the host
        n = rec.envelope.recipients.filter(role__in=['in_person', 'witness'], status__in=['sent', 'viewed']).filter(Q(host=actor) | Q(user=actor)).first() if actor else None
        nxt = reverse('esign_sign', args=[n.token]) if n else reverse('esign_detail', args=[rec.envelope.uid])
    return JsonResponse({'ok': True, 'status': rec.status, 'envelope': rec.envelope.status, 'next': nxt})


def verify(request):
    """Public: is this PDF the sealed version of an E-MedFlow envelope? Shows no patient details."""
    result = None
    if request.method == 'POST':
        f = request.FILES.get('document')
        code = request.POST.get('envelope', '').strip().replace('-', '').lower()
        env = None
        if f:
            digest = hashlib.sha256(f.read(E.MAX_PDF_BYTES + 1)).hexdigest()
            env = Envelope.objects.filter(signed_sha256=digest).first()
            result = {'digest': digest, 'found': bool(env)}
        elif len(code) >= 8:
            env = Envelope.objects.filter(status='completed').filter(uid__startswith=code[:8]).first() if len(code) < 32 else Envelope.objects.filter(uid=code).first()
            result = {'digest': '', 'found': bool(env)}
        if env:
            ok, problems = E.verify(env)
            result.update({'ok': ok, 'problems': problems, 'id': env.short_id, 'completed_at': env.completed_at, 'status': env.get_status_display(),
                           'signers': env.recipients.exclude(role='cc').count(), 'pages': env.pages, 'signed_sha256': env.signed_sha256})
    return render(request, 'hospital/esign/verify.html', {'result': result})
