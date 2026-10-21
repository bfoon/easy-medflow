"""Send a lab request to a laboratory outside the hospital. See models_extlab.py for the two ways a lab gets in.

Everything that changes a send-out goes through this module so the hospital pages, the one-time link pages and the
network lab portal behave the same way.
"""
import re
import secrets
import time
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models_extlab import MAX_PHONE_ATTEMPTS, ExternalLabReferral, sha

DEFAULT_DAYS = 14
MAX_DAYS = 60
NETWORK_GRANT_HOURS = 8                      # a network lab keeps a request open this long after typing the phone number
LOOKUPS_PER_HOUR = 30
REPORT_TYPES = {'.pdf': 'application/pdf', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}
REPORT_MAX_MB = 10
CLAIM_COOKIE = 'mf_xl_'


def hospital():
    return {'name': getattr(settings, 'HOSPITAL_NAME', 'E-MedFlow Hospital'),
            'phone': getattr(settings, 'HOSPITAL_PHONE', ''), 'address': getattr(settings, 'HOSPITAL_ADDRESS', '')}


def facility_on_platform(facility):
    """A network facility counts as 'on E-MedFlow' when it has at least one active partner login."""
    return bool(facility) and facility.staff.filter(role='partner', active=True, user__is_active=True).exists()


def open_orders(lr):
    """Tests that can still go out: not cancelled, not yet resulted."""
    return [o for o in lr.orders.all() if o.status in ('ordered', 'collected')]


def active_for(lr):
    return lr.sendouts.filter(status__in=ExternalLabReferral.ACTIVE).first()


# ------------------------------------------------------------------ create / reissue / cancel
def create(lr, user, *, facility=None, lab_name='', lab_phone='', lab_email='', lab_address='', patient_phone='',
           instructions='', note_to_lab='', days=DEFAULT_DAYS, save_phone_to_patient=False):
    """Send the request out. Returns (send-out, plain token or None). Raises ValidationError with readable messages."""
    from .phones import digits, local
    errors = []
    if active_for(lr):
        errors.append('This request is already with an outside lab. Cancel that first.')
    if not open_orders(lr):
        errors.append('Every test in this request is already done or cancelled.')
    if lr.encounter.patient.is_deceased:
        errors.append('The patient is recorded as deceased.')
    name = (facility.name if facility else lab_name).strip()
    if not name:
        errors.append('Choose a lab from the network or type the name of the outside lab.')
    d = local(digits(patient_phone))
    if len(d) < 7:
        errors.append("Enter the patient's phone number (at least 7 digits). The lab types it to open the request.")
    try:
        days = max(1, min(MAX_DAYS, int(days or DEFAULT_DAYS)))
    except (TypeError, ValueError):
        days = DEFAULT_DAYS
    channel = 'network' if facility_on_platform(facility) else 'link'
    phone_out = (lab_phone or (facility.phone if facility else '')).strip()
    email_out = (lab_email or (facility.email if facility else '')).strip()
    if channel == 'link' and not (phone_out or email_out):
        errors.append('Give the lab a phone number or email address so the link can be sent to them.')
    if errors:
        raise ValidationError(errors)
    token = None
    with transaction.atomic():
        s = ExternalLabReferral(lab_request=lr, channel=channel, facility=facility, lab_name=name[:200], lab_phone=phone_out[:40],
                                lab_email=email_out[:254], lab_address=(lab_address or (facility.location if facility else ''))[:250],
                                patient_phone=patient_phone.strip()[:40], instructions=instructions.strip()[:2000],
                                note_to_lab=note_to_lab.strip()[:2000], expires_at=timezone.now() + timedelta(days=days), created_by=user)
        if channel == 'link':
            token = s.issue_token()
        s.save()
        p = lr.encounter.patient
        if save_phone_to_patient and not p.phone:
            p.phone = s.patient_phone
            p.save(update_fields=['phone'])
        if channel == 'network':
            from .notify import notify
            staff = [sp.user for sp in facility.staff.filter(role='partner', active=True).select_related('user')]
            notify(staff, f'Lab request expected · {s.reference}',
                   f'{p.first_name} {p.last_name[:1]}. · {len(open_orders(lr))} test(s) from {hospital()["name"]}. Open it with the patient\'s phone number.',
                   reverse('xl_network'), 'lab_sendout')
    return s, token


