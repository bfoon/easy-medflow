"""Ambulance service pages.

/ambulance/                     dispatch board: live map, calls waiting, the fleet, patients arriving
/ambulance/calls/new/           service desk: guided call taking (complaint → questions → priority → place on map)
/ambulance/calls/<pk>/          one call: journey, best ambulance to send, destination, care on board, handover, timeline
/ambulance/crew/                crew screen (phone-first): directions, preparation checklist, vital signs, handover
/ambulance/fleet/               vehicles, readiness checks, crews on shift, paired phone-app devices
/ambulance/fleet/new/           register a new ambulance (…/fleet/<pk>/edit/ corrects or retires one)
/ambulance/insights/            response times, busiest hours, what people call about
/ambulance/api/                 API guide for the phone apps (+ /api/ems/v1/openapi.json)
/e/<token>/                     public tracking page for the caller (no sign-in)
"""
import io
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Prefetch

from . import ambulance as A
from .forms import AmbulanceForm
from .maps import tile_layers
from .models import Location, NetworkFacility
from .models_ambulance import Ambulance, ApiDevice, CrewShift, EmergencyCall, EmsStation
from .views import audit, authorize


def _can(request, cap):
    from .access import has
    return request.user.is_superuser or has(request.user, cap)


def _ctx(request, **kw):
    return dict(kw, can_dispatch=_can(request, 'ambulance_dispatch'), can_crew=_can(request, 'ambulance_crew'),
                can_fleet=_can(request, 'ambulance_fleet'), tiles=tile_layers(), router=getattr(settings, 'EMS_ROUTER_URL', ''))


def _wants_json(request):
    return request.headers.get('X-Requested-With') == 'fetch' or 'application/json' in request.headers.get('Accept', '')


# ------------------------------------------------------------------ board
@login_required
def board(request):
    authorize(request, 'ambulance')
    return render(request, 'hospital/ambulance/board.html', _ctx(request, payload=A.board_payload(), sim=A.simulation_enabled(),
                                                                  priorities=[(p, A.PRIORITY_WORD[p], A.PRIORITY_COLOR[p], A.TARGET_MIN[p]) for p in (1, 2, 3, 4)]))


# ------------------------------------------------------------------ service desk: new call
def _places():
    return [{'id': l.pk, 'name': str(l), 'lat': float(l.latitude), 'lon': float(l.longitude)}
            for l in Location.objects.filter(active=True).select_related('parent').order_by('name')]


@login_required
def call_new(request):
    authorize(request, 'ambulance_dispatch')
    if request.method == 'POST':
        P = request.POST
        data = {k: P.get(k, '') for k in ('complaint', 'caller_name', 'caller_phone', 'caller_relation', 'patient', 'patient_name', 'patient_age',
                                           'patient_sex', 'patients_count', 'landmark', 'description', 'latitude', 'longitude', 'location', 'priority')}
        data['answers'] = {k[2:]: v for k, v in P.items() if k.startswith('q_') and v in ('yes', 'no')}
        source = P.get('source') if P.get('source') in dict(EmergencyCall.SOURCE) else 'phone'
        try:
            call = A.create_call(data, by=request.user, source=source)
        except A.Refused as e:
            messages.error(request, str(e))
        else:
            audit(request, 'ems_call_new', f'ems:{call.pk}', {'priority': call.priority, 'complaint': call.complaint})
            messages.success(request, f'{call.reference} saved as {call.get_priority_display()}. Choose the ambulance to send.')
            return redirect('ems_call', pk=call.pk)
    return render(request, 'hospital/ambulance/call_new.html', _ctx(
        request, rules=[{'key': c['key'], 'label': c['label'], 'icon': c['icon'], 'base': c['base'], 'first_aid': c['first_aid'],
                         'questions': [{'key': q[0], 'text': q[1], 'trigger': q[2], 'p': q[3], 'why': q[4]} for q in A.questions_for(c['key'])]}
                        for c in A.COMPLAINTS],
        complaints=A.COMPLAINTS, places=_places(), home=A.home(), sources=[s for s in EmergencyCall.SOURCE if s[0] != 'app'],
        pmeta={'colors': A.PRIORITY_COLOR, 'words': A.PRIORITY_WORD, 'targets': A.TARGET_MIN},
        prefill={'caller_phone': request.GET.get('phone', ''), 'complaint': request.GET.get('complaint', '')}))


@login_required
def caller_lookup(request):
    """Patients matching the caller's number, for the call taker (JSON)."""
    authorize(request, 'ambulance_dispatch')
    phone = request.GET.get('phone', '')
    res = A.lookup_caller(phone)
    if res:
        audit(request, 'ems_caller_lookup', 'patients', {'matches': len(res)})
    return JsonResponse({'results': res})


