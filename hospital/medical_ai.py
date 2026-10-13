"""AI next-step suggestions after lab results.

What is sent (from the server only, never from the browser): the de-identified visit context already used by
`clinical.deidentified_context` (no name, record number, phone, address, date of birth, real dates or free-text notes),
including the de-identified pharmacy and bedside sections from dr_flow_context.py,
plus the results of this request with the hospital range and the WHO references, what clinicians here did after
similar results (anonymous aggregates), and the summaries already fetched from trusted sources.

Three providers (CLINICAL_AI_PROVIDER):
  * anthropic: the Claude Messages API. With CLINICAL_AI_WEB_SEARCH on, Claude may search the web, but only on the
    domains in MEDICAL_TRUSTED_DOMAINS (WHO, Gambia MoH, MRC Unit The Gambia, NIH/NLM/PubMed, CDC, NICE, MSF, Cochrane, BMJ, Lancet, NEJM...), and
    every source it used is stored and shown.
  * openai (alias: gemini): any OpenAI-compatible Chat Completions API at CLINICAL_AI_ENDPOINT, authorised with
    CLINICAL_AI_TOKEN. Google Gemini works with
    CLINICAL_AI_ENDPOINT=https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
    (the base URL ending in /openai/ is also accepted). No web search; the model is told to rely on the data and the
    trusted sources already fetched, which are stored as the answer's sources.
  * endpoint: any approved service at CLINICAL_AI_ENDPOINT that accepts {task, context, instructions} and returns
    {"text": "...", "sources": [{"title", "url"}]}.

Busy or rate-limited services (HTTP 429/500/502/503/504) are retried CLINICAL_AI_RETRIES times (default 3) with a short
back-off. For the openai provider, CLINICAL_AI_FALLBACK_MODEL (optional) is tried once if the main model stays busy,
and the answer says which model produced it.

Every answer is an unverified suggestion. It is stored (AISuggestion) with a SHA-256 of what was sent, for audit.
"""
import hashlib
import json
import time
import urllib.error
import urllib.request

from django.conf import settings
from django.utils import timezone

SYSTEM_PROMPT = """You are a clinical decision-support assistant for doctors at a hospital in The Gambia, West Africa.
You receive DE-IDENTIFIED data about one patient visit and the laboratory results that have just been reported.

Rules:
- You advise; the doctor decides. Never state a definitive diagnosis. Say how confident you are.
- Ground every suggestion in (1) the patient's data provided, (2) this hospital's own aggregated practice data and
  protocols provided, and (3) evidence from respected medical sources, in this order:
  a. WHO guidelines.
  b. The Gambia Ministry of Health (moh.gov.gm): national standard treatment guidelines, the essential medicines list,
     and national programme guidance (e.g. the National Malaria Control Programme, TB/leprosy, HIV/AIDS, reproductive,
     maternal, newborn and child health, nutrition, immunisation).
  c. MRC Unit The Gambia at LSHTM (mrc.gm, lshtm.ac.uk/research/units/mrc-gambia): research from Gambian
     populations, e.g. on malaria, nutrition, vaccines, TB, hepatitis B and maternal and child health.
  d. Other national and international guidelines (e.g. NICE, CDC, MSF clinical guidelines), NIH/MedlinePlus, Cochrane
     and peer-reviewed literature.
- Where Gambian national guidance and WHO guidance differ, say so and say which you followed and why. Where MRC Unit
  The Gambia evidence describes Gambian populations differently from international data, point that out.
- Name the specific guideline or study you rely on. If you are not sure a specific Gambian document or study says
  something, say so instead of attributing it.
- Prefer guidance that fits a West African, resource-limited setting: consider malaria, sickle cell disease and
  other haemoglobinopathies, G6PD deficiency, TB, HIV, hepatitis B, helminths and malnutrition where relevant, and
  tests and medicines that are realistically available.
- When you use web search, cite the page for each recommendation that relies on it. Do not cite sources you did not see.
- Compare the hospital reference range with the WHO reference where both are given; say when they disagree and
  what that means for this patient.
- Put anything urgent or life-threatening first. Mention critical values explicitly.
- Do not invent doses. If you mention a medicine, refer to the guideline for the dose and check allergies listed.
- Use the pharmacy section: prefer medicines marked in stock in hospital_formulary; when the best choice is out of
  stock or low, say so and give an in-stock alternative. Check what the patient is already taking, whether it was
  dispensed, and doses refused, held or missed (a missed antibiotic or antimalarial can explain a poor response).
- Use the bedside section for inpatients: the bed type, devices (oxygen, IV fluids, catheter output, drains) and the
  observations and NEWS2 of the last 24 hours. Rising NEWS2, falling SpO2 or low urine output belong under urgent.
- If the data are insufficient, say exactly what is missing (history, examination, a repeat test, another test).
- Be concise and practical. Write in plain English for a doctor."""

