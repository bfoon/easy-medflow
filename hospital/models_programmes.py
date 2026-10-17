"""Care programmes: long-term treatment and prevention programmes (HIV treatment, hypertension, diabetes, TB,
childhood immunisation, antenatal care…) with a care team, enrolled patients, a visit plan, missed-visit alerts,
defaulter tracing and optional, de-identified AI help. The logic is in programmes.py."""
from django.conf import settings
from django.db import models
from django.utils import timezone

from .models import Tracked


class Programme(Tracked):
    KIND = [('hiv', 'HIV treatment (ART)'), ('hypertension', 'Hypertension'), ('diabetes', 'Diabetes'), ('tb', 'Tuberculosis (DOTS)'),
            ('immunisation', 'Childhood immunisation'), ('antenatal', 'Antenatal care'), ('nutrition', 'Child nutrition'),
            ('mental_health', 'Mental health'), ('sickle_cell', 'Sickle cell disease'), ('family_planning', 'Family planning'), ('other', 'Other')]
    ANCHOR = [('enrolment', 'The day the patient is enrolled'), ('dob', "The patient's date of birth"), ('lmp', 'First day of the last menstrual period'),
              ('start', 'A start date chosen at enrolment (e.g. treatment start)')]
    name = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=20, choices=KIND, default='other')
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, default='#0F7B78')
    icon = models.CharField(max_length=40, default='heart-pulse', help_text='Bootstrap icon name, e.g. heart-pulse, shield-plus, droplet')
    active = models.BooleanField(default=True)
    lead = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='programmes_led',
                             help_text='Hears about escalations and patients lost to follow-up')
    team = models.ManyToManyField(settings.AUTH_USER_MODEL, through='ProgrammeMember', related_name='programmes', blank=True)
    anchor = models.CharField(max_length=10, choices=ANCHOR, default='enrolment', help_text='The visit plan is counted from this day')
    measures = models.JSONField(default=list, blank=True, help_text='What is recorded at each visit (keys from programmes.MEASURES)')
    # follow-up rules
    reminder_days = models.PositiveSmallIntegerField(default=2, help_text='Remind the patient this many days before a visit (0 = on the day)')
    grace_days = models.PositiveSmallIntegerField(default=3, help_text='A visit counts as missed after this many days')
    escalate_days = models.PositiveSmallIntegerField(default=7, help_text='Tell the programme lead when a missed visit is still not traced after this many days')
    ltfu_days = models.PositiveSmallIntegerField(default=28, help_text='Lost to follow-up after this many days without a visit (WHO uses 28 days for HIV)')
    discreet = models.BooleanField(default=False, help_text="Reminders do not name the programme or condition (recommended for HIV, TB, mental health)")
    reminder_text = models.CharField(max_length=320, blank=True, help_text='Optional. Placeholders: {name} {date} {clinic} {programme}')
    missed_text = models.CharField(max_length=320, blank=True, help_text='Optional. Sent after a missed visit. Same placeholders.')
    # AI, per programme (and only when the hospital has AI configured)
    ai_enabled = models.BooleanField(default=False, verbose_name='Dr. Flow AI for this programme',
                                     help_text='Only de-identified data is ever sent: no names, numbers, phones, addresses, dates or notes')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['-active', 'name']

    def __str__(self):
        return self.name


class ProgrammeMember(Tracked):
    ROLE = [('lead', 'Lead'), ('doctor', 'Doctor / clinician'), ('nurse', 'Nurse / midwife'), ('counsellor', 'Counsellor / adherence'),
            ('pharmacist', 'Pharmacist'), ('community', 'Community health worker'), ('data', 'Data officer')]
    programme = models.ForeignKey(Programme, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='programme_memberships')
    role = models.CharField(max_length=12, choices=ROLE, default='nurse')
    notify = models.BooleanField(default=True, help_text='Hears about missed visits of every patient in the programme (not only their own)')

    class Meta:
        unique_together = [('programme', 'user')]
        ordering = ['role', 'user__first_name']

    def __str__(self):
        return f'{self.user} · {self.get_role_display()} · {self.programme}'


