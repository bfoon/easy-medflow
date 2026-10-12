"""Doctor's reports: adopt the AI summary, edit, add files, ask the AI to check or rephrase, sign, download PDF or ZIP."""
import json
import os
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from . import reports as R
from .models import AISuggestion, DoctorReport, ReportAssist, ReportAttachment
from .views import audit, authorize, role_of

SIGN_ROLES = {'doctor', 'admin'}


def _report(pk):
    return get_object_or_404(DoctorReport.objects.select_related('encounter__patient', 'lab_request', 'source_suggestion', 'signed_by',
                                                                 'edited_by', 'amends'), pk=pk)


def _can_sign(user):
    return user.is_superuser or role_of(user) in SIGN_ROLES


def _verify_url(request, r):
    return request.build_absolute_uri(reverse('report_verify', args=[r.verify_token]))


def _editable(r):
    if not r.editable:
        raise PermissionDenied('This report is signed. Start an amendment to change it.')


@login_required
@require_POST
def report_adopt(request, pk):
    """Adopt an AI summary as the doctor's report (or open the existing draft for this lab request)."""
    authorize(request, 'clinical')
    s = get_object_or_404(AISuggestion.objects.select_related('lab_request', 'encounter__patient'), pk=pk)
    if s.status != 'done' or not s.text:
        messages.error(request, 'That AI summary is not ready.')
        return redirect('lab_request_detail', s.lab_request_id)
    r, created = R.adopt(s, request.user)
    audit(request, 'report_adopt', f'doctor_report:{r.pk}', {'suggestion': s.pk, 'created': created})
    if created:
        messages.success(request, 'AI summary adopted as a draft. Edit it, then sign.')
    url = reverse('report_detail', args=[r.pk])
    return redirect(url + (f'?newer={s.pk}' if not created and r.source_suggestion_id != s.pk else ''))


@login_required
def report_detail(request, pk):
    authorize(request, 'clinical')
    r = _report(pk)
    audit(request, 'view_chart', f'doctor_report:{r.pk}')
    newer = None
    if r.editable and r.lab_request_id:
        latest = AISuggestion.objects.filter(lab_request=r.lab_request, status='done').first()
        if latest and latest.pk != r.source_suggestion_id and (not r.source_suggestion or latest.created_at > r.source_suggestion.created_at):
            newer = latest
    all_rows = R.request_rows(r.lab_request, r.encounter.patient.sex) if r.lab_request_id else []
    return render(request, 'hospital/lab/doctor_report.html', {
        'r': r, 'p': r.encounter.patient, 'lr': r.lab_request, 'rows': all_rows, 'images': R.encounter_images(r.encounter),
        'attachments': list(r.attachments.all()), 'inc': {'labs': True, 'ai_sources': True, 'images': [], 'attachments': [], **(r.include or {})}, 'edited_pct': R.edited_pct(r), 'newer': newer,
        'can_sign': _can_sign(request.user), 'assists': list(r.assists.all()[:8]), 'kinds': ReportAssist.KINDS,
        'from_ai': r.source_suggestion, 'verify_url': _verify_url(request, r) if r.status != 'draft' else '',
        'critical': [x for x in all_rows if x['flag'] in ('HH', 'LL')], 'abnormal': [x for x in all_rows if x['flag'] in ('H', 'L', 'A')],
        'amendments': list(r.amendments.all()), 'ai_on': _ai_on(), 'today': date.today(),
        'history': [{**h, 'when': parse_datetime(h.get('at') or '')} for h in reversed(r.history or [])][:15]})


def _ai_on():
    from .medical_ai import enabled
    return enabled()


@login_required
@require_POST
def report_save(request, pk):
    """Autosave from the editor (JSON)."""
    authorize(request, 'clinical')
    r = _report(pk)
    if not r.editable:
        return JsonResponse({'error': 'This report is signed and can no longer change.'}, status=409)
    P = request.POST
    if 'title' in P:
        r.title = (P.get('title') or '').strip()[:160] or "Doctor's report"
    if 'body' in P:
        r.body = P.get('body', '')[:60000]
    if 'follow_up' in P:
        try:
            r.follow_up = date.fromisoformat(P['follow_up']) if P['follow_up'].strip() else None
        except ValueError:
            return JsonResponse({'error': 'Follow-up date is not valid.'}, status=400)
    if 'include' in P:
        try:
            inc = json.loads(P['include'])
            img_ok = {i.pk for i in R.encounter_images(r.encounter)}
            att_ok = set(r.attachments.values_list('pk', flat=True))
            r.include = {'labs': bool(inc.get('labs', True)), 'ai_sources': bool(inc.get('ai_sources', True)),
                         'images': [int(i) for i in inc.get('images', []) if int(i) in img_ok],
                         'attachments': [int(i) for i in inc.get('attachments', []) if int(i) in att_ok]}
        except (ValueError, TypeError, AttributeError):
            return HttpResponseBadRequest('include must be JSON')
    r.edited_by = request.user
    r.save()
    return JsonResponse({'ok': True, 'saved_at': timezone.localtime(r.updated_at).strftime('%H:%M:%S'), 'edited_pct': R.edited_pct(r)})


