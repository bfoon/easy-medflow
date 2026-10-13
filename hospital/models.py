from decimal import Decimal
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
    ROLE=[(x,x.replace('_',' ').title()) for x in ['admin','doctor','nurse','reception','lab','radiology','pharmacy','finance','management','partner','specialist']]
    user=models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='hospital_staff')
    role=models.CharField(max_length=20,choices=ROLE)
    department=models.ForeignKey(Department,null=True,blank=True,on_delete=models.SET_NULL)
    license_number=models.CharField(max_length=100,blank=True)
    active=models.BooleanField(default=True)
    specialist=models.ForeignKey('Specialist',null=True,blank=True,on_delete=models.SET_NULL,related_name='accounts',
                                 help_text='Specialist role only: the specialist this login belongs to')
    email_notifications=models.BooleanField(default=True,help_text='Also send notifications by email')
    facility=models.ForeignKey('NetworkFacility',null=True,blank=True,on_delete=models.SET_NULL,related_name='staff',
                               help_text='Partner role only: the network facility this account belongs to')
    lab_view=models.CharField(max_length=10,choices=[('body','Body map'),('clean','Charts & lists')],default='body',help_text='Preferred way to review lab results')
    def __str__(self):return f'{self.user} - {self.role}'

class Location(Tracked):
    """A town or an area within a town, with map coordinates. Patients are linked to one for maps and statistics."""
    REGIONS=[('banjul','Banjul'),('kanifing','Kanifing'),('west_coast','West Coast'),('north_bank','North Bank'),
             ('lower_river','Lower River'),('central_river','Central River'),('upper_river','Upper River'),('other','Other / outside The Gambia')]
    name=models.CharField(max_length=120)
    kind=models.CharField(max_length=8,choices=[('town','Town / village'),('area','Area within a town')],default='town')
    parent=models.ForeignKey('self',null=True,blank=True,on_delete=models.CASCADE,related_name='areas',limit_choices_to={'kind':'town'},help_text='For an area: the town it belongs to')
    region=models.CharField(max_length=16,choices=REGIONS,default='west_coast')
    latitude=models.DecimalField(max_digits=9,decimal_places=6)
    longitude=models.DecimalField(max_digits=9,decimal_places=6)
    active=models.BooleanField(default=True)
    class Meta: ordering=['region','name']; unique_together=[('name','parent')]
    @property
    def town(self):return self.parent if self.kind=='area' and self.parent_id else self
    def __str__(self):return f'{self.name}, {self.parent.name}' if self.parent_id else self.name

class Patient(Tracked):
    mrn=models.CharField(max_length=32,unique=True,editable=False)
    first_name=models.CharField(max_length=120)
    last_name=models.CharField(max_length=120)
    dob=models.DateField()
    sex=models.CharField(max_length=20,choices=[('F','Female'),('M','Male'),('X','Other / unspecified')])
    phone=models.CharField(max_length=40,blank=True)
    phone_digits=models.CharField(max_length=40,blank=True,db_index=True,editable=False,help_text='Digits of the phone, for search')
    email=models.EmailField(blank=True,help_text='Optional, for sending queue tickets and receipts')
    address=models.TextField(blank=True,verbose_name='Street / compound')
    location=models.ForeignKey('Location',null=True,blank=True,on_delete=models.SET_NULL,related_name='patients',verbose_name='Town or area')
    network_sharing=models.BooleanField(default=True,verbose_name='Share record across the E-MedFlow network',
                                        help_text='Other facilities on the platform may look up this record with the patient number and date of birth')
    emergency_contact=models.CharField(max_length=200,blank=True)
    contact_digits=models.CharField(max_length=200,blank=True,editable=False,help_text='Phone numbers in the emergency contact, digits only, for search')
    blood_group=models.CharField(max_length=5,blank=True)
    medical_alerts=models.TextField(blank=True,help_text='Human-reviewed high-priority alerts; do not replace structured allergy data')
    deceased_at=models.DateTimeField(null=True,blank=True)
    def save(self,*a,**kw):
        if not self.mrn: self.mrn=f'MF-{uuid.uuid4().hex[:10].upper()}'
        from .phones import digits, contact_digits
        self.phone_digits=digits(self.phone); self.contact_digits=contact_digits(self.emergency_contact)   # for phone search
        if kw.get('update_fields') is not None:
            kw['update_fields']=list(set(kw['update_fields'])|{'phone_digits','contact_digits'})
        super().save(*a,**kw)
    @property
    def full_name(self):return f'{self.first_name} {self.last_name}'
    @property
    def initials(self):return (self.first_name[:1]+self.last_name[:1]).upper()
    @property
    def age(self):
        if not self.dob:return None
        t=timezone.localdate()
        return t.year-self.dob.year-((t.month,t.day)<(self.dob.month,self.dob.day))
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
    category=models.CharField(max_length=20,blank=True,db_index=True,editable=False,help_text='Filed automatically from the name')
    def save(self,*a,**kw):
        from .categories import classify
        self.category=classify(self.name)
        if kw.get('update_fields') is not None and 'name' in kw['update_fields']:
            kw['update_fields']=list(set(kw['update_fields'])|{'category'})
        super().save(*a,**kw)
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
    OUTCOMES=[('resolved','Resolved'),('improved','Improved'),('no_change','No change'),('worsened','Worsened'),('referred','Referred on')]
    outcome=models.CharField(max_length=12,choices=OUTCOMES,blank=True,help_text='How the patient was at the end of this visit or course')
    outcome_notes=models.CharField(max_length=300,blank=True)
    category=models.CharField(max_length=20,blank=True,db_index=True,editable=False,help_text='Disease category, filed automatically from the diagnosis')
    def save(self,*a,**kw):
        from .categories import classify
        self.category=classify(self.diagnosis) if self.diagnosis else ''
        if kw.get('update_fields') is not None and 'diagnosis' in kw['update_fields']:
            kw['update_fields']=list(set(kw['update_fields'])|{'category'})
        super().save(*a,**kw)
    def __str__(self):return f'{self.patient.first_name} {self.patient.last_name} · {self.patient.mrn} · {self.reason[:40]} · {self.created_at:%d %b}'

class QueueReset(Tracked):
    """A manual restart of queue numbering (numbers also restart automatically every day)."""
    department=models.ForeignKey('Department',null=True,blank=True,on_delete=models.CASCADE,help_text='Blank = all departments')
    reset_at=models.DateTimeField(default=timezone.now)
    reset_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,related_name='+')
    class Meta: ordering=['-reset_at']

