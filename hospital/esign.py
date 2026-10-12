"""E-sign: envelopes that carry one PDF to people in routing order, collect signatures and seal the result.

* Documents are always PDFs: uploads are checked; form submissions and letters written here are rendered to PDF.
* Fields sit on pages as fractions (0–1) of the page width/height, so they line up at any zoom and in the final PDF.
* Recipients with the same order number receive the envelope together; the next group starts when they are all done.
* Every event is stored with the SHA-256 of the previous one (a hash chain). `verify` recomputes the chain and the
  document hashes, so any later change to the trail or the files is detected.
* When everyone has signed, the signatures are stamped into the PDF and a certificate page (people, times, IP
  addresses, identity checks, hashes) is added. The sealed PDF's SHA-256 is what /esign/verify/ looks up.

This is an audited electronic-signature workflow, not a qualified/PKI digital signature (see README).
"""
import base64
import hashlib
import io
import json
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_PAGES = 60
FIELD_SIZES = {'signature': (.26, .055), 'initials': (.09, .045), 'date_signed': (.16, .03), 'full_name': (.22, .03),
               'text': (.22, .03), 'checkbox': (.025, .018), 'choice': (.2, .03)}
COLORS = ['#0F7B78', '#4A5FC1', '#8A4A8F', '#E0912A', '#C8323F', '#2A5A78', '#16A34A', '#0891B2']


class EsignError(ValidationError):
    pass


# ------------------------------------------------------------------ PDFs
def inspect_pdf(data):
    """Return (pages, sizes) or raise EsignError with a plain message."""
    from pypdf import PdfReader
    if len(data) > MAX_PDF_BYTES:
        raise EsignError('The PDF is larger than 15 MB.')
    if not data.startswith(b'%PDF-'):
        raise EsignError('This file is not a PDF.')
    try:
        r = PdfReader(io.BytesIO(data))
        if r.is_encrypted:
            raise EsignError('The PDF is password-protected. Remove the password and upload it again.')
        sizes = []
        for p in r.pages:
            box = p.mediabox
            w, h = float(box.width), float(box.height)
            if (p.get('/Rotate') or 0) % 180:
                w, h = h, w
            sizes.append([round(w, 2), round(h, 2)])
    except EsignError:
        raise
    except Exception:
        raise EsignError('The PDF could not be read. Save it again as PDF and retry.')
    if not sizes:
        raise EsignError('The PDF has no pages.')
    if len(sizes) > MAX_PAGES:
        raise EsignError(f'The PDF has more than {MAX_PAGES} pages.')
    return len(sizes), sizes


def _styles():
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    ss = getSampleStyleSheet()
    return {'h1': ParagraphStyle('h1', parent=ss['Heading1'], fontName='Helvetica-Bold', fontSize=16, textColor='#0F2C3F', spaceAfter=4),
            'h2': ParagraphStyle('h2', parent=ss['Heading2'], fontName='Helvetica-Bold', fontSize=11.5, textColor='#0F2C3F', spaceBefore=10, spaceAfter=4),
            'p': ParagraphStyle('p', parent=ss['BodyText'], fontName='Helvetica', fontSize=10, leading=14),
            'small': ParagraphStyle('s', parent=ss['BodyText'], fontName='Helvetica', fontSize=8, leading=10, textColor='#5A6F7D'),
            'label': ParagraphStyle('l', parent=ss['BodyText'], fontName='Helvetica-Bold', fontSize=9, leading=12, textColor='#5A6F7D'),
            'value': ParagraphStyle('v', parent=ss['BodyText'], fontName='Helvetica', fontSize=10, leading=13)}