def reissue(s):
    """A new one-time link. The old link stops working at once; claim, wrong-number count and lock are reset."""
    if s.channel != 'link' or not s.is_active:
        raise ValidationError('Only an open send-out with a link can be re-issued.')
    token = s.issue_token()
    if s.is_expired:
        s.expires_at = timezone.now() + timedelta(days=DEFAULT_DAYS)
    s.save()
    return token


def cancel(s, reason):
    if not s.is_active:
        raise ValidationError('This send-out is already closed.')
    if not (reason or '').strip():
        raise ValidationError('Say why it is cancelled (the lab sees that the request was withdrawn).')
    s.status, s.cancelled_at, s.cancel_reason = 'cancelled', timezone.now(), reason.strip()[:300]
    s.token_hash = s.claim_hash = ''
    s.save()


# ------------------------------------------------------------------ the lab gets in
def phone_matches(s, typed):
    from .phones import digits, local
    d = local(digits(typed))
    return bool(d) and secrets.compare_digest(d, s.phone_local or '')


def try_phone(s, typed):
    """For the one-time link. True when the number is right; a wrong number counts, and the fifth locks the link."""
    with transaction.atomic():
        s = ExternalLabReferral.objects.select_for_update().get(pk=s.pk)
        if not s.is_open:
            return False, s
        if phone_matches(s, typed):
            return True, s
        s.failed_attempts += 1
        if s.failed_attempts >= MAX_PHONE_ATTEMPTS:
            s.locked_at = timezone.now()
            _tell_hospital(s, f'Link locked · {s.reference}', f'{s.lab_name} typed a wrong phone number {MAX_PHONE_ATTEMPTS} times. Re-issue the link if this was a mistake.', 'lab_sendout_locked')
        s.save(update_fields=['failed_attempts', 'locked_at', 'updated_at'])
        return False, s


def claim(s):
    """Bind the link to this browser: returns the secret to keep in a cookie (only its hash is stored)."""
    secret = secrets.token_urlsafe(24)
    first = s.claimed_at is None
    s.claim_hash, s.claimed_at = sha(secret), timezone.now()
    if s.status == 'sent':
        s.status, s.arrived_at = 'arrived', timezone.now()
    s.save()
    if first:
        _tell_hospital(s, f'Patient at {s.lab_name}', f'{s.reference} · {s.lab_request.number} was opened by the lab.', 'lab_sendout')
    return secret


def claim_ok(s, secret):
    return bool(s.claim_hash) and bool(secret) and secrets.compare_digest(sha(secret), s.claim_hash)


def network_find(facility, typed):
    """Open send-outs to this facility for the patient with that phone number."""
    from .phones import digits, local
    d = local(digits(typed))
    if len(d) < 7:
        return []
    qs = ExternalLabReferral.objects.filter(facility=facility, channel='network', status__in=ExternalLabReferral.ACTIVE, phone_local=d,
                                            expires_at__gte=timezone.now()).select_related('lab_request__encounter__patient')
    return list(qs)


def grant(request, s):
    g = dict(request.session.get('mf_xl', {}))
    g[str(s.pk)] = time.time() + NETWORK_GRANT_HOURS * 3600
    request.session['mf_xl'] = g


def granted(request, s):
    return request.session.get('mf_xl', {}).get(str(s.pk), 0) > time.time()


