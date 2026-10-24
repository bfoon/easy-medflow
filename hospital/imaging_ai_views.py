"""Dr. Flow on the imaging page: analyse an image (labels + explanation), label its anatomy, ask questions about it or
about an area selected on it (quick look or deep dive), rate answers, and preview exactly what would be sent. JSON
endpoints used by imaging-ai.js. See imaging_ai.py for what leaves the server.

Also the studio's enhancement assistant (assist): a quality check and an enhancement recipe computed on this server
from the pixels (imaging_studio.py). Nothing is sent to an AI service for that."""
import base64
import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from . import imaging_ai
from .evidence_views import _dispatch
from .models import ImagingAIRun, ImagingImage
from .views import ROLES, audit, authorize, role_of

ROLES['imaging_ai'] = {'radiology', 'doctor', 'nurse', 'admin'}
MAX_RUNS_PER_IMAGE = 60
MAX_QUESTION = 1000
KINDS = ('analyse', 'question', 'anatomy', 'region', 'outline')


def _image(pk):
    return get_object_or_404(ImagingImage.objects.select_related('order__encounter__patient'), pk=pk)


def _body(request):
    try:
        data = json.loads(request.body or '{}')
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


@login_required
@require_GET
def thread(request, pk):
    """Everything Dr. Flow has said about one image, oldest first, and what this person may do."""
    authorize(request, 'imaging_ai')
    img = _image(pk)
    runs = img.ai_runs.select_related('requested_by').order_by('created_at')[:MAX_RUNS_PER_IMAGE]
    return JsonResponse({'enabled': imaging_ai.enabled(), 'image': img.pk, 'cancelled': img.order.status == 'cancelled',
                         'can_keep': role_of(request.user) in ROLES['imaging'],
                         'runs': [imaging_ai.serialize(r, request.user) for r in runs]})


@login_required
@require_POST
def ask(request, pk):
    """Start an analysis or a question on one image. One job per image at a time; the page polls run()."""
    authorize(request, 'imaging_ai')
    img = _image(pk)
    data = _body(request)
    if not imaging_ai.enabled():
        return JsonResponse({'ok': False, 'error': 'AI is not connected. Ask an administrator to configure it.'}, status=400)
    if img.order.status == 'cancelled':
        return JsonResponse({'ok': False, 'error': 'This study was cancelled.'}, status=400)
    if not data.get('confirm_no_identifiers'):
        return JsonResponse({'ok': False, 'error': 'Cover any name or number on the image and tick the confirmation first.'}, status=400)
    kind = data.get('kind') if data.get('kind') in KINDS else 'analyse'
    question = str(data.get('question') or '').strip()[:MAX_QUESTION]
    if kind == 'question' and not question:
        return JsonResponse({'ok': False, 'error': 'Type a question about the image.'}, status=400)
    region, depth, parent, shape = [], 'quick', None, []
    if kind == 'region':
        shape = imaging_ai.clean_shape(data.get('shape'))
        region = imaging_ai.clean_region(data.get('region') or (imaging_ai.shape_box(shape) if shape else None))
        if not region:
            return JsonResponse({'ok': False, 'error': 'Select an area on the image first (drag a box over it). It must not be tiny.'}, status=400)
        depth = 'deep' if data.get('depth') == 'deep' else 'quick'
        if data.get('parent'):
            parent = img.ai_runs.filter(pk=data.get('parent')).first() if str(data.get('parent')).isdigit() else None
    busy = img.ai_runs.filter(status__in=['queued', 'running']).order_by('-created_at').first()
    if busy and busy.busy:
        return JsonResponse({'ok': True, 'run': imaging_ai.serialize(busy, request.user), 'message': 'Dr. Flow is still working on this image.'})
    if img.ai_runs.count() >= MAX_RUNS_PER_IMAGE:
        return JsonResponse({'ok': False, 'error': 'This image has reached the limit of AI questions.'}, status=400)
    r = ImagingAIRun.objects.create(image=img, order=img.order, requested_by=request.user, kind=kind, question=question,
                                    redactions=imaging_ai.clean_redactions(data.get('redactions')), region=region or [], shape=shape if region else [],
                                    depth=depth, parent=parent)
    audit(request, 'imaging_ai_request', f'imaging:{img.order_id}', {'image': img.pk, 'run': r.pk, 'kind': kind, 'covered': len(r.redactions),
                                                                     **({'region': region, 'depth': depth, 'shape_points': len(shape)} if region else {})})
    from .tasks import imaging_ai_task
    _dispatch(imaging_ai_task, r.pk)
    r.refresh_from_db()
    return JsonResponse({'ok': True, 'run': imaging_ai.serialize(r, request.user)})


