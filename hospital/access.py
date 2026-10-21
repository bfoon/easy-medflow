"""Who may do what: capabilities, access groups and which patients' records a user may open.

* A **capability** is one thing a user may do (open patient records, dispense, update stock, write operation notes...).
  Every module check in the code (``authorize(request, 'clinical')``) is a capability, so administrators control all of
  them from the Access & roles page.
* An **access group** (models_access.AccessGroup) is a named set of capabilities. A user in one or more groups gets
  exactly the capabilities of those groups. A user in no group keeps the standard access of their role, so nothing
  changes for a hospital until it starts using groups.
* **Patient scope.** Without ``all_patients`` a user opens records only for patients being cared for now: an open visit,
  a current admission or an operation in progress, plus a short grace period after the visit ends to finish notes.
  Anything else needs emergency access ("break the glass"): a written reason, time-limited, logged and reported to the
  access administrators.
"""
import time

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils import timezone

# (key, label, section, help). Module keys match the ROLES keys used by authorize() across the code.
CAPABILITIES = [
    ('all', 'Use E-MedFlow', 'General', 'Sign in and see the overview, queue and shared pages.'),
    ('patient_records', 'Open patient records', 'Patients', 'Charts, visits, results and history (limited by patient scope below).'),
    ('all_patients', 'See every patient', 'Patients', 'Without this, records open only for patients with an open visit or current admission.'),
    ('break_glass', 'Emergency access to other patients', 'Patients', 'Open another patient’s record for 4 hours after giving a reason. Logged and reported.'),
    ('reception', 'Register and check in patients', 'Patients', 'Registration, check-in and queue tickets.'),
    ('clinical', 'Clinical care', 'Clinical', 'Visits, notes, ordering tests, prescribing, injuries, eyes & ears, referrals.'),
    ('bedside', 'Bedside observations and equipment', 'Clinical', 'Record observations and set up drips, oxygen and monitors.'),
    ('beds', 'Manage beds and wards', 'Clinical', 'Admit, discharge and bed cleaning.'),
    ('theatre_view', 'See the theatre board', 'Theatre', 'The schedule and case pages.'),
    ('theatre', 'Run operations', 'Theatre', 'Book operations, pre-op checks, WHO checklist and recovery.'),
    ('operation_note', 'Write operation notes', 'Theatre', 'Usually surgeons and doctors.'),
    ('lab', 'Laboratory work', 'Diagnostics', 'Collect, process, enter and verify results.'),
    ('imaging', 'Imaging', 'Diagnostics', 'Take and report imaging studies.'),
    ('imaging_ai', 'Imaging AI tools', 'Diagnostics', 'Run AI image analysis.'),
    ('pharmacy_view', 'See medicines and stock', 'Pharmacy', 'Stock levels, expiry and what is available.'),
    ('pharmacy', 'Dispense prescriptions', 'Pharmacy', 'Issue signed prescriptions to patients.'),
    ('pharmacy_stock', 'Update stock', 'Pharmacy', 'Receive deliveries, adjust, write off, stock takes, purchase orders, issue requisitions, edit medicines.'),
    ('pharmacy_revise', 'Revise issuance', 'Pharmacy', 'Change line availability on prescriptions and supplier requests.'),
    ('billing', 'Billing', 'Finance', 'Create bills and take payments.'),
    ('finance_admin', 'Finance approvals', 'Finance', 'Discounts and voiding bills or payments.'),
    ('studio', 'Forms & approvals designer', 'Organisation', 'Design forms and approval flows.'),
    ('esign', 'E-sign', 'Organisation', 'Send and sign documents.'),
    ('programmes', 'Care programmes', 'Programmes', 'Work in the programmes you belong to: record visits, trace patients who missed, send reminders. Opens the records of patients enrolled in those programmes.'),
    ('programme_admin', 'Manage care programmes', 'Programmes', 'Create programmes, choose the care team and visit plan, switch AI on or off, see every programme.'),
    ('mortality', 'Record deaths and run the mortuary', 'Mortality', 'Pronounce and record a death (which archives the patient), inform the family, mortuary cabinets and release of the body.'),
    ('death_certify', 'Certify the cause of death', 'Mortality', 'Write and sign the WHO medical certificate of cause of death. Usually doctors.'),
    ('autopsy', 'Perform autopsies', 'Mortality', 'Pathology: autopsy reports, organ findings and clinicopathological correlation. Opens the records of deceased patients.'),
    ('mortality_review', 'Mortality reviews and study cases', 'Mortality', 'M&M reviews, mortality statistics and publishing anonymised study cases to the library. Opens the records of deceased patients.'),
    ('library', 'Clinical library', 'Knowledge', 'Anonymous summaries of diseases, treatments and outcomes at this hospital.'),
    ('drflow', 'Dr. Flow assistant', 'Knowledge', 'Ask Dr. Flow about medicines, tests, diseases and patients in your care.'),
    ('access_admin', 'Manage access and roles', 'Organisation', 'Create groups, choose capabilities, allocate staff and change roles.'),
]
CAP_KEYS = [c[0] for c in CAPABILITIES]
CAP_LABELS = {c[0]: c[1] for c in CAPABILITIES}