class QueueTicket(Tracked):
    STATES=[(x,x.title()) for x in ['waiting','called','in_service','completed','skipped','cancelled']]
    patient=models.ForeignKey(Patient,on_delete=models.PROTECT,related_name='tickets')
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT,related_name='tickets',null=True,blank=True,help_text='Leave blank to open a new visit automatically')
    department=models.ForeignKey(Department,on_delete=models.PROTECT)
    counter=models.CharField(max_length=40,blank=True,help_text='Room or desk shown on the waiting-room display, e.g. Room 3')
    ticket_number=models.CharField(max_length=30,unique=True,editable=False)
    PRIORITY=[(1,'1 · Emergency'),(2,'2 · Urgent'),(3,'3 · Standard'),(4,'4 · Non-urgent')]
    priority=models.PositiveSmallIntegerField(default=3,choices=PRIORITY,help_text='Clinical triage category; must be assessed by trained staff')
    status=models.CharField(max_length=20,choices=STATES,default='waiting')
    called_at=models.DateTimeField(null=True,blank=True)
    started_at=models.DateTimeField(null=True,blank=True)
    completed_at=models.DateTimeField(null=True,blank=True)
    display_code=models.CharField(max_length=12,blank=True,editable=False,help_text='Short code announced in the waiting room')
    def save(self,*a,**kw):
        if not self.ticket_number:self.ticket_number=f'Q-{timezone.now():%y%m%d}-{uuid.uuid4().hex[:6].upper()}'
        if not self.display_code:
            words=self.department.name.split()
            prefix=(''.join(w[0] for w in words[:2]) if len(words)>1 else words[0][:2]).upper()
            # numbers restart every day, or from the last manual restart for this department (or all departments)
            start=timezone.localtime().replace(hour=0,minute=0,second=0,microsecond=0)
            reset=QueueReset.objects.filter(models.Q(department=self.department)|models.Q(department__isnull=True),reset_at__gte=start).order_by('-reset_at').first()
            since=reset.reset_at if reset else start
            n=QueueTicket.objects.filter(department=self.department,created_at__gte=since).count()+1
            self.display_code=f'{prefix}{n:03d}'
        super().save(*a,**kw)
    def clean(self):
        if self.encounter_id and self.encounter.patient_id!=self.patient_id:raise ValidationError('Ticket patient must match encounter patient')
    @property
    def wait_minutes(self):
        end=self.called_at or timezone.now()
        return int((end-self.created_at).total_seconds()//60)
    def __str__(self):return self.display_code or self.ticket_number

class Attendance(Tracked):
    staff=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    clock_in=models.DateTimeField(default=timezone.now)
    clock_out=models.DateTimeField(null=True,blank=True)
    note=models.CharField(max_length=250,blank=True)
    def __str__(self):return f'{self.staff} @ {self.clock_in}'

BODY_SYSTEMS=[('brain','Brain & nerves'),('thyroid','Thyroid & endocrine'),('lungs','Lungs'),('heart','Heart'),
    ('blood','Blood & vessels'),('liver','Liver'),('stomach','Stomach & gut'),('pancreas','Pancreas'),
    ('kidneys','Kidneys'),('bladder','Bladder & urine'),('reproductive','Reproductive'),('bone','Bones & joints'),
    ('immune','Immune & infection')]

class LabCategory(Tracked):
    """A section of the laboratory catalogue, e.g. Hematology or Clinical Chemistry."""
    name=models.CharField(max_length=120,unique=True)
    code=models.SlugField(max_length=40,unique=True)
    color=models.CharField(max_length=7,default='#0F7B78',help_text='Hex colour used to tag the category')
    sort_order=models.PositiveSmallIntegerField(default=0)
    class Meta: ordering=['sort_order','name']; verbose_name_plural='lab categories'
    def __str__(self):return self.name

class LabTest(Tracked):
    code=models.CharField(max_length=40,unique=True)
    name=models.CharField(max_length=180)
    category=models.ForeignKey(LabCategory,null=True,blank=True,on_delete=models.SET_NULL,related_name='tests')
    body_system=models.CharField(max_length=20,choices=BODY_SYSTEMS,default='blood',help_text='Default organ for parameters of this test')
    sample_type=models.CharField(max_length=100,blank=True)
    container=models.CharField(max_length=60,blank=True,help_text='e.g. Purple-top EDTA tube')
    turnaround_hours=models.PositiveSmallIntegerField(default=24)
    description=models.TextField(blank=True)
    price=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    active=models.BooleanField(default=True)
    class Meta: ordering=['name']
    def __str__(self):return self.name

class LabParameter(Tracked):
    """One measured value within a test (an analyte), with units, reference and critical limits."""
    KIND=[('number','Number'),('choice','Choice'),('text','Free text')]
    test=models.ForeignKey(LabTest,on_delete=models.CASCADE,related_name='parameters')
    code=models.CharField(max_length=40)
    name=models.CharField(max_length=120)
    kind=models.CharField(max_length=10,choices=KIND,default='number')
    unit=models.CharField(max_length=30,blank=True)
    decimals=models.PositiveSmallIntegerField(default=1)
    ref_low=models.DecimalField(max_digits=12,decimal_places=4,null=True,blank=True)
    ref_high=models.DecimalField(max_digits=12,decimal_places=4,null=True,blank=True)
    female_ref_low=models.DecimalField(max_digits=12,decimal_places=4,null=True,blank=True,help_text='Optional female-specific range')
    female_ref_high=models.DecimalField(max_digits=12,decimal_places=4,null=True,blank=True)
    critical_low=models.DecimalField(max_digits=12,decimal_places=4,null=True,blank=True)
    critical_high=models.DecimalField(max_digits=12,decimal_places=4,null=True,blank=True)
    choices=models.JSONField(default=list,blank=True,help_text='For choice parameters, e.g. ["Negative","Positive"]')
    abnormal_choices=models.JSONField(default=list,blank=True,help_text='Choices that should be flagged, e.g. ["Positive"]')
    body_system=models.CharField(max_length=20,choices=BODY_SYSTEMS,blank=True,help_text='Overrides the test default')
    sort_order=models.PositiveSmallIntegerField(default=0)
    class Meta: ordering=['sort_order','id']; unique_together=[('test','code')]
    def __str__(self):return f'{self.test.code} · {self.name}'
    @property
    def system(self):return self.body_system or self.test.body_system
    def range_for(self,sex=None):
        if sex=='F' and self.female_ref_low is not None and self.female_ref_high is not None:
            return self.female_ref_low,self.female_ref_high
        return self.ref_low,self.ref_high
    def flag_for(self,value,sex=None):
        """N normal, L/H outside reference, LL/HH beyond critical limits, A abnormal choice, '' not assessable."""
        if value in (None,''):return ''
        if self.kind=='choice':return 'A' if value in (self.abnormal_choices or []) else 'N'
        if self.kind!='number':return ''
        from decimal import Decimal,InvalidOperation
        try:v=Decimal(str(value))
        except (InvalidOperation,ValueError):return ''
        if self.critical_low is not None and v<self.critical_low:return 'LL'
        if self.critical_high is not None and v>self.critical_high:return 'HH'
        lo,hi=self.range_for(sex)
        if lo is not None and v<lo:return 'L'
        if hi is not None and v>hi:return 'H'
        return 'N'
    def range_label(self,sex=None):
        if self.kind=='choice':return 'Expected: '+', '.join(x for x in self.choices if x not in self.abnormal_choices) if self.choices else ''
        lo,hi=self.range_for(sex)
        fmt=lambda d:f'{d.normalize():f}'
        if lo is not None and hi is not None:return f'{fmt(lo)}–{fmt(hi)}'
        if hi is not None:return f'< {fmt(hi)}'
        if lo is not None:return f'> {fmt(lo)}'
        return ''

class LabRequest(Tracked):
    """One laboratory request for a patient visit, holding every test ordered together."""
    PRIORITY=[('routine','Routine'),('urgent','Urgent'),('stat','STAT · immediately')]
    STAGES=['ordered','collected','processing','resulted','verified']
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT,related_name='lab_requests')
    requested_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='lab_requests_made')
    priority=models.CharField(max_length=10,choices=PRIORITY,default='routine')
    clinical_notes=models.TextField(blank=True,help_text='Relevant history or question for the lab')
    specimen_id=models.CharField(max_length=80,blank=True)
    collected_at=models.DateTimeField(null=True,blank=True)
    received_at=models.DateTimeField(null=True,blank=True,help_text='When the specimen arrived in the lab')
    received_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='+')
    REJECT=[('haemolysed','Haemolysed'),('clotted','Clotted'),('insufficient','Insufficient volume'),('unlabelled','Unlabelled or mislabelled'),
            ('wrong_tube','Wrong container'),('delayed','Delayed in transport'),('leaking','Leaking or broken')]
    rejection_reason=models.CharField(max_length=20,choices=REJECT,blank=True)
    rejected_at=models.DateTimeField(null=True,blank=True)
    recollect_count=models.PositiveSmallIntegerField(default=0)
    class Meta: ordering=['-created_at']
    @property
    def number(self):return f'LR-{self.pk:06d}'
    def active_orders(self):return [o for o in self.orders.all() if o.status!='cancelled']
    @property
    def stage(self):
        """The request sits at the stage of its least-advanced active test."""
        active=self.active_orders()
        if not active:return 'cancelled'
        return min((o.status for o in active),key=self.STAGES.index)
    def __str__(self):return f'{self.number} · {self.encounter.patient}'

