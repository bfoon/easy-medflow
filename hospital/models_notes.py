"""Clinical and nursing notes on a visit: every saved change is kept (NoteRevision), and Dr. Flow can polish the
wording, suggest tests and answer questions about the notes (ClinicalNoteAsk, see notes_ai.py)."""
from django.conf import settings
from django.db import models
from django.utils import timezone

from .models import Tracked


class NoteRevision(Tracked):
    """One saved change to the clinical or nursing notes: who, when, what it was before and after."""
    SECTIONS = [('clinical', 'Clinical notes'), ('nursing', 'Nursing notes')]
    encounter = models.ForeignKey('Encounter', on_delete=models.CASCADE, related_name='note_revisions')
    section = models.CharField(max_length=10, choices=SECTIONS)
    edited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    ai_assisted = models.BooleanField(default=False, help_text='The saved text included wording suggested by Dr. Flow')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_section_display()} · encounter {self.encounter_id} · {self.created_at:%d %b %H:%M}'

    @property
    def changed(self):
        """[(label, before, after)] for the fields that changed."""
        from .notes_ai import CLINICAL_FIELDS, NURSING_FIELDS
        labels = dict(CLINICAL_FIELDS + NURSING_FIELDS)
        return [(labels.get(k, k), self.before.get(k, ''), self.after.get(k, '')) for k in self.after if (self.before.get(k) or '') != (self.after.get(k) or '')]


class ClinicalNoteAsk(Tracked):
    """A Dr. Flow request about a visit's notes. Built from de-identified text only (notes_ai.py); kept for audit
    with a SHA-256 of what was sent."""
    KINDS = [('improve', 'Improve wording'), ('correct', 'Fix spelling and grammar'), ('suggest', 'Suggest tests and next steps'), ('question', 'Question')]
    STATUS = [('queued', 'Queued'), ('running', 'Thinking'), ('done', 'Ready'), ('failed', 'Failed')]
    encounter = models.ForeignKey('Encounter', on_delete=models.CASCADE, related_name='note_asks')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    kind = models.CharField(max_length=10, choices=KINDS)
    section = models.CharField(max_length=10, choices=NoteRevision.SECTIONS, default='clinical')
    question = models.CharField(max_length=500, blank=True)
    draft = models.JSONField(default=dict, blank=True, help_text='The draft text to polish, with names already removed')
    placeholders = models.JSONField(default=dict, blank=True, help_text='Placeholder -> original detail, to put names back after editing. Never sent.')
    status = models.CharField(max_length=10, choices=STATUS, default='queued')
    text = models.TextField(blank=True)
    result = models.JSONField(default=dict, blank=True, help_text='Improved text per field (improve / correct)')
    model_name = models.CharField(max_length=80, blank=True)
    context_digest = models.CharField(max_length=64, blank=True, help_text='SHA-256 of the de-identified context that was sent')
    error = models.CharField(max_length=500, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    helpful = models.BooleanField(null=True, blank=True, help_text="Clinician's rating")

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_kind_display()} · encounter {self.encounter_id} · {self.get_status_display()}'

    @property
    def busy(self):
        return self.status in ('queued', 'running') and (timezone.now() - self.created_at).total_seconds() < 600