# Capabilities that are not module checks, by role. Module checks come from ROLES (see defaults()).
EXTRA = {
    'admin': set(CAP_KEYS),
    'doctor': {'patient_records', 'break_glass', 'operation_note', 'pharmacy_view', 'pharmacy_revise', 'library', 'drflow',
               'mortality', 'death_certify', 'mortality_review'},
    'nurse': {'patient_records', 'break_glass', 'pharmacy_view', 'library', 'drflow', 'mortality'},
    'pharmacy': {'pharmacy_view', 'pharmacy_stock', 'pharmacy_revise', 'library', 'drflow'},
    'reception': {'patient_records', 'all_patients', 'pharmacy_view'},
    'lab': {'patient_records', 'all_patients', 'pharmacy_view', 'autopsy', 'library'},
    'radiology': {'patient_records', 'all_patients', 'pharmacy_view'},
    'finance': {'patient_records', 'all_patients', 'pharmacy_view'},
    'management': {'patient_records', 'all_patients', 'pharmacy_view', 'library', 'programme_admin', 'mortality_review'},
}
# Standard groups an administrator can create in one click (then edit).
STANDARD_GROUPS = [
    ('Doctors', 'doctor', 'Care for patients who are visiting or admitted; library and Dr. Flow.'),
    ('Nurses', 'nurse', 'Care, bedside observations and theatre for current patients.'),
    ('Pharmacists', 'pharmacy', 'Dispensing, stock and Dr. Flow. No patient charts.'),
    ('Pharmacy assistants (view only)', None, 'See which medicines are available; cannot dispense or change stock.'),
    ('Reception', 'reception', 'Registration, check-in, queue and billing.'),
    ('Laboratory', 'lab', 'Laboratory work for any patient.'),
    ('Radiology', 'radiology', 'Imaging for any patient.'),
    ('Finance', 'finance', 'Bills and payments.'),
    ('Management', 'management', 'Reports and the board; no clinical editing.'),
    ('Hospital administrators', 'admin', 'Everything, including access and roles.'),
]
VIEW_ONLY_PHARMACY = {'all', 'pharmacy_view', 'library', 'drflow'}

EMERGENCY_HOURS = 4


def grace_hours():
    return getattr(settings, 'MEDFLOW_ACCESS_GRACE_HOURS', 12)


def role_defaults(role):
    """The capabilities a role has when its user is in no access group."""
    from .views import ROLES
    if not role:
        return set()
    caps = {k for k, roles in ROLES.items() if role in roles} | EXTRA.get(role, set())
    return {c for c in caps if c in CAP_KEYS or c in ROLES}


def caps(user):
    """Everything this user may do (cached on the user object for the request)."""
    if not getattr(user, 'is_authenticated', False):
        return set()
    cached = getattr(user, '_mf_caps', None)
    if cached is not None:
        return cached
    from .views import ROLES, role_of
    if user.is_superuser:
        out = set(CAP_KEYS) | set(ROLES)
    else:
        role = role_of(user)
        groups = list(user.access_groups.all()) if role else []
        if groups:
            out = set()
            for g in groups:
                out |= set(g.capabilities or [])
            out.add('all')                 # an active staff member can always sign in
        else:
            out = role_defaults(role)
    user._mf_caps = out
    return out


def has(user, cap):
    return cap in caps(user)


def require(request, cap, message='Your access does not include this.'):
    if not has(request.user, cap):
        raise PermissionDenied(message)


def using_groups(user):
    return bool(getattr(user, 'pk', None)) and user.access_groups.exists()


