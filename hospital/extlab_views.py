"""Outside laboratories and printouts.

Hospital side   /labs/requests/<pk>/send-out/   choose the lab, patient phone, instructions → one-time link or network
                /labs/outside/                   every request that is with an outside lab
                /labs/outside/<pk>/              tracker, messages to send, re-issue, cancel
One-time link   /xl/<token>/                     the outside lab types the patient's phone number, then works
Network lab     /network/lab-work/               partner labs on E-MedFlow find a request by phone number only
Printouts       /labs/requests/<pk>/print/       laboratory request form (with the outside-lab slip for the patient)
                /prescriptions/<pk>/print/       printable prescription (A4 or A5) with a verification QR code
                /rx/<token>/                     public check that a printed prescription is genuine and not dispensed
"""
import os
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Prefetch
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from . import extlab
from .models import AuditEvent, LabOrder, LabRequest, NetworkFacility
from .models_extlab import MAX_PHONE_ATTEMPTS, ExternalLabReferral
from .views import audit, authorize, lab_requests_qs, partner_facility, role_of, rx_qs

RX_VALID_DAYS = 30


def _qr(text, scale=2):
    import segno
    return mark_safe(segno.make(text, error='m').svg_inline(scale=scale, border=1))


def _can_send(request):
    from .access import has
    if request.user.is_superuser:
        return
    authorize(request)
    if not (has(request.user, 'clinical') or has(request.user, 'lab')):
        raise PermissionDenied('Only clinical and laboratory staff can send tests to an outside lab.')


def sendout_qs():
    return ExternalLabReferral.objects.select_related('lab_request__encounter__patient', 'lab_request__requested_by', 'facility', 'created_by').prefetch_related(
        Prefetch('lab_request__orders', queryset=LabOrder.objects.select_related('test').prefetch_related('values__parameter', 'test__parameters').order_by('id')))


def _audit_public(action, s, request, details=None):
    AuditEvent.objects.create(actor=None, action=action, target=f'lab_sendout:{s.pk}', details=details or {}, ip_address=request.META.get('REMOTE_ADDR'))


# ================================================================== hospital side
@login_required
def extlab_new(request, pk):
    """Send a lab request to an outside lab."""
    _can_send(request)
    lr = get_object_or_404(lab_requests_qs(), pk=pk)
    p = lr.encounter.patient
    current = extlab.active_for(lr)
    if current:
        messages.info(request, f'This request is already with {current.lab_name}.')
        return redirect('extlab_detail', pk=current.pk)
    facilities = list(NetworkFacility.objects.order_by('name'))
    on_platform = set(NetworkFacility.objects.filter(staff__role='partner', staff__active=True).values_list('pk', flat=True))
    for f in facilities:
        f.on_platform = f.pk in on_platform
    facilities.sort(key=lambda f: (not f.on_platform, f.kind != 'diagnostic', f.name))
    form = request.POST if request.method == 'POST' else {}
    if request.method == 'POST':
        fac = NetworkFacility.objects.filter(pk=request.POST.get('facility') or 0).first() if request.POST.get('where') == 'network' else None
        try:
            s, token = extlab.create(lr, request.user, facility=fac, lab_name=request.POST.get('lab_name', ''), lab_phone=request.POST.get('lab_phone', ''),
                                     lab_email=request.POST.get('lab_email', ''), lab_address=request.POST.get('lab_address', ''),
                                     patient_phone=request.POST.get('patient_phone', ''), instructions=request.POST.get('instructions', ''),
                                     note_to_lab=request.POST.get('note_to_lab', ''), days=request.POST.get('days'),
                                     save_phone_to_patient=request.POST.get('save_phone') == '1')
        except ValidationError as exc:
            for m in exc.messages:
                messages.error(request, m)
        else:
            audit(request, 'lab_sendout', f'lab_request:{lr.pk}', {'sendout': s.pk, 'lab': s.lab_name, 'channel': s.channel})
            if token:
                request.session[f'mf_xl_tok_{s.pk}'] = token       # shown once on the next page, then forgotten
            messages.success(request, f'{lr.number} is going to {s.lab_name}. '
                             + ('They will find it with the patient\'s phone number.' if s.channel == 'network' else 'Send them the one-time link below.'))
            return redirect('extlab_detail', pk=s.pk)
    return render(request, 'hospital/extlab/new.html', {
        'lr': lr, 'p': p, 'orders': extlab.open_orders(lr), 'facilities': facilities, 'form': form, 'days': extlab.DEFAULT_DAYS,
        'max_days': extlab.MAX_DAYS, 'phone': form.get('patient_phone') if form else p.phone,
        'past': lr.sendouts.exclude(status__in=ExternalLabReferral.ACTIVE)[:5]})


