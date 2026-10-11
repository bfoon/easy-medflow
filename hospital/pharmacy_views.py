"""Pharmacy management screens. The stock logic lives in pharmacy.py; these views only gather input and show results."""
import csv
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from . import pharmacy as ph
from .models import (MED_CATEGORIES, Medication, PurchaseOrder, PurchaseOrderLine, Requisition, RequisitionLine, StaffProfile,
                     StockBatch, StockCount, StockCountLine, StockLocation, StockMovement, Supplier)
from .views import audit, authorize, finish, role_of

STOCK_ROLES = {'pharmacy', 'admin'}                 # receive, issue, adjust, write off, count
REQUEST_ROLES = {'nurse', 'doctor', 'pharmacy', 'admin'}   # raise a ward requisition


def can_stock(user):
    return role_of(user) in STOCK_ROLES


def need_stock(request):
    authorize(request)
    if not can_stock(request.user):
        raise PermissionDenied('Pharmacy staff only.')


def nav(active):
    """Counts for the pharmacy sub-navigation."""
    today = timezone.localdate()
    return {'pnav': active, 'pnav_counts': {
        'req': Requisition.objects.filter(status__in=['submitted', 'approved', 'partial']).count(),
        'po': PurchaseOrder.objects.filter(status__in=['draft', 'sent', 'partial']).count(),
        'exp': StockBatch.objects.filter(quantity__gt=0, expiry__lte=today + timedelta(days=60)).count(),
        'count': StockCount.objects.filter(status='open').count()}}


def witnesses(user):
    """Staff who can witness a controlled-drug movement: anyone clinical or pharmacy, except the person doing it."""
    return (get_user_model().objects.filter(hospital_staff__active=True, hospital_staff__role__in=['pharmacy', 'nurse', 'doctor', 'admin'])
            .exclude(pk=user.pk).order_by('first_name', 'username'))


def get_witness(request):
    wid = request.POST.get('witness')
    return get_user_model().objects.filter(pk=wid, hospital_staff__active=True).first() if wid else None


