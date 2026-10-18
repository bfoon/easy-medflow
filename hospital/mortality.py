"""Mortality: what happens when a patient dies, and how the hospital learns from it.

Recording a death **archives** the patient. In one transaction:

* open visits are completed with the outcome "Died", a current admission ends and the bed goes for terminal cleaning;
* waiting queue tickets, uncollected lab tests, unreported imaging, undispensed prescriptions and planned operations
  are cancelled;
* care-programme enrolments end as "Died", planned programme visits are cancelled and unsent reminders are stopped,
  so the family never receives an appointment SMS for someone who has died;
* the patient leaves every active list (patients, search, check-in, new visits) and appears in the archive instead.

Nothing in the medical record is deleted: every visit, result, image and note stays, and remains readable by the
people allowed to read it. Each change is written to ``DeathRecord.archive_log`` so that a death recorded in error
can be undone exactly (programme enrolments, visits and reminders are restored; cancelled clinical orders are not
re-activated automatically because they may no longer be appropriate — the team re-orders what is still needed).

Learning: the certificate follows the WHO medical certificate of cause of death (MCCD); an autopsy adds the
pathological cause and a clinicopathological correlation (Goldman class); the M&M review asks whether the death was
preventable (three-delays model). Together they become an anonymised **study case** in the clinical library.
"""
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

MODE_OF_DYING = re.compile(r'^\s*(cardiac|cardio-?respiratory|cardiopulmonary|respiratory|heart)\s+(arrest|failure|standstill)\s*$|^\s*(asystole|brain death|old age|senility)\s*$', re.I)
CORE_CHECKS = ('no_pulse', 'no_breath', 'five_minutes')
OPEN_AUTOPSY = ('requested', 'consented', 'scheduled', 'in_progress', 'preliminary')
STUDY_CHECKS = [
    ('names', 'No names of the patient, family or staff appear anywhere in the case'),
    ('numbers', 'No record numbers, phone numbers, addresses or exact dates'),
    ('rare', 'The case is not so rare or publicised that a reader could recognise the person'),
    ('images', 'Nothing in the text describes tattoos, scars or features that identify the person'),
]


def _now():
    return timezone.now()


def _notify(users, title, body, url, kind='mortality', exclude=None):
    from .models import Notification
    seen = set()
    for u in users:
        if not u or u.pk in seen or (exclude and u.pk == exclude.pk) or not u.is_active:
            continue
        seen.add(u.pk)
        Notification.objects.create(user=u, kind=kind, title=title[:200], body=(body or '')[:400], url=url[:300])


def _audit(user, action, target, details=None):
    from .models import AuditEvent
    AuditEvent.objects.create(actor=user, action=action, target=target, details=details or {})


def care_team(patient, days=14):
    """Clinicians, nurses and programme staff who looked after this patient recently."""
    from .models import Encounter
    since = _now() - timedelta(days=days)
    users = []
    for e in Encounter.objects.filter(patient=patient).filter(Q(status='open') | Q(created_at__gte=since)).select_related('clinician', 'attending_nurse'):
        users += [e.clinician, e.attending_nurse]
    for en in patient.enrolments.filter(status__in=['active', 'paused', 'lost']).select_related('clinician', 'nurse'):
        users += [en.clinician, en.nurse]
    return [u for u in users if u]


def staff_with_role(*roles):
    from django.contrib.auth import get_user_model
    U = get_user_model()
    return list(U.objects.filter(Q(hospital_staff__role__in=roles, hospital_staff__active=True) | Q(is_superuser=True), is_active=True).distinct()[:25])


# =================================================================== recording a death (and archiving the patient)
def _log(log, model, obj, field, old, new):
    log.append({'model': model, 'pk': obj.pk, 'field': field, 'old': old, 'new': new})


def parse_dt(value):
    """'2026-10-18T14:05' from a datetime-local input, in the hospital's time zone."""
    from datetime import datetime
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).strip())
    except ValueError:
        return None
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


