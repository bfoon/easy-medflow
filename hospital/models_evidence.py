"""Lab-result guidance: WHO and international reference values, hospital protocols, evidence fetched in the background
from trusted medical sources, and AI suggestions. Everything here is advisory and needs clinician review."""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from .models import Tracked


def _fmt(d):
    return f'{Decimal(d).normalize():f}' if d is not None else ''


class ReferenceRange(Tracked):
    """A WHO (or other guideline) reference value for one lab parameter code, for a defined group of patients.

    Stored in the unit of the hospital catalogue so it can be compared directly; a reference whose unit does not
    match the parameter's unit is shown but never used to classify a value. `interval` = normal between low and high;
    `threshold` = a decision cut-off (abnormal below `low` or above `high`), e.g. a WHO severe-malaria criterion."""
    SOURCES = [('who', 'WHO'), ('international', 'International guideline'), ('national', 'National guideline')]
    KINDS = [('interval', 'Reference interval'), ('threshold', 'Decision threshold')]
    SEXES = [('', 'Everyone'), ('M', 'Male'), ('F', 'Female')]
    CONDITIONS = [('', 'Any'), ('not_pregnant', 'Not pregnant'), ('pregnant', 'Pregnant · trimester not recorded'), ('t1', 'Pregnant · 1st trimester'),
                  ('t2', 'Pregnant · 2nd trimester'), ('t3', 'Pregnant · 3rd trimester'), ('no_inflammation', 'No infection or inflammation'),
                  ('inflammation', 'With infection or inflammation'), ('malaria', 'Confirmed or suspected malaria')]
    STATUS = [('curated', 'Curated from guideline'), ('verified', 'Verified by the laboratory'), ('review', 'Source changed · review'),
              ('retired', 'Retired')]
    code = models.CharField(max_length=40, db_index=True, help_text='Lab parameter code, e.g. HB')
    source = models.CharField(max_length=20, choices=SOURCES, default='who')
    source_name = models.CharField(max_length=120, default='World Health Organization')
    label = models.CharField(max_length=160, help_text='e.g. Anaemia cut-off, Severe malaria criterion')
    kind = models.CharField(max_length=10, choices=KINDS, default='interval')
    sex = models.CharField(max_length=1, choices=SEXES, blank=True)
    age_min_months = models.PositiveIntegerField(null=True, blank=True, help_text='Inclusive')
    age_max_months = models.PositiveIntegerField(null=True, blank=True, help_text='Exclusive')
    condition = models.CharField(max_length=20, choices=CONDITIONS, blank=True)
    low = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    high = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    unit = models.CharField(max_length=30, blank=True)
    bands = models.JSONField(default=list, blank=True, help_text='Optional severity bands: [{"label":"Moderate","low":8,"high":10.9,"tone":"amber"}]')
    note = models.CharField(max_length=300, blank=True)
    citation_title = models.CharField(max_length=300, blank=True)
    citation_url = models.URLField(max_length=500, blank=True)
    citation_year = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default='curated')
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    verified_at = models.DateTimeField(null=True, blank=True)
    source_hash = models.CharField(max_length=64, blank=True, help_text='Fingerprint of the cited page when last checked')
    source_checked_at = models.DateTimeField(null=True, blank=True)
    source_note = models.CharField(max_length=200, blank=True)
    seed_key = models.CharField(max_length=80, unique=True, null=True, blank=True, editable=False)

    class Meta:
        ordering = ['code', 'kind', 'condition', 'sex', 'age_min_months']

    def __str__(self):
        return f'{self.code} · {self.source_name} · {self.label}'

    @property
    def usable(self):
        return self.status in ('curated', 'verified', 'review')

    def population(self):
        bits = []
        if self.sex:
            bits.append(self.get_sex_display().lower())
        lo, hi = self.age_min_months, self.age_max_months
        fy = lambda m: f'{m // 12} y' if m % 12 == 0 else f'{m} mo'
        if lo is not None and hi is not None:
            bits.append(f'{fy(lo)} to under {fy(hi)}')
        elif lo is not None:
            bits.append(f'{fy(lo)}+')
        elif hi is not None:
            bits.append(f'under {fy(hi)}')
        if self.condition:
            bits.append(self.get_condition_display().lower())
        return ', '.join(bits) or 'everyone'

    def applies(self, ctx):
        """Does this reference fit the patient described by `ctx` (see evidence.patient_context)?"""
        if self.sex and ctx.get('sex') != self.sex:
            return False
        months = ctx.get('age_months')
        if self.age_min_months is not None and (months is None or months < self.age_min_months):
            return False
        if self.age_max_months is not None and (months is None or months >= self.age_max_months):
            return False
        c, preg, tri = self.condition, ctx.get('pregnant'), ctx.get('trimester')
        if c == 'not_pregnant' and preg:
            return False
        if c == 'pregnant' and not (preg and not tri):      # trimester-specific references cover the rest
            return False
        if c in ('t1', 't2', 't3') and not (preg and tri == int(c[1])):
            return False
        if c == 'inflammation' and not ctx.get('inflammation'):
            return False
        if c == 'no_inflammation' and ctx.get('inflammation'):
            return False
        if c == 'malaria' and not ctx.get('malaria'):
            return False
        return True

    def range_label(self):
        u = f' {self.unit}' if self.unit else ''
        if self.kind == 'threshold':
            if self.low is not None and self.high is not None:
                return f'< {_fmt(self.low)} or > {_fmt(self.high)}{u}'
            return f'< {_fmt(self.low)}{u}' if self.low is not None else f'> {_fmt(self.high)}{u}'
        if self.low is not None and self.high is not None:
            return f'{_fmt(self.low)}–{_fmt(self.high)}{u}'
        return f'≥ {_fmt(self.low)}{u}' if self.low is not None else (f'≤ {_fmt(self.high)}{u}' if self.high is not None else '')

    def outside(self, value):
        """True when the value is outside the interval (or meets the threshold criterion)."""
        if value is None:
            return None
        v = Decimal(str(value))
        return bool((self.low is not None and v < self.low) or (self.high is not None and v > self.high))

    def band_for(self, value):
        if value is None:
            return None
        v = Decimal(str(value))
        for b in self.bands or []:
            lo, hi = b.get('low'), b.get('high')
            if (lo is None or v >= Decimal(str(lo))) and (hi is None or v <= Decimal(str(hi))):
                return b
        return None


