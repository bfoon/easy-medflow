"""Death, the mortuary, autopsy and learning from every death (see hospital/mortality.py).

* **DeathRecord** — pronouncement, the WHO medical certificate of cause of death (MCCD), the family, the body's journey
  through the mortuary and its release. Recording a death archives the patient: open work is closed, reminders stop and
  the patient leaves every active list. Nothing in the medical record is deleted.
* **Autopsy** — hospital, limited, minimally invasive, medico-legal or verbal autopsy, with an organ-by-organ record,
  the pathological cause of death and a clinicopathological correlation (Goldman class) against what the team believed.
* **MortalityReview** — the morbidity & mortality meeting: was it preventable, which of the three delays, what to change.
* **StudyCase** — an anonymised, frozen copy of the whole story for the clinical library, published only after an
  anonymisation check and never when the family declined teaching use.
"""
import secrets

from django.conf import settings
from django.db import models
from django.db.models import Q

from .models import BODY_SYSTEMS, Tracked


def _token():
    return secrets.token_urlsafe(18)


class DeathRecord(Tracked):
    PLACE = [('ward', 'Ward'), ('icu', 'Intensive care'), ('emergency', 'Emergency department'), ('theatre', 'Operating theatre'),
             ('maternity', 'Labour & maternity'), ('dead_on_arrival', 'Dead on arrival'), ('community', 'Home / community (reported)'),
             ('other', 'Other')]
    MANNER = [('natural', 'Natural disease'), ('accident', 'Accident'), ('self_harm', 'Intentional self-harm'), ('assault', 'Assault'),
              ('legal', 'Legal intervention / war'), ('pending', 'Pending investigation'), ('undetermined', 'Could not be determined')]
    MATERNAL = [('', 'Not applicable'), ('no', 'Not pregnant within the past year'), ('pregnant', 'Pregnant at the time of death'),
                ('within_42d', 'Within 42 days of the end of a pregnancy'), ('43d_1y', '43 days to 1 year after a pregnancy'),
                ('unknown', 'Unknown')]
    STATUS = [('pronounced', 'Pronounced'), ('certified', 'Certified'), ('released', 'Body released'), ('closed', 'Closed'),
              ('revoked', 'Entered in error')]
    BODY = [('ward', 'Still on the ward'), ('mortuary', 'In the mortuary'), ('autopsy', 'In pathology for autopsy'), ('released', 'Released')]
    CONSENT = [('not_asked', 'Not asked yet'), ('granted', 'Family agreed to anonymous teaching use'),
               ('declined', 'Family declined teaching use'), ('policy', 'Anonymous use under hospital policy')]
    VERIFY_CHECKS = [('no_pulse', 'No central pulse'), ('no_heart_sounds', 'No heart sounds'), ('no_breath', 'No breathing or breath sounds'),
                     ('pupils_fixed', 'Pupils fixed and dilated, no light reflex'), ('no_response', 'No response to pain'),
                     ('five_minutes', 'Observed for at least 5 minutes')]

    patient = models.ForeignKey('Patient', on_delete=models.PROTECT, related_name='deaths')
    encounter = models.ForeignKey('Encounter', null=True, blank=True, on_delete=models.SET_NULL, related_name='deaths')
    admission = models.ForeignKey('Admission', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    status = models.CharField(max_length=12, choices=STATUS, default='pronounced', db_index=True)

    # pronouncement / verification of death
    died_at = models.DateTimeField()
    time_estimated = models.BooleanField(default=False, help_text='The time of death is an estimate')
    place = models.CharField(max_length=16, choices=PLACE, default='ward')
    place_detail = models.CharField(max_length=160, blank=True, help_text='Ward and bed, or where it happened')
    circumstances = models.TextField(blank=True, help_text='What happened in the last hours: events, resuscitation, who was present')
    resuscitation = models.CharField(max_length=12, blank=True, choices=[('', '—'), ('attempted', 'CPR attempted'), ('dnacpr', 'Not attempted · DNACPR in place'),
                                                                     ('futile', 'Not attempted · clearly futile'), ('none', 'Not attempted')])
    verification = models.JSONField(default=dict, blank=True, help_text='Signs confirmed at verification (keys from VERIFY_CHECKS)')
    pronounced_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    pronounced_at = models.DateTimeField(null=True, blank=True)

    # WHO medical certificate of cause of death: Part I (a leads to death, d is the underlying cause) and Part II
    cause_a = models.CharField(max_length=200, blank=True, verbose_name='I(a) Disease or condition directly leading to death')
    interval_a = models.CharField(max_length=40, blank=True)
    cause_b = models.CharField(max_length=200, blank=True, verbose_name='I(b) Due to')
    interval_b = models.CharField(max_length=40, blank=True)
    cause_c = models.CharField(max_length=200, blank=True, verbose_name='I(c) Due to')
    interval_c = models.CharField(max_length=40, blank=True)
    cause_d = models.CharField(max_length=200, blank=True, verbose_name='I(d) Due to')
    interval_d = models.CharField(max_length=40, blank=True)
    contributing = models.TextField(blank=True, verbose_name='Part II Other significant conditions contributing to death')
    icd_underlying = models.CharField(max_length=12, blank=True, verbose_name='ICD-10/11 code of the underlying cause')
    manner = models.CharField(max_length=12, choices=MANNER, default='natural')
    maternal = models.CharField(max_length=12, choices=MATERNAL, blank=True)
    surgery_4w = models.BooleanField(default=False, verbose_name='Operation within 4 weeks before death')
    surgery_detail = models.CharField(max_length=200, blank=True)
    legal_referral = models.CharField(max_length=160, blank=True, help_text='Police, coroner or magistrate informed (required unless natural)')
    certified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    certified_at = models.DateTimeField(null=True, blank=True)
    verify_token = models.CharField(max_length=40, unique=True, default=_token, editable=False)
    content_hash = models.CharField(max_length=64, blank=True, editable=False, help_text='SHA-256 of the certificate as signed')

    # the family
    nok_name = models.CharField(max_length=160, blank=True, verbose_name='Next of kin')
    nok_relation = models.CharField(max_length=60, blank=True)
    nok_phone = models.CharField(max_length=40, blank=True)
    nok_informed_at = models.DateTimeField(null=True, blank=True)
    nok_informed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    nok_how = models.CharField(max_length=12, blank=True, choices=[('', '—'), ('in_person', 'In person'), ('phone', 'By phone'), ('present', 'Present at the death')])
    family_notes = models.TextField(blank=True, help_text='Wishes, faith and burial customs, questions the family asked')
    rapid_release = models.BooleanField(default=False, help_text='The family asks for release as soon as possible (e.g. same-day burial for faith reasons)')
    teaching_consent = models.CharField(max_length=10, choices=CONSENT, default='not_asked')

    # the body
    body_status = models.CharField(max_length=10, choices=BODY, default='ward', db_index=True)
    mortuary_slot = models.CharField(max_length=30, blank=True, help_text='Cabinet / drawer, e.g. M-04')
    mortuary_in_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    released_to = models.CharField(max_length=160, blank=True)
    released_relation = models.CharField(max_length=60, blank=True)
    released_id_doc = models.CharField(max_length=80, blank=True, verbose_name='ID shown by the collector')
    released_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    release_notes = models.CharField(max_length=300, blank=True, help_text='Funeral home, vehicle, belongings handed over')

    # archiving trail: everything changed when the death was recorded, so an error can be undone exactly
    archive_log = models.JSONField(default=list, blank=True, editable=False)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    revoked_reason = models.TextField(blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-died_at']
        constraints = [models.UniqueConstraint(fields=['patient'], condition=~Q(status='revoked'), name='one_live_death_per_patient')]

    def __str__(self):
        return f'{self.number} · {self.patient}'

    @property
    def number(self):
        return f'DC-{self.died_at:%Y}-{self.pk:06d}' if self.pk else 'DC-new'

    @property
    def chain(self):
        """Part I as (line, condition, interval) for the filled lines, from the immediate cause down."""
        return [(k.upper(), getattr(self, f'cause_{k}'), getattr(self, f'interval_{k}')) for k in 'abcd' if getattr(self, f'cause_{k}')]

    @property
    def underlying_cause(self):
        """The lowest filled line of Part I is the underlying cause (WHO rule)."""
        c = self.chain
        return c[-1][1] if c else ''

    @property
    def certified(self):
        return bool(self.certified_at)

    @property
    def live(self):
        return self.status != 'revoked'

    @property
    def hours_in_hospital(self):
        """From arrival (the visit that ended in death) to death."""
        if not self.encounter_id:
            return None
        return round((self.died_at - self.encounter.created_at).total_seconds() / 3600, 1)

    @property
    def within_24h(self):
        h = self.hours_in_hospital
        return h is not None and 0 <= h < 24

    @property
    def is_maternal(self):
        return self.maternal in ('pregnant', 'within_42d')

    @property
    def is_perinatal(self):
        p = self.patient
        return bool(p.dob) and (self.died_at.date() - p.dob).days < 7

    @property
    def unnatural(self):
        return self.manner not in ('natural', '')

    @property
    def days_in_mortuary(self):
        from django.utils import timezone
        if not self.mortuary_in_at:
            return None
        end = self.released_at or timezone.now()
        return max(0, (end - self.mortuary_in_at).days)


class Autopsy(Tracked):
    KIND = [('clinical', 'Hospital (clinical) autopsy'), ('limited', 'Limited autopsy · selected organs'),
            ('minimally_invasive', 'Minimally invasive · needle and imaging'), ('medicolegal', 'Medico-legal · police or coroner'),
            ('verbal', 'Verbal autopsy · structured interview with the family')]
    STATUS = [('requested', 'Requested'), ('consented', 'Consent given'), ('declined', 'Family declined'), ('scheduled', 'Scheduled'),
              ('in_progress', 'In progress'), ('preliminary', 'Preliminary report'), ('final', 'Final · signed'), ('cancelled', 'Cancelled')]
    GOLDMAN = [('', 'Not yet assessed'),
               ('I', 'Class I · major missed diagnosis; treatment could have changed the outcome'),
               ('II', 'Class II · major missed diagnosis; would not have changed the outcome'),
               ('III', 'Class III · minor missed diagnosis related to the terminal illness'),
               ('IV', 'Class IV · other minor missed diagnoses'),
               ('V', 'Class V · clinical and autopsy diagnoses agree')]

    death = models.ForeignKey(DeathRecord, on_delete=models.PROTECT, related_name='autopsies')
    kind = models.CharField(max_length=20, choices=KIND, default='clinical')
    status = models.CharField(max_length=12, choices=STATUS, default='requested', db_index=True)
    questions = models.TextField(help_text='What the clinical team wants answered')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    clinical_diagnosis = models.TextField(blank=True, help_text='What the team believed at the time of death (copied when requested)')

    consent_name = models.CharField(max_length=160, blank=True)
    consent_relation = models.CharField(max_length=60, blank=True)
    consent_at = models.DateTimeField(null=True, blank=True)
    consent_scope = models.CharField(max_length=300, blank=True, help_text='Full, or the organs and procedures agreed')
    organ_retention = models.BooleanField(default=False, help_text='The family agreed to organs or tissue being kept for further study')
    consent_witness = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    legal_authority = models.CharField(max_length=160, blank=True, help_text='Medico-legal: who ordered it and the reference')

    pathologist = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='autopsies')
    scheduled_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    external_exam = models.TextField(blank=True, help_text='Build, nutrition, marks, injuries, medical devices, signs of treatment')
    organs = models.JSONField(default=dict, blank=True, help_text='{body system: {weight_g, finding, abnormal}} — keys from BODY_SYSTEMS')
    interview = models.TextField(blank=True, help_text='Verbal autopsy: the family’s account of the illness')
    histology = models.TextField(blank=True)
    microbiology = models.TextField(blank=True)
    toxicology = models.TextField(blank=True)
    anatomical_diagnosis = models.TextField(blank=True, help_text='Final pathological diagnoses, most important first')
    cause_a = models.CharField(max_length=200, blank=True)
    cause_b = models.CharField(max_length=200, blank=True)
    cause_c = models.CharField(max_length=200, blank=True)
    cause_d = models.CharField(max_length=200, blank=True)
    contributing = models.TextField(blank=True)
    goldman = models.CharField(max_length=3, choices=GOLDMAN, blank=True, verbose_name='Clinicopathological correlation')
    correlation_notes = models.TextField(blank=True, help_text='What the clinical team missed or got right, and why')
    learning_points = models.TextField(blank=True, help_text='One per line — these appear in the clinical library')

    signed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    signed_at = models.DateTimeField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, editable=False)
    addenda = models.JSONField(default=list, blank=True, editable=False, help_text='Later additions to a signed report')

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'autopsies'

    def __str__(self):
        return f'{self.number} · {self.death.patient}'

    @property
    def number(self):
        return f'AU-{self.pk:06d}' if self.pk else 'AU-new'

    @property
    def chain(self):
        return [(k.upper(), getattr(self, f'cause_{k}')) for k in 'abcd' if getattr(self, f'cause_{k}')]

    @property
    def underlying_cause(self):
        c = self.chain
        return c[-1][1] if c else ''

    @property
    def signed(self):
        return self.status == 'final'

    @property
    def open(self):
        return self.status not in ('final', 'cancelled', 'declined')

    @property
    def organ_rows(self):
        """Every body system with what was recorded for it (empty dict if not examined)."""
        return [{'key': k, 'label': label, **(self.organs or {}).get(k, {})} for k, label in BODY_SYSTEMS]

    @property
    def learning_list(self):
        return [x.strip(' -•\t') for x in (self.learning_points or '').splitlines() if x.strip(' -•\t')]


