"""Ambulance service: stations, the fleet, crews on shift, emergency calls and their journey, care on board, GPS trail
and the device tokens used by the phone apps. The rules live in hospital/ambulance.py.
"""
import hashlib
import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from .models import Encounter, Location, NetworkFacility, Patient, Tracked


class EmsStation(Tracked):
    """Where ambulances wait: the main base, stations, roadside standby posts and river jetties."""
    KIND = [('base', 'Main base'), ('station', 'Ambulance station'), ('post', 'Standby post'), ('jetty', 'River jetty')]
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=8, blank=True)
    kind = models.CharField(max_length=8, choices=KIND, default='station')
    latitude = models.FloatField()
    longitude = models.FloatField()
    address = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Ambulance(Tracked):
    LEVEL = [('als', 'Advanced life support'), ('bls', 'Basic life support'), ('neonatal', 'Mother & newborn'),
             ('rural', '4×4 rural'), ('moto', 'Motorbike first responder'), ('boat', 'River ambulance')]
    STATUS = [('available', 'Available'), ('dispatched', 'Dispatched'), ('en_route', 'On the way'), ('on_scene', 'On scene'),
              ('transporting', 'Transporting'), ('at_hospital', 'At hospital'), ('returning', 'Returning'),
              ('off_duty', 'Off duty'), ('maintenance', 'Out of service')]
    BUSY = ('dispatched', 'en_route', 'on_scene', 'transporting', 'at_hospital')
    call_sign = models.CharField(max_length=30, unique=True, help_text='Spoken on the radio, e.g. Hornbill 1')
    plate = models.CharField(max_length=20, blank=True)
    level = models.CharField(max_length=10, choices=LEVEL, default='bls')
    station = models.ForeignKey(EmsStation, on_delete=models.SET_NULL, null=True, blank=True, related_name='ambulances')
    status = models.CharField(max_length=12, choices=STATUS, default='available')
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    heading = models.FloatField(default=0, help_text='Degrees from north')
    speed_kmh = models.FloatField(default=0)
    position_at = models.DateTimeField(null=True, blank=True)
    fuel_pct = models.PositiveSmallIntegerField(default=100)
    oxygen_pct = models.PositiveSmallIntegerField(default=100)
    odometer_km = models.PositiveIntegerField(default=0)
    checked_at = models.DateTimeField(null=True, blank=True)
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    checklist = models.JSONField(default=dict, blank=True, help_text='Last readiness check: item key → true/false')
    notes = models.CharField(max_length=300, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['call_sign']

    def __str__(self):
        return self.call_sign

    @property
    def can_transport(self):
        return self.level != 'moto'

    @property
    def is_busy(self):
        return self.status in self.BUSY

    @property
    def is_free(self):
        return self.active and self.status in ('available', 'returning')

    @property
    def crew(self):
        return [s for s in self.shifts.all() if s.ended_at is None]

    @property
    def current_call(self):
        return self.calls.filter(status__in=EmergencyCall.ACTIVE).order_by('-dispatched_at').first()


class CrewShift(Tracked):
    """A person on board an ambulance from the start of their shift to the end."""
    ROLE = [('driver', 'Driver'), ('paramedic', 'Paramedic'), ('emt', 'Emergency technician'), ('nurse', 'Nurse'),
            ('midwife', 'Midwife'), ('doctor', 'Doctor')]
    ambulance = models.ForeignKey(Ambulance, on_delete=models.CASCADE, related_name='shifts')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='ems_shifts')
    role = models.CharField(max_length=10, choices=ROLE, default='paramedic')
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.user} on {self.ambulance} ({self.get_role_display()})'


def _reference():
    return f'EMS-{timezone.localtime():%y%m%d}-{uuid.uuid4().hex[:4].upper()}'


def _token():
    return secrets.token_urlsafe(12)


