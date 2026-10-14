"""Operating theatres, the procedure catalogue and surgical cases (operations and other procedures).

* OperatingRoom   — a theatre or procedure room with its working session (used for the schedule and utilisation).
* ProcedureType   — the catalogue: name, specialty, usual duration, usual anaesthetic, whether a side is needed, price.
* SurgicalCase    — one operation or procedure for a visit, from request → schedule → pre-op → WHO Sign in → Time out →
                    Sign out → recovery → back to the ward. The rules for each step live in hospital/theatre.py.

The JSON fields (pre-op checks, WHO checklist, recovery observations) are always cleaned by hospital/theatre.py.
"""
from django.conf import settings
from django.db import models

from .models import Encounter, Patient, Tracked

SPECIALTIES = [('general', 'General surgery'), ('orthopaedic', 'Orthopaedics & trauma'), ('obgyn', 'Obstetrics & gynaecology'),
               ('eye', 'Ophthalmology (eye)'), ('ent', 'ENT (ear, nose & throat)'), ('urology', 'Urology'), ('paediatric', 'Paediatric surgery'),
               ('plastic', 'Plastics & burns'), ('dental', 'Dental & maxillofacial'), ('other', 'Other')]
ANAESTHESIA = [('general', 'General anaesthetic'), ('spinal', 'Spinal'), ('epidural', 'Epidural'), ('regional', 'Regional nerve block'),
               ('local', 'Local anaesthetic'), ('sedation', 'Sedation')]


class OperatingRoom(Tracked):
    KIND = [('main', 'Main theatre'), ('obstetric', 'Obstetric theatre'), ('eye_ent', 'Eye & ENT theatre'), ('minor', 'Minor procedures room'),
            ('endoscopy', 'Endoscopy suite'), ('cath', 'Cath lab')]
    name = models.CharField(max_length=80, unique=True)
    kind = models.CharField(max_length=12, choices=KIND, default='main')
    active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    session_start = models.TimeField(default='08:00', help_text='Start of the routine operating session')
    session_end = models.TimeField(default='17:00', help_text='End of the routine operating session')
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class ProcedureType(Tracked):
    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    specialty = models.CharField(max_length=12, choices=SPECIALTIES, default='general')
    minor = models.BooleanField(default=False, help_text='Minor procedure (can be done in a procedure room)')
    default_minutes = models.PositiveSmallIntegerField(default=60)
    default_anaesthesia = models.CharField(max_length=10, choices=ANAESTHESIA, default='general')
    needs_side = models.BooleanField(default=False, help_text='Left or right must be stated and the site marked')
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text='Surgeon / procedure fee in dalasi')
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['specialty', 'name']

    def __str__(self):
        return self.name