class ProgrammeStep(Tracked):
    """One line of the visit plan: a refill, review, vaccine visit, test or counselling session."""
    KIND = [('refill', 'Medicine refill'), ('review', 'Clinical review'), ('vaccine', 'Vaccination'), ('test', 'Laboratory test'),
            ('counselling', 'Counselling'), ('visit', 'Visit')]
    programme = models.ForeignKey(Programme, on_delete=models.CASCADE, related_name='steps')
    order = models.PositiveSmallIntegerField(default=0)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=12, choices=KIND, default='visit')
    offset_days = models.PositiveIntegerField(default=0, help_text='Days after the anchor day (enrolment, birth, LMP or start)')
    repeat_days = models.PositiveIntegerField(null=True, blank=True, help_text='Repeat every this many days (blank = once)')
    until_days = models.PositiveIntegerField(null=True, blank=True, help_text='Stop repeating this many days after the anchor (blank = for as long as enrolled)')
    items = models.JSONField(default=list, blank=True, help_text='Vaccines or tasks done at this visit, e.g. ["BCG", "OPV 0"]')
    medicine = models.CharField(max_length=160, blank=True, help_text='Medicine given at a refill, e.g. TDF/3TC/DTG')
    days_supply = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Days of medicine given at a refill; the next refill is due when it runs out')

    class Meta:
        ordering = ['order', 'offset_days']

    def __str__(self):
        return f'{self.programme} · {self.name}'


class Enrolment(Tracked):
    STATUS = [('active', 'Active'), ('paused', 'Paused'), ('lost', 'Lost to follow-up'), ('completed', 'Completed'), ('transferred', 'Transferred out'),
              ('died', 'Died'), ('withdrawn', 'Withdrawn')]
    CHANNEL = [('sms', 'SMS'), ('whatsapp', 'WhatsApp'), ('email', 'Email'), ('call', 'Phone call by staff'), ('none', 'No reminders')]
    programme = models.ForeignKey(Programme, on_delete=models.CASCADE, related_name='enrolments')
    patient = models.ForeignKey('Patient', on_delete=models.PROTECT, related_name='enrolments')
    status = models.CharField(max_length=12, choices=STATUS, default='active')
    enrolled_on = models.DateField(default=timezone.localdate)
    anchor_date = models.DateField(null=True, blank=True, help_text='Birth, LMP or start date when the plan counts from it')
    clinician = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='programme_patients',
                                  verbose_name='Responsible doctor')
    nurse = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='programme_patients_nursed',
                              verbose_name='Responsible nurse')
    channel = models.CharField(max_length=10, choices=CHANNEL, default='sms', verbose_name='Reminders by')
    consent_reminders = models.BooleanField(default=True, verbose_name='Patient (or carer) agrees to reminders')
    contact_phone = models.CharField(max_length=40, blank=True, help_text="Leave blank to use the patient's phone (e.g. a carer's number for a child)")
    notes = models.TextField(blank=True, help_text='Private to the care team. Never sent to the AI.')
    ended_on = models.DateField(null=True, blank=True)
    lost_since = models.DateField(null=True, blank=True)
    enrolled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['programme', 'patient'], condition=models.Q(status__in=['active', 'paused', 'lost']),
                                               name='one_open_enrolment_per_programme')]

    def __str__(self):
        return f'{self.patient} in {self.programme}'

    @property
    def open(self):
        return self.status in ('active', 'paused', 'lost')

    @property
    def start(self):
        return self.anchor_date or self.enrolled_on


class ProgrammeVisit(Tracked):
    """A planned visit (appointment) and what happened at it."""
    STATUS = [('scheduled', 'Scheduled'), ('reminded', 'Reminded'), ('attended', 'Attended'), ('missed', 'Missed'), ('cancelled', 'Cancelled')]
    enrolment = models.ForeignKey(Enrolment, on_delete=models.CASCADE, related_name='visits')
    step = models.ForeignKey(ProgrammeStep, null=True, blank=True, on_delete=models.SET_NULL, related_name='visits')
    title = models.CharField(max_length=120)
    kind = models.CharField(max_length=12, choices=ProgrammeStep.KIND, default='visit')
    due = models.DateField(db_index=True)
    status = models.CharField(max_length=10, choices=STATUS, default='scheduled', db_index=True)
    attended_on = models.DateField(null=True, blank=True)
    items_planned = models.JSONField(default=list, blank=True)
    items_done = models.JSONField(default=list, blank=True)
    measures = models.JSONField(default=dict, blank=True)
    days_supply = models.PositiveSmallIntegerField(null=True, blank=True)
    note = models.TextField(blank=True, help_text='Private to the care team. Never sent to the AI.')
    encounter = models.ForeignKey('Encounter', null=True, blank=True, on_delete=models.SET_NULL, related_name='programme_visits')
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reminded_at = models.DateTimeField(null=True, blank=True)
    missed_at = models.DateTimeField(null=True, blank=True)
    missed_message_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    rescheduled_from = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['due', 'pk']
        indexes = [models.Index(fields=['status', 'due'])]

    def __str__(self):
        return f'{self.title} due {self.due}'

    @property
    def measure_list(self):
        from .programmes import MEASURES
        return [(MEASURES[k][0] if k in MEASURES else k, v, MEASURES[k][1] if k in MEASURES else '') for k, v in (self.measures or {}).items()]

    @property
    def days_late(self):
        return (timezone.localdate() - self.due).days if self.status in ('scheduled', 'reminded', 'missed') else 0


