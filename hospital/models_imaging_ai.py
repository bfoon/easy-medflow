"""Dr. Flow on imaging: one AI read of an image (labels drawn on it plus an explanation), or one question about it.

Every run is kept for audit with a SHA-256 of the exact pixels and the de-identified context that were sent.
The answer is an unverified suggestion for a clinician; it never changes the image, its measurements or the report.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from .models import Tracked


class ImagingAIRun(Tracked):
    KINDS = [('analyse', 'Analysis'), ('question', 'Question')]
    STATUS = [('queued', 'Queued'), ('running', 'Thinking'), ('done', 'Ready'), ('failed', 'Failed')]

    image = models.ForeignKey('ImagingImage', on_delete=models.CASCADE, related_name='ai_runs')
    order = models.ForeignKey('ImagingOrder', on_delete=models.CASCADE, related_name='ai_runs')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    kind = models.CharField(max_length=10, choices=KINDS, default='analyse')
    question = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default='queued')
    provider = models.CharField(max_length=20, blank=True)
    model_name = models.CharField(max_length=80, blank=True)
    summary = models.TextField(blank=True, help_text='One or two sentences')
    text = models.TextField(blank=True, help_text='The explanation or answer (Markdown)')
    labels = models.JSONField(default=list, blank=True,
                              help_text='[{"n":1,"name":"...","box":[x,y,w,h] (0-1) or null,"point":[x,y] (0-1) or null,'
                                        '"explanation":"...","concern":"normal|watch|abnormal|urgent","confidence":"low|moderate|high"}]')
    quality = models.CharField(max_length=300, blank=True, help_text='What Dr. Flow said about the image quality')
    limitations = models.TextField(blank=True)
    redactions = models.JSONField(default=list, blank=True, help_text='Boxes (0-1) blacked out before the image was sent')
    image_digest = models.CharField(max_length=64, blank=True, help_text='SHA-256 of the exact image bytes sent')
    context_digest = models.CharField(max_length=64, blank=True, help_text='SHA-256 of the de-identified context sent')
    error = models.CharField(max_length=500, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    helpful = models.BooleanField(null=True, blank=True, help_text="Clinician's rating")

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.get_kind_display()} · image {self.image_id} · {self.get_status_display()}'

    @property
    def busy(self):
        # a job that has been queued or thinking for 10 minutes has died; let a new one start
        return self.status in ('queued', 'running') and (timezone.now() - self.created_at).total_seconds() < 600