@transaction.atomic
def record_death(patient, user, data):
    """Pronounce a death and archive the patient. ``data`` is a dict of form values. Returns (death, summary)."""
    from .models import (Admission, Bed, DeathRecord, Enrolment, ImagingOrder, LabOrder, Patient, Prescription, ProgrammeMessage,
                         ProgrammeVisit, QueueTicket, Referral, SurgicalCase)
    p = Patient.objects.select_for_update().get(pk=patient.pk)
    if p.deceased_at or DeathRecord.objects.filter(patient=p).exclude(status='revoked').exists():
        raise ValidationError('A death is already recorded for this patient.')
    died_at = parse_dt(data.get('died_at'))
    now = _now()
    errors = []
    if not died_at:
        errors.append('Give the date and time of death.')
    elif died_at > now + timedelta(minutes=5):
        errors.append('The time of death cannot be in the future.')
    elif p.dob and died_at.date() < p.dob:
        errors.append('The time of death is before the date of birth.')
    place = data.get('place') or 'ward'
    if place not in dict(DeathRecord.PLACE):
        errors.append('Choose where the death happened.')
    checks = [k for k, _ in DeathRecord.VERIFY_CHECKS if data.get(f'check_{k}')]
    if place != 'community' and not all(c in checks for c in CORE_CHECKS):
        errors.append('Confirm verification of death: no central pulse, no breathing, observed for at least 5 minutes.')
    if errors:
        raise ValidationError(errors)

    enc = p.encounters.filter(status='open').order_by('-created_at').first() or p.encounters.order_by('-created_at').first()
    adm = Admission.objects.filter(encounter__patient=p, discharged_at__isnull=True).select_related('bed__ward').first()
    detail = (data.get('place_detail') or '').strip()[:160] or (str(adm.bed) if adm else '')
    d = DeathRecord.objects.create(
        patient=p, encounter=enc, admission=adm, died_at=died_at, time_estimated=bool(data.get('time_estimated')), place=place,
        place_detail=detail, circumstances=(data.get('circumstances') or '').strip(), resuscitation=data.get('resuscitation', '')[:12],
        verification={k: True for k in checks}, pronounced_by=user, pronounced_at=now, recorded_by=user,
        nok_name=(data.get('nok_name') or '').strip()[:160] or p.emergency_contact[:160], nok_relation=(data.get('nok_relation') or '')[:60],
        nok_phone=(data.get('nok_phone') or '')[:40], rapid_release=bool(data.get('rapid_release')),
        maternal='' if p.sex != 'F' else '',
    )
    log = []
    summary = Counter()
    _log(log, 'Patient', p, 'deceased_at', None, died_at.isoformat())
    p.deceased_at = died_at
    p.save(update_fields=['deceased_at', 'updated_at'])

    for e in p.encounters.filter(status='open'):
        _log(log, 'Encounter', e, 'status', e.status, 'completed')
        e.status, e.completed_at, e.outcome = 'completed', now, 'died'
        e.outcome_notes = f'Died {timezone.localtime(died_at):%d %b %Y %H:%M}'[:300]
        e.save(update_fields=['status', 'completed_at', 'outcome', 'outcome_notes', 'updated_at'])
        summary['visits closed'] += 1
    if adm:
        _log(log, 'Admission', adm, 'discharged_at', None, now.isoformat())
        adm.discharged_at = now
        adm.discharge_notes = (adm.discharge_notes + '\n' if adm.discharge_notes else '') + f'Deceased {timezone.localtime(died_at):%d %b %Y %H:%M}. See {d.number}.'
        adm.save(update_fields=['discharged_at', 'discharge_notes', 'updated_at'])
        Bed.objects.filter(pk=adm.bed_id).update(state='cleaning')
        summary['bed released for terminal cleaning'] += 1
    for t in QueueTicket.objects.filter(patient=p, status__in=['waiting', 'called', 'in_service']):
        _log(log, 'QueueTicket', t, 'status', t.status, 'cancelled')
        t.status = 'cancelled'; t.save(update_fields=['status', 'updated_at'])
        summary['queue tickets cancelled'] += 1
    for o in LabOrder.objects.filter(encounter__patient=p, status='ordered'):
        _log(log, 'LabOrder', o, 'status', o.status, 'cancelled')
        o.status = 'cancelled'; o.save(update_fields=['status', 'updated_at'])
        summary['uncollected lab tests cancelled'] += 1
    for x in ImagingOrder.objects.filter(encounter__patient=p, status='requested'):
        _log(log, 'ImagingOrder', x, 'status', x.status, 'cancelled')
        x.status = 'cancelled'; x.save(update_fields=['status', 'updated_at'])
        summary['imaging requests cancelled'] += 1
    for rx in Prescription.objects.filter(encounter__patient=p, state__in=['draft', 'signed', 'partial']):
        _log(log, 'Prescription', rx, 'state', rx.state, 'cancelled')
        rx.state = 'cancelled'; rx.save(update_fields=['state', 'updated_at'])
        summary['prescriptions stopped'] += 1
    for s in SurgicalCase.objects.filter(patient=p, status__in=['requested', 'scheduled', 'ready', 'postponed']):
        _log(log, 'SurgicalCase', s, 'status', s.status, 'cancelled')
        s.status = 'cancelled'; s.save(update_fields=['status', 'updated_at'])
        summary['planned operations cancelled'] += 1
    for r in Referral.objects.filter(encounter__patient=p, status='draft'):
        _log(log, 'Referral', r, 'status', r.status, 'cancelled')
        r.status = 'cancelled'; r.save(update_fields=['status', 'updated_at'])
        summary['draft referrals cancelled'] += 1
    team = care_team(p)
    for en in Enrolment.objects.filter(patient=p, status__in=['active', 'paused', 'lost']):
        _log(log, 'Enrolment', en, 'status', en.status, 'died')
        en.status = 'died'; en.save(update_fields=['status', 'updated_at'])
        summary['care-programme enrolments ended'] += 1
    for v in ProgrammeVisit.objects.filter(enrolment__patient=p, status__in=['scheduled', 'reminded', 'missed']):
        _log(log, 'ProgrammeVisit', v, 'status', v.status, 'cancelled')
        v.status = 'cancelled'; v.save(update_fields=['status', 'updated_at'])
        summary['planned programme visits cancelled'] += 1
    for m in ProgrammeMessage.objects.filter(enrolment__patient=p, status='pending'):
        _log(log, 'ProgrammeMessage', m, 'status', m.status, 'skipped')
        m.status = 'skipped'; m.error = 'Patient deceased'; m.save(update_fields=['status', 'error', 'updated_at'])
        summary['reminders stopped'] += 1
    d.archive_log = log
    d.save(update_fields=['archive_log', 'updated_at'])

    _audit(user, 'death_recorded', f'patient:{p.pk}', {'death': d.pk, 'archived': dict(summary)})
    who = user.get_full_name() or user.username
    _notify(team, f'Death recorded: {p.full_name}', f'{p.mrn} · {timezone.localtime(died_at):%d %b %H:%M} · recorded by {who}. '
            'Please complete the certificate and inform the family if not yet done.', reverse('death_detail', args=[d.pk]), exclude=user)
    return d, summary


@transaction.atomic
def revoke(death, user, reason):
    """Undo a death recorded in error. Restores the patient, enrolments, programme visits and reminders exactly."""
    from . import models as M
    d = M.DeathRecord.objects.select_for_update().get(pk=death.pk)
    if d.status == 'revoked':
        raise ValidationError('This record has already been marked as entered in error.')
    if len((reason or '').strip()) < 15:
        raise ValidationError('Explain in a sentence why this death was recorded in error.')
    if d.autopsies.exclude(status__in=['cancelled', 'declined', 'requested']).exists():
        raise ValidationError('An autopsy has already started on this record. It cannot be marked as an error here; contact the administrator.')
    restore = {'Enrolment', 'ProgrammeVisit', 'ProgrammeMessage', 'Patient'}
    restored = Counter()
    for entry in reversed(d.archive_log or []):
        if entry['model'] not in restore:
            continue
        model = M.__dict__.get(entry['model'])
        obj = model.objects.filter(pk=entry['pk']).first() if model else None
        if not obj:
            continue
        if entry['model'] == 'Patient':
            obj.deceased_at = None
            obj.save(update_fields=['deceased_at', 'updated_at'])
        elif getattr(obj, entry['field']) == entry['new']:      # untouched since the death was recorded
            setattr(obj, entry['field'], entry['old'])
            fields = [entry['field'], 'updated_at']
            if entry['model'] == 'ProgrammeMessage':
                obj.error = ''
                fields.append('error')
            obj.save(update_fields=fields)
        else:
            continue
        restored[entry['model']] += 1
    d.status, d.revoked_reason, d.revoked_by, d.revoked_at = 'revoked', reason.strip(), user, _now()
    d.save(update_fields=['status', 'revoked_reason', 'revoked_by', 'revoked_at', 'updated_at'])
    if hasattr(d, 'study_case'):
        sc = d.study_case
        sc.status, sc.withdrawn_reason = 'withdrawn', 'Death record entered in error'
        sc.save(update_fields=['status', 'withdrawn_reason', 'updated_at'])
    d.autopsies.filter(status='requested').update(status='cancelled')
    _audit(user, 'death_revoked', f'patient:{d.patient_id}', {'death': d.pk, 'reason': reason[:300], 'restored': dict(restored)})
    _notify(staff_with_role('admin'), f'Death record revoked: {d.patient.full_name}', f'{d.number} marked as entered in error by '
            f'{user.get_full_name() or user.username}: {reason[:200]}', reverse('patient_chart', args=[d.patient_id]), kind='access', exclude=user)
    return d, restored