@login_required
def extlab_detail(request, pk):
    authorize(request)
    s = get_object_or_404(sendout_qs(), pk=pk)
    token = request.session.pop(f'mf_xl_tok_{s.pk}', None) if s.is_active else None
    audit(request, 'view_chart', f'lab_sendout:{s.pk}')
    from .access import has
    sh = extlab.share(request, s, token)
    return render(request, 'hospital/extlab/detail.html', {
        's': s, 'lr': s.lab_request, 'p': s.lab_request.encounter.patient, 'token': token, 'share': sh,
        'qr': _qr(sh['link'], 3) if token else None, 'can_manage': request.user.is_superuser or has(request.user, 'clinical') or has(request.user, 'lab'),
        'max_attempts': MAX_PHONE_ATTEMPTS, 'h': extlab.hospital()})


@login_required
@require_POST
def extlab_action(request, pk, action):
    _can_send(request)
    s = get_object_or_404(ExternalLabReferral, pk=pk)
    try:
        if action == 'reissue':
            token = extlab.reissue(s)
            request.session[f'mf_xl_tok_{s.pk}'] = token
            audit(request, 'lab_sendout_reissue', f'lab_sendout:{s.pk}')
            messages.success(request, 'New one-time link made. The old link no longer works. Send the new one to the lab.')
        elif action == 'cancel':
            extlab.cancel(s, request.POST.get('reason', ''))
            audit(request, 'lab_sendout_cancel', f'lab_sendout:{s.pk}', {'reason': s.cancel_reason})
            messages.success(request, f'{s.reference} withdrawn. The request is back with our laboratory.')
        else:
            raise Http404
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    return redirect('extlab_detail', pk=s.pk)


@login_required
def extlab_list(request):
    """Every request with an outside lab: waiting for the patient, at the lab, results back (to verify)."""
    authorize(request)
    rows = list(sendout_qs().filter(created_at__gte=timezone.now() - timedelta(days=120))[:300])
    lanes = [('waiting', 'Waiting for the patient', [s for s in rows if s.status == 'sent' and s.is_open]),
             ('at_lab', 'At the outside lab', [s for s in rows if s.status in ('arrived', 'collected') and s.is_open]),
             ('back', 'Results back · to verify', [s for s in rows if s.status == 'reported' and s.lab_request.stage == 'resulted']),
             ('problem', 'Needs attention', [s for s in rows if s.is_active and (s.is_expired or s.is_locked)])]
    done = [s for s in rows if s.status == 'reported' and s.lab_request.stage == 'verified'][:20]
    return render(request, 'hospital/extlab/list.html', {'lanes': lanes, 'done': done, 'tab': 'outside'})


@login_required
def extlab_file(request, pk):
    """The outside lab's own report: hospital staff, or the partner lab that sent it."""
    s = get_object_or_404(ExternalLabReferral, pk=pk)
    fac = partner_facility(request.user)
    if fac:
        if s.facility_id != fac.pk:
            raise PermissionDenied
    else:
        authorize(request)
    if not s.report_file:
        raise Http404
    ext = os.path.splitext(s.report_file.name)[1].lower()
    if ext not in extlab.REPORT_TYPES:
        raise Http404
    try:
        resp = FileResponse(s.report_file.open('rb'), content_type=extlab.REPORT_TYPES[ext])
    except FileNotFoundError:
        raise Http404
    resp['Content-Disposition'] = f'inline; filename="{s.reference}{ext}"'
    resp['Cache-Control'] = 'private, max-age=600'
    resp['X-Content-Type-Options'] = 'nosniff'
    return resp