class LabOrder(Tracked):
    STATUS=[(x,x.replace('_',' ').title()) for x in ['ordered','collected','processing','resulted','verified','cancelled']]
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT,related_name='labs')
    request=models.ForeignKey(LabRequest,on_delete=models.CASCADE,null=True,blank=True,related_name='orders')
    test=models.ForeignKey(LabTest,on_delete=models.PROTECT)
    status=models.CharField(max_length=20,choices=STATUS,default='ordered')
    specimen_id=models.CharField(max_length=80,blank=True)
    result=models.TextField(blank=True)
    reference_range=models.CharField(max_length=100,blank=True)
    abnormal=models.BooleanField(default=False)
    resulted_at=models.DateTimeField(null=True,blank=True)
    verified_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True)
    verified_at=models.DateTimeField(null=True,blank=True)
    performed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='lab_orders_performed')
    @property
    def worst_flag(self):
        flags={v.flag for v in self.values.all()}
        for f in ('HH','LL','H','L','A'):
            if f in flags:return f
        return 'N' if flags else ''
    def __str__(self):return f'{self.test} / {self.encounter.patient.mrn}'

class LabResultValue(Tracked):
    FLAGS=[('','—'),('N','Normal'),('L','Low'),('H','High'),('LL','Critical low'),('HH','Critical high'),('A','Abnormal')]
    order=models.ForeignKey(LabOrder,on_delete=models.CASCADE,related_name='values')
    parameter=models.ForeignKey(LabParameter,on_delete=models.PROTECT)
    value_number=models.DecimalField(max_digits=12,decimal_places=4,null=True,blank=True)
    value_text=models.CharField(max_length=500,blank=True)
    flag=models.CharField(max_length=2,choices=FLAGS,blank=True)
    entered_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,related_name='+')
    acknowledged_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='+')
    acknowledged_at=models.DateTimeField(null=True,blank=True)
    class Meta: unique_together=[('order','parameter')]; ordering=['parameter__sort_order','id']
    @property
    def display(self):
        if self.value_number is not None:
            return f'{round(self.value_number,self.parameter.decimals):f}'
        return self.value_text
    @property
    def is_abnormal(self):return self.flag in ('L','H','LL','HH','A')
    @property
    def is_critical(self):return self.flag in ('LL','HH')

MED_CATEGORIES=[('analgesic','Pain & fever'),('antibiotic','Antibiotics'),('antimalarial','Antimalarials'),('antiretroviral','HIV medicines'),
    ('tb','TB medicines'),('cardiovascular','Heart & blood pressure'),('diabetes','Diabetes'),('respiratory','Respiratory'),('gi','Stomach & gut'),
    ('obstetric','Maternal health'),('vitamin','Vitamins & minerals'),('fluids','IV fluids & electrolytes'),('anaesthetic','Anaesthesia'),
    ('emergency','Emergency'),('mental','Mental health'),('skin','Skin'),('eye','Eye & ear'),('vaccine','Vaccines'),('other','Other')]
MED_UNITS=[('tablet','Tablet'),('capsule','Capsule'),('sachet','Sachet'),('vial','Vial'),('ampoule','Ampoule'),('bottle','Bottle'),('bag','Bag'),
    ('tube','Tube'),('inhaler','Inhaler'),('suppository','Suppository'),('pessary','Pessary'),('dose','Dose'),('piece','Piece')]

class StockLocation(Tracked):
    """A place that holds medicine stock: the main store, the dispensing pharmacy, or a ward's stock cupboard."""
    KINDS=[('store','Main store'),('pharmacy','Dispensing pharmacy'),('ward','Ward stock'),('theatre','Theatre'),('emergency','Emergency'),('quarantine','Quarantine')]
    name=models.CharField(max_length=100,unique=True)
    kind=models.CharField(max_length=12,choices=KINDS,default='ward')
    ward=models.ForeignKey('Ward',on_delete=models.SET_NULL,null=True,blank=True,related_name='stock_locations')
    is_dispensing=models.BooleanField(default=False,help_text='Prescriptions are dispensed from this location')
    active=models.BooleanField(default=True)
    class Meta: ordering=['kind','name']
    def __str__(self):return self.name
    @classmethod
    def dispensing(cls):
        loc=cls.objects.filter(is_dispensing=True,active=True).order_by('pk').first()
        return loc or cls.objects.get_or_create(name='Main Pharmacy',defaults={'kind':'pharmacy','is_dispensing':True})[0]

class Supplier(Tracked):
    name=models.CharField(max_length=160,unique=True)
    contact_person=models.CharField(max_length=120,blank=True)
    phone=models.CharField(max_length=40,blank=True)
    email=models.EmailField(blank=True)
    address=models.CharField(max_length=250,blank=True)
    lead_time_days=models.PositiveSmallIntegerField(default=14,help_text='Usual days from order to delivery')
    active=models.BooleanField(default=True)
    notes=models.TextField(blank=True)
    class Meta: ordering=['name']
    def __str__(self):return self.name

class Medication(Tracked):
    name=models.CharField(max_length=180)
    generic_name=models.CharField(max_length=180,blank=True)
    form=models.CharField(max_length=100,blank=True)
    strength=models.CharField(max_length=100,blank=True)
    reorder_level=models.PositiveIntegerField(default=50,help_text='Order more when stock falls to this level')
    max_level=models.PositiveIntegerField(default=0,help_text='Top-up target when ordering (0 = three times the reorder level)')
    unit_price=models.DecimalField(max_digits=10,decimal_places=2,default=0,help_text='Price per tablet, capsule, sachet or unit')
    category=models.CharField(max_length=20,choices=MED_CATEGORIES,default='other')
    unit=models.CharField(max_length=12,choices=MED_UNITS,default='tablet',help_text='Smallest unit counted and issued')
    pack_size=models.PositiveIntegerField(default=1,help_text='Units per pack as supplied, e.g. 1000 tablets per tin')
    essential=models.BooleanField(default=True,help_text='On the national essential medicines list')
    controlled=models.BooleanField(default=False,help_text='Controlled drug: issues need a witness and are kept in the register')
    cold_chain=models.BooleanField(default=False,help_text='Store at 2-8 °C')
    default_supplier=models.ForeignKey(Supplier,on_delete=models.SET_NULL,null=True,blank=True,related_name='medications')
    active=models.BooleanField(default=True)
    def __str__(self):return f'{self.name} {self.strength}'
    @property
    def target_level(self):return self.max_level or self.reorder_level*3

