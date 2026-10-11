import hashlib, hmac, json
from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import *

CLINICAL_DISCLAIMER='Decision support only. Clinician verification required. No drug-interaction or dosing engine is configured.'
def availability(medication,location=None):
    """Usable stock (in date, not quarantined) at the dispensing pharmacy, or at `location`."""
    loc=location or StockLocation.dispensing()
    return StockBatch.objects.filter(medication=medication,store=loc,expiry__gte=timezone.localdate(),quarantined=False).aggregate(total=Sum('quantity'))['total'] or 0

def prescription_warnings(encounter,medication,quantity):
    allergies=list(encounter.patient.allergies.filter(status='active').values('substance','reaction','severity'))
    # Name and drug-class screening (e.g. penicillin allergy flags amoxicillin) plus known cross-reactions as cautions.
    # It does not cover every class or interaction; absence of a warning is not proof of safety.
    from .clinical import allergy_matches
    possible,cautions=allergy_matches(allergies,medication)
    return {'possible_allergy_matches':possible,'allergy_cautions':cautions,'documented_allergies':allergies,'inventory_available':availability(medication),'insufficient_stock':availability(medication)<quantity,'disclaimer':CLINICAL_DISCLAIMER}

def prescription_check(prescription):
    """Safety summary for every line of a prescription: possible allergy matches and stock."""
    lines=[]
    for item in prescription.items.select_related('medication'):
        w=prescription_warnings(prescription.encounter,item.medication,item.quantity)
        lines.append({'item':item,**w})
    return {'lines':lines,'any_allergy':any(l['possible_allergy_matches'] for l in lines),'any_short':any(l['insufficient_stock'] for l in lines)}

@transaction.atomic
def dispense(prescription,actor,witness=None):
    """Dispense every line that is still owed, earliest-expiring stock first.

    Lines marked 'not available, patient informed' are skipped. Lines ordered from a supplier that still have no stock are
    left for later (the prescription becomes 'partly dispensed'). Any other line without enough stock stops the whole
    dispense, so nothing is handed out half-checked.
    """
    p=Prescription.objects.select_for_update().select_related('encounter__patient').get(pk=prescription.pk)
    if p.state not in ('signed','partial'):raise ValidationError('Prescription must be signed and not already fully dispensed')
    if not p.allergy_reviewed:raise ValidationError('Clinician must document allergy review')
    check=prescription_check(p)
    if check['any_allergy'] and not p.override_reason.strip():raise ValidationError('Possible allergy match requires documented clinical override')
    owed=[i for i in p.items.select_related('medication').prefetch_related('dispenses') if i.availability!='unavailable' and not i.is_dispensed]
    if not owed:raise ValidationError('Nothing left to dispense on this prescription')
    plan,waiting=[],[]
    for item in owed:
        need=item.quantity-item.dispensed_quantity
        batches=list(StockBatch.objects.select_for_update().filter(medication=item.medication,store=StockLocation.dispensing(),expiry__gte=timezone.localdate(),quarantined=False,quantity__gt=0).order_by('expiry','pk'))
        have=sum(b.quantity for b in batches)
        if have<need:
            if item.availability=='ordered':waiting.append(item);continue
            raise ValidationError(f'Not enough stock of {item.medication} (need {need}, have {have}). Order it from the supplier, or mark it not available and inform the patient.')
        plan.append((item,batches,need))
    if not plan:raise ValidationError('Still waiting for supplier stock: '+', '.join(str(i.medication) for i in waiting))
    from .pharmacy import move
    for item,batches,need in plan:
        for batch in batches:
            q=min(need,batch.quantity)
            if q:
                move(batch,-q,'dispense',actor,p.number,f'{item.medication} for {p.encounter.patient.mrn}',witness,p.encounter.patient)   # ledger + controlled-drug witness check
                Dispense.objects.create(prescription=p,item=item,batch=batch,quantity=q,dispensed_by=actor)
                need-=q
            if not need:break
    p.state='partial' if waiting else 'dispensed';p.save(update_fields=['state'])
    AuditEvent.objects.create(actor=actor,action='dispense',target=f'prescription:{p.pk}',details={'lines':len(plan),'waiting':len(waiting)})
    return p

@transaction.atomic
def receive_stock(stock_request,actor,batch_number,expiry,quantity):
    """Book supplier stock into the pharmacy and release prescription lines that were waiting for it."""
    sr=StockRequest.objects.select_for_update().get(pk=stock_request.pk)
    if sr.status in ('received','cancelled'):raise ValidationError('This supplier order is already closed')
    from .pharmacy import put
    batch=put(StockLocation.dispensing(),sr.medication,batch_number,expiry,quantity,Decimal('0'),'receipt',actor,f'SR-{sr.pk}','Supplier request received')
    sr.status,sr.received_batch='received',batch;sr.save(update_fields=['status','received_batch','updated_at'])
    PrescriptionItem.objects.filter(medication=sr.medication,availability='ordered',prescription__state__in=['draft','signed','partial']).update(availability='')
    AuditEvent.objects.create(actor=actor,action='stock_received',target=f'stock_request:{sr.pk}',details={'batch':batch_number,'quantity':quantity})
    return batch