class SurgicalCase(Tracked):
    STATUS = [('requested', 'Requested'), ('scheduled', 'Scheduled'), ('ready', 'Ready for theatre'), ('in_theatre', 'In theatre · anaesthesia'),
              ('operating', 'Operating'), ('recovery', 'In recovery'), ('completed', 'Completed'), ('postponed', 'Postponed'), ('cancelled', 'Cancelled')]
    URGENCY = [('immediate', 'Immediate · life, limb or organ, within minutes'), ('urgent', 'Urgent · within hours'),
               ('expedited', 'Expedited · within days'), ('elective', 'Elective · planned')]
    SIDE = [('', 'Not applicable'), ('left', 'Left'), ('right', 'Right'), ('bilateral', 'Both sides')]
    WOUND = [('', '—'), ('clean', 'Clean'), ('clean_contaminated', 'Clean-contaminated'), ('contaminated', 'Contaminated'), ('dirty', 'Dirty / infected')]
    DISCHARGE_TO = [('', '—'), ('ward', 'Ward'), ('home', 'Home (day case)'), ('icu', 'Intensive care'), ('hdu', 'High dependency')]

    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name='operations')
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='operations', editable=False)
    procedure_type = models.ForeignKey(ProcedureType, null=True, blank=True, on_delete=models.SET_NULL, related_name='cases',
                                       verbose_name='Procedure (catalogue)')
    procedure = models.CharField(max_length=200, blank=True, help_text='Leave empty to use the catalogue name')
    specialty = models.CharField(max_length=12, choices=SPECIALTIES, default='general')
    side = models.CharField(max_length=10, choices=SIDE, blank=True)
    site = models.CharField(max_length=120, blank=True, help_text='e.g. Right inguinal region, Left eye')
    indication = models.TextField(blank=True, help_text='Diagnosis / reason for the operation')
    urgency = models.CharField(max_length=10, choices=URGENCY, default='elective')
    status = models.CharField(max_length=12, choices=STATUS, default='requested', db_index=True)

    room = models.ForeignKey(OperatingRoom, null=True, blank=True, on_delete=models.PROTECT, related_name='cases')
    scheduled_start = models.DateTimeField(null=True, blank=True, db_index=True)
    est_minutes = models.PositiveSmallIntegerField(default=60, verbose_name='Expected duration (minutes)')
    surgeon = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='cases_as_surgeon')
    assistant = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    anaesthetist = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='cases_as_anaesthetist')
    scrub_nurse = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    anaesthesia = models.CharField(max_length=10, choices=ANAESTHESIA, default='general')
    asa = models.PositiveSmallIntegerField(null=True, blank=True, choices=[(i, f'ASA {i}') for i in range(1, 7)], verbose_name='ASA grade')
    blood_units = models.PositiveSmallIntegerField(default=0, verbose_name='Blood to cross-match (units)')

    preop = models.JSONField(default=dict, blank=True, help_text='Ward pre-operative checks; cleaned by hospital.theatre')
    fasting_since = models.DateTimeField(null=True, blank=True, verbose_name='Last food')
    clear_fluids_since = models.DateTimeField(null=True, blank=True, verbose_name='Last clear fluids')
    checklist = models.JSONField(default=dict, blank=True, help_text='WHO Surgical Safety Checklist; cleaned by hospital.theatre')

    in_room_at = models.DateTimeField(null=True, blank=True)
    anaesthesia_at = models.DateTimeField(null=True, blank=True)
    incision_at = models.DateTimeField(null=True, blank=True)
    closure_at = models.DateTimeField(null=True, blank=True)
    out_room_at = models.DateTimeField(null=True, blank=True)
    recovery_out_at = models.DateTimeField(null=True, blank=True)

    procedure_performed = models.CharField(max_length=300, blank=True)
    findings = models.TextField(blank=True)
    blood_loss_ml = models.PositiveIntegerField(null=True, blank=True)
    wound_class = models.CharField(max_length=20, choices=WOUND, blank=True)
    specimens = models.CharField(max_length=300, blank=True)
    implants = models.CharField(max_length=300, blank=True)
    drains = models.CharField(max_length=200, blank=True)
    closure = models.CharField(max_length=200, blank=True)
    complications = models.TextField(blank=True)
    post_op_plan = models.TextField(blank=True)
    note_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    note_at = models.DateTimeField(null=True, blank=True)

    recovery = models.JSONField(default=list, blank=True, help_text='Recovery observations with Aldrete score; cleaned by hospital.theatre')
    discharge_to = models.CharField(max_length=6, choices=DISCHARGE_TO, blank=True)
    discharge_override = models.CharField(max_length=200, blank=True, help_text='Why the patient left recovery with an Aldrete score below 9')
    cancel_reason = models.CharField(max_length=200, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['scheduled_start', 'created_at']

    def save(self, *a, **kw):
        self.patient_id = self.encounter.patient_id
        if not self.procedure and self.procedure_type_id:
            self.procedure = self.procedure_type.name
        super().save(*a, **kw)

    @property
    def number(self):
        return f'OP-{self.pk:06d}'

    @property
    def title(self):
        side = {'left': ' (left)', 'right': ' (right)', 'bilateral': ' (both sides)'}.get(self.side, '')
        return f'{self.procedure or "Procedure"}{side}'

    @property
    def scheduled_end(self):
        from datetime import timedelta
        return self.scheduled_start + timedelta(minutes=self.est_minutes) if self.scheduled_start else None

    def __str__(self):
        return f'{self.number} · {self.title} · {self.patient.full_name}' if self.pk else self.title
