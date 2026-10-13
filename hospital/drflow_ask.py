"""Ask Dr. Flow about a lab test, a medicine or anything else.

Three parts, shown together in Dr. Flow's card:
  1. Facts from this hospital's own catalogue and stock (instant, no AI).
  2. An AI explanation, de-identified, optionally about this patient (only when AI is configured).
  3. Pictures from open medical image sources: NLM Open-i (figures from open-access articles, U.S. National Library of
     Medicine) and Wikimedia Commons, with a link back to each source. No patient data is ever sent to them.
"""
import hashlib
import json
import urllib.parse
import urllib.request

from django.conf import settings
from django.utils import timezone

IMAGE_API_HOSTS = ('openi.nlm.nih.gov', 'en.wikipedia.org')
IMAGE_FILE_PREFIXES = ('https://openi.nlm.nih.gov/', 'https://upload.wikimedia.org/')
SKIP_IMAGE_WORDS = ('icon', 'logo', 'symbol', 'flag_of', 'question_book', 'commons-logo', 'wiktionary', 'edit-clear', 'padlock',
                    'ambox', 'portal', 'wikidata', 'nuvola', 'crystal_clear')

CLASS_LABELS = {'nsaid': 'NSAID', 'aspirin': 'Salicylate', 'anticoagulant': 'Anticoagulant', 'antiplatelet': 'Antiplatelet',
                'ace_inhibitor': 'ACE inhibitor', 'arb': 'Angiotensin receptor blocker', 'loop_diuretic': 'Loop diuretic',
                'thiazide': 'Thiazide diuretic', 'beta_blocker': 'Beta-blocker', 'aminoglycoside': 'Aminoglycoside',
                'fluoroquinolone': 'Fluoroquinolone', 'tetracycline': 'Tetracycline', 'opioid': 'Opioid', 'benzodiazepine': 'Benzodiazepine',
                'ssri': 'SSRI antidepressant', 'tca': 'Tricyclic antidepressant', 'statin': 'Statin', 'sulfonylurea': 'Sulfonylurea',
                'antimalarial': 'Antimalarial', 'anti_tb': 'Anti-TB medicine', 'antibiotic': 'Antibiotic', 'steroid': 'Corticosteroid',
                'qt': 'Can lengthen the QT interval', 'oxidant': 'Avoid in G6PD deficiency', 'inducer': 'Enzyme inducer'}

ASK_TASK = """A doctor asks Dr. Flow, the hospital's AI assistant, about {what}: "{topic}".{question}
Answer in under 280 words for a busy doctor in The Gambia. Use these headings and leave out any that do not apply:
## What it is
## When to use it
{how}
## Cautions
{patient}Name the guideline or source behind each key point (WHO, Gambia MoH, BNF, NICE...). The hospital's own facts about
this {what} are in the context as topic_facts; do not contradict them."""
HOW_TEST = '## How to read the result\n(typical abnormal patterns and what they suggest; say that the hospital range on the report applies)'
HOW_MED = '## How it is given\n(route and usual regimen; for doses refer to the national guideline, WHO or BNF and do not invent numbers)'
FOR_PATIENT = '## For this patient\n(only from the de-identified patient context provided: what matters for this patient, including the rule findings)\n'


def images_enabled():
    flag = getattr(settings, 'DRFLOW_IMAGES', None)
    if flag is not None:
        return bool(flag)
    from .evidence import fetch_enabled
    return fetch_enabled()


def _get_json(url, timeout=10):
    host = urllib.parse.urlparse(url).hostname or ''
    if not url.startswith('https://') or host not in IMAGE_API_HOSTS:
        raise ValueError(f'Not an allowed image source: {url}')
    from .evidence import user_agent
    req = urllib.request.Request(url, headers={'User-Agent': user_agent(), 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(2_000_000).decode('utf-8', 'replace'))


def _clean_caption(s, n=220):
    import re
    s = re.sub(r'<[^>]+>', '', str(s or ''))
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:n] + ('…' if len(s) > n else '')


