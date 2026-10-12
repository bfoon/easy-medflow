"""Flow engine: a workflow is a graph of steps; a run moves through it.

Steps (node types) and how each one leaves:
    start       → next, immediately
    fill        someone completes the form fields assigned to this step → next
    approval    people approve or reject (all / any one / at least N) → approved | rejected; may return for changes
    review      people acknowledge → next
    signature   an e-sign envelope goes out → signed | declined
    condition   checks rules on the answers → yes | no
    route       first branch whose rules match → that branch, otherwise → otherwise
    parallel    every outgoing branch at once
    join        waits for every incoming branch → next
    notify      bell + email to people → next
    set         writes a calculated value into the answers → next
    end         outcome "completed" ends this branch; "rejected" ends the whole run as rejected

Rules: an unconnected `rejected`/`declined` exit rejects the run; any other unconnected exit ends that branch. The run is
approved/completed when no branch has work left. Graphs must not loop (a return for changes restarts the open steps).
Old linear workflows ({"steps": [{"name", "role"}]}) are turned into a chain of approval steps.
"""
import math
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import formkit as F

NODE_TYPES = {
    'start': {'label': 'Start', 'icon': 'bi-play-fill', 'color': '#0F7B78', 'ports': ['next'], 'hint': 'Where every run begins.'},
    'fill': {'label': 'Fill in', 'icon': 'bi-input-cursor-text', 'color': '#4A5FC1', 'ports': ['next'], 'hint': 'Someone completes the fields assigned to this step.'},
    'approval': {'label': 'Approval', 'icon': 'bi-patch-check', 'color': '#E0912A', 'ports': ['approved', 'rejected'], 'hint': 'Approve, reject or send back for changes.'},
    'review': {'label': 'Review', 'icon': 'bi-eye', 'color': '#5A6F7D', 'ports': ['next'], 'hint': 'Read and acknowledge. No approve or reject.'},
    'signature': {'label': 'Signature', 'icon': 'bi-pen', 'color': '#0B5F5D', 'ports': ['signed', 'declined'], 'hint': 'Sends the completed form for e-signature and waits.'},
    'condition': {'label': 'Condition', 'icon': 'bi-signpost-split', 'color': '#8A4A8F', 'ports': ['yes', 'no'], 'hint': 'One path or the other, based on the answers.'},
    'route': {'label': 'Route', 'icon': 'bi-signpost-2', 'color': '#8A4A8F', 'ports': [], 'hint': 'Several paths with their own rules, plus Otherwise.'},
    'parallel': {'label': 'In parallel', 'icon': 'bi-diagram-3', 'color': '#2A5A78', 'ports': ['next'], 'hint': 'Start several branches at the same time.'},
    'join': {'label': 'Wait for all', 'icon': 'bi-bezier2', 'color': '#2A5A78', 'ports': ['next'], 'hint': 'Continue once every incoming branch has arrived.'},
    'notify': {'label': 'Notify', 'icon': 'bi-bell', 'color': '#0891B2', 'ports': ['next'], 'hint': 'Tell people and carry on without waiting.'},
    'set': {'label': 'Set a value', 'icon': 'bi-calculator', 'color': '#4A5FC1', 'ports': ['next'], 'hint': 'Write a calculated value into the answers.'},
    'end': {'label': 'End', 'icon': 'bi-flag-fill', 'color': '#16A34A', 'ports': [], 'hint': 'Finish: completed, or rejected.'},
}
PORT_LABELS = {'next': 'Next', 'approved': 'Approved', 'rejected': 'Rejected', 'signed': 'Signed', 'declined': 'Declined',
               'yes': 'Yes', 'no': 'No', 'otherwise': 'Otherwise'}
HUMAN = {'fill', 'approval', 'review', 'signature'}
ASSIGN_MODES = {'role': 'Anyone with a role', 'users': 'Specific people', 'initiator': 'The person who started it',
                'clinician': "The patient's clinician"}
SIGNER_SOURCES = {'initiator': 'The person who started it', 'clinician': "The patient's clinician", 'patient': 'The patient (in person)',
                  'role': 'Someone with a role'}
