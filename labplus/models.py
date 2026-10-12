"""Operational extension of existing hospital laboratory orders. Never stores results twice."""
import uuid
from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone

class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True

class Specimen(TimeStamped):
    STATUS = [(k,k.replace('_',' ').title()) for k in ('expected','collected','received','accepted','rejected','in_process','stored','disposed')]
    accession = models.CharField(max_length=40,unique=True,editable=False)
    request = models.ForeignKey('hospital.LabRequest',on_delete=models.PROTECT,related_name='tracked_specimens')
    sample_type = models.CharField(max_length=100)
    tube = models.CharField(max_length=100,blank=True)
    status = models.CharField(max_length=16,choices=STATUS,default='expected')
    parent = models.ForeignKey('self',null=True,blank=True,on_delete=models.PROTECT,related_name='recollections')
    collected_at = models.DateTimeField(null=True,blank=True)
    received_at = models.DateTimeField(null=True,blank=True)
    expires_at = models.DateTimeField(null=True,blank=True)
    collected_by = models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name='+')
    storage_location = models.CharField(max_length=100,blank=True)
    rejection_reason = models.TextField(blank=True)
    def save(self,*args,**kwargs):
        if not self.accession:self.accession='LAB-'+uuid.uuid4().hex[:14].upper()
        super().save(*args,**kwargs)
    def clean(self):
        if self.parent_id and self.parent.request_id != self.request_id:raise ValidationError('Recollection must belong to same request.')
        if self.status=='rejected' and not self.rejection_reason.strip():raise ValidationError('Rejection reason is required.')
    def __str__(self):return self.accession

class SpecimenEvent(models.Model):
    specimen = models.ForeignKey(Specimen,on_delete=models.PROTECT,related_name='events')
    action = models.CharField(max_length=30)
    from_status = models.CharField(max_length=20,blank=True)
    to_status = models.CharField(max_length=20)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    note = models.TextField(blank=True)
    at = models.DateTimeField(default=timezone.now)
    class Meta:ordering=['at','pk']

class Analyzer(TimeStamped):
    name=models.CharField(max_length=140)
    serial=models.CharField(max_length=100,unique=True)
    location=models.CharField(max_length=120,blank=True)
    method=models.CharField(max_length=180,blank=True)
    status=models.CharField(max_length=20,choices=[(x,x.title()) for x in ('active','maintenance','quarantined','retired')],default='active')
    last_calibrated=models.DateTimeField(null=True,blank=True)
    next_calibration=models.DateTimeField(null=True,blank=True)
    def __str__(self):return self.name+' / '+self.serial

class ReagentLot(TimeStamped):
    name=models.CharField(max_length=160)
    lot=models.CharField(max_length=80)
    expiry=models.DateField()
    quantity=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    unit=models.CharField(max_length=32,default='tests')
    analyzer=models.ForeignKey(Analyzer,on_delete=models.SET_NULL,null=True,blank=True)
    quarantined=models.BooleanField(default=False)
    class Meta:constraints=[models.UniqueConstraint(fields=['name','lot'],name='labplus_reagent_name_lot')]
    @property
    def usable(self):return not self.quarantined and self.expiry>=timezone.localdate() and self.quantity>0

class QualityControl(TimeStamped):
    analyzer=models.ForeignKey(Analyzer,on_delete=models.PROTECT,related_name='qc_runs')
    parameter=models.ForeignKey('hospital.LabParameter',on_delete=models.PROTECT)
    lot=models.CharField(max_length=80)
    level=models.CharField(max_length=40,default='normal')
    observed=models.DecimalField(max_digits=12,decimal_places=4)
    target=models.DecimalField(max_digits=12,decimal_places=4)
    sd=models.DecimalField(max_digits=12,decimal_places=4)
    passed=models.BooleanField(default=False,editable=False)
    z_score=models.DecimalField(max_digits=12,decimal_places=4,default=0,editable=False)
    reviewed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    note=models.TextField(blank=True)
    def clean(self):
        if self.sd is None or self.sd<=0:raise ValidationError('SD must be positive.')
    def save(self,*args,**kwargs):
        self.full_clean()
        self.z_score=(self.observed-self.target)/self.sd
        self.passed=abs(self.z_score)<=2
        super().save(*args,**kwargs)

class CriticalCommunication(TimeStamped):
    value=models.ForeignKey('hospital.LabResultValue',on_delete=models.PROTECT,related_name='critical_communications')
    contacted_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    contacted_person=models.CharField(max_length=180)
    method=models.CharField(max_length=20,choices=[(x,x.title()) for x in ('phone','in_person','secure_message')])
    contacted_at=models.DateTimeField(default=timezone.now)
    readback=models.TextField()
    escalation=models.TextField(blank=True)
    def clean(self):
        if self.value_id and self.value.flag not in ('LL','HH'):raise ValidationError('Only critical values can be recorded in this log.')
        if not self.readback.strip():raise ValidationError('Read-back confirmation is required.')

class LabIncident(TimeStamped):
    TYPES=[(x,x.replace('_',' ').title()) for x in ('specimen','quality_control','instrument','result_correction','other')]
    type=models.CharField(max_length=22,choices=TYPES)
    title=models.CharField(max_length=180)
    description=models.TextField()
    resolution=models.TextField(blank=True)
    closed_at=models.DateTimeField(null=True,blank=True)
    reporter=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    specimen=models.ForeignKey(Specimen,null=True,blank=True,on_delete=models.PROTECT)