class StockBatch(Tracked):
    medication=models.ForeignKey(Medication,on_delete=models.PROTECT,related_name='batches')
    batch_number=models.CharField(max_length=100)
    expiry=models.DateField()
    quantity=models.PositiveIntegerField(default=0)
    store=models.ForeignKey(StockLocation,on_delete=models.PROTECT,related_name='batches',null=True,blank=True)
    unit_cost=models.DecimalField(max_digits=10,decimal_places=2,default=0,help_text='Purchase cost per unit')
    supplier=models.ForeignKey(Supplier,on_delete=models.SET_NULL,null=True,blank=True,related_name='+')
    quarantined=models.BooleanField(default=False,help_text='Held back: recalled, damaged or awaiting a quality check')
    class Meta: unique_together=[('medication','batch_number','store')]
    def save(self,*a,**kw):
        if not self.store_id:self.store=StockLocation.dispensing()   # batches without a store belong to the dispensing pharmacy
        super().save(*a,**kw)
    @property
    def expired(self):return self.expiry<timezone.localdate()
    def __str__(self):return f'{self.medication} / {self.batch_number} ({self.quantity})'

FREQUENCIES=[
    ('OD','Once daily',1),('BD','Twice daily',2),('TDS','Three times daily',3),('QDS','Four times daily',4),
    ('Q4H','Every 4 hours',6),('Q6H','Every 6 hours',4),('Q8H','Every 8 hours',3),('Q12H','Every 12 hours',2),
    ('MANE','Every morning',1),('NOCTE','At night',1),('WEEKLY','Once a week',None),('STAT','Once only, now',None),('PRN','When required',None),('ASDIR','As directed',None)]
FREQ_PER_DAY={c:n for c,_,n in FREQUENCIES}
ROUTES=[('oral','By mouth'),('iv','Intravenous (IV)'),('im','Intramuscular (IM)'),('sc','Subcutaneous'),('topical','On the skin'),
        ('inhaled','Inhaled'),('sublingual','Under the tongue'),('rectal','Rectal'),('eye','Eye drops'),('ear','Ear drops'),('nasal','Nasal')]

class Prescription(Tracked):
    """One prescription for a visit. Holds one or more medicine lines (PrescriptionItem)."""
    STATES=[('draft','Draft'),('signed','Signed'),('partial','Partly dispensed'),('dispensed','Dispensed'),('cancelled','Cancelled')]
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT,related_name='prescriptions')
    notes=models.TextField(blank=True,help_text='Notes for the pharmacist')
    state=models.CharField(max_length=20,choices=STATES,default='draft')
    allergy_reviewed=models.BooleanField(default=False)
    override_reason=models.TextField(blank=True)
    signed_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL)
    signed_at=models.DateTimeField(null=True,blank=True)
    @property
    def number(self):return f'RX-{self.pk:06d}'
    def __str__(self):return f'{self.number} / {self.encounter.patient.mrn}'

class PrescriptionItem(Tracked):
    """One medicine on a prescription: what, how much, how often, how long."""
    prescription=models.ForeignKey(Prescription,on_delete=models.CASCADE,related_name='items')
    medication=models.ForeignKey(Medication,on_delete=models.PROTECT)
    dose=models.CharField(max_length=60,blank=True,help_text='Strength per dose, e.g. 500 mg')
    units_per_dose=models.DecimalField(max_digits=6,decimal_places=2,default=1,validators=[MinValueValidator(0.25)],help_text='Tablets, capsules, sachets or mL per dose')
    route=models.CharField(max_length=12,choices=ROUTES,default='oral')
    frequency=models.CharField(max_length=8,choices=[(c,l) for c,l,_ in FREQUENCIES],default='TDS')
    duration_days=models.PositiveSmallIntegerField(default=5,validators=[MinValueValidator(1)])
    quantity=models.PositiveIntegerField(validators=[MinValueValidator(1)],help_text='Total units to dispense')
    instructions=models.CharField(max_length=300,blank=True,help_text='e.g. after food, avoid alcohol')
    sort_order=models.PositiveSmallIntegerField(default=0)
    AVAILABILITY=[('','Normal'),('ordered','Ordered from supplier'),('unavailable','Not available · patient informed')]
    availability=models.CharField(max_length=12,choices=AVAILABILITY,blank=True)
    availability_note=models.CharField(max_length=300,blank=True,help_text='What the patient was told, e.g. buy at a community pharmacy')
    patient_informed_at=models.DateTimeField(null=True,blank=True)
    patient_informed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='+')
    @property
    def dispensed_quantity(self):return sum(d.quantity for d in self.dispenses.all())
    @property
    def is_dispensed(self):return self.dispensed_quantity>=self.quantity
    class Meta: ordering=['sort_order','id']
    @staticmethod
    def calculate_quantity(units_per_dose,frequency,duration_days):
        """Units needed for the course. None when it cannot be worked out (when required / once a week rounding)."""
        import math
        u=float(units_per_dose or 1);d=int(duration_days or 1)
        if frequency=='STAT':return max(1,math.ceil(u))
        if frequency=='WEEKLY':return max(1,math.ceil(u*math.ceil(d/7)))
        n=FREQ_PER_DAY.get(frequency)
        return max(1,math.ceil(u*n*d)) if n else None
    @property
    def directions(self):
        u=self.units_per_dose.normalize() if self.units_per_dose is not None else 1
        unit=(self.medication.form or 'unit').lower()
        parts=[f"{u:f} {unit}{'' if u==1 else 's'}"+(f' ({self.dose})' if self.dose else ''),self.get_route_display().lower(),
               self.get_frequency_display().lower()]
        if self.frequency=='ASDIR':
            return f"{self.medication}: as directed"+(f'. {self.instructions}' if self.instructions else '')
        if self.frequency not in ('STAT','PRN'):parts.append(f"for {self.duration_days} day{'s' if self.duration_days!=1 else ''}")
        text=' '.join(parts)
        return text[0].upper()+text[1:]+(f'. {self.instructions}' if self.instructions else '')
    def __str__(self):return f'{self.medication} · {self.directions}'

class StockRequest(Tracked):
    """A request to buy medicine the pharmacy does not have, often raised from a prescription line."""
    STATUS=[('requested','Requested'),('ordered','Ordered'),('received','Received'),('cancelled','Cancelled')]
    medication=models.ForeignKey(Medication,on_delete=models.PROTECT,related_name='stock_requests')
    quantity=models.PositiveIntegerField(validators=[MinValueValidator(1)])
    reason=models.CharField(max_length=300,blank=True)
    prescription_item=models.ForeignKey('PrescriptionItem',on_delete=models.SET_NULL,null=True,blank=True,related_name='stock_requests')
    status=models.CharField(max_length=12,choices=STATUS,default='requested')
    requested_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,related_name='+')
    received_batch=models.ForeignKey(StockBatch,on_delete=models.SET_NULL,null=True,blank=True,related_name='+')
    class Meta: ordering=['-created_at']
    def __str__(self):return f'{self.medication} × {self.quantity} ({self.get_status_display()})'

class Dispense(Tracked):
    prescription=models.ForeignKey(Prescription,on_delete=models.PROTECT,related_name='dispenses')
    item=models.ForeignKey(PrescriptionItem,on_delete=models.PROTECT,null=True,blank=True,related_name='dispenses')
    batch=models.ForeignKey(StockBatch,on_delete=models.PROTECT)
    quantity=models.PositiveIntegerField(validators=[MinValueValidator(1)])
    dispensed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)