def bars_svg(series, w=640, h=120, colour='#0F7B78'):
    """Small bar chart as inline SVG, so the page needs no chart library."""
    if not series:
        return ''
    mx = max(v for _, v in series) or 1
    bw = w / len(series)
    parts = [f'<svg viewBox="0 0 {w} {h + 18}" class="ph-bars" role="img" aria-label="Daily use">']
    for i, (d, v) in enumerate(series):
        bh = v / mx * h
        parts.append(f'<rect x="{i * bw + 1:.1f}" y="{h - bh:.1f}" width="{max(1, bw - 2):.1f}" height="{bh:.1f}" rx="1.5" fill="{colour}"><title>{d:%d %b}: {v}</title></rect>')
    for i, (d, _) in enumerate(series):
        if i % max(1, len(series) // 6) == 0:
            parts.append(f'<text x="{i * bw:.1f}" y="{h + 14}" class="ph-ax">{d:%d %b}</text>')
    parts.append('</svg>')
    return mark_safe(''.join(parts))


# ---------------------------------------------------------------- overview

@login_required
def overview(request):
    authorize(request)
    today = timezone.localdate()
    rows = ph.stock_overview()
    batches = StockBatch.objects.filter(quantity__gt=0)
    stock_value = sum((b.quantity * b.unit_cost for b in batches.filter(expiry__gte=today, quarantined=False)), Decimal('0'))
    expired = batches.filter(expiry__lt=today).select_related('medication', 'store')
    soon = batches.filter(expiry__gte=today, expiry__lte=today + timedelta(days=90)).select_related('medication', 'store').order_by('expiry')
    since = timezone.now() - timedelta(days=30)
    dispensed30 = -(StockMovement.objects.filter(kind='dispense', created_at__gte=since).aggregate(t=Sum('quantity'))['t'] or 0)
    use = ph.consumption(30)
    top = sorted(((Medication.objects.get(pk=k), v) for k, v in use.items()), key=lambda x: -x[1])[:8]
    top_max = top[0][1] if top else 1
    by_cat = defaultdict(Decimal)
    for r in rows:
        by_cat[r['m'].get_category_display()] += r['value']
    cats = sorted(by_cat.items(), key=lambda x: -x[1])[:8]
    cat_max = cats[0][1] if cats and cats[0][1] else Decimal('1')
    return render(request, 'hospital/pharmacy/overview.html', {
        **nav('overview'), 'stock_value': stock_value, 'n_items': len(rows),
        'out': [r for r in rows if r['level'] == 'out'], 'low': [r for r in rows if r['level'] == 'low'],
        'expired': expired, 'expired_value': sum((b.quantity * b.unit_cost for b in expired), Decimal('0')),
        'soon': soon[:12], 'soon_count': soon.count(), 'dispensed30': dispensed30,
        'chart': bars_svg(ph.daily_series(days=45)), 'top': [(m, v, round(v * 100 / top_max)) for m, v in top],
        'cats': [(c, v, round(v * 100 / cat_max)) for c, v in cats],
        'reqs': Requisition.objects.filter(status__in=['submitted', 'approved', 'partial']).select_related('deliver_to', 'requested_by')[:6],
        'orders': PurchaseOrder.objects.filter(status__in=['sent', 'partial']).select_related('supplier')[:6],
        'cold': [r for r in rows if r['m'].cold_chain and r['qty']][:6],
        'recent': StockMovement.objects.select_related('medication', 'location', 'actor').order_by('-created_at')[:10],
        'can_stock': can_stock(request.user), 'today': today, 'soon30': today + timedelta(days=30)})


# ---------------------------------------------------------------- stock list and stock card

@login_required
def stock(request):
    authorize(request)
    loc = StockLocation.objects.filter(pk=request.GET.get('location')).first()
    rows = ph.stock_overview(loc)
    q, cat, level = request.GET.get('q', '').strip().lower(), request.GET.get('cat', ''), request.GET.get('level', '')
    if q:
        rows = [r for r in rows if q in f'{r["m"].name} {r["m"].generic_name} {r["m"].strength}'.lower()]
    if cat:
        rows = [r for r in rows if r['m'].category == cat]
    if level == 'reorder':
        rows = [r for r in rows if r['level'] in ('out', 'low')]
    elif level:
        rows = [r for r in rows if r['level'] == level]
    if request.GET.get('format') == 'csv':
        resp = HttpResponse(content_type='text/csv'); resp['Content-Disposition'] = f'attachment; filename="stock-{timezone.localdate()}.csv"'
        w = csv.writer(resp)
        w.writerow(['Medicine', 'Strength', 'Form', 'Category', 'Usable stock', 'Unit', 'Reorder level', 'Average daily use', 'Days left', 'Value (GMD)', 'Status'])
        for r in rows:
            w.writerow([r['m'].name, r['m'].strength, r['m'].form, r['m'].get_category_display(), r['qty'], r['m'].get_unit_display(), r['m'].reorder_level,
                        r['daily'], r['days_left'] if r['days_left'] is not None else '', f"{r['value']:.2f}", r['level']])
        return resp
    return render(request, 'hospital/pharmacy/stock.html', {**nav('stock'), 'rows': rows, 'locations': StockLocation.objects.filter(active=True),
                                                            'loc': loc, 'categories': MED_CATEGORIES, 'f': request.GET, 'can_stock': can_stock(request.user),
                                                            'total_value': sum((r['value'] for r in rows), Decimal('0'))})


@login_required
def stock_card(request, pk):
    authorize(request)
    m = get_object_or_404(Medication, pk=pk)
    loc = StockLocation.objects.filter(pk=request.GET.get('location')).first()
    batches = m.batches.select_related('store', 'supplier').filter(Q(quantity__gt=0) | Q(movements__created_at__gte=timezone.now() - timedelta(days=30))).distinct().order_by('store__name', 'expiry')
    ledger = m.movements.select_related('location', 'actor', 'witness', 'batch', 'patient')
    if loc:
        ledger = ledger.filter(location=loc)
    use30 = ph.consumption(30).get(m.pk, 0)
    usable = sum(b.quantity for b in batches if not b.expired and not b.quarantined)
    per_loc = defaultdict(int)
    for b in batches:
        if not b.expired and not b.quarantined:
            per_loc[b.store] += b.quantity
    return render(request, 'hospital/pharmacy/stock_card.html', {
        **nav('stock'), 'm': m, 'batches': batches, 'ledger': ledger[:250], 'loc': loc, 'per_loc': sorted(per_loc.items(), key=lambda x: x[0].name),
        'usable': usable, 'daily': round(use30 / 30, 1), 'days_left': round(usable / (use30 / 30)) if use30 else None,
        'chart': bars_svg(ph.daily_series(m, days=60)), 'today': timezone.localdate(), 'can_stock': can_stock(request.user),
        'witnesses': witnesses(request.user) if m.controlled else None,
        'locations': StockLocation.objects.filter(active=True)})


@login_required
@require_POST
def batch_action(request, pk, action):
    need_stock(request)
    b = get_object_or_404(StockBatch.objects.select_related('medication'), pk=pk)
    note = request.POST.get('note', '').strip()[:200]
    try:
        if action in ('expired', 'damaged'):
            mv = ph.write_off(b, request.POST.get('quantity') or b.quantity, action, request.user, note or ('Expired stock' if action == 'expired' else 'Damaged'), get_witness(request))
            messages.success(request, f'{-mv.quantity} × {b.medication} written off from batch {b.batch_number}.')
        elif action in ('quarantine', 'release'):
            ph.set_quarantine(b, action == 'quarantine', request.user, note)
            messages.success(request, f'Batch {b.batch_number} {"quarantined: it will not be issued" if action == "quarantine" else "released back into use"}.')
        else:
            return HttpResponseBadRequest('Unknown action')
    except (ValidationError, ValueError) as e:
        messages.error(request, '; '.join(getattr(e, 'messages', [str(e)])))
    return redirect(request.POST.get('next') or reverse('pharm_card', args=[b.medication_id]))


# ---------------------------------------------------------------- ward requisitions

@login_required
def requisitions(request):
    authorize(request)
    status = request.GET.get('status', 'open')
    qs = Requisition.objects.select_related('deliver_to', 'supply_from', 'requested_by').annotate(n=Count('lines'))
    qs = qs.filter(status__in=['submitted', 'approved', 'partial']) if status == 'open' else qs.filter(status=status) if status != 'all' else qs
    return render(request, 'hospital/pharmacy/requisitions.html', {**nav('req'), 'reqs': qs[:200], 'status': status,
                                                                    'can_request': role_of(request.user) in REQUEST_ROLES, 'can_stock': can_stock(request.user)})


def _lines_from_post(request, allow_cost=False):
    """Read repeated medicine/quantity(/cost) rows from a form."""
    out = []
    meds, qtys, costs = request.POST.getlist('med'), request.POST.getlist('qty'), request.POST.getlist('cost')
    for i, (mid, q) in enumerate(zip(meds, qtys)):
        if not mid or not q:
            continue
        try:
            q = int(q)
            cost = Decimal(costs[i]) if allow_cost and i < len(costs) and costs[i] else Decimal('0')
        except (ValueError, InvalidOperation):
            continue
        m = Medication.objects.filter(pk=mid, active=True).first()
        if m and q > 0:
            out.append((m, q, cost))
    return out


@login_required
def requisition_new(request):
    authorize(request)
    if role_of(request.user) not in REQUEST_ROLES:
        raise PermissionDenied('Only clinical or pharmacy staff can raise requisitions.')
    wards = StockLocation.objects.filter(active=True).exclude(is_dispensing=True).exclude(kind__in=['store', 'quarantine'])
    sources = StockLocation.objects.filter(active=True, kind__in=['store', 'pharmacy'])
    if request.method == 'POST':
        lines = _lines_from_post(request)
        to = wards.filter(pk=request.POST.get('deliver_to')).first()
        frm = sources.filter(pk=request.POST.get('supply_from')).first() or StockLocation.dispensing()
        if not to or not lines:
            messages.error(request, 'Choose the ward and add at least one medicine with a quantity.')
        else:
            with transaction.atomic():
                r = Requisition.objects.create(deliver_to=to, supply_from=frm, requested_by=request.user, priority=request.POST.get('priority', 'routine'),
                                               needed_by=request.POST.get('needed_by') or None, notes=request.POST.get('notes', '')[:300])
                RequisitionLine.objects.bulk_create([RequisitionLine(requisition=r, medication=m, requested=q) for m, q, _ in lines])
            audit(request, 'requisition_create', f'requisition:{r.pk}', {'lines': len(lines)})
            messages.success(request, f'{r.number} sent to {frm}.')
            return redirect('pharm_requisition', pk=r.pk)
    # suggest a top-up: ward stock below what it usually holds
    ward = wards.filter(pk=request.GET.get('ward')).first()
    suggest = []
    if ward:
        for r in ph.stock_overview(ward):
            if r['m'].pk in set(ward.batches.values_list('medication', flat=True)) and r['qty'] < max(20, r['m'].reorder_level // 4):
                suggest.append({'m': r['m'], 'qty': max(20, r['m'].reorder_level // 3) - r['qty']})
    return render(request, 'hospital/pharmacy/requisition_form.html', {**nav('req'), 'wards': wards, 'sources': sources, 'ward': ward, 'suggest': suggest[:15],
                                                                        'meds': Medication.objects.filter(active=True).order_by('name')})


@login_required
def requisition_detail(request, pk):
    authorize(request)
    r = get_object_or_404(Requisition.objects.select_related('deliver_to', 'supply_from', 'requested_by', 'approved_by', 'issued_by'), pk=pk)
    lines = list(r.lines.select_related('medication'))
    for l in lines:
        l.available = ph.location_balance(l.medication, r.supply_from, usable_only=True)
    movements = StockMovement.objects.filter(reference=r.number).select_related('medication', 'batch', 'location', 'actor', 'witness')
    return render(request, 'hospital/pharmacy/requisition_detail.html', {**nav('req'), 'r': r, 'lines': lines, 'movements': movements,
                                                                          'can_stock': can_stock(request.user), 'any_controlled': any(l.medication.controlled for l in lines),
                                                                          'witnesses': witnesses(request.user)})


@login_required
@require_POST
def requisition_action(request, pk, action):
    authorize(request)
    r = get_object_or_404(Requisition, pk=pk)
    mine = r.requested_by_id == request.user.pk
    try:
        if action == 'cancel' and r.status == 'submitted' and (mine or can_stock(request.user)):
            r.status = 'cancelled'; r.save(update_fields=['status', 'updated_at']); messages.success(request, f'{r.number} cancelled.')
        elif not can_stock(request.user):
            raise PermissionDenied('Pharmacy staff only.')
        elif action == 'approve' and r.status == 'submitted':
            with transaction.atomic():
                for l in r.lines.all():
                    v = request.POST.get(f'approve_{l.pk}')
                    l.approved = max(0, int(v)) if v not in (None, '') else l.requested
                    l.save(update_fields=['approved'])
                r.status, r.approved_by = 'approved', request.user; r.save(update_fields=['status', 'approved_by', 'updated_at'])
            messages.success(request, f'{r.number} approved. Issue it when the stock is packed.')
        elif action == 'reject' and r.status == 'submitted':
            r.status = 'rejected'; r.notes = (r.notes + ' · Rejected: ' + request.POST.get('reason', ''))[:300]
            r.save(update_fields=['status', 'notes', 'updated_at']); messages.success(request, f'{r.number} rejected.')
        elif action == 'issue':
            qty = {l.pk: request.POST.get(f'issue_{l.pk}') for l in r.lines.all()}
            ph.issue_requisition(r, request.user, qty, get_witness(request))
            r.refresh_from_db()
            messages.success(request, f'{r.number} issued to {r.deliver_to}.' if r.status == 'issued' else f'{r.number} partly issued; the rest stays open.')
        else:
            return HttpResponseBadRequest('That action is not possible now.')
        audit(request, f'requisition_{action}', f'requisition:{r.pk}')
    except ValidationError as e:
        messages.error(request, '; '.join(e.messages))
    except ValueError:
        messages.error(request, 'Quantities must be whole numbers.')
    return redirect('pharm_requisition', pk=r.pk)


# ---------------------------------------------------------------- purchase orders

@login_required
def orders(request):
    authorize(request)
    status = request.GET.get('status', 'open')
    qs = PurchaseOrder.objects.select_related('supplier').prefetch_related('lines')
    qs = qs.filter(status__in=['draft', 'sent', 'partial']) if status == 'open' else qs.filter(status=status) if status != 'all' else qs
    return render(request, 'hospital/pharmacy/orders.html', {**nav('po'), 'orders': qs[:200], 'status': status,
                                                              'suggest': ph.reorder_suggestions()[:40], 'can_stock': can_stock(request.user)})


@login_required
def order_new(request):
    need_stock(request)
    suppliers = Supplier.objects.filter(active=True)
    if request.method == 'POST':
        lines = _lines_from_post(request, allow_cost=True)
        sup = suppliers.filter(pk=request.POST.get('supplier')).first()
        if not sup or not lines:
            messages.error(request, 'Choose a supplier and add at least one medicine.')
        else:
            with transaction.atomic():
                po = PurchaseOrder.objects.create(supplier=sup, created_by=request.user, funding=request.POST.get('funding', 'budget'),
                                                  deliver_to=StockLocation.objects.filter(pk=request.POST.get('deliver_to')).first(),
                                                  expected_date=timezone.localdate() + timedelta(days=sup.lead_time_days), notes=request.POST.get('notes', '')[:500])
                PurchaseOrderLine.objects.bulk_create([PurchaseOrderLine(order=po, medication=m, quantity=q, unit_cost=c or _last_cost(m)) for m, q, c in lines])
            audit(request, 'po_create', f'purchase_order:{po.pk}', {'lines': len(lines)})
            messages.success(request, f'{po.number} created as a draft. Check it, then send it to {sup}.')
            return redirect('pharm_order', pk=po.pk)
    pre = []
    if request.GET.get('from') == 'suggestions':
        sup_id = request.GET.get('supplier')
        for s in ph.reorder_suggestions():
            if not sup_id or str(s['m'].default_supplier_id) == sup_id:
                pre.append({'m': s['m'], 'qty': s['suggest'], 'cost': _last_cost(s['m'])})
    return render(request, 'hospital/pharmacy/order_form.html', {**nav('po'), 'suppliers': suppliers, 'pre': pre[:40], 'sel_supplier': request.GET.get('supplier', ''),
                                                                  'meds': Medication.objects.filter(active=True).order_by('name'), 'funding': PurchaseOrder.FUNDING,
                                                                  'stores': StockLocation.objects.filter(active=True, kind__in=['store', 'pharmacy'])})


def _last_cost(m):
    b = m.batches.exclude(unit_cost=0).order_by('-created_at').first()
    return b.unit_cost if b else (m.unit_price * Decimal('0.6')).quantize(Decimal('0.01'))


@login_required
def order_detail(request, pk):
    authorize(request)
    po = get_object_or_404(PurchaseOrder.objects.select_related('supplier', 'deliver_to', 'created_by'), pk=pk)
    return render(request, 'hospital/pharmacy/order_detail.html', {**nav('po'), 'po': po, 'lines': po.lines.select_related('medication'),
                                                                    'receipts': StockMovement.objects.filter(reference=po.number).select_related('medication', 'batch', 'actor'),
                                                                    'can_stock': can_stock(request.user), 'today': timezone.localdate()})


@login_required
@require_POST
def order_action(request, pk, action):
    need_stock(request)
    po = get_object_or_404(PurchaseOrder, pk=pk)
    try:
        if action == 'send' and po.status == 'draft':
            po.status, po.sent_at = 'sent', timezone.now(); po.save(update_fields=['status', 'sent_at', 'updated_at'])
            messages.success(request, f'{po.number} marked as sent to {po.supplier}. Expected around {po.expected_date:%d %b}.')
        elif action == 'cancel' and po.status in ('draft', 'sent'):
            po.status = 'cancelled'; po.save(update_fields=['status', 'updated_at']); messages.success(request, f'{po.number} cancelled.')
        elif action == 'receive':
            got = []
            for l in po.lines.all():
                q = request.POST.get(f'qty_{l.pk}')
                if q and int(q) > 0:
                    got.append({'line': l, 'quantity': int(q), 'batch_number': request.POST.get(f'batch_{l.pk}', '').strip()[:100],
                                'expiry': date.fromisoformat(request.POST.get(f'expiry_{l.pk}')) if request.POST.get(f'expiry_{l.pk}') else None})
            ph.receive_order(po, request.user, got)
            po.refresh_from_db()
            messages.success(request, f'Delivery booked into {po.deliver_to or "the main store"}. {po.number} is now {po.get_status_display().lower()}.')
        else:
            return HttpResponseBadRequest('That action is not possible now.')
        audit(request, f'po_{action}', f'purchase_order:{po.pk}')
    except ValidationError as e:
        messages.error(request, '; '.join(e.messages))
    except ValueError:
        messages.error(request, 'Check the quantities and dates.')
    return redirect('pharm_order', pk=po.pk)


# ---------------------------------------------------------------- stock takes

@login_required
def counts(request):
    authorize(request)
    if request.method == 'POST':
        need_stock(request)
        loc = get_object_or_404(StockLocation, pk=request.POST.get('location'))
        try:
            c = ph.start_count(loc, request.user, request.POST.get('notes', ''))
            messages.success(request, f'{c.number} started for {loc}: {c.lines.count()} batches to count.')
            return redirect('pharm_count', pk=c.pk)
        except ValidationError as e:
            messages.error(request, '; '.join(e.messages))
    return render(request, 'hospital/pharmacy/counts.html', {**nav('count'), 'counts': StockCount.objects.select_related('location', 'started_by', 'posted_by').annotate(n=Count('lines'))[:100],
                                                              'locations': StockLocation.objects.filter(active=True), 'can_stock': can_stock(request.user)})


@login_required
def count_detail(request, pk):
    authorize(request)
    c = get_object_or_404(StockCount.objects.select_related('location'), pk=pk)
    if request.method == 'POST':
        need_stock(request)
        if c.status != 'open':
            return HttpResponseBadRequest('Closed')
        with transaction.atomic():
            for l in c.lines.all():
                v = request.POST.get(f'count_{l.pk}')
                l.counted = int(v) if v not in (None, '') and v.isdigit() else None
                l.reason = request.POST.get(f'reason_{l.pk}', '')[:120]
                l.save(update_fields=['counted', 'reason'])
        if request.POST.get('action') == 'post':
            try:
                n = ph.post_count(c, request.user)
                messages.success(request, f'{c.number} posted: {n} adjustment{"s" if n != 1 else ""} written to the stock ledger.')
            except ValidationError as e:
                messages.error(request, '; '.join(e.messages))
        else:
            messages.success(request, 'Counts saved. You can carry on later.')
        return redirect('pharm_count', pk=c.pk)
    lines = list(c.lines.select_related('batch__medication'))
    counted = [l for l in lines if l.counted is not None]
    return render(request, 'hospital/pharmacy/count_detail.html', {**nav('count'), 'c': c, 'lines': lines, 'n_counted': len(counted),
                                                                    'n_diff': sum(1 for l in counted if l.variance),
                                                                    'value_diff': sum((l.variance * l.batch.unit_cost for l in counted if l.variance), Decimal('0')),
                                                                    'can_stock': can_stock(request.user)})


# ---------------------------------------------------------------- expiry

@login_required
def expiry(request):
    authorize(request)
    today = timezone.localdate()
    if request.method == 'POST' and request.POST.get('action') == 'writeoff_all':
        need_stock(request)
        n, skipped = 0, []
        for b in StockBatch.objects.filter(quantity__gt=0, expiry__lt=today).select_related('medication'):
            try:
                ph.write_off(b, b.quantity, 'expired', request.user, 'Expired · bulk write-off', get_witness(request)); n += 1
            except ValidationError:
                skipped.append(str(b.medication))
        messages.success(request, f'{n} expired batch{"es" if n != 1 else ""} written off.' + (f' Controlled drugs need a witness and were left: {", ".join(skipped)}.' if skipped else ''))
        return redirect('pharm_expiry')
    base = StockBatch.objects.filter(quantity__gt=0).select_related('medication', 'store', 'supplier')
    groups = [('Expired · remove from shelves', 'red', base.filter(expiry__lt=today)),
              ('Expires within 30 days', 'red', base.filter(expiry__gte=today, expiry__lte=today + timedelta(days=30))),
              ('Expires in 31–90 days', 'amber', base.filter(expiry__gt=today + timedelta(days=30), expiry__lte=today + timedelta(days=90))),
              ('Quarantined', 'indigo', base.filter(quarantined=True))]
    use = ph.consumption(60)
    out = []
    for label, colour, qs in groups:
        rows = []
        for b in qs.order_by('expiry'):
            daily = use.get(b.medication_id, 0) / 60
            days = (b.expiry - today).days
            at_risk = max(0, b.quantity - round(daily * max(0, days))) if days >= 0 else b.quantity   # what will not be used in time
            rows.append({'b': b, 'days': days, 'at_risk': at_risk, 'value': b.quantity * b.unit_cost})
        out.append({'label': label, 'colour': colour, 'rows': rows, 'value': sum((r['value'] for r in rows), Decimal('0'))})
    written = StockMovement.objects.filter(kind__in=['expired', 'damaged'], created_at__gte=timezone.now() - timedelta(days=90))
    lost = sum((-m.quantity * m.unit_cost for m in written), Decimal('0'))
    return render(request, 'hospital/pharmacy/expiry.html', {**nav('exp'), 'groups': out, 'lost90': lost, 'written': written.select_related('medication', 'actor')[:30],
                                                              'can_stock': can_stock(request.user), 'witnesses': witnesses(request.user)})


# ---------------------------------------------------------------- controlled drugs register

@login_required
def controlled(request):
    authorize(request)
    meds = Medication.objects.filter(controlled=True).order_by('name')
    m = meds.filter(pk=request.GET.get('med')).first() or meds.first()
    loc = StockLocation.objects.filter(pk=request.GET.get('location')).first()
    entries = StockMovement.objects.filter(medication=m).select_related('location', 'actor', 'witness', 'patient', 'batch') if m else StockMovement.objects.none()
    if loc:
        entries = entries.filter(location=loc)
    balances = [(l, ph.location_balance(m, l)) for l in StockLocation.objects.filter(active=True)] if m else []
    return render(request, 'hospital/pharmacy/controlled.html', {**nav('cd'), 'meds': meds, 'm': m, 'loc': loc, 'entries': entries.order_by('-created_at', '-id')[:300],
                                                                  'balances': [b for b in balances if b[1]], 'locations': StockLocation.objects.filter(active=True),
                                                                  'unwitnessed': entries.filter(quantity__lt=0, witness__isnull=True).count()})


# ---------------------------------------------------------------- reports

@login_required
def reports(request):
    authorize(request)
    days = 90 if request.GET.get('days') == '90' else 30
    use = ph.consumption(days)
    meds = {m.pk: m for m in Medication.objects.all()}
    top = sorted(((meds[k], v) for k, v in use.items() if k in meds), key=lambda x: -x[1])[:20]
    abc = ph.abc_analysis(90)
    abc_counts = {c: sum(1 for r in abc if r['cls'] == c) for c in 'ABC'}
    abc_share = {c: round(sum(r['share'] for r in abc if r['cls'] == c)) for c in 'ABC'}
    last_move = dict(StockMovement.objects.filter(kind__in=['dispense', 'issue_out', 'ward_use']).values('medication').annotate(t=Max('created_at')).values_list('medication', 't'))
    cutoff = timezone.now() - timedelta(days=90)
    dead = [r for r in ph.stock_overview() if r['qty'] and (last_move.get(r['m'].pk) is None or last_move[r['m'].pk] < cutoff)]
    by_loc = (StockBatch.objects.filter(quantity__gt=0, expiry__gte=timezone.localdate(), quarantined=False)
              .values('store__name').annotate(units=Sum('quantity')).order_by('store__name'))
    loc_value = defaultdict(Decimal)
    for b in StockBatch.objects.filter(quantity__gt=0, expiry__gte=timezone.localdate(), quarantined=False).select_related('store'):
        loc_value[b.store.name] += b.quantity * b.unit_cost
    wards = (StockMovement.objects.filter(kind='issue_in', created_at__gte=timezone.now() - timedelta(days=days))
             .values('location__name').annotate(units=Sum('quantity'), n=Count('reference', distinct=True)).order_by('-units'))
    return render(request, 'hospital/pharmacy/reports.html', {**nav('rep'), 'days': days, 'top': top, 'top_max': top[0][1] if top else 1, 'abc': abc[:40],
                                                              'abc_counts': abc_counts, 'abc_share': abc_share, 'dead': dead,
                                                              'locs': [(r['store__name'], r['units'], loc_value[r['store__name']]) for r in by_loc], 'wards': wards})


# ---------------------------------------------------------------- suppliers, medicines and locations (configuration)

class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['name', 'contact_person', 'phone', 'email', 'address', 'lead_time_days', 'active', 'notes']


class MedicationForm(forms.ModelForm):
    class Meta:
        model = Medication
        fields = ['name', 'generic_name', 'form', 'strength', 'category', 'unit', 'pack_size', 'unit_price', 'reorder_level', 'max_level',
                  'default_supplier', 'essential', 'controlled', 'cold_chain', 'active']


class LocationForm(forms.ModelForm):
    class Meta:
        model = StockLocation
        fields = ['name', 'kind', 'ward', 'is_dispensing', 'active']


@login_required
def suppliers(request):
    authorize(request)
    rows = Supplier.objects.annotate(n_orders=Count('orders'), n_meds=Count('medications', distinct=True)).order_by('-active', 'name')
    spend = dict(PurchaseOrderLine.objects.filter(order__status__in=['partial', 'received'], order__created_at__gte=timezone.now() - timedelta(days=365))
                 .values('order__supplier').annotate(t=Sum('unit_cost')).values_list('order__supplier', 't'))
    totals = defaultdict(Decimal)
    for l in PurchaseOrderLine.objects.filter(order__status__in=['partial', 'received'], order__created_at__gte=timezone.now() - timedelta(days=365)).select_related('order'):
        totals[l.order.supplier_id] += l.received_quantity * l.unit_cost
    for s in rows:
        s.spend = totals.get(s.pk, Decimal('0'))
    return render(request, 'hospital/pharmacy/suppliers.html', {**nav('sup'), 'rows': rows, 'locations': StockLocation.objects.annotate(n=Count('batches')),
                                                                 'can_stock': can_stock(request.user)})


def _config(request, formclass, title, pk=None, model=None):
    """Create or edit one supplier, location or medicine (edit_page in views.py only creates)."""
    need_stock(request)
    obj = get_object_or_404(model, pk=pk) if pk else None
    form = formclass(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        saved = form.save()
        audit(request, 'update' if obj else 'create', f'{saved._meta.label}:{saved.pk}')
        back = reverse('pharm_card', args=[saved.pk]) if model is Medication else reverse('pharm_suppliers')
        return finish(request, request.POST.get('next') or back, f'{title.replace("Edit ", "").replace("New ", "").capitalize()} saved.')
    return render(request, 'hospital/form.html', {'form': form, 'title': title, 'subtitle': 'Pharmacy settings'})


@login_required
def supplier_edit(request, pk=None):
    return _config(request, SupplierForm, 'Edit supplier' if pk else 'New supplier', pk, Supplier)


@login_required
def location_edit(request, pk=None):
    return _config(request, LocationForm, 'Edit stock location' if pk else 'New stock location', pk, StockLocation)


@login_required
def medication_edit(request, pk=None):
    return _config(request, MedicationForm, 'Edit medicine' if pk else 'New medicine', pk, Medication)
