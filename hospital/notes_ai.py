"""Clinical and nursing notes on a visit, and Dr. Flow's help with them.

Who may change the notes (only while the visit is open; a completed or cancelled visit is read-only):
  * clinical notes (symptoms, assessment, diagnosis, plan): the attending doctor, and superusers. If the visit has no
    attending doctor yet, any doctor may write them and becomes the attending doctor;
  * nursing notes: the attending nurse, the attending doctor and superusers. If no nurse is attending yet, any nurse
    may write them and becomes the attending nurse.
Every save keeps the text before and after (NoteRevision).

What Dr. Flow can do:
  * improve / correct: rewrite the draft the clinician is typing (clearer, or spelling and grammar only). The
    answer is a suggestion shown next to the draft; nothing is saved until the clinician accepts it and presses Save;
  * suggest: tests, differentials, missing information and red flags, from the notes and the visit data;
  * question: any question about the notes, with earlier questions on this visit kept in mind.

What is sent: the notes with the patient's names, record number and phone removed (dr_flow_context.scrub), plus the
names in the emergency contact, staff names and any "Mr / Mrs / Dr ... Name" replaced by [name]; for suggest and
question also clinical.deidentified_context (sex, age band, vitals, allergies, conditions, medicines, lab results,
imaging, all counted in days, no dates). Never sent: name, record number, phone, address, date of birth, real dates,
who wrote the notes. clinical_context() returns exactly what would be sent, for the "What the AI sees" view.
"""
import json
import re

from django.contrib.auth import get_user_model
from django.utils import timezone

from . import medical_ai
from .dr_flow_context import scrub

CLINICAL_FIELDS = [('symptoms', 'Symptoms'), ('assessment', 'Assessment'), ('diagnosis', 'Diagnosis'), ('plan', 'Plan')]
NURSING_FIELDS = [('nursing_notes', 'Nursing notes')]
FIELDS = {'clinical': CLINICAL_FIELDS, 'nursing': NURSING_FIELDS}
LIMIT = 6000                    # characters per field
TITLE = re.compile(r'\b(Mr|Mrs|Ms|Miss|Mme|Dr|Doctor|Nurse|Sister|Brother|Pa|Ma|Alhaji|Haja)(\.?\s+)([A-Z][a-z]+(?:[ -][A-Z][a-z]+)?)')


# ------------------------------------------------------------------ who may do what
def _role(user):
    from .views import role_of
    return role_of(user)


def can_edit(user, e, section):
    """May this user change this section of the notes right now?"""
    if e.status != 'open' or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    role = _role(user)
    doctor = role == 'doctor' and e.clinician_id in (None, user.pk)
    if section == 'clinical':
        return doctor
    if section == 'nursing':
        return doctor or (role == 'nurse' and e.attending_nurse_id in (None, user.pk))
    return False


def can_use_ai(user):
    from .access import has
    return user.is_superuser or has(user, 'drflow')


def ai_on():
    return medical_ai.enabled()


# ------------------------------------------------------------------ removing names
_staff_cache = {'at': None, 'names': []}


def _staff_names():
    """First and last names of every staff account (cached for a minute)."""
    now = timezone.now()
    if _staff_cache['at'] and (now - _staff_cache['at']).total_seconds() < 60:
        return _staff_cache['names']
    names = set()
    for first, last in get_user_model().objects.values_list('first_name', 'last_name'):
        for part in f'{first} {last}'.split():
            if len(part) >= 3 and part[:1].isupper():
                names.add(part)
    _staff_cache.update(at=now, names=sorted(names, key=len, reverse=True))
    return _staff_cache['names']


def deidentify(text, patient, limit=LIMIT):
    """The patient's identifiers (scrub), then other people: the emergency contact, staff names, titled names."""
    t = scrub(text, patient, limit)
    if not t:
        return t
    t = TITLE.sub(lambda m: f'{m.group(1)}{m.group(2)}[name]', t)
    others = {w for w in re.findall(r'[A-Za-z][A-Za-z\'-]+', getattr(patient, 'emergency_contact', '') or '') if len(w) >= 3 and w[:1].isupper()}
    for name in sorted(others, key=len, reverse=True):
        t = re.sub(rf'(?<![\w]){re.escape(name)}(?![\w])', '[name]', t)
    for name in _staff_names():
        t = re.sub(rf'(?<![\w]){re.escape(name)}(?![\w])', '[name]', t)      # case-sensitive: "Grace" the person, not "grace"
    return t