class StockMovement(Tracked):
    """One line of the stock ledger. Every change to a batch quantity writes one of these, so each medicine has a full stock card."""
    KINDS=[('receipt','Received from supplier'),('dispense','Dispensed to patient'),('issue_out','Issued to ward'),('issue_in','Received from pharmacy'),
           ('return','Returned to stock'),('adjust','Stock-take adjustment'),('expired','Expired · written off'),('damaged','Damaged · written off'),
           ('quarantine','Quarantined'),('ward_use','Used on ward'),('opening','Opening balance')]
    medication=models.ForeignKey(Medication,on_delete=models.PROTECT,related_name='movements')
    batch=models.ForeignKey(StockBatch,on_delete=models.PROTECT,related_name='movements')
    location=models.ForeignKey(StockLocation,on_delete=models.PROTECT,related_name='movements')
    kind=models.CharField(max_length=12,choices=KINDS)
    quantity=models.IntegerField(help_text='Positive into stock, negative out of stock')
    balance_after=models.IntegerField(default=0,help_text='This medicine\'s balance at this location after the movement')
    unit_cost=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    reference=models.CharField(max_length=40,blank=True,help_text='RX-, PO-, REQ- or SC- number')
    note=models.CharField(max_length=250,blank=True)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    witness=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+',help_text='Second person for controlled drugs')
    patient=models.ForeignKey('Patient',on_delete=models.SET_NULL,null=True,blank=True,related_name='+')
    class Meta: ordering=['-created_at','-id']; indexes=[models.Index(fields=['medication','location','created_at']),models.Index(fields=['kind','created_at'])]

class PurchaseOrder(Tracked):
    STATUS=[('draft','Draft'),('sent','Sent to supplier'),('partial','Partly received'),('received','Received'),('cancelled','Cancelled')]
    FUNDING=[('budget','Hospital budget'),('programme','National programme'),('donor','Donor'),('emergency','Emergency purchase')]
    supplier=models.ForeignKey(Supplier,on_delete=models.PROTECT,related_name='orders')
    status=models.CharField(max_length=10,choices=STATUS,default='draft')
    funding=models.CharField(max_length=10,choices=FUNDING,default='budget')
    deliver_to=models.ForeignKey(StockLocation,on_delete=models.PROTECT,related_name='+',null=True,blank=True)
    expected_date=models.DateField(null=True,blank=True)
    sent_at=models.DateTimeField(null=True,blank=True)
    notes=models.TextField(blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,related_name='+')
    class Meta: ordering=['-created_at']
    @property
    def number(self):return f'PO-{self.pk:05d}'
    @property
    def total(self):return sum((l.quantity*l.unit_cost for l in self.lines.all()),Decimal('0'))
    def __str__(self):return f'{self.number} · {self.supplier}'

class PurchaseOrderLine(Tracked):
    order=models.ForeignKey(PurchaseOrder,on_delete=models.CASCADE,related_name='lines')
    medication=models.ForeignKey(Medication,on_delete=models.PROTECT)
    quantity=models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_cost=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    received_quantity=models.PositiveIntegerField(default=0)
    class Meta: ordering=['id']
    @property
    def outstanding(self):return max(0,self.quantity-self.received_quantity)
    @property
    def line_total(self):return self.quantity*self.unit_cost

class Requisition(Tracked):
    """A ward or department asking the pharmacy for stock."""
    STATUS=[('submitted','Submitted'),('approved','Approved'),('partial','Partly issued'),('issued','Issued'),('rejected','Rejected'),('cancelled','Cancelled')]
    supply_from=models.ForeignKey(StockLocation,on_delete=models.PROTECT,related_name='requisitions_out')
    deliver_to=models.ForeignKey(StockLocation,on_delete=models.PROTECT,related_name='requisitions_in')
    status=models.CharField(max_length=10,choices=STATUS,default='submitted')
    priority=models.CharField(max_length=10,choices=[('routine','Routine'),('urgent','Urgent')],default='routine')
    needed_by=models.DateField(null=True,blank=True)
    notes=models.CharField(max_length=300,blank=True)
    requested_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,related_name='+')
    approved_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='+')
    issued_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='+')
    issued_at=models.DateTimeField(null=True,blank=True)
    class Meta: ordering=['-created_at']
    @property
    def number(self):return f'REQ-{self.pk:05d}'
    def __str__(self):return f'{self.number} · {self.deliver_to}'

class RequisitionLine(Tracked):
    requisition=models.ForeignKey(Requisition,on_delete=models.CASCADE,related_name='lines')
    medication=models.ForeignKey(Medication,on_delete=models.PROTECT)
    requested=models.PositiveIntegerField(validators=[MinValueValidator(1)])
    approved=models.PositiveIntegerField(null=True,blank=True)
    issued=models.PositiveIntegerField(default=0)
    class Meta: ordering=['id']
    @property
    def to_issue(self):return max(0,(self.approved if self.approved is not None else self.requested)-self.issued)

class StockCount(Tracked):
    """A stock take for one location: count every batch, then post the differences as adjustments."""
    STATUS=[('open','Counting'),('posted','Posted'),('cancelled','Cancelled')]
    location=models.ForeignKey(StockLocation,on_delete=models.PROTECT,related_name='counts')
    status=models.CharField(max_length=10,choices=STATUS,default='open')
    started_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,related_name='+')
    posted_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='+')
    posted_at=models.DateTimeField(null=True,blank=True)
    notes=models.CharField(max_length=300,blank=True)
    class Meta: ordering=['-created_at']
    @property
    def number(self):return f'SC-{self.pk:05d}'

class StockCountLine(Tracked):
    count=models.ForeignKey(StockCount,on_delete=models.CASCADE,related_name='lines')
    batch=models.ForeignKey(StockBatch,on_delete=models.PROTECT,related_name='+')
    system_quantity=models.IntegerField()
    counted=models.PositiveIntegerField(null=True,blank=True)
    reason=models.CharField(max_length=120,blank=True)
    class Meta: ordering=['batch__medication__name','batch__expiry']
    @property
    def variance(self):return None if self.counted is None else self.counted-self.system_quantity

MODALITIES=[('xray','X-ray'),('ct','CT scan'),('mri','MRI'),('ultrasound','Ultrasound'),('ecg','ECG'),('echo','Echocardiogram'),
            ('mammogram','Mammogram'),('fluoro','Fluoroscopy'),('eeg','EEG (brain waves)')]

class ImagingOrder(Tracked):
    """An imaging study (X-ray, CT, MRI, ultrasound, ECG…) with its images and the radiologist's report."""
    STATUS=[('requested','Requested'),('acquired','Images taken'),('reported','Reported'),('cancelled','Cancelled')]
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT,related_name='imaging')
    modality=models.CharField(max_length=12,choices=MODALITIES)
    region=models.CharField(max_length=80,help_text='e.g. Chest PA, Abdomen, Left knee')
    body_system=models.CharField(max_length=20,choices=BODY_SYSTEMS,default='lungs',help_text='Where it appears on the body map')
    clinical_question=models.TextField(blank=True)
    priority=models.CharField(max_length=10,choices=[('routine','Routine'),('urgent','Urgent'),('stat','STAT · immediately')],default='routine')
    status=models.CharField(max_length=12,choices=STATUS,default='requested')
    requested_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,related_name='imaging_requested')
    performed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='imaging_performed')
    findings=models.TextField(blank=True)
    impression=models.TextField(blank=True)
    measurements=models.JSONField(default=list,blank=True,help_text='[{"label":"Ejection fraction","value":"35","unit":"%","abnormal":true}]')
    abnormal=models.BooleanField(default=False)
    reported_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='imaging_reported')
    reported_at=models.DateTimeField(null=True,blank=True)
    class Meta: ordering=['-created_at']
    @property
    def number(self):return f'IM-{self.pk:06d}'
    def __str__(self):return f'{self.number} · {self.get_modality_display()} {self.region}'