# ------------------------------------------------------------------ similar cases (anonymised, observational)
SUCCESS={'resolved','improved'}
MIN_GROUP=3  # never show a treatment group, or any case inside it, with fewer than this many patients

def _diagnosis_term(dx):
    import re
    words=[w for w in re.findall(r'[a-z]+',(dx or '').lower()) if w not in {'suspected','acute','query','with','and','the','of','type','mild','severe','uncomplicated','upper','lower','chronic','early','review','tract','post'} and len(w)>3]
    return words[0] if words else ''

def _age_band(patient,on_date):
    if not patient.dob:return 'Age unknown'
    a=on_date.year-patient.dob.year-((on_date.month,on_date.day)<(patient.dob.month,patient.dob.day))
    if a<5:return 'Under 5'
    if a<18:return '5–17'
    lo=a//10*10;return f'{lo}–{lo+9}'

def case_token(encounter_id):
    from django.core import signing
    return signing.dumps(encounter_id,salt='medflow.case',compress=True)

def case_from_token(token):
    from django.core import signing
    try:return signing.loads(token,salt='medflow.case',max_age=60*60*12)
    except signing.BadSignature:return None

def similar_cases(patient,diagnosis):
    """What was prescribed for other completed visits with a similar diagnosis, and how those patients did.

    Returns regimens (groups of medicines) with at least MIN_GROUP cases. Other patients appear only as anonymous
    cases: sex, age band and outcome, no names, record numbers or dates.
    """
    term=_diagnosis_term(diagnosis)
    if not term:return {'term':'','groups':[],'total':0}
    encs=(Encounter.objects.filter(status='completed',diagnosis__icontains=term).exclude(outcome='')
          .select_related('patient').prefetch_related('prescriptions__items__medication'))
    groups={}
    for e in encs:
        meds=sorted({i.medication.name for rx in e.prescriptions.all() if rx.state!='cancelled' for i in rx.items.all()})
        key=' + '.join(meds) or 'No medicine prescribed'
        g=groups.setdefault(key,{'regimen':key,'meds':meds,'cases':[]})
        own=e.patient_id==patient.pk
        g['cases'].append({'token':case_token(e.pk),'own':own,'outcome':e.outcome,'outcome_label':e.get_outcome_display(),
                           'success':e.outcome in SUCCESS,'sex':e.patient.get_sex_display(),'age':_age_band(e.patient,e.created_at.date()),
                           'date':e.created_at if own else None,'encounter_id':e.pk if own else None})
    out=[]
    for g in groups.values():
        others=[c for c in g['cases'] if not c['own']]
        if len(g['cases'])<MIN_GROUP and not any(c['own'] for c in g['cases']):continue
        n=len(g['cases']);ok=sum(c['success'] for c in g['cases'])
        g.update(n=n,ok=ok,rate=round(ok*100/n),
                 shown=g['cases'] if len(others)>=MIN_GROUP else [c for c in g['cases'] if c['own']],  # hide others in tiny groups
                 small=len(others)<MIN_GROUP)
        g['shown']=sorted(g['shown'],key=lambda c:(not c['own'],not c['success']))[:12]
        out.append(g)
    out.sort(key=lambda g:(g['small'],-g['rate'],-g['n']))
    return {'term':term,'groups':out[:5],'total':sum(g['n'] for g in out)}

def anonymised_case(encounter_id,viewer_patient):
    """Details of one case. Another patient's case is stripped of identity and real dates, and only released when it
    belongs to a treatment group of at least MIN_GROUP patients."""
    e=(Encounter.objects.select_related('patient').prefetch_related('prescriptions__items__medication','labs__test','labs__values__parameter')
       .filter(pk=encounter_id,status='completed').first())
    if not e:return None
    own=e.patient_id==viewer_patient.pk
    if not own:
        sim=similar_cases(viewer_patient,e.diagnosis)
        token_ok=any(c.get('encounter_id') is None and case_from_token(c['token'])==e.pk for g in sim['groups'] if not g['small'] for c in g['shown'])
        if not token_ok:return None
    start=e.created_at
    rel=lambda dt:f'Day {(dt-start).days}' if dt and dt>=start else 'Day 0'
    meds=[{'medicine':str(i.medication),'directions':i.directions,'quantity':i.quantity} for rx in e.prescriptions.all() if rx.state!='cancelled' for i in rx.items.all()]
    labs=[{'test':o.test.name,'when':rel(o.resulted_at or o.created_at),'values':[{'name':v.parameter.name,'value':v.display,'unit':v.parameter.unit,'flag':v.flag} for v in o.values.all()]}
          for o in e.labs.all() if o.status in ('resulted','verified')]
    return {'own':own,'title':('This patient · '+timezone.localtime(e.created_at).strftime('%d %b %Y')) if own else 'Anonymous case',
            'sex':e.patient.get_sex_display(),'age':_age_band(e.patient,e.created_at.date()),'diagnosis':e.diagnosis,
            'outcome':e.get_outcome_display() or '—','success':e.outcome in SUCCESS,'length':rel(e.completed_at) if e.completed_at else '',
            'medicines':meds,'labs':labs,'encounter_id':e.pk if own else None}

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


