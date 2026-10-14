"""Access groups: a named set of capabilities (see hospital/access.py) that staff are allocated to."""
from django.conf import settings
from django.db import models

from .models import Tracked


class AccessGroup(Tracked):
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=240, blank=True)
    capabilities = models.JSONField(default=list, blank=True, help_text='Capability keys from hospital.access.CAPABILITIES')
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='access_groups')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