MAX_NODES = 60


class FlowError(ValidationError):
    pass


def ports_for(node):
    if node.get('type') == 'route':
        return [b['id'] for b in (node.get('config') or {}).get('branches', [])] + ['otherwise']
    return NODE_TYPES.get(node.get('type'), {}).get('ports', [])


# ------------------------------------------------------------------ graph cleaning
def _s(v, n):
    return str(v if v is not None else '').strip()[:n]


def _clean_assign(a, roles):
    a = a if isinstance(a, dict) else {}
    mode = a.get('mode') if a.get('mode') in ASSIGN_MODES else 'role'
    out = {'mode': mode}
    if mode == 'role':
        out['role'] = a.get('role') if a.get('role') in roles else 'doctor'
    if mode == 'users':
        ids = []
        for x in a.get('users') or []:
            try:
                ids.append(int(x))
            except (TypeError, ValueError):
                pass
        out['users'] = sorted(set(ids))[:20]
    return out


def clean_graph(raw, form_schema=None, roles=()):
    """Return (graph, errors). Positions are kept for the designer."""
    roles = set(roles) or {'admin', 'doctor', 'nurse', 'reception', 'lab', 'radiology', 'pharmacy', 'finance', 'management'}
    errors = []
    raw = raw if isinstance(raw, dict) else {}
    keys = {f['key'] for f in (form_schema or {}).get('fields', []) if f.get('type') in F.INPUT_TYPES}
    nodes, ids = [], set()
    for n in (raw.get('nodes') or [])[:MAX_NODES + 1]:
        if not isinstance(n, dict) or n.get('type') not in NODE_TYPES:
            errors.append('A step has an unknown type.'); continue
        nid = _s(n.get('id'), 40)
        if not nid or not nid.replace('_', '').replace('-', '').isalnum() or nid in ids:
            errors.append('Every step needs a different id.'); continue
        ids.add(nid)
        t, cfg = n['type'], n.get('config') if isinstance(n.get('config'), dict) else {}
        c = {}
        if t in ('fill', 'approval', 'review', 'notify'):
            c['assign'] = _clean_assign(cfg.get('assign'), roles)
            if c['assign']['mode'] == 'users' and not c['assign']['users']:
                errors.append(f'“{n.get("label") or t}”: choose at least one person.')
        if t in ('fill', 'approval', 'review'):
            due = F._as_num(cfg.get('due_hours'))
            if due:
                c['due_hours'] = max(1, min(24 * 30, int(due)))
                if cfg.get('escalate_role') in roles:
                    c['escalate_role'] = cfg['escalate_role']
        if t == 'approval':
            c['mode'] = cfg.get('mode') if cfg.get('mode') in ('any', 'all', 'quorum') else 'any'
            c['quorum'] = max(1, min(10, int(F._as_num(cfg.get('quorum')) or 2))) if c['mode'] == 'quorum' else 1
            c['allow_return'] = cfg.get('allow_return', True) is not False
        if t == 'notify':
            c['message'] = _s(cfg.get('message'), 300) or 'A form you follow has moved on.'
        if t == 'signature':
            signers = []
            for s in (cfg.get('signers') or [])[:6]:
                if not isinstance(s, dict) or s.get('source') not in SIGNER_SOURCES:
                    continue
                x = {'source': s['source'], 'as': s.get('as') if s.get('as') in ('signer', 'in_person', 'witness', 'approver') else ('in_person' if s['source'] == 'patient' else 'signer'),
                     'order': max(1, min(9, int(F._as_num(s.get('order')) or 1)))}
                if s['source'] == 'role':
                    x['role'] = s.get('role') if s.get('role') in roles else 'doctor'
                signers.append(x)
            if not signers:
                errors.append(f'“{n.get("label") or "Signature"}”: add at least one signer.')
            c['signers'] = signers
            c['require_full_read'] = bool(cfg.get('require_full_read'))
        if t == 'condition':
            errs = []
            c['rules'] = F.clean_tree(cfg.get('rules'), keys, errors=errs) if keys else None
            errors += [f'“{n.get("label") or "Condition"}”: {e}' for e in errs]
            if not c['rules']:
                errors.append(f'“{n.get("label") or "Condition"}”: add at least one rule (the flow needs a form for rules).')
        if t == 'route':
            branches, bids = [], set()
            for b in (cfg.get('branches') or [])[:8]:
                if not isinstance(b, dict):
                    continue
                bid = _s(b.get('id'), 20)
                if not bid or bid in bids or bid in PORT_LABELS:
                    continue
                bids.add(bid)
                errs = []
                rules = F.clean_tree(b.get('rules'), keys, errors=errs) if keys else None
                errors += [f'Route branch “{b.get("label") or bid}”: {e}' for e in errs]
                if not rules:
                    errors.append(f'Route branch “{b.get("label") or bid}” needs rules.')
                branches.append({'id': bid, 'label': _s(b.get('label'), 40) or bid, 'rules': rules})
            if not branches:
                errors.append(f'“{n.get("label") or "Route"}”: add at least one path.')
            c['branches'] = branches
        if t == 'set':
            c['field'] = _s(cfg.get('field'), 40)
            c['formula'] = _s(cfg.get('formula'), 500)
            if c['field'] not in keys:
                errors.append(f'“{n.get("label") or "Set a value"}”: choose a form field to write to.')
            try:
                missing = F.formula_vars(F.parse(c['formula'])) - keys
                if missing:
                    errors.append(f'“{n.get("label") or "Set a value"}” uses fields that do not exist: {", ".join(sorted(missing))}.')
            except F.FormulaError as exc:
                errors.append(f'“{n.get("label") or "Set a value"}”: {exc}')
        if t == 'end':
            c['outcome'] = 'rejected' if cfg.get('outcome') == 'rejected' else 'completed'
        nodes.append({'id': nid, 'type': t, 'label': _s(n.get('label'), 60) or NODE_TYPES[t]['label'],
                      'x': F._as_num(n.get('x')) or 0, 'y': F._as_num(n.get('y')) or 0, 'config': c})
    if len(nodes) > MAX_NODES:
        errors.append(f'A flow can have at most {MAX_NODES} steps.')
    by_id = {n['id']: n for n in nodes}
    edges, seen = [], set()
    for e in (raw.get('edges') or [])[:400]:
        if not isinstance(e, dict):
            continue
        a, b, port = _s(e.get('from'), 40), _s(e.get('to'), 40), _s(e.get('port'), 20) or 'next'
        if a not in by_id or b not in by_id or a == b:
            continue
        if port not in ports_for(by_id[a]):
            continue
        if by_id[a]['type'] != 'parallel' and any(x['from'] == a and x['port'] == port for x in edges):
            errors.append(f'“{by_id[a]["label"]}” has two arrows from the same exit ({PORT_LABELS.get(port, port)}).'); continue
        if (a, port, b) in seen:
            continue
        seen.add((a, port, b))
        edges.append({'id': f'e{len(edges) + 1}', 'from': a, 'port': port, 'to': b})
    starts = [n for n in nodes if n['type'] == 'start']
    if len(starts) != 1:
        errors.append('A flow needs exactly one Start step.')
    if not any(n['type'] == 'end' for n in nodes) and nodes:
        pass                                                     # unconnected exits end a branch; an End step is optional
    if starts:
        if any(e['to'] == starts[0]['id'] for e in edges):
            errors.append('Nothing can lead back into Start.')
        # reachability and loops
        out = {}
        for e in edges:
            out.setdefault(e['from'], []).append(e['to'])
        reach, stack = set(), [starts[0]['id']]
        while stack:
            x = stack.pop()
            if x not in reach:
                reach.add(x); stack += out.get(x, [])
        for n in nodes:
            if n['id'] not in reach:
                errors.append(f'“{n["label"]}” cannot be reached from Start.')
        state = {}

        def dfs(x):
            state[x] = 1
            for y in out.get(x, []):
                if state.get(y) == 1:
                    raise FlowError(f'The flow loops back to “{by_id[y]["label"]}”. Use “send back for changes” instead of loops.')
                if not state.get(y):
                    dfs(y)
            state[x] = 2
        try:
            dfs(starts[0]['id'])
        except FlowError as exc:
            errors.append(exc.messages[0])
    for n in nodes:
        if n['type'] == 'join' and sum(1 for e in edges if e['to'] == n['id']) < 2:
            errors.append(f'“{n["label"]}” waits for branches but fewer than two arrive.')
        if n['type'] == 'parallel' and sum(1 for e in edges if e['from'] == n['id']) < 2:
            errors.append(f'“{n["label"]}” should start at least two branches.')
        if n['type'] == 'fill' and keys and form_schema and not any(f.get('filled_by') == n['id'] for f in form_schema.get('fields', [])):
            errors.append(f'“{n["label"]}”: no form fields are assigned to this step (set “Filled in at” on the fields).')
    return {'nodes': nodes, 'edges': edges}, errors


