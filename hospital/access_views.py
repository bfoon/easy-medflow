"""Access & roles: hospital administrators create groups, choose what each group may do, allocate staff to groups and
change roles. Also the emergency ("break the glass") access to a patient outside the user's scope."""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import access as A
from .models import AccessGroup, AuditEvent, Patient, StaffProfile
from .views import audit, role_of


def _admin(request):
    if not (request.user.is_superuser or A.has(request.user, 'access_admin')):
        raise PermissionDenied('Only access administrators can manage access and roles.')


def _sections():
    out = {}
    for key, label, section, help_ in A.CAPABILITIES:
        out.setdefault(section, []).append({'key': key, 'label': label, 'help': help_})
    return out


@login_required
def manage(request):
    _admin(request)
    U = get_user_model()
    tab = request.GET.get('tab', 'groups')
    groups = list(AccessGroup.objects.annotate(n=Count('members')).prefetch_related('members'))
    staff = (U.objects.filter(Q(hospital_staff__isnull=False) | Q(is_superuser=True)).select_related('hospital_staff')
             .prefetch_related('access_groups').order_by('hospital_staff__role', 'first_name', 'username'))
    rows = []
    for u in staff:
        role = role_of(u) if not u.is_superuser else 'admin'
        gs = list(u.access_groups.all())
        rows.append({'u': u, 'role': getattr(getattr(u, 'hospital_staff', None), 'role', ''), 'active': getattr(getattr(u, 'hospital_staff', None), 'active', True),
                     'groups': gs, 'group_ids': {g.pk for g in gs}, 'super': u.is_superuser,
                     'summary': 'Superuser: everything' if u.is_superuser else (', '.join(g.name for g in gs) if gs else f'Standard access for {role or "no role"}'),
                     'scope': 'All patients' if u.is_superuser or A.has(u, 'all_patients') else ('Patients in care now' if A.has(u, 'patient_records') else 'No patient records')})
    log = AuditEvent.objects.filter(action__in=['break_glass', 'access_group', 'access_member', 'access_role']).select_related('actor')[:60]
    glass = []
    for ev in log:
        if ev.action == 'break_glass' and ev.target.startswith('patient:'):
            ev.patient = Patient.objects.filter(pk=ev.target.split(':')[1]).first()
        glass.append(ev)
    return render(request, 'hospital/access/manage.html', {
        'tab': tab, 'groups': groups, 'rows': rows, 'sections': _sections(), 'roles': StaffProfile.ROLE, 'log': glass,
        'standard': A.STANDARD_GROUPS, 'labels': A.CAP_LABELS, 'missing_standard': [g for g in A.STANDARD_GROUPS if not any(x.name == g[0] for x in groups)]})


@login_required
@require_POST
def group_save(request, pk=None):
    _admin(request)
    g = get_object_or_404(AccessGroup, pk=pk) if pk else AccessGroup(created_by=request.user)
    name = request.POST.get('name', '').strip()[:80]
    if not name:
        messages.error(request, 'Give the group a name.')
        return redirect(reverse('access') + '?tab=groups')
    if AccessGroup.objects.filter(name__iexact=name).exclude(pk=g.pk).exists():
        messages.error(request, f'There is already a group called {name}.')
        return redirect(reverse('access') + '?tab=groups')
    chosen = [c for c in request.POST.getlist('cap') if c in A.CAP_KEYS]
    if 'all' not in chosen:
        chosen.insert(0, 'all')
    before = set(g.capabilities or [])
    # an administrator cannot lock themselves out by removing their own access-management right
    if g.pk and 'access_admin' in before and 'access_admin' not in chosen and not request.user.is_superuser and _would_lose_admin(request.user, g):
        messages.error(request, 'You would lose access to this page. Ask another administrator to make this change.')
        return redirect(reverse('access') + f'?tab=groups#g{g.pk}')
    g.name, g.description, g.capabilities = name, request.POST.get('description', '').strip()[:240], chosen
    g.save()
    audit(request, 'access_group', f'access_group:{g.pk}', {'name': name, 'added': sorted(set(chosen) - before), 'removed': sorted(before - set(chosen))})
    messages.success(request, f'Group “{name}” saved.')
    return redirect(reverse('access') + f'?tab=groups#g{g.pk}')


