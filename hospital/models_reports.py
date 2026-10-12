"""Doctor's reports: an AI summary adopted, edited and signed by a clinician, exported as one PDF or a ZIP with every
file. A signed report is never changed; an amendment is a new report that supersedes it."""
import os
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from .models import Tracked


def _token():
    return uuid.uuid4().hex


class DoctorReport(Tracked):
    STATUS = [('draft', 'Draft'), ('final', 'Signed'), ('superseded', 'Superseded by an amendment')]
    encounter = models.ForeignKey('Encounter', on_delete=models.PROTECT, related_name='doctor_reports')
    lab_request = models.ForeignKey('LabRequest', on_delete=models.PROTECT, null=True, blank=True, related_name='doctor_reports')
    source_suggestion = models.ForeignKey('AISuggestion', on_delete=models.SET_NULL, null=True, blank=True, related_name='reports',
                                          help_text='The AI summary this report was adopted from')
    amends = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='amendments')
    title = models.CharField(max_length=160, default="Doctor's report")
    body = models.TextField(blank=True, help_text='Markdown subset: ## headings, - lists, 1. steps, **bold**')
    ai_draft = models.TextField(blank=True, editable=False, help_text='The AI text as adopted, to measure how much the doctor changed')
    follow_up = models.DateField(null=True, blank=True)
    include = models.JSONField(default=dict, blank=True, help_text='{"labs": true, "images": [ids], "attachments": [ids], "ai_sources": true}')
    status = models.CharField(max_length=12, choices=STATUS, default='draft')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    edited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    signed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    signed_at = models.DateTimeField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, help_text='SHA-256 of the signed content')
    amend_reason = models.CharField(max_length=300, blank=True)
    verify_token = models.CharField(max_length=32, unique=True, default=_token, editable=False)
    history = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def number(self):
        return f'DR-{self.pk:06d}'

    @property
    def editable(self):
        return self.status == 'draft'

    def log(self, user, action, **extra):
        name = (user.get_full_name() or user.get_username()) if user else 'System'
        self.history = (self.history or []) + [{'at': timezone.now().isoformat(timespec='seconds'), 'by': name, 'action': action, **extra}]

    def __str__(self):
        return f'{self.number} · {self.encounter.patient}'


def report_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()[:6]
    return f'reports/{instance.report.encounter.patient_id}/{instance.report_id}/{uuid.uuid4().hex}{ext}'


class ReportAttachment(Tracked):
    """A file the doctor adds to a report: a photo of an ECG strip, a scanned letter, an outside result."""
    report = models.ForeignKey(DoctorReport, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to=report_upload_path)
    name = models.CharField(max_length=160)
    content_type = models.CharField(max_length=60)
    size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')

    class Meta:
        ordering = ['id']

    @property
    def is_image(self):
        return self.content_type.startswith('image/')


class ReportAssist(Tracked):
    """One AI helper run on a draft (safety check, patient-friendly version, tighten, ICD-10 codes). Advisory only."""
    KINDS = [('safety', 'Safety check'), ('patient', 'Patient-friendly explanation'), ('tighten', 'Tighten wording'),
             ('codes', 'Suggest ICD-10 codes')]
    STATUS = [('queued', 'Queued'), ('running', 'Thinking'), ('done', 'Ready'), ('failed', 'Failed')]
    report = models.ForeignKey(DoctorReport, on_delete=models.CASCADE, related_name='assists')
    kind = models.CharField(max_length=10, choices=KINDS)
    status = models.CharField(max_length=10, choices=STATUS, default='queued')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    input_text = models.TextField(blank=True, help_text='The de-identified draft that was sent')
    text = models.TextField(blank=True)
    model_name = models.CharField(max_length=80, blank=True)
    error = models.CharField(max_length=500, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def busy(self):
        return self.status in ('queued', 'running') and (timezone.now() - self.created_at).total_seconds() < 600
