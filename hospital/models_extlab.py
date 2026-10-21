"""Lab requests sent out to a laboratory outside the hospital ("send-outs").

A doctor sends a lab request to another laboratory and the patient goes there. Two ways in for the lab:

* **On E-MedFlow** (a network facility with partner logins): the lab signs in and types the patient's phone number.
  Nothing else is needed; only send-outs addressed to that facility can be found.
* **Not on E-MedFlow**: the lab receives a one-time link (WhatsApp, SMS or email). Opening it asks for the patient's
  phone number. The first correct number *claims* the link for that browser; any other device is refused, five wrong
  numbers lock it, and it closes for good once results are sent. Only a SHA-256 of the link's secret is stored, so the
  link cannot be recovered from the database; the hospital re-issues a new one instead (the old one stops working).

Results come back into the same request (catalogue parameters with flags, and/or the lab's own report file) and are
verified by the hospital laboratory like any other result.
"""
import hashlib
import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from .models import LabRequest, NetworkFacility, Tracked

MAX_PHONE_ATTEMPTS = 5


def _reference():
    alphabet = 'ACDEFGHJKMNPQRTUVWXY3479'          # no 0/O, 1/I/L, 2/Z, 5/S, 6/G, 8/B: easy to read out on the phone
    return 'XL-' + ''.join(secrets.choice(alphabet) for _ in range(6))


def sha(value):
    return hashlib.sha256((value or '').encode()).hexdigest()


def report_upload_path(instance, filename):
    import os
    ext = os.path.splitext(filename)[1].lower()[:6]
    return f'extlab/{instance.lab_request_id}/{uuid.uuid4().hex}{ext}'


class ExternalLabReferral(Tracked):
    STATUS = [('sent', 'Waiting for the patient'), ('arrived', 'Patient at the lab'), ('collected', 'Sample collected'),
              ('reported', 'Results sent back'), ('cancelled', 'Cancelled')]
    ACTIVE = ('sent', 'arrived', 'collected')
    CHANNEL = [('network', 'On E-MedFlow · phone number only'), ('link', 'One-time link + phone number')]

    reference = models.CharField(max_length=12, unique=True, default=_reference, editable=False)
    lab_request = models.ForeignKey(LabRequest, on_delete=models.PROTECT, related_name='sendouts')
    channel = models.CharField(max_length=8, choices=CHANNEL)
    status = models.CharField(max_length=10, choices=STATUS, default='sent')
    facility = models.ForeignKey(NetworkFacility, on_delete=models.PROTECT, null=True, blank=True, related_name='lab_sendouts',
                                 help_text='The receiving lab when it is in the network directory')
    lab_name = models.CharField(max_length=200)
    lab_phone = models.CharField(max_length=40, blank=True)
    lab_email = models.EmailField(blank=True)
    lab_address = models.CharField(max_length=250, blank=True)
    patient_phone = models.CharField(max_length=40, help_text='The number the lab must type to open the request')
    phone_local = models.CharField(max_length=30, db_index=True, editable=False)
    instructions = models.TextField(blank=True, help_text='For the patient, e.g. come fasting, bring a morning urine sample')
    note_to_lab = models.TextField(blank=True)
    expires_at = models.DateTimeField()
    # one-time link (channel = link)
    token_hash = models.CharField(max_length=64, blank=True, db_index=True, editable=False)
    token_issued_at = models.DateTimeField(null=True, blank=True)
    claim_hash = models.CharField(max_length=64, blank=True, editable=False)
    claimed_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_at = models.DateTimeField(null=True, blank=True)
    # progress
    arrived_at = models.DateTimeField(null=True, blank=True)
    collected_at = models.DateTimeField(null=True, blank=True)
    specimen_ref = models.CharField(max_length=80, blank=True, help_text="The outside lab's own sample or accession number")
    reported_at = models.DateTimeField(null=True, blank=True)
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reported_by_name = models.CharField(max_length=160, blank=True, help_text='Who at the outside lab released the results')
    lab_comment = models.TextField(blank=True)
    report_file = models.FileField(upload_to=report_upload_path, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='lab_sendouts_made')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *a, **kw):
        from .phones import digits, local
        self.phone_local = local(digits(self.patient_phone))
        super().save(*a, **kw)

    # ------------------------------------------------------------ state
    @property
    def is_active(self):
        return self.status in self.ACTIVE

    @property
    def is_expired(self):
        return self.is_active and self.expires_at < timezone.now()

    @property
    def is_locked(self):
        return self.locked_at is not None

    @property
    def is_open(self):
        """The lab may still work on it."""
        return self.is_active and not self.is_expired and not self.is_locked

    @property
    def display_status(self):
        if self.status == 'reported' and self.lab_request.stage == 'verified':
            return 'Verified at the hospital'
        if self.is_locked and self.is_active:
            return 'Locked · too many wrong numbers'
        if self.is_expired:
            return 'Expired'
        return self.get_status_display()

    @property
    def tone(self):
        if self.is_locked or self.is_expired or self.status == 'cancelled':
            return 'red'
        return {'sent': 'amber', 'arrived': 'indigo', 'collected': 'indigo', 'reported': 'plum'}.get(self.status, 'teal')

    @property
    def masked_phone(self):
        d = self.phone_local or ''
        return ('•' * max(0, len(d) - 3)) + d[-3:] if d else ''

    TRACK = [('sent', 'Sent'), ('arrived', 'Patient at the lab'), ('collected', 'Sample taken'), ('reported', 'Results back'), ('verified', 'Verified')]

    def track(self):
        """Steps for the progress tracker: done / current / todo."""
        order = [k for k, _ in self.TRACK]
        cur = 'verified' if self.status == 'reported' and self.lab_request.stage == 'verified' else self.status
        idx = order.index(cur) if cur in order else -1
        when = {'sent': self.created_at, 'arrived': self.arrived_at, 'collected': self.collected_at, 'reported': self.reported_at}
        return [{'key': k, 'label': lbl, 'at': when.get(k), 'state': 'done' if i <= idx else 'current' if i == idx + 1 and self.is_open else 'todo'}
                for i, (k, lbl) in enumerate(self.TRACK)]

    # ------------------------------------------------------------ one-time link
    def issue_token(self):
        """A fresh link secret. Returns the plain token (shown once); only its hash is kept. Resets claim and lock."""
        token = secrets.token_urlsafe(24)
        self.token_hash, self.token_issued_at = sha(token), timezone.now()
        self.claim_hash, self.claimed_at, self.failed_attempts, self.locked_at = '', None, 0, None
        return token

    @classmethod
    def from_token(cls, token):
        if not token or len(token) > 64:
            return None
        return cls.objects.select_related('lab_request__encounter__patient', 'lab_request__requested_by').filter(
            token_hash=sha(token), channel='link').first()

    def __str__(self):
        return f'{self.reference} · {self.lab_name}'