def network_arrived(s):
    if s.status == 'sent':
        s.status, s.arrived_at = 'arrived', timezone.now()
        s.save(update_fields=['status', 'arrived_at', 'updated_at'])
        _tell_hospital(s, f'Patient at {s.lab_name}', f'{s.reference} · {s.lab_request.number}', 'lab_sendout')


# ------------------------------------------------------------------ the lab works
def mark_collected(s, specimen_ref=''):
    if not s.is_open:
        raise ValidationError('This request is closed.')
    s.specimen_ref = (specimen_ref or '').strip()[:80] or s.specimen_ref
    if s.status in ('sent', 'arrived'):
        s.status, s.collected_at = 'collected', timezone.now()
        s.arrived_at = s.arrived_at or s.collected_at
    s.save()
    lr = s.lab_request
    for o in open_orders(lr):
        if o.status == 'ordered':
            o.status, o.specimen_id = 'collected', s.specimen_ref or s.reference
            o.save(update_fields=['status', 'specimen_id', 'updated_at'])
    if not lr.collected_at:
        lr.collected_at, lr.specimen_id = timezone.now(), lr.specimen_id or s.specimen_ref or s.reference
        lr.save(update_fields=['collected_at', 'specimen_id', 'updated_at'])


def sheet(s, post=None, errors=None):
    """The result sheet: one section per test going out, one row per catalogue parameter."""
    p = s.lab_request.encounter.patient
    out = []
    for o in [o for o in s.lab_request.orders.all() if o.status in ('ordered', 'collected', 'processing')]:
        existing = {v.parameter_id: v for v in o.values.all()}
        rows = []
        for prm in o.test.parameters.all():
            key = f'p_{o.pk}_{prm.pk}'
            v = existing.get(prm.pk)
            lo, hi = prm.range_for(p.sex)
            num = lambda d: '' if d is None else f'{d.normalize():f}'
            rows.append({'p': prm, 'key': key, 'range': prm.range_label(p.sex), 'error': (errors or {}).get(key),
                         'lo': num(lo), 'hi': num(hi), 'clo': num(prm.critical_low), 'chi': num(prm.critical_high),
                         'abn': '|'.join(prm.abnormal_choices or []),
                         'value': post.get(key, '') if post is not None else (v.display if v else '')})
        out.append({'o': o, 'rows': rows, 'comment_key': f'comment_{o.pk}', 'comment': post.get(f'comment_{o.pk}', '') if post is not None else o.result})
    return out


def check_file(f):
    import os
    if not f:
        return None
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in REPORT_TYPES:
        return 'Attach a PDF or a photo (JPG, PNG, WEBP).'
    if f.size > REPORT_MAX_MB * 1024 * 1024:
        return f'The file is larger than {REPORT_MAX_MB} MB.'
    head = f.read(16); f.seek(0)
    if ext == '.pdf' and not head.startswith(b'%PDF'):
        return 'That file is not a real PDF.'
    if ext != '.pdf':
        try:
            from PIL import Image
            Image.open(f).verify(); f.seek(0)
        except Exception:
            return 'That file is not a readable image.'
    return None