# ================================================================== one-time link (no sign-in)
def _closed(request, title, message, status=410):
    return render(request, 'hospital/extlab/public_closed.html', {'title': title, 'message': message, 'h': extlab.hospital()}, status=status)


def _link_state(s):
    """None when the link may be used, else (title, message) explaining why not. Never reveals patient details."""
    if s is None:
        return 'Link not valid', 'This link is not valid. It may have been replaced by a newer one. Ask the hospital to send it again.'
    if s.status == 'reported':
        return 'Results received', 'The results for this request were sent to the hospital. Thank you. This link is now closed.'
    if s.status == 'cancelled':
        return 'Request withdrawn', 'The hospital withdrew this request. Please do not take a sample.'
    if s.is_locked:
        return 'Link locked', 'A wrong phone number was entered too many times. Ask the hospital to send a new link.'
    if s.is_expired:
        return 'Link expired', 'This request has expired. Ask the hospital or the patient for a new request.'
    return None


def xl_open(request, token):
    """Landing page for the outside lab: hospital, reference, number of tests, and the phone number box."""
    s = ExternalLabReferral.from_token(token)
    bad = _link_state(s)
    if bad:
        return _closed(request, *bad, status=404 if s is None else 410)
    cookie = request.COOKIES.get(extlab.CLAIM_COOKIE + s.reference)
    if s.claimed_at:
        if extlab.claim_ok(s, cookie):
            return redirect('xl_work', token=token)
        return _closed(request, 'Link already used', 'This one-time link was already opened on another device. Ask the hospital to send a new link.', 403)
    error = ''
    if request.method == 'POST':
        ok, s = extlab.try_phone(s, request.POST.get('phone', ''))
        if ok:
            secret = extlab.claim(s)
            _audit_public('lab_sendout_claimed', s, request)
            resp = redirect('xl_work', token=token)
            resp.set_cookie(extlab.CLAIM_COOKIE + s.reference, secret, max_age=60 * 60 * 24 * extlab.MAX_DAYS, httponly=True,
                            samesite='Lax', secure=request.is_secure(), path='/xl/')
            return resp
        _audit_public('lab_sendout_wrong_phone', s, request, {'attempt': s.failed_attempts})
        bad = _link_state(s)
        if bad:
            return _closed(request, *bad)
        left = MAX_PHONE_ATTEMPTS - s.failed_attempts
        error = f'That number does not match. {left} attempt{"s" if left != 1 else ""} left before the link locks.'
    lr = s.lab_request
    return render(request, 'hospital/extlab/public_open.html', {'s': s, 'h': extlab.hospital(), 'error': error,
                                                                'n_tests': len([o for o in lr.orders.all() if o.status != 'cancelled']),
                                                                'priority': lr.get_priority_display(), 'is_urgent': lr.priority != 'routine'})


def xl_work(request, token):
    """The outside lab's workbench after the phone number matched: details, print, sample taken, results."""
    s = ExternalLabReferral.from_token(token)
    bad = _link_state(s)
    if bad:
        return _closed(request, *bad, status=404 if s is None else 410)
    if not extlab.claim_ok(s, request.COOKIES.get(extlab.CLAIM_COOKIE + s.reference)):
        return redirect('xl_open', token=token)
    s = sendout_qs().get(pk=s.pk)
    resp = _workbench(request, s, user=None, template='hospital/extlab/public_work.html', back=reverse('xl_work', args=[token]))
    resp['Cache-Control'] = 'no-store'
    resp['X-Robots-Tag'] = 'noindex, nofollow'
    return resp