# =================================================================== the certificate (WHO MCCD)
def certificate_payload(d):
    return {'death': d.pk, 'patient': d.patient.mrn, 'name': d.patient.full_name, 'dob': str(d.patient.dob), 'died_at': d.died_at.isoformat(),
            'chain': [list(x) for x in d.chain], 'contributing': d.contributing, 'icd': d.icd_underlying, 'manner': d.manner,
            'maternal': d.maternal, 'surgery_4w': d.surgery_4w, 'certified_by': d.certified_by_id,
            'certified_at': d.certified_at.isoformat() if d.certified_at else None}


def certificate_hash(d):
    return hashlib.sha256(json.dumps(certificate_payload(d), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_chain(data, patient):
    errors = []
    lines = [(data.get(f'cause_{k}') or '').strip() for k in 'abcd']
    if not lines[0]:
        errors.append('Part I(a) is required: the disease or condition that directly led to death.')
    last = max((i for i, x in enumerate(lines) if x), default=-1)
    if any(not lines[i] for i in range(last + 1)):
        errors.append('Fill Part I from (a) downwards without gaps: each line is the cause of the line above it.')
    filled = [x for x in lines if x]
    if filled and all(MODE_OF_DYING.match(x) for x in filled):
        errors.append('“Cardiac arrest”, “respiratory failure” and similar describe how a person dies, not why. '
                      'Give the disease or injury that led to it.')
    manner = data.get('manner') or 'natural'
    if manner not in ('natural', 'undetermined') and not (data.get('legal_referral') or '').strip():
        errors.append('A death that is not from natural disease must be reported to the police or coroner. Record who was informed.')
    if patient.sex == 'F' and patient.dob and 10 <= (patient.age or 0) <= 54 and not data.get('maternal'):
        errors.append('For a woman aged 10–54, answer the pregnancy question (WHO maternal death rule).')
    if data.get('surgery_4w') and not (data.get('surgery_detail') or '').strip():
        errors.append('Name the operation done in the 4 weeks before death.')
    return errors


@transaction.atomic
def certify(death, user, data):
    from .models import DeathRecord
    d = DeathRecord.objects.select_for_update().get(pk=death.pk)
    if d.status in ('revoked', 'closed'):
        raise ValidationError('This record can no longer be changed.')
    if d.body_status == 'released' and d.certified:
        raise ValidationError('The body has been released; the certificate is locked. Add a note to the record instead.')
    errors = validate_chain(data, d.patient)
    if errors:
        raise ValidationError(errors)
    before = [list(x) for x in d.chain] if d.certified else None
    for k in 'abcd':
        setattr(d, f'cause_{k}', (data.get(f'cause_{k}') or '').strip()[:200])
        setattr(d, f'interval_{k}', (data.get(f'interval_{k}') or '').strip()[:40])
    d.contributing = (data.get('contributing') or '').strip()
    d.icd_underlying = (data.get('icd_underlying') or '').strip().upper()[:12]
    d.manner = data.get('manner') if data.get('manner') in dict(DeathRecord.MANNER) else 'natural'
    d.maternal = data.get('maternal') if data.get('maternal') in dict(DeathRecord.MATERNAL) else ''
    d.surgery_4w = bool(data.get('surgery_4w'))
    d.surgery_detail = (data.get('surgery_detail') or '').strip()[:200]
    d.legal_referral = (data.get('legal_referral') or '').strip()[:160]
    d.certified_by, d.certified_at = user, _now()
    if d.status == 'pronounced':
        d.status = 'certified'
    d.content_hash = certificate_hash(d)
    d.save()
    _audit(user, 'death_certified' if before is None else 'death_certificate_amended', f'patient:{d.patient_id}',
           {'death': d.pk, 'sha256': d.content_hash, 'previous_chain': before})
    if d.teaching_consent != 'declined':
        ensure_study_case(d)
    return d


# =================================================================== family and the body
@transaction.atomic
def inform_family(death, user, data):
    from .models import DeathRecord
    d = DeathRecord.objects.select_for_update().get(pk=death.pk)
    d.nok_name = (data.get('nok_name') or d.nok_name).strip()[:160]
    d.nok_relation = (data.get('nok_relation') or d.nok_relation).strip()[:60]
    d.nok_phone = (data.get('nok_phone') or d.nok_phone).strip()[:40]
    d.family_notes = (data.get('family_notes') or '').strip()
    d.rapid_release = bool(data.get('rapid_release'))
    if data.get('informed') and not d.nok_informed_at:
        if not d.nok_name:
            raise ValidationError('Record who was informed.')
        d.nok_informed_at, d.nok_informed_by = parse_dt(data.get('informed_at')) or _now(), user
        d.nok_how = data.get('nok_how', '')[:12]
    consent = data.get('teaching_consent')
    if consent in dict(DeathRecord.CONSENT) and consent != d.teaching_consent:
        _audit(user, 'teaching_consent', f'patient:{d.patient_id}', {'death': d.pk, 'from': d.teaching_consent, 'to': consent})
        d.teaching_consent = consent
        if consent == 'declined' and hasattr(d, 'study_case') and d.study_case.status == 'published':
            withdraw_case(d.study_case, user, 'The family declined teaching use')
    d.save()
    _audit(user, 'death_family', f'patient:{d.patient_id}', {'death': d.pk, 'informed': bool(d.nok_informed_at)})
    return d


@transaction.atomic
def move_body(death, user, action, data):
    from .models import DeathRecord
    d = DeathRecord.objects.select_for_update().get(pk=death.pk)
    if d.status == 'revoked':
        raise ValidationError('This record was entered in error.')
    now = _now()
    if action == 'mortuary':
        if d.body_status == 'released':
            raise ValidationError('The body has already been released.')
        slot = (data.get('mortuary_slot') or '').strip()[:30]
        if not slot:
            raise ValidationError('Give the mortuary cabinet or drawer.')
        taken = DeathRecord.objects.filter(mortuary_slot__iexact=slot, body_status__in=['mortuary', 'autopsy']).exclude(pk=d.pk).exclude(status='revoked').first()
        if taken:
            raise ValidationError(f'{slot} is occupied ({taken.number}). Choose another cabinet.')
        d.mortuary_slot, d.body_status = slot, 'mortuary'
        d.mortuary_in_at = d.mortuary_in_at or now
    elif action == 'release':
        if d.body_status == 'released':
            raise ValidationError('The body has already been released.')
        if not d.certified:
            raise ValidationError('The cause of death must be certified before the body is released.')
        if d.autopsies.filter(status__in=OPEN_AUTOPSY).exclude(status='preliminary').exists():
            raise ValidationError('An autopsy is still pending. Finish or cancel it before release.')
        if not (data.get('released_to') or '').strip() or not (data.get('released_id_doc') or '').strip():
            raise ValidationError('Record who collected the body and the identity document they showed.')
        if not data.get('identity_confirmed'):
            raise ValidationError('Confirm that the body was identified by the collector against the wristband and record number.')
        d.released_to = data['released_to'].strip()[:160]
        d.released_relation = (data.get('released_relation') or '').strip()[:60]
        d.released_id_doc = data['released_id_doc'].strip()[:80]
        d.release_notes = (data.get('release_notes') or '').strip()[:300]
        d.released_at, d.released_by, d.body_status = now, user, 'released'
        if d.status == 'certified':
            d.status = 'released'
    else:
        raise ValidationError('Unknown action.')
    d.save()
    _audit(user, f'body_{action}', f'patient:{d.patient_id}', {'death': d.pk, 'slot': d.mortuary_slot})
    maybe_close(d)
    return d


def maybe_close(d):
    """A death is closed when the body is released, any autopsy is finished and the M&M review is final."""
    from .models import DeathRecord, MortalityReview
    d = DeathRecord.objects.get(pk=d.pk)                      # always decide on the current state
    review = MortalityReview.objects.filter(death=d).first()
    if d.status == 'released' and review and review.status == 'final' and not d.autopsies.filter(status__in=OPEN_AUTOPSY).exists():
        d.status = 'closed'
        d.save(update_fields=['status', 'updated_at'])
    return d


# =================================================================== autopsy
def autopsy_hash(a):
    payload = {k: getattr(a, k) for k in ('kind', 'external_exam', 'interview', 'histology', 'microbiology', 'toxicology', 'anatomical_diagnosis',
                                          'cause_a', 'cause_b', 'cause_c', 'cause_d', 'contributing', 'goldman', 'correlation_notes', 'learning_points')}
    payload.update(organs=a.organs, death=a.death_id, signed_by=a.signed_by_id, height=str(a.height_cm), weight=str(a.weight_kg))
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


@transaction.atomic
def request_autopsy(death, user, data):
    from .models import Autopsy, DeathRecord
    death = DeathRecord.objects.select_for_update().get(pk=death.pk)
    if death.status == 'revoked':
        raise ValidationError('This record was entered in error.')
    kind = data.get('kind') if data.get('kind') in dict(Autopsy.KIND) else 'clinical'
    questions = (data.get('questions') or '').strip()
    if len(questions) < 10:
        raise ValidationError('Write the questions the autopsy should answer.')
    if death.body_status == 'released' and kind != 'verbal':
        raise ValidationError('The body has been released; only a verbal autopsy is possible now.')
    if death.autopsies.filter(status__in=OPEN_AUTOPSY).exists():
        raise ValidationError('An autopsy is already in progress for this death.')
    if kind == 'medicolegal' and not (data.get('legal_authority') or '').strip():
        raise ValidationError('A medico-legal autopsy needs the ordering authority and reference.')
    enc = death.encounter
    clinical = ' → '.join(c for _l, c, _i in reversed(death.chain)) if death.chain else (enc.diagnosis if enc else '')
    a = Autopsy.objects.create(death=death, kind=kind, questions=questions, requested_by=user, clinical_diagnosis=clinical[:2000],
                               legal_authority=(data.get('legal_authority') or '').strip()[:160],
                               status='consented' if kind == 'medicolegal' else 'requested')
    _audit(user, 'autopsy_requested', f'patient:{death.patient_id}', {'autopsy': a.pk, 'kind': kind})
    _notify(staff_with_role('lab', 'admin'), f'Autopsy requested · {a.get_kind_display()}', f'{death.patient.mrn}: {questions[:200]}',
            reverse('autopsy_detail', args=[a.pk]), exclude=user)
    return a


ORGAN_FIELDS = ('weight_g', 'finding')


def save_autopsy(a, data):
    """Save the working report (not allowed once signed)."""
    from .models import BODY_SYSTEMS
    from decimal import Decimal, InvalidOperation
    if a.signed or a.status in ('cancelled', 'declined'):
        raise ValidationError('This autopsy report is closed. Add an addendum instead.')
    for f in ('external_exam', 'interview', 'histology', 'microbiology', 'toxicology', 'anatomical_diagnosis', 'contributing',
              'correlation_notes', 'learning_points'):
        if f in data:
            setattr(a, f, (data.get(f) or '').strip())
    for k in 'abcd':
        if f'cause_{k}' in data:
            setattr(a, f'cause_{k}', (data.get(f'cause_{k}') or '').strip()[:200])
    if data.get('goldman', None) is not None and data.get('goldman') in dict(a.GOLDMAN):
        a.goldman = data.get('goldman')
    for f in ('height_cm', 'weight_kg'):
        if f in data:
            v = (data.get(f) or '').strip()
            try:
                setattr(a, f, Decimal(v) if v else None)
            except InvalidOperation:
                raise ValidationError(f'{f.replace("_", " ")} must be a number.')
    organs = dict(a.organs or {})
    for key, _label in BODY_SYSTEMS:
        if f'organ_{key}_finding' not in data and f'organ_{key}_weight_g' not in data:
            continue
        row = {'finding': (data.get(f'organ_{key}_finding') or '').strip()[:1500],
               'weight_g': (data.get(f'organ_{key}_weight_g') or '').strip()[:10],
               'abnormal': bool(data.get(f'organ_{key}_abnormal'))}
        if row['finding'] or row['weight_g']:
            organs[key] = row
        else:
            organs.pop(key, None)
    a.organs = organs
    a.save()
    return a


@transaction.atomic
def autopsy_action(autopsy, user, action, data):
    from django.contrib.auth import get_user_model
    from .models import Autopsy
    a = Autopsy.objects.select_for_update().select_related('death__patient').get(pk=autopsy.pk)
    d = a.death
    now = _now()
    if action == 'consent':
        if a.status != 'requested':
            raise ValidationError('Consent can only be recorded for a new request.')
        if not (data.get('consent_name') or '').strip() or not (data.get('consent_relation') or '').strip():
            raise ValidationError('Record who gave consent and their relationship to the deceased.')
        a.consent_name, a.consent_relation = data['consent_name'].strip()[:160], data['consent_relation'].strip()[:60]
        a.consent_scope = (data.get('consent_scope') or 'Full autopsy').strip()[:300]
        a.organ_retention, a.consent_at, a.consent_witness, a.status = bool(data.get('organ_retention')), now, user, 'consented'
    elif action == 'decline':
        if a.status != 'requested':
            raise ValidationError('Only a pending request can be declined.')
        a.status = 'declined'
        a.correlation_notes = (data.get('note') or 'Family declined autopsy.').strip()
    elif action == 'schedule':
        if a.status not in ('consented', 'scheduled'):
            raise ValidationError('Record consent before scheduling.')
        when = parse_dt(data.get('scheduled_at'))
        if not when:
            raise ValidationError('Choose a date and time.')
        pid = data.get('pathologist')
        a.pathologist = get_user_model().objects.filter(pk=pid).first() if str(pid or '').isdigit() else a.pathologist
        a.scheduled_at, a.status = when, 'scheduled'
    elif action == 'start':
        if a.status not in ('consented', 'scheduled') and not (a.kind == 'verbal' and a.status == 'requested'):
            raise ValidationError('This autopsy cannot start yet: consent is needed first.')
        if d.body_status == 'released' and a.kind != 'verbal':
            raise ValidationError('The body has been released.')
        a.started_at, a.status = now, 'in_progress'
        a.pathologist = a.pathologist or user
        if a.kind != 'verbal' and d.body_status in ('ward', 'mortuary'):
            d.body_status = 'autopsy'; d.save(update_fields=['body_status', 'updated_at'])
    elif action == 'preliminary':
        if a.status != 'in_progress':
            raise ValidationError('Start the autopsy first.')
        save_autopsy(a, data)
        if not (a.anatomical_diagnosis or a.cause_a):
            raise ValidationError('A preliminary report needs at least the main findings or a provisional cause.')
        a.status = 'preliminary'
        if d.body_status == 'autopsy':
            d.body_status = 'mortuary'; d.save(update_fields=['body_status', 'updated_at'])
        _notify([a.requested_by] + care_team(d.patient, days=30), f'Preliminary autopsy report · {d.patient.full_name}',
                (a.anatomical_diagnosis or a.cause_a)[:300], reverse('autopsy_detail', args=[a.pk]), exclude=user)
    elif action == 'sign':
        if a.status not in ('in_progress', 'preliminary'):
            raise ValidationError('Only an autopsy in progress can be signed.')
        save_autopsy(a, data)
        missing = [lbl for f, lbl in (('cause_a', 'cause of death I(a)'), ('anatomical_diagnosis', 'pathological diagnoses'), ('goldman', 'clinicopathological correlation'))
                   if not getattr(a, f)]
        if a.kind == 'verbal':
            missing = [m for m in missing if m != 'pathological diagnoses']
        if missing:
            raise ValidationError('Before signing, complete: ' + ', '.join(missing) + '.')
        a.status, a.signed_by, a.signed_at, a.completed_at = 'final', user, now, now
        a.content_hash = autopsy_hash(a)
        if d.body_status == 'autopsy':
            d.body_status = 'mortuary'; d.save(update_fields=['body_status', 'updated_at'])
        _notify([a.requested_by, d.certified_by] + care_team(d.patient, days=30), f'Autopsy report signed · {d.patient.full_name}',
                f'Cause: {a.underlying_cause or a.cause_a}. {a.get_goldman_display()}', reverse('autopsy_detail', args=[a.pk]), exclude=user)
    elif action == 'addendum':
        if not a.signed:
            raise ValidationError('Addenda are for signed reports; edit the report instead.')
        text = (data.get('text') or '').strip()
        if len(text) < 5:
            raise ValidationError('Write the addendum.')
        a.addenda = list(a.addenda or []) + [{'at': now.isoformat(), 'by': user.get_full_name() or user.username, 'text': text[:3000]}]
    elif action == 'cancel':
        if a.signed:
            raise ValidationError('A signed report cannot be cancelled.')
        a.status = 'cancelled'
        if d.body_status == 'autopsy':
            d.body_status = 'mortuary'; d.save(update_fields=['body_status', 'updated_at'])
    else:
        raise ValidationError('Unknown action.')
    a.save()
    _audit(user, f'autopsy_{action}', f'patient:{d.patient_id}', {'autopsy': a.pk, 'status': a.status})
    if action == 'sign':
        from .models import StudyCase
        sc = StudyCase.objects.filter(death=d, status='draft').first()
        if sc:
            refresh_case(sc)
    maybe_close(d)
    return a


# =================================================================== M&M review
@transaction.atomic
def save_review(death, user, data, finalise=False):
    from .models import DeathRecord, MortalityReview, StudyCase
    from datetime import date
    death = DeathRecord.objects.get(pk=death.pk)
    r, _ = MortalityReview.objects.get_or_create(death=death)
    if r.status == 'final':
        raise ValidationError('This review is final.')
    r.summary = (data.get('summary') or '').strip()
    r.attendees = (data.get('attendees') or '').strip()[:400]
    try:
        r.meeting_date = date.fromisoformat(data.get('meeting_date')) if data.get('meeting_date') else None
    except ValueError:
        raise ValidationError('Meeting date is not valid.')
    r.preventability = data.get('preventability') if data.get('preventability') in dict(MortalityReview.PREVENTABLE) else ''
    r.delays = [k for k, _ in MortalityReview.DELAYS if k in data.getlist('delays')] if hasattr(data, 'getlist') else data.get('delays', [])
    r.factors = [k for k, _ in MortalityReview.FACTORS if k in data.getlist('factors')] if hasattr(data, 'getlist') else data.get('factors', [])
    r.went_well = (data.get('went_well') or '').strip()
    r.lessons = (data.get('lessons') or '').strip()
    actions = []
    for i in range(6):
        t = (data.get(f'action_{i}_text') or '').strip()
        if t:
            actions.append({'text': t[:300], 'owner': (data.get(f'action_{i}_owner') or '').strip()[:80],
                            'due': (data.get(f'action_{i}_due') or '')[:10], 'done': bool(data.get(f'action_{i}_done'))})
    r.actions = actions
    r.chair = r.chair or user
    if finalise:
        missing = [lbl for ok, lbl in ((r.summary, 'case summary'), (r.preventability, 'preventability'), (r.lessons or r.went_well, 'lessons or what went well'))
                   if not ok]
        if missing:
            raise ValidationError('Before finalising, complete: ' + ', '.join(missing) + '.')
        r.status, r.finalised_by, r.finalised_at = 'final', user, _now()
    r.save()
    _audit(user, 'mortality_review_final' if finalise else 'mortality_review_saved', f'patient:{death.patient_id}', {'death': death.pk})
    if finalise:
        sc = StudyCase.objects.filter(death=death, status='draft').first()
        if sc:
            refresh_case(sc)
        maybe_close(death)
    return r


# =================================================================== anonymised study case for the library
AGE_BANDS = [(0, 0, 'under 1 year'), (1, 4, '1–4 years'), (5, 14, '5–14 years'), (15, 29, '15–29 years'), (30, 49, '30–49 years'),
             (50, 64, '50–64 years'), (65, 200, '65 years or older')]
MONTHS = r'(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sep(t(ember)?)?|oct(ober)?|nov(ember)?|dec(ember)?)'
DATE_RES = [re.compile(r'\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b'), re.compile(r'\b\d{4}-\d{2}-\d{2}\b'),
            re.compile(rf'\b\d{{1,2}}(st|nd|rd|th)?\s+{MONTHS}\.?(\s+\d{{2,4}})?\b', re.I), re.compile(rf'\b{MONTHS}\.?\s+\d{{1,2}}(st|nd|rd|th)?(,?\s+\d{{4}})?\b', re.I)]
PHONE_RE = re.compile(r'(\+?\d[\d\s\-]{6,}\d)')
EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
MRN_RE = re.compile(r'\bMF-[0-9A-F]{6,}\b', re.I)


def age_band(age):
    if age is None:
        return 'age unknown'
    return next(l for lo, hi, l in AGE_BANDS if lo <= age <= hi)


def _identifiers(d):
    """Words that must never appear in a study case: names of the patient, the family and the staff involved."""
    p = d.patient
    words = {p.first_name, p.last_name, d.nok_name, d.released_to, p.emergency_contact}
    if p.location_id:
        words |= {p.location.name, getattr(p.location.parent, 'name', '')}
    users = {d.pronounced_by, d.certified_by, d.recorded_by}
    for e in p.encounters.select_related('clinician', 'attending_nurse'):
        users |= {e.clinician, e.attending_nurse}
    for a in d.autopsies.select_related('pathologist', 'requested_by'):
        users |= {a.pathologist, a.requested_by}
        words |= {a.consent_name}
    for u in users:
        if u:
            words |= {u.first_name, u.last_name, u.username}
    out = set()
    for w in words:
        for part in re.split(r'[\s,;:()]+', w or ''):
            part = part.strip(".'\"")
            if len(part) >= 3 and not part.isdigit():
                out.add(part)
    return sorted(out, key=len, reverse=True)


def scrubber(d):
    names = _identifiers(d)
    name_re = re.compile(r'\b(' + '|'.join(re.escape(n) for n in names) + r')\b', re.I) if names else None
    mrn = d.patient.mrn

    def scrub(text, limit=900):
        if not text:
            return ''
        t = str(text).replace(mrn, '[number]')
        t = MRN_RE.sub('[number]', t)
        t = EMAIL_RE.sub('[email]', t)
        for rx in DATE_RES:
            t = rx.sub('[date]', t)
        t = PHONE_RE.sub('[phone]', t)
        if name_re:
            t = name_re.sub('[name]', t)
        t = re.sub(r'\s+', ' ', t).strip()
        return t[:limit] + ('…' if len(t) > limit else '')
    return scrub


def _when(dt, died_at):
    secs = (died_at - dt).total_seconds()
    if secs < 0:
        return {'h': round(secs / 3600, 1), 'label': 'after death'}
    h = secs / 3600
    if h < 1:
        lbl = f'{max(1, int(secs // 60))} min before death'
    elif h < 48:
        lbl = f'{int(h)} h before death'
    elif h < 24 * 60:
        lbl = f'{int(h // 24)} days before death'
    elif h < 24 * 730:
        lbl = f'{int(h // (24 * 30))} months before death'
    else:
        lbl = f'{int(h // (24 * 365))} years before death'
    return {'h': round(h, 1), 'label': lbl}


def build_snapshot(d):
    """The anonymised story of this patient: profile, the course of care, death, autopsy and review. Relative times only."""
    from .models import ImagingOrder, LabResultValue, Location, Prescription
    p, died = d.patient, d.died_at
    scrub = scrubber(d)
    region = dict(Location.REGIONS).get(p.location.region, '') if p.location_id else ''
    events = []
    encs = list(p.encounters.select_related('department').order_by('-created_at')[:40])
    for e in encs:
        events.append({**_when(e.created_at, died), 'kind': 'visit', 'title': scrub(e.reason, 160), 'dept': str(e.department or ''),
                       'dx': scrub(e.diagnosis, 300), 'symptoms': scrub(e.symptoms, 400), 'assessment': scrub(e.assessment, 500),
                       'plan': scrub(e.plan, 400), 'vitals': {k: str(v)[:12] for k, v in (e.vitals or {}).items()}, 'outcome': e.get_outcome_display() if e.outcome else ''})
    vals = defaultdict(list)
    for v in (LabResultValue.objects.filter(order__encounter__patient=p).exclude(flag__in=['', 'N'])
              .select_related('parameter', 'order__test').order_by('-order__created_at')[:150]):
        vals[v.order_id].append(f'{v.parameter.name} {v.display}{(" " + v.parameter.unit) if v.parameter.unit else ""} ({v.flag})')
    from .models import LabOrder
    for o in LabOrder.objects.filter(encounter__patient=p).exclude(status='cancelled').select_related('test').order_by('-created_at')[:60]:
        events.append({**_when(o.created_at, died), 'kind': 'lab', 'title': o.test.name, 'abnormal': vals.get(o.pk, [])[:8],
                       'status': o.get_status_display(), 'flag': bool(vals.get(o.pk))})
    for x in ImagingOrder.objects.filter(encounter__patient=p).exclude(status='cancelled').order_by('-created_at')[:20]:
        events.append({**_when(x.created_at, died), 'kind': 'imaging', 'title': f'{x.get_modality_display()} · {x.region}',
                       'impression': scrub(x.impression or x.findings, 500), 'flag': bool(x.abnormal)})
    for rx in Prescription.objects.filter(encounter__patient=p).exclude(state='draft').prefetch_related('items__medication').order_by('-created_at')[:40]:
        events.append({**_when(rx.created_at, died), 'kind': 'rx', 'title': ', '.join(sorted({i.medication.name for i in rx.items.all()}))[:300],
                       'lines': [f'{i.medication.name} {i.dose} {i.get_route_display()} {i.get_frequency_display()}'.strip() for i in rx.items.all()][:8]})
    for s in p.operations.exclude(status='cancelled').order_by('-created_at')[:10]:
        events.append({**_when(s.scheduled_start or s.created_at, died), 'kind': 'operation', 'title': scrub(s.title, 160), 'status': s.get_status_display()})
    from .models import Admission
    for a in Admission.objects.filter(encounter__patient=p).select_related('bed').order_by('-admitted_at')[:10]:
        end = a.discharged_at or died
        events.append({**_when(a.admitted_at, died), 'kind': 'admission', 'title': f'Admitted · {a.bed.get_kind_display()} bed',
                       'days': round((end - a.admitted_at).total_seconds() / 86400, 1)})
    events.sort(key=lambda x: -x['h'])
    snap = {
        'built_at': _now().isoformat(),
        'profile': {'sex': p.get_sex_display(), 'age_band': age_band(p.age if not p.dob else (died.date() - p.dob).days // 365),
                    'region': region, 'blood_group': p.blood_group,
                    'conditions': [{'name': scrub(c.name, 120), 'status': c.get_status_display()} for c in p.conditions.all()[:15]],
                    'allergies': [a.substance for a in p.allergies.filter(status='active')[:10]],
                    'visits': p.encounters.count()},
        'events': events,
        'death': {'place': d.get_place_display(), 'manner': d.get_manner_display(), 'resuscitation': d.get_resuscitation_display() if d.resuscitation else '',
                  'hours_in_hospital': d.hours_in_hospital, 'within_24h': d.within_24h, 'maternal': d.get_maternal_display() if d.maternal else '',
                  'perinatal': d.is_perinatal, 'circumstances': scrub(d.circumstances, 900), 'surgery_4w': d.surgery_4w,
                  'chain': [{'line': l, 'cause': scrub(c, 200), 'interval': i} for l, c, i in d.chain], 'contributing': scrub(d.contributing, 400),
                  'icd': d.icd_underlying, 'year': died.year},
    }
    a = d.autopsies.filter(status='final').order_by('-signed_at').first() or d.autopsies.filter(status='preliminary').first()
    if a:
        snap['autopsy'] = {'kind': a.get_kind_display(), 'status': a.get_status_display(), 'questions': scrub(a.questions, 500),
                           'clinical': scrub(a.clinical_diagnosis, 500), 'external': scrub(a.external_exam, 900),
                           'interview': scrub(a.interview, 900),
                           'organs': [{'key': r['key'], 'label': r['label'], 'weight_g': r.get('weight_g', ''), 'finding': scrub(r.get('finding'), 600),
                                       'abnormal': r.get('abnormal', False)} for r in a.organ_rows if r.get('finding') or r.get('weight_g')],
                           'histology': scrub(a.histology, 900), 'microbiology': scrub(a.microbiology, 600), 'toxicology': scrub(a.toxicology, 500),
                           'diagnosis': scrub(a.anatomical_diagnosis, 900), 'chain': [{'line': l, 'cause': scrub(c, 200)} for l, c in a.chain],
                           'contributing': scrub(a.contributing, 400), 'goldman': a.goldman, 'goldman_label': a.get_goldman_display() if a.goldman else '',
                           'correlation': scrub(a.correlation_notes, 900), 'learning': [scrub(x, 300) for x in a.learning_list]}
    r = getattr(d, 'review', None)
    if r and r.status == 'final':
        snap['review'] = {'preventability': r.get_preventability_display() if r.preventability else '', 'preventability_key': r.preventability,
                          'delays': r.delay_labels(), 'factors': r.factor_labels(), 'went_well': scrub(r.went_well, 600),
                          'lessons': [scrub(x, 300) for x in r.lesson_list], 'actions': [scrub(x['text'], 300) for x in r.actions]}
    return snap


def case_title(d):
    from . import library as L
    a = d.autopsies.filter(status='final').order_by('-signed_at').first()
    cause = (a.underlying_cause if a else '') or d.underlying_cause or (d.encounter.diagnosis if d.encounter else '') or 'Undiagnosed illness'
    slug, title = L.match(cause)
    p = d.patient
    age = (d.died_at.date() - p.dob).days // 365 if p.dob else None
    sex = {'F': 'female', 'M': 'male'}.get(p.sex, 'patient')
    return slug, f'{title} · {sex}, {age_band(age)}'


def _next_code(year):
    from .models import StudyCase
    n = StudyCase.objects.filter(code__startswith=f'SC-{year}-').count() + 1
    while StudyCase.objects.filter(code=f'SC-{year}-{n:03d}').exists():
        n += 1
    return f'SC-{year}-{n:03d}'


def ensure_study_case(d):
    """A draft study case exists for every certified death the family has not refused."""
    from .models import StudyCase
    if d.teaching_consent == 'declined' or d.status == 'revoked':
        return None
    sc = StudyCase.objects.filter(death=d).first()
    if sc:
        if sc.status == 'draft':
            refresh_case(sc)
        return sc
    slug, title = case_title(d)
    sc = StudyCase.objects.create(death=d, code=_next_code(_now().year), title=title, slug=slug, snapshot=build_snapshot(d),
                                  snapshot_at=_now(), question='What was the underlying cause of death, and could it have been prevented?')
    return sc


def refresh_case(sc):
    if sc.status != 'draft':
        raise ValidationError('A published case is frozen. Withdraw it to rebuild.')
    sc.slug, sc.title = case_title(sc.death)
    sc.snapshot, sc.snapshot_at = build_snapshot(sc.death), _now()
    sc.save(update_fields=['slug', 'title', 'snapshot', 'snapshot_at', 'updated_at'])
    return sc


@transaction.atomic
def publish_case(sc, user, data):
    from .models import StudyCase
    sc = StudyCase.objects.select_related('death__patient').get(pk=sc.pk)
    d = sc.death
    if d.status == 'revoked':
        raise ValidationError('The death record was entered in error.')
    if d.teaching_consent == 'declined':
        raise ValidationError('The family declined teaching use; this case cannot be published.')
    if d.teaching_consent == 'not_asked':
        raise ValidationError('Record the family’s decision on teaching use (or hospital policy) on the death record first.')
    if not d.certified:
        raise ValidationError('Certify the cause of death first.')
    checks = [k for k, _ in STUDY_CHECKS if data.get(f'chk_{k}')]
    if len(checks) < len(STUDY_CHECKS):
        raise ValidationError('Confirm every anonymisation check before publishing.')
    title = (data.get('title') or '').strip()
    if sc.status == 'draft':
        refresh_case(sc)
    sc.title = title[:200] or sc.title
    sc.teaching_points = (data.get('teaching_points') or '').strip()
    sc.question = (data.get('question') or sc.question).strip()[:240]
    leak = scrubber(d)
    for t in [sc.title, sc.teaching_points, sc.question]:
        if leak(t, 99999) != re.sub(r'\s+', ' ', t).strip():
            raise ValidationError('The title, question or teaching points contain a name, number or date. Remove it and try again.')
    sc.checklist, sc.status, sc.published_by, sc.published_at = checks, 'published', user, _now()
    sc.save()
    _audit(user, 'study_case_published', f'study_case:{sc.pk}', {'death': d.pk, 'code': sc.code})
    return sc


def withdraw_case(sc, user, reason):
    sc.status, sc.withdrawn_reason = 'withdrawn', (reason or '').strip()[:300] or 'Withdrawn'
    sc.save(update_fields=['status', 'withdrawn_reason', 'updated_at'])
    _audit(user, 'study_case_withdrawn', f'study_case:{sc.pk}', {'reason': sc.withdrawn_reason})
    return sc


def redraft_case(sc, user):
    if sc.death.teaching_consent == 'declined':
        raise ValidationError('The family declined teaching use.')
    sc.status, sc.published_at, sc.checklist = 'draft', None, []
    sc.save(update_fields=['status', 'published_at', 'checklist', 'updated_at'])
    refresh_case(sc)
    _audit(user, 'study_case_redraft', f'study_case:{sc.pk}', {})
    return sc


def published_cases(slug=None, q=''):
    from .models import StudyCase
    qs = StudyCase.objects.filter(status='published').select_related('death')
    if slug:
        qs = qs.filter(slug=slug)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(teaching_points__icontains=q))
    return qs


# =================================================================== journey, alerts and statistics
def journey(d):
    """The steps after a death, in order, for the stepper on the death record."""
    a = d.autopsies.exclude(status__in=['cancelled']).first()
    r = getattr(d, 'review', None)
    sc = getattr(d, 'study_case', None)
    steps = [
        ('pronounced', 'Pronounced', True, d.pronounced_at),
        ('family', 'Family informed', bool(d.nok_informed_at), d.nok_informed_at),
        ('certified', 'Certificate', d.certified, d.certified_at),
        ('mortuary', 'Mortuary', bool(d.mortuary_in_at), d.mortuary_in_at),
    ]
    if a:
        steps.append(('autopsy', 'Autopsy' if a.status != 'declined' else 'Autopsy declined', a.status in ('final', 'declined'), a.signed_at or a.consent_at))
    steps += [
        ('released', 'Released', bool(d.released_at), d.released_at),
        ('review', 'M&M review', bool(r and r.status == 'final'), r.finalised_at if r else None),
        ('library', 'In the library', bool(sc and sc.status == 'published'), sc.published_at if sc else None),
    ]
    current = next((s[0] for s in steps if not s[2]), None)
    return [{'key': k, 'label': l, 'done': done, 'at': at, 'current': k == current} for k, l, done, at in steps]


def alerts(qs=None):
    """Things the mortuary and the clinical teams need to do now."""
    from .models import Autopsy, DeathRecord
    now = _now()
    live = qs if qs is not None else DeathRecord.objects.exclude(status='revoked')
    out = []
    for d in live.filter(certified_at__isnull=True).select_related('patient'):
        h = (now - d.died_at).total_seconds() / 3600
        if h >= 12 or d.rapid_release:
            out.append({'level': 'red' if h >= 24 or d.rapid_release else 'amber', 'icon': 'bi-file-earmark-medical', 'd': d,
                        'text': f'Certificate not written · {int(h)} h' + (' · family asked for rapid release' if d.rapid_release else '')})
    for d in live.filter(nok_informed_at__isnull=True).select_related('patient'):
        out.append({'level': 'amber', 'icon': 'bi-people', 'd': d, 'text': 'Family not yet recorded as informed'})
    for d in live.filter(body_status__in=['mortuary', 'autopsy']).select_related('patient'):
        days = d.days_in_mortuary or 0
        if days >= 7:
            out.append({'level': 'red' if days >= 14 else 'amber', 'icon': 'bi-snow', 'd': d, 'text': f'In the mortuary {days} days · unclaimed?'})
    for a in Autopsy.objects.filter(status='requested', created_at__lte=now - timedelta(hours=48)).select_related('death__patient'):
        out.append({'level': 'amber', 'icon': 'bi-clipboard2-check', 'd': a.death, 'text': f'{a.number}: no consent decision after 48 h'})
    for d in live.filter(died_at__lte=now - timedelta(days=14)).filter(Q(review__isnull=True) | Q(review__status='draft')).select_related('patient')[:30]:
        out.append({'level': 'indigo', 'icon': 'bi-people-fill', 'd': d, 'text': 'M&M review not finalised'})
    order = {'red': 0, 'amber': 1, 'indigo': 2}
    out.sort(key=lambda x: (order[x['level']], x['d'].died_at))
    return out


def stats():
    from . import library as L
    from .models import Admission, Autopsy, DeathRecord, StudyCase
    now = _now()
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    live = DeathRecord.objects.exclude(status='revoked').select_related('patient', 'encounter')
    last12 = list(live.filter(died_at__gte=now - timedelta(days=365)))
    d30 = [d for d in last12 if d.died_at >= now - timedelta(days=30)]
    since90 = now - timedelta(days=90)
    adm_ended = Admission.objects.filter(discharged_at__gte=since90).count()
    adm_deaths = sum(1 for d in last12 if d.died_at >= since90 and d.admission_id)
    finals = {a.death_id: a for a in Autopsy.objects.filter(status='final', death__in=[d.pk for d in last12])}
    causes = Counter()
    for d in last12:
        cause = finals[d.pk].underlying_cause if d.pk in finals else d.underlying_cause
        if cause:
            causes[L.match(cause)] += 1
    today = timezone.localdate()
    months = []
    for i in range(11, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12; y -= 1
        months.append((y, m))
    per = Counter((timezone.localtime(d.died_at).year, timezone.localtime(d.died_at).month) for d in last12)
    trend = [{'label': f'{m:02d}/{str(y)[2:]}', 'n': per.get((y, m), 0)} for y, m in months]
    bands = Counter(age_band((d.died_at.date() - d.patient.dob).days // 365 if d.patient.dob else None) for d in last12)
    goldman = Counter(a.goldman for a in finals.values() if a.goldman)
    n_final = len(finals)
    return {
        'n30': len(d30), 'n_year': sum(1 for d in last12 if d.died_at >= year_start), 'n12': len(last12),
        'rate': round(adm_deaths * 100 / adm_ended, 1) if adm_ended else None, 'adm_ended': adm_ended, 'adm_deaths': adm_deaths,
        'within_24h': sum(1 for d in last12 if d.within_24h), 'maternal': sum(1 for d in last12 if d.is_maternal and d.died_at >= year_start),
        'perinatal': sum(1 for d in last12 if d.is_perinatal),
        'autopsy_rate': round(n_final * 100 / len(last12)) if last12 else 0, 'n_autopsy': n_final,
        'uncertified': live.filter(certified_at__isnull=True).count(),
        'in_mortuary': live.filter(body_status__in=['mortuary', 'autopsy']).count(),
        'open_autopsies': Autopsy.objects.filter(status__in=OPEN_AUTOPSY).count(),
        'cases_published': StudyCase.objects.filter(status='published').count(),
        'cases_draft': StudyCase.objects.filter(status='draft', death__status__in=['certified', 'released', 'closed']).count(),
        'causes': [{'slug': s, 'title': t, 'n': n} for (s, t), n in causes.most_common(8)],
        'cause_peak': max([n for n in causes.values()] or [1]),
        'trend': trend, 'peak': max(1, max(t['n'] for t in trend)),
        'places': [{'label': dict(DeathRecord.PLACE).get(k, k), 'n': n} for k, n in Counter(d.place for d in last12).most_common()],
        'ages': [{'label': l, 'n': bands.get(l, 0)} for _lo, _hi, l in AGE_BANDS],
        'age_peak': max([bands.get(l, 0) for *_x, l in AGE_BANDS] or [1]) or 1,
        'goldman': [{'key': k, 'label': lbl.split(' · ')[0], 'desc': lbl.split(' · ', 1)[-1], 'n': goldman.get(k, 0),
                     'pct': round(goldman.get(k, 0) * 100 / n_final) if n_final else 0} for k, lbl in Autopsy.GOLDMAN if k],
        'major_missed': goldman.get('I', 0) + goldman.get('II', 0), 'n_final': n_final,
    }


def deaths_for_slug(slug):
    """How many deaths in the last 12 months had this library diagnosis as their (autopsy-confirmed or certified) underlying cause."""
    from . import library as L
    from .models import Autopsy, DeathRecord
    since = _now() - timedelta(days=365)
    n = 0
    finals = {a.death_id: a.underlying_cause for a in Autopsy.objects.filter(status='final', death__died_at__gte=since)}
    for d in DeathRecord.objects.exclude(status='revoked').filter(died_at__gte=since):
        cause = finals.get(d.pk) or d.underlying_cause
        if cause and L.match(cause)[0] == slug:
            n += 1
    return n