def submit_results(s, post, files, *, user=None):
    """Write the outside lab's results into the hospital request. Each test needs all its values, or the lab's report
    file must be attached. Returns (ok, errors dict, message). The hospital laboratory verifies afterwards."""
    from .models import LabResultValue
    if not s.is_open:
        return False, {}, 'This request is closed.'
    p = s.lab_request.encounter.patient
    orders = [o for o in s.lab_request.orders.select_related('test').prefetch_related('test__parameters') if o.status in ('ordered', 'collected', 'processing')]
    errors, parsed = {}, {}
    name = (post.get('reported_by_name') or '').strip()
    if not user and not name:
        errors['reported_by_name'] = 'Write the name of the person releasing these results.'
    upload = files.get('report_file') if files else None
    ferr = check_file(upload)
    if ferr:
        errors['report_file'] = ferr
    has_file = bool(upload and not ferr) or bool(s.report_file)
    for o in orders:
        for prm in o.test.parameters.all():
            key = f'p_{o.pk}_{prm.pk}'
            raw = (post.get(key) or '').strip()
            if not raw:
                continue
            if prm.kind == 'number':
                try:
                    parsed[key] = Decimal(raw.replace(',', '.'))
                except InvalidOperation:
                    errors[key] = 'Enter a number'
            elif prm.kind == 'choice' and prm.choices and raw not in prm.choices:
                errors[key] = 'Choose a listed option'
            else:
                parsed[key] = raw[:500]
    incomplete = []
    for o in orders:
        required = [prm for prm in o.test.parameters.all() if prm.kind != 'text']
        if required and not all(f'p_{o.pk}_{prm.pk}' in parsed for prm in required) and not has_file:
            incomplete.append(o.test.name)
    if incomplete:
        errors['_'] = 'Enter every value for: ' + ', '.join(incomplete) + ', or attach your lab report.'
    if errors:
        return False, errors, 'Please correct the marked fields.'
    now, crit = timezone.now(), 0
    with transaction.atomic():
        s = ExternalLabReferral.objects.select_for_update().get(pk=s.pk)
        if not s.is_open:
            return False, {}, 'This request was closed meanwhile.'
        if upload:
            s.report_file = upload
        who = name or (user.get_full_name() or user.username if user else '')
        for o in orders:
            for prm in o.test.parameters.all():
                val = parsed.get(f'p_{o.pk}_{prm.pk}')
                if val in (None, ''):
                    continue
                num = val if prm.kind == 'number' else None
                LabResultValue.objects.update_or_create(order=o, parameter=prm, defaults={
                    'value_number': num, 'value_text': '' if num is not None else val, 'flag': prm.flag_for(val, p.sex), 'entered_by': user})
            comment = (post.get(f'comment_{o.pk}') or '').strip()[:3500]
            source = f'Reported by {s.lab_name}' + (f' ({who})' if who else '') + (f', sample {s.specimen_ref}' if s.specimen_ref else '') + '.'
            if not o.values.exists() and s.report_file:
                source += ' See the attached lab report.'
            o.result = (comment + '\n' if comment else '') + source
            o.abnormal = o.values.exclude(flag__in=['', 'N']).exists()
            o.status, o.resulted_at, o.performed_by = 'resulted', now, user
            o.specimen_id = o.specimen_id or s.specimen_ref or s.reference
            o.save()
            crit += o.values.filter(flag__in=['LL', 'HH']).count()
        s.status, s.reported_at, s.reported_by, s.reported_by_name = 'reported', now, user, who[:160]
        s.collected_at = s.collected_at or now
        s.arrived_at = s.arrived_at or now
        s.lab_comment = (post.get('lab_comment') or '').strip()[:2000]
        s.token_hash = ''                                  # the link is finished: it can never open the record again
        s.save()
        lr = s.lab_request
        lr.collected_at = lr.collected_at or s.collected_at
        lr.received_at = lr.received_at or now
        lr.save(update_fields=['collected_at', 'received_at', 'updated_at'])
        if crit:
            from . import lab_mgmt
            lab_mgmt.register_criticals(lr, user or lr.requested_by)
        _tell_hospital(s, f'Results from {s.lab_name} · {lr.number}',
                       f'{s.reference}: ready for the laboratory to verify' + (f'. {crit} critical value(s)!' if crit else '.'),
                       'lab_critical' if crit else 'lab_sendout_result')
    return True, {}, f'Results sent to {hospital()["name"]}. Thank you.'


def _tell_hospital(s, title, body, kind):
    from .notify import notify
    lr = s.lab_request
    notify([lr.requested_by, lr.encounter.clinician, s.created_by], title, body, reverse('extlab_detail', args=[s.pk]), kind)


# ------------------------------------------------------------------ messages to send
def wa_number(phone):
    from .phones import country_code
    d = re.sub(r'\D', '', phone or '')
    if d.startswith('00'):
        d = d[2:]
    if len(d) == 7:
        d = country_code() + d
    return d