def graph_from_steps(steps):
    nodes = [{'id': 'start', 'type': 'start', 'label': 'Start', 'x': 40, 'y': 120, 'config': {}}]
    edges, prev = [], 'start'
    for i, s in enumerate(steps or []):
        nid = f's{i + 1}'
        nodes.append({'id': nid, 'type': 'approval', 'label': str(s.get('name', f'Step {i + 1}'))[:60], 'x': 220 + i * 190, 'y': 120,
                      'config': {'assign': {'mode': 'role', 'role': s.get('role', 'doctor')}, 'mode': 'any', 'quorum': 1, 'allow_return': False}})
        edges.append({'id': f'e{i + 1}', 'from': prev, 'port': 'next' if prev == 'start' else 'approved', 'to': nid})
        prev = nid
    nodes.append({'id': 'end', 'type': 'end', 'label': 'Approved', 'x': 220 + len(steps or []) * 190, 'y': 120, 'config': {'outcome': 'completed'}})
    edges.append({'id': f'e{len(edges) + 1}', 'from': prev, 'port': 'next' if prev == 'start' else 'approved', 'to': 'end'})
    return {'nodes': nodes, 'edges': edges}


def definition_graph(defn):
    return defn.graph if defn.graph and defn.graph.get('nodes') else graph_from_steps(defn.steps if isinstance(defn.steps, list) else [])