@login_required
@require_POST
def report_sign(request, pk):
    authorize(request, 'clinical')
    r = _report(pk)
    _editable(r)
    if not _can_sign(request.user):
        raise PermissionDenied('Only doctors can sign a report.')
    if request.POST.get('reviewed') != '1':
        messages.error(request, 'Confirm that you have reviewed the whole report before signing.')
        return redirect('report_detail', r.pk)
    if not (r.body or '').strip() or '(Add your examination findings' in r.body:
        messages.error(request, 'Write your own assessment (replace the placeholder under “Doctor\'s assessment”) before signing.')
        return redirect('report_detail', r.pk)
    R.sign(r, request.user)
    audit(request, 'report_sign', f'doctor_report:{r.pk}', {'hash': r.content_hash, 'edited_pct': R.edited_pct(r)})
    messages.success(request, f'{r.number} signed. Download it as a PDF or a ZIP with every file.')
    return redirect('report_detail', r.pk)


@login_required
@require_POST
def report_amend(request, pk):
    authorize(request, 'clinical')
    r = _report(pk)
    if r.status != 'final':
        messages.error(request, 'Only a signed, current report can be amended.')
        return redirect('report_detail', r.pk)
    reason = request.POST.get('reason', '').strip()
    if not reason:
        messages.error(request, 'Give a reason for the amendment.')
        return redirect('report_detail', r.pk)
    new = R.amend(r, request.user, reason)
    audit(request, 'report_amend', f'doctor_report:{r.pk}', {'amendment': new.pk})
    return redirect('report_detail', new.pk)


@login_required
@require_POST
def report_replace(request, pk, sid):
    authorize(request, 'clinical')
    r = _report(pk)
    _editable(r)
    s = get_object_or_404(AISuggestion, pk=sid, lab_request=r.lab_request, status='done')
    R.replace_with_suggestion(r, s, request.user)
    audit(request, 'report_replace_ai', f'doctor_report:{r.pk}', {'suggestion': s.pk})
    messages.success(request, 'Draft replaced with the newer AI summary.')
    return redirect('report_detail', r.pk)


@login_required
@require_POST
def report_discard(request, pk):
    authorize(request, 'clinical')
    r = _report(pk)
    _editable(r)
    back = r.lab_request_id
    for a in r.attachments.all():
        a.file.delete(save=False)
    audit(request, 'report_discard', f'doctor_report:{r.pk}')
    r.delete()
    messages.info(request, 'Draft discarded.')
    return redirect('lab_request_detail', back) if back else redirect('dashboard')


@login_required
@require_POST
def report_attach(request, pk):
    authorize(request, 'clinical')
    r = _report(pk)
    _editable(r)
    added, errors = [], []
    count = r.attachments.count()
    for f in request.FILES.getlist('files'):
        ext = os.path.splitext(f.name)[1].lower()
        if ext not in R.ATTACH_TYPES:
            errors.append(f'{f.name}: only JPG, PNG, WebP or PDF')
            continue
        if f.size > R.ATTACH_MAX_BYTES:
            errors.append(f'{f.name}: larger than 15 MB')
            continue
        if count >= R.ATTACH_MAX_COUNT:
            errors.append(f'{f.name}: at most {R.ATTACH_MAX_COUNT} files per report')
            continue
        head = f.read(8); f.seek(0)
        if ext == '.pdf' and not head.startswith(b'%PDF'):
            errors.append(f'{f.name}: not a PDF')
            continue
        if ext != '.pdf':
            try:
                from PIL import Image
                Image.open(f).verify(); f.seek(0)
            except Exception:
                errors.append(f'{f.name}: not a readable image')
                continue
        a = ReportAttachment.objects.create(report=r, file=f, name=os.path.basename(f.name)[:160], content_type=R.ATTACH_TYPES[ext],
                                            size=f.size, uploaded_by=request.user)
        added.append(a.pk)
        count += 1
    if added:
        inc = dict(r.include or {})
        inc['attachments'] = list(inc.get('attachments') or []) + added
        r.include = inc
        r.log(request.user, 'added files', count=len(added))
        r.save(update_fields=['include', 'history', 'updated_at'])
        audit(request, 'report_attach', f'doctor_report:{r.pk}', {'files': added})
    if request.headers.get('X-Requested-With') == 'fetch':
        return JsonResponse({'ok': bool(added), 'added': added, 'errors': errors}, status=200 if added or not errors else 400)
    for e in errors:
        messages.error(request, e)
    if added:
        messages.success(request, f'{len(added)} file{"s" if len(added) != 1 else ""} added.')
    return redirect(reverse('report_detail', args=[r.pk]) + '#files')