def _workbench(request, s, *, user, template, back):
    errors, post = {}, None
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'collected':
            try:
                extlab.mark_collected(s, request.POST.get('specimen_ref', ''))
                messages.success(request, 'Sample recorded. Enter the results when they are ready; you can come back to this page.')
                if user is None:
                    _audit_public('lab_sendout_collected', s, request)
                else:
                    audit(request, 'lab_sendout_collected', f'lab_sendout:{s.pk}')
            except ValidationError as exc:
                messages.error(request, ' '.join(exc.messages))
            return redirect(back)
        if action == 'results':
            ok, errors, msg = extlab.submit_results(s, request.POST, request.FILES, user=user)
            if ok:
                if user is None:
                    _audit_public('lab_sendout_reported', s, request)
                else:
                    audit(request, 'lab_sendout_reported', f'lab_sendout:{s.pk}')
                s.refresh_from_db()
                return render(request, template, {'s': s, 'done': True, 'message': msg, 'h': extlab.hospital()})
            messages.error(request, msg)
            post = request.POST
    p = s.lab_request.encounter.patient
    return render(request, template, {'s': s, 'lr': s.lab_request, 'p': p, 'h': extlab.hospital(), 'sections': extlab.sheet(s, post, errors),
                                      'errors': errors, 'post': post or {}, 'tubes': {o.pk: extlab.tube(o.test) for o in s.lab_request.orders.all()},
                                      'is_network': user is not None})


# ================================================================== network lab (partner login)
def _partner(request):
    fac = partner_facility(request.user)
    if not fac:
        raise PermissionDenied('This page is for partner laboratories on E-MedFlow.')
    return fac


@login_required
def xl_network(request):
    """Partner lab: patients expected (no names until the phone number is given) and the phone-number search."""
    fac = _partner(request)
    found = None
    if request.method == 'POST':
        recent = AuditEvent.objects.filter(actor=request.user, action__in=['lab_sendout_lookup', 'lab_sendout_lookup_failed'],
                                           occurred_at__gte=timezone.now() - timedelta(hours=1)).count()
        if recent >= extlab.LOOKUPS_PER_HOUR:
            messages.error(request, 'Too many searches in the last hour. Please try again later.')
        else:
            found = extlab.network_find(fac, request.POST.get('phone', ''))
            audit(request, 'lab_sendout_lookup' if found else 'lab_sendout_lookup_failed', f'facility:{fac.pk}', {'found': len(found)})
            if not found:
                messages.error(request, 'No open request for your lab matches that phone number.')
            for s in found:
                extlab.grant(request, s)
                extlab.network_arrived(s)
            if len(found) == 1:
                return redirect('xl_network_work', pk=found[0].pk)
    qs = sendout_qs().filter(facility=fac, channel='network')
    expected = [s for s in qs.filter(status__in=ExternalLabReferral.ACTIVE) if s.is_open]
    recent_done = list(qs.filter(status='reported').order_by('-reported_at')[:10])
    return render(request, 'hospital/extlab/network.html', {'fac': fac, 'expected': expected, 'found': found, 'recent_done': recent_done,
                                                            'granted': {s.pk for s in expected if extlab.granted(request, s)}})


@login_required
def xl_network_work(request, pk):
    fac = _partner(request)
    s = get_object_or_404(sendout_qs(), pk=pk, facility=fac, channel='network')
    if s.status == 'reported':
        return render(request, 'hospital/extlab/network_work.html', {'s': s, 'done': True, 'message': 'Results were sent to the hospital.', 'h': extlab.hospital()})
    if not s.is_open:
        messages.error(request, 'This request is closed (cancelled or expired).')
        return redirect('xl_network')
    if not extlab.granted(request, s):
        messages.info(request, "Type the patient's phone number to open this request.")
        return redirect('xl_network')
    return _workbench(request, s, user=request.user, template='hospital/extlab/network_work.html', back=reverse('xl_network_work', args=[s.pk]))