class EmergencyCall(Tracked):
    """One request for an ambulance, from the first ring (or app tap) to handover at hospital."""
    SOURCE = [('phone', 'Phone call'), ('app', 'Phone app'), ('walk_in', 'Walk-in / radio'), ('transfer', 'Inter-facility transfer'),
              ('police', 'Police / fire service')]
    PRIORITY = [(1, 'P1 · Immediate'), (2, 'P2 · Emergency'), (3, 'P3 · Urgent'), (4, 'P4 · Routine')]
    STATUS = [('new', 'Waiting for call-back'), ('waiting', 'Waiting for an ambulance'), ('dispatched', 'Ambulance assigned'),
              ('en_route', 'Ambulance on the way'), ('on_scene', 'Crew with the patient'), ('transporting', 'On the way to hospital'),
              ('at_hospital', 'Arrived at hospital'), ('closed', 'Closed'), ('cancelled', 'Cancelled')]
    ACTIVE = ('dispatched', 'en_route', 'on_scene', 'transporting', 'at_hospital')
    OPEN = ('new', 'waiting') + ACTIVE
    OUTCOME = [('transported', 'Taken to hospital'), ('treated', 'Treated on scene'), ('refused', 'Refused transport'),
               ('deceased', 'Died before or on arrival'), ('no_patient', 'No patient found'), ('cancelled', 'Cancelled')]
    SEX = [('F', 'Female'), ('M', 'Male'), ('X', 'Not known')]

    reference = models.CharField(max_length=20, unique=True, default=_reference, editable=False)
    token = models.CharField(max_length=24, unique=True, default=_token, editable=False, help_text='For the caller’s tracking link')
    source = models.CharField(max_length=10, choices=SOURCE, default='phone')
    caller_name = models.CharField(max_length=120, blank=True)
    caller_phone = models.CharField(max_length=40, blank=True)
    caller_relation = models.CharField(max_length=60, blank=True, help_text='e.g. Self, Son, Passer-by')
    patient = models.ForeignKey(Patient, on_delete=models.SET_NULL, null=True, blank=True, related_name='ems_calls')
    patient_name = models.CharField(max_length=160, blank=True)
    patient_age = models.PositiveSmallIntegerField(null=True, blank=True)
    patient_sex = models.CharField(max_length=1, choices=SEX, default='X')
    patients_count = models.PositiveSmallIntegerField(default=1)
    complaint = models.CharField(max_length=20, default='other')
    answers = models.JSONField(default=dict, blank=True)
    priority = models.PositiveSmallIntegerField(choices=PRIORITY, default=3)
    priority_reason = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    landmark = models.CharField(max_length=200, blank=True, help_text='What the crew will see: “behind Westfield mosque, green gate”')
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    accuracy_m = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default='waiting', db_index=True)
    outcome = models.CharField(max_length=12, choices=OUTCOME, blank=True)
    ambulance = models.ForeignKey(Ambulance, on_delete=models.SET_NULL, null=True, blank=True, related_name='calls')
    destination = models.ForeignKey(NetworkFacility, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                    help_text='Blank = this hospital')
    eta_scene_at = models.DateTimeField(null=True, blank=True)
    eta_hospital_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(default=timezone.now)
    verified_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    en_route_at = models.DateTimeField(null=True, blank=True)
    on_scene_at = models.DateTimeField(null=True, blank=True)
    transporting_at = models.DateTimeField(null=True, blank=True)
    at_hospital_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=200, blank=True)
    prep = models.JSONField(default=dict, blank=True, help_text='Crew preparation checklist: item key → who ticked it, when')
    handover = models.JSONField(default=dict, blank=True, help_text='ATMIST handover given at hospital')
    encounter = models.ForeignKey(Encounter, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                  help_text='The emergency visit opened at handover')
    taken_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    dispatched_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['priority', 'received_at']
        indexes = [models.Index(fields=['status', 'priority'])]

    def __str__(self):
        return self.reference

    @property
    def is_open(self):
        return self.status in self.OPEN

    @property
    def has_position(self):
        return self.latitude is not None and self.longitude is not None

    @property
    def response_minutes(self):
        """Call received → crew with the patient."""
        if self.on_scene_at:
            return round((self.on_scene_at - self.received_at).total_seconds() / 60, 1)
        return None

    @property
    def waiting_minutes(self):
        end = self.on_scene_at or self.closed_at or timezone.now()
        return int((end - self.received_at).total_seconds() // 60)


class CallEvent(models.Model):
    """The call's timeline: status changes, notes, treatment given and messages."""
    KIND = [('status', 'Status'), ('note', 'Note'), ('treatment', 'Treatment'), ('message', 'Message'), ('system', 'System')]
    call = models.ForeignKey(EmergencyCall, on_delete=models.CASCADE, related_name='events')
    kind = models.CharField(max_length=10, choices=KIND, default='note')
    text = models.CharField(max_length=400)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['at', 'id']


class CallObservation(models.Model):
    """Vital signs taken by the crew. The last one goes into the handover and the emergency visit."""
    AVPU = [('A', 'Alert'), ('V', 'Responds to voice'), ('P', 'Responds to pain'), ('U', 'Unresponsive')]
    call = models.ForeignKey(EmergencyCall, on_delete=models.CASCADE, related_name='observations')
    taken_at = models.DateTimeField(default=timezone.now)
    heart_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    systolic = models.PositiveSmallIntegerField(null=True, blank=True)
    diastolic = models.PositiveSmallIntegerField(null=True, blank=True)
    resp_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    spo2 = models.PositiveSmallIntegerField(null=True, blank=True)
    temperature_c = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    glucose_mmol = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    gcs = models.PositiveSmallIntegerField(null=True, blank=True)
    avpu = models.CharField(max_length=1, choices=AVPU, blank=True)
    pain = models.PositiveSmallIntegerField(null=True, blank=True, help_text='0–10')
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['taken_at', 'id']


class PositionPing(models.Model):
    """The GPS trail of an ambulance (from the crew phone, or the demo simulator)."""
    ambulance = models.ForeignKey(Ambulance, on_delete=models.CASCADE, related_name='pings')
    call = models.ForeignKey(EmergencyCall, on_delete=models.SET_NULL, null=True, blank=True, related_name='pings')
    latitude = models.FloatField()
    longitude = models.FloatField()
    speed_kmh = models.FloatField(default=0)
    heading = models.FloatField(default=0)
    accuracy_m = models.PositiveIntegerField(null=True, blank=True)
    at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['at']
        indexes = [models.Index(fields=['ambulance', 'at'])]


class ApiDevice(Tracked):
    """A phone or tablet paired with the ambulance API. Only a hash of the token is kept."""
    name = models.CharField(max_length=80)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ems_devices')
    prefix = models.CharField(max_length=8, editable=False)
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.prefix}…)'

    @staticmethod
    def hash(raw):
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, user, name, created_by=None):
        """Create a device and return (device, raw token). The raw token is shown once and never stored."""
        raw = 'ems_' + secrets.token_urlsafe(30)
        d = cls.objects.create(user=user, name=name[:80] or 'Phone', prefix=raw[4:12], key_hash=cls.hash(raw), created_by=created_by or user)
        return d, raw

    @classmethod
    def authenticate(cls, raw):
        if not raw or not raw.startswith('ems_'):
            return None
        d = cls.objects.select_related('user').filter(key_hash=cls.hash(raw), revoked_at__isnull=True).first()
        if not d or not d.user.is_active:
            return None
        if not d.last_used_at or (timezone.now() - d.last_used_at).total_seconds() > 60:
            cls.objects.filter(pk=d.pk).update(last_used_at=timezone.now())
        return d
