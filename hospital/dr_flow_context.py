"""What Dr. Flow may know from the pharmacy and the bedside, with no personal data.

Used by every Dr. Flow surface: lab next steps and report helpers (through clinical.deidentified_context) and the
imaging analysis and questions (imaging_ai.image_context).

Shared (minimum necessary, all de-identified):
  pharmacy
    * this patient's medicines from the last CLINICAL_AI_MEDICINE_DAYS days: generic name, strength, form, dose,
      route, frequency, duration, the day it was prescribed counted from this visit, whether it was signed or
      dispensed, and whether the pharmacy had it;
    * for inpatients, the doses given, refused, held or missed in the last 48 hours (counts, hours since last dose);
    * whether an allergy warning was overridden (yes/no only, never the reason text);
    * the hospital formulary: each active medicine with in stock / low / out of stock at the dispensing pharmacy,
      so Dr. Flow suggests what the patient can actually get here.
  bedside
    * whether the patient is admitted, the type of bed (general, ICU, maternity, paediatric, isolation) and the
      number of days since admission;
    * the devices at the bed (oxygen, IV fluid and rate, urinary catheter, NG tube, chest drain, collar, traction,
      head-of-bed angle) and the warnings computed from them;
    * observations of the last 24 hours (heart rate, blood pressure, breathing rate, SpO2, temperature,
      consciousness, oxygen, NEWS2) counted in hours ago.

Never shared: names, record numbers, phone numbers, addresses, dates of birth, real dates or times, ward names, bed
codes, staff names (prescriber, pharmacist, nurse), batch numbers, suppliers, prices, stock quantities, and free-text
notes (pharmacist notes, allergy override reasons, availability notes, nursing notes, discharge notes). Short
medicine instructions such as "after food" are kept, with the patient's names and numbers removed.

Switch either part off with CLINICAL_AI_SHARE_PHARMACY=False or CLINICAL_AI_SHARE_BEDSIDE=False.
"""
import re
from datetime import timedelta

from django.conf import settings
from django.db.models import Q, Sum
from django.utils import timezone


# ------------------------------------------------------------------ free text
def scrub(text, patient, limit=1500):
    """Remove the patient's names, record number and phone from free text before it leaves the server."""
    t = str(text or '')[:limit]
    if not t or patient is None:
        return t
    tokens = {patient.mrn, patient.phone, patient.first_name, patient.last_name, f'{patient.first_name} {patient.last_name}'}
    tokens |= set((patient.first_name or '').split()) | set((patient.last_name or '').split())
    for tok in sorted({x.strip() for x in tokens if x and len(x.strip()) >= 2}, key=len, reverse=True):
        t = re.sub(rf'(?i)(?<![\w]){re.escape(tok)}(?![\w])', '[patient]', t)
    digits = re.sub(r'\D', '', patient.phone or '')
    if len(digits) >= 6:
        t = t.replace(digits, '[phone]')
    t = re.sub(r'\+\d[\d\s-]{6,}\d|\b\d{7,}\b', '[number]', t)   # other phone-like numbers (not doses like 2 400 000 IU)
    t = re.sub(r'\bMF-[0-9A-F]{6,}\b', '[record]', t)              # any record number, not only this patient's
    return t


def _on(name):
    return bool(getattr(settings, name, True))


def _hours_ago(dt, now):
    return round((now - dt).total_seconds() / 3600, 1) if dt else None


# ------------------------------------------------------------------ pharmacy
def stock_status():
    """{medication_id: 'in stock' | 'low' | 'out of stock'} at the dispensing pharmacy, usable batches only."""
    from .models import Medication, StockBatch, StockLocation
    loc = StockLocation.dispensing()
    qty = dict(StockBatch.objects.filter(store=loc, expiry__gte=timezone.localdate(), quarantined=False)
               .values('medication_id').annotate(q=Sum('quantity')).values_list('medication_id', 'q'))
    out = {}
    for m_id, reorder in Medication.objects.filter(active=True).values_list('id', 'reorder_level'):
        q = qty.get(m_id) or 0
        out[m_id] = 'out of stock' if q <= 0 else 'low' if q <= (reorder or 0) else 'in stock'
    return out


def _med_name(m):
    base = m.generic_name or m.name
    return ' '.join(x for x in (base, m.strength, (m.form or '').lower()) if x).strip()


def formulary(status=None):
    """The hospital's active medicines grouped by category, each with its stock status. Names only."""
    from .models import Medication
    status = status if status is not None else stock_status()
    limit = int(getattr(settings, 'CLINICAL_AI_FORMULARY_LIMIT', 300))
    groups = {}
    for m in Medication.objects.filter(active=True).order_by('category', 'name')[:limit]:
        groups.setdefault(m.get_category_display(), []).append(
            f"{_med_name(m)} ({status.get(m.id, 'out of stock')}{', essential' if m.essential else ''}{', controlled' if m.controlled else ''})")
    return groups


