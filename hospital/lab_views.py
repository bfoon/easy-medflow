"""Laboratory management pages: command centre, specimen reception, labels and reports, QC, analysers, reagents and
critical-value calls. Lab staff and admins only (reports also for clinical staff)."""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import lab_mgmt
from .models import Analyzer, AnalyzerLog, CriticalCall, LabRequest, LabResultValue, QCMaterial, Reagent
from .views import audit, authorize, lab_requests_qs


@login_required
def lab_dashboard(request):
    authorize(request, 'lab')
    return render(request, 'hospital/lab/dashboard.html', {'d': lab_mgmt.dashboard(), 'tab': 'dashboard'})


@login_required
def lab_specimens(request):
    """Specimen reception: scan or type the specimen or request number to receive it; reject with a reason."""
    authorize(request, 'lab')
    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        lr = LabRequest.objects.filter(pk=request.POST.get('pk') or 0).first()
        if not lr and code:
            num = code.upper().replace('LR-', '')
            lr = LabRequest.objects.filter(specimen_id__iexact=code).first() or (LabRequest.objects.filter(pk=int(num)).first() if num.isdigit() else None)
        if not lr:
            messages.error(request, f'No lab request matches “{code}”.')
        elif request.POST.get('action') == 'reject':
            reason = request.POST.get('reason')
            if reason not in dict(LabRequest.REJECT):
                messages.error(request, 'Choose why the specimen is rejected.')
            else:
                lab_mgmt.reject_specimen(lr, request.user, reason)
                messages.warning(request, f'{lr.number} rejected ({dict(LabRequest.REJECT)[reason].lower()}). The requesting clinician has been notified to recollect.')
        elif lab_mgmt.receive_specimen(lr, request.user):
            messages.success(request, f'{lr.number} received at {timezone.localtime().strftime("%H:%M")}.')
        else:
            messages.info(request, f'{lr.number} was already received.')
        return redirect('lab_specimens')
    pending = [r for r in lab_requests_qs().filter(received_at__isnull=True).exclude(orders__status__in=['resulted', 'verified']).distinct()[:80]
               if r.stage in ('ordered', 'collected')]
    recent = LabRequest.objects.filter(received_at__isnull=False).select_related('encounter__patient', 'received_by').order_by('-received_at')[:20]
    rejected = LabRequest.objects.filter(rejected_at__gte=timezone.now() - timedelta(days=7)).select_related('encounter__patient').order_by('-rejected_at')[:20]
    return render(request, 'hospital/lab/specimens.html', {'pending': pending, 'recent': recent, 'rejected': rejected, 'reasons': LabRequest.REJECT, 'tab': 'specimens'})


@login_required
def lab_label(request, pk):
    """Specimen label for 50 × 25 mm label printers, with a QR code of the specimen number."""
    authorize(request, 'lab')
    import segno
    from django.utils.safestring import mark_safe
    lr = get_object_or_404(lab_requests_qs(), pk=pk)
    code = lr.specimen_id or lr.number
    return render(request, 'hospital/lab/label.html', {'lr': lr, 'p': lr.encounter.patient, 'code': code,
                                                       'qr': mark_safe(segno.make(code, error='m').svg_inline(scale=2, border=0))})


@login_required
def lab_report(request, pk):
    """Printable laboratory report: results with reference ranges and flags, verification and a QR back to the record."""
    authorize(request)
    import segno
    from django.utils.safestring import mark_safe
    lr = get_object_or_404(lab_requests_qs(), pk=pk)
    p = lr.encounter.patient
    url = request.build_absolute_uri(f'/labs/requests/{lr.pk}/')
    audit(request, 'lab_report_print', f'lab_request:{lr.pk}')
    from .evidence import who_for_request
    who, _ = who_for_request(lr)
    return render(request, 'hospital/lab/report.html', {'lr': lr, 'p': p, 'qr': mark_safe(segno.make(url, error='m').svg_inline(scale=2, border=1)), 'who': who,
                                                        'orders': [o for o in lr.orders.all() if o.status in ('resulted', 'verified')]})


@login_required
def lab_qc(request):
    """Quality control: today's status per analyser and material, Levey-Jennings charts, and entry of control results."""
    authorize(request, 'lab')
    if request.method == 'POST':
        m = get_object_or_404(QCMaterial, pk=request.POST.get('material'))
        try:
            value = Decimal(request.POST.get('value', '').replace(',', '.'))
        except InvalidOperation:
            messages.error(request, 'Enter the control value as a number.')
            return redirect(request.POST.get('next') or 'lab_qc')
        run = lab_mgmt.record_qc(m, value, request.user, request.POST.get('comment', ''))
        audit(request, 'qc_run', f'qc_material:{m.pk}', {'status': run.status, 'rules': run.rules})
        (messages.error if run.status == 'rejected' else messages.warning if run.status == 'warning' else messages.success)(
            request, f'{m}: {value} → {run.get_status_display()}' + (f' ({run.rules}). {m.analyzer} is on QC hold: do not release results until QC passes.' if run.status == 'rejected'
                                                                   else f' ({run.rules}). Check before running patients.' if run.rules else '.'))
        return redirect(request.POST.get('next') or 'lab_qc')
    analyzers = []
    for a in Analyzer.objects.prefetch_related('qc_materials__parameter', 'qc_materials__runs'):
        mats = []
        for m in a.qc_materials.filter(active=True):
            runs = list(m.runs.order_by('-created_at')[:30])[::-1]
            mats.append({'m': m, 'runs': runs, 'last': runs[-1] if runs else None,
                         'points': [{'z': round(r.z, 2), 'v': float(r.value), 's': r.status, 'd': timezone.localtime(r.created_at).strftime('%d %b %H:%M')} for r in runs]})
        analyzers.append({'a': a, 'light': lab_mgmt.qc_light(a), 'mats': mats})
    return render(request, 'hospital/lab/qc.html', {'analyzers': analyzers, 'tab': 'qc'})


