import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError

class Tracked(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta: abstract=True

class Department(Tracked):
    name=models.CharField(max_length=120,unique=True)
    def __str__(self): return self.name

class StaffProfile(Tracked):
    ROLE=[(x,x.replace('_',' ').title()) for x in ['admin','doctor','nurse','reception','lab','pharmacy','finance','management']]
    user=models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='hospital_staff')
    role=models.CharField(max_length=20,choices=ROLE)
    department=models.ForeignKey(Department,null=True,blank=True,on_delete=models.SET_NULL)
    license_number=models.CharField(max_length=100,blank=True)
    active=models.BooleanField(default=True)
    def __str__(self):return f'{self.user} - {self.role}'

class Patient(Tracked):
    mrn=models.CharField(max_length=32,unique=True,editable=False)
    first_name=models.CharField(max_length=120)
    last_name=models.CharField(max_length=120)
    dob=models.DateField()
    sex=models.CharField(max_length=20,choices=[('F','Female'),('M','Male'),('X','Other / unspecified')])
    phone=models.CharField(max_length=40,blank=True)
    address=models.TextField(blank=True)
    emergency_contact=models.CharField(max_length=200,blank=True)
    blood_group=models.CharField(max_length=5,blank=True)
    medical_alerts=models.TextField(blank=True,help_text='Human-reviewed high-priority alerts; do not replace structured allergy data')
    deceased_at=models.DateTimeField(null=True,blank=True)
    def save(self,*a,**kw):
        if not self.mrn: self.mrn=f'MF-{uuid.uuid4().hex[:10].upper()}'
        super().save(*a,**kw)
    def __str__(self):return f'{self.first_name} {self.last_name} ({self.mrn})'

class Allergy(Tracked):
    patient=models.ForeignKey(Patient,on_delete=models.PROTECT,related_name='allergies')
    substance=models.CharField(max_length=150)
    reaction=models.CharField(max_length=200)
    severity=models.CharField(max_length=20,choices=[('unknown','Unknown'),('mild','Mild'),('moderate','Moderate'),('severe','Severe')],default='unknown')
    status=models.CharField(max_length=20,choices=[('active','Active'),('inactive','Inactive'),('entered-in-error','Entered in error')],default='active')
    verified_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL)
    def __str__(self):return f'{self.patient.mrn}: {self.substance}'

class Condition(Tracked):
    patient=models.ForeignKey(Patient,on_delete=models.PROTECT,related_name='conditions')
    code=models.CharField(max_length=50,blank=True)
    name=models.CharField(max_length=250)
    status=models.CharField(max_length=30,choices=[('active','Active'),('resolved','Resolved'),('history','History')],default='active')
    onset=models.DateField(null=True,blank=True)
    notes=models.TextField(blank=True)
    def __str__(self):return self.name

class Encounter(Tracked):
    STATUS=[(x,x.title()) for x in ['open','completed','cancelled']]
    patient=models.ForeignKey(Patient,on_delete=models.PROTECT,related_name='encounters')
    clinician=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL)
    department=models.ForeignKey(Department,null=True,blank=True,on_delete=models.SET_NULL)
    reason=models.CharField(max_length=300)
    symptoms=models.TextField(blank=True)
    assessment=models.TextField(blank=True)
    plan=models.TextField(blank=True)
    diagnosis=models.TextField(blank=True)
    vitals=models.JSONField(default=dict,blank=True,help_text='Measurements with units (e.g. bp, heart_rate, temperature_c)')
    status=models.CharField(max_length=20,choices=STATUS,default='open')
    completed_at=models.DateTimeField(null=True,blank=True)
    def __str__(self):return f'{self.patient.mrn} - {self.created_at:%Y-%m-%d} / {self.status}'

class QueueTicket(Tracked):
    STATES=[(x,x.title()) for x in ['waiting','called','in_service','completed','skipped','cancelled']]
    patient=models.ForeignKey(Patient,on_delete=models.PROTECT,related_name='tickets')
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT,related_name='tickets')
    department=models.ForeignKey(Department,on_delete=models.PROTECT)
    ticket_number=models.CharField(max_length=30,unique=True,editable=False)
    priority=models.PositiveSmallIntegerField(default=3,help_text='1 urgent, 3 normal; requires staff clinical triage')
    status=models.CharField(max_length=20,choices=STATES,default='waiting')
    called_at=models.DateTimeField(null=True,blank=True)
    def save(self,*a,**kw):
        if not self.ticket_number:self.ticket_number=f'Q-{timezone.now():%y%m%d}-{uuid.uuid4().hex[:6].upper()}'
        super().save(*a,**kw)
    def clean(self):
        if self.encounter_id and self.encounter.patient_id!=self.patient_id:raise ValidationError('Ticket patient must match encounter patient')
    def __str__(self):return self.ticket_number

