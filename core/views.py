from django.contrib import messages
from django.contrib.auth.decorators import login_required,user_passes_test
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q,Count
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import *
from .forms import *
from .services import audit,clinical_alerts,dispense_prescription,admit,discharge

ROLE_PERMS={
    'dashboard': {'manager','doctor','nurse','reception','lab','pharmacy','billing'},
    'patients': {'manager','doctor','nurse','reception'},
    'clinical': {'manager','doctor','nurse'},
    'prescribe': {'doctor'},
    'queue': {'manager','reception','nurse','doctor'},
    'lab': {'manager','lab','doctor'},
    'pharmacy': {'manager','pharmacy'},
    'beds': {'manager','nurse','doctor'},
    'attendance': {'manager','doctor','nurse','reception','lab','pharmacy','billing'},
}

def allow(request,capability):
    if request.user.is_superuser:return
    profile=getattr(request.user,'staff_profile',None)
    if not profile or not profile.active or profile.role not in ROLE_PERMS[capability]:raise PermissionDenied('Your staff role does not permit this operation.')

def action_form(request, form_cls, template, title, on_save, **kwargs):
    form=form_cls(request.POST or None,**kwargs)
    if request.method=='POST' and form.is_valid():return on_save(form)
    return render(request,'core/form.html',{'form':form,'title':title})

@login_required
def dashboard(request):
    allow(request,'dashboard')
    return render(request,'core/dashboard.html',{'patients':Patient.objects.count(),'waiting':QueueTicket.objects.filter(status='waiting').count(),'available_beds':Bed.objects.filter(status='available').count(),'total_beds':Bed.objects.count(),'open_encounters':Encounter.objects.filter(status='open').count(),'labs':LabOrder.objects.exclude(status__in=['resulted','cancelled']).count(),'recent':QueueTicket.objects.select_related('patient','department').order_by('-created_at')[:10]})

@login_required
def patient_list(request):
    allow(request,'patients')
    q=request.GET.get('q','').strip()
    patients=Patient.objects.all().order_by('-created_at')
    if q:patients=patients.filter(Q(mrn__icontains=q)|Q(first_name__icontains=q)|Q(last_name__icontains=q)|Q(phone__icontains=q))
    return render(request,'core/patients.html',{'patients':patients[:100],'q':q})

@login_required
def patient_add(request):
    allow(request,'patients')
    def save(form):
        patient=form.save();audit(request.user,'create_patient',patient);messages.success(request,'Patient registered.');return redirect('patient_detail',pk=patient.pk)
    return action_form(request,PatientForm,'','Register patient',save)

@login_required
def patient_detail(request,pk):
    allow(request,'patients')
    patient=get_object_or_404(Patient,pk=pk)
    audit(request.user,'view_patient',patient)
    return render(request,'core/patient_detail.html',{'patient':patient,'alerts':clinical_alerts(patient),'encounters':patient.encounters.select_related('department','clinician').order_by('-created_at')[:30],'prescriptions':Prescription.objects.filter(encounter__patient=patient).select_related('medicine').order_by('-created_at')[:30],'labs':LabOrder.objects.filter(encounter__patient=patient).select_related('test').order_by('-created_at')[:30],'admissions':patient.admissions.select_related('bed').order_by('-admitted_at')[:15]})

@login_required
def allergy_add(request,pk):
    allow(request,'clinical')
    patient=get_object_or_404(Patient,pk=pk)
    def save(form):
        obj=form.save(commit=False);obj.patient=patient;obj.save();audit(request.user,'add_allergy',obj);return redirect('patient_detail',pk=pk)
    return action_form(request,AllergyForm,'','Record allergy',save)

@login_required
def problem_add(request,pk):
    allow(request,'clinical')
    patient=get_object_or_404(Patient,pk=pk)
    def save(form):
        obj=form.save(commit=False);obj.patient=patient;obj.save();audit(request.user,'add_problem',obj);return redirect('patient_detail',pk=pk)
    return action_form(request,ProblemForm,'','Record diagnosis / problem',save)

@login_required
def encounter_add(request,pk):
    allow(request,'clinical')
    patient=get_object_or_404(Patient,pk=pk)
    def save(form):
        obj=form.save(commit=False);obj.patient=patient;obj.clinician=request.user;obj.save();audit(request.user,'create_encounter',obj);return redirect('encounter_detail',pk=obj.pk)
    return action_form(request,EncounterForm,'','Start consultation',save)