# ================================================================== printouts
@login_required
def lab_request_print(request, pk):
    """Laboratory request form. When the request is with an outside lab, the bottom part is the patient's slip."""
    authorize(request)
    lr = get_object_or_404(lab_requests_qs(), pk=pk)
    s = extlab.active_for(lr)
    audit(request, 'lab_request_print', f'lab_request:{lr.pk}')
    orders = [o for o in lr.orders.all() if o.status != 'cancelled']
    p = lr.encounter.patient
    return render(request, 'hospital/print/lab_request.html', {
        'lr': lr, 'p': p, 's': s, 'h': extlab.hospital(), 'orders': [{'o': o, 'tube': extlab.tube(o.test)} for o in orders],
        'qr': _qr(lr.specimen_id or lr.number), 'allergies': p.allergies.filter(status='active'),
        'fasting': any('fast' in (o.test.name + ' ' + o.test.description).lower() for o in orders),
        'size': 'a5' if request.GET.get('size') == 'a5' else 'a4', 'licence': _licence(lr.requested_by)})


def rx_token(p):
    from django.core import signing
    return signing.dumps(p.pk, salt='medflow.rx.verify')


@login_required
def prescription_print(request, pk):
    authorize(request)
    p = get_object_or_404(rx_qs(), pk=pk)
    patient = p.encounter.patient
    audit(request, 'prescription_print', f'prescription:{p.pk}')
    url = request.build_absolute_uri(reverse('rx_verify', args=[rx_token(p)]))
    items = [{'i': i, 'words': extlab.in_words(i.quantity)} for i in p.items.all()]
    return render(request, 'hospital/print/prescription.html', {
        'p': p, 'patient': patient, 'items': items, 'h': extlab.hospital(), 'qr': _qr(url), 'verify_url': url,
        'allergies': patient.allergies.filter(status='active'), 'licence': _licence(p.signed_by),
        'valid_until': (p.signed_at + timedelta(days=RX_VALID_DAYS)) if p.signed_at else None,
        'size': 'a4' if request.GET.get('size') == 'a4' else 'a5', 'copy': request.GET.get('copy') == '1'})


def _licence(user):
    prof = getattr(user, 'hospital_staff', None) if user else None
    return prof.license_number if prof else ''


def rx_verify(request, token):
    """Public: a pharmacy scans the QR to check a printed prescription. Shows no name, only initials and birth year."""
    from django.core import signing
    try:
        pk = signing.loads(token, salt='medflow.rx.verify')
    except signing.BadSignature:
        raise Http404
    p = get_object_or_404(rx_qs(), pk=pk)
    AuditEvent.objects.create(actor=request.user if request.user.is_authenticated else None, action='rx_verify', target=f'prescription:{p.pk}',
                              ip_address=request.META.get('REMOTE_ADDR'))
    if p.state == 'draft':
        verdict, tone = 'Not valid · never signed', 'bad'
    elif p.state == 'cancelled':
        verdict, tone = 'Cancelled by the hospital', 'bad'
    elif p.state == 'dispensed':
        verdict, tone = 'Already dispensed', 'bad'
    elif p.signed_at and p.signed_at + timedelta(days=RX_VALID_DAYS) < timezone.now():
        verdict, tone = 'Expired', 'bad'
    elif p.state == 'partial':
        verdict, tone = 'Partly dispensed · check which medicines are still owed', 'warn'
    else:
        verdict, tone = 'Genuine and valid', 'ok'
    pt = p.encounter.patient
    return render(request, 'hospital/print/rx_verify.html', {
        'p': p, 'verdict': verdict, 'tone': tone, 'h': extlab.hospital(), 'initials': pt.initials, 'birth_year': pt.dob.year if pt.dob else '',
        'items': [{'i': i, 'given': i.dispensed_quantity} for i in p.items.all()],
        'valid_until': (p.signed_at + timedelta(days=RX_VALID_DAYS)) if p.signed_at else None})
