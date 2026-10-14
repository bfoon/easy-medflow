"""Fictional demo content for the operating theatre and the eye & ear examination. Safe to run more than once."""
from datetime import date, timedelta

from django.utils import timezone

from . import senses as S
from . import theatre as T


def _signed(phase, user, at):
    items = {k: ('na' if na and k in ('blood_loss', 'imaging', 'specimen', 'equipment', 'airway') else 'yes') for k, _, na in T.CHECKLIST[phase]['items']}
    return {'items': items, 'at': at.isoformat(), 'by': user.get_full_name() or user.username, 'by_id': user.pk}


def run(doctor, nurse):
    from .models import Department, Encounter, OperatingRoom, Patient, ProcedureType, SenseExam, SurgicalCase, Condition
    if SurgicalCase.objects.exists() or not OperatingRoom.objects.exists():
        return 0
    now = timezone.now()
    # times are written as on a day where "12:00" is the moment the demo is loaded, so the board always looks live
    at = lambda h, m=0: (now + timedelta(hours=h - 12, minutes=m)).replace(second=0, microsecond=0)
    rooms = {r.name: r for r in OperatingRoom.objects.all()}
    pt = {p.code: p for p in ProcedureType.objects.all()}
    surg = Department.objects.filter(name='Surgery').first() or Department.objects.first()
    opd = Department.objects.filter(name='Outpatient').first() or surg
    made = 0

    def person(first, last, dob, sex, reason, dx, vitals, dept=surg, alerts=''):
        p = Patient.objects.create(first_name=first, last_name=last, dob=dob, sex=sex, phone='7' + str(abs(hash(first + last)) % 10 ** 6).zfill(6), medical_alerts=alerts)
        e = Encounter.objects.create(patient=p, department=dept, clinician=doctor, reason=reason, diagnosis=dx, vitals=vitals)
        return p, e

    def case(e, code, room, start, status, **kw):
        nonlocal made
        c = SurgicalCase(encounter=e, procedure_type=pt.get(code), specialty=pt[code].specialty if code in pt else 'general',
                         room=rooms.get(room), scheduled_start=start, est_minutes=pt[code].default_minutes if code in pt else 60,
                         anaesthesia=pt[code].default_anaesthesia if code in pt else 'general', surgeon=doctor, scrub_nurse=nurse, requested_by=doctor, status=status, **kw)
        c.save(); made += 1
        return c

    yes_preop = lambda c: {k: 'yes' for k, _, _ in T.preop_items(c)}

    # 1 · operating now: appendicectomy, started 35 minutes ago
    _, e = person('Ousman', 'Jatta', date(2001, 5, 14), 'M', 'Right lower abdominal pain, vomiting', 'Acute appendicitis',
                  {'bp': '124/78', 'heart_rate': '104', 'temperature_c': '38.4', 'weight_kg': '64'})
    c = case(e, 'appendicectomy', 'Main Theatre 1', now - timedelta(minutes=50), 'operating', urgency='urgent', asa=1, indication='Acute appendicitis, Alvarado 8',
             anaesthetist=doctor, fasting_since=now - timedelta(hours=9), in_room_at=now - timedelta(minutes=48), anaesthesia_at=now - timedelta(minutes=46),
             incision_at=now - timedelta(minutes=35))
    c.preop = yes_preop(c)
    c.checklist = {'sign_in': _signed('sign_in', nurse, now - timedelta(minutes=47)), 'time_out': _signed('time_out', doctor, now - timedelta(minutes=36))}
    c.checklist['time_out']['antibiotic_time'] = timezone.localtime(now - timedelta(minutes=55)).strftime('%H:%M')
    c.save()

    # 2 · in recovery: caesarean section
    _, e = person('Mariama', 'Bojang', date(1996, 8, 2), 'F', 'Labour, obstructed', 'Obstructed labour, term pregnancy',
                  {'bp': '118/74', 'heart_rate': '96', 'weight_kg': '71'}, dept=Department.objects.filter(name='Maternity').first() or surg)
    c = case(e, 'caesarean', 'Obstetric Theatre', now - timedelta(minutes=110), 'recovery', urgency='urgent', asa=2, blood_units=1,
             in_room_at=now - timedelta(minutes=105), anaesthesia_at=now - timedelta(minutes=100), incision_at=now - timedelta(minutes=92),
             closure_at=now - timedelta(minutes=40), out_room_at=now - timedelta(minutes=35), procedure_performed='Lower segment caesarean section',
             findings='Live baby girl, Apgar 8 and 9. Placenta complete.', blood_loss_ml=650, wound_class='clean_contaminated', closure='Subcuticular absorbable',
             post_op_plan='Observations every 15 min for 1 h; oxytocin infusion; analgesia; mobilise in 12 h.', note_by=doctor, note_at=now - timedelta(minutes=36))
    c.preop = yes_preop(c)
    c.checklist = {p: _signed(p, nurse, now - timedelta(minutes=m)) for p, m in (('sign_in', 104), ('time_out', 93), ('sign_out', 38))}
    c.recovery = [T.clean_recovery_obs(o, 118, now=now - timedelta(minutes=m)) for o, m in (
        ({'heart_rate': 112, 'systolic': 92, 'diastolic': 58, 'spo2': 95, 'on_oxygen': True, 'pain': 6, 'activity': 1, 'respiration': 2, 'consciousness': 1}, 30),
        ({'heart_rate': 102, 'systolic': 104, 'diastolic': 66, 'spo2': 96, 'on_oxygen': False, 'pain': 4, 'activity': 1, 'respiration': 2, 'consciousness': 2}, 15))]
    c.save()

    # 3 · completed this morning: hernia repair
    _, e = person('Lamin', 'Darboe', date(1972, 1, 20), 'M', 'Groin lump', 'Right inguinal hernia', {'bp': '132/84', 'weight_kg': '78'})
    c = case(e, 'hernia-inguinal', 'Main Theatre 2', at(8), 'completed', side='right', urgency='elective', asa=2, in_room_at=at(8, 5), anaesthesia_at=at(8, 10),
             incision_at=at(8, 22), closure_at=at(9, 5), out_room_at=at(9, 12), recovery_out_at=at(9, 55), discharge_to='ward',
             procedure_performed='Right Lichtenstein mesh repair', implants='Polypropylene mesh 6 × 11 cm', blood_loss_ml=30, wound_class='clean', note_by=doctor, note_at=at(9, 10))
    c.preop = yes_preop(c)
    c.checklist = {p: _signed(p, nurse, at(h, m)) for p, (h, m) in (('sign_in', (8, 6)), ('time_out', (8, 20)), ('sign_out', (9, 8)))}
    c.recovery = [T.clean_recovery_obs({'heart_rate': 76, 'systolic': 128, 'diastolic': 80, 'spo2': 98, 'pain': 2, 'activity': 2, 'respiration': 2, 'consciousness': 2}, 132, now=at(9, 50))]
    c.save()

    # 4 · eye patient: examination drives a cataract operation later today
    p, e = person('Kaddy', 'Touray', date(1956, 4, 9), 'F', 'Blurred vision for a year, worse in the right eye', 'Right cataract; diabetic retinopathy',
                  {'bp': '168/96', 'heart_rate': '80', 'weight_kg': '66'}, dept=opd)
    Condition.objects.create(patient=p, name='Type 2 diabetes', status='active')
    exam = S.clean_exam({'eyes': {
        'right': {'examined': True, 'va': '6/60', 'pinhole': '6/36', 'iop': 19, 'cdr': 0.4, 'lens': 'dense', 'pupil_mm': 3.5, 'retina': {'dr': 'moderate', 'htn': 1}},
        'left': {'examined': True, 'va': '6/12', 'pinhole': '6/9', 'iop': 24, 'cdr': 0.65, 'lens': 'early', 'pupil_mm': 3.5, 'retina': {'dr': 'mild', 'htn': 1}}},
        'ears': {'right': {'examined': True, 'ac': {'250': 15, '500': 20, '1000': 25, '2000': 35, '4000': 55, '8000': 65}},
                 'left': {'examined': True, 'ac': {'250': 20, '500': 25, '1000': 30, '2000': 40, '4000': 60, '8000': 70}, 'bc': {'500': 25, '1000': 30, '2000': 35, '4000': 55}}}})
    ctx = {'age': p.age, 'diabetic': True, 'hba1c': None, 'systolic': 168, 'diastolic': 96}
    SenseExam.objects.create(encounter=e, patient=p, data=exam, computed=S.compute(exam, ctx), examined_by=doctor)
    c = case(e, 'cataract', 'Eye & ENT Theatre', at(13), 'scheduled', side='right', site='Right eye', urgency='elective', asa=2,
             indication='Dense right cataract, vision 6/60', fasting_since=now - timedelta(hours=3))

    # 5 · child with glue ear: grommet on the waiting list after the hearing test
    p, e = person('Fatou', 'Sanneh', date.today() - timedelta(days=5 * 365 + 40), 'F', 'Not hearing at school', 'Bilateral otitis media with effusion',
                  {'temperature_c': '36.8', 'weight_kg': '18'}, dept=opd)
    exam = S.clean_exam({'ears': {
        'right': {'examined': True, 'ac': {'500': 35, '1000': 30, '2000': 30, '4000': 25}, 'bc': {'500': 5, '1000': 5, '2000': 10, '4000': 5}, 'tm': 'effusion', 'tympanogram': 'B'},
        'left': {'examined': True, 'ac': {'500': 30, '1000': 30, '2000': 25, '4000': 25}, 'tm': 'effusion', 'tympanogram': 'B'}}})
    SenseExam.objects.create(encounter=e, patient=p, data=exam, computed=S.compute(exam, {'age': p.age}), examined_by=doctor)
    case(e, 'grommet', None, None, 'requested', side='bilateral', urgency='elective', indication='Glue ear for 4 months with 30 dB hearing loss')

    # 6 · an emergency waiting for a theatre, and two more booked this afternoon
    _, e = person('Ebrima', 'Ceesay', date(1985, 11, 3), 'M', 'Stab wound to the abdomen', 'Penetrating abdominal trauma',
                  {'bp': '96/60', 'heart_rate': '122', 'spo2': '95', 'weight_kg': '70'}, dept=Department.objects.filter(name='Emergency').first() or surg)
    case(e, 'laparotomy', None, None, 'requested', urgency='immediate', asa=3, blood_units=2, indication='Stab wound, peritonism, haemodynamically unstable')
    _, e = person('Awa', 'Njie', date(1968, 2, 27), 'F', 'Neck swelling', 'Multinodular goitre', {'bp': '136/82', 'weight_kg': '74'})
    c = case(e, 'thyroidectomy', 'Main Theatre 2', at(14), 'ready', urgency='elective', asa=2, fasting_since=now - timedelta(hours=10))
    c.preop = yes_preop(c); c.save()
    _, e = person('Modou', 'Bah', date(1990, 7, 7), 'M', 'Back abscess', 'Back abscess', {'bp': '122/76', 'temperature_c': '38.1'})
    case(e, 'incision-drainage', 'Minor Procedures Room', at(15, 30), 'scheduled', urgency='expedited')
    return made