@login_required
def encounter_detail(request,pk):
    allow(request,'clinical')
    obj=get_object_or_404(Encounter.objects.select_related('patient','department','clinician'),pk=pk)
    audit(request.user,'view_encounter',obj)
    return render(request,'core/encounter.html',{'encounter':obj,'alerts':clinical_alerts(obj.patient),'beds':Bed.objects.filter(status='available')[:30]})

@login_required
def vital_add(request,pk):
    allow(request,'clinical');encounter=get_object_or_404(Encounter,pk=pk)
    def save(form):
        obj=form.save(commit=False);obj.encounter=encounter;obj.recorded_by=request.user;obj.save();audit(request.user,'record_vitals',obj);return redirect('encounter_detail',pk=pk)
    return action_form(request,VitalForm,'','Record vital signs',save)

@login_required
def prescription_add(request,pk):
    allow(request,'prescribe');encounter=get_object_or_404(Encounter,pk=pk)
    if encounter.status!='open':return HttpResponseBadRequest('Encounter is closed')
    def save(form):
        obj=form.save(commit=False);obj.encounter=encounter;obj.save();audit(request.user,'draft_prescription',obj);messages.warning(request,'Draft only; a licensed prescriber must verify dose, interactions and allergy risks.');return redirect('encounter_detail',pk=pk)
    return action_form(request,PrescriptionForm,'','Draft prescription',save)

@login_required
@require_POST
def prescription_sign(request,pk):
    allow(request,'prescribe')
    with transaction.atomic():
        rx=get_object_or_404(Prescription.objects.select_for_update().select_related('medicine','encounter__patient'),pk=pk)
        if rx.status!='draft':return HttpResponseBadRequest('Not a draft')
        if rx.encounter.status!='open':return HttpResponseBadRequest('Encounter closed')
        alerts=clinical_alerts(rx.encounter.patient,rx.medicine)
        if any('EXACT NAME ALLERGY MATCH' in a[1] for a in alerts):
            messages.error(request,'Prescription blocked: recorded allergy exact-name match.');return redirect('encounter_detail',pk=rx.encounter_id)
        if not request.POST.get('clinical_review'):
            messages.error(request,'Clinical verification checkbox is required.');return redirect('encounter_detail',pk=rx.encounter_id)
        rx.status='signed';rx.signed_by=request.user;rx.signed_at=timezone.now();rx.safety_acknowledgement='Prescriber acknowledged need to review allergies, interactions, dosage and contraindications independently.';rx.save()
        audit(request.user,'sign_prescription',rx)
    messages.success(request,'Prescription signed.');return redirect('encounter_detail',pk=rx.encounter_id)

@login_required
def lab_add(request,pk):
    allow(request,'clinical');encounter=get_object_or_404(Encounter,pk=pk)
    def save(form):
        obj=form.save(commit=False);obj.encounter=encounter;obj.save();audit(request.user,'order_lab',obj);return redirect('encounter_detail',pk=pk)
    return action_form(request,LabOrderForm,'','Order available lab test',save)

@login_required
def queue(request):
    allow(request,'queue')
    tickets=QueueTicket.objects.select_related('patient','department').filter(created_at__date=timezone.localdate()).exclude(status__in=['done','cancelled']).order_by('-priority','created_at')
    return render(request,'core/queue.html',{'tickets':tickets})

@login_required
def ticket_add(request,pk):
    allow(request,'queue');patient=get_object_or_404(Patient,pk=pk)
    def save(form):
        obj=form.save(commit=False);obj.patient=patient
        obj.number=f'{timezone.localdate():%y%m%d}-{obj.department.code}-{uuid.uuid4().hex[:5].upper()}'
        obj.save();audit(request.user,'issue_ticket',obj);messages.success(request,'Ticket '+obj.number+' issued');return redirect('queue')
    return action_form(request,TicketForm,'','Issue queue ticket',save)