def pharmacy_context(encounter, now=None):
    if not _on('CLINICAL_AI_SHARE_PHARMACY'):
        return None
    from .models import MedicationAdministration, PrescriptionItem
    now = now or timezone.now()
    p, start = encounter.patient, encounter.created_at
    days = int(getattr(settings, 'CLINICAL_AI_MEDICINE_DAYS', 90))
    status = stock_status()
    items = (PrescriptionItem.objects.filter(prescription__encounter__patient=p, prescription__created_at__gte=now - timedelta(days=days))
             .exclude(prescription__state='cancelled').select_related('medication', 'prescription')
             .prefetch_related('dispenses').order_by('-prescription__created_at', 'sort_order')[:40])
    since = now - timedelta(hours=48)
    meds = []
    for i in items:
        rx = i.prescription
        given = list(MedicationAdministration.objects.filter(item=i, scheduled_for__gte=since).values_list('status', 'given_at'))
        counts = {}
        for st, _ in given:
            counts[st] = counts.get(st, 0) + 1
        last = max((g for st, g in given if st == 'given'), default=None)
        meds.append({
            'medicine': _med_name(i.medication), 'category': i.medication.get_category_display(),
            'dose': scrub(i.dose, p, 60) or None, 'units_per_dose': float(i.units_per_dose or 1), 'route': i.get_route_display(),
            'frequency': i.get_frequency_display(), 'duration_days': i.duration_days,
            'instructions': scrub(i.instructions, p, 160) or None,
            'prescribed_day': (rx.created_at - start).days, 'this_visit': rx.encounter_id == encounter.id,
            'state': rx.get_state_display(), 'dispensed': 'fully' if i.is_dispensed else 'partly' if i.dispensed_quantity else 'not yet',
            'availability_at_prescribing': i.get_availability_display() if i.availability else 'Normal',
            'pharmacy_stock_now': status.get(i.medication_id, 'out of stock'),
            'allergy_warning_overridden': bool(rx.override_reason),
            'doses_last_48h': counts or None, 'hours_since_last_dose_given': _hours_ago(last, now),
        })
    return {
        'note': 'Medicines from the hospital pharmacy record. Stock status is for the dispensing pharmacy now. '
                'Doses are not to be invented: refer to the guideline and check allergies.',
        'allergies': [{'substance': a.substance, 'severity': a.severity} for a in p.allergies.filter(status='active')],
        'current_and_recent_medicines': meds,
        'hospital_formulary': formulary(status),
    }


# ------------------------------------------------------------------ bedside
def _devices_summary(dev):
    """Only the devices that are on, without free-text notes."""
    out = {}
    if dev['oxygen']['on']:
        out['oxygen'] = {k: dev['oxygen'][k] for k in ('device', 'flow_l_min', 'fio2')}
    if dev['iv']['on']:
        out['iv_fluid'] = {k: dev['iv'][k] for k in ('fluid', 'rate_ml_h', 'remaining_ml', 'site', 'pump')}
    for k in ('catheter', 'ng_tube', 'chest_drain', 'traction'):
        if dev[k]['on']:
            out[k] = {kk: vv for kk, vv in dev[k].items() if kk != 'on'}
    if dev['collar']['on']:
        out['cervical_collar'] = True
    out['head_of_bed_degrees'] = dev['bed']['head_deg']
    return out


def _news2(o):
    """The stored NEWS2, or worked out from the readings when the observation was saved some other way."""
    if o.news2 is not None:
        return o.news2
    try:
        from . import bedside as B
        return B.news2(o.as_dict()).get('total')
    except Exception:
        return None


def bedside_context(encounter, now=None):
    if not _on('CLINICAL_AI_SHARE_BEDSIDE'):
        return None
    from .models import Admission
    now = now or timezone.now()
    p = encounter.patient
    adm = (Admission.objects.filter(Q(encounter=encounter) | Q(encounter__patient=p), discharged_at__isnull=True)
           .select_related('bed').order_by('-admitted_at').first())
    if not adm:
        last = Admission.objects.filter(encounter__patient=p).exclude(discharged_at=None).order_by('-discharged_at').first()
        return {'admitted': False,
                'last_discharged_days_ago': (now - last.discharged_at).days if last else None}
    ctx = {'admitted': True, 'bed_type': adm.bed.get_kind_display(), 'days_since_admission': (now - adm.admitted_at).days}
    try:
        from . import bedside as B
        state = getattr(adm, 'bedside', None)
        if state is not None:
            dev = B.clean_devices(state.devices)
            weight = (encounter.vitals or {}).get('weight_kg') if isinstance(encounter.vitals, dict) else None
            ctx['devices'] = _devices_summary(dev)
            ctx['device_warnings'] = B.derive(dev, weight_kg=weight)['warnings']
    except Exception:                                  # a broken device record must never block the AI answer
        ctx['devices'] = None
    obs = list(adm.observations.filter(taken_at__gte=now - timedelta(hours=24)).order_by('-taken_at')[:12])
    ctx['observations_last_24h'] = [{
        'hours_ago': _hours_ago(o.taken_at, now), 'heart_rate': o.heart_rate,
        'bp': f'{o.systolic}/{o.diastolic}' if o.systolic and o.diastolic else o.systolic,
        'resp_rate': o.resp_rate, 'spo2': o.spo2, 'temperature_c': float(o.temperature_c) if o.temperature_c is not None else None,
        'consciousness': o.get_consciousness_display(), 'on_oxygen': o.on_oxygen, 'news2': _news2(o),
    } for o in obs]
    return ctx


def care_context(encounter):
    """Both parts, as added to every Dr. Flow context. Keys are left out when switched off."""
    out = {}
    ph, bd = pharmacy_context(encounter), bedside_context(encounter)
    if ph is not None:
        out['pharmacy'] = ph
    if bd is not None:
        out['bedside'] = bd
    return out
