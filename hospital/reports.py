"""Doctor's reports: adopt an AI summary as a draft, measure the doctor's edits, sign with a content hash, and export
as one PDF (results, images and attached PDFs merged in) or a ZIP with every original file and a manifest."""
import csv
import difflib
import hashlib
import io
import json
import os
import re
import zipfile

from django.conf import settings
from django.utils import timezone

ATTACH_TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.pdf': 'application/pdf'}
ATTACH_MAX_BYTES = 15 * 1024 * 1024
ATTACH_MAX_COUNT = 20

# AI headings (medical_ai.SYSTEM_PROMPT) → the sections of a doctor's report
SECTION_NAMES = {
    'summary': 'Clinical summary', 'urgent / red flags': 'Red flags', 'suggested next steps': 'Plan',
    'differential considerations': 'Differential diagnosis', 'hospital range vs who reference': 'Reference ranges',
    'gaps and uncertainties': 'Outstanding questions',
}


# ------------------------------------------------------------------ adopting and editing
def ai_to_report(text):
    """Turn the AI's answer into a report draft: the same content under report headings, citations kept."""
    out = []
    for line in (text or '').splitlines():
        m = re.match(r'^\s*#{1,4}\s+(.*?)\s*$', line)
        if m:
            name = SECTION_NAMES.get(m.group(1).strip().lower().rstrip(':'), m.group(1).strip())
            out.append(f'## {name}')
        else:
            out.append(line.rstrip())
    body = re.sub(r'\n{3,}', '\n\n', '\n'.join(out)).strip()
    return body + '\n\n## Doctor\'s assessment\n(Add your examination findings and final impression here.)\n'


def adopt(suggestion, user):
    """Start a draft report from an AI suggestion, or return the open draft for that lab request."""
    from .models import DoctorReport
    lr = suggestion.lab_request
    draft = DoctorReport.objects.filter(lab_request=lr, status='draft').first()
    if draft:
        return draft, False
    body = ai_to_report(suggestion.text)
    r = DoctorReport(encounter=suggestion.encounter, lab_request=lr, source_suggestion=suggestion, body=body, ai_draft=body,
                     created_by=user, edited_by=user, title=f"Doctor's report · {lr.number}" if lr else "Doctor's report",
                     include={'labs': True, 'images': [i.pk for i in encounter_images(suggestion.encounter)], 'attachments': [],
                              'ai_sources': True})
    r.log(user, 'adopted AI summary', suggestion=suggestion.pk)
    r.save()
    return r, True


def replace_with_suggestion(report, suggestion, user):
    report.body = report.ai_draft = ai_to_report(suggestion.text)
    report.source_suggestion = suggestion
    report.edited_by = user
    report.log(user, 'replaced draft with newer AI summary', suggestion=suggestion.pk)
    report.save()


def amend(report, user, reason):
    """A signed report never changes: an amendment is a new draft that will supersede it when signed."""
    from .models import DoctorReport
    open_one = report.amendments.filter(status='draft').first()
    if open_one:
        return open_one
    new = DoctorReport(encounter=report.encounter, lab_request=report.lab_request, source_suggestion=report.source_suggestion,
                       amends=report, title=report.title, body=report.body, ai_draft=report.ai_draft, follow_up=report.follow_up,
                       include=dict(report.include or {}), created_by=user, edited_by=user, amend_reason=reason[:300])
    new.log(user, 'started amendment', amends=report.number, reason=reason[:300])
    new.save()
    return new


def edited_pct(report):
    """How much of the AI draft the doctor changed (0–100), for the AI-assistance disclosure."""
    if not report.ai_draft:
        return 100
    return round((1 - difflib.SequenceMatcher(None, report.ai_draft, report.body or '', autojunk=False).ratio()) * 100)


def encounter_images(encounter):
    from .models import ImagingImage
    return list(ImagingImage.objects.filter(order__encounter=encounter).exclude(order__status='cancelled')
                .select_related('order').order_by('order_id', 'id'))


