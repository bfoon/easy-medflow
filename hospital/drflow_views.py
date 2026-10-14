"""Dr. Flow endpoints: the patient brief, live advice while prescribing or ordering tests, and questions."""
import json

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import drflow, drflow_ask
from .models import DrFlowAsk, Encounter, LabTest, Medication, Patient, Prescription
from .views import audit, authorize


def _encounter(request):
    return Encounter.objects.select_related('patient').filter(pk=(request.POST.get('encounter') or request.GET.get('encounter') or 0)).first()


@login_required
def api_brief(request, pk):
    authorize(request, 'clinical')
    p = get_object_or_404(Patient, pk=pk)
    return JsonResponse(drflow.patient_brief(p))


def parse_lines(raw):
    """[{'med': id, 'dose', 'units', 'frequency', 'days', 'quantity', 'route'}] → the same with Medication objects."""
    try:
        items = json.loads(raw or '[]')
    except ValueError:
        return []
    ids = [int(i['med']) for i in items if isinstance(i, dict) and str(i.get('med', '')).isdigit()][:40]
    meds = {m.pk: m for m in Medication.objects.filter(pk__in=ids)}
    out = []
    for i in items:
        if isinstance(i, dict) and str(i.get('med', '')).isdigit() and int(i['med']) in meds:
            out.append({**{k: i.get(k) for k in ('dose', 'units', 'frequency', 'days', 'quantity', 'route')}, 'med': meds[int(i['med'])]})
    return out


@login_required
@require_POST
def api_rx(request):
    """Live prescribing advice for the lines on screen."""
    authorize(request, 'clinical')
    e = _encounter(request)
    if not e:
        return JsonResponse({'ready': False})
    rx = Prescription.objects.filter(pk=request.POST.get('prescription') or 0).first()
    F = drflow.rx_findings(e, parse_lines(request.POST.get('lines')), exclude_prescription=rx)
    return JsonResponse({'ready': True, 'findings': F, 'blocking': len(drflow.blocking(F))})


@login_required
@require_POST
def api_lab(request):
    """Live advice for the tests being ticked."""
    authorize(request, 'clinical')
    e = _encounter(request)
    if not e:
        return JsonResponse({'ready': False})
    ids = [int(x) for x in request.POST.get('tests', '').split(',') if x.isdigit()][:60]
    tests = list(LabTest.objects.filter(pk__in=ids).prefetch_related('parameters'))
    return JsonResponse({'ready': True, 'findings': drflow.lab_findings(e, tests)})


@login_required
@require_POST
def ask(request):
    """Ask about a test, a medicine or anything. Returns the hospital's facts now; the AI answer and pictures follow.
    Open to everyone with the Dr. Flow right (doctors, nurses and pharmacists by default); an answer only considers a
    patient the asker is allowed to see."""
    authorize(request, 'drflow')
    from .evidence_views import _dispatch
    from .tasks import drflow_ask_task
    kind = request.POST.get('kind', 'free')
    if kind not in dict(DrFlowAsk.KINDS):
        raise Http404
    tid = int(request.POST['id']) if str(request.POST.get('id', '')).isdigit() else None
    question = request.POST.get('question', '').strip()[:500]
    obj, name = drflow_ask.topic(kind, tid, question)
    if kind != 'free' and not obj:
        return JsonResponse({'error': 'Not found.'}, status=404)
    if kind == 'free' and len(question) < 3:
        return JsonResponse({'error': 'Type a question first.'}, status=400)
    e = _encounter(request)
    from .access import can_see
    if e and not can_see(request, e.patient_id):
        e = None
    personal = e if e and request.POST.get('personal', '1') == '1' else None
    f = drflow_ask.facts(kind, obj, e)
    key = '' if personal else drflow_ask.cache_key(kind, tid, name, question if kind != 'free' else question)
    a = None
    if key:
        a = DrFlowAsk.objects.filter(cache_key=key, status='done', error='', created_at__gte=timezone.now() - timezone.timedelta(days=30)).first()
    cached = bool(a)
    if not a:
        a = DrFlowAsk.objects.create(kind=kind, topic=name[:200], topic_id=tid, question=question, encounter=personal, requested_by=request.user, cache_key=key)
        _dispatch(drflow_ask_task, a.pk)
    audit(request, 'drflow_ask', f'drflow_ask:{a.pk}', {'kind': kind, 'topic': name[:80], 'personal': bool(personal), 'cached': cached})
    from .medical_ai import enabled
    return JsonResponse({'id': a.pk, 'poll': reverse('drflow_ask_status', args=[a.pk]), 'title': name if kind != 'free' else 'Your question',
                         'subtitle': {'test': 'Lab test', 'med': 'Medicine', 'free': question[:120]}[kind], 'facts': f['rows'],
                         'warnings': f['warnings'], 'ai': enabled(), 'images': drflow_ask.images_enabled(), 'cached': cached})


@login_required
def ask_status(request, pk):
    authorize(request, 'drflow')
    a = get_object_or_404(DrFlowAsk, pk=pk)
    if a.requested_by_id != request.user.pk and a.encounter_id:
        from .access import can_see
        if not can_see(request, a.encounter.patient_id):
            raise Http404
    from .templatetags.evidence_tags import simple_md
    running = a.busy
    return JsonResponse({'id': a.pk, 'status': 'running' if running else ('done' if a.status == 'done' else 'failed'),
                         'html': str(simple_md(a.text)) if a.text else '', 'images': a.images if not running else [],
                         'sources': [s for s in a.sources if str(s.get('url', '')).startswith('https://')][:8] if not running else [],
                         'error': a.error if not running else '', 'model': a.model_name})