def pseudonymise(text, patient, mapping, limit=LIMIT):
    """Like deidentify, but each removed detail gets a numbered placeholder ([patient 1], [name 2], [number 3],
    [record 4]) recorded in `mapping` (placeholder -> original), so the text can be put back after the AI has
    edited it. The same detail gets the same placeholder everywhere. `mapping` never leaves the server."""
    t = str(text or '')[:limit]
    if not t:
        return t
    seen = {v.lower(): k for k, v in mapping.items()}

    def ph_for(kind, orig):
        if orig.lower() not in seen:
            ph = f'[{kind} {len(mapping) + 1}]'
            mapping[ph] = orig; seen[orig.lower()] = ph
        return seen[orig.lower()]

    def tag(kind):
        return lambda m: ph_for(kind, m.group(0))
    p = patient
    tokens = {p.mrn, p.phone, p.first_name, p.last_name, f'{p.first_name} {p.last_name}'} | set((p.first_name or '').split()) | set((p.last_name or '').split())
    for tok in sorted({x.strip() for x in tokens if x and len(x.strip()) >= 2}, key=len, reverse=True):
        t = re.sub(rf'(?i)(?<![\w\[]){re.escape(tok)}(?![\w\]])', tag('patient'), t)
    t = re.sub(r'\bMF-[0-9A-F]{6,}\b', tag('record'), t)
    t = re.sub(r'\+\d[\d\s-]{6,}\d|\b\d{7,}\b', tag('number'), t)
    t = TITLE.sub(lambda m: m.group(1) + m.group(2) + ph_for('name', m.group(3)), t)
    others = {w for w in re.findall(r"[A-Za-z][A-Za-z'-]+", getattr(p, 'emergency_contact', '') or '') if len(w) >= 3 and w[:1].isupper()}
    for name in sorted(others | set(_staff_names()), key=len, reverse=True):
        t = re.sub(rf'(?<![\w\[]){re.escape(name)}(?![\w\]])', tag('name'), t)
    return t


def restore(text, mapping):
    """Put the real details back in place of the numbered placeholders."""
    for ph, orig in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(ph, orig)
    return text


# ------------------------------------------------------------------ what is sent
def notes_of(e, draft=None):
    """The notes, de-identified. `draft` (field -> text) replaces the saved text where given."""
    p, src = e.patient, dict(draft or {})
    out = {'reason_for_visit': deidentify(e.reason, p, 300)}
    for key, _label in CLINICAL_FIELDS + NURSING_FIELDS:
        val = src[key] if key in src else getattr(e, key)
        out[key] = deidentify(val, p)
    return out


def clinical_context(e, draft=None):
    """Everything Dr. Flow receives for suggestions and questions about this visit's notes."""
    from .clinical import deidentified_context
    ctx = deidentified_context(e)
    ctx['notes'] = notes_of(e, draft)
    ctx['visit']['days_since_visit_opened'] = round((timezone.now() - e.created_at).total_seconds() / 86400, 1)
    return ctx


def rewrite_context(e, ask):
    from .clinical import _age_band
    return {'patient': {'sex': e.patient.sex, 'age_band': _age_band(e.patient)}, 'department': str(e.department or ''),
            'section': ask.get_section_display(), 'draft': ask.draft}


def digest(ctx):
    return medical_ai.digest(ctx)


# ------------------------------------------------------------------ the tasks
EDITOR_SYSTEM = """You are a careful medical editor for doctors and nurses at a hospital in The Gambia, West Africa.
You edit clinical notes. You never add, remove or change clinical facts, findings, numbers, doses, times, negatives
("no fever"), uncertainty ("?malaria", "query") or the clinician's conclusions. You never invent history or results.
Placeholders such as [patient 1], [name 2], [record 3] or [number 4] stand for removed personal details: keep every
one exactly as written, in the same place, so the real details can be put back. Keep standard medical abbreviations the clinician used (BP, HR, RR, SpO2, Hb, RDT, PO, IV, BD,
TDS, OD, PRN, c/o, O/E, NAD, etc.) unless they are wrong. Use British English spelling."""

IMPROVE_TASK = """Rewrite each field of the draft below so it reads clearly and professionally, as a doctor or nurse
would write it in the record: correct spelling, grammar and medical terms; turn fragments into clear short sentences
or tidy bullet points; keep the clinician's own structure where it works. Keep every fact. Do not add anything that
is not in the draft. A field that is empty stays empty.
Answer with ONE JSON object only, no other text: the same keys as the draft, each value the improved text. Then a key
"changes" with a short list (at most 6 items) of what you changed and why, e.g. "Corrected 'diahrea' to 'diarrhoea'"."""

CORRECT_TASK = """Correct only the spelling, grammar, punctuation and misspelt medical terms in each field of the draft
below. Change as little as possible: keep the clinician's wording, order, abbreviations and line breaks. A field that
is empty stays empty.
Answer with ONE JSON object only, no other text: the same keys as the draft, each value the corrected text. Then a key
"changes" with a short list (at most 8 items) of each correction, e.g. "'hedache' → 'headache'"."""

