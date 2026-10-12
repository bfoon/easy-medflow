from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from hospital.models import LabRequest, LabResultValue
from .models import Specimen, SpecimenEvent, Analyzer, ReagentLot, QualityControl, CriticalCommunication, LabIncident

TRANSITIONS={
    'expected':{'collected'},'collected':{'received','rejected'},
    'received':{'accepted','rejected'},'accepted':{'in_process','rejected'},
    'in_process':{'stored','rejected'},'stored':{'disposed'},
    'rejected':set(),'disposed':set()
}

def guard(request):
    from hospital.views import authorize
    authorize(request,'lab')

def record_event(specimen, destination, actor, note='', **kwargs):
    if destination not in TRANSITIONS.get(specimen.status,set()):
        raise ValidationError('Invalid specimen transition: '+specimen.status+' → '+destination)
    if destination=='rejected' and not note.strip():raise ValidationError('Explain why the specimen was rejected.')
    old=specimen.status
    specimen.status=destination
    if destination=='collected':specimen.collected_at=timezone.now();specimen.collected_by=actor
    if destination=='received':specimen.received_at=timezone.now()
    if destination=='rejected':specimen.rejection_reason=note
    specimen.full_clean()
    specimen.save()
    return SpecimenEvent.objects.create(specimen=specimen,action=destination,from_status=old,to_status=destination,actor=actor,note=note[:2000])

@login_required
def dashboard(request):
    guard(request)
    specimens=Specimen.objects.select_related('request__encounter__patient').order_by('-created_at')[:100]
    critical=LabResultValue.objects.filter(flag__in=('LL','HH'),order__status='verified').exclude(critical_communications__isnull=False).select_related('order__encounter__patient','parameter')[:30]
    qc=QualityControl.objects.select_related('analyzer','parameter').order_by('-created_at')[:25]
    return render(request,'labplus/dashboard.html',{'specimens':specimens,'critical':critical,'qc':qc,
        'analyzers':Analyzer.objects.all(),'reagents':ReagentLot.objects.order_by('expiry')[:30],
        'incidents':LabIncident.objects.filter(closed_at__isnull=True).order_by('-created_at')[:20],
        'counts':dict(Specimen.objects.values_list('status').annotate(total=Count('pk'))),
        'requests':LabRequest.objects.select_related('encounter__patient').order_by('-created_at')[:30]})

@login_required
@require_POST
def accession(request,request_id):
    guard(request)
    lr=get_object_or_404(LabRequest,pk=request_id)
    sample_type=request.POST.get('sample_type','').strip()[:100]
    if not sample_type:return HttpResponseBadRequest('Sample type required')
    obj=Specimen.objects.create(request=lr,sample_type=sample_type,tube=request.POST.get('tube','').strip()[:100])
    from hospital.views import audit
    audit(request,'lab_update',f'specimen:{obj.pk}',{'action':'accession'})
    return redirect('labplus:dashboard')

@login_required
@require_POST
def transition(request,pk):
    guard(request)
    target=request.POST.get('status','')
    with transaction.atomic():
        specimen=get_object_or_404(Specimen.objects.select_for_update(),pk=pk)
        try:record_event(specimen,target,request.user,request.POST.get('note',''))
        except ValidationError as e:return HttpResponseBadRequest('; '.join(e.messages))
        from hospital.views import audit
        audit(request,'lab_update',f'specimen:{pk}',{'status':target})
    return redirect('labplus:dashboard')

@login_required
@require_POST
def recollect(request,pk):
    guard(request)
    with transaction.atomic():
        source=get_object_or_404(Specimen.objects.select_for_update(),pk=pk,status='rejected')
        obj=Specimen.objects.create(request=source.request,sample_type=source.sample_type,tube=source.tube,parent=source)
        from hospital.views import audit
        audit(request,'lab_update',f'specimen:{obj.pk}',{'recollection_of':source.pk})
    return redirect('labplus:dashboard')

@login_required
@require_POST
def qc_run(request):
    guard(request)
    from hospital.models import LabParameter
    from decimal import Decimal,InvalidOperation
    try:
        analyzer=Analyzer.objects.get(pk=request.POST.get('analyzer'),status='active')
        param=LabParameter.objects.get(pk=request.POST.get('parameter'))
        v=[Decimal(request.POST[k]) for k in ('observed','target','sd')]
        run=QualityControl(analyzer=analyzer,parameter=param,lot=request.POST.get('lot','')[:80],observed=v[0],target=v[1],sd=v[2],reviewed_by=request.user)
        run.save()
    except (KeyError,InvalidOperation,ValueError,TypeError,Analyzer.DoesNotExist,LabParameter.DoesNotExist,ValidationError) as e:
        return HttpResponseBadRequest('Invalid quality control: '+str(e)[:200])
    from hospital.views import audit
    audit(request,'lab_update',f'qc:{run.pk}',{'passed':run.passed,'z':str(run.z_score)})
    return redirect('labplus:dashboard')

@login_required
@require_POST
def critical_call(request,pk):
    guard(request)
    value=get_object_or_404(LabResultValue,pk=pk,flag__in=['LL','HH'],order__status='verified')
    person=request.POST.get('person','').strip()[:180]
    readback=request.POST.get('readback','').strip()[:2000]
    method=request.POST.get('method','')
    if not person or not readback or method not in ('phone','in_person','secure_message'):return HttpResponseBadRequest('Recipient, method and readback required')
    with transaction.atomic():
        c=CriticalCommunication.objects.create(value=value,contacted_by=request.user,contacted_person=person,method=method,readback=readback,escalation=request.POST.get('escalation','')[:2000])
        from hospital.views import audit
        audit(request,'lab_update',f'critical_call:{c.pk}',{'value_id':value.pk})
    return redirect('labplus:dashboard')