class MortalityReview(Tracked):
    PREVENTABLE = [('', 'Not yet decided'), ('not', 'Not preventable'), ('possibly', 'Possibly preventable'),
                   ('probably', 'Probably preventable'), ('undetermined', 'Cannot be determined')]
    DELAYS = [('seeking', 'Delay 1 · deciding to seek care'), ('reaching', 'Delay 2 · reaching the facility'),
              ('receiving', 'Delay 3 · receiving the right care here')]
    FACTORS = [('late_presentation', 'Late presentation'), ('diagnosis', 'Delayed or missed diagnosis'), ('treatment', 'Treatment delayed or not given'),
               ('monitoring', 'Gaps in monitoring / observations'), ('escalation', 'Deterioration not escalated'), ('guideline', 'Guideline not followed'),
               ('staffing', 'Staff shortage'), ('skills', 'Skills or training'), ('medicine', 'Medicine out of stock'), ('blood', 'Blood not available'),
               ('equipment', 'Equipment missing or broken'), ('oxygen', 'Oxygen not available'), ('lab', 'Laboratory delay'), ('imaging', 'Imaging delay'),
               ('referral', 'Referral or transport'), ('theatre', 'Theatre access'), ('communication', 'Communication / handover'),
               ('documentation', 'Documentation'), ('cost', 'Cost to the family'), ('patient', 'Patient or family decision')]

    death = models.OneToOneField(DeathRecord, on_delete=models.PROTECT, related_name='review')
    status = models.CharField(max_length=8, choices=[('draft', 'Draft'), ('final', 'Final')], default='draft')
    meeting_date = models.DateField(null=True, blank=True)
    chair = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    attendees = models.CharField(max_length=400, blank=True, help_text='Roles present, not names, e.g. 2 consultants, ward nurse, pharmacist')
    summary = models.TextField(blank=True, help_text='The case in a few lines, without names')
    preventability = models.CharField(max_length=12, choices=PREVENTABLE, blank=True)
    delays = models.JSONField(default=list, blank=True)
    factors = models.JSONField(default=list, blank=True)
    went_well = models.TextField(blank=True, help_text='What was done well')
    lessons = models.TextField(blank=True, help_text='One per line')
    actions = models.JSONField(default=list, blank=True, help_text='[{text, owner, due, done}]')
    finalised_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    finalised_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'Review of {self.death.number}'

    @property
    def lesson_list(self):
        return [x.strip(' -•\t') for x in (self.lessons or '').splitlines() if x.strip(' -•\t')]

    def factor_labels(self):
        d = dict(self.FACTORS)
        return [d[f] for f in self.factors if f in d]

    def delay_labels(self):
        d = dict(self.DELAYS)
        return [d[f] for f in self.delays if f in d]


