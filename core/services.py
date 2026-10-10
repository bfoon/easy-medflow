from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .models import AuditEvent, StockBatch, Bed, Admission, Dispense

def audit(user,action,obj,description=''):
    AuditEvent.objects.create(actor=user if user.is_authenticated else None,action=action,object_type=type(obj).__name__,object_id=str(obj.pk),description=description[:255])

def clinical_alerts(patient,medicine=None):
    """Conservative, informational *exact-name* checks; not a validated clinical decision support engine."""
    alerts=[]
    if patient.medical_alert:alerts.append(('danger','Medical alert: '+patient.medical_alert))
    allergies=list(patient.allergies.all())
    if allergies:alerts.append(('warning','Known allergies: '+', '.join(f'{a.substance} ({a.severity})' for a in allergies)))
    else:alerts.append(('warning','Allergy information is not recorded. Confirm allergies before prescribing.'))
    if medicine:
        terms={medicine.name.strip().casefold(),medicine.generic_name.strip().casefold()}- {''}
        matches=[a for a in allergies if a.substance.strip().casefold() in terms]
        if matches:alerts.append(('danger','EXACT NAME ALLERGY MATCH: '+', '.join(a.substance for a in matches)+'. Do not sign; clinical review required.'))
        if medicine.available_quantity < 1:alerts.append(('warning','No unexpired pharmacy stock recorded for this medicine.'))
    alerts.append(('secondary','Interaction, contraindication, dose and cross-reactivity checking are NOT implemented. Independently verify.'))
    return alerts

@transaction.atomic
def dispense_prescription(rx,user):
    from .models import Prescription
    rx=Prescription.objects.select_for_update().select_related('medicine').get(pk=rx.pk)
    if rx.status!='signed':raise ValueError('Only signed prescriptions may be dispensed')
    qty=rx.quantity
    batches=StockBatch.objects.select_for_update().filter(medicine=rx.medicine,expiry_date__gte=timezone.localdate(),quantity__gt=0).order_by('expiry_date','pk')
    selected=list(batches)
    if sum(batch.quantity for batch in selected)<qty:raise ValueError('Insufficient unexpired stock')
    remaining=qty
    for batch in selected:
        take=min(batch.quantity,remaining)
        batch.quantity-=take
        batch.save(update_fields=['quantity','updated_at'])
        remaining-=take
        if not remaining:break
    Dispense.objects.create(prescription=rx,dispensed_by=user,quantity=qty)
    rx.status='dispensed'
    rx.save(update_fields=['status','updated_at'])
    audit(user,'dispense',rx,'Pharmacy dispense, quantity '+str(qty))
    return rx

@transaction.atomic
def admit(patient,encounter,bed,user,reason):
    bed=Bed.objects.select_for_update().get(pk=bed.pk)
    if bed.status!='available':raise ValueError('Bed no longer available')
    if Admission.objects.filter(patient=patient,discharged_at__isnull=True).exists():raise ValueError('Patient already admitted')
    record=Admission.objects.create(patient=patient,encounter=encounter,bed=bed,reason=reason)
    bed.status='occupied';bed.save(update_fields=['status','updated_at'])
    audit(user,'admission',record)
    return record

@transaction.atomic
def discharge(record,user):
    record=Admission.objects.select_for_update().get(pk=record.pk)
    if record.discharged_at:raise ValueError('Patient already discharged')
    bed=Bed.objects.select_for_update().get(pk=record.bed_id)
    record.discharged_at=timezone.now();record.save(update_fields=['discharged_at','updated_at'])
    bed.status='cleaning';bed.save(update_fields=['status','updated_at'])
    audit(user,'discharge',record)