@login_required
@require_POST
def ticket_update(request,pk):
    allow(request,'queue')
    status=request.POST.get('status')
    transitions={'waiting':['called','cancelled'],'called':['in_service','waiting','cancelled'],'in_service':['done','cancelled']}
    with transaction.atomic():
        obj=get_object_or_404(QueueTicket.objects.select_for_update(),pk=pk)
        if status not in transitions.get(obj.status,[]):return HttpResponseBadRequest('Invalid transition')
        obj.status=status
        if status=='called':obj.called_at=timezone.now()
        if status=='done':obj.served_at=timezone.now()
        obj.save();audit(request.user,'ticket_status',obj,status)
    return redirect('queue')

@login_required
def pharmacy(request):
    allow(request,'pharmacy')
    rx=Prescription.objects.filter(status='signed').select_related('medicine','encounter__patient').order_by('created_at')[:60]
    medicines=Medicine.objects.filter(active=True).order_by('name')[:100]
    return render(request,'core/pharmacy.html',{'prescriptions':rx,'medicines':medicines})

@login_required
@require_POST
def dispense(request,pk):
    allow(request,'pharmacy');rx=get_object_or_404(Prescription,pk=pk)
    try:dispense_prescription(rx,request.user);messages.success(request,'Medication dispensed and inventory updated.')
    except ValueError as err:messages.error(request,str(err))
    return redirect('pharmacy')

@login_required
def laboratory(request):
    allow(request,'lab')
    orders=LabOrder.objects.select_related('test','encounter__patient').order_by('-created_at')[:100]
    return render(request,'core/laboratory.html',{'orders':orders})

@login_required
@require_POST
def lab_result(request,pk):
    allow(request,'lab')
    with transaction.atomic():
        obj=get_object_or_404(LabOrder.objects.select_for_update(),pk=pk)
        if obj.status in ['cancelled','resulted']:return HttpResponseBadRequest('Order not open')
        result=request.POST.get('result','').strip()
        if not result:return HttpResponseBadRequest('Result required')
        obj.result=result;obj.reference_range=request.POST.get('reference_range','')[:200];obj.abnormal=request.POST.get('abnormal')=='on';obj.resulted_by=request.user;obj.resulted_at=timezone.now();obj.status='resulted';obj.save();audit(request.user,'lab_result',obj)
    return redirect('laboratory')

@login_required
def beds(request):
    allow(request,'beds')
    return render(request,'core/beds.html',{'beds':Bed.objects.order_by('ward','number'),'admissions':Admission.objects.filter(discharged_at__isnull=True).select_related('patient','bed')})

@login_required
@require_POST
def admission_add(request,pk):
    allow(request,'beds');encounter=get_object_or_404(Encounter,pk=pk)
    bed=get_object_or_404(Bed,pk=request.POST.get('bed'))
    reason=request.POST.get('reason','').strip()
    if not reason:messages.error(request,'Admission reason required.');return redirect('encounter_detail',pk=pk)
    try:admit(encounter.patient,encounter,bed,request.user,reason);messages.success(request,'Patient admitted.')
    except ValueError as e:messages.error(request,str(e))
    return redirect('encounter_detail',pk=pk)

@login_required
@require_POST
def discharge_patient(request,pk):
    allow(request,'beds');record=get_object_or_404(Admission,pk=pk)
    try:discharge(record,request.user);messages.success(request,'Discharged. Bed requires cleaning before reuse.')
    except ValueError as e:messages.error(request,str(e))
    return redirect('beds')

@login_required
def attendance(request):
    allow(request,'attendance')
    current=Attendance.objects.filter(staff=request.user,clock_out__isnull=True).first()
    entries=Attendance.objects.filter(staff=request.user)[:20]
    return render(request,'core/attendance.html',{'current':current,'entries':entries})

@login_required
@require_POST
def attendance_toggle(request):
    allow(request,'attendance')
    with transaction.atomic():
        current=Attendance.objects.select_for_update().filter(staff=request.user,clock_out__isnull=True).first()
        if current:current.clock_out=timezone.now();current.save();audit(request.user,'clock_out',current)
        else:obj=Attendance.objects.create(staff=request.user);audit(request.user,'clock_in',obj)
    return redirect('attendance')

@login_required
def ai_status(request,pk):
    allow(request,'clinical')
    encounter=get_object_or_404(Encounter,pk=pk)
    # Never transmit identifiable patient information to an external AI provider here.
    audit(request.user,'ai_status_view',encounter)
    return render(request,'core/ai_status.html',{'encounter':encounter})
