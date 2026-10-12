"""Forms & approvals: form designer, filling in, flow designer, tasks and run pages."""
import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from . import esign
from . import flows
from . import formkit as F
from .models import (Encounter, Envelope, FormDefinition, FormDraft, FormSubmission, FormVersion, Patient, StaffProfile,
                     WorkflowDefinition, WorkflowRun, WorkflowTask)
from .views import ROLES, audit, authorize, role_of


def _wants_json(request):
    return request.headers.get('Accept', '').startswith('application/json') or request.content_type == 'application/json'


def _body(request):
    try:
        d = json.loads(request.body.decode('utf-8') or '{}')
        return d if isinstance(d, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return None


def _staff_list():
    return [{'id': p.user_id, 'name': p.user.get_full_name() or p.user.username, 'role': p.role}
            for p in StaffProfile.objects.filter(active=True).exclude(role__in=['partner', 'specialist']).select_related('user').order_by('role', 'user__first_name')]


# ================================================================== home
@login_required
def studio(request):
    authorize(request)
    flows.sweep(); esign.sweep()
    mine = list(flows.tasks_for(request.user)[:40])
    runs = WorkflowRun.objects.filter(status__in=['open', 'returned']).select_related('definition', 'submission__patient', 'submission__definition').order_by('-created_at')[:40]
    is_designer = role_of(request.user) in ROLES['studio']
    return render(request, 'hospital/studio.html', {
        'forms': FormDefinition.objects.annotate(n=Count('submissions')).order_by('name'),
        'workflows': WorkflowDefinition.objects.annotate(n=Count('workflowrun')).order_by('name'),
        'submissions': FormSubmission.objects.select_related('definition', 'patient', 'submitted_by').prefetch_related('signature_set').order_by('-created_at')[:25],
        'runs': runs, 'tasks': mine, 'is_designer': is_designer,
        'patients': Patient.objects.order_by('last_name')[:300],
        'envelopes_waiting': Envelope.objects.filter(status='sent', recipients__user=request.user, recipients__status__in=['sent', 'viewed']).distinct().count(),
    })


# ================================================================== forms
TEMPLATES = {
    'consent': {'name': 'Consent for procedure', 'schema': {'pages': [{'id': 'p1', 'title': 'Procedure'}, {'id': 'p2', 'title': 'Consent'}], 'fields': [
        {'type': 'patient', 'label': 'Patient', 'page': 'p1'},
        {'key': 'procedure', 'label': 'Procedure', 'type': 'text', 'required': True, 'page': 'p1'},
        {'key': 'side', 'label': 'Side', 'type': 'radio', 'options': ['Left', 'Right', 'Both', 'Not applicable'], 'required': True, 'page': 'p1', 'width': 'half'},
        {'key': 'anaesthesia', 'label': 'Anaesthesia', 'type': 'select', 'options': ['Local', 'Regional', 'General', 'Sedation'], 'page': 'p1', 'width': 'half'},
        {'key': 'risks', 'label': 'Risks explained', 'type': 'checkboxes', 'options': ['Bleeding', 'Infection', 'Pain', 'Damage to nearby structures', 'Need for further surgery', 'Risk of anaesthesia'], 'required': True, 'page': 'p1'},
        {'key': 'blood', 'label': 'May need a blood transfusion', 'type': 'yesno', 'page': 'p1', 'width': 'half'},
        {'key': 'blood_consent', 'label': 'Patient agrees to a transfusion if needed', 'type': 'yesno', 'page': 'p1', 'width': 'half', 'show_if': {'all': [{'field': 'blood', 'op': 'eq', 'value': 'yes'}]}, 'required': True},
        {'key': 'interpreter', 'label': 'Interpreter used', 'type': 'checkbox', 'page': 'p2'},
        {'key': 'language', 'label': 'Language', 'type': 'select', 'options': ['Mandinka', 'Wolof', 'Fula', 'Jola', 'Serahule', 'Other'], 'page': 'p2', 'show_if': {'all': [{'field': 'interpreter', 'op': 'truthy'}]}, 'require_if': {'all': [{'field': 'interpreter', 'op': 'truthy'}]}},
        {'type': 'paragraph', 'text': 'I confirm the procedure, its benefits, risks and alternatives have been explained to me and I have had the chance to ask questions.', 'page': 'p2'},
        {'key': 'understood', 'label': 'I understand and agree', 'type': 'checkbox', 'required': True, 'page': 'p2'}]}},
    'burns': {'name': 'Burns assessment', 'schema': {'fields': [
        {'type': 'patient', 'label': 'Patient'},
        {'key': 'weight', 'label': 'Weight', 'type': 'number', 'unit': 'kg', 'min': 1, 'max': 300, 'required': True, 'width': 'third'},
        {'key': 'tbsa', 'label': 'Burned area (% TBSA)', 'type': 'number', 'min': 0, 'max': 100, 'required': True, 'width': 'third'},
        {'key': 'hours', 'label': 'Hours since burn', 'type': 'number', 'min': 0, 'max': 72, 'width': 'third'},
        {'key': 'areas', 'label': 'Burned areas', 'type': 'bodymap'},
        {'key': 'parkland', 'label': 'Parkland 24-hour fluids', 'type': 'calc', 'formula': 'round(4 * weight * tbsa)', 'decimals': 0, 'unit': 'mL', 'width': 'half'},
        {'key': 'first8', 'label': 'Rate for the first 8 hours', 'type': 'calc', 'formula': 'round(parkland / 2 / 8)', 'decimals': 0, 'unit': 'mL/h', 'width': 'half'},
        {'key': 'major', 'label': 'Major burn', 'type': 'calc', 'formula': 'if(tbsa >= 15, "Yes: start resuscitation and refer", "No")'},
        {'key': 'vitals', 'label': 'Vital signs', 'type': 'vitals'},
        {'key': 'gcs', 'label': 'Consciousness', 'type': 'gcs'}]}},
    'falls': {'name': 'Falls risk (Morse)', 'schema': {'fields': [
        {'type': 'patient', 'label': 'Patient'},
        {'key': 'history', 'label': 'Fallen in the last 3 months', 'type': 'radio', 'options': ['No', 'Yes'], 'required': True, 'width': 'half'},
        {'key': 'second_dx', 'label': 'More than one diagnosis', 'type': 'radio', 'options': ['No', 'Yes'], 'required': True, 'width': 'half'},
        {'key': 'aid', 'label': 'Walking aid', 'type': 'radio', 'options': ['None / bed rest / nurse assists', 'Crutches / cane / walker', 'Holds furniture'], 'required': True},
        {'key': 'iv', 'label': 'IV or heparin lock', 'type': 'radio', 'options': ['No', 'Yes'], 'required': True, 'width': 'half'},
        {'key': 'gait', 'label': 'Gait', 'type': 'radio', 'options': ['Normal / bed rest', 'Weak', 'Impaired'], 'required': True, 'width': 'half'},
        {'key': 'mental', 'label': 'Mental status', 'type': 'radio', 'options': ['Knows own limits', 'Forgets limitations'], 'required': True},
        {'key': 'score', 'label': 'Morse score', 'type': 'calc', 'decimals': 0, 'width': 'half',
         'formula': 'if(history=="Yes",25,0) + if(second_dx=="Yes",15,0) + if(aid=="Holds furniture",30,if(aid=="Crutches / cane / walker",15,0)) + if(iv=="Yes",20,0) + if(gait=="Impaired",20,if(gait=="Weak",10,0)) + if(mental=="Forgets limitations",15,0)'},
        {'key': 'risk', 'label': 'Risk', 'type': 'calc', 'width': 'half', 'formula': 'if(score >= 45, "High", if(score >= 25, "Moderate", "Low"))'},
        {'key': 'plan', 'label': 'Prevention plan', 'type': 'checkboxes', 'options': ['Bed low and brakes on', 'Call bell in reach', 'Non-slip footwear', 'Hourly rounding', 'Bed alarm'], 'show_if': {'all': [{'field': 'score', 'op': 'gte', 'value': '25'}]}, 'required': True}]}},
    'admission': {'name': 'Nursing admission assessment', 'schema': {'pages': [{'id': 'a', 'title': 'Arrival'}, {'id': 'b', 'title': 'Observations'}, {'id': 'c', 'title': 'Belongings'}], 'fields': [
        {'type': 'patient', 'label': 'Patient', 'page': 'a'},
        {'key': 'arrived', 'label': 'Arrived', 'type': 'radio', 'options': ['Walking', 'Wheelchair', 'Stretcher'], 'page': 'a', 'width': 'half'},
        {'key': 'with', 'label': 'Accompanied by', 'type': 'text', 'page': 'a', 'width': 'half'},
        {'key': 'allergies', 'label': 'Allergies (from record)', 'type': 'text', 'prefill': 'patient.allergies', 'readonly': True, 'page': 'a'},
        {'key': 'obs', 'label': 'Observations', 'type': 'vitals', 'required': True, 'page': 'b'},
        {'key': 'pain', 'label': 'Pain score', 'type': 'rating', 'page': 'b', 'width': 'half'},
        {'key': 'weight', 'label': 'Weight', 'type': 'number', 'unit': 'kg', 'page': 'b', 'width': 'third'},
        {'key': 'height', 'label': 'Height', 'type': 'number', 'unit': 'cm', 'page': 'b', 'width': 'third'},
        {'key': 'bmi', 'label': 'BMI', 'type': 'calc', 'formula': 'round(bmi(weight, height), 1)', 'page': 'b', 'width': 'third'},
        {'key': 'items', 'label': 'Belongings kept on the ward', 'type': 'table', 'page': 'c', 'columns': [{'key': 'item', 'label': 'Item', 'type': 'text'}, {'key': 'qty', 'label': 'How many', 'type': 'number'}, {'key': 'kept', 'label': 'Kept by', 'type': 'select', 'options': ['Patient', 'Relative', 'Ward safe']}]},
        {'key': 'nurse_sig', 'label': 'Admitting nurse', 'type': 'signature', 'required': True, 'page': 'c'}]}},
}


@login_required
def form_designer(request, pk=None):
    authorize(request, 'studio')
    obj = get_object_or_404(FormDefinition, pk=pk) if pk else None
    errors = []
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()[:200]
        slug = slugify(request.POST.get('slug') or name)[:50]
        try:
            raw = json.loads(request.POST.get('schema') or '{}')
        except ValueError:
            raw = None
        schema, errors = F.clean_schema(raw) if raw is not None else (None, ['The form could not be read.'])
        if not name:
            errors.append('Give the form a name.')
        if not slug or FormDefinition.objects.filter(slug=slug).exclude(pk=obj.pk if obj else None).exists():
            errors.append('Another form already uses this short name; choose a different one.')
        if not errors:
            with transaction.atomic():
                publish = request.POST.get('published') in ('on', 'true', '1')
                changed = obj is None or obj.schema != schema
                if obj is None:
                    obj = FormDefinition(version=1)
                elif changed and (obj.submissions.exists() or obj.versions.exists()):
                    obj.version += 1
                obj.name, obj.slug, obj.schema, obj.published = name, slug, schema, publish
                obj.description = request.POST.get('description', '')[:300]
                obj.save()
                if publish and not obj.versions.filter(version=obj.version).exists():
                    FormVersion.objects.create(definition=obj, version=obj.version, schema=schema, published_by=request.user,
                                               note=request.POST.get('note', '')[:200])
                audit(request, 'form_saved', f'form:{obj.pk}', {'version': obj.version, 'published': publish})
            if _wants_json(request):
                return JsonResponse({'ok': True, 'id': obj.pk, 'version': obj.version, 'url': reverse('form_edit', args=[obj.pk])})
            messages.success(request, f'{obj.name} saved{" and published" if obj.published else " as a draft"} (version {obj.version}).')
            return redirect('studio')
        if _wants_json(request):
            return JsonResponse({'ok': False, 'errors': errors}, status=400)
    tpl = TEMPLATES.get(request.GET.get('template', ''))
    boot = {'schema': obj.schema if obj else (tpl['schema'] if tpl else {'fields': []}), 'name': obj.name if obj else (tpl['name'] if tpl else ''),
            'slug': obj.slug if obj else '', 'description': obj.description if obj else '', 'published': obj.published if obj else True,
            'version': obj.version if obj else 1, 'catalogue': F.catalogue(), 'errors': errors,
            'templates': {k: v['name'] for k, v in TEMPLATES.items()},
            'flow_steps': sorted({n['id']: n['label'] for w in (obj.workflows.all() if obj else []) for n in flows.definition_graph(w)['nodes'] if n['type'] == 'fill'}.items()),
            'save_url': request.path}
    if request.method == 'POST':
        boot.update({'name': request.POST.get('name', ''), 'slug': request.POST.get('slug', '')})
        try:
            boot['schema'] = json.loads(request.POST.get('schema') or '{}')
        except ValueError:
            pass
    return render(request, 'hospital/form_builder.html', {'obj': obj, 'boot': boot, 'errors': errors,
                                                          'versions': obj.versions.select_related('published_by')[:10] if obj else []})


def _patterns():
    return {k: v for k, v in F.PATTERNS.items()}


def _fill_boot(definition, patient, user, values=None, errors=None, scope='', submit_url='', draft=None, extra=None):
    schema = definition.schema if isinstance(definition, FormDefinition) else definition
    pre = F.prefill_values(schema, patient, user)
    return {'schema': schema, 'values': {**pre, **(draft.values if draft else {}), **(values or {})}, 'errors': errors or {},
            'scope': scope, 'submit_url': submit_url, 'page': draft.page if draft else 0, 'patterns': _patterns(),
            'patient': {'name': patient.full_name, 'mrn': patient.mrn, 'age': patient.age, 'sex': patient.get_sex_display(),
                        'allergies': [a.substance for a in patient.allergies.filter(status='active')]},
            'draft_saved': draft.updated_at.isoformat() if draft else None, **(extra or {})}


@login_required
def fill_form(request, pk, patient_id):
    authorize(request, 'clinical')
    definition = get_object_or_404(FormDefinition, pk=pk, published=True)
    patient = get_object_or_404(Patient, pk=patient_id)
    schema = definition.schema if definition.schema.get('version') == 2 else (F.clean_schema(definition.schema)[0] or definition.schema)
    workflows = WorkflowDefinition.objects.filter(active=True).filter(Q(form=definition) | Q(form__isnull=True))
    draft = FormDraft.objects.filter(definition=definition, patient=patient, user=request.user).first()
    if request.method == 'POST':
        if request.content_type == 'application/json':
            data = _body(request) or {}
            raw, wf_id, enc_id = data.get('values') or {}, data.get('workflow'), data.get('encounter')
        else:
            raw = {}
            for f in schema.get('fields', []):
                if f['type'] == 'checkboxes':
                    raw[f['key']] = request.POST.getlist(f['key'])
                elif f['key'] in request.POST:
                    raw[f['key']] = request.POST.get(f['key'])
            if request.POST.get('__payload'):
                try:
                    raw = json.loads(request.POST['__payload'])
                except ValueError:
                    pass
            wf_id, enc_id = request.POST.get('workflow'), request.POST.get('encounter')
        pre = F.prefill_values(schema, patient, request.user)
        raw.update({f['key']: pre[f['key']] for f in schema.get('fields', []) if f.get('readonly') and f['key'] in pre})
        values, errors, _ = F.evaluate_form(schema, raw)
        wf = None
        if wf_id:
            wf = workflows.filter(pk=wf_id).first()
            if not wf:
                errors['__all__'] = 'Choose an active approval flow.'
        if errors:
            if request.content_type == 'application/json':
                return JsonResponse({'ok': False, 'errors': errors}, status=400)
            return render(request, 'hospital/form_fill.html', {'definition': definition, 'patient': patient, 'workflows': workflows,
                                                                'boot': _fill_boot(schema, patient, request.user, raw, errors, submit_url=request.path)})
        with transaction.atomic():
            enc = Encounter.objects.filter(pk=enc_id, patient=patient).first() if enc_id else patient.encounters.filter(status='open').order_by('-created_at').first()
            s = FormSubmission.objects.create(definition=definition, patient=patient, encounter=enc, values=values, schema_snapshot=schema,
                                              submitted_by=request.user)
            run = flows.start_run(wf, s, request.user) if wf else None
            FormDraft.objects.filter(definition=definition, patient=patient, user=request.user).delete()
            audit(request, 'submit_form', f'form_submission:{s.pk}', {'workflow_run': run.pk if run else None})
        url = reverse('run_detail', args=[run.pk]) if run else reverse('submission_detail', args=[s.pk])
        if request.content_type == 'application/json':
            return JsonResponse({'ok': True, 'url': url, 'id': s.pk})
        messages.success(request, f'{definition.name} submitted.' + (' The approval flow has started.' if run else ''))
        return redirect('patient_chart', pk=patient.pk)
    return render(request, 'hospital/form_fill.html', {
        'definition': definition, 'patient': patient, 'workflows': workflows,
        'boot': _fill_boot(schema, patient, request.user, submit_url=request.path, draft=draft,
                           extra={'draft_url': reverse('form_draft', args=[definition.pk, patient.pk]),
                                  'workflows': [{'id': w.pk, 'name': w.name, 'linked': w.form_id == definition.pk} for w in workflows],
                                  'encounters': [{'id': e.pk, 'label': f'{e.created_at:%d %b} · {e.reason[:40]}'} for e in patient.encounters.filter(status='open')[:6]]})})


@login_required
@require_POST
def form_draft(request, pk, patient_id):
    authorize(request, 'clinical')
    definition = get_object_or_404(FormDefinition, pk=pk)
    patient = get_object_or_404(Patient, pk=patient_id)
    data = _body(request)
    if data is None:
        return JsonResponse({'ok': False}, status=400)
    if data.get('discard'):
        FormDraft.objects.filter(definition=definition, patient=patient, user=request.user).delete()
        return JsonResponse({'ok': True})
    vals = data.get('values') if isinstance(data.get('values'), dict) else {}
    if len(json.dumps(vals)) > 600_000:
        return JsonResponse({'ok': False, 'error': 'Draft too large'}, status=400)
    d, _ = FormDraft.objects.update_or_create(definition=definition, patient=patient, user=request.user,
                                              defaults={'values': vals, 'page': max(0, min(20, int(data.get('page') or 0)))})
    return JsonResponse({'ok': True, 'saved': d.updated_at.isoformat()})


@login_required
def submission_detail(request, pk):
    authorize(request)
    s = get_object_or_404(FormSubmission.objects.select_related('definition', 'patient', 'submitted_by', 'encounter'), pk=pk)
    schema = s.schema_snapshot or {}
    hidden = F.evaluate_form(schema, s.values or {}, previous=s.values)[2] if schema.get('version') == 2 else set()
    rows = []
    for f in schema.get('fields', []):
        if f['key'] in hidden or f['type'] in ('divider', 'patient'):
            continue
        v = (s.values or {}).get(f['key'])
        rows.append({'f': f, 'v': v, 'text': F.display_value(f, v) if f['type'] not in F.DISPLAY_TYPES else ''})
    return render(request, 'hospital/submission_detail.html', {
        's': s, 'rows': rows, 'runs': s.workflowrun_set.select_related('definition'),
        'envelopes': s.envelopes.all(), 'signatures': s.signature_set.select_related('signer')})


# ================================================================== flows
@login_required
def workflow_designer(request, pk=None):
    authorize(request, 'studio')
    obj = get_object_or_404(WorkflowDefinition, pk=pk) if pk else None
    errors = []
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()[:200]
        form = FormDefinition.objects.filter(pk=request.POST.get('form') or None).first()
        graph = None
        try:
            if request.POST.get('graph'):
                graph = json.loads(request.POST['graph'])
            steps = json.loads(request.POST.get('steps') or '[]')
        except ValueError:
            errors.append('The flow could not be read.'); steps = []
        if not name:
            errors.append('Give the flow a name.')
        if not graph or not graph.get('nodes'):
            # legacy: a list of {"name", "role"} approval steps
            if not isinstance(steps, list) or not 1 <= len(steps) <= 20 or any(
                    not isinstance(s, dict) or s.get('role') not in ROLES['all'] or not str(s.get('name', '')).strip() for s in steps):
                errors.append('Add between 1 and 20 approval steps, each with a name and a valid staff role.')
            graph = flows.graph_from_steps(steps) if not errors else None
        if graph is not None and not errors:
            graph, gerr = flows.clean_graph(graph, form.schema if form else None, ROLES['all'])
            errors += gerr
        if not errors:
            obj = obj or WorkflowDefinition()
            obj.name, obj.graph, obj.form, obj.active = name, graph, form, request.POST.get('active') in ('on', 'true', '1')
            obj.steps = steps if isinstance(steps, list) and steps and not request.POST.get('graph') else []
            obj.description = request.POST.get('description', '')[:300]
            obj.save()
            audit(request, 'workflow_saved', f'workflow:{obj.pk}', {'steps': len(graph['nodes'])})
            if _wants_json(request):
                return JsonResponse({'ok': True, 'id': obj.pk, 'url': reverse('workflow_edit', args=[obj.pk])})
            messages.success(request, f'Flow “{obj.name}” saved.')
            return redirect('studio')
        if _wants_json(request):
            return JsonResponse({'ok': False, 'errors': errors}, status=400)
    forms_ = FormDefinition.objects.order_by('name')
    boot = {'graph': flows.definition_graph(obj) if obj else None, 'name': obj.name if obj else '', 'description': obj.description if obj else '',
            'active': obj.active if obj else True, 'form': obj.form_id if obj else None,
            'forms': {f.pk: {'name': f.name, 'fields': [{'key': x['key'], 'label': x.get('label') or x['key'], 'type': x['type'], 'options': x.get('options', []), 'filled_by': x.get('filled_by', '')}
                                                          for x in (f.schema or {}).get('fields', []) if x.get('type') in F.INPUT_TYPES]} for f in forms_},
            'catalogue': flows.catalogue(ROLES['all']), 'staff': _staff_list(), 'save_url': request.path, 'errors': errors}
    return render(request, 'hospital/workflow_builder.html', {'obj': obj, 'boot': boot, 'errors': errors})


@login_required
def tasks(request):
    authorize(request)
    flows.sweep()
    mine = flows.tasks_for(request.user)
    waiting = Envelope.objects.filter(recipients__user=request.user, recipients__status__in=['sent', 'viewed'], status='sent').distinct()
    hosting = Envelope.objects.filter(status='sent', recipients__role='in_person', recipients__status__in=['sent', 'viewed']).filter(
        Q(recipients__host=request.user) | Q(created_by=request.user)).distinct()
    return render(request, 'hospital/tasks.html', {'tasks': mine, 'waiting': waiting, 'hosting': hosting,
                                                   'done': WorkflowTask.objects.filter(decided_by=request.user).select_related('run__definition', 'run__submission__patient').order_by('-decided_at')[:15]})


def _may_view_run(request, run):
    if role_of(request.user) in ('partner', 'specialist', None):
        raise PermissionDenied('Your account is not authorized for this module.')


@login_required
def run_detail(request, pk):
    authorize(request)
    run = get_object_or_404(WorkflowRun.objects.select_related('definition', 'submission__patient', 'submission__definition', 'started_by'), pk=pk)
    if not run.graph:
        run.graph = flows.definition_graph(run.definition); run.save(update_fields=['graph'])
    my = [t for t in run.tasks.filter(status='pending').select_related('envelope') if flows.can_act(t, request.user)]
    sub = run.submission
    fill_boot = None
    fill_task = next((t for t in my if t.kind == 'fill'), None)
    if fill_task:
        fill_boot = _fill_boot(sub.schema_snapshot, sub.patient, request.user, values=sub.values, scope=fill_task.node_id,
                               submit_url=reverse('task_act', args=[fill_task.pk]))
    resubmit_boot = None
    if run.status == 'returned' and (request.user == (run.started_by or sub.submitted_by) or request.user.is_superuser):
        resubmit_boot = _fill_boot(sub.schema_snapshot, sub.patient, request.user, values=sub.values, submit_url=reverse('run_resubmit', args=[run.pk]))
    return render(request, 'hospital/run_detail.html', {
        'run': run, 'sub': sub, 'my': my,
        # automatic steps already log their decision; their "left" line would only repeat it
        'events': [e for e in run.events.select_related('actor') if not (e.kind == 'left' and next((n['type'] for n in run.graph['nodes'] if n['id'] == e.node_id), '') in ('start', 'condition', 'route', 'parallel', 'join', 'notify', 'set'))], 'view': flows.run_view(run),
        'catalogue': flows.catalogue(ROLES['all']), 'fill_boot': fill_boot, 'fill_task': fill_task, 'resubmit_boot': resubmit_boot,
        'tasks': run.tasks.filter(round=run.round).select_related('user', 'decided_by', 'envelope'), 'staff': _staff_list(),
        'can_manage': request.user == run.started_by or role_of(request.user) in ('admin', 'management'),
    })


@login_required
@require_POST
def task_act(request, pk):
    authorize(request)
    t = get_object_or_404(WorkflowTask.objects.select_related('run'), pk=pk)
    data = _body(request) if request.content_type == 'application/json' else request.POST
    if data is None:
        return HttpResponseBadRequest('Invalid data')
    action = data.get('action') or ('submit' if t.kind == 'fill' else '')
    try:
        flows.decide(t, request.user, action, str(data.get('comment', ''))[:2000], values=data.get('values') if isinstance(data.get('values'), dict) else None)
        audit(request, 'workflow_action', f'workflow_run:{t.run_id}', {'action': action, 'task': t.pk})
    except ValidationError as e:
        if request.content_type == 'application/json':
            return JsonResponse({'ok': False, 'error': '; '.join(e.messages)}, status=400)
        messages.error(request, '; '.join(e.messages))
        return redirect('run_detail', pk=t.run_id)
    done = {'approve': 'Approved.', 'reject': 'Rejected.', 'return': 'Sent back for changes.', 'acknowledge': 'Marked as reviewed.', 'submit': 'Your part is saved.'}.get(action, 'Done.')
    if request.content_type == 'application/json':
        return JsonResponse({'ok': True, 'url': reverse('run_detail', args=[t.run_id])})
    messages.success(request, done)
    return redirect(request.POST.get('next') or reverse('run_detail', args=[t.run_id]))


@login_required
@require_POST
def workflow_act(request, pk, action):
    """Older one-click approve/reject buttons: act on the first waiting step this person may decide."""
    authorize(request)
    run = get_object_or_404(WorkflowRun, pk=pk)
    if not run.graph:
        run.graph = flows.definition_graph(run.definition); run.save(update_fields=['graph'])
    task = next((t for t in run.tasks.filter(status='pending', kind='approval') if flows.can_act(t, request.user)), None)
    try:
        if action not in ('approve', 'reject'):
            raise ValidationError('Invalid action')
        if not task:
            raise ValidationError('Not authorized for this step')
        flows.decide(task, request.user, action, request.POST.get('comment', '')[:1000] or ('Rejected' if action == 'reject' else ''))
        audit(request, 'workflow_action', f'workflow_run:{pk}', {'action': action})
        messages.success(request, 'Step approved.' if action == 'approve' else 'Submission rejected.')
    except ValidationError as e:
        messages.error(request, '; '.join(e.messages))
    return redirect('studio')


@login_required
@require_POST
def run_resubmit(request, pk):
    authorize(request)
    run = get_object_or_404(WorkflowRun, pk=pk)
    data = _body(request) or {}
    try:
        flows.resubmit(run, request.user, data.get('values') or {})
    except ValidationError as e:
        return JsonResponse({'ok': False, 'error': '; '.join(e.messages)}, status=400)
    audit(request, 'workflow_resubmit', f'workflow_run:{pk}')
    return JsonResponse({'ok': True, 'url': reverse('run_detail', args=[pk])})


@login_required
@require_POST
def run_cancel(request, pk):
    authorize(request)
    run = get_object_or_404(WorkflowRun, pk=pk)
    if not (request.user == run.started_by or role_of(request.user) in ('admin', 'management')):
        raise PermissionDenied('Only the person who started this flow or a manager can cancel it.')
    reason = request.POST.get('reason', '').strip()
    try:
        if len(reason) < 3:
            raise ValidationError('Give a reason for cancelling.')
        flows.cancel(run, request.user, reason)
        messages.success(request, 'Flow cancelled.')
    except ValidationError as e:
        messages.error(request, '; '.join(e.messages))
    return redirect('run_detail', pk=pk)


@login_required
@require_POST
def task_reassign(request, pk):
    authorize(request)
    t = get_object_or_404(WorkflowTask, pk=pk)
    u = get_user_model().objects.filter(pk=request.POST.get('user'), is_active=True).first()
    try:
        if not u:
            raise ValidationError('Choose someone to pass this to.')
        flows.reassign(t, request.user, u)
        messages.success(request, f'Passed to {u.get_full_name() or u.username}.')
    except ValidationError as e:
        messages.error(request, '; '.join(e.messages))
    return redirect('run_detail', pk=t.run_id)