class StudyCase(Tracked):
    STATUS = [('draft', 'Draft · awaiting anonymisation check'), ('published', 'Published in the library'), ('withdrawn', 'Withdrawn')]
    death = models.OneToOneField(DeathRecord, on_delete=models.PROTECT, related_name='study_case')
    code = models.CharField(max_length=20, unique=True, editable=False)
    title = models.CharField(max_length=200)
    slug = models.CharField(max_length=80, blank=True, db_index=True, help_text='Library disease this case belongs to')
    status = models.CharField(max_length=10, choices=STATUS, default='draft', db_index=True)
    snapshot = models.JSONField(default=dict, blank=True, help_text='Anonymised copy of the whole record; frozen when published')
    snapshot_at = models.DateTimeField(null=True, blank=True)
    teaching_points = models.TextField(blank=True, help_text='One per line: what every clinician should take from this case')
    question = models.CharField(max_length=240, blank=True, help_text='Asked before the answer is revealed in case-conference mode')
    checklist = models.JSONField(default=list, blank=True, help_text='Anonymisation checks confirmed at publication')
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    published_at = models.DateTimeField(null=True, blank=True)
    views = models.PositiveIntegerField(default=0)
    withdrawn_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['-published_at', '-created_at']

    def __str__(self):
        return f'{self.code} · {self.title}'

    @property
    def teaching_list(self):
        return [x.strip(' -•\t') for x in (self.teaching_points or '').splitlines() if x.strip(' -•\t')]