class Attendance(Tracked):
    staff=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    clock_in=models.DateTimeField(default=timezone.now)
    clock_out=models.DateTimeField(null=True,blank=True)
    note=models.CharField(max_length=250,blank=True)
    def __str__(self):return f'{self.staff} @ {self.clock_in}'

class LabTest(Tracked):
    code=models.CharField(max_length=40,unique=True)
    name=models.CharField(max_length=180)
    sample_type=models.CharField(max_length=100,blank=True)
    price=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    active=models.BooleanField(default=True)
    def __str__(self):return self.name

class LabOrder(Tracked):
    STATUS=[(x,x.replace('_',' ').title()) for x in ['ordered','collected','processing','resulted','verified','cancelled']]
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT,related_name='labs')
    test=models.ForeignKey(LabTest,on_delete=models.PROTECT)
    status=models.CharField(max_length=20,choices=STATUS,default='ordered')
    specimen_id=models.CharField(max_length=80,blank=True)
    result=models.TextField(blank=True)
    reference_range=models.CharField(max_length=100,blank=True)
    verified_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True)
    verified_at=models.DateTimeField(null=True,blank=True)
    def __str__(self):return f'{self.test} / {self.encounter.patient.mrn}'

class Medication(Tracked):
    name=models.CharField(max_length=180)
    generic_name=models.CharField(max_length=180,blank=True)
    form=models.CharField(max_length=100,blank=True)
    strength=models.CharField(max_length=100,blank=True)
    active=models.BooleanField(default=True)
    def __str__(self):return f'{self.name} {self.strength}'

class StockBatch(Tracked):
    medication=models.ForeignKey(Medication,on_delete=models.PROTECT,related_name='batches')
    batch_number=models.CharField(max_length=100)
    expiry=models.DateField()
    quantity=models.PositiveIntegerField(default=0)
    location=models.CharField(max_length=100,default='Main Pharmacy')
    class Meta: unique_together=[('medication','batch_number','location')]
    def __str__(self):return f'{self.medication} / {self.batch_number} ({self.quantity})'

class Prescription(Tracked):
    STATES=[(x,x.title()) for x in ['draft','signed','dispensed','cancelled']]
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT,related_name='prescriptions')
    medication=models.ForeignKey(Medication,on_delete=models.PROTECT)
    directions=models.TextField()
    quantity=models.PositiveIntegerField(validators=[MinValueValidator(1)])
    state=models.CharField(max_length=20,choices=STATES,default='draft')
    allergy_reviewed=models.BooleanField(default=False)
    override_reason=models.TextField(blank=True)
    signed_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL)
    signed_at=models.DateTimeField(null=True,blank=True)
    def __str__(self):return f'{self.medication} / {self.encounter.patient.mrn}'

class Dispense(Tracked):
    prescription=models.ForeignKey(Prescription,on_delete=models.PROTECT,related_name='dispenses')
    batch=models.ForeignKey(StockBatch,on_delete=models.PROTECT)
    quantity=models.PositiveIntegerField(validators=[MinValueValidator(1)])
    dispensed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)

class Ward(Tracked):
    name=models.CharField(max_length=120,unique=True)
    def __str__(self):return self.name

class Bed(Tracked):
    ward=models.ForeignKey(Ward,on_delete=models.PROTECT)
    code=models.CharField(max_length=30,unique=True)
    state=models.CharField(max_length=20,choices=[('available','Available'),('occupied','Occupied'),('cleaning','Cleaning'),('maintenance','Maintenance')],default='available')
    def __str__(self):return f'{self.ward} / {self.code}'

class Admission(Tracked):
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT,related_name='admissions')
    bed=models.ForeignKey(Bed,on_delete=models.PROTECT)
    admitted_at=models.DateTimeField(default=timezone.now)
    discharged_at=models.DateTimeField(null=True,blank=True)
    discharge_notes=models.TextField(blank=True)
    def __str__(self):return f'{self.encounter.patient.mrn} / {self.bed}'