# ------------------------------------------------------------------ one call
@login_required
def call_detail(request, pk):
    authorize(request, 'ambulance')
    call = get_object_or_404(EmergencyCall.objects.select_related('ambulance', 'ambulance__station', 'destination', 'patient', 'location', 'taken_by',
                                                                   'dispatched_by', 'encounter'), pk=pk)
    audit(request, 'ems_call_view', f'ems:{call.pk}')
    journey = []
    for field, label in A.JOURNEY:
        t = getattr(call, field)
        journey.append({'label': label, 'at': t, 'done': bool(t)})
    if call.status == 'cancelled':
        journey = [j for j in journey if j['done'] and j['label'] != 'Closed'] + [{'label': 'Cancelled', 'at': call.closed_at, 'done': True, 'cancel': True}]
    done = [j for j in journey if j['done']]
    if done and call.is_open:
        done[-1]['now'] = True
    recs = A.recommend(call) if call.status in ('new', 'waiting') else []
    dests = A.destinations(call)
    obs = list(call.observations.all())
    track = request.build_absolute_uri(reverse('ems_track', args=[call.token]))
    c = A.complaint(call.complaint)
    return render(request, 'hospital/ambulance/call.html', _ctx(
        request, call=call, c=c, journey=journey, recs=recs, dests=dests, dest=A.destination_point(call), obs=[(o, A.obs_flags(o), A.obs_line(o)) for o in obs],
        events=list(call.events.select_related('by')), prep=A.prep_for(call) if call.status not in ('new', 'waiting') else None, atmist=A.atmist(call),
        atmist_labels=A.ATMIST_LABELS, answers=[(q[1], call.answers.get(q[0]), call.answers.get(q[0]) == q[2]) for q in A.questions_for(call.complaint) if call.answers.get(q[0])],
        track=track, color=A.PRIORITY_COLOR[call.priority], target=A.TARGET_MIN[call.priority], outcomes=[o for o in EmergencyCall.OUTCOME if o[0] in ('treated', 'refused', 'deceased', 'no_patient')],
        next=A.CREW_NEXT.get(call.status), obs_fields=OBS_FIELDS,
        geo={'call': A.call_json(call, detail=True), 'unit': A.unit_json(call.ambulance) if call.ambulance_id else None, 'home': A.home(),
             'trail': [[p.latitude, p.longitude] for p in call.pings.order_by('at')[:2000]]}))


OBS_FIELDS = [('heart_rate', 'HR'), ('systolic', 'Systolic'), ('diastolic', 'Diastolic'), ('resp_rate', 'Resp rate'), ('spo2', 'SpO₂ %'),
              ('temperature_c', 'Temp °C'), ('glucose_mmol', 'Glucose'), ('gcs', 'GCS')]


DISPATCH_ACTIONS = {'verify', 'dispatch', 'cancel', 'locate', 'destination', 'priority'}
CREW_ACTIONS = {'advance', 'obs', 'treatment', 'prep', 'handover'}