def share(request, s, token=None):
    """Ready-made messages: the link for the lab (only while the plain token is known) and directions for the patient."""
    from urllib.parse import quote
    h = hospital()
    lr, p = s.lab_request, s.lab_request.encounter.patient
    tests = ', '.join(o.test.name for o in open_orders(lr)) or ', '.join(o.test.name for o in lr.orders.all() if o.status != 'cancelled')
    out = {'tests': tests}
    if token:
        link = request.build_absolute_uri(reverse('xl_open', args=[token]))
        lab_text = (f'{h["name"]} has sent a laboratory request ({s.reference}, {tests}). '
                    f'Open it when the patient arrives: {link} . You will be asked for the patient\'s phone number. '
                    f'The link works on one device only and closes once the results are sent. Valid until {timezone.localtime(s.expires_at):%d %b %Y}.')
        lab_wa = wa_number(s.lab_phone)
        out.update({'link': link, 'lab_text': lab_text,
                    'lab_whatsapp': f'https://wa.me/{lab_wa}?text={quote(lab_text)}' if lab_wa else f'https://wa.me/?text={quote(lab_text)}',
                    'lab_sms': f'sms:{s.lab_phone}?body={quote(lab_text)}' if s.lab_phone else '',
                    'lab_email': f'mailto:{s.lab_email}?subject={quote(f"Laboratory request {s.reference} from {h["name"]}")}&body={quote(lab_text)}' if s.lab_email else ''})
    patient_text = (f'{h["name"]}: please go to {s.lab_name}' + (f' ({s.lab_address})' if s.lab_address else '') +
                    f' for your tests: {tests}. Reference {s.reference}. At the lab, give this phone number so they can find your request.'
                    + (f' {s.instructions}' if s.instructions else '') + f' Please go before {timezone.localtime(s.expires_at):%d %b %Y}.')
    pw = wa_number(s.patient_phone)
    out.update({'patient_text': patient_text, 'patient_whatsapp': f'https://wa.me/{pw}?text={quote(patient_text)}' if pw else '',
                'patient_sms': f'sms:{s.patient_phone}?body={quote(patient_text)}'})
    return out


# ------------------------------------------------------------------ printing helpers
TUBES = [('lavender', '#9B7BD4', ('purple', 'lavender', 'edta')), ('red', '#C8323F', ('red-top', 'red top', 'plain')),
         ('gold', '#E0B12A', ('gold', 'yellow', 'sst', 'gel')), ('green', '#2E9E5B', ('green', 'heparin')),
         ('grey', '#8A949C', ('grey', 'gray', 'fluoride')), ('black', '#2B3440', ('black',)), ('blue', '#4A8FD9', ('blue', 'citrate')),
         ('pot', '#E9EEF2', ('urine', 'stool', 'pot', 'container', 'swab', 'sterile'))]


def tube(test):
    """A colour chip for the container, read from the catalogue text ('Purple-top EDTA tube' -> lavender)."""
    text = f'{test.container} {test.sample_type}'.lower()
    for name, colour, words in TUBES:
        if any(w in text for w in words):
            return {'name': name, 'color': colour}
    return None


ONES = 'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
TENS = 'twenty thirty forty fifty sixty seventy eighty ninety'.split()


def in_words(n):
    """Quantities written out on printed prescriptions so a 10 cannot quietly become 100."""
    n = int(n)
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10 - 2] + ('-' + ONES[n % 10] if n % 10 else '')
    if n < 1000:
        return ONES[n // 100] + ' hundred' + (' and ' + in_words(n % 100) if n % 100 else '')
    if n < 10000:
        return in_words(n // 1000) + ' thousand' + ((' and ' if n % 1000 < 100 else ' ') + in_words(n % 1000) if n % 1000 else '')
    return str(n)