# ------------------------------------------------------------------ people
def role_of(user):
    if user.is_superuser:
        return 'admin'
    p = getattr(user, 'hospital_staff', None)
    return p.role if p and p.active else None


def users_with_role(role):
    from .models import StaffProfile
    return [p.user for p in StaffProfile.objects.filter(role=role, active=True).select_related('user') if p.user.is_active]


def can_act(task, user):
    if task.status != 'pending':
        return False
    if task.user_id:
        return task.user_id == user.pk or user.is_superuser
    return user.is_superuser or (task.role and role_of(user) == task.role)


def resolve_assignees(run, assign):
    """[(user or None, role or '')] — one entry per seat."""
    mode = assign.get('mode')
    if mode == 'role':
        return [(None, assign['role'])]
    if mode == 'users':
        return [(u, '') for u in get_user_model().objects.filter(pk__in=assign.get('users', []), is_active=True)]
    if mode == 'initiator':
        return [(run.started_by or run.submission.submitted_by, '')]
    if mode == 'clinician':
        enc = run.submission.encounter
        u = enc.clinician if enc and enc.clinician_id else run.submission.submitted_by
        return [(u, '')]
    return []


# ------------------------------------------------------------------ engine
def _log(run, kind, node_id='', actor=None, note='', **details):
    from .models import WorkflowEvent
    WorkflowEvent.objects.create(run=run, kind=kind, node_id=node_id, actor=actor, note=note[:400], details=details)


def _node(run, nid):
    return next(n for n in run.graph['nodes'] if n['id'] == nid)


def _url(run):
    return f'/studio/runs/{run.pk}/'


def _notify(users, title, body, url):
    from .notify import notify
    notify([u for u in users if u], title, body, url, kind='flow')