@login_required
@require_POST
def call_action(request, pk, action):
    call = get_object_or_404(EmergencyCall, pk=pk)
    if action in DISPATCH_ACTIONS:
        authorize(request, 'ambulance_dispatch')
    elif action in CREW_ACTIONS or action == 'note':
        if not (_can(request, 'ambulance_crew') or _can(request, 'ambulance_dispatch')):
            raise PermissionDenied('Your access does not include this.')
    else:
        raise Http404
    P, u = request.POST, request.user
    msg = ''
    try:
        if action == 'verify':
            A.verify(call, u, P.get('note', '').strip()[:200])
            msg = 'Confirmed. Now send an ambulance.'
        elif action == 'dispatch':
            amb = get_object_or_404(Ambulance, pk=P.get('ambulance') or 0)
            dest = NetworkFacility.objects.filter(pk=P.get('destination')).first() if (P.get('destination') or '').isdigit() else None
            A.dispatch(call, amb, u, destination=dest)
            msg = f'{amb.call_sign} is on its way.'
        elif action == 'cancel':
            A.cancel(call, u, P.get('reason', ''))
            msg = 'Call cancelled.'
        elif action == 'locate':
            lat, lon = A._float(P.get('latitude')), A._float(P.get('longitude'))
            if lat is None or lon is None:
                raise A.Refused('Pick the place on the map.')
            if call.status not in ('new', 'waiting', 'dispatched', 'en_route'):
                raise A.Refused('The crew is already with the patient.')
            call.latitude, call.longitude = lat, lon
            if P.get('landmark') is not None:
                call.landmark = P.get('landmark', '').strip()[:200]
            call.save(update_fields=['latitude', 'longitude', 'landmark', 'updated_at'])
            A.log(call, 'Location corrected by the service desk', 'note', u)
            msg = 'Location saved.'
        elif action == 'destination':
            dest = NetworkFacility.objects.filter(pk=P.get('destination')).first() if (P.get('destination') or '').isdigit() else None
            if call.status in ('at_hospital', 'closed', 'cancelled'):
                raise A.Refused('Too late to change where the patient goes.')
            call.destination = dest
            call.save(update_fields=['destination', 'updated_at'])
            A.log(call, f'Destination: {A.destination_point(call)["name"]}', 'note', u)
            msg = 'Destination changed.'
        elif action == 'priority':
            p = int(P.get('priority') or 0)
            if p not in (1, 2, 3, 4):
                raise A.Refused('Choose P1 to P4.')
            if p != call.priority:
                old = call.priority
                call.priority = p
                call.save(update_fields=['priority', 'updated_at'])
                A.log(call, f'Priority changed P{old} → P{p}' + (f': {P.get("reason").strip()[:150]}' if P.get('reason') else ''), 'status', u)
            msg = 'Priority saved.'
        elif action == 'advance':
            A.advance(call, P.get('to', ''), u, outcome=P.get('outcome', ''), note=P.get('note', '').strip()[:200])
            call.refresh_from_db()
            msg = call.get_status_display()
        elif action in ('note', 'treatment'):
            text = P.get('text', '').strip()
            if not text:
                raise A.Refused('Write something first.')
            A.log(call, text[:300], 'treatment' if action == 'treatment' else 'note', u)
            msg = 'Added to the timeline.'
        elif action == 'obs':
            A.record_observation(call, P, u)
            msg = 'Vital signs recorded.'
        elif action == 'prep':
            A.toggle_prep(call, P.get('key', ''), P.get('done') in ('1', 'true', 'on'), u)
            msg = 'Checklist updated.'
        elif action == 'handover':
            enc = A.handover(call, P, u, register=P.get('register') == '1')
            msg = f'Handed over. {call.patient.full_name if enc else "Call closed"}' + (' is in the emergency queue.' if enc else '.')
        audit(request, f'ems_{action}', f'ems:{call.pk}')
    except A.Refused as e:
        if _wants_json(request):
            return JsonResponse({'ok': False, 'error': str(e)}, status=409)
        messages.error(request, str(e))
    else:
        if _wants_json(request):
            call.refresh_from_db()
            return JsonResponse({'ok': True, 'message': msg, 'status': call.status, 'prep': A.prep_for(call) if action == 'prep' else None})
        messages.success(request, msg)
    nxt = P.get('next', '')
    return redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else reverse('ems_call', args=[call.pk]))


# ------------------------------------------------------------------ crew screen
@login_required
def crew(request):
    authorize(request, 'ambulance_crew')
    shift = A.my_shift(request.user)
    amb = shift.ambulance if shift else None
    unit_param = request.GET.get('unit')
    if unit_param and unit_param.isdigit() and (_can(request, 'ambulance_fleet') or request.user.is_superuser):
        amb = get_object_or_404(Ambulance, pk=unit_param)
    if not amb:
        units = Ambulance.objects.filter(active=True).select_related('station').prefetch_related('shifts__user')
        return render(request, 'hospital/ambulance/crew_start.html', _ctx(request, units=units, roles=CrewShift.ROLE))
    from .ambulance_api import crew_job
    return render(request, 'hospital/ambulance/crew.html', _ctx(
        request, amb=amb, shift=shift, job=crew_job(amb), unit_param=amb.pk if unit_param else '',
        sim=A.simulation_enabled(), readiness=A.readiness(amb), checks=A.READINESS))


@login_required
@require_POST
def crew_shift(request):
    authorize(request, 'ambulance_crew')
    if request.POST.get('end') == '1':
        A.end_shift(request.user)
        messages.success(request, 'Shift ended. Thank you.')
        return redirect('ems_crew')
    amb = get_object_or_404(Ambulance, pk=request.POST.get('ambulance') or 0, active=True)
    try:
        s = A.start_shift(request.user, amb, request.POST.get('role', ''))
    except A.Refused as e:
        messages.error(request, str(e))
    else:
        audit(request, 'ems_shift_start', f'ambulance:{amb.pk}', {'role': s.role})
        messages.success(request, f'You are on {amb.call_sign} as {s.get_role_display().lower()}.')
    return redirect('ems_crew')


