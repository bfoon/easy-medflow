"""Lab result guidance for doctors: hospital and WHO ranges, protocol, local practice, trusted sources and AI.
Also the laboratory's page for WHO / international reference values."""
import json
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import evidence
from .models import AISuggestion, EvidenceFetch, EvidenceItem, LabParameter, ReferenceRange
from .views import ROLES, audit, authorize, lab_requests_qs, role_of

GUIDANCE_ROLES = {'doctor', 'nurse', 'lab', 'admin'}


def _guidance_access(request):
    authorize(request)
    if role_of(request.user) not in GUIDANCE_ROLES:
        raise PermissionDenied('Result guidance is for clinical and laboratory staff.')


def _dispatch(task, *args):
    """Queue a background job; run it here and now if the worker cannot be reached."""
    try:
        task.apply_async(args=list(args), retry=False)
        return True
    except Exception:
        task(*args)
        return False


@login_required
def lab_guidance(request, pk):
    """The guidance panel of a lab request (an HTML fragment loaded by guidance.js; it reloads itself while
    sources are being fetched or the AI is thinking)."""
    _guidance_access(request)
    lr = get_object_or_404(lab_requests_qs(), pk=pk)
    g = evidence.request_guidance(lr)
    from .medical_ai import enabled as ai_on, model_name, provider
    latest = AISuggestion.objects.filter(lab_request=lr).select_related('requested_by').first()
    if request.GET.get('first') == '1':
        audit(request, 'view_chart', f'lab_guidance:{lr.pk}')
    return render(request, 'hospital/lab/_guidance.html', {
        'lr': lr, 'p': lr.encounter.patient, 'g': g, 'ai_on': ai_on(), 'ai': latest, 'ai_model': model_name() if provider() == 'anthropic' else '',
        'ai_web': provider() == 'anthropic' and getattr(settings, 'CLINICAL_AI_WEB_SEARCH', True),
        'can_ai': role_of(request.user) in ROLES['clinical'], 'pending': g['pending'] or bool(latest and latest.busy),
        'open_encounter': lr.encounter if lr.encounter.status == 'open' else None})


@login_required
@require_POST
def lab_guidance_refresh(request, pk):
    """Fetch trusted sources again for every abnormal result in this request (now, if the worker is down)."""
    _guidance_access(request)
    lr = get_object_or_404(lab_requests_qs(), pk=pk)
    if not evidence.fetch_enabled():
        return JsonResponse({'error': 'Fetching from medical sources is switched off (MEDICAL_EVIDENCE_FETCH).'}, status=400)
    done = set()
    for o in lr.orders.all():
        if o.status not in ('resulted', 'verified'):
            continue
        for v in o.values.all():
            d = evidence.direction(v.flag)
            if d and (v.parameter.code, d) not in done:
                done.add((v.parameter.code, d))
                evidence.queue_refresh(v.parameter.code, d, v.parameter.name, v.parameter.unit, force=True, inline_fallback=True)
    audit(request, 'evidence_refresh', f'lab_request:{lr.pk}', {'results': len(done)})
    return JsonResponse({'ok': True, 'message': f'Fetching sources for {len(done)} result type{"s" if len(done) != 1 else ""}.' if done
                         else 'No abnormal results to look up.'})


@login_required
@require_POST
def lab_ai_request(request, pk):
    """Ask the AI for next steps on this request. One request at a time; the panel shows progress."""
    authorize(request, 'clinical')
    from .medical_ai import enabled
    from .tasks import ai_suggestion_task
    lr = get_object_or_404(lab_requests_qs(), pk=pk)
    if not enabled():
        return JsonResponse({'error': 'AI is not connected. Ask an administrator to configure it.'}, status=400)
    if not any(o.status in ('resulted', 'verified') for o in lr.orders.all()):
        return JsonResponse({'error': 'No results have been reported yet.'}, status=400)
    busy = AISuggestion.objects.filter(lab_request=lr, status__in=['queued', 'running']).first()
    if busy and busy.busy:
        return JsonResponse({'ok': True, 'id': busy.pk, 'message': 'The AI is already working on this request.'})
    s = AISuggestion.objects.create(lab_request=lr, encounter=lr.encounter, requested_by=request.user)
    audit(request, 'ai_request', f'lab_request:{lr.pk}', {'suggestion': s.pk})
    _dispatch(ai_suggestion_task, s.pk)
    return JsonResponse({'ok': True, 'id': s.pk, 'message': 'Asking the AI. Results appear here in a moment.'})


@login_required
@require_POST
def lab_ai_rate(request, pk):
    authorize(request, 'clinical')
    s = get_object_or_404(AISuggestion, pk=pk)
    v = request.POST.get('helpful')
    if v not in ('1', '0'):
        return HttpResponseBadRequest('helpful must be 1 or 0')
    s.helpful = v == '1'
    s.save(update_fields=['helpful', 'updated_at'])
    audit(request, 'ai_rate', f'ai_suggestion:{s.pk}', {'helpful': s.helpful})
    return JsonResponse({'ok': True, 'message': 'Thank you, feedback recorded.'})


@login_required
def lab_ai_context(request, pk):
    """Exactly what the AI receives for this lab request: de-identified, for transparency and audit."""
    authorize(request, 'clinical')
    from .medical_ai import digest, enabled, lab_context
    lr = get_object_or_404(lab_requests_qs(), pk=pk)
    ctx = lab_context(lr)
    audit(request, 'ai_context_preview', f'lab_request:{lr.pk}')
    return render(request, 'hospital/ai_context.html', {'e': lr.encounter, 'p': lr.encounter.patient, 'lr': lr, 'enabled': enabled(),
                                                        'json': json.dumps(ctx, indent=2, default=str), 'digest': digest(ctx)})