@transaction.atomic
def start_run(definition, submission, user):
    from .models import WorkflowRun
    run = WorkflowRun.objects.create(definition=definition, submission=submission, started_by=user,
                                     graph=definition_graph(definition), state={'active': [], 'arrived': {}})
    _log(run, 'started', actor=user, note=f'Started by {user.get_full_name() or user.username}')
    start = next(n for n in run.graph['nodes'] if n['type'] == 'start')
    _drive(run, [('enter', start['id'], None)])
    return run


def _drive(run, queue):
    """Process enter/leave actions until only human work (or nothing) is left."""
    guard = 0
    while queue:
        guard += 1
        if guard > 500:
            _finish(run, 'rejected', 'The flow took too many automatic steps and was stopped.'); return
        action, nid, port = queue.pop(0)
        if run.status not in ('open',):
            return
        if action == 'enter':
            queue += _enter(run, _node(run, nid))
        else:
            queue += _leave(run, _node(run, nid), port)
    _settle(run)


def _values(run):
    return run.submission.values or {}


def _enter(run, node):
    t, cfg, nid = node['type'], node.get('config', {}), node['id']
    _log(run, 'entered', nid, note=node['label'])
    if t in ('start', 'parallel'):
        return [('leave', nid, 'next')]
    if t == 'condition':
        ok = F.check(cfg.get('rules'), _values(run))
        _log(run, 'decided', nid, note=f'{node["label"]}: {"yes" if ok else "no"}')
        return [('leave', nid, 'yes' if ok else 'no')]
    if t == 'route':
        for b in cfg.get('branches', []):
            if F.check(b.get('rules'), _values(run)):
                _log(run, 'decided', nid, note=f'{node["label"]}: {b["label"]}')
                return [('leave', nid, b['id'])]
        _log(run, 'decided', nid, note=f'{node["label"]}: otherwise')
        return [('leave', nid, 'otherwise')]
    if t == 'join':
        incoming = [e['id'] for e in run.graph['edges'] if e['to'] == nid]
        arrived = set(run.state.setdefault('arrived', {}).get(nid, []))
        if arrived >= set(incoming):
            run.state['arrived'][nid] = []
            return [('leave', nid, 'next')]
        return []
    if t == 'notify':
        people = []
        for u, role in resolve_assignees(run, cfg.get('assign', {})):
            people += [u] if u else users_with_role(role)
        _notify(people, cfg.get('message', 'Update'), f'{run.definition.name} · {run.submission.patient.full_name}', _url(run))
        return [('leave', nid, 'next')]
    if t == 'set':
        val = F.run_formula(cfg.get('formula', ''), _values(run))
        sub = run.submission
        sub.values = {**(sub.values or {}), cfg['field']: val}
        sub.save(update_fields=['values', 'updated_at'])
        _log(run, 'value_set', nid, note=f'{cfg["field"]} = {F._text(val)}')
        return [('leave', nid, 'next')]
    if t == 'end':
        if cfg.get('outcome') == 'rejected':
            _finish(run, 'rejected', f'Ended at “{node["label"]}”.')
        else:
            _log(run, 'branch_done', nid, note=node['label'])
        return []
    if t in HUMAN:
        run.state.setdefault('active', [])
        if nid not in run.state['active']:
            run.state['active'].append(nid)
        if t == 'signature':
            from . import esign
            env = esign.envelope_for_flow(run, node)
            _log(run, 'envelope_sent', nid, note=f'Envelope {env.short_id} sent for signature')
        else:
            _create_tasks(run, node)
        run.save(update_fields=['state', 'updated_at'])
        return []
    return []


def _create_tasks(run, node):
    from .models import WorkflowTask
    cfg = node['config']
    due = timezone.now() + timedelta(hours=cfg['due_hours']) if cfg.get('due_hours') else None
    seats = resolve_assignees(run, cfg.get('assign', {}))
    if node['type'] == 'approval' and cfg.get('mode') == 'quorum' and len(seats) == 1 and seats[0][0] is None:
        seats = seats * cfg.get('quorum', 1)                  # role-based quorum: N separate seats
    people = []
    for u, role in seats:
        WorkflowTask.objects.create(run=run, node_id=node['id'], kind=node['type'], label=node['label'], user=u, role=role or '',
                                    due_at=due, round=run.round)
        people += [u] if u else users_with_role(role)
    verb = {'approval': 'Approval needed', 'review': 'Please review', 'fill': 'Please complete'}[node['type']]
    _notify(people, f'{verb}: {run.definition.name}', f'{node["label"]} · {run.submission.patient.full_name}', _url(run))