# Lab-result reviews use a fixed structure; other tasks (Dr. Flow questions, report helpers) give their own format.
GENERAL_SYSTEM_PROMPT = SYSTEM_PROMPT
SYSTEM_PROMPT = SYSTEM_PROMPT + """

Answer with exactly these headings, in this order:
## Summary
## Urgent / red flags
## Suggested next steps
(numbered; each step with a one-line reason and the source)
## Differential considerations
## Hospital range vs WHO reference
## Gaps and uncertainties"""

NO_SEARCH_NOTE = ('\n\nWeb search is not available for this request. Rely on the patient data, the hospital data and the '
                  'trusted sources provided in the context. Do not cite any source that is not listed there; where you rely '
                  'on general guideline knowledge, name the guideline but do not invent a link.')


def provider():
    p = (getattr(settings, 'CLINICAL_AI_PROVIDER', '') or '').strip().lower()
    if p in ('openai', 'gemini'):
        return 'openai'
    if p in ('anthropic', 'endpoint'):
        return p
    return 'anthropic' if getattr(settings, 'ANTHROPIC_API_KEY', '') else 'endpoint'


def enabled():
    if not getattr(settings, 'CLINICAL_AI_ENABLED', False):
        return False
    p = provider()
    if p == 'anthropic':
        return bool(getattr(settings, 'ANTHROPIC_API_KEY', ''))
    if p == 'openai':
        return bool(getattr(settings, 'CLINICAL_AI_ENDPOINT', '')) and bool(getattr(settings, 'CLINICAL_AI_TOKEN', ''))
    return bool(getattr(settings, 'CLINICAL_AI_ENDPOINT', ''))


def model_name():
    return getattr(settings, 'CLINICAL_AI_MODEL', '') or 'claude-sonnet-5-5'