@login_required
@require_GET
def run(request, pk):
    authorize(request, 'imaging_ai')
    r = get_object_or_404(ImagingAIRun.objects.select_related('requested_by'), pk=pk)
    return JsonResponse({'ok': True, 'run': imaging_ai.serialize(r, request.user)})


@login_required
@require_POST
def rate(request, pk):
    authorize(request, 'imaging_ai')
    r = get_object_or_404(ImagingAIRun, pk=pk)
    v = str(_body(request).get('helpful', request.POST.get('helpful', '')))
    if v not in ('1', '0', 'True', 'False', 'true', 'false'):
        return HttpResponseBadRequest('helpful must be 1 or 0')
    r.helpful = v in ('1', 'True', 'true')
    r.save(update_fields=['helpful', 'updated_at'])
    audit(request, 'imaging_ai_rate', f'imaging_ai_run:{r.pk}', {'helpful': r.helpful})
    return JsonResponse({'ok': True, 'message': 'Thank you, feedback recorded.'})


@login_required
@require_POST
def preview(request, pk):
    """Exactly what would be sent for this image: the cleaned pixels (with covered boxes painted black) and the
    de-identified context. For the clinician to check before asking; nothing is sent to the AI here."""
    authorize(request, 'imaging_ai')
    img = _image(pk)
    data = _body(request)
    covered = imaging_ai.clean_redactions(data.get('redactions'))
    kind = data.get('kind') if data.get('kind') in KINDS else 'analyse'
    shape = imaging_ai.clean_shape(data.get('shape')) if kind == 'region' else []
    region = imaging_ai.clean_region(data.get('region') or (imaging_ai.shape_box(shape) if shape else None)) if kind == 'region' else None
    if kind == 'region' and not region:
        kind = 'question'
    probe = ImagingAIRun(image=img, order=img.order, kind=kind, question=str(data.get('question') or '')[:MAX_QUESTION], redactions=covered,
                         region=region or [], shape=shape if region else [], depth='deep' if data.get('depth') == 'deep' else 'quick')
    try:
        with img.file.open('rb') as f:
            pics = imaging_ai.prepare(probe, f)
    except (OSError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Could not read this image.'}, status=400)
    if kind in ('question', 'region'):
        ctx = imaging_ai.image_context(probe, include_draft=False)
        ctx['note'] = 'A question also sends the radiologist draft (names removed) and the earlier answers on this image.'
    else:
        ctx = imaging_ai.image_context(probe)
    audit(request, 'imaging_ai_preview', f'imaging:{img.order_id}', {'image': img.pk, 'covered': len(covered), 'kind': kind})
    jpeg, w, h = pics[0]
    return JsonResponse({'ok': True, 'width': w, 'height': h, 'bytes': sum(len(j) for j, _, _ in pics),
                         'image': 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode(),
                         'images': [{'image': 'data:image/jpeg;base64,' + base64.b64encode(j).decode(), 'width': pw, 'height': ph} for j, pw, ph in pics],
                         'context': json.dumps(ctx, indent=2, default=str), 'digest': imaging_ai.digest(b''.join(j for j, _, _ in pics))})


@login_required
@require_GET
def assist(request, pk):
    """Dr. Flow's enhancement assistant for the studio: how readable the picture is, what to improve, and a recipe for the
    studio controls with the reason for each step. Computed here from the pixels; nothing is sent to an AI service."""
    authorize(request, 'imaging_ai')
    img = _image(pk)
    from PIL import Image, ImageOps
    from . import imaging_studio as S
    try:
        with img.file.open('rb') as f:
            im = ImageOps.exif_transpose(Image.open(f))
            im.load()
        m = S.measure(im)
    except (OSError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Could not read this image.'}, status=400)
    o = img.order
    out = S.suggest(m, o.modality, o.region)
    return JsonResponse({'ok': True, 'metrics': m, **out, 'modality': o.get_modality_display(), 'region': o.region,
                         'presets': {k: {'label': v[0], 'recipe': v[1]} for k, v in S.PRESETS.items()},
                         'palettes': {k: v['label'] for k, v in S.PALETTES.items()}})