class ParameterGuidance(Tracked):
    """This hospital's own protocol for an abnormal result (shown first, above general guidance and online sources)."""
    DIRS = [('L', 'Low'), ('H', 'High'), ('A', 'Abnormal / positive'), ('N', 'In range')]
    code = models.CharField(max_length=40, db_index=True, help_text='Lab parameter code, e.g. K')
    direction = models.CharField(max_length=1, choices=DIRS)
    title = models.CharField(max_length=160)
    steps = models.TextField(help_text='One step per line, in order')
    protocol_url = models.URLField(max_length=500, blank=True, help_text='Link to the full hospital protocol, if any')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code', 'direction']
        verbose_name_plural = 'parameter guidance'

    def __str__(self):
        return f'{self.code} · {self.get_direction_display()} · {self.title}'

    @property
    def step_list(self):
        return [s.strip(' -•\t') for s in self.steps.splitlines() if s.strip(' -•\t')]


class EvidenceItem(Tracked):
    """A summary and link from a trusted source for one parameter and direction (key e.g. 'HB:L'), cached locally so
    doctors see it instantly and offline."""
    SOURCES = [('who', 'WHO'), ('medlineplus', 'MedlinePlus · US National Library of Medicine'), ('pubmed', 'PubMed · NCBI'),
               ('other', 'Trusted site')]
    key = models.CharField(max_length=60, db_index=True)
    source = models.CharField(max_length=20, choices=SOURCES)
    kind = models.CharField(max_length=30, blank=True, help_text='fact sheet, lab test, health topic, guideline, systematic review…')
    title = models.CharField(max_length=400)
    url = models.URLField(max_length=600)
    summary = models.TextField(blank=True)
    published = models.CharField(max_length=40, blank=True)
    rank = models.PositiveSmallIntegerField(default=0)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['key', 'rank', 'source']
        unique_together = [('key', 'url')]

    def __str__(self):
        return f'{self.key} · {self.get_source_display()} · {self.title[:60]}'


class EvidenceFetch(Tracked):
    """Background fetch status for one key, so pages can show 'fetching…' and know when cached evidence is stale."""
    STATUS = [('queued', 'Queued'), ('running', 'Fetching'), ('done', 'Done'), ('failed', 'Failed')]
    key = models.CharField(max_length=60, unique=True)
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=160, blank=True)
    unit = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default='queued')
    last_run_at = models.DateTimeField(null=True, blank=True)
    items = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['key']

    @property
    def stale(self):
        days = getattr(settings, 'MEDICAL_EVIDENCE_MAX_AGE_DAYS', 30)
        return not self.last_run_at or (timezone.now() - self.last_run_at).days >= days

    @property
    def busy(self):
        # a job that has been 'running' for 10 minutes has died; let it be retried
        return self.status in ('queued', 'running') and (timezone.now() - self.updated_at).total_seconds() < 600


class AISuggestion(Tracked):
    """One AI review of a lab request, kept for audit. The text is an unverified suggestion for a clinician."""
    STATUS = [('queued', 'Queued'), ('running', 'Thinking'), ('done', 'Ready'), ('failed', 'Failed')]
    encounter = models.ForeignKey('Encounter', on_delete=models.CASCADE, related_name='ai_suggestions')
    lab_request = models.ForeignKey('LabRequest', on_delete=models.CASCADE, null=True, blank=True, related_name='ai_suggestions')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    status = models.CharField(max_length=10, choices=STATUS, default='queued')
    provider = models.CharField(max_length=20, blank=True)
    model_name = models.CharField(max_length=80, blank=True)
    text = models.TextField(blank=True)
    sources = models.JSONField(default=list, blank=True)
    searches = models.JSONField(default=list, blank=True, help_text='Web searches the AI ran (queries only)')
    context_digest = models.CharField(max_length=64, blank=True, help_text='SHA-256 of the de-identified context that was sent')
    error = models.CharField(max_length=500, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    helpful = models.BooleanField(null=True, blank=True, help_text="Clinician's rating")

    class Meta:
        ordering = ['-created_at']

    @property
    def busy(self):
        return self.status in ('queued', 'running') and (timezone.now() - self.created_at).total_seconds() < 600