SUGGEST_TASK = """Read this visit's notes (in the context under "notes") together with the rest of the de-identified
data, and help the doctor. Start with one sentence: the most important thing. Then use exactly these headings:
## Red flags
(anything urgent in the notes or data; write "None found" if none)
## Differential diagnosis
(most likely first, each with the features in the notes that support or argue against it; include common West
African causes where they fit: malaria, typhoid, TB, HIV, sickle cell disease, schistosomiasis, helminths,
malnutrition, hypertension, diabetes)
## Suggested tests
(only tests that would change management, each with a one-line reason; say which are already done or pending in the
lab results, and prefer tests realistically available in The Gambia)
## Missing from the notes
(history, examination findings or vital signs that should be documented to support the diagnosis and plan)
## Plan points to consider
(management and follow-up points the plan does not yet cover; refer to the guideline for doses rather than inventing
them, and check the allergies listed)
Be concise. Do not invent findings or results. You advise; the clinician decides."""

QUESTION_TASK = """The clinician has a question about this visit's notes (in the context under "notes") and the
de-identified visit data. Answer directly and briefly. Quote the parts of the notes or the results you rely on. If the
notes or data cannot answer it, say what is missing. Keep earlier questions and answers on this visit in mind.
Use the heading ## Answer, then ## What to do next if action is needed.
Question: {question}"""


def parse_rewrite(text, keys):
    """Pull the JSON object out of the AI's answer: {field: text} for the requested fields, and the list of changes."""
    t = (text or '').strip()
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', t)
    start, end = t.find('{'), t.rfind('}')
    if start < 0 or end <= start:
        raise ValueError('The AI answer could not be read')
    data = json.loads(t[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError('The AI answer could not be read')
    out = {k: str(data.get(k) or '').strip() for k in keys}
    changes = data.get('changes') or []
    if isinstance(changes, str):
        changes = [changes]
    return out, [str(c)[:240] for c in changes if c][:10]


def run(pk):
    from .models import ClinicalNoteAsk
    a = ClinicalNoteAsk.objects.select_related('encounter__patient', 'encounter__department').get(pk=pk)
    if a.status not in ('queued', 'running'):
        return a
    prov = medical_ai.provider()
    a.status, a.model_name = 'running', medical_ai.model_name() if prov in ('anthropic', 'openai') else 'endpoint'
    a.save(update_fields=['status', 'model_name', 'updated_at'])
    e = a.encounter
    try:
        if not medical_ai.enabled():
            raise RuntimeError('AI is not configured')
        if a.kind in ('improve', 'correct'):
            ctx = rewrite_context(e, a)
            task, system = (IMPROVE_TASK if a.kind == 'improve' else CORRECT_TASK), EDITOR_SYSTEM
        else:
            ctx = clinical_context(e, a.draft or None)
            system = medical_ai.GENERAL_SYSTEM_PROMPT
            if a.kind == 'question':
                earlier = a.encounter.note_asks.filter(kind__in=['question', 'suggest'], status='done', created_at__lt=a.created_at).order_by('-created_at')[:6]
                ctx['earlier_questions'] = [{'asked': x.question if x.kind == 'question' else 'Suggest tests and next steps', 'answer': x.text[:800]}
                                            for x in reversed(earlier)]
                task = QUESTION_TASK.format(question=a.question)
            else:
                task = SUGGEST_TASK
        a.context_digest = digest(ctx)
        text, _sources, _ = medical_ai._ask(ctx, f'notes_{a.kind}', task, system=system)
        if not (text or '').strip():
            raise RuntimeError('The AI service returned no text')
        if a.kind in ('improve', 'correct'):
            fields, changes = parse_rewrite(text, list(a.draft))
            m = a.placeholders or {}
            a.result = {'fields': {k: restore(v, m) for k, v in fields.items()}, 'changes': [restore(c, m) for c in changes]}
            a.text = '\n'.join(changes)
        else:
            a.text = text.strip()
        a.status = 'done'
    except Exception as exc:
        a.status, a.error = 'failed', f'{exc.__class__.__name__}: {exc}'[:500]
    a.finished_at = timezone.now()
    a.save()
    return a


def serialize(a):
    from .templatetags.evidence_tags import simple_md
    status = 'running' if a.busy else 'failed' if a.status in ('queued', 'running') else a.status
    error = ''
    if status == 'failed':
        error = 'The AI answer could not be read. Try again.' if 'could not be read' in a.error or 'JSONDecodeError' in a.error else 'The AI did not answer. Try again in a moment.'
    return {'id': a.pk, 'kind': a.kind, 'kind_label': a.get_kind_display(), 'section': a.section, 'question': a.question, 'status': status,
            'html': str(simple_md(a.text)) if a.text and a.kind in ('suggest', 'question') else '', 'text': a.text,
            'fields': (a.result or {}).get('fields') or {}, 'changes': (a.result or {}).get('changes') or [],
            'error': error, 'model': a.model_name, 'helpful': a.helpful,
            'by': (a.requested_by.get_full_name() or a.requested_by.get_username()) if a.requested_by_id else '',
            'at': timezone.localtime(a.created_at).strftime('%d %b %H:%M')}