def _leave(run, node, port):
    nid = node['id']
    if nid in run.state.get('active', []):
        run.state['active'].remove(nid)
    _log(run, 'left', nid, note=f'{node["label"]} → {PORT_LABELS.get(port, port)}', port=port)
    if node['type'] == 'approval' and port == 'approved':
        run.step_index += 1
    nxt = [e for e in run.graph['edges'] if e['from'] == nid and e['port'] == port]
    if not nxt:
        if port in ('rejected', 'declined'):
            _finish(run, 'rejected', f'{node["label"]}: {PORT_LABELS[port].lower()}.')
        return []
    actions = []
    for e in nxt:
        target = _node(run, e['to'])
        if target['type'] == 'join':
            run.state.setdefault('arrived', {}).setdefault(target['id'], [])
            if e['id'] not in run.state['arrived'][target['id']]:
                run.state['arrived'][target['id']].append(e['id'])
        actions.append(('enter', e['to'], None))
    run.save(update_fields=['state', 'step_index', 'updated_at'])
    return actions


def _settle(run):
    run.refresh_from_db(fields=['status'])
    if run.status != 'open':
        return
    from .models import WorkflowTask
    waiting = run.state.get('active') or []
    joins = [k for k, v in (run.state.get('arrived') or {}).items() if v]
    if not waiting and not WorkflowTask.objects.filter(run=run, status='pending').exists():
        if joins:
            _finish(run, 'rejected', 'A branch ended before reaching “Wait for all”, so the flow cannot finish.')
        else:
            _finish(run, 'approved', 'Every step is complete.')
    else:
        run.save(update_fields=['state', 'updated_at'])


def _finish(run, status, note):
    from .models import WorkflowTask
    run.status = status
    run.completed_at = timezone.now()
    run.save(update_fields=['status', 'completed_at', 'state', 'step_index', 'updated_at'])
    WorkflowTask.objects.filter(run=run, status='pending').update(status='skipped')
    for env in run.envelopes.filter(status='sent'):
        from . import esign
        esign.void(env, None, 'The flow it belonged to has finished.')
    sub = run.submission
    sub.status = 'approved' if status == 'approved' else 'rejected'
    sub.save(update_fields=['status', 'updated_at'])
    _log(run, 'finished', note=note, status=status)
    _notify([run.started_by or sub.submitted_by], f'{run.definition.name}: {"approved" if status == "approved" else "rejected"}',
            f'{sub.patient.full_name} · {note}', _url(run))