def imaging_upload_path(instance,filename):
    import os
    ext=os.path.splitext(filename)[1].lower()[:6]
    return f'imaging/{instance.order.encounter.patient_id}/{instance.order_id}/{uuid.uuid4().hex}{ext}'

class ImagingImage(Tracked):
    order=models.ForeignKey(ImagingOrder,on_delete=models.CASCADE,related_name='images')
    file=models.FileField(upload_to=imaging_upload_path)
    caption=models.CharField(max_length=120,blank=True)
    uploaded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,related_name='+')
    derived_from=models.ForeignKey('self',on_delete=models.SET_NULL,null=True,blank=True,related_name='derivatives',help_text='The original this processed copy was made from; originals are never changed')
    processing=models.JSONField(default=dict,blank=True,help_text='Steps applied to make this copy')
    annotations=models.JSONField(default=list,blank=True,help_text='Rulers, angles, regions, arrows and notes drawn on the image')
    mm_per_pixel=models.FloatField(null=True,blank=True,help_text='Calibration for real-world measurements')
    class Meta: ordering=['id']

class Ward(Tracked):
    name=models.CharField(max_length=120,unique=True)
    def __str__(self):return self.name

class Bed(Tracked):
    ward=models.ForeignKey(Ward,on_delete=models.PROTECT)
    code=models.CharField(max_length=30,unique=True)
    kind=models.CharField(max_length=20,choices=[('general','General'),('icu','ICU'),('maternity','Maternity'),('pediatric','Pediatric'),('isolation','Isolation')],default='general')
    state=models.CharField(max_length=20,choices=[('available','Available'),('occupied','Occupied'),('cleaning','Cleaning'),('maintenance','Maintenance')],default='available')
    def __str__(self):return f'{self.ward} / {self.code}'

class Admission(Tracked):
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT,related_name='admissions')
    bed=models.ForeignKey(Bed,on_delete=models.PROTECT)
    admitted_at=models.DateTimeField(default=timezone.now)
    discharged_at=models.DateTimeField(null=True,blank=True)
    discharge_notes=models.TextField(blank=True)
    def __str__(self):return f'{self.encounter.patient.mrn} / {self.bed}'

class NetworkFacility(Tracked):
    """A hospital, clinic or diagnostic centre in the referral network."""
    KIND=[('hospital','Hospital'),('clinic','Specialist clinic'),('diagnostic','Diagnostic centre'),('maternity','Maternity centre'),('rehab','Rehabilitation')]
    name=models.CharField(max_length=200,unique=True)
    kind=models.CharField(max_length=12,choices=KIND,default='hospital')
    location=models.CharField(max_length=160,blank=True)
    phone=models.CharField(max_length=40,blank=True)
    email=models.EmailField(blank=True)
    capabilities=models.CharField(max_length=400,blank=True,help_text='Comma-separated, e.g. Cath lab, ICU, MRI')
    accepts_referrals=models.BooleanField(default=True)
    class Meta: ordering=['name']
    @property
    def capability_list(self):return [c.strip() for c in self.capabilities.split(',') if c.strip()]
    def __str__(self):return self.name

class Specialist(Tracked):
    facility=models.ForeignKey(NetworkFacility,on_delete=models.CASCADE,related_name='specialists')
    name=models.CharField(max_length=160)
    title=models.CharField(max_length=60,default='Dr')
    speciality=models.CharField(max_length=120)
    bio=models.TextField(blank=True)
    languages=models.CharField(max_length=160,blank=True)
    rating=models.DecimalField(max_digits=3,decimal_places=2,default=0)
    reviews=models.PositiveIntegerField(default=0)
    consult_fee=models.PositiveIntegerField(default=0,help_text='In local currency, 0 if not applicable')
    telehealth=models.BooleanField(default=False)
    active=models.BooleanField(default=True)
    PRESENCE=[('available','Available'),('busy','Busy'),('procedure','In theatre / procedure'),('on_call','On call'),('away','Away'),('off','Off duty')]
    presence=models.CharField(max_length=12,choices=PRESENCE,default='available')
    presence_note=models.CharField(max_length=160,blank=True,help_text='e.g. In theatre until 14:00')
    where=models.CharField(max_length=160,blank=True,help_text='e.g. Kotu Heart Centre, clinic room 3; or teleconsult only')
    presence_at=models.DateTimeField(null=True,blank=True)
    class Meta: ordering=['-rating','name']
    @property
    def display_name(self):return f'{self.title} {self.name}'.strip()
    @property
    def initials(self):return ''.join(w[0] for w in self.name.split()[:2]).upper()
    def __str__(self):return f'{self.display_name} · {self.speciality}'

class SpecialistSlot(Tracked):
    specialist=models.ForeignKey(Specialist,on_delete=models.CASCADE,related_name='slots')
    start=models.DateTimeField()
    minutes=models.PositiveSmallIntegerField(default=30)
    mode=models.CharField(max_length=10,choices=[('in_person','In person'),('video','Video call')],default='in_person')
    class Meta: ordering=['start']; unique_together=[('specialist','start')]
    @property
    def is_booked(self):return hasattr(self,'referral') and self.referral is not None
    def __str__(self):return f'{self.specialist} · {self.start:%a %d %b %H:%M}'

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
    KIND=[('consultation','Specialist consultation'),('operation','Operation / procedure'),('admission','Admission / transfer'),('diagnostics','Diagnostics')]
    kind=models.CharField(max_length=14,choices=KIND,default='consultation')
    facility=models.ForeignKey(NetworkFacility,on_delete=models.PROTECT,null=True,blank=True,related_name='referrals')
    specialist=models.ForeignKey(Specialist,on_delete=models.SET_NULL,null=True,blank=True,related_name='referrals')
    slot=models.OneToOneField(SpecialistSlot,on_delete=models.SET_NULL,null=True,blank=True,related_name='referral')
    consent_to_share=models.BooleanField(default=False,help_text='Patient agreed that their records may be shared with the receiving facility')
    planned_date=models.DateField(null=True,blank=True,help_text='Planned operation or admission date')
    direction=models.CharField(max_length=3,choices=[('out','Sent by this hospital'),('in','Received from a network facility')],default='out')
    from_facility=models.ForeignKey(NetworkFacility,on_delete=models.SET_NULL,null=True,blank=True,related_name='referrals_sent')
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='referrals_created')
    decline_reason=models.CharField(max_length=300,blank=True)
    shared_at=models.DateTimeField(null=True,blank=True,help_text='When the referrer sent the patient record (only after acceptance)')
    locked_at=models.DateTimeField(null=True,blank=True,help_text='When the case closed; the receiver then sees de-identified data only')
    @property
    def number(self):return f'RF-{self.pk:06d}'
    @property
    def shared(self):
        """The receiver sees the patient's identifiable record only after accepting, once the referrer has sent it with the
        patient's consent, and only until the case is closed (then it is locked and only de-identified data remain)."""
        return bool(self.consent_to_share and self.shared_at and not self.locked_at and self.status in ('accepted','transferred'))
    def __str__(self):return f'{self.encounter.patient.mrn} -> {self.destination}'

