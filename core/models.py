import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone

class Timestamped(models.Model):
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta: abstract=True

class Department(Timestamped):
    name=models.CharField(max_length=120,unique=True)
    code=models.CharField(max_length=20,unique=True)
    def __str__(self):return self.name

class StaffProfile(Timestamped):
    ROLES=[('doctor','Doctor'),('nurse','Nurse'),('reception','Reception'),('lab','Lab'),('pharmacy','Pharmacy'),('manager','Manager'),('billing','Billing')]
    user=models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='staff_profile')
    role=models.CharField(max_length=20,choices=ROLES)
    department=models.ForeignKey(Department,on_delete=models.SET_NULL,null=True,blank=True)
    license_number=models.CharField(max_length=100,blank=True)
    active=models.BooleanField(default=True)
    def __str__(self):return f'{self.user.get_username()} ({self.role})'

class Patient(Timestamped):
    mrn=models.CharField(max_length=24,unique=True,editable=False)
    first_name=models.CharField(max_length=100)
    last_name=models.CharField(max_length=100)
    dob=models.DateField(null=True,blank=True)
    sex=models.CharField(max_length=20,choices=[('female','Female'),('male','Male'),('other','Other'),('unknown','Unknown')],default='unknown')
    phone=models.CharField(max_length=40,blank=True)
    address=models.TextField(blank=True)
    emergency_contact=models.CharField(max_length=200,blank=True)
    blood_type=models.CharField(max_length=5,blank=True)
    medical_alert=models.TextField(blank=True,help_text='Prominent safety alert; verify against clinical record')
    def save(self,*args,**kwargs):
        if not self.mrn:self.mrn='PT-'+uuid.uuid4().hex[:10].upper()
        super().save(*args,**kwargs)
    def __str__(self):return f'{self.mrn} — {self.first_name} {self.last_name}'

class Allergy(Timestamped):
    patient=models.ForeignKey(Patient,on_delete=models.CASCADE,related_name='allergies')
    substance=models.CharField(max_length=180)
    reaction=models.CharField(max_length=255,blank=True)
    severity=models.CharField(max_length=20,choices=[('unknown','Unknown'),('mild','Mild'),('moderate','Moderate'),('severe','Severe')],default='unknown')
    verified=models.BooleanField(default=False)
    class Meta: unique_together=[('patient','substance')]
    def __str__(self):return self.substance

class Problem(Timestamped):
    patient=models.ForeignKey(Patient,on_delete=models.CASCADE,related_name='problems')
    title=models.CharField(max_length=200)
    code=models.CharField(max_length=30,blank=True,help_text='ICD/SNOMED code when available')
    onset=models.DateField(null=True,blank=True)
    active=models.BooleanField(default=True)
    notes=models.TextField(blank=True)

class Encounter(Timestamped):
    STATUS=[('open','Open'),('completed','Completed'),('cancelled','Cancelled')]
    patient=models.ForeignKey(Patient,on_delete=models.PROTECT,related_name='encounters')
    department=models.ForeignKey(Department,on_delete=models.PROTECT)
    clinician=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='encounters')
    chief_complaint=models.TextField()
    history=models.TextField(blank=True)
    examination=models.TextField(blank=True)
    assessment=models.TextField(blank=True)
    plan=models.TextField(blank=True)
    diagnosis=models.CharField(max_length=255,blank=True)
    status=models.CharField(max_length=15,choices=STATUS,default='open')
    completed_at=models.DateTimeField(null=True,blank=True)
    def __str__(self):return f'Encounter #{self.pk} {self.patient.mrn}'

class VitalSign(Timestamped):
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT,related_name='vitals')
    temperature_c=models.DecimalField(max_digits=4,decimal_places=1,null=True,blank=True)
    pulse_bpm=models.PositiveSmallIntegerField(null=True,blank=True)
    systolic=models.PositiveSmallIntegerField(null=True,blank=True)
    diastolic=models.PositiveSmallIntegerField(null=True,blank=True)
    spo2=models.PositiveSmallIntegerField(null=True,blank=True)
    weight_kg=models.DecimalField(max_digits=6,decimal_places=2,null=True,blank=True)
    recorded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True)

class QueueTicket(Timestamped):
    STATUS=[('waiting','Waiting'),('called','Called'),('in_service','In service'),('done','Completed'),('cancelled','Cancelled')]
    number=models.CharField(max_length=25,unique=True)
    patient=models.ForeignKey(Patient,on_delete=models.PROTECT,related_name='tickets')
    department=models.ForeignKey(Department,on_delete=models.PROTECT)
    priority=models.CharField(max_length=15,choices=[('routine','Routine'),('urgent','Urgent')],default='routine')
    status=models.CharField(max_length=20,choices=STATUS,default='waiting')
    called_at=models.DateTimeField(null=True,blank=True)
    served_at=models.DateTimeField(null=True,blank=True)
    def __str__(self):return self.number

