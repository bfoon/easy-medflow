import hashlib, hmac, json
from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import *

CLINICAL_DISCLAIMER='Decision support only. Clinician verification required. No drug-interaction or dosing engine is configured.'
def availability(medication):
    return StockBatch.objects.filter(medication=medication,expiry__gte=timezone.localdate()).aggregate(total=Sum('quantity'))['total'] or 0

def prescription_warnings(encounter,medication,quantity):
    allergies=list(encounter.patient.allergies.filter(status='active').values('substance','reaction','severity'))
    names=' '.join([medication.name,medication.generic_name]).casefold()
    # Exact-name screening only. No synonyms, classes, cross-reactivity or interactions; do not treat absence as safe.
    possible=[a for a in allergies if a['substance'].strip() and a['substance'].casefold().strip() in names]
    return {'possible_allergy_matches':possible,'documented_allergies':allergies,'inventory_available':availability(medication),'insufficient_stock':availability(medication)<quantity,'disclaimer':CLINICAL_DISCLAIMER}

@transaction.atomic
def dispense(prescription,actor):
    p=Prescription.objects.select_for_update().select_related('encounter__patient','medication').get(pk=prescription.pk)
    if p.state!='signed':raise ValidationError('Prescription must be signed and not already dispensed')
    if not p.allergy_reviewed:raise ValidationError('Clinician must document allergy review')
    if prescription_warnings(p.encounter,p.medication,p.quantity)['possible_allergy_matches'] and not p.override_reason.strip():raise ValidationError('Possible allergy match requires documented clinical override')
    batches=list(StockBatch.objects.select_for_update().filter(medication=p.medication,expiry__gte=timezone.localdate(),quantity__gt=0).order_by('expiry','pk'))
    if sum(b.quantity for b in batches)<p.quantity:raise ValidationError('Insufficient unexpired stock')
    remaining=p.quantity
    for batch in batches:
        q=min(remaining,batch.quantity)
        if q:
            batch.quantity-=q; batch.save(update_fields=['quantity'])
            Dispense.objects.create(prescription=p,batch=batch,quantity=q,dispensed_by=actor)
            remaining-=q
        if not remaining:break
    p.state='dispensed';p.save(update_fields=['state'])
    AuditEvent.objects.create(actor=actor,action='dispense',target=f'prescription:{p.pk}',details={'quantity':p.quantity})
    return p

@transaction.atomic
def assign_bed(encounter,bed):
    b=Bed.objects.select_for_update().get(pk=bed.pk)
    if b.state!='available':raise ValidationError('Bed is not available')
    if Admission.objects.filter(encounter__patient=encounter.patient,discharged_at__isnull=True).exists():raise ValidationError('Patient has an active admission')
    a=Admission.objects.create(encounter=encounter,bed=b)
    b.state='occupied';b.save(update_fields=['state'])
    return a

@transaction.atomic
def discharge(admission):
    a=Admission.objects.select_for_update().get(pk=admission.pk)
    if a.discharged_at:raise ValidationError('Already discharged')
    b=Bed.objects.select_for_update().get(pk=a.bed_id)
    a.discharged_at=timezone.now();a.save(update_fields=['discharged_at'])
    b.state='cleaning';b.save(update_fields=['state'])
    return a

def document_bytes(kind,instance):
    if kind=='form':
        data={'id':instance.pk,'definition':instance.definition_id,'patient':instance.patient_id,'values':instance.values,'schema_snapshot':instance.schema_snapshot}
    else:
        data={'id':instance.pk,'encounter':instance.encounter_id,'medication':instance.medication_id,'directions':instance.directions,'quantity':instance.quantity,'override_reason':instance.override_reason}
    return json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()

@transaction.atomic
def sign_document(kind,instance,user,meaning):
    payload=document_bytes(kind,instance)
    digest=hashlib.sha256(payload).hexdigest()
    stamped=f'{kind}:{instance.pk}:{user.pk}:{meaning}:{digest}:{timezone.now().isoformat()}'
    sig=hmac.new(settings.SECRET_KEY.encode(),stamped.encode(),hashlib.sha256).hexdigest()
    fields={'submission':instance} if kind=='form' else {'prescription':instance}
    s=Signature.objects.create(signer=user,meaning=meaning,document_hash=digest,signature_hash=sig,**fields)
    AuditEvent.objects.create(actor=user,action='esign',target=f'{kind}:{instance.pk}',details={'signature_id':s.pk,'sha256':digest})
    return s

@transaction.atomic
def advance_workflow(run,user,action,comment=''):
    r=WorkflowRun.objects.select_for_update().select_related('definition','submission').get(pk=run.pk)
    if r.status!='open':raise ValidationError('Workflow already closed')
    steps=r.definition.steps
    if not isinstance(steps,list) or r.step_index>=len(steps):raise ValidationError('Invalid workflow')
    step=steps[r.step_index]
    profile=getattr(user,'hospital_staff',None)
    if not user.is_superuser and (not profile or not profile.active or profile.role!=step.get('role')):raise ValidationError('Not authorized for this step')
    if action not in ('approve','reject'):raise ValidationError('Invalid action')
    WorkflowAction.objects.create(run=r,step_index=r.step_index,action=action,actor=user,comment=comment)
    if action=='reject':r.status='rejected';r.submission.status='rejected'
    else:
        r.step_index+=1
        if r.step_index>=len(steps):r.status='approved';r.submission.status='approved'
    r.save(update_fields=['step_index','status'])
    r.submission.save(update_fields=['status'])
    return r
