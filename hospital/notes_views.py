"""Editing the clinical and nursing notes of a visit, and Dr. Flow's help with them (notes-ai.js).
Who may edit and what the AI receives: see notes_ai.py."""
import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from . import notes_ai as N
from .models import ClinicalNoteAsk, Encounter, NoteRevision
from .views import audit, authorize, role_of


def nurses():
    return get_user_model().objects.filter(hospital_staff__role='nurse', hospital_staff__active=True, is_active=True).order_by('first_name', 'last_name')


@login_required
@require_POST
def save(request, pk):
    """Save one section of the notes. Keeps the text before and after."""
    authorize(request, 'clinical')
    section = request.POST.get('section', '')
    if section not in N.FIELDS:
        return HttpResponseBadRequest('Unknown section')
    with transaction.atomic():
        e = get_object_or_404(Encounter.objects.select_for_update(), pk=pk)
        if e.status != 'open':
            messages.error(request, 'This visit is closed; its notes can no longer be changed.')
            return redirect('encounter_detail', pk=pk)
        if not N.can_edit(request.user, e, section):
            raise PermissionDenied('Only the attending clinician can change these notes.')
        before = {k: getattr(e, k) for k, _ in N.FIELDS[section]}
        after = {k: request.POST.get(k, '').replace('\r\n', '\n').strip()[:N.LIMIT] for k, _ in N.FIELDS[section]}
        changed = [k for k in after if after[k] != (before[k] or '')]
        update = []
        role = role_of(request.user)
        if section == 'clinical' and e.clinician_id is None and role == 'doctor':
            e.clinician = request.user; update.append('clinician')            # the first doctor to write the notes attends
        if section == 'nursing':
            if role == 'nurse' and e.attending_nurse_id is None:
                e.attending_nurse = request.user; update.append('attending_nurse')
            elif role != 'nurse' and 'attending_nurse' in request.POST:      # the doctor (or a superuser) chooses the nurse
                nid = request.POST.get('attending_nurse') or None
                new = nurses().filter(pk=nid).first() if nid else None
                if (new.pk if new else None) != e.attending_nurse_id:
                    e.attending_nurse = new; update.append('attending_nurse')
        if changed:
            for k in changed:
                setattr(e, k, after[k])
            NoteRevision.objects.create(encounter=e, section=section, edited_by=request.user,
                                        before={k: before[k] or '' for k in changed}, after={k: after[k] for k in changed},
                                        ai_assisted=request.POST.get('ai_assisted') == '1')
            update += changed
        if update:
            e.save(update_fields=list(set(update)) + ['updated_at'])
            audit(request, 'edit_notes', f'encounter:{e.pk}', {'section': section, 'fields': changed, 'ai_assisted': request.POST.get('ai_assisted') == '1'})
    messages.success(request, ('Nursing notes' if section == 'nursing' else 'Clinical notes') + (' saved.' if changed else ' unchanged.'))
    return redirect(reverse('encounter_detail', args=[e.pk]) + f'#notes-{section}')


def _ai_gate(request):
    if not N.can_use_ai(request.user):
        return JsonResponse({'ok': False, 'error': 'Your access does not include Dr. Flow.'}, status=403)
    if not N.ai_on():
        return JsonResponse({'ok': False, 'error': 'AI is not connected. Ask an administrator to configure it.'}, status=400)
    return None


