"""Forms, flows and e-sign.

Forms   FormDefinition (in models.py) holds the live schema; every publish freezes a FormVersion. FormDraft keeps a
        half-filled form per person and patient so nobody loses work.
Flows   WorkflowDefinition.graph is a graph of steps (see hospital/flows.py). A WorkflowRun moves through it; people's
        work is a WorkflowTask, and every move is a WorkflowEvent.
E-sign  An Envelope carries one PDF to recipients in routing order. Fields are placed on the pages as fractions of
        the page, so they line up at any zoom. Every event is chained to the previous one with SHA-256, so any later
        edit to the trail is detectable (see hospital/esign.py `verify`).
"""
import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from .models import FormDefinition, FormSubmission, Patient, Tracked, WorkflowRun


class FormVersion(Tracked):
    definition = models.ForeignKey(FormDefinition, on_delete=models.CASCADE, related_name='versions')
    version = models.PositiveIntegerField()
    schema = models.JSONField()
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-version']
        unique_together = [('definition', 'version')]


class FormDraft(Tracked):
    definition = models.ForeignKey(FormDefinition, on_delete=models.CASCADE, related_name='drafts')
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='+')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    values = models.JSONField(default=dict)
    page = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = [('definition', 'patient', 'user')]


class WorkflowTask(Tracked):
    KIND = [('approval', 'Approval'), ('review', 'Review'), ('fill', 'Fill in'), ('signature', 'Signature')]
    STATUS = [('pending', 'Waiting for action'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('done', 'Done'),
              ('returned', 'Returned for changes'), ('skipped', 'No longer needed'), ('cancelled', 'Cancelled')]
    run = models.ForeignKey(WorkflowRun, on_delete=models.CASCADE, related_name='tasks')
    node_id = models.CharField(max_length=40)
    kind = models.CharField(max_length=12, choices=KIND)
    label = models.CharField(max_length=120)
    role = models.CharField(max_length=20, blank=True, help_text='Anyone with this role may act')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='flow_tasks')
    status = models.CharField(max_length=10, choices=STATUS, default='pending', db_index=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    round = models.PositiveSmallIntegerField(default=1)
    envelope = models.ForeignKey('Envelope', null=True, blank=True, on_delete=models.SET_NULL, related_name='tasks')

    class Meta:
        ordering = ['created_at']

    @property
    def overdue(self):
        return self.status == 'pending' and self.due_at and self.due_at < timezone.now()


class WorkflowEvent(Tracked):
    run = models.ForeignKey(WorkflowRun, on_delete=models.CASCADE, related_name='events')
    node_id = models.CharField(max_length=40, blank=True)
    kind = models.CharField(max_length=30)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    note = models.CharField(max_length=400, blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['created_at', 'pk']


# ================================================================== e-sign
class SignatureProfile(Tracked):
    """A staff member's adopted signature and initials, reused on every envelope."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='signature_profile')
    signature = models.TextField(help_text='PNG data URL')
    initials = models.TextField(blank=True, help_text='PNG data URL')
    style = models.CharField(max_length=10, default='draw')


def _token():
    return secrets.token_urlsafe(32)


class Envelope(Tracked):
    STATUS = [('draft', 'Draft'), ('sent', 'Out for signature'), ('completed', 'Completed'), ('declined', 'Declined'),
              ('voided', 'Voided'), ('expired', 'Expired')]
    SOURCE = [('upload', 'Uploaded PDF'), ('form', 'Form submission'), ('letter', 'Written here')]
    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    subject = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default='draft', db_index=True)
    source = models.CharField(max_length=8, choices=SOURCE, default='upload')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='envelopes')
    patient = models.ForeignKey(Patient, null=True, blank=True, on_delete=models.PROTECT, related_name='envelopes')
    submission = models.ForeignKey(FormSubmission, null=True, blank=True, on_delete=models.PROTECT, related_name='envelopes')
    document = models.FileField(upload_to='esign/original/%Y/%m/')
    document_name = models.CharField(max_length=200, default='document.pdf')
    document_sha256 = models.CharField(max_length=64)
    pages = models.PositiveSmallIntegerField(default=1)
    page_sizes = models.JSONField(default=list, help_text='[[width_pt, height_pt], …] per page')
    signed_document = models.FileField(upload_to='esign/signed/%Y/%m/', blank=True)
    signed_sha256 = models.CharField(max_length=64, blank=True)
    require_full_read = models.BooleanField(default=False, help_text='Signers must page through the whole document before signing')
    expires_at = models.DateTimeField(null=True, blank=True)
    remind_every_hours = models.PositiveSmallIntegerField(default=24)
    sent_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=300, blank=True)
    run = models.ForeignKey(WorkflowRun, null=True, blank=True, on_delete=models.SET_NULL, related_name='envelopes')
    node_id = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.subject

    @property
    def short_id(self):
        return self.uid.hex[:8].upper()


class EnvelopeRecipient(Tracked):
    ROLE = [('signer', 'Needs to sign'), ('in_person', 'Signs in person on this device'), ('witness', 'Witness'),
            ('approver', 'Needs to approve'), ('cc', 'Receives a copy')]
    STATUS = [('waiting', 'Waiting for earlier recipients'), ('sent', 'Sent'), ('viewed', 'Opened'),
              ('signed', 'Signed'), ('approved', 'Approved'), ('declined', 'Declined'), ('copied', 'Copy sent')]
    envelope = models.ForeignKey(Envelope, on_delete=models.CASCADE, related_name='recipients')
    name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='envelope_recipients')
    role = models.CharField(max_length=10, choices=ROLE, default='signer')
    relation = models.CharField(max_length=80, blank=True, help_text='e.g. Patient, Mother (guardian), Interpreter')
    order = models.PositiveSmallIntegerField(default=1, help_text='Recipients with the same number receive it together')
    status = models.CharField(max_length=10, choices=STATUS, default='waiting')
    color = models.CharField(max_length=7, default='#0F7B78')
    token = models.CharField(max_length=64, default=_token, unique=True)
    access_code_hash = models.CharField(max_length=128, blank=True)
    host = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                             help_text='In-person signing: the staff member who hands over the device')
    identity_check = models.CharField(max_length=200, blank=True, help_text='How identity was confirmed, for in-person signing')
    sent_at = models.DateTimeField(null=True, blank=True)
    viewed_at = models.DateTimeField(null=True, blank=True)
    acted_at = models.DateTimeField(null=True, blank=True)
    last_reminded_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.CharField(max_length=400, blank=True)
    pages_seen = models.JSONField(default=list, blank=True)
    signature_image = models.TextField(blank=True)
    initials_image = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['order', 'pk']

    @property
    def done(self):
        return self.status in ('signed', 'approved', 'copied')

    @property
    def needs_fields(self):
        return self.role in ('signer', 'in_person', 'witness')


class EnvelopeField(Tracked):
    KIND = [('signature', 'Signature'), ('initials', 'Initials'), ('date_signed', 'Date signed'), ('full_name', 'Full name'),
            ('text', 'Text'), ('checkbox', 'Checkbox'), ('choice', 'Choose one')]
    envelope = models.ForeignKey(Envelope, on_delete=models.CASCADE, related_name='fields')
    recipient = models.ForeignKey(EnvelopeRecipient, on_delete=models.CASCADE, related_name='fields')
    kind = models.CharField(max_length=12, choices=KIND)
    page = models.PositiveSmallIntegerField()
    x = models.FloatField(); y = models.FloatField(); w = models.FloatField(); h = models.FloatField()
    required = models.BooleanField(default=True)
    label = models.CharField(max_length=120, blank=True)
    options = models.JSONField(default=list, blank=True)
    value = models.TextField(blank=True)
    filled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['page', 'y', 'x']


class EnvelopeEvent(models.Model):
    envelope = models.ForeignKey(Envelope, on_delete=models.CASCADE, related_name='events')
    recipient = models.ForeignKey(EnvelopeRecipient, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    action = models.CharField(max_length=30)
    at = models.DateTimeField(default=timezone.now)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    details = models.JSONField(default=dict, blank=True)
    prev_hash = models.CharField(max_length=64, blank=True)
    hash = models.CharField(max_length=64)

    class Meta:
        ordering = ['at', 'pk']
