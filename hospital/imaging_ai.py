"""Dr. Flow reads an image: labels drawn on it, an explanation, and answers to questions about it.

What is sent (from the server only, never from the browser):
  * the image itself, re-encoded on the server: EXIF/GPS and every other metadata field is dropped, it is turned
    upright, shrunk to CLINICAL_AI_IMAGE_MAX_SIDE pixels on the long side, and any boxes the clinician drew with
    "Cover names" are painted solid black first. A phone photo of a film often shows the patient's name on the film
    label, so the page asks the clinician to cover it (and to confirm) before anything is sent;
  * a de-identified context: modality, region, the clinical question and captions with the patient's name, record
    number and phone removed, sex and age band, the visit diagnosis, calibration and the names of measurements;
  * for questions only: the radiologist's draft findings (also scrubbed) and the earlier questions and answers on
    this image. A first analysis is deliberately blind to the draft so it is an independent second read.

Providers are the same as medical_ai (CLINICAL_AI_PROVIDER):
  * anthropic: Claude Messages API with an image block (no web search for imaging);
  * openai (alias gemini): any OpenAI-compatible Chat Completions API with an image_url data URI part. Google Gemini
    works with CLINICAL_AI_ENDPOINT=https://generativelanguage.googleapis.com/v1beta/openai/ and a vision model;
  * endpoint: your approved service receives {task, context, instructions, image: {media_type, data}} and returns
    {"text": "<the JSON answer>"}.

The model answers in JSON. Positions use Gemini's native convention, [ymin, xmin, ymax, xmax] scaled 0-1000, which
Claude also follows well; they are converted to fractions of the image (0-1) so the viewer can draw them whatever
the zoom, rotation or flip. Labels are approximate and are shown as AI labels, never as measurements.

Every answer is an unverified suggestion, stored (ImagingAIRun) with SHA-256 digests of the pixels and context sent.
"""
import base64
import hashlib
import io
import json
import re

from django.conf import settings
from django.utils import timezone

from . import medical_ai

CONCERNS = ('normal', 'watch', 'abnormal', 'urgent')
CONFIDENCE = ('low', 'moderate', 'high')
MAX_LABELS = 20

SYSTEM_PROMPT = """You are Dr. Flow, an imaging decision-support assistant for doctors and radiographers at a hospital
in The Gambia, West Africa. You look at ONE medical image (an X-ray, CT or MRI slice, ultrasound frame, ECG strip,
echo still, or a phone photo of a film on a light box) together with DE-IDENTIFIED context.

Rules:
- You advise; the clinician decides. Never state a definitive diagnosis. Say how confident you are for each finding.
- Describe only what is visible in this image. If something cannot be judged from one view or one slice, say so.
- Comment on image quality first (exposure, rotation, positioning, inspiration, artefacts, film glare, blur, crop).
  If quality is too poor to read safely, say that clearly and still describe what you can.
- Label every finding you mention, including important NORMAL landmarks that help the clinician orient (for a chest
  X-ray: trachea, heart border, costophrenic angles, hemidiaphragms; for a fracture: the bone and the fracture line).
- Put anything urgent or life-threatening first (e.g. tension pneumothorax, free air, large effusion, displaced
  fracture of the cervical spine, ST elevation) and mark it concern "urgent".
- Think about conditions common in West Africa where they fit the image: TB (cavities, upper-zone change, miliary
  pattern, hilar nodes), pneumonia, pleural effusion and empyema, cardiomegaly from rheumatic or hypertensive heart
  disease, sickle cell bone and chest changes, osteomyelitis, trauma from road traffic accidents, HIV-related disease.
- Never read text that identifies the patient (names, numbers, dates) even if some is visible; do not repeat it.
- Do not invent measurements in millimetres unless a calibration is given; describe size relative to anatomy instead.
- Be concise and practical. Plain English for a clinician.

Positions: give every label a box_2d [ymin, xmin, ymax, xmax] or a point [y, x], as integers from 0 to 1000 relative
to the full image as you see it (0,0 is the top-left corner). Use a box for a region or structure and a point for a
thin line, a tip, or a small spot. Be as accurate as you can; the boxes are drawn on the image for the clinician.

Answer with ONE JSON object and nothing else (no Markdown fences, no text before or after):
{
 "summary": "one or two sentences: the main finding or the direct answer",
 "quality": "one short sentence on image quality",
 "labels": [
  {"name": "short label, max 6 words", "box_2d": [ymin, xmin, ymax, xmax] or null, "point": [y, x] or null,
   "explanation": "what it is, why it matters, what to check next (1-3 sentences)",
   "concern": "normal | watch | abnormal | urgent", "confidence": "low | moderate | high"}
 ],
 "explanation": "Markdown for the clinician. For an analysis use these headings: ## Findings, ## Impression
 (suggested, for the clinician to confirm), ## Suggested next steps, ## Differential considerations. Refer to labels as
 [1], [2] in the order of the labels list. For a question, answer it directly under the heading ## Answer and refer to
 labels the same way.",
 "limitations": "what cannot be judged from this image and what is missing"
}"""