class Medicine(Timestamped):
    name=models.CharField(max_length=200,unique=True)
    generic_name=models.CharField(max_length=200,blank=True)
    formulation=models.CharField(max_length=100,blank=True)
    reorder_threshold=models.PositiveIntegerField(default=10)
    active=models.BooleanField(default=True)
    def __str__(self):return self.name
    @property
    def available_quantity(self):
        return sum(x.quantity for x in self.batches.filter(expiry_date__gte=timezone.localdate(),quantity__gt=0))

class StockBatch(Timestamped):
    medicine=models.ForeignKey(Medicine,on_delete=models.PROTECT,related_name='batches')
    batch_number=models.CharField(max_length=100)
    expiry_date=models.DateField()
    quantity=models.PositiveIntegerField(default=0)
    unit_cost=models.DecimalField(max_digits=11,decimal_places=2,default=0)
    class Meta: unique_together=[('medicine','batch_number')]

class Prescription(Timestamped):
    STATUS=[('draft','Draft'),('signed','Signed'),('dispensed','Dispensed'),('cancelled','Cancelled')]
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT,related_name='prescriptions')
    medicine=models.ForeignKey(Medicine,on_delete=models.PROTECT)
    dose=models.CharField(max_length=100)
    frequency=models.CharField(max_length=120)
    duration=models.CharField(max_length=120)
    quantity=models.PositiveIntegerField(default=1)
    instructions=models.TextField(blank=True)
    status=models.CharField(max_length=15,choices=STATUS,default='draft')
    signed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True)
    signed_at=models.DateTimeField(null=True,blank=True)
    safety_acknowledgement=models.TextField(blank=True)
    def __str__(self):return f'{self.medicine} for {self.encounter.patient}'

class Dispense(Timestamped):
    prescription=models.OneToOneField(Prescription,on_delete=models.PROTECT,related_name='dispense')
    dispensed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    quantity=models.PositiveIntegerField()

class LabTest(Timestamped):
    name=models.CharField(max_length=160,unique=True)
    specimen=models.CharField(max_length=100,blank=True)
    available=models.BooleanField(default=True)
    turnaround_hours=models.PositiveIntegerField(default=24)
    def __str__(self):return self.name

class LabOrder(Timestamped):
    STATUS=[('ordered','Ordered'),('collected','Collected'),('processing','Processing'),('resulted','Resulted'),('cancelled','Cancelled')]
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT,related_name='lab_orders')
    test=models.ForeignKey(LabTest,on_delete=models.PROTECT)
    status=models.CharField(max_length=15,choices=STATUS,default='ordered')
    result=models.TextField(blank=True)
    reference_range=models.CharField(max_length=200,blank=True)
    abnormal=models.BooleanField(default=False)
    resulted_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True)
    resulted_at=models.DateTimeField(null=True,blank=True)

class Bed(Timestamped):
    ward=models.CharField(max_length=100)
    number=models.CharField(max_length=30)
    type=models.CharField(max_length=30,choices=[('general','General'),('private','Private'),('icu','ICU'),('maternity','Maternity')],default='general')
    status=models.CharField(max_length=20,choices=[('available','Available'),('occupied','Occupied'),('cleaning','Cleaning'),('maintenance','Maintenance')],default='available')
    class Meta: unique_together=[('ward','number')]
    def __str__(self):return f'{self.ward} / {self.number}'

class Admission(Timestamped):
    patient=models.ForeignKey(Patient,on_delete=models.PROTECT,related_name='admissions')
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT)
    bed=models.ForeignKey(Bed,on_delete=models.PROTECT,related_name='admissions')
    admitted_at=models.DateTimeField(default=timezone.now)
    discharged_at=models.DateTimeField(null=True,blank=True)
    reason=models.TextField()

class Attendance(Timestamped):
    staff=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='attendance_entries')
    clock_in=models.DateTimeField(default=timezone.now)
    clock_out=models.DateTimeField(null=True,blank=True)
    class Meta: ordering=['-clock_in']

class AuditEvent(models.Model):
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True)
    action=models.CharField(max_length=100)
    object_type=models.CharField(max_length=100)
    object_id=models.CharField(max_length=80)
    description=models.CharField(max_length=255,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-created_at']

class Invoice(Timestamped):
    patient=models.ForeignKey(Patient,on_delete=models.PROTECT,related_name='invoices')
    encounter=models.ForeignKey(Encounter,on_delete=models.SET_NULL,null=True,blank=True)
    total=models.DecimalField(max_digits=12,decimal_places=2)
    status=models.CharField(max_length=15,choices=[('unpaid','Unpaid'),('part_paid','Part paid'),('paid','Paid')],default='unpaid')
    notes=models.CharField(max_length=200,blank=True)

class AIReviewLog(Timestamped):
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT)
    requested_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    provider=models.CharField(max_length=100,default='disabled')
    status=models.CharField(max_length=20,default='not_enabled')
    # Store redacted metadata, not full prompts or identifiable clinical output.
    rationale=models.TextField(blank=True)