def openi_images(query, n=4):
    """Figures from open-access articles indexed by the U.S. National Library of Medicine (Open-i)."""
    data = _get_json('https://openi.nlm.nih.gov/api/search?' + urllib.parse.urlencode({'query': query, 'm': 1, 'n': n * 2}))
    out = []
    for it in data.get('list') or []:
        thumb, large = it.get('imgThumb') or it.get('imgGrid150'), it.get('imgLarge') or it.get('imgThumb')
        if not thumb or not large:
            continue
        thumb, large = urllib.parse.urljoin('https://openi.nlm.nih.gov/', thumb), urllib.parse.urljoin('https://openi.nlm.nih.gov/', large)
        pmc = it.get('pmcid') or ''
        page = f'https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc}/' if pmc else 'https://openi.nlm.nih.gov/'
        caption = _clean_caption((it.get('image') or {}).get('caption') or it.get('title'))
        out.append({'thumb': thumb, 'full': large, 'caption': caption, 'source': 'NLM Open-i', 'page': page,
                    'credit': _clean_caption(it.get('journal_title') or it.get('title') or 'Open-access article', 90)})
        if len(out) >= n:
            break
    return out


def wikimedia_images(query, n=4):
    """Images from the Wikipedia article that best matches the query (files hosted on Wikimedia Commons)."""
    found = _get_json('https://en.wikipedia.org/w/api.php?' + urllib.parse.urlencode(
        {'action': 'query', 'list': 'search', 'srsearch': query, 'srlimit': 1, 'format': 'json', 'utf8': 1}))
    hits = (found.get('query') or {}).get('search') or []
    if not hits:
        return []
    title = hits[0]['title']
    media = _get_json('https://en.wikipedia.org/api/rest_v1/page/media-list/' + urllib.parse.quote(title.replace(' ', '_'), safe=''))
    out = []
    for it in media.get('items') or []:
        name = (it.get('title') or '').lower()
        if it.get('type') != 'image' or any(w in name for w in SKIP_IMAGE_WORDS):
            continue
        srcs = it.get('srcset') or []
        if not srcs:
            continue
        src = srcs[-1].get('src') or srcs[0].get('src')
        src = 'https:' + src if src.startswith('//') else src
        thumb = srcs[0].get('src')
        thumb = 'https:' + thumb if thumb and thumb.startswith('//') else thumb or src
        out.append({'thumb': thumb, 'full': src, 'caption': _clean_caption((it.get('caption') or {}).get('text') or it.get('title', '').replace('File:', '')),
                    'source': 'Wikimedia Commons', 'page': 'https://commons.wikimedia.org/wiki/' + urllib.parse.quote(it.get('title', '').replace(' ', '_')),
                    'credit': f'Wikipedia: {title}'})
        if len(out) >= n:
            break
    return out


def find_images(kind, query, n=6):
    """Up to n pictures; tests and questions favour clinical figures, medicines favour the encyclopaedia article."""
    order = (wikimedia_images, openi_images) if kind == 'med' else (openi_images, wikimedia_images)
    out, errors = [], []
    for fn in order:
        try:
            out += fn(query, n=4)
        except Exception as exc:                   # an unreachable source must never break the answer
            errors.append(f'{fn.__name__}: {exc.__class__.__name__}')
    safe = [i for i in out if str(i.get('thumb', '')).startswith(IMAGE_FILE_PREFIXES) and str(i.get('full', '')).startswith(IMAGE_FILE_PREFIXES)]
    return safe[:n], errors


# ------------------------------------------------------------------ facts from the hospital's own data
def topic(kind, topic_id, text):
    from .models import LabTest, Medication
    if kind == 'test':
        t = LabTest.objects.filter(pk=topic_id).prefetch_related('parameters').first()
        return t, (t.name if t else text)
    if kind == 'med':
        m = Medication.objects.filter(pk=topic_id).first()
        return m, (str(m) if m else text)
    return None, text


