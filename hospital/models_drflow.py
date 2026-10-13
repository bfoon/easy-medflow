"""Questions asked to Dr. Flow about a lab test, a medicine or anything else, kept for audit and reused as a cache."""
from django.conf import settings
from django.db import models
from django.utils import timezone

from .models import Tracked


class DrFlowAsk(Tracked):
    KINDS = [('test', 'Lab test'), ('med', 'Medicine'), ('free', 'Question')]
    STATUS = [('queued', 'Queued'), ('running', 'Thinking'), ('done', 'Ready'), ('failed', 'Failed')]
    kind = models.CharField(max_length=5, choices=KINDS)
    topic = models.CharField(max_length=200, help_text='Test or medicine name, or the question')
    topic_id = models.PositiveIntegerField(null=True, blank=True)
    question = models.CharField(max_length=500, blank=True)
    encounter = models.ForeignKey('Encounter', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                  help_text='Set when the answer should consider this patient (de-identified)')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    cache_key = models.CharField(max_length=64, blank=True, db_index=True, help_text='Same general question = same answer for 30 days')
    status = models.CharField(max_length=10, choices=STATUS, default='queued')
    text = models.TextField(blank=True)
    sources = models.JSONField(default=list, blank=True)
    images = models.JSONField(default=list, blank=True)
    model_name = models.CharField(max_length=80, blank=True)
    error = models.CharField(max_length=500, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def busy(self):
        return self.status in ('queued', 'running') and (timezone.now() - self.created_at).total_seconds() < 600


class BedSummary(Tracked):
    """A Dr. Flow handover summary of the patient in a bed, written from de-identified data only (bed_summary.py)."""
    STATUS = [('queued', 'Queued'), ('running', 'Thinking'), ('done', 'Ready'), ('failed', 'Failed')]
    admission = models.ForeignKey('Admission', on_delete=models.CASCADE, related_name='drflow_summaries')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    status = models.CharField(max_length=10, choices=STATUS, default='queued')
    text = models.TextField(blank=True)
    model_name = models.CharField(max_length=80, blank=True)
    context_digest = models.CharField(max_length=64, blank=True, help_text='SHA-256 of the de-identified context that was sent')
    error = models.CharField(max_length=500, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    helpful = models.BooleanField(null=True, blank=True, help_text="Clinician's rating")

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Bed summary {self.pk} · admission {self.admission_id} · {self.get_status_display()}'

    @property
    def busy(self):
        return self.status in ('queued', 'running') and (timezone.now() - self.created_at).total_seconds() < 600


class LabInsightAsk(Tracked):
    """Dr. Flow on the Lab insights page: a heads-up on all results, or a question about them (lab_insights_ai.py).
    Written from de-identified data only; kept for audit with a SHA-256 of what was sent."""
    KINDS = [('headsup', 'Heads-up'), ('question', 'Question')]
    STATUS = [('queued', 'Queued'), ('running', 'Thinking'), ('done', 'Ready'), ('failed', 'Failed')]
    patient = models.ForeignKey('Patient', on_delete=models.CASCADE, related_name='lab_insight_asks')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    kind = models.CharField(max_length=10, choices=KINDS, default='question')
    question = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default='queued')
    text = models.TextField(blank=True)
    model_name = models.CharField(max_length=80, blank=True)
    context_digest = models.CharField(max_length=64, blank=True, help_text='SHA-256 of the de-identified context that was sent')
    error = models.CharField(max_length=500, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    helpful = models.BooleanField(null=True, blank=True, help_text="Clinician's rating")

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_kind_display()} · patient {self.patient_id} · {self.get_status_display()}'

    @property
    def busy(self):
        return self.status in ('queued', 'running') and (timezone.now() - self.created_at).total_seconds() < 600