# ------------------------------------------------------------------ billing
import math
from decimal import Decimal as _D
from datetime import timedelta as _td

def _tariff(code):
    return Tariff.objects.filter(code=code, active=True).first()

def open_invoice_for(encounter, user):
    """The visit's current bill (draft, issued or part-paid), or a new draft."""
    inv = encounter.invoices.exclude(status__in=['void', 'paid']).order_by('-created_at').first()
    return inv or Invoice.objects.create(patient=encounter.patient, encounter=encounter, created_by=user)

@transaction.atomic
def capture_charges(invoice):
    """Add every billable item for the visit that is not yet on any live bill. Returns the number of lines added."""
    if invoice.status in ('void', 'paid') or not invoice.encounter_id:
        return 0
    enc = invoice.encounter
    billed = set(InvoiceLine.objects.filter(invoice__patient=invoice.patient).exclude(invoice__status='void').values_list('source', flat=True))
    added = 0
    def add(cat, desc, qty, price, source):
        nonlocal added
        if source in billed or price is None or _D(price) <= 0:
            return
        InvoiceLine.objects.create(invoice=invoice, category=cat, description=desc[:200], quantity=qty, unit_price=price, source=source)
        billed.add(source); added += 1
    emergency = enc.department and enc.department.name == 'Emergency'
    t = _tariff('consultation-emergency' if emergency else 'consultation')
    if t:
        add('consultation', t.name + (f' · {enc.department}' if enc.department else ''), 1, t.amount, f'consult:{enc.pk}')
    for o in enc.labs.exclude(status='cancelled').select_related('test'):
        add('lab', o.test.name, 1, o.test.price, f'lab_order:{o.pk}')
    for im in enc.imaging.exclude(status='cancelled'):
        t = _tariff(f'imaging-{im.modality}')
        if t:
            add('imaging', f'{im.get_modality_display()} · {im.region}', 1, t.amount, f'imaging:{im.pk}')
    # One line per medicine, even when it was drawn from several stock batches. Each draw's id is kept in the
    # line's source, so no draw can ever be billed twice.
    billed_draws = {int(x) for src in billed if src.startswith('dispense:') for x in src[9:].split(',') if x.isdigit()}
    groups = {}
    for d in Dispense.objects.filter(prescription__encounter=enc).exclude(pk__in=billed_draws).select_related('item__medication', 'batch__medication').order_by('pk'):
        med = d.item.medication if d.item_id else d.batch.medication
        groups.setdefault((d.item_id, med.pk), (med, []))[1].append(d)
    for med, draws in groups.values():
        ids, qty = [str(d.pk) for d in draws], sum(d.quantity for d in draws)
        chunks, cur = [], []
        for i in ids:   # keep each source within the field length
            if len('dispense:' + ','.join(cur + [i])) > 60:
                chunks.append(cur); cur = []
            cur.append(i)
        chunks.append(cur)
        if len(chunks) == 1:
            add('pharmacy', f'{med} × {qty}', qty, med.unit_price, 'dispense:' + ','.join(ids))
        else:
            by_id = {str(d.pk): d for d in draws}
            for ch in chunks:
                q = sum(by_id[i].quantity for i in ch)
                add('pharmacy', f'{med} × {q}', q, med.unit_price, 'dispense:' + ','.join(ch))
    now = timezone.now()
    for a in enc.admissions.select_related('bed'):
        t = _tariff(f'bed-{a.bed.kind}') or _tariff('bed-general')
        if not t:
            continue
        days = max(1, math.ceil(((a.discharged_at or now) - a.admitted_at).total_seconds() / 86400))
        for n in range(1, days + 1):
            day = timezone.localtime(a.admitted_at + _td(days=n - 1))
            add('bed', f'{t.name} · {a.bed.code} · day {n} ({day:%d %b})', 1, t.amount, f'bed:{a.pk}:{n}')
    return added

@transaction.atomic
def record_payment(invoice, amount, method, reference, user):
    inv = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if inv.status not in ('issued', 'partial'):
        raise ValidationError('Issue the bill before taking payment.')
    amount = _D(str(amount)).quantize(_D('0.01'))
    if amount <= 0:
        raise ValidationError('Enter an amount above zero.')
    if amount > inv.balance:
        raise ValidationError(f'That is more than the balance of D{inv.balance}.')
    if method in ('wave', 'afrimoney', 'qmoney', 'card', 'bank') and not reference.strip():
        raise ValidationError('Enter the transaction reference for mobile money, card or bank payments.')
    pay = Payment.objects.create(invoice=inv, amount=amount, method=method, reference=reference.strip()[:80], received_by=user)
    inv.refresh_status(); inv.save(update_fields=['status', 'updated_at'])
    AuditEvent.objects.create(actor=user, action='payment', target=f'invoice:{inv.pk}', details={'amount': str(amount), 'method': method})
    return pay