def _dec(raw):
    raw = (raw or '').strip().replace(',', '.')
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise ValueError(f'“{raw}” is not a number')


@login_required
def lab_references(request):
    """WHO and other guideline reference values used beside the hospital ranges, and the trusted-source cache."""
    authorize(request, 'lab')
    can_edit = role_of(request.user) in ('lab', 'admin')
    if request.method == 'POST':
        if not can_edit:
            raise PermissionDenied('Only laboratory staff can change reference values.')
        action = request.POST.get('action')
        r = ReferenceRange.objects.filter(pk=request.POST.get('pk') or 0).first()
        if action == 'verify' and r:
            r.status, r.verified_by, r.verified_at, r.source_note = 'verified', request.user, timezone.now(), ''
            r.save()
            audit(request, 'reference_verify', f'reference:{r.pk}')
            messages.success(request, f'{r.code} · {r.label} ({r.population()}) verified.')
        elif action == 'retire' and r:
            r.status = 'retired'
            r.save(update_fields=['status', 'updated_at'])
            audit(request, 'reference_retire', f'reference:{r.pk}')
            messages.info(request, f'{r.code} · {r.label} retired; it is no longer shown to doctors.')
        elif action == 'restore' and r:
            r.status = 'curated'
            r.save(update_fields=['status', 'updated_at'])
            messages.success(request, f'{r.code} · {r.label} restored.')
        elif action == 'add':
            P = request.POST
            try:
                code = P.get('code', '').strip().upper()
                if not LabParameter.objects.filter(code=code).exists():
                    raise ValueError(f'No lab parameter has the code “{code}”.')
                low, high = _dec(P.get('low')), _dec(P.get('high'))
                if low is None and high is None:
                    raise ValueError('Enter a low value, a high value or both.')
                amin = int(P['age_min_months']) if P.get('age_min_months', '').strip() else None
                amax = int(P['age_max_months']) if P.get('age_max_months', '').strip() else None
                if P.get('kind') not in dict(ReferenceRange.KINDS) or P.get('source') not in dict(ReferenceRange.SOURCES) \
                        or P.get('sex', '') not in dict(ReferenceRange.SEXES) or P.get('condition', '') not in dict(ReferenceRange.CONDITIONS):
                    raise ValueError('Choose the source, kind, sex and condition from the lists.')
                if not P.get('citation_title', '').strip():
                    raise ValueError('Give the guideline or document the values come from.')
                url = P.get('citation_url', '').strip()
                if url and not url.startswith('https://'):
                    raise ValueError('The source link must start with https://')
                r = ReferenceRange.objects.create(
                    code=code, source=P['source'], source_name=P.get('source_name', '').strip()[:120] or dict(ReferenceRange.SOURCES)[P['source']],
                    label=P.get('label', '').strip()[:160] or 'Reference', kind=P['kind'], sex=P.get('sex', ''), condition=P.get('condition', ''),
                    age_min_months=amin, age_max_months=amax, low=low, high=high, unit=P.get('unit', '').strip()[:30],
                    note=P.get('note', '').strip()[:300], citation_title=P['citation_title'].strip()[:300], citation_url=url[:500],
                    citation_year=int(P['citation_year']) if P.get('citation_year', '').strip().isdigit() else None,
                    status='verified', verified_by=request.user, verified_at=timezone.now())
                audit(request, 'reference_add', f'reference:{r.pk}')
                messages.success(request, f'Reference added for {code}.')
            except (ValueError, KeyError) as exc:
                messages.error(request, str(exc) or 'Check the form.')
        elif action == 'check_sources':
            from .tasks import check_reference_sources_task
            if not evidence.fetch_enabled():
                messages.error(request, 'Fetching from medical sources is switched off (MEDICAL_EVIDENCE_FETCH).')
            else:
                queued = _dispatch(check_reference_sources_task)
                messages.info(request, 'Checking the cited pages in the background.' if queued else 'Cited pages checked.')
        elif action == 'seed':
            n = evidence.seed_who_references()
            messages.success(request, f'{n} standard WHO reference{"s" if n != 1 else ""} added.' if n else 'All standard WHO references are present.')
        else:
            messages.error(request, 'Unknown action.')
        return redirect('lab_references')
    refs = list(ReferenceRange.objects.select_related('verified_by'))
    units = {p.code: p.unit for p in LabParameter.objects.all()}
    groups = {}
    for r in refs:
        groups.setdefault(r.code, []).append(r)
        r.unit_mismatch = r.code in units and evidence._unit(units[r.code]) != evidence._unit(r.unit)
    names = {p.code: p.name for p in LabParameter.objects.all()}
    fetches = EvidenceFetch.objects.all()
    counts = {}
    for it in EvidenceItem.objects.values_list('key', 'source'):
        counts.setdefault(it[0], set()).add(it[1])
    return render(request, 'hospital/lab/references.html', {
        'groups': [(code, names.get(code, code), rows) for code, rows in sorted(groups.items())], 'can_edit': can_edit, 'tab': 'references',
        'review': [r for r in refs if r.status == 'review'], 'fetches': fetches, 'counts': counts, 'fetch_on': evidence.fetch_enabled(),
        'domains': evidence.trusted_domains(), 'R': ReferenceRange, 'codes': sorted(names.items())})