class Referral(Tracked):
    STATUS=[(x,x.replace('_',' ').title()) for x in ['draft','sent','accepted','declined','transferred','completed','cancelled']]
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT,related_name='referrals')
    destination=models.CharField(max_length=250)
    speciality=models.CharField(max_length=120,blank=True)
    reason=models.TextField()
    urgency=models.CharField(max_length=20,choices=[('routine','Routine'),('urgent','Urgent'),('emergency','Emergency')],default='routine')
    status=models.CharField(max_length=20,choices=STATUS,default='draft')
    contact=models.CharField(max_length=200,blank=True)
    transfer_notes=models.TextField(blank=True)
    accepted_by=models.CharField(max_length=180,blank=True)
    sent_at=models.DateTimeField(null=True,blank=True)
    completed_at=models.DateTimeField(null=True,blank=True)
    def __str__(self):return f'{self.encounter.patient.mrn} -> {self.destination}'

class FormDefinition(Tracked):
    name=models.CharField(max_length=200)
    slug=models.SlugField(unique=True)
    schema=models.JSONField(default=dict,help_text='{"fields":[{"key":"reason","label":"Reason","type":"textarea","required":true}]}')
    published=models.BooleanField(default=False)
    version=models.PositiveIntegerField(default=1)
    def __str__(self):return self.name

class FormSubmission(Tracked):
    definition=models.ForeignKey(FormDefinition,on_delete=models.PROTECT,related_name='submissions')
    patient=models.ForeignKey(Patient,on_delete=models.PROTECT,related_name='submissions')
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT,null=True,blank=True)
    values=models.JSONField(default=dict)
    schema_snapshot=models.JSONField(default=dict)
    submitted_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    status=models.CharField(max_length=20,choices=[('submitted','Submitted'),('approved','Approved'),('rejected','Rejected')],default='submitted')
    def __str__(self):return f'{self.definition} / {self.patient.mrn}'

class WorkflowDefinition(Tracked):
    name=models.CharField(max_length=200)
    steps=models.JSONField(default=list,help_text='Ordered list of {"name":"Nurse review","role":"nurse"}')
    active=models.BooleanField(default=True)
    def __str__(self):return self.name

class WorkflowRun(Tracked):
    definition=models.ForeignKey(WorkflowDefinition,on_delete=models.PROTECT)
    submission=models.ForeignKey(FormSubmission,on_delete=models.PROTECT)
    step_index=models.PositiveIntegerField(default=0)
    status=models.CharField(max_length=20,choices=[('open','Open'),('approved','Approved'),('rejected','Rejected')],default='open')
    def __str__(self):return f'{self.definition} / {self.submission_id}'

class WorkflowAction(Tracked):
    run=models.ForeignKey(WorkflowRun,on_delete=models.PROTECT,related_name='actions')
    step_index=models.PositiveIntegerField()
    action=models.CharField(max_length=20,choices=[('approve','Approve'),('reject','Reject')])
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    comment=models.TextField(blank=True)

class Signature(Tracked):
    submission=models.ForeignKey(FormSubmission,null=True,blank=True,on_delete=models.PROTECT)
    prescription=models.ForeignKey(Prescription,null=True,blank=True,on_delete=models.PROTECT)
    signer=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    meaning=models.CharField(max_length=200,default='Reviewed and approved')
    document_hash=models.CharField(max_length=64)
    signature_hash=models.CharField(max_length=64)
    signed_at=models.DateTimeField(default=timezone.now)
    def clean(self):
        if bool(self.submission_id)==bool(self.prescription_id):raise ValidationError('Sign exactly one document')
    def __str__(self):return f'Signature by {self.signer} @ {self.signed_at}'

class AuditEvent(models.Model):
    occurred_at=models.DateTimeField(default=timezone.now,db_index=True)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL)
    action=models.CharField(max_length=80)
    target=models.CharField(max_length=180)
    details=models.JSONField(default=dict)
    ip_address=models.GenericIPAddressField(null=True,blank=True)
    class Meta: ordering=['-occurred_at']
    def __str__(self):return f'{self.occurred_at} {self.actor} {self.action} {self.target}'
