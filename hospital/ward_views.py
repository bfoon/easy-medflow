"""Wards.

/wards/                       every ward as a card: occupancy, free beds, acuity, alerts, visiting
/wards/<pk>/                  the ward: floor plan by NEWS2, attention list, patients, handover board, 14-day chart, contacts
/wards/<pk>/?screen=1         nurses' station screen: initials only, large, refreshes itself
/wards/<pk>/handover/         printable handover sheet for the shift
/wards/new/  /wards/<pk>/edit/   details, visiting hours, people in charge, add beds in bulk
"""
from datetime import time

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import wards as W
from .models import Bed, Patient, Ward, WardNote
from .models_wards import current_shift
from .views import audit, authorize


def _can(request, *caps):
    from .access import has
    return request.user.is_superuser or any(has(request.user, c) for c in caps)


def _wards_qs():
    return Ward.objects.prefetch_related('bed_set').select_related('nurse_in_charge', 'lead_clinician')


@login_required
def wards_index(request):
    authorize(request)
    show_all = request.GET.get('all') == '1'
    qs = _wards_qs() if show_all else _wards_qs().filter(active=True)
    cards = []
    for w in qs:
        snap = W.snapshot(w, light=True)
        alerts = w.notes.filter(kind='alert', resolved_at__isnull=True).count()
        cards.append(dict(snap, alerts=alerts, ring=_ring(snap['stats']['pct'])))
    totals = {k: sum(c['stats'][k] for c in cards) for k in ('total', 'occupied', 'free', 'cleaning', 'overdue')}
    totals['pct'] = round(totals['occupied'] * 100 / totals['total']) if totals['total'] else 0
    totals['critical'] = sum(c['stats']['acuity']['critical'] + c['stats']['acuity']['urgent'] for c in cards)
    return render(request, 'hospital/wards/index.html', {'cards': cards, 'totals': totals, 'show_all': show_all,
                                                         'can_edit': _can(request, 'beds'), 'acuity_keys': W.ACUITY})


def _ring(pct):
    """Stroke offset for the SVG occupancy ring (r=34)."""
    c = 2 * 3.14159 * 34
    return {'c': round(c, 1), 'off': round(c * (1 - min(100, pct) / 100), 1)}


@login_required
def ward_detail(request, pk):
    authorize(request)
    w = get_object_or_404(_wards_qs(), pk=pk)
    snap = W.snapshot(w)
    if request.GET.get('screen') == '1':
        return render(request, 'hospital/wards/screen.html', dict(snap, now=timezone.localtime(), acuity_keys=W.ACUITY))
    audit(request, 'view_ward', f'ward:{w.pk}')
    notes = list(w.notes.select_related('author', 'patient', 'resolved_by')[:40])
    hist = W.history(w)
    peak = max([d['occupied'] for d in hist] + [snap['stats']['total'], 1])
    occupied_patients = [r['p'] for r in snap['rows'] if r['a']]
    return render(request, 'hospital/wards/detail.html', dict(
        snap, notes=notes, alerts=[n for n in notes if n.open_alert], history=hist, peak=peak, moves=W.today_moves(w),
        ring=_ring(snap['stats']['pct']), shift=current_shift(), occupied_patients=occupied_patients, acuity_keys=W.ACUITY,
        can_edit=_can(request, 'beds'), can_note=_can(request, 'beds', 'bedside', 'clinical'),
        siblings=Ward.objects.filter(active=True).exclude(pk=w.pk)))


@login_required
def ward_handover(request, pk):
    """Printable handover sheet: every bed with NEWS2, observations due, medicines late, allergies, and space to write."""
    authorize(request)
    w = get_object_or_404(_wards_qs(), pk=pk)
    snap = W.snapshot(w)
    audit(request, 'ward_handover_print', f'ward:{w.pk}')
    from .extlab import hospital
    since = timezone.now() - timezone.timedelta(hours=24)
    from django.db.models import Q
    notes = w.notes.select_related('author', 'patient').filter(Q(created_at__gte=since, kind__in=['handover', 'info']) | Q(kind='alert', resolved_at__isnull=True))
    return render(request, 'hospital/wards/handover_print.html', dict(snap, h=hospital(), size='a4', shift=current_shift(), notes=notes[:20]))


# ---------------------------------------------------------------- edit
def _time(v):
    try:
        hh, mm = (v or '').split(':')[:2]
        return time(int(hh), int(mm))
    except (ValueError, TypeError):
        return None


