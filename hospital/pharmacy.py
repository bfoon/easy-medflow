"""Pharmacy stock engine.

Every change to a batch quantity goes through `move()`, which writes one StockMovement with the running balance,
so each medicine has a complete stock card per location. Issues always take the earliest-expiring usable batch
first (FEFO). Controlled drugs need a second person (witness) on every movement out of stock.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from .models import (AuditEvent, Medication, PurchaseOrder, Requisition, StockBatch, StockCount, StockCountLine, StockLocation,
                     StockMovement)

OUT_KINDS = {'dispense', 'issue_out', 'expired', 'damaged', 'quarantine', 'ward_use'}


def location_balance(medication, location, usable_only=False):
    qs = StockBatch.objects.filter(medication=medication, store=location)
    if usable_only:
        qs = qs.filter(expiry__gte=timezone.localdate(), quarantined=False)
    return qs.aggregate(t=Sum('quantity'))['t'] or 0


def usable_batches(medication, location, lock=False):
    """Batches that may be issued: in date, not quarantined, with stock, earliest expiry first."""
    qs = StockBatch.objects.filter(medication=medication, store=location, expiry__gte=timezone.localdate(), quarantined=False, quantity__gt=0)
    if lock:
        qs = qs.select_for_update()
    return list(qs.order_by('expiry', 'pk'))


def move(batch, quantity, kind, actor, reference='', note='', witness=None, patient=None):
    """Change one batch by `quantity` (negative = out) and record it in the ledger. Call inside a transaction."""
    if quantity == 0:
        return None
    if batch.medication.controlled and quantity < 0 and kind in OUT_KINDS:
        if not witness:
            raise ValidationError(f'{batch.medication} is a controlled drug: a witness must confirm this.')
        if witness == actor:
            raise ValidationError('The witness must be a different person.')
    if batch.quantity + quantity < 0:
        raise ValidationError(f'Batch {batch.batch_number} of {batch.medication} has only {batch.quantity} left.')
    StockBatch.objects.filter(pk=batch.pk).update(quantity=F('quantity') + quantity, updated_at=timezone.now())
    batch.refresh_from_db(fields=['quantity'])
    return StockMovement.objects.create(
        medication=batch.medication, batch=batch, location=batch.store, kind=kind, quantity=quantity,
        balance_after=location_balance(batch.medication, batch.store), unit_cost=batch.unit_cost,
        reference=reference[:40], note=note[:250], actor=actor, witness=witness, patient=patient)


def take(medication, location, quantity, kind, actor, reference='', note='', witness=None, patient=None):
    """Take `quantity` from a location, earliest expiry first. Returns [(batch, qty)] taken."""
    batches = usable_batches(medication, location, lock=True)
    if sum(b.quantity for b in batches) < quantity:
        raise ValidationError(f'Not enough {medication} at {location}: need {quantity}, have {sum(b.quantity for b in batches)} usable.')
    taken = []
    for b in batches:
        q = min(quantity, b.quantity)
        if q:
            move(b, -q, kind, actor, reference, note, witness, patient)
            taken.append((b, q)); quantity -= q
        if not quantity:
            break
    return taken


def put(location, medication, batch_number, expiry, quantity, unit_cost, kind, actor, reference='', note='', supplier=None):
    """Add stock to a location, into the matching batch if it already exists there."""
    b, created = StockBatch.objects.get_or_create(medication=medication, batch_number=batch_number, store=location,
                                                  defaults={'expiry': expiry, 'quantity': 0, 'unit_cost': unit_cost, 'supplier': supplier})
    if not created and unit_cost and not b.unit_cost:
        b.unit_cost = unit_cost; b.save(update_fields=['unit_cost'])
    move(b, quantity, kind, actor, reference, note)
    return b


# ---------------------------------------------------------------- purchase orders

@transaction.atomic
def receive_order(order, actor, lines):
    """Book a delivery. `lines` = [{'line': PurchaseOrderLine, 'quantity': n, 'batch_number': str, 'expiry': date}]."""
    order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
    if order.status not in ('sent', 'partial'):
        raise ValidationError('Only orders sent to the supplier can be received.')
    dest = order.deliver_to or StockLocation.objects.filter(kind='store', active=True).first() or StockLocation.dispensing()
    got = 0
    for x in lines:
        line, qty = x['line'], int(x['quantity'] or 0)
        if qty <= 0:
            continue
        if qty > line.outstanding:
            raise ValidationError(f'{line.medication}: only {line.outstanding} still expected.')
        if not x.get('batch_number') or not x.get('expiry') or x['expiry'] <= timezone.localdate():
            raise ValidationError(f'{line.medication}: enter a batch number and a future expiry date.')
        put(dest, line.medication, x['batch_number'], x['expiry'], qty, line.unit_cost, 'receipt', actor, order.number, f'From {order.supplier}', order.supplier)
        line.received_quantity += qty; line.save(update_fields=['received_quantity'])
        got += qty
    if not got:
        raise ValidationError('Enter the quantity received for at least one line.')
    order.status = 'received' if all(l.outstanding == 0 for l in order.lines.all()) else 'partial'
    order.save(update_fields=['status', 'updated_at'])
    AuditEvent.objects.create(actor=actor, action='po_received', target=f'purchase_order:{order.pk}', details={'units': got, 'status': order.status})
    return order


def reorder_suggestions(location=None):
    """Medicines at or below their reorder level (counting what is already on order), with a suggested top-up quantity."""
    location = location or None
    on_order = defaultdict(int)
    from .models import PurchaseOrderLine
    for l in PurchaseOrderLine.objects.filter(order__status__in=['draft', 'sent', 'partial']).select_related('medication'):
        on_order[l.medication_id] += l.outstanding
    stock = dict(StockBatch.objects.filter(expiry__gte=timezone.localdate(), quarantined=False).values('medication')
                 .annotate(t=Sum('quantity')).values_list('medication', 't'))
    out = []
    for m in Medication.objects.filter(active=True).select_related('default_supplier'):
        have = stock.get(m.pk, 0)
        if have + on_order[m.pk] <= m.reorder_level:
            qty = max(m.target_level - have - on_order[m.pk], m.reorder_level)
            if m.pack_size > 1:
                qty = -(-qty // m.pack_size) * m.pack_size          # round up to whole packs
            out.append({'m': m, 'have': have, 'on_order': on_order[m.pk], 'suggest': qty})
    return sorted(out, key=lambda r: (r['have'] > 0, r['have'] / max(1, r['m'].reorder_level)))


# ---------------------------------------------------------------- ward requisitions

@transaction.atomic
def issue_requisition(req, actor, quantities, witness=None):
    """Issue stock for a requisition: move it from the supplying location to the ward. `quantities` = {line_pk: n}."""
    req = Requisition.objects.select_for_update().get(pk=req.pk)
    if req.status not in ('approved', 'partial'):
        raise ValidationError('Approve the requisition before issuing.')
    issued = 0
    for line in req.lines.select_related('medication'):
        qty = int(quantities.get(line.pk, 0) or 0)
        if qty <= 0:
            continue
        if qty > line.to_issue:
            raise ValidationError(f'{line.medication}: only {line.to_issue} left to issue.')
        for batch, q in take(line.medication, req.supply_from, qty, 'issue_out', actor, req.number, f'To {req.deliver_to}', witness):
            put(req.deliver_to, line.medication, batch.batch_number, batch.expiry, q, batch.unit_cost, 'issue_in', actor, req.number, f'From {req.supply_from}', batch.supplier)
        line.issued += qty; line.save(update_fields=['issued'])
        issued += qty
    if not issued:
        raise ValidationError('Enter a quantity to issue for at least one line.')
    req.status = 'issued' if all(l.to_issue == 0 for l in req.lines.all()) else 'partial'
    req.issued_by, req.issued_at = actor, timezone.now()
    req.save(update_fields=['status', 'issued_by', 'issued_at', 'updated_at'])
    return req


# ---------------------------------------------------------------- write-offs and quarantine

@transaction.atomic
def write_off(batch, quantity, kind, actor, note, witness=None):
    if kind not in ('expired', 'damaged'):
        raise ValidationError('Write-offs are for expired or damaged stock.')
    batch = StockBatch.objects.select_for_update().get(pk=batch.pk)
    quantity = min(int(quantity), batch.quantity)
    if quantity <= 0:
        raise ValidationError('Nothing to write off.')
    return move(batch, -quantity, kind, actor, 'WRITE-OFF', note, witness)


@transaction.atomic
def set_quarantine(batch, on, actor, note=''):
    StockBatch.objects.filter(pk=batch.pk).update(quarantined=on)
    AuditEvent.objects.create(actor=actor, action='batch_quarantine' if on else 'batch_release', target=f'batch:{batch.pk}', details={'note': note[:200]})


# ---------------------------------------------------------------- stock takes

@transaction.atomic
def start_count(location, actor, notes=''):
    if StockCount.objects.filter(location=location, status='open').exists():
        raise ValidationError(f'A stock take is already open for {location}.')
    c = StockCount.objects.create(location=location, started_by=actor, notes=notes[:300])
    StockCountLine.objects.bulk_create([StockCountLine(count=c, batch=b, system_quantity=b.quantity)
                                        for b in StockBatch.objects.filter(store=location).filter(Q(quantity__gt=0) | Q(expiry__gte=timezone.localdate())).select_related('medication')])
    return c


@transaction.atomic
def post_count(count, actor):
    """Post every counted difference as an adjustment. Uncounted lines are left unchanged."""
    count = StockCount.objects.select_for_update().get(pk=count.pk)
    if count.status != 'open':
        raise ValidationError('This stock take is already closed.')
    n = 0
    for line in count.lines.select_related('batch__medication'):
        if line.counted is None:
            continue
        b = StockBatch.objects.select_for_update().get(pk=line.batch_id)
        diff = line.counted - b.quantity        # against the live quantity, in case stock moved during the count
        if diff:
            move(b, diff, 'adjust', actor, count.number, line.reason or 'Stock-take difference'); n += 1
    count.status, count.posted_by, count.posted_at = 'posted', actor, timezone.now()
    count.save(update_fields=['status', 'posted_by', 'posted_at', 'updated_at'])
    return n


# ---------------------------------------------------------------- analytics

def consumption(days=30, location=None):
    """Units used per medicine over the last `days` (dispensed to patients and used on wards)."""
    since = timezone.now() - timedelta(days=days)
    qs = StockMovement.objects.filter(created_at__gte=since, kind__in=['dispense', 'ward_use'])
    if location:
        qs = qs.filter(location=location)
    return {mid: -t for mid, t in qs.values('medication').annotate(t=Sum('quantity')).values_list('medication', 't')}


def stock_overview(location=None):
    """One row per active medicine: usable stock, value, average daily use, days of stock left, status."""
    today = timezone.localdate()
    use30 = consumption(30, location)
    bq = StockBatch.objects.filter(quantity__gt=0)
    if location:
        bq = bq.filter(store=location)
    usable, value, expiring = defaultdict(int), defaultdict(Decimal), defaultdict(int)
    for b in bq.values('medication', 'quantity', 'unit_cost', 'expiry', 'quarantined'):
        if b['expiry'] >= today and not b['quarantined']:
            usable[b['medication']] += b['quantity']
            value[b['medication']] += b['quantity'] * b['unit_cost']
            if b['expiry'] <= today + timedelta(days=90):
                expiring[b['medication']] += b['quantity']
    rows = []
    for m in Medication.objects.filter(active=True).order_by('name'):
        qty, daily = usable[m.pk], use30.get(m.pk, 0) / 30
        days_left = round(qty / daily) if daily else None
        level = 'out' if qty == 0 else 'low' if qty <= m.reorder_level else 'over' if m.target_level and qty > m.target_level * 1.6 else 'ok'
        rows.append({'m': m, 'qty': qty, 'value': value[m.pk], 'daily': round(daily, 1), 'days_left': days_left, 'level': level,
                     'expiring': expiring[m.pk], 'pct': min(100, round(qty * 100 / max(m.target_level, 1)))})
    return rows


def abc_analysis(days=90):
    """Rank medicines by the value consumed: A = top 70 % of spend, B = next 20 %, C = the rest."""
    since = timezone.now() - timedelta(days=days)
    used = (StockMovement.objects.filter(created_at__gte=since, kind__in=['dispense', 'ward_use'])
            .values('medication__name', 'medication__strength', 'medication').annotate(units=Sum('quantity')))
    vals = []
    costs = {mid: c for mid, c in StockBatch.objects.values('medication').annotate(c=Sum(F('unit_cost') * F('quantity')) / Sum('quantity')).values_list('medication', 'c') if c}
    for u in used:
        units = -u['units']
        unit_cost = costs.get(u['medication']) or Decimal('0')
        vals.append({'name': f"{u['medication__name']} {u['medication__strength']}", 'units': units, 'value': Decimal(units) * Decimal(unit_cost)})
    vals.sort(key=lambda r: r['value'], reverse=True)
    total = sum(r['value'] for r in vals) or Decimal('1')
    run = Decimal('0')
    for r in vals:
        run += r['value']
        r['share'] = round(float(r['value'] / total * 100), 1)
        r['cls'] = 'A' if run / total <= Decimal('0.70') or r is vals[0] else 'B' if run / total <= Decimal('0.90') else 'C'
    return vals


def daily_series(medication=None, days=60, kinds=('dispense', 'ward_use')):
    """Units used per day, for charts."""
    since = timezone.localdate() - timedelta(days=days - 1)
    qs = StockMovement.objects.filter(created_at__date__gte=since, kind__in=kinds)
    if medication:
        qs = qs.filter(medication=medication)
    per = defaultdict(int)
    for d, q in qs.values_list('created_at__date', 'quantity'):
        per[d] += -q
    return [(since + timedelta(days=i), per.get(since + timedelta(days=i), 0)) for i in range(days)]
