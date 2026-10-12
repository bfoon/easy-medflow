"""Advanced hematology visualization endpoint using existing E-MedFlow permissions."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from .models import Patient, LabResultValue
from .hematology_engine import build_hematology_scene

@login_required
def hematology_lab(request, pk):
    from .views import authorize, audit
    authorize(request, 'clinical')
    patient = get_object_or_404(Patient, pk=pk)
    audit(request, 'view_chart', f'hematology:{patient.pk}')
    return render(request, 'hospital/hematology_lab.html', {'patient': patient})

@login_required
def hematology_data(request, pk):
    from .views import authorize, audit
    authorize(request, 'clinical')
    patient = get_object_or_404(Patient, pk=pk)
    readings = (LabResultValue.objects.filter(order__encounter__patient=patient, order__status='verified',
                                               order__verified_at__isnull=False)
                .select_related('order__test', 'parameter').order_by('-order__verified_at', '-pk')[:2000])
    values = []
    for v in readings:
        param = v.parameter
        if v.value_number is None:
            continue
        low, high = param.range_for(patient.sex)
        values.append({'code': param.code, 'name': param.name, 'number': v.value_number,
                       'low': low, 'high': high, 'flag': v.flag, 'unit': param.unit,
                       'verified': True, 'test': v.order.test.name,
                       'observed_at': v.order.verified_at.isoformat()})
    audit(request, 'view_chart', f'hematology_data:{patient.pk}')
    response = JsonResponse(build_hematology_scene(values))
    response['Cache-Control'] = 'no-store, private'
    return response