def _would_lose_admin(user, group):
    others = user.access_groups.exclude(pk=group.pk)
    return user.access_groups.filter(pk=group.pk).exists() and not any('access_admin' in (o.capabilities or []) for o in others)


@login_required
@require_POST
def group_delete(request, pk):
    _admin(request)
    g = get_object_or_404(AccessGroup, pk=pk)
    if not request.user.is_superuser and 'access_admin' in (g.capabilities or []) and _would_lose_admin(request.user, g):
        messages.error(request, 'You would lose access to this page. Ask another administrator to delete this group.')
        return redirect(reverse('access') + '?tab=groups')
    n = g.members.count()
    audit(request, 'access_group', f'access_group:{g.pk}', {'deleted': g.name, 'members': n})
    g.delete()
    messages.success(request, f'Group deleted. Its {n} member{"s" if n != 1 else ""} now use their other groups, or the standard access of their role.')
    return redirect(reverse('access') + '?tab=groups')


@login_required
@require_POST
def standard_groups(request):
    """Create the standard groups (only those missing), each starting from the standard access of its role."""
    _admin(request)
    made = 0
    for name, role, desc in A.STANDARD_GROUPS:
        if AccessGroup.objects.filter(name=name).exists():
            continue
        cap = sorted(A.VIEW_ONLY_PHARMACY) if role is None else sorted(c for c in A.role_defaults(role) if c in A.CAP_KEYS)
        AccessGroup.objects.create(name=name, description=desc, capabilities=cap, created_by=request.user)
        made += 1
    audit(request, 'access_group', 'access_group:standard', {'created': made})
    messages.success(request, f'{made} standard group{"s" if made != 1 else ""} created. Nobody is in them yet: allocate staff on the Staff tab.')
    return redirect(reverse('access') + '?tab=groups')


@login_required
@require_POST
def member_save(request, user_pk):
    """Change one staff member's role, active flag and groups."""
    _admin(request)
    u = get_object_or_404(get_user_model(), pk=user_pk)
    if u.is_superuser and not request.user.is_superuser:
        raise PermissionDenied('Only a superuser can change a superuser.')
    prof = getattr(u, 'hospital_staff', None)
    ids = {int(x) for x in request.POST.getlist('groups') if x.isdigit()}
    new_groups = list(AccessGroup.objects.filter(pk__in=ids))
    role = request.POST.get('role', '')
    if u == request.user and not request.user.is_superuser:
        keeps = any('access_admin' in (g.capabilities or []) for g in new_groups) or (not new_groups and role == 'admin')
        if not keeps:
            messages.error(request, 'You cannot remove your own access to this page.')
            return redirect(reverse('access') + '?tab=staff')
    with transaction.atomic():
        before = {'role': prof.role if prof else '', 'groups': sorted(g.name for g in u.access_groups.all())}
        if prof and role in dict(StaffProfile.ROLE):
            prof.role = role
        if prof and u != request.user:
            prof.active = request.POST.get('active') == 'on'
        if prof:
            prof.save()
        u.access_groups.set(new_groups)
    after = {'role': prof.role if prof else '', 'groups': sorted(g.name for g in new_groups)}
    audit(request, 'access_member', f'user:{u.pk}', {'before': before, 'after': after})
    messages.success(request, f'Access for {u.get_full_name() or u.username} saved.')
    return redirect(reverse('access') + f'?tab=staff#u{u.pk}')


@login_required
@require_POST
def emergency(request, pk):
    p = get_object_or_404(Patient, pk=pk)
    if not A.has(request.user, 'break_glass'):
        raise PermissionDenied('Your access does not include emergency access.')
    reason = request.POST.get('reason', '').strip()[:300]
    if len(reason) < 10:
        messages.error(request, 'Write a reason of at least a few words.')
    else:
        A.grant_emergency(request, p, reason)
        messages.warning(request, f'Emergency access to {p.full_name} for {A.EMERGENCY_HOURS} hours. This has been logged.')
    nxt = request.POST.get('next') or reverse('patient_chart', args=[p.pk])
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        nxt = reverse('patient_chart', args=[p.pk])
    return redirect(nxt)