def lab_context(lr):
    """The de-identified visit context plus the focus of this request: results, references, practice and evidence."""
    from .clinical import deidentified_context
    from .evidence import request_guidance
    g = request_guidance(lr)
    start = lr.encounter.created_at
    rel = lambda dt: (dt - start).days if dt else None
    ctx = deidentified_context(lr.encounter)
    ctx['focus_lab_request'] = {
        'priority': lr.priority,
        'patient_group_used_for_who_references': {k: v for k, v in g['ctx'].items() if k in ('pregnant', 'trimester', 'inflammation', 'malaria')},
        'results': [{
            'test': r['o'].test.name, 'parameter': r['p'].name, 'value': r['v'].display, 'unit': r['p'].unit, 'flag': r['v'].get_flag_display(),
            'hospital_reference': r['range'] or None, 'day': rel(r['o'].resulted_at),
            'who_references': [{'label': w['ref'].label, 'value': w['label'], 'population': w['population'], 'outside': w['outside'],
                                'band': (w['band'] or {}).get('label'), 'source': w['ref'].citation_title} for w in r['who']],
            'hospital_vs_who': (r['agreement'] or {}).get('text'),
            'previous': {'value': r['prev'].display, 'flag': r['prev'].get_flag_display(), 'day': rel(r['prev'].order.resulted_at)} if r['prev'] else None,
        } for r in g['rows']],
    }
    ctx['hospital_practice_after_similar_results'] = [{
        'result': f"{_word(r['dir'])} {r['p'].name}", 'similar_patients': r['practice']['n'], 'window_days': r['practice']['days'],
        'tests_ordered_next': [f"{t['name']} ({t['pct']}%)" for t in r['practice']['tests']],
        'medicines_prescribed_next': [f"{m['name']} ({m['pct']}%, improved/resolved {m['success']}%)" for m in r['practice']['meds']],
        'outcomes': [f"{o['label']} {o['pct']}%" for o in r['practice']['outcomes']],
    } for r in g['abnormal'] if r['practice'] and r['practice']['n'] >= r['practice']['min_group']]
    ctx['trusted_sources_already_fetched'] = [{'result': f"{_word(r['dir'])} {r['p'].name}", 'source': it.get_source_display(), 'title': it.title,
                                               'url': it.url, 'summary': it.summary[:500]}
                                              for r in g['abnormal'] for it in r['evidence'][:3]][:15]
    ctx['hospital_protocols'] = [{'result': f"{_word(r['dir'])} {r['p'].name}", 'title': pr.title, 'steps': pr.step_list}
                                 for r in g['rows'] for pr in r['protocol']]
    return ctx


def _word(d):
    return {'L': 'Low', 'H': 'High', 'A': 'Abnormal'}.get(d, '')


def digest(ctx):
    return hashlib.sha256(json.dumps(ctx, sort_keys=True, default=str).encode()).hexdigest()


def _user_message(ctx, task_text):
    return f'{task_text}\n\nDe-identified context (JSON):\n{json.dumps(ctx, default=str, indent=1)}'


def _error_detail(raw):
    """Pull a readable message out of an error body. Handles Anthropic/OpenAI ({"error": {...}}) and
    Gemini's OpenAI-compatible layer, which can wrap the error in a list ([{"error": {...}}])."""
    if not raw:
        return ''
    try:
        data = json.loads(raw)
    except ValueError:
        return raw.strip()[:300]
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        err = data.get('error', data)
        if isinstance(err, dict):
            return str(err.get('message') or err.get('status') or '')[:300]
        if isinstance(err, str):
            return err[:300]
    return ''


RETRY_STATUSES = {429, 500, 502, 503, 504}


class AIServiceError(RuntimeError):
    """The AI service answered with an HTTP error. Subclass of RuntimeError, so existing handlers still catch it."""

    def __init__(self, status, detail=''):
        self.status = status
        super().__init__(f'AI service returned HTTP {status}{": " + detail if detail else ""}')


def _retry_delay(exc, attempt):
    """Seconds to wait before the next attempt: the server's Retry-After if given, else 2, 4, 8... capped at 30."""
    try:
        after = int((exc.headers or {}).get('Retry-After') or 0)
    except (TypeError, ValueError):
        after = 0
    return min(after if after > 0 else 2 ** (attempt + 1), 30)