# ------------------------------------------------------------------ human decisions
@transaction.atomic
def decide(task, user, action, comment='', values=None):
    """approve | reject | return (approval); acknowledge (review); submit (fill, with values)."""
    from .models import WorkflowAction, WorkflowRun, WorkflowTask
    run = WorkflowRun.objects.select_for_update().get(pk=task.run_id)
    task = WorkflowTask.objects.select_for_update().get(pk=task.pk)
    if run.status != 'open':
        raise FlowError('This flow is no longer in progress.')
    if not can_act(task, user):
        raise FlowError('This step is not assigned to you, or it has already been done.')
    node = _node(run, task.node_id)
    cfg = node['config']
    allowed = {'approval': {'approve', 'reject'} | ({'return'} if cfg.get('allow_return') else set()),
               'review': {'acknowledge'}, 'fill': {'submit'}}[task.kind]
    if action not in allowed:
        raise FlowError('That action is not available on this step.')
    if task.kind == 'approval' and WorkflowTask.objects.filter(run=run, node_id=task.node_id, round=run.round, decided_by=user).exists():
        raise FlowError('You have already decided on this step; someone else must take the other places.')
    if action in ('reject', 'return') and not comment.strip():
        raise FlowError('Say why, so the person can act on it.')
    if task.kind == 'fill':
        sub = run.submission
        schema = sub.schema_snapshot
        clean, errors, _ = F.evaluate_form(schema, values or {}, scope=task.node_id, previous=sub.values)
        if errors:
            raise FlowError([f'{k}: {v}' for k, v in errors.items()])
        sub.values = clean
        sub.save(update_fields=['values', 'updated_at'])
    task.status = {'approve': 'approved', 'reject': 'rejected', 'return': 'returned', 'acknowledge': 'done', 'submit': 'done'}[action]
    task.decided_by, task.decided_at, task.comment = user, timezone.now(), comment[:2000]
    task.save()
    WorkflowAction.objects.create(run=run, step_index=run.step_index, action={'acknowledge': 'review', 'submit': 'fill'}.get(action, action),
                                  actor=user, comment=comment[:1000])
    _log(run, action, task.node_id, actor=user, note=f'{user.get_full_name() or user.username}: {action}{" · " + comment[:200] if comment else ""}')
    if action == 'return':
        return _return_for_changes(run, task, comment)
    siblings = WorkflowTask.objects.filter(run=run, node_id=task.node_id, round=run.round).exclude(status__in=['skipped', 'cancelled'])
    port = None
    if task.kind == 'approval':
        approved = siblings.filter(status='approved').count()
        rejected = siblings.filter(status='rejected').count()
        pending = siblings.filter(status='pending').count()
        mode, need = cfg.get('mode', 'any'), cfg.get('quorum', 1)
        if mode == 'any':
            port = 'approved' if approved else ('rejected' if not pending else None)
        elif mode == 'all':
            port = 'rejected' if rejected else ('approved' if not pending else None)
        else:
            port = 'approved' if approved >= need else ('rejected' if approved + pending < need else None)
    elif not siblings.filter(status='pending').exists() or task.kind == 'fill':
        port = 'next'
    if port:
        siblings.filter(status='pending').update(status='skipped')
        _drive(run, [('leave', task.node_id, port)])
    return run


def _return_for_changes(run, task, comment):
    from .models import WorkflowTask
    WorkflowTask.objects.filter(run=run, status='pending').update(status='cancelled')
    run.state['returned'] = list(run.state.get('active', []))
    run.state['active'] = []
    run.status = 'returned'
    run.save(update_fields=['state', 'status', 'updated_at'])
    _log(run, 'returned', task.node_id, actor=task.decided_by, note=f'Sent back for changes: {comment[:200]}')
    _notify([run.started_by or run.submission.submitted_by], f'Changes requested: {run.definition.name}', comment[:300], _url(run))
    return run


@transaction.atomic
def resubmit(run, user, values):
    from .models import WorkflowRun
    run = WorkflowRun.objects.select_for_update().get(pk=run.pk)
    if run.status != 'returned':
        raise FlowError('This flow is not waiting for changes.')
    if user != (run.started_by or run.submission.submitted_by) and not user.is_superuser:
        raise FlowError('Only the person who started this flow can resubmit it.')
    sub = run.submission
    clean, errors, _ = F.evaluate_form(sub.schema_snapshot, values or {}, previous=sub.values)
    if errors:
        raise FlowError([f'{k}: {v}' for k, v in errors.items()])
    sub.values = clean
    sub.save(update_fields=['values', 'updated_at'])
    run.status, run.round = 'open', run.round + 1
    nodes = run.state.pop('returned', [])
    run.save(update_fields=['status', 'round', 'state', 'updated_at'])
    _log(run, 'resubmitted', actor=user, note=f'Resubmitted (round {run.round})')
    _drive(run, [('enter', n, None) for n in nodes])
    return run


@transaction.atomic
def cancel(run, user, reason):
    from .models import WorkflowRun
    run = WorkflowRun.objects.select_for_update().get(pk=run.pk)
    if run.status not in ('open', 'returned'):
        raise FlowError('This flow has already finished.')
    run.status = 'cancelled'
    run.completed_at = timezone.now()
    run.save(update_fields=['status', 'completed_at', 'updated_at'])
    run.tasks.filter(status='pending').update(status='cancelled')
    from . import esign
    for env in run.envelopes.filter(status='sent'):
        esign.void(env, user, f'Flow cancelled: {reason}')
    _log(run, 'cancelled', actor=user, note=reason[:300])