@login_required
def ward_edit(request, pk=None):
    authorize(request, 'beds')
    w = get_object_or_404(Ward, pk=pk) if pk else Ward()
    User = get_user_model()
    staff = User.objects.filter(is_active=True, hospital_staff__active=True).select_related('hospital_staff').order_by('first_name', 'username')
    nurses = [u for u in staff if u.hospital_staff.role in ('nurse', 'admin', 'management')]
    clinicians = [u for u in staff if u.hospital_staff.role in ('doctor', 'admin')]
    errors = {}
    if request.method == 'POST':
        P = request.POST
        name = P.get('name', '').strip()
        if not name:
            errors['name'] = 'Give the ward a name.'
        elif Ward.objects.filter(name__iexact=name).exclude(pk=w.pk).exists():
            errors['name'] = 'Another ward already has this name.'
        w.name = name[:120]
        w.code = P.get('code', '').strip().upper()[:10]
        w.kind = P.get('kind') if P.get('kind') in dict(Ward.KIND) else 'general'
        w.sex_policy = P.get('sex_policy') if P.get('sex_policy') in dict(Ward.SEX) else 'mixed'
        w.age_group = P.get('age_group') if P.get('age_group') in dict(Ward.AGE) else 'all'
        w.building, w.floor, w.phone = P.get('building', '').strip()[:80], P.get('floor', '').strip()[:40], P.get('phone', '').strip()[:40]
        w.nurse_in_charge = next((u for u in nurses if str(u.pk) == P.get('nurse_in_charge')), None)
        w.lead_clinician = next((u for u in clinicians if str(u.pk) == P.get('lead_clinician')), None)
        w.visiting_from, w.visiting_to = _time(P.get('visiting_from')), _time(P.get('visiting_to'))
        if bool(w.visiting_from) != bool(w.visiting_to):
            errors['visiting'] = 'Give both the start and the end of visiting hours, or neither.'
        w.visiting_note = P.get('visiting_note', '').strip()[:200]
        w.description = P.get('description', '').strip()[:3000]
        w.active = P.get('closed') != '1'
        try:
            add = max(0, min(60, int(P.get('add_beds') or 0)))
        except ValueError:
            add = 0
        if not errors:
            w.save()
            made = W.bulk_beds(w, add, P.get('bed_kind') if P.get('bed_kind') in dict(Bed._meta.get_field('kind').choices) else 'general',
                               P.get('bed_prefix', '').strip()) if add else []
            audit(request, 'ward_save', f'ward:{w.pk}', {'beds_added': len(made)})
            messages.success(request, f'{w.name} saved.' + (f' Added {len(made)} beds: {made[0].code} to {made[-1].code}.' if made else ''))
            return redirect('ward_detail', pk=w.pk)
    return render(request, 'hospital/wards/edit.html', {'w': w, 'errors': errors, 'nurses': nurses, 'clinicians': clinicians,
                                                        'bed_kinds': Bed._meta.get_field('kind').choices, 'is_new': not w.pk,
                                                        'colors': Ward.COLORS, 'icons': Ward.ICONS})


# ---------------------------------------------------------------- handover board
@login_required
@require_POST
def ward_note(request, pk):
    if not _can(request, 'beds', 'bedside', 'clinical'):
        raise PermissionDenied('Only ward staff can write on the handover board.')
    w = get_object_or_404(Ward, pk=pk)
    text = request.POST.get('text', '').strip()
    if not text:
        messages.error(request, 'Write the note first.')
        return redirect('ward_detail', pk=w.pk)
    kind = request.POST.get('kind') if request.POST.get('kind') in dict(WardNote.KIND) else 'handover'
    pt = Patient.objects.filter(admissions_on_ward(w), pk=request.POST.get('patient') or 0).distinct().first() if request.POST.get('patient') else None
    n = WardNote.objects.create(ward=w, kind=kind, text=text[:2000], patient=pt, author=request.user)
    audit(request, 'ward_note', f'ward:{w.pk}', {'note': n.pk, 'kind': kind})
    if kind == 'alert':
        from .notify import notify
        notify([w.nurse_in_charge, w.lead_clinician], f'Safety alert · {w.name}', text[:300], f'/wards/{w.pk}/', 'ward_alert', exclude=request.user)
    messages.success(request, 'Safety alert pinned to the top of the ward.' if kind == 'alert' else 'Added to the handover board.')
    return redirect(f'/wards/{w.pk}/#handover')


def admissions_on_ward(w):
    from django.db.models import Q
    return Q(encounters__admissions__bed__ward=w, encounters__admissions__discharged_at__isnull=True)


@login_required
@require_POST
def ward_note_resolve(request, pk, note_pk):
    if not _can(request, 'beds', 'bedside', 'clinical'):
        raise PermissionDenied
    n = get_object_or_404(WardNote, pk=note_pk, ward_id=pk, kind='alert', resolved_at__isnull=True)
    n.resolved_at, n.resolved_by = timezone.now(), request.user
    n.save(update_fields=['resolved_at', 'resolved_by', 'updated_at'])
    audit(request, 'ward_alert_resolved', f'ward:{pk}', {'note': n.pk})
    messages.success(request, 'Alert resolved.')
    return redirect(f'/wards/{pk}/#handover')