class TracingAttempt(Tracked):
    """Following up a patient who missed a visit: a call, a message or a home visit, and what came of it."""
    METHOD = [('call', 'Phone call'), ('sms', 'SMS'), ('whatsapp', 'WhatsApp'), ('home', 'Home visit'), ('community', 'Community health worker')]
    OUTCOME = [('reached', 'Reached, will come'), ('rescheduled', 'Reached, new date agreed'), ('no_answer', 'No answer'),
               ('wrong_number', 'Wrong or switched-off number'), ('moved', 'Moved away / transferred'), ('refused', 'Does not want to continue'),
               ('died', 'Reported to have died'), ('other', 'Other')]
    enrolment = models.ForeignKey(Enrolment, on_delete=models.CASCADE, related_name='tracing')
    visit = models.ForeignKey(ProgrammeVisit, null=True, blank=True, on_delete=models.SET_NULL, related_name='tracing')
    method = models.CharField(max_length=10, choices=METHOD, default='call')
    outcome = models.CharField(max_length=14, choices=OUTCOME)
    reason = models.CharField(max_length=40, blank=True, help_text='Why the visit was missed (coded, see programmes.MISS_REASONS)')
    note = models.CharField(max_length=300, blank=True, help_text='Private to the care team. Never sent to the AI.')
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['-created_at']

    @property
    def reason_label(self):
        from .programmes import MISS_REASON_LABEL
        return MISS_REASON_LABEL.get(self.reason, self.reason)


class ProgrammeMessage(Tracked):
    """A reminder or missed-visit message to a patient: sent automatically (email, SMS gateway) or waiting in the
    outbox for staff to send from their phone."""
    KIND = [('reminder', 'Reminder'), ('missed', 'Missed visit')]
    STATUS = [('pending', 'Waiting to be sent'), ('sent', 'Sent'), ('failed', 'Failed'), ('skipped', 'Not sent')]
    enrolment = models.ForeignKey(Enrolment, on_delete=models.CASCADE, related_name='messages')
    visit = models.ForeignKey(ProgrammeVisit, null=True, blank=True, on_delete=models.CASCADE, related_name='messages')
    kind = models.CharField(max_length=10, choices=KIND)
    channel = models.CharField(max_length=10, choices=Enrolment.CHANNEL)
    to = models.CharField(max_length=200, blank=True)
    text = models.CharField(max_length=480)
    status = models.CharField(max_length=10, choices=STATUS, default='pending', db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['-created_at']


class ProgrammeAIRun(Tracked):
    """A Dr. Flow answer for a programme (cohort insight) or one enrolment (follow-up plan). Only de-identified data is
    sent; the SHA-256 of exactly what was sent is kept for audit."""
    KIND = [('cohort', 'Programme insight'), ('patient', 'Follow-up plan')]
    STATUS = [('queued', 'Queued'), ('running', 'Thinking'), ('done', 'Ready'), ('failed', 'Failed'), ('blocked', 'Blocked by the privacy check')]
    programme = models.ForeignKey(Programme, on_delete=models.CASCADE, related_name='ai_runs')
    enrolment = models.ForeignKey(Enrolment, null=True, blank=True, on_delete=models.CASCADE, related_name='ai_runs')
    kind = models.CharField(max_length=8, choices=KIND)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    status = models.CharField(max_length=10, choices=STATUS, default='queued')
    text = models.TextField(blank=True)
    model_name = models.CharField(max_length=80, blank=True)
    context_digest = models.CharField(max_length=64, blank=True)
    error = models.CharField(max_length=500, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    helpful = models.BooleanField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def busy(self):
        return self.status in ('queued', 'running') and (timezone.now() - self.created_at).total_seconds() < 600
