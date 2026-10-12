"""Bedside equipment, bedside observations and the injury & burns assessment.

All saves are JSON: the page sends what the nurse or doctor entered, the server cleans it (hospital/bedside.py,
hospital/injury.py), stores it and answers with the cleaned values and the numbers derived from them. The page then
redraws its animation from the server's answer, so what is shown is always what was saved.
"""
import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from . import bedside as B
from . import injury as I
from .models import Admission, BedsideObservation, BedsideState, Encounter, InjuryAssessment
from .views import ROLES, audit, authorize

ROLES['bedside'] = {'nurse', 'doctor', 'admin'}


def _json(request):
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _bad(message, status=400):
    return JsonResponse({'ok': False, 'error': message}, status=status)


def encounter_weight(e):
    try:
        return float(str((e.vitals or {}).get('weight_kg', '')).strip() or 'x')
    except ValueError:
        return None


def encounter_vitals(e):
    """Encounter vitals ('120/80', '88' …) as numbers, for when no bedside observation exists yet."""
    v = e.vitals or {}

    def n(k):
        try:
            return float(str(v.get(k, '')).strip())
        except ValueError:
            return None
    sbp = dbp = None
    if '/' in str(v.get('bp', '')):
        a, _, b = str(v['bp']).partition('/')
        try:
            sbp, dbp = int(a), int(b)
        except ValueError:
            pass
    return {'heart_rate': n('heart_rate'), 'systolic': sbp, 'diastolic': dbp, 'resp_rate': n('resp_rate'),
            'spo2': n('spo2'), 'temperature_c': n('temperature_c'), 'consciousness': 'A', 'on_oxygen': False}


def latest_vitals(admission):
    obs = admission.observations.first() if admission else None
    if obs:
        return obs.as_dict(), obs
    return encounter_vitals(admission.encounter), None


def latest_injury(patient, encounter=None):
    qs = InjuryAssessment.objects.filter(patient=patient)
    if encounter is not None:
        qs = qs.filter(encounter=encounter)
    return qs.first()


def bedside_payload(admission):
    """Everything bedside.js needs to draw the bed scene for an admission."""
    e, p = admission.encounter, admission.encounter.patient
    try:
        state = admission.bedside
    except BedsideState.DoesNotExist:
        state = None
    devices = B.clean_devices(state.devices if state else {'monitor': {'on': True}, 'pulse_ox': {'on': True}, 'bp_cuff': {'on': True}})
    vitals, obs = latest_vitals(admission)
    inj = latest_injury(p)
    weight = encounter_weight(e) or (float(inj.weight_kg) if inj and inj.weight_kg else None)
    injury = None
    if inj:
        injury = {'data': inj.data, 'computed': I.compute(inj.data, age=p.age, weight_kg=weight, vitals=vitals),
                  'summary': I.summary(inj.computed, inj.data), 'url': f'/encounters/{inj.encounter_id}/injuries/'}
    return {
        'admission': admission.pk, 'devices': devices, 'derived': B.derive(devices, weight_kg=weight),
        'vitals': vitals, 'news2': B.news2(vitals), 'observed_at': obs.taken_at.isoformat() if obs else None,
        'patient': {'name': p.full_name, 'initials': p.initials, 'sex': p.sex, 'age': p.age, 'weight_kg': weight,
                    'allergies': [a.substance for a in p.allergies.filter(status='active')]},
        'injury': injury, 'catalogue': B.catalogue(),
        'urls': {'devices': f'/beds/admissions/{admission.pk}/bedside/', 'observations': f'/beds/admissions/{admission.pk}/observations/'},
        'history': [dict(o.as_dict(), at=o.taken_at.isoformat(), news2=o.news2) for o in admission.observations.all()[:12]],
    }


@login_required
@require_POST
def bedside_save(request, pk):
    authorize(request, 'bedside')
    data = _json(request)
    if data is None:
        return _bad('The data sent was not valid JSON.')
    with transaction.atomic():
        adm = get_object_or_404(Admission.objects.select_for_update().select_related('encounter__patient'), pk=pk)
        if adm.discharged_at:
            return _bad('This patient has been discharged; the bedside record is closed.', 409)
        devices = B.clean_devices(data.get('devices'))
        BedsideState.objects.update_or_create(admission=adm, defaults={'devices': devices, 'updated_by': request.user})
        audit(request, 'bedside_update', f'admission:{adm.pk}', {'on': sorted(k for k, v in devices.items() if v.get('on'))})
    payload = bedside_payload(adm)
    return JsonResponse({'ok': True, **payload})


@login_required
@require_POST
def observation_save(request, pk):
    authorize(request, 'bedside')
    data = _json(request)
    if data is None:
        return _bad('The data sent was not valid JSON.')
    adm = get_object_or_404(Admission.objects.select_related('encounter__patient'), pk=pk)
    if adm.discharged_at:
        return _bad('This patient has been discharged; the bedside record is closed.', 409)
    try:
        obs = B.clean_observation(data)
    except ValueError as exc:
        return _bad(str(exc))
    score = B.news2(obs)
    o = BedsideObservation.objects.create(admission=adm, recorded_by=request.user, news2=score['total'] if score else None, **obs)
    audit(request, 'observations', f'admission:{adm.pk}', {'news2': o.news2})
    return JsonResponse({'ok': True, **bedside_payload(adm)})


@login_required
def injury_assessment(request, pk):
    """GET: the interactive body figure and form. POST (JSON): save a new version of the assessment."""
    authorize(request, 'clinical')
    e = get_object_or_404(Encounter.objects.select_related('patient'), pk=pk)
    p = e.patient
    adm = e.admissions.filter(discharged_at__isnull=True).first()
    vitals = latest_vitals(adm)[0] if adm else encounter_vitals(e)
    if request.method == 'POST':
        data = _json(request)
        if data is None:
            return _bad('The data sent was not valid JSON.')
        clean = I.clean_assessment(data.get('assessment'))
        weight = I._num(data.get('weight_kg'), 1, 400, None, 1)
        computed = I.compute(clean, age=p.age, weight_kg=weight, vitals=vitals)
        a = InjuryAssessment.objects.create(encounter=e, patient=p, data=clean, computed=computed, weight_kg=weight,
                                            assessed_by=request.user)
        audit(request, 'injury_assessment', f'encounter:{e.pk}', {'assessment': a.pk, 'tbsa': computed['tbsa']})
        return JsonResponse({'ok': True, 'id': a.pk, 'assessment': clean, 'computed': computed, 'weight_kg': weight,
                             'summary': I.summary(computed, clean), 'saved_at': a.created_at.isoformat()})
    current = latest_injury(p, e)
    weight = float(current.weight_kg) if current and current.weight_kg else encounter_weight(e)
    history = InjuryAssessment.objects.filter(encounter=e).select_related('assessed_by')[:20]
    return render(request, 'hospital/injury.html', {
        'e': e, 'p': p, 'adm': adm, 'history': history, 'current': current,
        'boot': {'assessment': current.data if current else I.clean_assessment({}), 'weight_kg': weight, 'age': p.age,
                 'sex': p.sex, 'vitals': vitals, 'catalogue': I.catalogue(), 'save_url': request.path,
                 'bed_url': f'/beds/{adm.bed_id}/' if adm else None,
                 'bedside': {'devices': bedside_payload(adm)['devices']} if adm else None,
                 'bedside_url': f'/beds/admissions/{adm.pk}/bedside/' if adm else None},
    })
