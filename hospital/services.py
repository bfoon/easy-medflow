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

def prescription_check(prescription):
    """Safety summary for every line of a prescription: possible allergy matches and stock."""
    lines=[]
    for item in prescription.items.select_related('medication'):
        w=prescription_warnings(prescription.encounter,item.medication,item.quantity)
        lines.append({'item':item,**w})
    return {'lines':lines,'any_allergy':any(l['possible_allergy_matches'] for l in lines),'any_short':any(l['insufficient_stock'] for l in lines)}

@transaction.atomic
def dispense(prescription,actor):
    """Dispense every line, earliest-expiring stock first. All lines or nothing."""
    p=Prescription.objects.select_for_update().select_related('encounter__patient').get(pk=prescription.pk)
    if p.state!='signed':raise ValidationError('Prescription must be signed and not already dispensed')
    if not p.allergy_reviewed:raise ValidationError('Clinician must document allergy review')
    items=list(p.items.select_related('medication'))
    if not items:raise ValidationError('Prescription has no medicines')
    check=prescription_check(p)
    if check['any_allergy'] and not p.override_reason.strip():raise ValidationError('Possible allergy match requires documented clinical override')
    plan=[]
    for item in items:
        batches=list(StockBatch.objects.select_for_update().filter(medication=item.medication,expiry__gte=timezone.localdate(),quantity__gt=0).order_by('expiry','pk'))
        if sum(b.quantity for b in batches)<item.quantity:
            raise ValidationError(f'Not enough unexpired stock of {item.medication} (need {item.quantity})')
        plan.append((item,batches))
    for item,batches in plan:
        remaining=item.quantity
        for batch in batches:
            q=min(remaining,batch.quantity)
            if q:
                batch.quantity-=q; batch.save(update_fields=['quantity'])
                Dispense.objects.create(prescription=p,item=item,batch=batch,quantity=q,dispensed_by=actor)
                remaining-=q
            if not remaining:break
    p.state='dispensed';p.save(update_fields=['state'])
    AuditEvent.objects.create(actor=actor,action='dispense',target=f'prescription:{p.pk}',details={'lines':len(items),'units':sum(i.quantity for i in items)})
    return p

def group_orphan_lab_orders():
    """Put any lab orders without a request into requests (same visit, ordered within five minutes = one request)."""
    current,last_enc,last_time=None,None,None
    for o in LabOrder.objects.filter(request__isnull=True).order_by('encounter_id','created_at','id'):
        if current is None or o.encounter_id!=last_enc or (o.created_at-last_time).total_seconds()>300:
            current=LabRequest.objects.create(encounter_id=o.encounter_id,specimen_id=o.specimen_id)
            LabRequest.objects.filter(pk=current.pk).update(created_at=o.created_at)
        LabOrder.objects.filter(pk=o.pk).update(request=current)
        last_enc,last_time=o.encounter_id,o.created_at

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
        data={'id':instance.pk,'encounter':instance.encounter_id,'override_reason':instance.override_reason,'notes':instance.notes,
              'items':[{'medication':i.medication_id,'dose':i.dose,'units_per_dose':str(i.units_per_dose),'route':i.route,'frequency':i.frequency,
                        'duration_days':i.duration_days,'quantity':i.quantity,'instructions':i.instructions} for i in instance.items.order_by('sort_order','id')]}
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
