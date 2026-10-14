"""Bedside care and injury records.

* BedsideState        — the equipment on an inpatient right now (IV, oxygen, monitor, catheter …). One per admission.
* BedsideObservation  — a set of bedside observations (heart rate, blood pressure, SpO2 …) with its NEWS2 score.
* InjuryAssessment    — burns, spinal injury, head injury and other wounds for a visit, with computed TBSA and fluids.

The JSON payloads are always cleaned by hospital/bedside.py and hospital/injury.py before they are saved, and the
same functions compute the derived numbers that drive the animations, so the picture always matches the values.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from .models import Admission, Encounter, Patient, Tracked


class BedsideState(Tracked):
    admission = models.OneToOneField(Admission, on_delete=models.CASCADE, related_name='bedside')
    devices = models.JSONField(default=dict, blank=True, help_text='Cleaned by hospital.bedside.clean_devices')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    def __str__(self):
        return f'Bedside · {self.admission}'


class BedsideObservation(Tracked):
    LOC = [('A', 'Alert'), ('C', 'New confusion'), ('V', 'Responds to voice'), ('P', 'Responds to pain'), ('U', 'Unresponsive')]
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='observations')
    taken_at = models.DateTimeField(default=timezone.now, db_index=True)
    heart_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    systolic = models.PositiveSmallIntegerField(null=True, blank=True)
    diastolic = models.PositiveSmallIntegerField(null=True, blank=True)
    resp_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    spo2 = models.PositiveSmallIntegerField(null=True, blank=True)
    temperature_c = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    consciousness = models.CharField(max_length=1, choices=LOC, default='A')
    on_oxygen = models.BooleanField(default=False)
    news2 = models.PositiveSmallIntegerField(null=True, blank=True, editable=False)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')

    class Meta:
        ordering = ['-taken_at']

    def as_dict(self):
        return {'heart_rate': self.heart_rate, 'systolic': self.systolic, 'diastolic': self.diastolic, 'resp_rate': self.resp_rate,
                'spo2': self.spo2, 'temperature_c': float(self.temperature_c) if self.temperature_c is not None else None,
                'consciousness': self.consciousness, 'on_oxygen': self.on_oxygen}


class InjuryAssessment(Tracked):
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name='injury_assessments')
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='injury_assessments')
    data = models.JSONField(default=dict, help_text='Cleaned by hospital.injury.clean_assessment')
    computed = models.JSONField(default=dict, editable=False)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    assessed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Injury assessment · {self.patient.mrn} · {self.created_at:%d %b %Y}'


class SenseExam(Tracked):
    """Eye and ear examination: acuity, pressure, lens, fundus, otoscopy and the audiogram for both sides.
    The numbers that drive the animations (vision simulation, ear sound path, audiogram) are computed by
    hospital/senses.py from the values entered, and recomputed on every save."""
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name='sense_exams')
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='sense_exams')
    data = models.JSONField(default=dict, help_text='Cleaned by hospital.senses.clean_exam')
    computed = models.JSONField(default=dict, editable=False)
    examined_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Eye & ear exam · {self.patient.mrn} · {self.created_at:%d %b %Y}'