class ReferralTask(Tracked):
    """A preparation item between the two facilities, e.g. 'Send latest ECG' or 'Book theatre'."""
    SIDES=[('sender','Referring hospital'),('receiver','Receiving facility')]
    KIND=[('test','Test'),('form','Form to complete'),('document','Document / result'),('preparation','Preparation'),('other','Other')]
    referral=models.ForeignKey(Referral,on_delete=models.CASCADE,related_name='tasks')
    requested_by_side=models.CharField(max_length=10,choices=SIDES)
    assigned_to_side=models.CharField(max_length=10,choices=SIDES)
    kind=models.CharField(max_length=12,choices=KIND,default='preparation')
    title=models.CharField(max_length=200)
    details=models.TextField(blank=True)
    lab_test=models.ForeignKey('LabTest',on_delete=models.SET_NULL,null=True,blank=True)
    form=models.ForeignKey('FormDefinition',on_delete=models.SET_NULL,null=True,blank=True)
    due=models.DateField(null=True,blank=True)
    status=models.CharField(max_length=10,choices=[('open','Open'),('done','Done'),('cancelled','Cancelled')],default='open')
    response=models.TextField(blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,related_name='+')
    completed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='+')
    completed_at=models.DateTimeField(null=True,blank=True)
    class Meta: ordering=['status','due','id']
    @property
    def overdue(self):return self.status=='open' and self.due and self.due<timezone.localdate()

class FormDefinition(Tracked):
    name=models.CharField(max_length=200)
    slug=models.SlugField(unique=True)
    schema=models.JSONField(default=dict,help_text='{"fields":[{"key":"reason","label":"Reason","type":"textarea","required":true}]}')
    published=models.BooleanField(default=False)
    version=models.PositiveIntegerField(default=1)
    description=models.CharField(max_length=300,blank=True)
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
    steps=models.JSONField(default=list,blank=True,help_text='Legacy: ordered list of {"name":"Nurse review","role":"nurse"}; used when there is no graph')
    graph=models.JSONField(default=dict,blank=True,help_text='Flow graph {"nodes":[…],"edges":[…]}, see hospital/flows.py')
    form=models.ForeignKey(FormDefinition,null=True,blank=True,on_delete=models.SET_NULL,related_name='workflows',help_text='Form whose answers the flow can check')
    description=models.CharField(max_length=300,blank=True)
    active=models.BooleanField(default=True)
    def __str__(self):return self.name

class WorkflowRun(Tracked):
    definition=models.ForeignKey(WorkflowDefinition,on_delete=models.PROTECT)
    submission=models.ForeignKey(FormSubmission,on_delete=models.PROTECT)
    step_index=models.PositiveIntegerField(default=0,help_text='Number of approval steps completed')
    status=models.CharField(max_length=20,choices=[('open','In progress'),('returned','Returned for changes'),('approved','Approved'),('rejected','Rejected'),('cancelled','Cancelled')],default='open')
    graph=models.JSONField(default=dict,blank=True,help_text='The flow as it was when this run started')
    state=models.JSONField(default=dict,blank=True,help_text='Engine state: active steps, join arrivals')
    round=models.PositiveSmallIntegerField(default=1)
    started_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name='+')
    completed_at=models.DateTimeField(null=True,blank=True)
    def __str__(self):return f'{self.definition} / {self.submission_id}'

class WorkflowAction(Tracked):
    run=models.ForeignKey(WorkflowRun,on_delete=models.PROTECT,related_name='actions')
    step_index=models.PositiveIntegerField()
    action=models.CharField(max_length=20,choices=[('approve','Approve'),('reject','Reject'),('return','Return for changes'),('review','Acknowledge'),('fill','Fill in')])
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


# ============================================================== finance
class Tariff(Tracked):
    """Price list for services that are not lab tests or medicines (those carry their own price)."""
    CATEGORY=[('consultation','Consultation'),('imaging','Imaging'),('bed','Bed / ward'),('procedure','Procedure'),('other','Other')]
    code=models.SlugField(max_length=40,unique=True)
    name=models.CharField(max_length=160)
    category=models.CharField(max_length=14,choices=CATEGORY)
    amount=models.DecimalField(max_digits=10,decimal_places=2)
    active=models.BooleanField(default=True)
    class Meta: ordering=['category','name']
    def __str__(self):return f'{self.name} · D{self.amount}'

class Invoice(Tracked):
    STATUS=[('draft','Draft'),('issued','Issued'),('partial','Part paid'),('paid','Paid'),('void','Void')]
    patient=models.ForeignKey(Patient,on_delete=models.PROTECT,related_name='invoices')
    encounter=models.ForeignKey(Encounter,on_delete=models.PROTECT,null=True,blank=True,related_name='invoices')
    status=models.CharField(max_length=8,choices=STATUS,default='draft')
    issued_at=models.DateTimeField(null=True,blank=True)
    due_date=models.DateField(null=True,blank=True)
    discount=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    discount_reason=models.CharField(max_length=200,blank=True)
    insurer=models.CharField(max_length=120,blank=True)
    policy_number=models.CharField(max_length=60,blank=True)
    insurance_cover=models.PositiveSmallIntegerField(default=0,validators=[MinValueValidator(0)],help_text='Percent of the bill the insurer pays')
    notes=models.CharField(max_length=300,blank=True)
    void_reason=models.CharField(max_length=200,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,related_name='+')
    class Meta: ordering=['-created_at']
    @property
    def number(self):return f'INV-{self.pk:06d}'
    @property
    def subtotal(self):return sum((l.total for l in self.lines.all()),Decimal('0'))
    @property
    def after_discount(self):return max(Decimal('0'),self.subtotal-self.discount)
    @property
    def insurance_share(self):return (self.after_discount*self.insurance_cover/100).quantize(Decimal('0.01'))
    @property
    def patient_share(self):return self.after_discount-self.insurance_share
    @property
    def total(self):return self.after_discount
    @property
    def paid(self):return sum((p.amount for p in self.payments.all() if not p.voided),Decimal('0'))
    @property
    def balance(self):return max(Decimal('0'),self.total-self.paid)
    @property
    def insurer_paid(self):return sum((p.amount for p in self.payments.all() if not p.voided and p.method=='insurance'),Decimal('0'))
    @property
    def patient_paid(self):return self.paid-self.insurer_paid
    @property
    def patient_balance(self):return max(Decimal('0'),self.patient_share-self.patient_paid)
    @property
    def insurer_balance(self):return max(Decimal('0'),self.insurance_share-self.insurer_paid)
    def refresh_status(self):
        if self.status in ('draft','void'):return
        paid=self.paid
        self.status='paid' if paid>=self.total and self.total>0 else 'partial' if paid>0 else 'issued'
    def __str__(self):return f'{self.number} · {self.patient}'

class InvoiceLine(Tracked):
    CATEGORY=[('consultation','Consultation'),('lab','Laboratory'),('imaging','Imaging'),('pharmacy','Pharmacy'),('bed','Bed / ward'),('procedure','Procedure'),('other','Other')]
    invoice=models.ForeignKey(Invoice,on_delete=models.CASCADE,related_name='lines')
    category=models.CharField(max_length=14,choices=CATEGORY)
    description=models.CharField(max_length=200)
    quantity=models.DecimalField(max_digits=8,decimal_places=2,default=1)
    unit_price=models.DecimalField(max_digits=10,decimal_places=2)
    source=models.CharField(max_length=60,blank=True,help_text='What was billed, e.g. lab_order:12. Prevents billing the same item twice.')
    class Meta: ordering=['category','id']
    @property
    def total(self):return (self.quantity*self.unit_price).quantize(Decimal('0.01'))