@login_required
@require_POST
def ask(request, pk):
    """Start a Dr. Flow request about this visit's notes. One at a time per visit; the page polls status()."""
    authorize(request, 'clinical')
    from .evidence_views import _dispatch
    from .tasks import notes_ai_task
    e = get_object_or_404(Encounter.objects.select_related('patient'), pk=pk)
    kind, section = request.POST.get('kind', ''), request.POST.get('section', 'clinical')
    if kind not in dict(ClinicalNoteAsk.KINDS) or section not in N.FIELDS:
        return JsonResponse({'ok': False, 'error': 'Unknown request.'}, status=400)
    gate = _ai_gate(request)
    if gate:
        return gate
    question = request.POST.get('question', '').strip()[:500]
    if kind == 'question' and len(question) < 3:
        return JsonResponse({'ok': False, 'error': 'Type a question first.'}, status=400)
    draft, mapping = {}, {}
    if kind in ('improve', 'correct'):
        if not N.can_edit(request.user, e, section):
            return JsonResponse({'ok': False, 'error': 'Only the attending clinician can change these notes while the visit is open.'}, status=403)
        mapping = {}
        draft = {k: N.pseudonymise(request.POST.get(k, ''), e.patient, mapping) for k, _ in N.FIELDS[section] if k in request.POST}
        if not any(v.strip() for v in draft.values()):
            return JsonResponse({'ok': False, 'error': 'There is no text to work on yet.'}, status=400)
    else:
        # questions and suggestions use the draft on screen if the clinician is editing, else the saved notes
        draft = {k: request.POST[k] for fields in N.FIELDS.values() for k, _ in fields if k in request.POST}
    busy = e.note_asks.filter(status__in=['queued', 'running']).first()
    if busy and busy.busy:
        return JsonResponse({'ok': True, 'ask': N.serialize(busy), 'message': 'Dr. Flow is still working on the last request.'})
    a = ClinicalNoteAsk.objects.create(encounter=e, requested_by=request.user, kind=kind, section=section,
                                       question=N.deidentify(question, e.patient, 500), draft=draft, placeholders=mapping)
    audit(request, 'drflow_notes', f'encounter:{e.pk}', {'ask': a.pk, 'kind': kind, 'section': section})
    _dispatch(notes_ai_task, a.pk)
    a.refresh_from_db()
    return JsonResponse({'ok': True, 'ask': N.serialize(a)})


def _own_ask(request, pk):
    a = get_object_or_404(ClinicalNoteAsk.objects.select_related('requested_by', 'encounter'), pk=pk)
    from .access import can_see
    if not request.user.is_superuser and not can_see(request, a.encounter.patient_id):
        raise PermissionDenied('This patient is outside your access.')
    return a


@login_required
@require_GET
def status(request, pk):
    authorize(request, 'clinical')
    return JsonResponse({'ok': True, 'ask': N.serialize(_own_ask(request, pk))})


@login_required
@require_POST
def rate(request, pk):
    authorize(request, 'clinical')
    a = _own_ask(request, pk)
    v = request.POST.get('helpful', '')
    if v not in ('1', '0'):
        return HttpResponseBadRequest('helpful must be 1 or 0')
    a.helpful = v == '1'
    a.save(update_fields=['helpful', 'updated_at'])
    audit(request, 'drflow_notes_rate', f'note_ask:{a.pk}', {'helpful': a.helpful})
    return JsonResponse({'ok': True, 'message': 'Thank you, feedback recorded.'})


@login_required
@require_GET
def context(request, pk):
    """Exactly what Dr. Flow would receive about this visit's notes: de-identified. Nothing is sent here."""
    authorize(request, 'clinical')
    e = get_object_or_404(Encounter.objects.select_related('patient', 'department'), pk=pk)
    audit(request, 'view_chart', f'notes_ai_context:{e.pk}')
    ctx = N.clinical_context(e)
    return JsonResponse({'ok': True, 'context': ctx, 'sha256': N.digest(ctx),
                         'note': 'This is what Dr. Flow receives for suggestions and questions. Names, record number, phone, '
                                 'address, date of birth and real dates are removed; other people\'s names are replaced by [name].'},
                        json_dumps_params={'indent': 1})


def page_context(request, e):
    """What the encounter page needs to draw the notes, the nursing notes and the assistant."""
    asks = [N.serialize(a) for a in e.note_asks.filter(kind__in=['suggest', 'question']).select_related('requested_by')[:8]]
    return {
        'notes_fields': [(k, lbl, getattr(e, k)) for k, lbl in N.CLINICAL_FIELDS],
        'can_edit_clinical': N.can_edit(request.user, e, 'clinical'), 'can_edit_nursing': N.can_edit(request.user, e, 'nursing'),
        'can_pick_nurse': N.can_edit(request.user, e, 'nursing') and role_of(request.user) != 'nurse',
        'nurses': nurses() if e.status == 'open' else [],
        'notes_ai': N.ai_on() and N.can_use_ai(request.user),
        'note_revisions': e.note_revisions.select_related('edited_by')[:30],
        'notes_asks_json': json.dumps(asks),
    }