@login_required
def lab_analyzers(request):
    authorize(request, 'lab')
    if request.method == 'POST':
        a = get_object_or_404(Analyzer, pk=request.POST.get('analyzer'))
        note = request.POST.get('note', '').strip()[:300]
        st = request.POST.get('status')
        if st in dict(Analyzer.STATUS) and st != a.status:
            a.status, a.status_note = st, note or dict(Analyzer.STATUS)[st]
            a.save(update_fields=['status', 'status_note', 'updated_at'])
            AnalyzerLog.objects.create(analyzer=a, kind='status', note=f'{a.get_status_display()}: {note}' if note else a.get_status_display(), by=request.user)
        kind = request.POST.get('kind')
        if kind in ('maintenance', 'calibration', 'fault') and note:
            AnalyzerLog.objects.create(analyzer=a, kind=kind, note=note, by=request.user)
            if kind == 'maintenance':
                a.last_maintenance = timezone.localdate(); a.next_maintenance = timezone.localdate() + timedelta(days=30)
                a.save(update_fields=['last_maintenance', 'next_maintenance', 'updated_at'])
        messages.success(request, f'{a} updated.')
        return redirect('lab_analyzers')
    rows = [{'a': a, 'light': lab_mgmt.qc_light(a), 'logs': list(a.logs.select_related('by')[:5]), 'reagents': list(a.reagents.all()[:4])} for a in Analyzer.objects.all()]
    return render(request, 'hospital/lab/analyzers.html', {'rows': rows, 'statuses': Analyzer.STATUS, 'tab': 'analyzers', 'today': timezone.localdate()})


@login_required
def lab_reagents(request):
    authorize(request, 'lab')
    if request.method == 'POST':
        r = Reagent.objects.filter(pk=request.POST.get('reagent') or 0).first()
        try:
            if request.POST.get('action') == 'use' and r:
                n = int(request.POST.get('qty') or 0); r.quantity = max(0, r.quantity - n); r.save(update_fields=['quantity', 'updated_at'])
                messages.success(request, f'{r.name}: {n} {r.unit} used, {r.quantity} left.')
            elif request.POST.get('action') == 'receive':
                new = Reagent.objects.create(name=request.POST['name'].strip()[:160], analyzer=Analyzer.objects.filter(pk=request.POST.get('analyzer') or 0).first(),
                                             lot=request.POST['lot'].strip()[:40], expiry=date.fromisoformat(request.POST['expiry']), quantity=int(request.POST.get('qty') or 0),
                                             unit=request.POST.get('unit', 'tests')[:30] or 'tests', reorder_level=int(request.POST.get('reorder') or 50))
                messages.success(request, f'Received {new.name} lot {new.lot}.')
        except (KeyError, ValueError):
            messages.error(request, 'Give a name, lot, expiry date and quantity.')
        return redirect('lab_reagents')
    rows = list(Reagent.objects.select_related('analyzer'))
    return render(request, 'hospital/lab/reagents.html', {'rows': rows, 'analyzers': Analyzer.objects.all(), 'tab': 'reagents',
                                                          'expiring': sum(1 for r in rows if r.days_left <= 21), 'low': sum(1 for r in rows if r.low)})


@login_required
def lab_critical(request):
    """Critical-value call-back log: who was phoned, when, and whether they read the result back."""
    authorize(request, 'lab')
    if request.method == 'POST':
        c = get_object_or_404(CriticalCall, pk=request.POST.get('call'))
        to = request.POST.get('called_to', '').strip()
        if not to or request.POST.get('read_back') != 'on':
            messages.error(request, 'Record who you spoke to and confirm they read the result back.')
        else:
            c.called_to, c.called_by, c.called_at, c.read_back, c.note = to[:120], request.user, timezone.now(), True, request.POST.get('note', '')[:200]
            c.save()
            audit(request, 'critical_call', f'lab_value:{c.value_id}', {'to': to[:60]})
            messages.success(request, f'Call recorded: {c.value.parameter.name} {c.value.display} given to {to}.')
        return redirect('lab_critical')
    qs = CriticalCall.objects.select_related('value__parameter', 'value__order__encounter__patient', 'value__order__request', 'called_by')
    return render(request, 'hospital/lab/critical.html', {'pending': qs.filter(called_at__isnull=True), 'done': qs.filter(called_at__isnull=False).order_by('-called_at')[:30], 'tab': 'critical'})