ANALYSE_TASK = ('Read this image. Label the findings and the key landmarks on it, explain them, and suggest an '
                'impression and next steps for the clinician to confirm.')

QUESTION_TASK = ('The clinician has a question about this image. Answer it directly. Label on the image any '
                 'structure or finding your answer refers to (labels may be an empty list if none apply). Keep earlier '
                 'answers in the conversation in mind, but look at the image again.\n\nQuestion: {question}')


# ------------------------------------------------------------------ settings
def max_side():
    return max(512, min(int(getattr(settings, 'CLINICAL_AI_IMAGE_MAX_SIDE', 1568)), 3072))


def enabled():
    return medical_ai.enabled()


# ------------------------------------------------------------------ the pixels
def clean_redactions(raw):
    """Boxes [x, y, w, h] as fractions of the image (0-1), from the browser. Up to 20; tiny or invalid boxes dropped."""
    out = []
    for b in (raw or [])[:20]:
        try:
            x, y, w, h = (float(v) for v in b)
        except (TypeError, ValueError):
            continue
        x, y = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
        w, h = min(max(w, 0.0), 1.0 - x), min(max(h, 0.0), 1.0 - y)
        if w * h >= 1e-5:
            out.append([round(x, 4), round(y, 4), round(w, 4), round(h, 4)])
    return out


def prepare_image(fileobj, redactions=()):
    """Return (jpeg_bytes, width, height) ready to send: upright, no metadata, shrunk, covered boxes painted black.
    Re-encoding from raw pixels is what drops EXIF (camera, GPS, time) and any embedded comments."""
    from PIL import Image, ImageDraw, ImageOps
    im = Image.open(fileobj)
    im.load()
    im = ImageOps.exif_transpose(im)                      # what the browser shows is what the AI sees
    if im.mode in ('RGBA', 'LA', 'P'):
        bg = Image.new('RGB', im.size, (0, 0, 0))
        rgba = im.convert('RGBA')
        bg.paste(rgba, mask=rgba.split()[-1])
        im = bg
    elif im.mode not in ('RGB', 'L'):
        im = im.convert('RGB')
    side = max_side()
    if max(im.size) > side:
        k = side / max(im.size)
        im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    if redactions:
        im = im.convert('RGB') if im.mode == 'L' else im
        d = ImageDraw.Draw(im)
        for x, y, w, h in redactions:
            d.rectangle([x * im.width, y * im.height, (x + w) * im.width, (y + h) * im.height], fill=(0, 0, 0))
    clean = Image.new(im.mode, im.size)                   # copy pixels only: nothing else survives
    clean.paste(im)
    buf = io.BytesIO()
    clean.save(buf, 'JPEG', quality=90, optimize=True)
    return buf.getvalue(), clean.width, clean.height


# ------------------------------------------------------------------ the words
def _scrub(text, patient, limit=1500):
    """Remove the patient's names, record number and phone from free text before it leaves the server."""
    t = str(text or '')[:limit]
    if not t or patient is None:
        return t
    tokens = {patient.mrn, patient.phone, patient.first_name, patient.last_name, f'{patient.first_name} {patient.last_name}'}
    tokens |= set((patient.first_name or '').split()) | set((patient.last_name or '').split())
    for tok in sorted({x.strip() for x in tokens if x and len(x.strip()) >= 2}, key=len, reverse=True):
        t = re.sub(rf'(?i)(?<![\w]){re.escape(tok)}(?![\w])', '[patient]', t)
    digits = re.sub(r'\D', '', patient.phone or '')
    if len(digits) >= 6:
        t = t.replace(digits, '[phone]')
    t = re.sub(r'\bMF-[0-9A-F]{6,}\b', '[record]', t)          # any record number, not only this patient's
    return t