@login_required
@require_POST
def report_attachment_delete(request, pk):
    authorize(request, 'clinical')
    a = get_object_or_404(ReportAttachment.objects.select_related('report'), pk=pk)
    r = a.report
    _editable(r)
    inc = dict(r.include or {})
    inc['attachments'] = [i for i in inc.get('attachments') or [] if i != a.pk]
    r.include = inc
    r.log(request.user, 'removed file', name=a.name)
    r.save(update_fields=['include', 'history', 'updated_at'])
    a.file.delete(save=False)
    a.delete()
    return redirect(reverse('report_detail', args=[r.pk]) + '#files')


@login_required
def report_attachment_file(request, pk):
    authorize(request, 'clinical')
    a = get_object_or_404(ReportAttachment, pk=pk)
    try:
        resp = FileResponse(a.file.open('rb'), content_type=a.content_type)
    except FileNotFoundError:
        raise Http404
    resp['Cache-Control'] = 'private, max-age=3600'
    resp['Content-Disposition'] = 'inline'
    return resp


@login_required
def report_pdf(request, pk):
    authorize(request, 'clinical')
    r = _report(pk)
    pdf = R.build_pdf(r, _verify_url(request, r))
    audit(request, 'report_pdf', f'doctor_report:{r.pk}', {'status': r.status})
    resp = HttpResponse(pdf, content_type='application/pdf')
    name = f'{r.number}{"-DRAFT" if r.status == "draft" else ""}.pdf'
    resp['Content-Disposition'] = f'{"inline" if request.GET.get("inline") else "attachment"}; filename="{name}"'
    resp['Cache-Control'] = 'no-store'
    return resp


@login_required
def report_zip(request, pk):
    authorize(request, 'clinical')
    r = _report(pk)
    data, name = R.build_zip(r, _verify_url(request, r))
    audit(request, 'report_zip', f'doctor_report:{r.pk}', {'status': r.status})
    resp = HttpResponse(data, content_type='application/zip')
    resp['Content-Disposition'] = f'attachment; filename="{name.replace(".zip", "-DRAFT.zip") if r.status == "draft" else name}"'
    resp['Cache-Control'] = 'no-store'
    return resp


@login_required
@require_POST
def report_assist(request, pk, kind):
    """Ask the AI to check or rephrase the draft as it is in the editor now (identifiers removed first)."""
    authorize(request, 'clinical')
    from .medical_ai import enabled
    from .evidence_views import _dispatch
    from .tasks import report_assist_task
    r = _report(pk)
    _editable(r)
    if kind not in dict(ReportAssist.KINDS):
        raise Http404
    if not enabled():
        return JsonResponse({'error': 'AI is not connected. Ask an administrator to configure it.'}, status=400)
    if r.assists.filter(status__in=['queued', 'running'], created_at__gte=timezone.now() - timezone.timedelta(minutes=10)).count() >= 2:
        return JsonResponse({'error': 'Two AI helpers are already working on this report. Wait for them first.'}, status=429)
    body = request.POST.get('body', r.body)[:60000]
    a = ReportAssist.objects.create(report=r, kind=kind, requested_by=request.user, input_text=R.deidentify(body, r.encounter.patient))
    audit(request, 'report_assist', f'doctor_report:{r.pk}', {'kind': kind, 'assist': a.pk})
    _dispatch(report_assist_task, a.pk)
    return JsonResponse({'ok': True, 'id': a.pk, 'poll': reverse('report_assist_status', args=[a.pk])})


@login_required
def report_assist_status(request, pk):
    authorize(request, 'clinical')
    a = get_object_or_404(ReportAssist, pk=pk)
    from .templatetags.evidence_tags import simple_md
    return JsonResponse({'id': a.pk, 'kind': a.kind, 'label': a.get_kind_display(), 'status': 'running' if a.busy else
                         ('failed' if a.status in ('queued', 'running') else a.status), 'text': a.text,
                         'html': str(simple_md(a.text)) if a.text else '', 'error': a.error or ('Timed out' if a.status in ('queued', 'running') and not a.busy else '')})


def report_verify(request, token):
    """Public: is this a genuine signed report, and has its content changed? Shows no patient details."""
    r = DoctorReport.objects.filter(verify_token=token).select_related('signed_by').first()
    ok = None
    if r and r.status != 'draft':
        try:
            ok = R.content_hash(r) == r.content_hash
        except Exception:
            ok = False
    return render(request, 'hospital/lab/report_verify.html', {'r': r, 'ok': ok,
                                                               'current': r.amendments.filter(status='final').first() if r else None})


def reports_for(lab_request):
    """The latest draft or signed report for a lab request (for the guidance panel)."""
    return (DoctorReport.objects.filter(lab_request=lab_request).filter(Q(status='draft') | Q(status='final'))
            .select_related('source_suggestion').first())
