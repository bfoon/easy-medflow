"""The ward's handover board: notes passed from shift to shift, and safety alerts that stay pinned until resolved."""
from django.conf import settings
from django.db import models
from django.utils import timezone

from .models import Patient, Tracked, Ward


def current_shift(now=None):
    h = timezone.localtime(now or timezone.now()).hour
    return 'day' if 7 <= h < 19 else 'night'


class WardNote(Tracked):
    KIND = [('handover', 'Handover'), ('alert', 'Safety alert'), ('info', 'Information')]
    SHIFT = [('day', 'Day shift'), ('night', 'Night shift')]
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name='notes')
    kind = models.CharField(max_length=10, choices=KIND, default='handover')
    shift = models.CharField(max_length=5, choices=SHIFT, default=current_shift)
    patient = models.ForeignKey(Patient, on_delete=models.SET_NULL, null=True, blank=True, related_name='ward_notes',
                                help_text='When the note is about one patient')
    text = models.TextField()
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['-created_at']

    @property
    def open_alert(self):
        return self.kind == 'alert' and not self.resolved_at

    def __str__(self):
        return f'{self.ward} · {self.get_kind_display()} · {self.created_at:%d %b %H:%M}'