def _esc(s):
    return str(s if s is not None else '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _doc(title, story_fn, signers=()):
    """Build a PDF with an E-MedFlow header, the story and a final signature page with one block per signer.
    Returns (bytes, blocks) where blocks = [(signer_index, page, [x, y, w, h] as fractions)]."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
    W, H = A4
    S = _styles()
    buf = io.BytesIO()
    hospital = getattr(settings, 'HOSPITAL_NAME', 'E-MedFlow Hospital')

    def deco(c, doc):
        c.saveState()
        c.setFillColor('#0F2C3F'); c.rect(0, H - 14 * mm, W, 14 * mm, fill=1, stroke=0)
        c.setFillColor('#FFFFFF'); c.setFont('Helvetica-Bold', 10); c.drawString(18 * mm, H - 9 * mm, hospital)
        c.setFont('Helvetica', 8); c.drawRightString(W - 18 * mm, H - 9 * mm, title[:80])
        c.setFillColor('#5A6F7D'); c.drawRightString(W - 18 * mm, 10 * mm, f'Page {doc.page}')
        c.restoreState()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=24 * mm, bottomMargin=18 * mm, title=title)
    story = story_fn(S)
    blocks = []
    if signers:
        story += [PageBreak(), Paragraph('Signatures', S['h1']),
                  Paragraph('Each person signs in their own box. Signing electronically has the same meaning as signing by hand.', S['small']), Spacer(1, 6 * mm)]
    doc.build(story, onFirstPage=deco, onLaterPages=deco)
    pages = _page_count(buf.getvalue())
    if not signers:
        return buf.getvalue(), []
    # draw the signature blocks onto the last page
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas
    over = io.BytesIO()
    c = canvas.Canvas(over, pagesize=A4)
    top = H - 52 * mm
    for i, (name, relation) in enumerate(signers):
        y = top - i * 34 * mm
        if y < 30 * mm:
            break
        c.setStrokeColor('#C9D5CF'); c.setLineWidth(.8)
        c.line(20 * mm, y - 16 * mm, 110 * mm, y - 16 * mm)
        c.setFont('Helvetica-Bold', 9); c.setFillColor('#14293A'); c.drawString(20 * mm, y - 21 * mm, name[:60])
        c.setFont('Helvetica', 8); c.setFillColor('#5A6F7D'); c.drawString(20 * mm, y - 25 * mm, relation[:60] or 'Signer')
        c.drawString(120 * mm, y - 21 * mm, 'Date signed')
        c.line(120 * mm, y - 16 * mm, 175 * mm, y - 16 * mm)
        blocks.append((i, pages, [(20 * mm) / W, 1 - (y - 2 * mm) / H, (90 * mm) / W, (14 * mm) / H]))
        blocks.append((i, pages, [(120 * mm) / W, 1 - (y - 10 * mm) / H, (55 * mm) / W, (6 * mm) / H], 'date_signed'))
    c.save()
    base, ov = PdfReader(io.BytesIO(buf.getvalue())), PdfReader(io.BytesIO(over.getvalue()))
    out = PdfWriter()
    for n, p in enumerate(base.pages):
        if n == len(base.pages) - 1:
            p.merge_page(ov.pages[0])
        out.add_page(p)
    res = io.BytesIO(); out.write(res)
    return res.getvalue(), blocks


def _page_count(data):
    from pypdf import PdfReader
    return len(PdfReader(io.BytesIO(data)).pages)


def submission_pdf(sub, signers=()):
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, Spacer, Table, TableStyle
    from . import formkit as F
    schema = sub.schema_snapshot or {}
    p = sub.patient

    def story(S):
        st = [Paragraph(_esc(sub.definition.name), S['h1']),
              Paragraph(f'{_esc(p.full_name)} · {_esc(p.mrn)} · born {p.dob:%d %b %Y} · submitted {timezone.localtime(sub.created_at):%d %b %Y %H:%M} by {_esc(sub.submitted_by.get_full_name() or sub.submitted_by.username)}', S['small']),
              Spacer(1, 4 * mm)]
        rows = []
        hidden = F.evaluate_form(schema, sub.values or {}, previous=sub.values)[2] if schema.get('fields') else set()

        def flush():
            if rows:
                t = Table(rows, colWidths=[58 * mm, 116 * mm])
                t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LINEBELOW', (0, 0), (-1, -1), .3, '#DCE4E0'),
                                       ('BOTTOMPADDING', (0, 0), (-1, -1), 5), ('TOPPADDING', (0, 0), (-1, -1), 5)]))
                st.append(t); rows.clear()
        for f in schema.get('fields', []):
            if f['key'] in hidden:
                continue
            t = f['type']
            if t == 'heading':
                flush(); st.append(Paragraph(_esc(f['label']), S['h2'])); continue
            if t == 'paragraph':
                flush(); st.append(Paragraph(_esc(f.get('text', '')).replace('\n', '<br/>'), S['p'])); continue
            if t in ('divider', 'patient'):
                continue
            v = (sub.values or {}).get(f['key'])
            if t == 'signature' and isinstance(v, str) and v.startswith('data:image/png;base64,'):
                try:
                    img = Image(io.BytesIO(base64.b64decode(v.split(',', 1)[1])), width=50 * mm, height=16 * mm, kind='proportional')
                    rows.append([Paragraph(_esc(f['label']), S['label']), img]); continue
                except Exception:
                    pass
            if t == 'table' and v:
                flush()
                st.append(Paragraph(_esc(f['label']), S['label']))
                data = [[Paragraph(_esc(c['label']), S['label']) for c in f['columns']]] + [[Paragraph(_esc(F._text(r.get(c['key']))), S['value']) for c in f['columns']] for r in v]
                tt = Table(data, repeatRows=1)
                tt.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), .3, '#DCE4E0'), ('BACKGROUND', (0, 0), (-1, 0), '#F2F5F3')]))
                st += [tt, Spacer(1, 3 * mm)]
                continue
            rows.append([Paragraph(_esc(f['label']), S['label']), Paragraph(_esc(F.display_value(f, v)).replace('\n', '<br/>'), S['value'])])
        flush()
        if not schema.get('fields'):
            for k, v in (sub.values or {}).items():
                st.append(Paragraph(f'<b>{_esc(k)}</b>: {_esc(v)}', S['p']))
        return st
    return _doc(sub.definition.name, story, signers)


MERGE = {'{patient.name}': lambda p: p.full_name, '{patient.mrn}': lambda p: p.mrn,
         '{patient.dob}': lambda p: p.dob.strftime('%d %b %Y') if p.dob else '', '{patient.age}': lambda p: str(p.age or ''),
         '{today}': lambda p: timezone.localdate().strftime('%d %B %Y')}


def letter_pdf(title, body, patient=None, signers=()):
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.units import mm
    text = body
    for k, fn in MERGE.items():
        text = text.replace(k, fn(patient) if patient else '')

    def story(S):
        st = [Paragraph(_esc(title), S['h1']), Spacer(1, 3 * mm)]
        for para in text.split('\n\n'):
            if para.strip():
                st.append(Paragraph(_esc(para.strip()).replace('\n', '<br/>'), S['p'])); st.append(Spacer(1, 2 * mm))
        return st
    return _doc(title, story, signers)


# ------------------------------------------------------------------ audit hash chain
def _canon(ev):
    return json.dumps({'envelope': str(ev.envelope.uid), 'action': ev.action, 'at': ev.at.isoformat(), 'actor': ev.actor_id,
                       'recipient': ev.recipient_id, 'ip': ev.ip_address or '', 'details': ev.details}, sort_keys=True, separators=(',', ':'))


def log(env, action, *, actor=None, recipient=None, request=None, **details):
    from .models import EnvelopeEvent
    prev = EnvelopeEvent.objects.filter(envelope=env).order_by('-at', '-pk').values_list('hash', flat=True).first() or ''
    ip = (request.META.get('REMOTE_ADDR') if request else None) or None
    ua = (request.META.get('HTTP_USER_AGENT', '')[:300] if request else '')
    ev = EnvelopeEvent(envelope=env, action=action, actor=actor if actor and actor.is_authenticated else None, recipient=recipient,
                       ip_address=ip, user_agent=ua, details=details, prev_hash=prev, at=timezone.now())
    ev.hash = hashlib.sha256((prev + _canon(ev)).encode()).hexdigest()
    ev.save()
    return ev


def _file_sha(f):
    if not f:
        return ''
    f.open('rb')
    try:
        return hashlib.sha256(f.read()).hexdigest()
    finally:
        f.close()


def verify(env):
    """(ok, problems): recompute the event chain and the document hashes."""
    problems, prev = [], ''
    for ev in env.events.order_by('at', 'pk'):
        if ev.prev_hash != prev:
            problems.append(f'Event “{ev.action}” at {timezone.localtime(ev.at):%d %b %H:%M} does not follow the one before it.')
        if hashlib.sha256((ev.prev_hash + _canon(ev)).encode()).hexdigest() != ev.hash:
            problems.append(f'Event “{ev.action}” at {timezone.localtime(ev.at):%d %b %H:%M} was changed after it was recorded.')
        prev = ev.hash
    if _file_sha(env.document) != env.document_sha256:
        problems.append('The original document no longer matches its recorded fingerprint.')
    if env.signed_document and _file_sha(env.signed_document) != env.signed_sha256:
        problems.append('The signed document no longer matches its recorded fingerprint.')
    return not problems, problems


# ------------------------------------------------------------------ creating
@transaction.atomic
def create_envelope(*, user, subject, message='', source='upload', pdf_bytes, name='document.pdf', patient=None, submission=None,
                    recipients=(), expires_days=14, require_full_read=False, request=None, run=None, node_id=''):
    from .models import Envelope, EnvelopeRecipient
    pages, sizes = inspect_pdf(pdf_bytes)
    env = Envelope(subject=subject[:200], message=message[:2000], source=source, created_by=user, patient=patient, submission=submission,
                   document_name=name[:200], document_sha256=hashlib.sha256(pdf_bytes).hexdigest(), pages=pages, page_sizes=sizes,
                   require_full_read=require_full_read, run=run, node_id=node_id,
                   expires_at=timezone.now() + timedelta(days=max(1, min(90, expires_days))) if expires_days else None)
    env.document.save(f'{env.uid.hex}.pdf', ContentFile(pdf_bytes), save=False)
    env.save()
    for i, r in enumerate(recipients):
        add_recipient(env, r, i)
    log(env, 'created', actor=user, request=request, source=source, document_sha256=env.document_sha256, pages=pages)
    return env


def add_recipient(env, r, i=None):
    from .models import EnvelopeRecipient
    role = r.get('role') if r.get('role') in dict(EnvelopeRecipient.ROLE) else 'signer'
    name = str(r.get('name') or '').strip()[:160]
    user = r.get('user')
    if user is not None and not name:
        name = user.get_full_name() or user.username
    if not name:
        raise EsignError('Every recipient needs a name.')
    email = str(r.get('email') or (user.email if user else '') or '').strip()[:200]
    if role in ('signer', 'approver', 'cc') and not user and not email:
        raise EsignError(f'{name}: add an email address or choose a staff member, so they can be reached.')
    code = str(r.get('access_code') or '').strip()
    rec = EnvelopeRecipient.objects.create(
        envelope=env, name=name, email=email, user=user, role=role, relation=str(r.get('relation') or '')[:80],
        order=max(1, min(20, int(r.get('order') or 1))), color=COLORS[(i if i is not None else env.recipients.count()) % len(COLORS)],
        access_code_hash=make_password(code) if code else '', host=r.get('host'))
    return rec


def auto_place(env, blocks=None):
    """Put a signature and date field for each recipient who signs; uses the form's signature blocks if given."""
    from .models import EnvelopeField
    signers = [r for r in env.recipients.order_by('pk') if r.needs_fields]       # creation order = order of the PDF's blocks
    if blocks:
        for b in blocks:
            idx, page, (x, y, w, h) = b[0], b[1], b[2]
            if idx < len(signers):
                EnvelopeField.objects.create(envelope=env, recipient=signers[idx], kind=b[3] if len(b) > 3 else 'signature', page=page, x=x, y=y, w=w, h=h)
        return
    last = env.pages
    for i, r in enumerate(signers):
        y = min(.9, .62 + i * .085)
        EnvelopeField.objects.create(envelope=env, recipient=r, kind='signature', page=last, x=.08, y=y, w=.3, h=.055)
        EnvelopeField.objects.create(envelope=env, recipient=r, kind='full_name', page=last, x=.42, y=y + .02, w=.25, h=.03)
        EnvelopeField.objects.create(envelope=env, recipient=r, kind='date_signed', page=last, x=.7, y=y + .02, w=.2, h=.03)


def save_fields(env, items):
    """Replace all fields from the prepare screen. Each item: {recipient, kind, page, x, y, w, h, required, label, options}."""
    from .models import EnvelopeField
    if env.status != 'draft':
        raise EsignError('Fields can only be changed before the envelope is sent.')
    recips = {r.pk: r for r in env.recipients.all()}
    clean = []
    for it in (items or [])[:300]:
        try:
            rid, page = int(it.get('recipient')), int(it.get('page'))
            x, y, w, h = (float(it.get(k)) for k in ('x', 'y', 'w', 'h'))
        except (TypeError, ValueError, AttributeError):
            raise EsignError('A field has invalid position data.')
        kind = it.get('kind')
        if rid not in recips or kind not in dict(EnvelopeField.KIND) or not 1 <= page <= env.pages:
            raise EsignError('A field belongs to an unknown recipient, kind or page.')
        if not recips[rid].needs_fields:
            raise EsignError(f'{recips[rid].name} only receives a copy or approves, so they cannot have fields.')
        w, h = max(.01, min(1, w)), max(.008, min(1, h))
        x, y = max(0, min(1 - w, x)), max(0, min(1 - h, y))
        opts = [str(o)[:60] for o in (it.get('options') or []) if str(o).strip()][:20] if kind == 'choice' else []
        if kind == 'choice' and len(opts) < 2:
            raise EsignError('A “choose one” field needs at least two options.')
        clean.append(EnvelopeField(envelope=env, recipient=recips[rid], kind=kind, page=page, x=x, y=y, w=w, h=h,
                                   required=bool(it.get('required', kind != 'checkbox')),
                                   label=str(it.get('label') or '')[:120], options=opts))
    EnvelopeField.objects.filter(envelope=env).delete()
    EnvelopeField.objects.bulk_create(clean)
    return len(clean)


# ------------------------------------------------------------------ routing
def current_order(env):
    pending = [r.order for r in env.recipients.all() if not r.done and r.status != 'declined']
    return min(pending) if pending else None


def _activate(env, request=None):
    """Send to the next routing group; complete the envelope when nobody is left."""
    from .notify import notify
    while True:
        order = current_order(env)
        if order is None:
            return _complete(env, request)
        group = [r for r in env.recipients.all() if r.order == order and r.status == 'waiting']
        now = timezone.now()
        for r in group:
            if r.role == 'cc':
                r.status, r.sent_at, r.acted_at = 'copied', now, now
                r.save(update_fields=['status', 'sent_at', 'acted_at'])
                log(env, 'copy_sent', recipient=r, request=request, name=r.name)
                continue
            r.status, r.sent_at = 'sent', now
            r.save(update_fields=['status', 'sent_at'])
            log(env, 'sent_to', recipient=r, request=request, name=r.name, role=r.role, order=order)
            if r.role == 'in_person':
                host = r.host or env.created_by
                notify([host], f'Ready to sign in person: {env.subject}', f'Hand the device to {r.name}.', f'/esign/{env.uid}/', kind='esign')
            elif r.user:
                notify([r.user], f'Please {"approve" if r.role == "approver" else "sign"}: {env.subject}', env.message[:300], f'/esign/sign/{r.token}/', kind='esign')
            elif r.email:
                _email_link(env, r)
        if any(r.status == 'sent' for r in env.recipients.filter(order=order)):
            return env
        # the whole group was copies only: move on


def _email_link(env, r):
    from django.core.mail import send_mail
    link = settings.SITE_URL.rstrip('/') + f'/esign/sign/{r.token}/'
    try:
        send_mail(f'Please sign: {env.subject}',
                  f'{env.created_by.get_full_name() or env.created_by.username} has sent you a document to sign through E-MedFlow.\n\n'
                  f'{env.message}\n\nOpen it here: {link}\n\nIf you were given an access code, you will need it to open the document.',
                  settings.DEFAULT_FROM_EMAIL, [r.email], fail_silently=True)
    except Exception:
        pass


@transaction.atomic
def send(env, user, request=None):
    from .models import Envelope
    env = Envelope.objects.select_for_update().get(pk=env.pk)
    if env.status != 'draft':
        raise EsignError('This envelope has already been sent.')
    recips = list(env.recipients.all())
    if not any(r.role != 'cc' for r in recips):
        raise EsignError('Add at least one person who signs or approves.')
    for r in recips:
        if r.needs_fields and not r.fields.filter(kind__in=['signature', 'initials']).exists():
            raise EsignError(f'{r.name} has no signature field. Place one on the document.')
    env.status, env.sent_at = 'sent', timezone.now()
    env.save(update_fields=['status', 'sent_at', 'updated_at'])
    log(env, 'sent', actor=user, request=request, recipients=[{'name': r.name, 'role': r.role, 'order': r.order} for r in recips])
    _activate(env, request)
    return env


def can_open(rec, user, session):
    """May this browser open the signing page for this recipient?"""
    if rec.role == 'in_person':
        host = rec.host_id or rec.envelope.created_by_id
        return user.is_authenticated and (user.pk == host or user.is_superuser), 'in_person'
    if rec.user_id:
        return user.is_authenticated and user.pk == rec.user_id, 'login'
    if rec.access_code_hash and not session.get(f'esign_ok_{rec.pk}'):
        return False, 'code'
    return True, ''


def check_access_code(rec, code, session):
    key = f'esign_tries_{rec.pk}'
    tries = session.get(key, 0)
    if tries >= 5:
        raise EsignError('Too many wrong codes. Ask the sender for a new link.')
    if check_password(code or '', rec.access_code_hash):
        session[f'esign_ok_{rec.pk}'] = True
        log(rec.envelope, 'access_code_ok', recipient=rec)
        return True
    session[key] = tries + 1
    log(rec.envelope, 'access_code_wrong', recipient=rec)
    return False


def mark_viewed(rec, request, pages=None):
    if rec.status == 'sent':
        rec.status, rec.viewed_at = 'viewed', timezone.now()
        rec.save(update_fields=['status', 'viewed_at'])
        log(rec.envelope, 'viewed', recipient=rec, request=request, name=rec.name)
    if pages:
        seen = sorted(set(rec.pages_seen or []) | {int(p) for p in pages if str(p).isdigit() and 1 <= int(p) <= rec.envelope.pages})
        if seen != rec.pages_seen:
            rec.pages_seen = seen
            rec.save(update_fields=['pages_seen'])


def _png(data, limit=400_000):
    if not isinstance(data, str) or not data.startswith('data:image/png;base64,') or len(data) > limit:
        return None
    try:
        raw = base64.b64decode(data.split(',', 1)[1], validate=True)
    except Exception:
        return None
    return data if raw[:8] == b'\x89PNG\r\n\x1a\n' else None


@transaction.atomic
def sign(rec, request, *, values, signature=None, initials=None, identity_check='', consent=False, actor=None):
    """Record a recipient's signature and field values. `values` maps field id → value."""
    from .models import EnvelopeRecipient, SignatureProfile
    rec = EnvelopeRecipient.objects.select_for_update().select_related('envelope').get(pk=rec.pk)
    env = rec.envelope
    _check_open(env, rec)
    if not consent:
        raise EsignError('Tick the box to agree to sign electronically.')
    if rec.role == 'approver':
        raise EsignError('This person approves; use Approve.')
    if env.require_full_read and len(set(rec.pages_seen or [])) < env.pages:
        raise EsignError(f'Read every page before signing ({len(set(rec.pages_seen or []))} of {env.pages} viewed).')
    if rec.role == 'in_person' and len(identity_check.strip()) < 4:
        raise EsignError('Record how you confirmed who is signing (for example: name and date of birth checked).')
    sig, ini = _png(signature), _png(initials)
    fields = list(rec.fields.all())
    if any(f.kind == 'signature' for f in fields) and not sig:
        raise EsignError('Adopt a signature first.')
    if any(f.kind == 'initials' for f in fields) and not ini:
        raise EsignError('Adopt your initials first.')
    now = timezone.now()
    for f in fields:
        v = values.get(str(f.pk))
        if f.kind == 'signature':
            v = 'signed'
        elif f.kind == 'initials':
            v = 'initialled'
        elif f.kind == 'date_signed':
            v = timezone.localtime(now).strftime('%d %b %Y')
        elif f.kind == 'full_name':
            v = rec.name
        elif f.kind == 'checkbox':
            v = 'yes' if v in (True, 'yes', 'true', 'on', 1) else ''
        elif f.kind == 'choice':
            v = str(v or '') if str(v or '') in f.options else ''
        else:
            v = str(v or '').strip()[:500]
        if f.required and not v:
            raise EsignError(f'Complete every required field ({f.get_kind_display()}{": " + f.label if f.label else ""}, page {f.page}).')
        f.value, f.filled_at = v, now
        f.save(update_fields=['value', 'filled_at'])
    rec.status, rec.acted_at = 'signed', now
    rec.signature_image, rec.initials_image = sig or '', ini or ''
    rec.identity_check = identity_check.strip()[:200]
    rec.ip_address = request.META.get('REMOTE_ADDR') if request else None
    rec.user_agent = request.META.get('HTTP_USER_AGENT', '')[:300] if request else ''
    rec.save()
    if rec.user_id and sig and actor and actor.pk == rec.user_id:
        SignatureProfile.objects.update_or_create(user=actor, defaults={'signature': sig, 'initials': ini or ''})
    log(env, 'signed', recipient=rec, request=request, actor=actor, name=rec.name, role=rec.role,
        signature_sha256=hashlib.sha256(sig.encode()).hexdigest() if sig else '', identity_check=rec.identity_check,
        host=(actor.get_full_name() or actor.username) if rec.role == 'in_person' and actor else '')
    _activate(env, request)
    return rec


def _check_open(env, rec):
    if env.status != 'sent':
        raise EsignError({'completed': 'This envelope is already complete.', 'declined': 'This envelope was declined.',
                          'voided': 'The sender cancelled this envelope.', 'expired': 'This envelope has expired.',
                          'draft': 'This envelope has not been sent yet.'}[env.status])
    if env.expires_at and env.expires_at < timezone.now():
        expire(env); raise EsignError('This envelope has expired.')
    if rec.status not in ('sent', 'viewed'):
        raise EsignError('It is not your turn yet.' if rec.status == 'waiting' else 'You have already acted on this envelope.')


@transaction.atomic
def approve(rec, request, actor=None):
    from .models import EnvelopeRecipient
    rec = EnvelopeRecipient.objects.select_for_update().select_related('envelope').get(pk=rec.pk)
    _check_open(rec.envelope, rec)
    if rec.role != 'approver':
        raise EsignError('This person needs to sign, not approve.')
    rec.status, rec.acted_at = 'approved', timezone.now()
    rec.ip_address = request.META.get('REMOTE_ADDR') if request else None
    rec.save()
    log(rec.envelope, 'approved', recipient=rec, request=request, actor=actor, name=rec.name)
    _activate(rec.envelope, request)
    return rec


@transaction.atomic
def decline(rec, request, reason, actor=None):
    from .models import EnvelopeRecipient
    from .notify import notify
    rec = EnvelopeRecipient.objects.select_for_update().select_related('envelope').get(pk=rec.pk)
    env = rec.envelope
    _check_open(env, rec)
    if len(reason.strip()) < 3:
        raise EsignError('Say why you are declining, so the sender can fix it.')
    rec.status, rec.acted_at, rec.decline_reason = 'declined', timezone.now(), reason.strip()[:400]
    rec.save()
    env.status = 'declined'
    env.save(update_fields=['status', 'updated_at'])
    log(env, 'declined', recipient=rec, request=request, actor=actor, name=rec.name, reason=rec.decline_reason)
    notify([env.created_by], f'Declined: {env.subject}', f'{rec.name}: {rec.decline_reason}', f'/esign/{env.uid}/', kind='esign')
    transaction.on_commit(lambda: _flow_hook(env.pk))
    return rec


def void(env, user, reason, request=None):
    if env.status not in ('draft', 'sent'):
        return env
    env.status, env.void_reason = 'voided', reason[:300]
    env.save(update_fields=['status', 'void_reason', 'updated_at'])
    log(env, 'voided', actor=user, request=request, reason=reason[:300])
    return env


def expire(env):
    if env.status == 'sent':
        env.status = 'expired'
        env.save(update_fields=['status', 'updated_at'])
        log(env, 'expired')
        transaction.on_commit(lambda: _flow_hook(env.pk))


def remind(env, user=None, request=None):
    from .notify import notify
    n = 0
    for r in env.recipients.filter(status__in=['sent', 'viewed']):
        if r.user:
            notify([r.user], f'Reminder: please sign {env.subject}', '', f'/esign/sign/{r.token}/', kind='esign')
        elif r.email:
            _email_link(env, r)
        r.last_reminded_at = timezone.now()
        r.save(update_fields=['last_reminded_at'])
        n += 1
    if n:
        log(env, 'reminded', actor=user, request=request, count=n)
    return n


def sweep(now=None):
    """Expire overdue envelopes and send automatic reminders."""
    from .models import Envelope
    now = now or timezone.now()
    for env in Envelope.objects.filter(status='sent', expires_at__lt=now):
        expire(env)
    for env in Envelope.objects.filter(status='sent', remind_every_hours__gt=0):
        due = [r for r in env.recipients.filter(status__in=['sent', 'viewed']) if (r.last_reminded_at or r.sent_at or now) < now - timedelta(hours=env.remind_every_hours)]
        if due:
            remind(env)


def _complete(env, request=None):
    from .notify import notify
    data = stamp(env)
    env.signed_document.save(f'{env.uid.hex}-signed.pdf', ContentFile(data), save=False)
    env.signed_sha256 = hashlib.sha256(data).hexdigest()
    env.status, env.completed_at = 'completed', timezone.now()
    env.save()
    log(env, 'completed', request=request, signed_sha256=env.signed_sha256)
    people = [env.created_by] + [r.user for r in env.recipients.all() if r.user]
    notify(people, f'Completed: {env.subject}', 'Everyone has signed. The sealed document is ready.', f'/esign/{env.uid}/', kind='esign')
    for r in env.recipients.filter(user__isnull=True).exclude(email=''):
        try:
            from django.core.mail import send_mail
            send_mail(f'Completed: {env.subject}', f'Everyone has signed. Your copy: {settings.SITE_URL.rstrip("/")}/esign/sign/{r.token}/',
                      settings.DEFAULT_FROM_EMAIL, [r.email], fail_silently=True)
        except Exception:
            pass
    transaction.on_commit(lambda: _flow_hook(env.pk))
    return env


def _flow_hook(pk):
    from .models import Envelope
    from . import flows
    env = Envelope.objects.get(pk=pk)
    if env.run_id:
        flows.on_envelope(env)


# ------------------------------------------------------------------ sealing
def stamp(env):
    """Original PDF + values and signature images drawn in place + certificate pages."""
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    env.document.open('rb')
    try:
        reader = PdfReader(io.BytesIO(env.document.read()))
    finally:
        env.document.close()
    fields = list(env.fields.select_related('recipient'))
    writer = PdfWriter()
    for n, page in enumerate(reader.pages, 1):
        w, h = env.page_sizes[n - 1] if n - 1 < len(env.page_sizes) else (float(page.mediabox.width), float(page.mediabox.height))
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(w, h))
        for f in [f for f in fields if f.page == n]:
            x, y, fw, fh = f.x * w, h - (f.y + f.h) * h, f.w * w, f.h * h
            r = f.recipient
            img = r.signature_image if f.kind == 'signature' else r.initials_image if f.kind == 'initials' else ''
            if img and f.value:
                try:
                    c.drawImage(ImageReader(io.BytesIO(base64.b64decode(img.split(',', 1)[1]))), x, y, fw, fh, mask='auto', preserveAspectRatio=True, anchor='sw')
                    c.setFont('Helvetica', 5); c.setFillColor('#0B5F5D')
                    c.drawString(x, y + fh + 2, f'Signed by {r.name[:40]} · {env.short_id}')   # above the box, clear of the printed name
                except Exception:
                    pass
            elif f.kind == 'checkbox':
                c.setStrokeColor('#14293A'); c.rect(x, y, min(fw, fh), min(fw, fh))
                if f.value:
                    c.setFont('ZapfDingbats', min(fw, fh) * .9); c.drawString(x + 1, y + 1, '4')
            elif f.value:
                size = max(6, min(11, fh * .7))
                c.setFont('Helvetica', size); c.setFillColor('#14293A'); c.drawString(x + 2, y + (fh - size) / 2 + 1, f.value[:120])
        c.setFont('Helvetica', 6); c.setFillColor('#5A6F7D')
        c.drawString(18, 10, f'E-MedFlow e-sign · envelope {env.short_id} · page {n} of {len(reader.pages)} · verify at {settings.SITE_URL.rstrip("/")}/esign/verify/')
        c.save()
        page.merge_page(PdfReader(io.BytesIO(buf.getvalue())).pages[0])
        writer.add_page(page)
    for p in PdfReader(io.BytesIO(certificate(env))).pages:
        writer.add_page(p)
    writer.add_metadata({'/Title': env.subject, '/Producer': 'E-MedFlow e-sign', '/EnvelopeId': str(env.uid)})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def certificate(env):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    S = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm)
    when = lambda d: timezone.localtime(d).strftime('%d %b %Y %H:%M:%S %Z') if d else '—'
    st = [Paragraph('Certificate of completion', S['h1']),
          Paragraph(f'Envelope {env.uid} · “{_esc(env.subject)}” · {env.pages} page(s) · sent by {_esc(env.created_by.get_full_name() or env.created_by.username)} on {when(env.sent_at)}', S['small']),
          Paragraph(f'Original document SHA-256: {env.document_sha256}', S['small']), Spacer(1, 4 * mm), Paragraph('Recipients', S['h2'])]
    rows = [['Name', 'Role', 'Sent', 'Opened', 'Completed', 'Signature']]
    for r in env.recipients.all():
        sig = ''
        if r.signature_image:
            try:
                sig = Image(io.BytesIO(base64.b64decode(r.signature_image.split(',', 1)[1])), width=30 * mm, height=10 * mm, kind='proportional')
            except Exception:
                sig = ''
        extra = f'<br/><font size="7">{_esc(r.relation)}</font>' if r.relation else ''
        extra += f'<br/><font size="7">ID: {_esc(r.identity_check)}</font>' if r.identity_check else ''
        extra += f'<br/><font size="7">IP {r.ip_address}</font>' if r.ip_address else ''
        cell = lambda d: Paragraph(timezone.localtime(d).strftime('%d %b %Y<br/>%H:%M:%S %Z') if d else '—', S['small'])
        rows.append([Paragraph(_esc(r.name) + extra, S['value']), Paragraph(_esc(r.get_role_display()), S['small']), cell(r.sent_at), cell(r.viewed_at), cell(r.acted_at), sig])
    t = Table(rows, colWidths=[44 * mm, 28 * mm, 26 * mm, 26 * mm, 26 * mm, 32 * mm], repeatRows=1)
    t.setStyle(TableStyle([('FONT', (0, 0), (-1, -1), 'Helvetica', 7.5), ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 7.5),
                           ('GRID', (0, 0), (-1, -1), .3, '#DCE4E0'), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BACKGROUND', (0, 0), (-1, 0), '#F2F5F3')]))
    st += [t, Paragraph('Audit trail (each line is chained to the previous one with SHA-256)', S['h2'])]
    ev_rows = [['Time', 'Event', 'By', 'Hash']]
    for ev in env.events.select_related('recipient', 'actor').order_by('at', 'pk'):
        who = ev.recipient.name if ev.recipient else (ev.actor.get_full_name() or ev.actor.username) if ev.actor else 'System'
        ev_rows.append([when(ev.at), ev.action.replace('_', ' '), who[:40], ev.hash[:20] + '…'])
    t2 = Table(ev_rows, colWidths=[42 * mm, 34 * mm, 50 * mm, 56 * mm], repeatRows=1)
    t2.setStyle(TableStyle([('FONT', (0, 0), (-1, -1), 'Helvetica', 7), ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 7),
                            ('LINEBELOW', (0, 0), (-1, -1), .3, '#DCE4E0')]))
    st += [t2, Spacer(1, 4 * mm),
           Paragraph('This is an audited electronic signature record produced by E-MedFlow. Each signer was identified by their '
                     'staff login, a private link (with access code where set) or, for in-person signing, by the staff host who '
                     'recorded the identity check above. Check this document has not been changed at the verify page.', S['small'])]
    doc.build(st)
    return buf.getvalue()


# ------------------------------------------------------------------ flows
def envelope_for_flow(run, node):
    """Signature step: render the submission, create the envelope with the configured signers, place fields, send."""
    from . import flows
    from .models import WorkflowTask
    cfg = node['config']
    sub = run.submission
    recips, seen = [], set()
    for s in cfg.get('signers', []):
        src = s['source']
        if src == 'patient':
            recips.append({'name': sub.patient.full_name, 'role': 'in_person', 'relation': 'Patient', 'order': s['order'], 'host': run.started_by or sub.submitted_by})
            continue
        if src == 'role':
            users = flows.users_with_role(s.get('role', 'doctor'))
            u = users[0] if users else None
        else:
            u = (run.started_by or sub.submitted_by) if src == 'initiator' else (sub.encounter.clinician if sub.encounter and sub.encounter.clinician_id else sub.submitted_by)
        if u and (u.pk, s['as']) not in seen:
            seen.add((u.pk, s['as']))
            recips.append({'user': u, 'role': 'witness' if s['as'] == 'witness' else 'approver' if s['as'] == 'approver' else 'signer', 'order': s['order'],
                           'relation': {'initiator': 'Started the form', 'clinician': 'Clinician', 'role': (s.get('role') or '').title()}[src]})
    signers = [(r.get('name') or (r['user'].get_full_name() or r['user'].username), r.get('relation', '')) for r in recips if r['role'] != 'approver']
    data, blocks = submission_pdf(sub, signers)
    env = create_envelope(user=run.started_by or sub.submitted_by, subject=f'{run.definition.name} · {sub.patient.full_name}', source='form',
                          pdf_bytes=data, name=f'{sub.definition.slug}.pdf', patient=sub.patient, submission=sub, recipients=recips,
                          require_full_read=cfg.get('require_full_read', False), run=run, node_id=node['id'])
    auto_place(env, blocks)
    for r in env.recipients.all():
        WorkflowTask.objects.create(run=run, node_id=node['id'], kind='signature', label=node['label'], user=r.user or r.host,
                                    round=run.round, envelope=env)
    send(env, run.started_by or sub.submitted_by)
    return env