def selected_images(report):
    ids = set((report.include or {}).get('images') or [])
    return [i for i in encounter_images(report.encounter) if i.pk in ids]


def selected_attachments(report):
    ids = set((report.include or {}).get('attachments') or [])
    return [a for a in report.attachments.all() if a.pk in ids]


def lab_rows(report):
    if not report.lab_request_id or not (report.include or {}).get('labs', True):
        return []
    return request_rows(report.lab_request, report.encounter.patient.sex)


def request_rows(lr, sex):
    rows = []
    for o in lr.orders.all():
        if o.status not in ('resulted', 'verified'):
            continue
        for v in o.values.all():
            rows.append({'test': o.test.name, 'parameter': v.parameter.name, 'value': v.display, 'unit': v.parameter.unit,
                         'range': _range(v.parameter, sex), 'flag': v.flag, 'flag_label': v.get_flag_display() if v.flag else '',
                         'verified': o.status == 'verified'})
    return rows


def _range(param, sex):
    try:
        return param.range_label(sex) or ''
    except Exception:
        return ''


def _file_sha(f):
    h = hashlib.sha256()
    try:
        with f.open('rb') as fh:
            for chunk in iter(lambda: fh.read(65536), b''):
                h.update(chunk)
    except (FileNotFoundError, ValueError, OSError):
        return 'missing'
    return h.hexdigest()


def canonical(report):
    """Everything the signature covers: text, results, and the exact bytes of every included file."""
    return {
        'number': report.number, 'title': report.title, 'body': report.body, 'follow_up': str(report.follow_up or ''),
        'patient': report.encounter.patient.mrn,
        'labs': [[r['test'], r['parameter'], r['value'], r['unit'], r['flag']] for r in lab_rows(report)],
        'images': [[i.pk, _file_sha(i.file)] for i in selected_images(report)],
        'attachments': [[a.pk, _file_sha(a.file)] for a in selected_attachments(report)],
    }