# ------------------------------------------------------------------ fleet
@login_required
def fleet(request):
    authorize(request, 'ambulance')
    units = list(Ambulance.objects.filter(active=True).select_related('station', 'checked_by').prefetch_related('shifts__user').order_by('station__name', 'call_sign'))
    retired = Ambulance.objects.filter(active=False).select_related('station').order_by('call_sign')
    cards = []
    for a in units:
        score, why = A.readiness(a)
        cards.append({'a': a, 'score': score, 'why': why, 'color': A.STATUS_COLOR.get(a.status), 'icon': A.LEVEL_ICON.get(a.level, 'bi-truck-front'),
                      'call': a.current_call, 'checked_today': bool(a.checked_at and timezone.localtime(a.checked_at).date() == timezone.localdate())})
    devices = ApiDevice.objects.select_related('user').filter(revoked_at__isnull=True)[:40] if _can(request, 'ambulance_fleet') else []
    U = get_user_model()
    crew_users = U.objects.filter(is_active=True, hospital_staff__active=True, hospital_staff__role__in=['paramedic', 'driver', 'nurse', 'doctor', 'dispatcher']).order_by('first_name')
    return render(request, 'hospital/ambulance/fleet.html', _ctx(
        request, cards=cards, retired=retired, checks=A.READINESS, devices=devices,
        stations=EmsStation.objects.filter(active=True).prefetch_related(Prefetch('ambulances', queryset=Ambulance.objects.filter(active=True))),
        crew_users=crew_users, on_shift=CrewShift.objects.filter(ended_at__isnull=True).select_related('user', 'ambulance')))


def _vehicle_form(request, amb=None):
    authorize(request, 'ambulance_fleet')
    name = amb.call_sign if amb else ''    # the form writes typed values onto the instance; keep the real name for the heading
    if request.method != 'POST':
        form = AmbulanceForm(instance=amb)
    else:
        with transaction.atomic():
            if amb is not None:     # lock the vehicle so a dispatch or crew change can't slip in while it is checked and saved
                amb = Ambulance.objects.select_for_update().get(pk=amb.pk)
            form = AmbulanceForm(request.POST, instance=amb)
            saved = form.save() if form.is_valid() else None
        if saved is not None:
            if amb is None:
                audit(request, 'ems_fleet_register', f'ambulance:{saved.pk}', {'call_sign': saved.call_sign, 'level': saved.level})
                messages.success(request, f'{saved.call_sign} is registered. Run the vehicle check and put a crew on board to make it ready for calls.')
            else:
                audit(request, 'ems_fleet_edit', f'ambulance:{saved.pk}', {'changed': form.changed_data})
                messages.success(request, f'{saved.call_sign} saved.' if saved.active else f'{saved.call_sign} has been retired from the fleet.')
            return redirect('ems_fleet')
    title = f'Edit {name}' if amb else 'Register an ambulance'
    subtitle = ('Correct the vehicle’s details. Its status, fuel, oxygen and readiness are updated from the fleet page and the crew app.' if amb else
                'Add a vehicle to the fleet. Once it is checked and has a crew on board, dispatchers can send it to calls.')
    return render(request, 'hospital/form.html', _ctx(request, form=form, title=title, subtitle=subtitle))


@login_required
def fleet_new(request):
    return _vehicle_form(request)


@login_required
def fleet_edit(request, pk):
    return _vehicle_form(request, get_object_or_404(Ambulance, pk=pk))


@login_required
@require_POST
def fleet_action(request, pk, action):
    authorize(request, 'ambulance_fleet' if action == 'status' else 'ambulance')
    amb = get_object_or_404(Ambulance, pk=pk)
    try:
        if action == 'check':
            if not (_can(request, 'ambulance_crew') or _can(request, 'ambulance_fleet')):
                raise PermissionDenied
            A.save_check(amb, {k: request.POST.get(f'c_{k}') for k, _ in A.READINESS}, request.user, request.POST.get('fuel'), request.POST.get('oxygen'),
                         request.POST.get('notes', '').strip())
            messages.success(request, f'{amb.call_sign} checked. Readiness {A.readiness(amb)[0]}%.')
        elif action == 'status':
            A.set_unit_status(amb, request.POST.get('status', ''), request.user)
            messages.success(request, f'{amb.call_sign}: {amb.get_status_display()}.')
        elif action == 'available':
            if not (_can(request, 'ambulance_crew') or _can(request, 'ambulance_fleet')):
                raise PermissionDenied
            A.back_in_service(amb, request.user)
            messages.success(request, f'{amb.call_sign} is available.')
        else:
            raise Http404
        audit(request, f'ems_fleet_{action}', f'ambulance:{amb.pk}')
    except A.Refused as e:
        messages.error(request, str(e))
    nxt = request.POST.get('next', '')
    return redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else 'ems_fleet')