# ------------------------------------------------------------------ patient scope
def active_patient_ids():
    """Patients being cared for now: open visit, current admission or an operation in progress (with grace period)."""
    from .models import Admission, Encounter, SurgicalCase
    since = timezone.now() - timezone.timedelta(hours=grace_hours())
    ids = set(Encounter.objects.filter(Q(status='open') | Q(completed_at__gte=since)).values_list('patient_id', flat=True))
    ids |= set(Admission.objects.filter(Q(discharged_at__isnull=True) | Q(discharged_at__gte=since)).values_list('encounter__patient_id', flat=True))
    ids |= set(SurgicalCase.objects.filter(status__in=['scheduled', 'ready', 'in_theatre', 'operating', 'recovery']).values_list('patient_id', flat=True))
    return ids


def emergency_ids(request):
    grants = request.session.get('mf_glass', {}) if hasattr(request, 'session') else {}
    now = time.time()
    return {int(pid) for pid, until in grants.items() if until > now}


def all_access(user):
    return has(user, 'all_patients')


def visible_patient_ids(request):
    """None means every patient; otherwise the set of patient ids this user may open."""
    if all_access(request.user):
        return None
    if not has(request.user, 'patient_records'):
        return set()
    ids = active_patient_ids() | emergency_ids(request)
    if has(request.user, 'programmes'):              # a programme's care team follows its patients between visits
        from .programmes import care_team_patient_ids
        ids |= care_team_patient_ids(request.user)
    if has(request.user, 'mortality_review') or has(request.user, 'autopsy'):   # learning from deaths needs the whole record
        ids |= deceased_patient_ids()
    return ids


def deceased_patient_ids():
    from .models import Patient
    return set(Patient.objects.filter(deceased_at__isnull=False).values_list('pk', flat=True))


def can_mortality(user):
    """May open the mortality pages at all."""
    return any(has(user, c) for c in ('mortality', 'death_certify', 'autopsy', 'mortality_review'))


def can_see(request, patient_id):
    ids = visible_patient_ids(request)
    return ids is None or patient_id in ids


def filter_patients(request, qs, field='pk'):
    ids = visible_patient_ids(request)
    return qs if ids is None else qs.filter(**{f'{field}__in': ids})


def grant_emergency(request, patient, reason):
    from .models import AuditEvent, Notification
    from django.contrib.auth import get_user_model
    g = dict(request.session.get('mf_glass', {}))
    g[str(patient.pk)] = time.time() + EMERGENCY_HOURS * 3600
    request.session['mf_glass'] = g
    AuditEvent.objects.create(actor=request.user, action='break_glass', target=f'patient:{patient.pk}',
                              details={'reason': reason, 'hours': EMERGENCY_HOURS}, ip_address=request.META.get('REMOTE_ADDR'))
    who = request.user.get_full_name() or request.user.username
    admins = get_user_model().objects.filter(Q(is_superuser=True) | Q(hospital_staff__role='admin', hospital_staff__active=True)).exclude(pk=request.user.pk).distinct()
    for a in admins[:20]:
        Notification.objects.create(user=a, kind='access', title=f'Emergency access by {who}', body=f'{patient.mrn}: {reason}'[:400], url='/access/?tab=log')


# ------------------------------------------------------------------ which patient does a page belong to?
def _p(model, field='patient_id', key='pk'):
    def get(kw):
        from . import models as M
        return M.__dict__[model].objects.filter(pk=kw.get(key)).values_list(field, flat=True).first()
    return get


def _mrn(kw):
    from .models import Patient
    return Patient.objects.filter(mrn=kw.get('mrn')).values_list('pk', flat=True).first()


def _bed(kw):
    from .models import Admission
    return Admission.objects.filter(bed_id=kw.get('pk'), discharged_at__isnull=True).values_list('encounter__patient_id', flat=True).first()


