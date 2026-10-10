import json
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import transaction
from django.db.models import Q,Sum
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .forms import *
from .models import *
from .services import *

# Base authorization: staff accounts are provisioned by administrators; no public signup.
ROLES={
 'clinical':{'doctor','nurse','admin'},
 'reception':{'reception','nurse','admin'},
 'pharmacy':{'pharmacy','admin'},
 'lab':{'lab','doctor','admin'},
 'beds':{'nurse','admin','management'},
 'studio':{'admin','management'},
 'all':{'admin','doctor','nurse','reception','lab','pharmacy','finance','management'},
}
def authorize(request,role='all'):
    if request.user.is_superuser:return
    p=getattr(request.user,'hospital_staff',None)
    if not p or not p.active or p.role not in ROLES[role]:raise PermissionDenied('Your account is not authorized for this clinical module')

def audit(request,action,target,details=None):
    AuditEvent.objects.create(actor=request.user,action=action,target=target,details=details or {},ip_address=request.META.get('REMOTE_ADDR'))

def edit_page(request,formclass,title,return_to,role='all',save=None):
    authorize(request,role)
    form=formclass(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            obj=save(form) if save else form.save()
            audit(request,'create',f'{obj._meta.label}:{obj.pk}')
            messages.success(request,f'{title} saved')
            return redirect(return_to)
        except (ValidationError,ValueError) as exc:form.add_error(None,str(exc))
    return render(request,'hospital/form.html',{'form':form,'title':title})

@login_required
def dashboard(request):
    authorize(request)
    return render(request,'hospital/dashboard.html',{'patients':Patient.objects.count(),'waiting':QueueTicket.objects.filter(status='waiting').count(),'open_encounters':Encounter.objects.filter(status='open').count(),'beds_free':Bed.objects.filter(state='available').count(),'referrals_open':Referral.objects.exclude(status__in=['completed','cancelled']).count(),'prescriptions_pending':Prescription.objects.filter(state='signed').count()})
@login_required
def patients(request):
    authorize(request)
    q=request.GET.get('q','').strip()[:100]
    qs=Patient.objects.order_by('-created_at')
    if q:qs=qs.filter(Q(first_name__icontains=q)|Q(last_name__icontains=q)|Q(mrn__icontains=q)|Q(phone__icontains=q))
    return render(request,'hospital/list.html',{'title':'Patient Registry','rows':qs[:100],'columns':['MRN / patient'],'create_url':'patient_new','patient_list':True,'q':q})
@login_required
def patient_new(request):return edit_page(request,PatientForm,'Register Patient','patients','reception')
@login_required
def patient_chart(request,pk):
    authorize(request)
    p=get_object_or_404(Patient,pk=pk)
    audit(request,'view_chart',f'patient:{p.pk}')
    return render(request,'hospital/chart.html',{'p':p,'allergies':p.allergies.order_by('-created_at'),'conditions':p.conditions.order_by('-created_at'),'encounters':p.encounters.select_related('clinician').order_by('-created_at')[:50],'prescriptions':Prescription.objects.filter(encounter__patient=p).select_related('medication').order_by('-created_at')[:100],'labs':LabOrder.objects.filter(encounter__patient=p).select_related('test').order_by('-created_at')[:100],'referrals':Referral.objects.filter(encounter__patient=p).order_by('-created_at'),'admissions':Admission.objects.filter(encounter__patient=p).select_related('bed').order_by('-admitted_at'),'submissions':p.submissions.select_related('definition').order_by('-created_at'),'available_forms':FormDefinition.objects.filter(published=True)})
@login_required
def encounter_new(request):return edit_page(request,EncounterForm,'New Clinical Encounter','patients','clinical')
@login_required
def queue(request):
    authorize(request)
    return render(request,'hospital/queue.html',{'tickets':QueueTicket.objects.select_related('patient','department').exclude(status__in=['completed','cancelled']).order_by('priority','created_at')[:200]})
@login_required
def ticket_new(request):return edit_page(request,TicketForm,'Create Queue Ticket','queue','reception')
@login_required
@require_POST
def ticket_transition(request,pk,state):
    authorize(request,'reception')
    allowed={'waiting':{'called','cancelled'},'called':{'in_service','skipped','waiting'},'in_service':{'completed'},'skipped':{'waiting'}}
    with transaction.atomic():
        t=get_object_or_404(QueueTicket.objects.select_for_update(),pk=pk)
        if state not in allowed.get(t.status,set()):return HttpResponseBadRequest('Invalid status transition')
        t.status=state
        if state=='called':t.called_at=timezone.now()
        t.save(update_fields=['status','called_at'])
        audit(request,'queue_transition',f'ticket:{t.pk}',{'status':state})
    return redirect('queue')
@login_required
def referrals(request):
    authorize(request)
    return render(request,'hospital/list.html',{'title':'Referral Management','rows':Referral.objects.select_related('encounter__patient').order_by('-created_at')[:150],'create_url':'referral_new'})
@login_required
def referral_new(request):
    def save(form):
        o=form.save(commit=False)
        if o.status=='sent':o.sent_at=timezone.now()
        o.save();return o
    return edit_page(request,ReferralForm,'Create Referral','referrals','clinical',save)
@login_required
def labs(request):
    authorize(request)
    return render(request,'hospital/list.html',{'title':'Laboratory Orders','rows':LabOrder.objects.select_related('encounter__patient','test').order_by('-created_at')[:150],'create_url':'lab_new'})
@login_required
def lab_new(request):return edit_page(request,LabOrderForm,'Order Laboratory Test','labs','lab')
@login_required
def pharmacy(request):
    authorize(request)
    meds=Medication.objects.filter(active=True).order_by('name')[:200]
    rx=Prescription.objects.select_related('encounter__patient','medication').order_by('-created_at')[:100]
    return render(request,'hospital/pharmacy.html',{'medications':[(m,availability(m)) for m in meds],'prescriptions':rx})
@login_required
def prescription_new(request):
    def save(form):
        p=form.save(commit=False)
        warnings=prescription_warnings(p.encounter,p.medication,p.quantity)
        if not p.allergy_reviewed:raise ValidationError('Clinician must explicitly review allergy history before saving')
        if warnings['possible_allergy_matches'] and not p.override_reason.strip():raise ValidationError('POTENTIAL ALLERGY MATCH: document clinical justification or select alternative')
        p.save()
        audit(request,'prescribing_warning_review',f'prescription:{p.pk}',{'possible_exact_match':bool(warnings['possible_allergy_matches']),'stock':warnings['inventory_available']})
        return p
    return edit_page(request,PrescriptionForm,'New Prescription (Draft)','pharmacy','clinical',save)
@login_required
@require_POST
def prescription_sign(request,pk):
    authorize(request,'clinical')
    if not (request.user.is_superuser or getattr(request.user.hospital_staff,'role',None)=='doctor'):raise PermissionDenied('Prescriber role required')
    with transaction.atomic():
        p=get_object_or_404(Prescription.objects.select_for_update().select_related('encounter__patient','medication'),pk=pk)
        if p.state!='draft':return HttpResponseBadRequest('Not a draft')
        warnings=prescription_warnings(p.encounter,p.medication,p.quantity)
        if not p.allergy_reviewed or (warnings['possible_allergy_matches'] and not p.override_reason.strip()):return HttpResponseBadRequest('Allergy review incomplete')
        p.state='signed';p.signed_by=request.user;p.signed_at=timezone.now();p.save(update_fields=['state','signed_by','signed_at'])
        sign_document('prescription',p,request.user,'Prescriber authorization')
    messages.success(request,'Prescription signed; pharmacist must review before dispensing')
    return redirect('pharmacy')
@login_required
@require_POST
def prescription_dispense(request,pk):
    authorize(request,'pharmacy')
    try:dispense(get_object_or_404(Prescription,pk=pk),request.user);messages.success(request,'Dispense recorded')
    except ValidationError as e:messages.error(request,str(e))
    return redirect('pharmacy')
@login_required
def beds(request):
    authorize(request)
    return render(request,'hospital/beds.html',{'beds':Bed.objects.select_related('ward').order_by('ward__name','code'),'admissions':Admission.objects.filter(discharged_at__isnull=True).select_related('encounter__patient','bed')})
@login_required
def admission_new(request):
    def save(form):return assign_bed(form.cleaned_data['encounter'],form.cleaned_data['bed'])
    return edit_page(request,AdmissionForm,'Admit Patient','beds','beds',save)
@login_required
@require_POST
def admission_discharge(request,pk):
    authorize(request,'beds')
    try:discharge(get_object_or_404(Admission,pk=pk));audit(request,'discharge',f'admission:{pk}')
    except ValidationError as e:messages.error(request,str(e))
    return redirect('beds')
@login_required
def attendance(request):
    authorize(request)
    active=Attendance.objects.filter(staff=request.user,clock_out__isnull=True).order_by('-clock_in').first()
    if request.method=='POST':
        with transaction.atomic():
            active=Attendance.objects.select_for_update().filter(staff=request.user,clock_out__isnull=True).order_by('-clock_in').first()
            action=request.POST.get('action')
            if action=='in' and not active:Attendance.objects.create(staff=request.user)
            elif action=='out' and active:active.clock_out=timezone.now();active.save(update_fields=['clock_out'])
            audit(request,'attendance',f'employee:{request.user.pk}',{'action':action})
        return redirect('attendance')
    return render(request,'hospital/attendance.html',{'active':active,'recent':Attendance.objects.filter(staff=request.user).order_by('-clock_in')[:20]})
@login_required
def studio(request):
    authorize(request)
    return render(request,'hospital/studio.html',{'forms':FormDefinition.objects.order_by('name'),'workflows':WorkflowDefinition.objects.order_by('name'),'submissions':FormSubmission.objects.select_related('definition','patient').order_by('-created_at')[:50],'runs':WorkflowRun.objects.filter(status='open').select_related('definition','submission__patient')[:50]})
@login_required
def form_definition_new(request):
    def save(form):
        obj=form.save(commit=False)
        fields=obj.schema.get('fields',[]) if isinstance(obj.schema,dict) else None
        if not isinstance(fields,list) or len(fields)>60:raise ValidationError('schema.fields must be a list of at most 60 fields')
        keys=set()
        for f in fields:
            if not isinstance(f,dict) or f.get('type') not in ['text','textarea','date','number','checkbox','select'] or not isinstance(f.get('key'),str) or not f['key'].isidentifier() or f['key'] in keys:raise ValidationError('Invalid/duplicate form field key or type')
            keys.add(f['key'])
            if f['type']=='select' and (not isinstance(f.get('options'),list) or len(f['options'])>100 or any(not isinstance(o,str) for o in f['options'])):raise ValidationError('Select requires list of string options')
        obj.save();return obj
    return edit_page(request,FormDefinitionForm,'Create Form Schema','studio','studio',save)
@login_required
def workflow_definition_new(request):
    def save(form):
        obj=form.save(commit=False)
        if not isinstance(obj.steps,list) or not 1<=len(obj.steps)<=20:raise ValidationError('Steps must be a list of 1–20 entries')
        for s in obj.steps:
            if not isinstance(s,dict) or s.get('role') not in ROLES['all'] or not isinstance(s.get('name'),str):raise ValidationError('Each step requires a name and valid staff role')
        obj.save();return obj
    return edit_page(request,WorkflowDefinitionForm,'Create Approval Workflow','studio','studio',save)
@login_required
def fill_form(request,pk,patient_id):
    authorize(request,'clinical')
    definition=get_object_or_404(FormDefinition,pk=pk,published=True)
    patient=get_object_or_404(Patient,pk=patient_id)
    fields=definition.schema.get('fields',[])
    dynamic={}
    for fld in fields:
        key=fld['key'];typ=fld['type'];label=fld.get('label',key)
        if typ=='checkbox':f=forms.BooleanField(label=label,required=False)
        elif typ=='select':f=forms.ChoiceField(label=label,choices=[(x,x) for x in fld.get('options',[])],required=bool(fld.get('required')))
        elif typ=='number':f=forms.DecimalField(label=label,required=bool(fld.get('required')))
        elif typ=='date':f=forms.DateField(label=label,required=bool(fld.get('required')),widget=forms.DateInput(attrs={'type':'date'}))
        else:f=forms.CharField(label=label,required=bool(fld.get('required')),widget=forms.Textarea if typ=='textarea' else forms.TextInput,max_length=4000)
        f.widget.attrs['class']='form-control';dynamic[key]=f
    DynamicForm=type('DynamicForm',(forms.Form,),dynamic)
    form=DynamicForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            s=FormSubmission.objects.create(definition=definition,patient=patient,values=json.loads(json.dumps(form.cleaned_data,default=str)),schema_snapshot=definition.schema,submitted_by=request.user)
            workflow_id=request.POST.get('workflow')
            if workflow_id:
                definition_workflow=get_object_or_404(WorkflowDefinition,pk=workflow_id,active=True)
                WorkflowRun.objects.create(definition=definition_workflow,submission=s)
            audit(request,'submit_form',f'form_submission:{s.pk}')
        return redirect('patient_chart',pk=patient.pk)
    return render(request,'hospital/form.html',{'form':form,'title':f'{definition.name}: {patient}','workflows':WorkflowDefinition.objects.filter(active=True)})
@login_required
@require_POST
def submission_sign(request,pk):
    authorize(request,'clinical')
    sub=get_object_or_404(FormSubmission,pk=pk)
    if sub.status=='rejected':return HttpResponseBadRequest('Cannot sign rejected submission')
    if Signature.objects.filter(submission=sub).exists():return HttpResponseBadRequest('Already signed')
    sign_document('form',sub,request.user,'Reviewed and signed')
    return redirect('patient_chart',pk=sub.patient_id)
@login_required
@require_POST
def workflow_act(request,pk,action):
    authorize(request)
    try:advance_workflow(get_object_or_404(WorkflowRun,pk=pk),request.user,action,request.POST.get('comment','')[:1000]);audit(request,'workflow_action',f'workflow_run:{pk}',{'action':action})
    except ValidationError as e:messages.error(request,str(e))
    return redirect('studio')