@login_required
@require_POST
def device_new(request):
    """Pair a phone with the crew API: a token shown once, with a QR code the app can scan."""
    authorize(request, 'ambulance_crew' if not request.POST.get('user') else 'ambulance_fleet')
    U = get_user_model()
    user = request.user
    if request.POST.get('user') and request.POST['user'] != str(request.user.pk):
        user = get_object_or_404(U, pk=request.POST['user'], is_active=True)
    dev, raw = ApiDevice.issue(user, request.POST.get('name', '').strip() or f'{user.first_name or user.username}’s phone', created_by=request.user)
    audit(request, 'ems_device_pair', f'device:{dev.pk}', {'for': user.pk})
    server = request.build_absolute_uri(reverse('ems_api_meta').rsplit('meta/', 1)[0])
    payload = json.dumps({'server': server, 'token': raw})
    svg = ''
    try:
        import segno
        buf = io.BytesIO()
        segno.make(payload, error='m').save(buf, kind='svg', scale=5, dark='#0F2C3F', border=2, xmldecl=False, svgns=True)
        svg = buf.getvalue().decode()
    except Exception:       # QR is a convenience; the token is shown as text too
        svg = ''
    return render(request, 'hospital/ambulance/device.html', _ctx(request, dev=dev, raw=raw, server=server, svg=svg, for_user=user))


@login_required
@require_POST
def device_revoke(request, pk):
    dev = get_object_or_404(ApiDevice, pk=pk)
    if dev.user_id != request.user.pk:
        authorize(request, 'ambulance_fleet')
    dev.revoked_at = timezone.now()
    dev.save(update_fields=['revoked_at', 'updated_at'])
    audit(request, 'ems_device_revoke', f'device:{dev.pk}')
    messages.success(request, f'{dev.name} can no longer use the ambulance API.')
    return redirect('ems_fleet')


# ------------------------------------------------------------------ insights, API guide
@login_required
def insights(request):
    authorize(request, 'ambulance')
    try:
        days = max(7, min(180, int(request.GET.get('days', 30))))
    except ValueError:
        days = 30
    return render(request, 'hospital/ambulance/insights.html', _ctx(request, s=A.insights(days), days=days, day_options=[7, 30, 90]))


@login_required
def api_docs(request):
    authorize(request, 'ambulance')
    from django.urls import resolve
    from .ambulance_api import ROUTES
    prefix = reverse('ems_api_meta').rsplit('meta/', 1)[0]
    base = request.build_absolute_uri(prefix)
    rows = []
    for path, name, tag, summary, auth in ROUTES:
        fn = resolve(prefix.rstrip('/') + path.replace('{token}', 'x').replace('{id}', '1')).func
        rows.append({'path': path, 'tag': tag, 'summary': summary, 'auth': auth, 'methods': getattr(fn, 'ems_methods', ('POST',))})
    sample = {'complaint': 'chest_pain', 'answers': {'u_awake': 'yes', 'u_breathing': 'yes', 'c_spread': 'yes'}, 'caller_name': 'Awa Ceesay',
              'caller_phone': '+220 770 1234', 'patient_age': 58, 'patient_sex': 'M', 'latitude': 13.4383, 'longitude': -16.6781, 'accuracy_m': 12,
              'landmark': 'Behind Westfield mosque, green gate'}
    return render(request, 'hospital/ambulance/api.html', _ctx(request, routes=rows, base=base, sample=json.dumps(sample, indent=2, ensure_ascii=False),
                                                                  needs_key=bool([k for k in getattr(settings, 'EMS_APP_KEYS', []) if k])))


# ------------------------------------------------------------------ public tracking (no sign-in)
def track(request, token):
    call = EmergencyCall.objects.select_related('ambulance', 'destination').filter(token=token).first()
    if not call:
        raise Http404
    return render(request, 'hospital/ambulance/track.html', {'call': call, 'status': A.public_status(call), 'tiles': tile_layers(),
                                                               'hospital': getattr(settings, 'HOSPITAL_NAME', 'E-MedFlow'),
                                                               'hospital_phone': getattr(settings, 'HOSPITAL_PHONE', ''),
                                                               'color': A.PRIORITY_COLOR[call.priority]})