def facts(kind, obj, encounter=None):
    """Plain facts for the card: what the hospital knows about this test or medicine, and rule findings for this patient."""
    from django.urls import reverse
    rows, warnings = [], []
    if kind == 'test' and obj:
        sex = encounter.patient.sex if encounter else None
        rows += [('Sample', ' · '.join(x for x in (obj.sample_type, obj.container) if x) or '—'), ('Turnaround', f'about {obj.turnaround_hours} h')]
        params = list(obj.parameters.all())
        if params:
            rng = lambda p: (p.range_label(sex) or '') if (p.range_label(sex) or '').strip() not in ('< 0', '<0') else ''   # "below zero" means none expected
            rows.append(('Measures', '; '.join(f'{p.name}' + (f' ({rng(p)} {p.unit})'.replace(' )', ')') if rng(p) else '') for p in params[:8])))
        if obj.price:
            rows.append(('Price', f'{obj.price:,.2f}'))
        if obj.description:
            rows.append(('Notes', obj.description[:300]))
        if encounter:
            from .models import LabOrder
            last = (LabOrder.objects.filter(encounter__patient=encounter.patient, test=obj, status__in=['resulted', 'verified'])
                    .order_by('-resulted_at').prefetch_related('values__parameter').first())
            if last and last.resulted_at:
                rows.append(('Last result', f'{timezone.localtime(last.resulted_at):%d %b %Y}: ' + ', '.join(
                    f'{v.parameter.name} {v.display} {v.parameter.unit}'.strip() + (f' ({v.get_flag_display().lower()})' if v.flag not in ('', 'N') else '')
                    for v in list(last.values.all())[:4])))
            from .drflow import lab_findings
            warnings = [f for f in lab_findings(encounter, [obj]) if f.get('ask', {}) and f['ask'].get('id') == obj.pk]
    elif kind == 'med' and obj:
        from .drflow import classes_of, rx_findings
        from .services import availability
        rows += [('Form', ' '.join(x for x in (obj.strength, obj.form or obj.get_unit_display()) if x) or '—'),
                 ('Group', obj.get_category_display()),
                 ('In the pharmacy', f'{availability(obj)} {obj.get_unit_display().lower()}s in stock')]
        labels = [CLASS_LABELS[c] for c in sorted(classes_of(obj)) if c in CLASS_LABELS]
        if labels:
            rows.append(('Class', ', '.join(dict.fromkeys(labels))))
        flags = [x for x, on in (('On the national essential medicines list', obj.essential), ('Controlled drug: witness needed', obj.controlled),
                                 ('Keep at 2-8 °C', obj.cold_chain)) if on]
        if flags:
            rows.append(('Notes', '; '.join(flags)))
        if encounter:
            warnings = rx_findings(encounter, [{'med': obj, 'route': 'oral'}])
    return {'rows': [{'label': a, 'value': b} for a, b in rows], 'warnings': warnings[:6]}


def cache_key(kind, topic_id, topic_text, question):
    return hashlib.sha256(f'{kind}|{topic_id or ""}|{topic_text.strip().lower()}|{question.strip().lower()}'.encode()).hexdigest()


def run_ask(pk):
    """Worker entry point: pictures from the open sources, then the AI answer. Either may be missing; the card copes."""
    from . import medical_ai
    from .models import DrFlowAsk
    a = DrFlowAsk.objects.select_related('encounter__patient').get(pk=pk)
    if a.status not in ('queued', 'running'):
        return a
    a.status = 'running'
    a.save(update_fields=['status', 'updated_at'])
    obj, name = topic(a.kind, a.topic_id, a.topic)
    if images_enabled():
        query = a.question if a.kind == 'free' else (obj.generic_name or obj.name) if a.kind == 'med' and obj else name
        a.images, _errs = find_images(a.kind, query[:120])
    try:
        if medical_ai.enabled():
            what = {'test': 'a laboratory test', 'med': 'a medicine', 'free': 'a clinical question'}[a.kind]
            ctx = {'topic_facts': facts(a.kind, obj)['rows']}
            if a.encounter_id:
                from .clinical import deidentified_context
                ctx['patient'] = deidentified_context(a.encounter)
                ctx['rule_findings_for_this_patient'] = [f"{f['level']}: {f['title']} - {f['detail']}" for f in facts(a.kind, obj, a.encounter)['warnings']]
            task = ASK_TASK.format(what=what.split(' ', 1)[1] if a.kind != 'free' else 'question', topic=name,
                                   question=f'\nTheir question: "{a.question}"' if a.question and a.kind != 'free' else '',
                                   how=HOW_TEST if a.kind == 'test' else HOW_MED if a.kind == 'med' else '## What to do',
                                   patient=FOR_PATIENT if a.encounter_id else '')
            a.text, a.sources, _ = medical_ai._ask(ctx, f'drflow_{a.kind}', task, system=medical_ai.GENERAL_SYSTEM_PROMPT)
            prov = medical_ai.provider()
            a.model_name = medical_ai.model_name() if prov in ('anthropic', 'openai') else 'endpoint'
    except Exception as exc:
        a.error = f'{exc.__class__.__name__}: {exc}'[:500]
    a.status, a.finished_at = 'done', timezone.now()
    a.save()
    return a
