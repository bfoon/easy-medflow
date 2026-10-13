"""Dr. Flow on the Lab insights page: the heads-up, the AI heads-up and questions, rating answers, and exactly what
the AI receives. JSON endpoints used by lab-insights-drflow.js. See lab_insights_ai.py for what is and is not sent."""
import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from . import lab_insights_ai as L
from .models import LabInsightAsk, Patient
from .views import audit, authorize

THREAD = 20


@login_required
@require_GET
def panel(request, pk):
    """The heads-up (no AI) and the conversation so far, oldest first."""
    authorize(request, 'clinical')
    from .medical_ai import enabled
    p = get_object_or_404(Patient, pk=pk)
    asks = list(p.lab_insight_asks.select_related('requested_by')[:THREAD])
    return JsonResponse({'enabled': enabled(), 'headsup': L.headsup(p), 'thread': [L.serialize(a) for a in reversed(asks)]})


@login_required
@require_POST
def ask(request, pk):
    """Start an AI heads-up or a question. One at a time per patient; the page polls status()."""
    authorize(request, 'clinical')
    from .evidence_views import _dispatch
    from .medical_ai import enabled
    from .tasks import lab_insight_task
    p = get_object_or_404(Patient, pk=pk)
    kind = request.POST.get('kind', 'question')
    if kind not in dict(LabInsightAsk.KINDS):
        return JsonResponse({'ok': False, 'error': 'Unknown request.'}, status=400)
    question = request.POST.get('question', '').strip()[:500]
    if kind == 'question' and len(question) < 3:
        return JsonResponse({'ok': False, 'error': 'Type a question first.'}, status=400)
    if not enabled():
        return JsonResponse({'ok': False, 'error': 'AI is not connected. Ask an administrator to configure it.'}, status=400)
    busy = p.lab_insight_asks.filter(status__in=['queued', 'running']).first()
    if busy and busy.busy:
        return JsonResponse({'ok': True, 'ask': L.serialize(busy), 'message': 'Dr. Flow is still answering the last one.'})
    a = LabInsightAsk.objects.create(patient=p, requested_by=request.user, kind=kind, question=question)
    audit(request, 'drflow_lab_insights', f'patient_labs:{p.pk}', {'ask': a.pk, 'kind': kind})
    _dispatch(lab_insight_task, a.pk)
    a.refresh_from_db()
    return JsonResponse({'ok': True, 'ask': L.serialize(a)})


@login_required
@require_GET
def status(request, pk):
    authorize(request, 'clinical')
    a = get_object_or_404(LabInsightAsk.objects.select_related('requested_by'), pk=pk)
    return JsonResponse({'ok': True, 'ask': L.serialize(a)})


@login_required
@require_POST
def rate(request, pk):
    authorize(request, 'clinical')
    a = get_object_or_404(LabInsightAsk, pk=pk)
    v = request.POST.get('helpful', '')
    if v not in ('1', '0'):
        return HttpResponseBadRequest('helpful must be 1 or 0')
    a.helpful = v == '1'
    a.save(update_fields=['helpful', 'updated_at'])
    audit(request, 'drflow_lab_insights_rate', f'lab_insight:{a.pk}', {'helpful': a.helpful})
    return JsonResponse({'ok': True, 'message': 'Thank you, feedback recorded.'})


@login_required
@require_GET
def context(request, pk):
    """Exactly what the AI would receive about these results: de-identified, for transparency. Nothing is sent here."""
    authorize(request, 'clinical')
    p = get_object_or_404(Patient, pk=pk)
    ctx = L.insights_context(p)
    audit(request, 'ai_context_preview', f'patient_labs:{p.pk}')
    return JsonResponse({'ok': True, 'context': json.dumps(ctx, indent=2, default=str), 'digest': L.digest(ctx)})