def image_context(run, include_draft=False):
    """The de-identified context sent with the image. No name, record number, phone, address, date of birth or dates."""
    from .clinical import _age_band
    img, o = run.image, run.order
    e, p = o.encounter, o.encounter.patient
    measures = []
    for a in (img.annotations or [])[:40]:
        name = _scrub(a.get('label') or a.get('text') or '', p, 120)
        if name or a.get('type') in ('ruler', 'angle', 'cobb', 'ellipse'):
            measures.append({'type': a.get('type'), 'name': name or None})
    ctx = {
        'study': {'modality': o.get_modality_display(), 'region': _scrub(o.region, p, 120), 'body_system': o.get_body_system_display(),
                  'priority': o.priority, 'clinical_question': _scrub(o.clinical_question, p) or None},
        'image': {'caption': _scrub(img.caption, p, 120) or None,
                  'processed_copy_of_a_photo': bool(img.derived_from_id or img.processing),
                  'processing_steps': [k for k in (img.processing or {}) if k not in ('source_image', 'resized', 'corners')],
                  'mm_per_pixel_of_original': img.mm_per_pixel,
                  'clinician_measurements_and_notes': measures,
                  'areas_covered_in_black_for_privacy': len(run.redactions or [])},
        'patient': {'sex': p.sex, 'age_band': _age_band(p)},
        'visit': {'department': str(e.department or ''), 'working_diagnosis': _scrub(e.diagnosis, p, 300) or None},
    }
    if include_draft:
        ctx['radiologist_draft'] = {'findings': _scrub(o.findings, p, 3000) or None, 'impression': _scrub(o.impression, p, 800) or None,
                                    'measurements': [{'label': _scrub(m.get('label'), p, 60), 'value': m.get('value'), 'unit': m.get('unit')}
                                                     for m in (o.measurements or [])[:20]]}
        earlier = []
        for r in run.image.ai_runs.filter(status='done', created_at__lt=run.created_at).order_by('-created_at')[:6]:
            earlier.append({'asked': _scrub(r.question, p, 600) if r.kind == 'question' else 'Full analysis of the image',
                            'answer_summary': r.summary[:600], 'labels': [lb.get('name') for lb in (r.labels or [])][:MAX_LABELS]})
        ctx['earlier_questions_on_this_image'] = list(reversed(earlier))
    return ctx


def digest(data):
    if isinstance(data, (bytes, bytearray)):
        return hashlib.sha256(data).hexdigest()
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def task_text(run):
    return ANALYSE_TASK if run.kind == 'analyse' else QUESTION_TASK.format(question=_scrub(run.question, run.order.encounter.patient, 1000))


def _user_text(ctx, task, w, h):
    return f'{task}\n\nThe image is {w} x {h} pixels.\n\nDe-identified context (JSON):\n{json.dumps(ctx, default=str, indent=1)}'