def _post_json(url, body, headers, timeout):
    data = json.dumps(body, default=str).encode()
    retries = max(0, int(getattr(settings, 'CLINICAL_AI_RETRIES', 3)))
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method='POST', headers={'Content-Type': 'application/json', **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            raw = ''
            try:
                raw = exc.read().decode(errors='replace')
            except Exception:
                pass
            if exc.code in RETRY_STATUSES and attempt < retries:
                time.sleep(_retry_delay(exc, attempt))
                continue
            raise AIServiceError(exc.code, _error_detail(raw)) from None


def ask_anthropic(ctx, task_text, system=None):
    """Claude Messages API, optionally with the server-side web search tool limited to trusted medical domains.
    Returns (text, sources, searches)."""
    from .evidence import trusted_domains
    web_search = getattr(settings, 'CLINICAL_AI_WEB_SEARCH', True)
    body = {'model': model_name(), 'max_tokens': int(getattr(settings, 'CLINICAL_AI_MAX_TOKENS', 3000)), 'system': system or SYSTEM_PROMPT,
            'messages': [{'role': 'user', 'content': _user_message(ctx, task_text if web_search else task_text + NO_SEARCH_NOTE)}]}
    if web_search:
        body['tools'] = [{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': int(getattr(settings, 'CLINICAL_AI_MAX_SEARCHES', 5)),
                          'allowed_domains': trusted_domains()}]
    headers = {'x-api-key': settings.ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01'}
    url = (getattr(settings, 'ANTHROPIC_BASE_URL', '') or 'https://api.anthropic.com').rstrip('/') + '/v1/messages'
    texts, cited, found, searches = [], {}, {}, []
    for _ in range(4):                                   # a long search turn can pause; continue it up to 3 times
        resp = _post_json(url, body, headers, timeout=int(getattr(settings, 'CLINICAL_AI_TIMEOUT', 120)))
        blocks = resp.get('content') or []
        for b in blocks:
            t = b.get('type')
            if t == 'text':
                texts.append(b.get('text', ''))
                for c in b.get('citations') or []:
                    if c.get('url'):
                        cited.setdefault(c['url'], {'title': c.get('title') or c['url'], 'url': c['url'], 'cited': True,
                                                    'quote': (c.get('cited_text') or '')[:240]})
            elif t == 'server_tool_use' and (b.get('input') or {}).get('query') and b['input']['query'] not in searches:
                searches.append(b['input']['query'])
            elif t == 'web_search_tool_result' and isinstance(b.get('content'), list):
                for r in b['content']:
                    if r.get('url'):
                        found.setdefault(r['url'], {'title': r.get('title') or r['url'], 'url': r['url'], 'cited': False, 'quote': ''})
        if resp.get('stop_reason') != 'pause_turn':
            break
        body['messages'] = body['messages'] + [{'role': 'assistant', 'content': blocks}]
    sources = list(cited.values()) + [s for u, s in found.items() if u not in cited]
    return ''.join(texts).strip(), sources[:20], searches[:10]


def _chat_completions_url():
    url = (getattr(settings, 'CLINICAL_AI_ENDPOINT', '') or '').strip().rstrip('/')
    if not url.endswith('/chat/completions'):
        url += '/chat/completions'
    return url


def _provided_sources(ctx):
    """The trusted sources that were given to the model, stored as the answer's (uncited) sources."""
    out, seen = [], set()
    for it in ctx.get('trusted_sources_already_fetched') or []:
        url = it.get('url')
        if url and url not in seen:
            seen.add(url)
            title = it.get('title') or url
            out.append({'title': f"{it['source']}: {title}" if it.get('source') else title, 'url': url, 'cited': False, 'quote': ''})
    return out[:20]


def ask_openai(ctx, task_text, system=None):
    """OpenAI-compatible Chat Completions (Google Gemini, Azure OpenAI, local servers...). Returns (text, sources, searches)."""
    body = {
        'model': model_name(),
        # Reasoning models spend part of this budget thinking, so it is larger than the Claude default.
        'max_tokens': int(getattr(settings, 'CLINICAL_AI_OPENAI_MAX_TOKENS', 8192)),
        'messages': [
            {'role': 'system', 'content': system or SYSTEM_PROMPT},
            {'role': 'user', 'content': _user_message(ctx, task_text + NO_SEARCH_NOTE)},
        ],
    }
    headers = {'Authorization': f'Bearer {(getattr(settings, "CLINICAL_AI_TOKEN", "") or "").strip()}'}
    url, timeout = _chat_completions_url(), int(getattr(settings, 'CLINICAL_AI_TIMEOUT', 120))
    used_fallback = ''
    try:
        data = _post_json(url, body, headers, timeout=timeout)
    except AIServiceError as exc:
        fallback = (getattr(settings, 'CLINICAL_AI_FALLBACK_MODEL', '') or '').strip()
        if exc.status not in RETRY_STATUSES or not fallback or fallback == body['model']:
            raise
        data = _post_json(url, {**body, 'model': fallback}, headers, timeout=timeout)
        used_fallback = fallback
    choices = data.get('choices') if isinstance(data, dict) else None
    choice = choices[0] if choices else {}
    content = (choice.get('message') or {}).get('content') or ''
    if isinstance(content, list):                        # some servers return content parts
        content = ''.join(p.get('text', '') for p in content if isinstance(p, dict))
    text = content.strip()
    if text and choice.get('finish_reason') == 'length':
        text += '\n\n_(This answer was cut off at the length limit.)_'
    if text and used_fallback:
        text += f'\n\n_(Answered by the fallback model {used_fallback} because {body["model"]} was busy.)_'
    return text, _provided_sources(ctx), []


def ask_endpoint(ctx, task, task_text, system=None):
    body = {'task': task, 'context': ctx, 'instructions': (system or SYSTEM_PROMPT) + '\n\n' + task_text}
    headers = {'Authorization': f'Bearer {getattr(settings, "CLINICAL_AI_TOKEN", "")}'}
    data = _post_json(settings.CLINICAL_AI_ENDPOINT, body, headers, timeout=int(getattr(settings, 'CLINICAL_AI_TIMEOUT', 120)))
    text = data.get('text') or data.get('summary') or json.dumps(data, indent=1)
    sources = [{'title': s.get('title') or s.get('url'), 'url': s.get('url'), 'cited': True, 'quote': ''}
               for s in data.get('sources') or data.get('evidence') or [] if isinstance(s, dict) and s.get('url')]
    return text, sources, []


def _ask(ctx, task, task_text, system=None):
    """Send to the configured provider. Returns (text, sources, searches). `system` replaces the lab-review prompt."""
    p = provider()
    if p == 'anthropic':
        return ask_anthropic(ctx, task_text, system)
    if p == 'openai':
        return ask_openai(ctx, task_text, system)
    return ask_endpoint(ctx, task, task_text, system)


LAB_TASK = ('Laboratory results for this visit have just been reported. Suggest the next steps for the doctor: what to do now, '
            'what to repeat or add, what to look for, and when to refer. Use the hospital data and the trusted sources provided, '
            'and search the trusted medical sites for current guidance where it helps.')


def run_suggestion(pk):
    """Worker entry point: build the context, ask the provider, store the answer (or the error)."""
    from .models import AISuggestion
    s = AISuggestion.objects.select_related('lab_request__encounter__patient', 'encounter').get(pk=pk)
    if s.status not in ('queued', 'running'):
        return s
    p = provider()
    s.status, s.provider, s.model_name = 'running', p, model_name() if p in ('anthropic', 'openai') else 'endpoint'
    s.save(update_fields=['status', 'provider', 'model_name', 'updated_at'])
    try:
        if not enabled():
            raise RuntimeError('AI is not configured')
        from .views import lab_requests_qs
        lr = lab_requests_qs().get(pk=s.lab_request_id)
        ctx = lab_context(lr)
        s.context_digest = digest(ctx)
        s.text, s.sources, s.searches = _ask(ctx, 'lab_next_steps', LAB_TASK)
        if not s.text:
            raise RuntimeError('The AI service returned no text')
        s.status = 'done'
    except Exception as exc:
        s.status, s.error = 'failed', f'{exc.__class__.__name__}: {exc}'[:500]
    s.finished_at = timezone.now()
    s.save()
    return s


def review_encounter(encounter):
    """Visit-level review (used by clinical.ai_review). Returns a dict, or None when AI is off."""
    if not enabled():
        return None
    from .clinical import deidentified_context
    ctx = deidentified_context(encounter)
    task = 'Suggest missing work-up, flag possible misdiagnosis and safety issues for this visit. Advisory only.'
    try:
        text, sources, _ = _ask(ctx, 'clinical_review', task)
        return {'text': text, 'sources': sources, 'requires_clinician_review': True}
    except Exception as exc:
        return {'error': f'AI service unavailable: {exc.__class__.__name__}'}