@transaction.atomic
def reassign(task, user, new_user):
    if task.status != 'pending':
        raise FlowError('Only waiting steps can be passed on.')
    if not (can_act(task, user) or role_of(user) in ('admin', 'management')):
        raise FlowError('You cannot pass this step on.')
    old = task.user
    task.user, task.role = new_user, ''
    task.save(update_fields=['user', 'role', 'updated_at'])
    _log(task.run, 'reassigned', task.node_id, actor=user, note=f'Passed to {new_user.get_full_name() or new_user.username}')
    _notify([new_user], f'Passed to you: {task.label}', task.run.definition.name, _url(task.run))
    return old


def on_envelope(envelope):
    """Called by esign when an envelope that belongs to a flow is completed or declined."""
    from .models import WorkflowRun
    if not envelope.run_id or not envelope.node_id:
        return
    with transaction.atomic():
        run = WorkflowRun.objects.select_for_update().get(pk=envelope.run_id)
        if run.status != 'open' or envelope.node_id not in run.state.get('active', []):
            return
        envelope.tasks.filter(status='pending').update(status='done' if envelope.status == 'completed' else 'rejected', decided_at=timezone.now())
        _drive(run, [('leave', envelope.node_id, 'signed' if envelope.status == 'completed' else 'declined')])


def sweep(now=None):
    """Escalate overdue steps (call from a scheduler or any page load). Returns the number escalated."""
    from .models import WorkflowTask
    now = now or timezone.now()
    n = 0
    for t in WorkflowTask.objects.filter(status='pending', due_at__lt=now, escalated_at__isnull=True).select_related('run__definition', 'run__submission__patient')[:200]:
        cfg = _node(t.run, t.node_id).get('config', {})
        people = users_with_role(cfg['escalate_role']) if cfg.get('escalate_role') else []
        people += [t.user] if t.user else users_with_role(t.role)
        _notify(people, f'Overdue: {t.label}', f'{t.run.definition.name} · {t.run.submission.patient.full_name}', _url(t.run))
        t.escalated_at = now
        t.save(update_fields=['escalated_at'])
        _log(t.run, 'escalated', t.node_id, note=f'{t.label} is overdue' + (f'; escalated to {cfg["escalate_role"]}' if cfg.get('escalate_role') else ''))
        n += 1
    return n


def tasks_for(user):
    from .models import WorkflowTask
    from django.db.models import Q
    q = Q(user=user)
    r = role_of(user)
    if r:
        q |= Q(user__isnull=True, role=r)
    qs = WorkflowTask.objects.filter(status='pending', run__status='open').select_related('run__definition', 'run__submission__patient', 'envelope')
    return qs if user.is_superuser else qs.filter(q)


def run_view(run):
    """State of every step for the animated flow map."""
    from .models import WorkflowTask
    st = {}
    for ev in run.events.all():
        if ev.kind == 'entered':
            st[ev.node_id] = 'active'
        if ev.kind in ('left', 'branch_done', 'decided'):
            st[ev.node_id] = 'done'
    for nid in run.state.get('active', []):
        st[nid] = 'active'
    for nid in run.state.get('returned', []):
        st[nid] = 'returned'
    taken = [{'from': ev.node_id, 'port': ev.details.get('port')} for ev in run.events.filter(kind='left')]
    tasks = {}
    for t in WorkflowTask.objects.filter(run=run, round=run.round):
        tasks.setdefault(t.node_id, []).append({'status': t.status, 'who': (t.user.get_full_name() or t.user.username) if t.user else (t.role or '').title(),
                                                 'overdue': bool(t.overdue)})
    return {'graph': run.graph, 'state': st, 'taken': taken, 'tasks': tasks, 'status': run.status}


def catalogue(roles):
    return {'types': NODE_TYPES, 'ports': PORT_LABELS, 'assign_modes': ASSIGN_MODES, 'signer_sources': SIGNER_SOURCES,
            'roles': sorted(roles), 'formkit': F.catalogue()}