# ------------------------------------------------------------------ providers (same settings as medical_ai)
def ask_anthropic(ctx, task, jpeg, w, h):
    body = {'model': medical_ai.model_name(), 'max_tokens': int(getattr(settings, 'CLINICAL_AI_IMAGING_MAX_TOKENS', 4000)),
            'system': SYSTEM_PROMPT,
            'messages': [{'role': 'user', 'content': [
                {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': base64.b64encode(jpeg).decode()}},
                {'type': 'text', 'text': _user_text(ctx, task, w, h)}]}]}
    headers = {'x-api-key': settings.ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01'}
    url = (getattr(settings, 'ANTHROPIC_BASE_URL', '') or 'https://api.anthropic.com').rstrip('/') + '/v1/messages'
    resp = medical_ai._post_json(url, body, headers, timeout=int(getattr(settings, 'CLINICAL_AI_TIMEOUT', 120)))
    text = ''.join(b.get('text', '') for b in resp.get('content') or [] if b.get('type') == 'text').strip()
    return text, '', resp.get('stop_reason') == 'max_tokens'


def ask_openai(ctx, task, jpeg, w, h):
    """OpenAI-compatible Chat Completions with an image part (Google Gemini, Azure OpenAI, local vision servers)."""
    body = {'model': medical_ai.model_name(),
            'max_tokens': int(getattr(settings, 'CLINICAL_AI_OPENAI_MAX_TOKENS', 8192)),
            'messages': [{'role': 'system', 'content': SYSTEM_PROMPT},
                         {'role': 'user', 'content': [
                             {'type': 'text', 'text': _user_text(ctx, task, w, h)},
                             {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode()}}]}]}
    headers = {'Authorization': f'Bearer {(getattr(settings, "CLINICAL_AI_TOKEN", "") or "").strip()}'}
    url, timeout = medical_ai._chat_completions_url(), int(getattr(settings, 'CLINICAL_AI_TIMEOUT', 120))
    used = ''
    try:
        data = medical_ai._post_json(url, body, headers, timeout=timeout)
    except medical_ai.AIServiceError as exc:
        fallback = (getattr(settings, 'CLINICAL_AI_FALLBACK_MODEL', '') or '').strip()
        if exc.status not in medical_ai.RETRY_STATUSES or not fallback or fallback == body['model']:
            raise
        data = medical_ai._post_json(url, {**body, 'model': fallback}, headers, timeout=timeout)
        used = fallback
    choices = data.get('choices') if isinstance(data, dict) else None
    choice = choices[0] if choices else {}
    content = (choice.get('message') or {}).get('content') or ''
    if isinstance(content, list):
        content = ''.join(part.get('text', '') for part in content if isinstance(part, dict))
    return content.strip(), used, choice.get('finish_reason') == 'length'


def ask_endpoint(ctx, task, jpeg, w, h, kind):
    body = {'task': f'imaging_{kind}', 'context': ctx, 'instructions': SYSTEM_PROMPT + '\n\n' + _user_text({}, task, w, h),
            'image': {'media_type': 'image/jpeg', 'data': base64.b64encode(jpeg).decode(), 'width': w, 'height': h}}
    headers = {'Authorization': f'Bearer {getattr(settings, "CLINICAL_AI_TOKEN", "")}'}
    data = medical_ai._post_json(settings.CLINICAL_AI_ENDPOINT, body, headers, timeout=int(getattr(settings, 'CLINICAL_AI_TIMEOUT', 120)))
    if isinstance(data, dict) and isinstance(data.get('labels'), list):
        return json.dumps(data), '', False
    return str((data or {}).get('text') or ''), '', False


# ------------------------------------------------------------------ reading the answer
def _json_block(text):
    """The JSON object in the model's answer, even if it added fences or a sentence around it."""
    t = (text or '').strip()
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', t, flags=re.I).strip()
    try:
        return json.loads(t)
    except ValueError:
        pass
    a, b = t.find('{'), t.rfind('}')
    if a >= 0 and b > a:
        try:
            return json.loads(t[a:b + 1])
        except ValueError:
            return None
    return None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _box(raw):
    """[ymin, xmin, ymax, xmax] 0-1000 → [x, y, w, h] 0-1. Also accepts 0-1 fractions."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    v = [_num(x) for x in raw]
    if any(x is None for x in v):
        return None
    scale = 1.0 if max(v) <= 1.0 else 1000.0
    y0, x0, y1, x1 = (min(max(x / scale, 0.0), 1.0) for x in v)
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    if (x1 - x0) * (y1 - y0) < 1e-5:
        return None
    return [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]


def _point(raw):
    """[y, x] 0-1000 → [x, y] 0-1."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None
    v = [_num(x) for x in raw]
    if any(x is None for x in v):
        return None
    scale = 1.0 if max(v) <= 1.0 else 1000.0
    return [round(min(max(v[1] / scale, 0.0), 1.0), 4), round(min(max(v[0] / scale, 0.0), 1.0), 4)]


def parse_answer(text):
    """Return a dict {summary, quality, labels, explanation, limitations}. A non-JSON answer is kept as the
    explanation with no labels, so nothing the AI wrote is lost."""
    data = _json_block(text)
    if not isinstance(data, dict):
        return {'summary': '', 'quality': '', 'labels': [], 'explanation': (text or '').strip()[:20000], 'limitations': ''}
    labels = []
    for raw in data.get('labels') or []:
        if not isinstance(raw, dict) or len(labels) >= MAX_LABELS:
            continue
        name = str(raw.get('name') or '').strip()[:80]
        box, point = _box(raw.get('box_2d') or raw.get('box')), _point(raw.get('point'))
        if not name:
            continue
        concern = str(raw.get('concern') or '').strip().lower()
        conf = str(raw.get('confidence') or '').strip().lower()
        labels.append({'n': len(labels) + 1, 'name': name, 'box': box, 'point': None if box else point,
                       'explanation': str(raw.get('explanation') or '').strip()[:1200],
                       'concern': concern if concern in CONCERNS else 'watch',
                       'confidence': conf if conf in CONFIDENCE else 'low'})
    s = lambda k, n: str(data.get(k) or '').strip()[:n]
    return {'summary': s('summary', 1000), 'quality': s('quality', 300), 'labels': labels,
            'explanation': s('explanation', 20000), 'limitations': s('limitations', 3000)}


# ------------------------------------------------------------------ the worker
def run(pk):
    """Worker entry point: prepare the pixels and the context, ask the provider, store the answer (or the error)."""
    from .models import ImagingAIRun
    r = (ImagingAIRun.objects.select_related('image__order__encounter__patient', 'order__encounter__patient', 'order__encounter__department')
         .get(pk=pk))
    if r.status not in ('queued', 'running'):
        return r
    prov = medical_ai.provider()
    r.status, r.provider = 'running', prov
    r.model_name = medical_ai.model_name() if prov in ('anthropic', 'openai') else 'endpoint'
    r.save(update_fields=['status', 'provider', 'model_name', 'updated_at'])
    try:
        if not enabled():
            raise RuntimeError('AI is not configured')
        with r.image.file.open('rb') as f:
            jpeg, w, h = prepare_image(f, r.redactions)
        ctx = image_context(r, include_draft=r.kind == 'question')
        r.image_digest, r.context_digest = digest(jpeg), digest(ctx)
        task = task_text(r)
        if prov == 'anthropic':
            text, used, cut = ask_anthropic(ctx, task, jpeg, w, h)
        elif prov == 'openai':
            text, used, cut = ask_openai(ctx, task, jpeg, w, h)
        else:
            text, used, cut = ask_endpoint(ctx, task, jpeg, w, h, r.kind)
        if not text:
            raise RuntimeError('The AI service returned no text')
        ans = parse_answer(text)
        if not (ans['summary'] or ans['explanation'] or ans['labels']):
            raise RuntimeError('The AI answer was empty')
        notes = []
        if cut:
            notes.append('_(This answer was cut off at the length limit; some labels may be missing.)_')
        if used:
            notes.append(f'_(Answered by the fallback model {used} because {r.model_name} was busy.)_')
            r.model_name = used[:80]
        r.summary, r.quality, r.labels, r.limitations = ans['summary'], ans['quality'], ans['labels'], ans['limitations']
        r.text = '\n\n'.join([ans['explanation']] + notes).strip()
        r.status = 'done'
    except Exception as exc:
        r.status, r.error = 'failed', f'{exc.__class__.__name__}: {exc}'[:500]
    r.finished_at = timezone.now()
    r.save()
    return r


def serialize(r, user=None):
    return {'id': r.pk, 'image': r.image_id, 'kind': r.kind, 'question': r.question, 'status': r.status,
            'busy': r.busy, 'summary': r.summary, 'text': r.text, 'labels': r.labels, 'quality': r.quality,
            'limitations': r.limitations, 'covered': len(r.redactions or []), 'model': r.model_name,
            'error': 'The AI service did not answer. Try again in a moment.' if r.status == 'failed' else '',
            'helpful': r.helpful, 'mine': bool(user and r.requested_by_id == user.pk),
            'by': (r.requested_by.get_full_name() or r.requested_by.get_username()) if r.requested_by_id else '',
            'at': timezone.localtime(r.created_at).strftime('%d %b %H:%M')}
