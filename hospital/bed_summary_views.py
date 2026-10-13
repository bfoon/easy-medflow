"""Dr. Flow on the bed page: quick facts, the AI handover summary, rating it, and exactly what the AI receives.
JSON endpoints used by bed-summary.js. See bed_summary.py for what is and is not sent."""
import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from . import bed_summary as S
from .models import Admission, BedSummary
from .views import audit, authorize


def _admission(pk):
    return get_object_or_404(Admission.objects.select_related('encounter__patient', 'bed'), pk=pk)


@login_required
@require_GET
def panel(request, pk):
    """Quick facts (no AI) and the latest summary for this stay."""
    authorize(request, 'clinical')
    from .medical_ai import enabled
    a = _admission(pk)
    latest = a.drflow_summaries.select_related('requested_by').first()
    return JsonResponse({'enabled': enabled(), 'discharged': bool(a.discharged_at), 'quick': S.quick_facts(a), 'summary': S.serialize(latest)})


@login_required
@require_POST
def ask(request, pk):
    """Start a new handover summary. One at a time per stay; the page polls status()."""
    authorize(request, 'clinical')
    from .evidence_views import _dispatch
    from .medical_ai import enabled
    from .tasks import bed_summary_task
    a = _admission(pk)
    if not enabled():
        return JsonResponse({'ok': False, 'error': 'AI is not connected. Ask an administrator to configure it.'}, status=400)
    if a.discharged_at:
        return JsonResponse({'ok': False, 'error': 'This patient has been discharged from the bed.'}, status=400)
    busy = a.drflow_summaries.filter(status__in=['queued', 'running']).first()
    if busy and busy.busy:
        return JsonResponse({'ok': True, 'summary': S.serialize(busy)})
    s = BedSummary.objects.create(admission=a, requested_by=request.user)
    audit(request, 'drflow_bed_summary', f'admission:{a.pk}', {'summary': s.pk})
    _dispatch(bed_summary_task, s.pk)
    s.refresh_from_db()
    return JsonResponse({'ok': True, 'summary': S.serialize(s)})


@login_required
@require_GET
def status(request, pk):
    authorize(request, 'clinical')
    s = get_object_or_404(BedSummary.objects.select_related('requested_by'), pk=pk)
    return JsonResponse({'ok': True, 'summary': S.serialize(s)})


@login_required
@require_POST
def rate(request, pk):
    authorize(request, 'clinical')
    s = get_object_or_404(BedSummary, pk=pk)
    v = request.POST.get('helpful', '')
    if v not in ('1', '0'):
        return HttpResponseBadRequest('helpful must be 1 or 0')
    s.helpful = v == '1'
    s.save(update_fields=['helpful', 'updated_at'])
    audit(request, 'drflow_bed_summary_rate', f'bed_summary:{s.pk}', {'helpful': s.helpful})
    return JsonResponse({'ok': True, 'message': 'Thank you, feedback recorded.'})


@login_required
@require_GET
def context(request, pk):
    """Exactly what the AI would receive for this stay: de-identified, for transparency. Nothing is sent here."""
    authorize(request, 'clinical')
    a = _admission(pk)
    ctx = S.summary_context(a)
    audit(request, 'ai_context_preview', f'admission:{a.pk}')
    return JsonResponse({'ok': True, 'context': json.dumps(ctx, indent=2, default=str), 'digest': S.digest(ctx)})