class Payment(Tracked):
    METHOD=[('cash','Cash'),('wave','Wave'),('afrimoney','Afrimoney'),('qmoney','QMoney'),('card','Card'),('bank','Bank transfer'),('insurance','Insurance')]
    invoice=models.ForeignKey(Invoice,on_delete=models.PROTECT,related_name='payments')
    amount=models.DecimalField(max_digits=10,decimal_places=2,validators=[MinValueValidator(Decimal('0.01'))])
    method=models.CharField(max_length=10,choices=METHOD)
    reference=models.CharField(max_length=80,blank=True,help_text='Mobile money or card transaction reference')
    received_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    received_at=models.DateTimeField(default=timezone.now)
    voided=models.BooleanField(default=False)
    void_reason=models.CharField(max_length=200,blank=True)
    class Meta: ordering=['-received_at']
    @property
    def receipt_number(self):return f'RCP-{self.pk:06d}'


class MedicationAdministration(Tracked):
    """One dose given (or not given) to an inpatient, against a scheduled time from the prescription."""
    STATUS=[('given','Given'),('refused','Refused'),('held','Held'),('missed','Missed'),('unavailable','Not available')]
    item=models.ForeignKey('PrescriptionItem',on_delete=models.CASCADE,related_name='administrations')
    scheduled_for=models.DateTimeField(help_text='The dose time this record answers; for when-required doses, the time given')
    status=models.CharField(max_length=12,choices=STATUS,default='given')
    given_at=models.DateTimeField(default=timezone.now)
    given_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    note=models.CharField(max_length=200,blank=True)
    class Meta: ordering=['scheduled_for']; unique_together=[('item','scheduled_for')]


class Notification(Tracked):
    """An in-app notification (the bell), optionally also emailed."""
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='notifications')
    kind=models.CharField(max_length=30,default='info')
    title=models.CharField(max_length=200)
    body=models.CharField(max_length=400,blank=True)
    url=models.CharField(max_length=300,blank=True)
    read_at=models.DateTimeField(null=True,blank=True)
    emailed_at=models.DateTimeField(null=True,blank=True)
    class Meta: ordering=['-created_at']; indexes=[models.Index(fields=['user','read_at'])]


# ============================================================== laboratory management
LAB_SECTIONS=[('haematology','Haematology'),('chemistry','Clinical chemistry'),('microbiology','Microbiology'),('serology','Serology & immunology'),('urinalysis','Urinalysis'),('blood_gas','Blood gas')]

class Analyzer(Tracked):
    STATUS=[('online','Online'),('qc_hold','QC hold'),('maintenance','Maintenance'),('down','Down')]
    name=models.CharField(max_length=120)
    section=models.CharField(max_length=20,choices=LAB_SECTIONS)
    model_name=models.CharField(max_length=120,blank=True)
    serial=models.CharField(max_length=80,blank=True)
    status=models.CharField(max_length=12,choices=STATUS,default='online')
    status_note=models.CharField(max_length=200,blank=True)
    last_maintenance=models.DateField(null=True,blank=True)
    next_maintenance=models.DateField(null=True,blank=True)
    class Meta: ordering=['section','name']
    def __str__(self):return self.name

class AnalyzerLog(Tracked):
    analyzer=models.ForeignKey(Analyzer,on_delete=models.CASCADE,related_name='logs')
    kind=models.CharField(max_length=12,choices=[('maintenance','Maintenance'),('calibration','Calibration'),('fault','Fault'),('status','Status change')])
    note=models.CharField(max_length=300)
    by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,related_name='+')
    class Meta: ordering=['-created_at']

class QCMaterial(Tracked):
    """A control material for one test parameter on one analyser, with its target mean and SD."""
    analyzer=models.ForeignKey(Analyzer,on_delete=models.CASCADE,related_name='qc_materials')
    parameter=models.ForeignKey('LabParameter',on_delete=models.CASCADE,related_name='qc_materials')
    level=models.CharField(max_length=10,choices=[('L1','Level 1 (low)'),('L2','Level 2 (normal)'),('L3','Level 3 (high)')])
    lot=models.CharField(max_length=40)
    mean=models.DecimalField(max_digits=10,decimal_places=3)
    sd=models.DecimalField(max_digits=10,decimal_places=3)
    expiry=models.DateField(null=True,blank=True)
    active=models.BooleanField(default=True)
    class Meta: ordering=['analyzer','parameter','level']
    def __str__(self):return f'{self.parameter.name} {self.level} · {self.analyzer}'

class QCRun(Tracked):
    material=models.ForeignKey(QCMaterial,on_delete=models.CASCADE,related_name='runs')
    value=models.DecimalField(max_digits=10,decimal_places=3)
    status=models.CharField(max_length=10,choices=[('accepted','Accepted'),('warning','Warning'),('rejected','Rejected')],default='accepted')
    rules=models.CharField(max_length=80,blank=True,help_text='Westgard rules broken, e.g. 1-3s, 2-2s')
    comment=models.CharField(max_length=200,blank=True)
    by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,related_name='+')
    class Meta: ordering=['-created_at']
    @property
    def z(self):return float((self.value-self.material.mean)/self.material.sd) if self.material.sd else 0.0

class Reagent(Tracked):
    name=models.CharField(max_length=160)
    analyzer=models.ForeignKey(Analyzer,on_delete=models.SET_NULL,null=True,blank=True,related_name='reagents')
    lot=models.CharField(max_length=40)
    expiry=models.DateField()
    quantity=models.PositiveIntegerField(default=0)
    unit=models.CharField(max_length=30,default='tests')
    reorder_level=models.PositiveIntegerField(default=50)
    opened_at=models.DateField(null=True,blank=True)
    class Meta: ordering=['expiry','name']
    @property
    def low(self):return self.quantity<=self.reorder_level
    @property
    def days_left(self):return (self.expiry-timezone.localdate()).days

class CriticalCall(Tracked):
    """A critical result phoned through to the clinical team, with read-back confirmation."""
    value=models.OneToOneField('LabResultValue',on_delete=models.CASCADE,related_name='critical_call')
    called_to=models.CharField(max_length=120,blank=True,help_text='Name and role of the person informed')
    called_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='+')
    called_at=models.DateTimeField(null=True,blank=True)
    read_back=models.BooleanField(default=False,help_text='The receiver read the result back correctly')
    note=models.CharField(max_length=200,blank=True)
    class Meta: ordering=['called_at','-created_at']


from .models_care import BedsideState, BedsideObservation, InjuryAssessment  # noqa: E402,F401
from .models_studio import (FormVersion, FormDraft, WorkflowTask, WorkflowEvent, SignatureProfile, Envelope,  # noqa: E402,F401
                            EnvelopeRecipient, EnvelopeField, EnvelopeEvent)
from .models_evidence import ReferenceRange, ParameterGuidance, EvidenceItem, EvidenceFetch, AISuggestion  # noqa: E402,F401
from .models_reports import DoctorReport, ReportAttachment, ReportAssist  # noqa: E402,F401
from .models_drflow import DrFlowAsk  # noqa: E402,F401