ENC = 'encounter__patient_id'
PATIENT_PAGES = {
    'patient_chart': lambda kw: kw.get('pk'), 'allergy_new': lambda kw: kw.get('pk'), 'condition_new': lambda kw: kw.get('pk'),
    'patient_labs': lambda kw: kw.get('pk'), 'patient_story': lambda kw: kw.get('pk'), 'drflow_brief': lambda kw: kw.get('pk'),
    'patient_network_toggle': lambda kw: kw.get('pk'),   # the QR link (/p/<mrn>/) only redirects to the chart, which is checked
    'encounter_detail': _p('Encounter'), 'encounter_complete': _p('Encounter'), 'ai_context_preview': _p('Encounter'),
    'notes_save': _p('Encounter'), 'notes_ai_ask': _p('Encounter'), 'notes_ai_context': _p('Encounter'),
    'notes_ai_status': _p('ClinicalNoteAsk', ENC), 'notes_ai_rate': _p('ClinicalNoteAsk', ENC),
    'injury_assessment': _p('Encounter'), 'sense_exam': _p('Encounter'), 'invoice_for_encounter': _p('Encounter'),
    'lab_request_detail': _p('LabRequest', ENC), 'prescription_detail': _p('Prescription', ENC), 'prescription_edit': _p('Prescription', ENC),
    'imaging_detail': _p('ImagingOrder', ENC), 'imaging_file': _p('ImagingImage', 'order__encounter__patient_id'),
    'referral_detail': _p('Referral', ENC), 'referral_summary': _p('Referral', ENC),
    'theatre_case': _p('SurgicalCase'), 'theatre_edit': _p('SurgicalCase'), 'theatre_action': _p('SurgicalCase'),
    'theatre_preop': _p('SurgicalCase'), 'theatre_checklist': _p('SurgicalCase'), 'theatre_recovery': _p('SurgicalCase'), 'theatre_note': _p('SurgicalCase'),
    'bed_detail': _bed, 'submission_detail': _p('FormSubmission'),
    'programme_enrolment': _p('Enrolment'), 'programme_visit_record': _p('ProgrammeVisit', 'enrolment__patient_id'),
    'death_new': lambda kw: kw.get('pk'),
    'death_detail': _p('DeathRecord'), 'death_certificate': _p('DeathRecord'), 'death_print': _p('DeathRecord'),
    'death_family': _p('DeathRecord'), 'death_body': _p('DeathRecord'), 'death_revoke': _p('DeathRecord'),
    'autopsy_new': _p('DeathRecord'), 'death_review': _p('DeathRecord'), 'study_case_manage': _p('DeathRecord'),
    'autopsy_detail': _p('Autopsy', 'death__patient_id'), 'autopsy_act': _p('Autopsy', 'death__patient_id'),
    'autopsy_print': _p('Autopsy', 'death__patient_id'),
    'lab_request_print': _p('LabRequest', ENC), 'prescription_print': _p('Prescription', ENC), 'extlab_new': _p('LabRequest', ENC),
    'extlab_detail': _p('ExternalLabReferral', 'lab_request__encounter__patient_id'),
}
# Pages that are part of a job and open for that job even without patient-record access
JOB_PAGES = {'prescription_detail': 'pharmacy', 'lab_request_detail': 'lab', 'imaging_detail': 'imaging', 'imaging_file': 'imaging',
             'invoice_for_encounter': 'billing',
             # the mortuary looks after every body, whoever the clinical team was
             'death_detail': 'mortality', 'death_family': 'mortality', 'death_body': 'mortality', 'death_print': 'mortality',
             'death_certificate': 'death_certify', 'autopsy_detail': 'autopsy', 'autopsy_act': 'autopsy', 'autopsy_print': 'autopsy',
             'death_review': 'mortality_review', 'study_case_manage': 'mortality_review',
             # outside labs and printouts belong to the lab and pharmacy jobs too
             'lab_request_print': 'lab', 'extlab_new': 'lab', 'extlab_detail': 'lab', 'prescription_print': 'pharmacy'}


class PatientScopeMiddleware:
    """Blocks patient pages for patients outside the user's scope, whatever the view does. Lists are filtered in the views."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or user.is_superuser:
            return None
        name = getattr(getattr(request, 'resolver_match', None), 'url_name', None)
        if name not in PATIENT_PAGES:
            return None
        from .views import role_of
        if role_of(user) in (None, 'partner', 'specialist'):
            return None                               # partner and specialist portals have their own checks
        job = JOB_PAGES.get(name)
        if job and has(user, job):
            return None
        pid = PATIENT_PAGES[name](view_kwargs)
        if pid is None or can_see(request, int(pid)):
            return None
        from django.shortcuts import render
        from .models import Patient
        p = Patient.objects.filter(pk=pid).first()
        return render(request, 'hospital/access/out_of_scope.html', {'p': p, 'can_glass': has(user, 'break_glass') and p is not None,
                                                                     'next': request.get_full_path(), 'hours': EMERGENCY_HOURS,
                                                                     'records': has(user, 'patient_records')}, status=403)