def content_hash(report):
    return hashlib.sha256(json.dumps(canonical(report), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def sign(report, user):
    report.status, report.signed_by, report.signed_at, report.edited_by = 'final', user, timezone.now(), user
    report.content_hash = content_hash(report)
    report.log(user, 'signed', hash=report.content_hash[:16], edited_pct=edited_pct(report))
    report.save()
    if report.amends_id and report.amends.status == 'final':
        old = report.amends
        old.status = 'superseded'
        old.log(user, 'superseded', by=report.number)
        old.save(update_fields=['status', 'history', 'updated_at'])


# ------------------------------------------------------------------ markdown → PDF
def _esc(s):
    return str(s if s is not None else '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _inline_pdf(s):
    s = _pdf_text(s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])', r'<i>\1</i>', s)
    return re.sub(r'\[([^\]]+)\]\((https://[^)\s]+)\)', r'<link href="\2" color="#0B5F5D">\1</link>', s)


SUPERSCRIPTS = str.maketrans('⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺', '0123456789-+')


def _pdf_text(s):
    """Escape for a reportlab Paragraph; superscript digits (×10⁹/L) become <super> so the built-in fonts can draw them."""
    return re.sub(r'[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+', lambda m: f'<super>{m.group(0).translate(SUPERSCRIPTS)}</super>', _esc(s))


def md_flowables(text, S):
    from reportlab.platypus import ListFlowable, ListItem, Paragraph
    out, items, kind = [], [], None

    def flush():
        nonlocal items, kind
        if items:
            out.append(ListFlowable([ListItem(Paragraph(t, S['p']), leftIndent=12) for t in items],
                                    bulletType='1' if kind == 'ol' else 'bullet', start='1' if kind == 'ol' else None,
                                    leftIndent=14, bulletFontSize=9))
        items, kind = [], None
    for raw in (text or '').splitlines():
        line = raw.strip()
        h = re.match(r'^#{1,4}\s+(.*)', line)
        ol = re.match(r'^(\d+)[.)]\s+(.*)', line)
        ul = re.match(r'^[-*•]\s+(.*)', line)
        if ul and kind == 'ol' and raw[:1] in (' ', '\t') and items:
            items[-1] += f'<br/><font color="#5A6F7D" size="8.5">{_inline_pdf(ul.group(1))}</font>'
            continue
        k = 'ol' if ol else 'ul' if ul else None
        if kind and k != kind and line:
            flush()
        if h:
            out.append(Paragraph(_inline_pdf(h.group(1)), S['h2']))
        elif k:
            kind = k
            items.append(_inline_pdf(ol.group(2) if ol else ul.group(1)))
        elif line:
            out.append(Paragraph(_inline_pdf(line), S['p']))
    flush()
    return out


def _image_flowable(fileobj, max_w, max_h):
    from PIL import Image as PILImage
    from reportlab.platypus import Image
    with fileobj.open('rb') as fh:
        im = PILImage.open(fh)
        im.load()
    if im.mode not in ('RGB', 'L'):
        im = im.convert('RGB')
    im.thumbnail((1800, 1800))
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=85)
    buf.seek(0)
    w, h = im.size
    scale = min(max_w / w, max_h / h)
    return Image(buf, width=w * scale, height=h * scale)


FLAG_COLORS = {'HH': '#C8323F', 'LL': '#C8323F', 'H': '#E0912A', 'L': '#E0912A', 'A': '#E0912A', 'N': '#0F7B78'}


def build_pdf(report, verify_url=''):
    """One PDF: the report, results, imaging with images, AI disclosure and sources, signature, attached PDFs merged."""
    import segno
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from .esign import _styles
    S = _styles()
    W, H = A4
    p, e = report.encounter.patient, report.encounter
    hospital = getattr(settings, 'HOSPITAL_NAME', 'E-MedFlow Hospital')
    draft = report.status == 'draft'
    buf = io.BytesIO()

    def deco(c, doc):
        c.saveState()
        c.setFillColor('#0F2C3F'); c.rect(0, H - 14 * mm, W, 14 * mm, fill=1, stroke=0)
        c.setFillColor('#3FE0B0'); c.rect(0, H - 14.8 * mm, W, .8 * mm, fill=1, stroke=0)
        c.setFillColor('#FFFFFF'); c.setFont('Helvetica-Bold', 10); c.drawString(18 * mm, H - 9 * mm, hospital)
        c.setFont('Helvetica', 8); c.drawRightString(W - 18 * mm, H - 9 * mm, f'{report.number} · {p.full_name} · {p.mrn}'[:90])
        c.setFillColor('#5A6F7D')
        c.drawString(18 * mm, 10 * mm, 'Confidential medical record' + (' · DRAFT, not signed' if draft else
                                                                       f' · signed {timezone.localtime(report.signed_at):%d %b %Y %H:%M}'))
        c.drawRightString(W - 18 * mm, 10 * mm, f'Page {doc.page}')
        if draft:
            c.setFillColor(colors.Color(.78, .2, .25, alpha=.08)); c.setFont('Helvetica-Bold', 90)
            c.translate(W / 2, H / 2); c.rotate(35); c.drawCentredString(0, 0, 'DRAFT')
        c.restoreState()

    st = []
    st.append(Paragraph(_esc(report.title), S['h1']))
    sub = f'{report.number} · {report.get_status_display()}'
    if report.amends_id:
        sub += f' · amends {report.amends.number}' + (f' ({_esc(report.amend_reason)})' if report.amend_reason else '')
    st.append(Paragraph(sub, S['small']))
    st.append(Spacer(1, 4 * mm))
    age = f'{p.age} yrs' if p.age is not None else ''
    info = [[Paragraph('Patient', S['label']), Paragraph(f'<b>{_esc(p.full_name)}</b><br/>{_esc(p.mrn)}', S['value']),
             Paragraph('Sex / age', S['label']), Paragraph(f'{_esc(p.get_sex_display())}{", " + age if age else ""}<br/>born {p.dob:%d %b %Y}', S['value'])],
            [Paragraph('Visit', S['label']), Paragraph(f'{_esc(e.reason)}<br/>{timezone.localtime(e.created_at):%d %b %Y}', S['value']),
             Paragraph('Lab request', S['label']),
             Paragraph(f'{report.lab_request.number}<br/>specimen {_esc(report.lab_request.specimen_id or "—")}' if report.lab_request else '—', S['value'])]]
    if report.follow_up:
        info.append([Paragraph('Follow-up', S['label']), Paragraph(f'<b>{report.follow_up:%A %d %b %Y}</b>', S['value']), '', ''])
    t = Table(info, colWidths=[24 * mm, 63 * mm, 24 * mm, 63 * mm])
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F2F5F3')), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                           ('BOX', (0, 0), (-1, -1), .6, colors.HexColor('#DCE4E0')), ('TOPPADDING', (0, 0), (-1, -1), 5),
                           ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
    st += [t, Spacer(1, 3 * mm)]
    st += md_flowables(report.body, S)

    rows = lab_rows(report)
    if rows:
        st.append(Paragraph('Laboratory results', S['h2']))
        from reportlab.lib.styles import ParagraphStyle
        cell = ParagraphStyle('cell', parent=S['p'], fontSize=8.5, leading=10.5)
        data = [['Test', 'Parameter', 'Result', 'Reference', 'Flag']]
        style = [('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 8.5), ('FONT', (0, 1), (-1, -1), 'Helvetica', 8.5),
                 ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#5A6F7D')), ('LINEBELOW', (0, 0), (-1, 0), .8, colors.HexColor('#0F2C3F')),
                 ('LINEBELOW', (0, 1), (-1, -1), .3, colors.HexColor('#DCE4E0')), ('VALIGN', (0, 0), (-1, -1), 'TOP')]
        last_test = None
        for i, r in enumerate(rows, start=1):
            abn = r['flag'] in FLAG_COLORS and r['flag'] != 'N'
            res = _pdf_text(f"{r['value']} {r['unit']}".strip())
            res = f'<font color="{FLAG_COLORS[r["flag"]]}"><b>{res}</b></font>' if abn else res
            data.append([Paragraph(_esc(r['test']) if r['test'] != last_test else '', cell), Paragraph(_esc(r['parameter']), cell),
                         Paragraph(res, cell), Paragraph(_pdf_text(r['range'] or '—'), cell), r['flag_label']])
            last_test = r['test']
            if r['flag'] in FLAG_COLORS and r['flag'] != 'N':
                style += [('TEXTCOLOR', (4, i), (4, i), colors.HexColor(FLAG_COLORS[r['flag']]))]
        lt = Table(data, colWidths=[38 * mm, 42 * mm, 34 * mm, 34 * mm, 26 * mm], repeatRows=1)
        lt.setStyle(TableStyle(style))
        st.append(lt)

    imgs = selected_images(report)
    if imgs:
        st.append(Paragraph('Imaging', S['h2']))
        by_order = {}
        for im in imgs:
            by_order.setdefault(im.order, []).append(im)
        for o, ims in by_order.items():
            st.append(Paragraph(f'<b>{_esc(o.number)} · {_esc(o.get_modality_display())} {_esc(o.region)}</b> · {_esc(o.get_status_display())}', S['p']))
            if o.impression:
                st.append(Paragraph(f'<b>Impression:</b> {_esc(o.impression)}', S['p']))
            if o.findings:
                st.append(Paragraph(f'<b>Findings:</b> {_esc(o.findings)}', S['small']))
            for im in ims:
                try:
                    fl = _image_flowable(im.file, 174 * mm, 115 * mm)
                    st.append(KeepTogether([Spacer(1, 2 * mm), fl, Paragraph(_esc(im.caption or os.path.basename(im.file.name)) +
                                                                            (' · processed copy' if im.derived_from_id else ''), S['small'])]))
                except Exception:
                    st.append(Paragraph(f'Image {im.pk} could not be read; it is in the ZIP download if the file exists.', S['small']))

    atts = selected_attachments(report)
    img_atts = [a for a in atts if a.is_image]
    if atts:
        heading = Paragraph('Attached files', S['h2'])
        for n, a in enumerate(img_atts):
            try:
                block = [_image_flowable(a.file, 174 * mm, 115 * mm), Paragraph(_esc(a.name), S['small']), Spacer(1, 2 * mm)]
            except Exception:
                block = [Paragraph(f'{_esc(a.name)} could not be read.', S['small'])]
            st.append(KeepTogether(([heading] if n == 0 else []) + block))
        if not img_atts:
            st.append(heading)
        pdfs = [a for a in atts if not a.is_image]
        if pdfs:
            st.append(Paragraph('Appended at the end of this PDF: ' + ', '.join(_esc(a.name) for a in pdfs), S['small']))

    s = report.source_suggestion
    if s:
        st.append(Paragraph('AI assistance', S['h2']))
        who = report.signed_by or report.edited_by
        whos = (who.get_full_name() or who.get_username()) if who else 'the clinician'
        st.append(Paragraph(
            f'Drafted from an AI decision-support summary ({_esc(s.model_name or s.provider or "AI")}, '
            f'{timezone.localtime(s.finished_at or s.created_at):%d %b %Y %H:%M}) that received de-identified data only. '
            f'{"Reviewed, edited and signed" if not draft else "Being reviewed and edited"} by {_esc(whos)}; '
            f'about {edited_pct(report)}% of the AI text was changed. The clinician is responsible for this report.', S['small']))
        if (report.include or {}).get('ai_sources', True) and s.sources:
            for i, src in enumerate(s.sources[:20], start=1):
                url = src.get('url') or ''
                link = f'<link href="{_esc(url)}" color="#0B5F5D">{_esc(src.get("title") or url)}</link>' if url.startswith('https://') else _esc(src.get('title') or url)
                st.append(Paragraph(f'{i}. {link}', S['small']))

    st.append(Spacer(1, 6 * mm))
    if report.status in ('final', 'superseded'):
        signer = report.signed_by
        name = (signer.get_full_name() or signer.get_username()) if signer else '—'
        lic = getattr(getattr(signer, 'hospital_staff', None), 'license_number', '') if signer else ''
        sig = [Paragraph(f'<b>Electronically signed by {_esc(name)}</b>' + (f' · licence {_esc(lic)}' if lic else ''), S['p']),
               Paragraph(f'{timezone.localtime(report.signed_at):%d %b %Y %H:%M} · SHA-256 {report.content_hash[:32]}…', S['small'])]
        if report.status == 'superseded':
            sig.append(Paragraph('<font color="#C8323F"><b>Superseded by an amendment. Do not use for care.</b></font>', S['p']))
    else:
        sig = [Paragraph('<font color="#C8323F"><b>Draft · not signed. Not valid for care decisions.</b></font>', S['p'])]
    cells = [sig, '']
    if verify_url and report.status != 'draft':
        qb = io.BytesIO()
        segno.make(verify_url, error='m').save(qb, kind='png', scale=4, border=1)
        qb.seek(0)
        cells[1] = [Image(qb, width=24 * mm, height=24 * mm), Paragraph('Scan to verify', S['small'])]
    sigt = Table([cells], colWidths=[140 * mm, 34 * mm])
    sigt.setStyle(TableStyle([('LINEABOVE', (0, 0), (-1, 0), .8, colors.HexColor('#0F2C3F')), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                              ('TOPPADDING', (0, 0), (-1, -1), 6)]))
    st.append(KeepTogether([sigt]))

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=24 * mm, bottomMargin=18 * mm,
                            title=f'{report.title} {report.number}', author=hospital)
    doc.build(st, onFirstPage=deco, onLaterPages=deco)
    pdf = buf.getvalue()

    pdf_atts = [a for a in atts if not a.is_image]
    if pdf_atts:
        from pypdf import PdfReader, PdfWriter
        w = PdfWriter()
        w.append(PdfReader(io.BytesIO(pdf)))
        for a in pdf_atts:
            try:
                with a.file.open('rb') as fh:
                    r = PdfReader(io.BytesIO(fh.read()))
                if r.is_encrypted:
                    continue
                w.append(r)
            except Exception:
                continue
        out = io.BytesIO()
        w.write(out)
        pdf = out.getvalue()
    return pdf


# ------------------------------------------------------------------ ZIP
def _safe(name):
    name = re.sub(r'[^A-Za-z0-9._-]+', '-', name or '').strip('-.')
    return name[:80] or 'file'


def build_zip(report, verify_url=''):
    """report.pdf + report.md + lab_results.csv + every original image and attachment + AI text, with SHA-256 manifest."""
    p = report.encounter.patient
    root = f'{report.number}_{_safe(p.mrn)}'
    files, manifest = [], []

    def add(path, data):
        files.append((f'{root}/{path}', data))
        manifest.append({'file': path, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})

    add('report.pdf', build_pdf(report, verify_url))
    add('report.md', f'# {report.title}\n\n{report.number} · {report.get_status_display()}\n\n{report.body}\n'.encode())
    rows = lab_rows(report)
    if rows:
        sbuf = io.StringIO()
        wr = csv.writer(sbuf)
        wr.writerow(['test', 'parameter', 'value', 'unit', 'reference', 'flag', 'verified'])
        for r in rows:
            wr.writerow([r['test'], r['parameter'], r['value'], r['unit'], r['range'], r['flag_label'], 'yes' if r['verified'] else 'no'])
        add('lab_results.csv', sbuf.getvalue().encode('utf-8-sig'))
    for n, im in enumerate(selected_images(report), start=1):
        try:
            with im.file.open('rb') as fh:
                data = fh.read()
        except (FileNotFoundError, OSError):
            continue
        ext = os.path.splitext(im.file.name)[1].lower()
        add(f'images/{im.order.number}_{n:02d}_{_safe(im.caption or im.order.region)}{ext}', data)
    for n, a in enumerate(selected_attachments(report), start=1):
        try:
            with a.file.open('rb') as fh:
                data = fh.read()
        except (FileNotFoundError, OSError):
            continue
        base, ext = os.path.splitext(a.name)
        add(f'attachments/{n:02d}_{_safe(base)}{ext.lower() or os.path.splitext(a.file.name)[1]}', data)
    s = report.source_suggestion
    if s:
        add('ai/ai_summary_as_received.md', (s.text or '').encode())
        if s.sources:
            add('ai/sources.json', json.dumps(s.sources, indent=2, ensure_ascii=False).encode())
    readme = (f'{report.title}\n{report.number} for {p.full_name} ({p.mrn})\nStatus: {report.get_status_display()}\n'
              f'Exported {timezone.localtime():%d %b %Y %H:%M}\n'
              + (f'Signed content hash (SHA-256): {report.content_hash}\nVerify: {verify_url}\n' if report.content_hash else 'DRAFT: not signed.\n')
              + '\nmanifest.json lists the SHA-256 of every file in this folder.\nConfidential medical record: store and share securely.\n')
    add('README.txt', readme.encode())
    files.append((f'{root}/manifest.json', json.dumps({'report': report.number, 'status': report.status, 'content_hash': report.content_hash,
                                                       'files': manifest}, indent=2).encode()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for path, data in files:
            z.writestr(path, data)
    return out.getvalue(), f'{root}.zip'


# ------------------------------------------------------------------ AI helpers on the draft
ASSIST_TASKS = {
    'safety': ('You are reviewing a doctor\'s DRAFT report against the patient data in the context. List, most important first: '
               'critical or abnormal results the draft does not address; statements that contradict the results; medicines that '
               'conflict with listed allergies or conditions; any dose stated (ask the doctor to check it against the national '
               'guideline); missing follow-up or safety-netting; anything else unsafe. If nothing is wrong, say so in one line. '
               'Answer as a short bulleted list. Do not rewrite the report.'),
    'patient': ('Write a short explanation of this report for the patient, in plain English a 12-year-old could follow, '
                'warm and respectful. Explain what the tests showed, what happens next and the warning signs that mean they '
                'should come back at once. No jargon, no doses, no blame. Use "you". Under 220 words. Start with "## For the patient".'),
    'tighten': ('Rewrite the doctor\'s draft report to be clearer and more concise for another clinician, keeping every clinical fact, '
                'number, plan step and uncertainty, keeping the same ## headings and the citations. Do not add new clinical content. '
                'Return only the rewritten report.'),
    'codes': ('Suggest up to 5 ICD-10 codes that fit the doctor\'s assessment in this draft, most likely first, as a bulleted list: '
              '**code** description, then one short reason. Mark any code that needs a confirmed diagnosis before use. '
              'Do not invent codes; if unsure, say so.'),
}


def deidentify(text, patient):
    """Remove the identifiers a doctor might type into a draft before it goes to the AI service."""
    t = text or ''
    for val, tag in ((patient.mrn, '[MRN]'), (patient.full_name, '[PATIENT]'), (patient.phone, '[PHONE]'),
                     (patient.first_name, '[PATIENT]'), (patient.last_name, '[PATIENT]'), (patient.email, '[EMAIL]')):
        if val and len(val.strip()) >= 2:
            t = re.sub(re.escape(val.strip()), tag, t, flags=re.I)
    t = re.sub(r'\b[\w.+-]+@[\w-]+\.[\w.]+\b', '[EMAIL]', t)
    t = re.sub(r'(?<!\d)(?:\+?\d[\d\s-]{6,}\d)(?!\d)', '[NUMBER]', t)
    if patient.dob:
        for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d %b %Y', '%d %B %Y'):
            t = t.replace(patient.dob.strftime(fmt), '[DOB]')
    return t


def run_assist(pk):
    from . import medical_ai
    from .models import ReportAssist
    a = ReportAssist.objects.select_related('report__encounter__patient', 'report__lab_request').get(pk=pk)
    if a.status not in ('queued', 'running'):
        return a
    prov = medical_ai.provider()
    a.status, a.model_name = 'running', medical_ai.model_name() if prov in ('anthropic', 'openai') else 'endpoint'
    a.save(update_fields=['status', 'model_name', 'updated_at'])
    try:
        if not medical_ai.enabled():
            raise RuntimeError('AI is not configured')
        r = a.report
        if r.lab_request_id:
            from .views import lab_requests_qs
            ctx = medical_ai.lab_context(lab_requests_qs().get(pk=r.lab_request_id))
        else:
            from .clinical import deidentified_context
            ctx = deidentified_context(r.encounter)
        ctx['doctor_draft_report'] = a.input_text
        text, _sources, _ = medical_ai._ask(ctx, f'report_{a.kind}', ASSIST_TASKS[a.kind] +
                                            '\n\nThe draft is in the context as doctor_draft_report.')
        if not text:
            raise RuntimeError('The AI service returned no text')
        a.text, a.status = text.strip(), 'done'
    except Exception as exc:
        a.status, a.error = 'failed', f'{exc.__class__.__name__}: {exc}'[:500]
    a.finished_at = timezone.now()
    a.save()
    return a
