"""Extra fictional demo data: brain cases and scans, imaging, four months of visits for the health dashboard,
and inpatient medication charts. Used by seed_demo and by seed_demo_extras (for databases that already exist)."""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.utils import timezone

from . import demo_images as di
from .models import (Condition, Admission, Department, Encounter, ImagingImage, ImagingOrder, LabOrder, LabRequest, LabResultValue, LabTest,
                     MedicationAdministration, Medication, Patient, Prescription, PrescriptionItem, StaffProfile)

FIRST_F = ['Awa', 'Fatou', 'Isatou', 'Mariama', 'Binta', 'Haddy', 'Ndey', 'Kaddy', 'Aminata', 'Jainaba', 'Sainabou', 'Oumie', 'Adama', 'Rohey']
FIRST_M = ['Lamin', 'Ebrima', 'Modou', 'Ousman', 'Alieu', 'Momodou', 'Bakary', 'Sulayman', 'Omar', 'Musa', 'Kebba', 'Yusupha', 'Sheriff', 'Pa']
LAST = ['Jallow', 'Ceesay', 'Bah', 'Touray', 'Sowe', 'Camara', 'Njie', 'Jobe', 'Sanneh', 'Darboe', 'Faye', 'Manneh', 'Sarr', 'Drammeh', 'Saidy', 'Fofana']
TOWNS = ['Serrekunda'] * 5 + ['Brikama'] * 4 + ['Bakau'] * 2 + ['Banjul'] * 2 + ['Lamin'] * 2 + ['Kololi', 'Farafenni', 'Soma', 'Basse', 'Gunjur']


def staff_user(role):
    p = StaffProfile.objects.filter(role=role, active=True).select_related('user').first()
    return p.user if p else None


def study(enc, by, modality, region, system, png, findings, impression, abnormal, meas=None, hours=3, caption=''):
    now = timezone.now()
    o = ImagingOrder.objects.create(encounter=enc, modality=modality, region=region, body_system=system, status='reported', requested_by=by,
                                    performed_by=by, findings=findings, impression=impression, abnormal=abnormal, measurements=meas or [],
                                    reported_by=by, reported_at=now - timedelta(hours=max(0, hours - 1)))
    ImagingOrder.objects.filter(pk=o.pk).update(created_at=now - timedelta(hours=hours))
    ImagingImage.objects.create(order=o, file=ContentFile(png, name=f'demo-{modality}.png'), caption=caption or region, uploaded_by=by)
    return o


def lab_result(enc, code, values, by, hours=4):
    now = timezone.now()
    test = LabTest.objects.get(code=code)
    lr = LabRequest.objects.create(encounter=enc, requested_by=by, priority='urgent')
    o = LabOrder.objects.create(encounter=enc, request=lr, test=test, status='verified', resulted_at=now - timedelta(hours=hours),
                                verified_by=by, verified_at=now - timedelta(hours=hours - 1), performed_by=by)
    for prm in test.parameters.all():
        if prm.code in values:
            v = values[prm.code]; num = Decimal(str(v)) if prm.kind == 'number' else None
            LabResultValue.objects.create(order=o, parameter=prm, value_number=num, value_text='' if num is not None else str(v),
                                          flag=prm.flag_for(v, enc.patient.sex), entered_by=by)
    o.abnormal = o.values.exclude(flag__in=['', 'N']).exists(); o.save(update_fields=['abnormal'])
    return o


def new_patient(first, last, sex, age, town, **kw):
    return Patient.objects.create(first_name=first, last_name=last, sex=sex, dob=date.today() - timedelta(days=int(age * 365.25) + random.randint(0, 300)),
                                  phone=f'+220 {random.randint(300, 799)} {random.randint(1000, 9999)}', address=f'{random.randint(1, 90)} Main Road, {town}', **kw)


def brain_cases(doctor, rad):
    """Three fictional neurology cases with CSF results, CT, MRI and EEG."""
    if Encounter.objects.filter(diagnosis__icontains='meningitis').exists():
        return 0
    neuro = Department.objects.filter(name='General Medicine').first()
    p1 = new_patient('Omar', 'Saidy', 'M', 24, 'Brikama')
    e1 = Encounter.objects.create(patient=p1, clinician=doctor, department=neuro, reason='Fever, severe headache, neck stiffness', status='open',
                                  diagnosis='Suspected bacterial meningitis', vitals={'bp': '118/72', 'heart_rate': '112', 'temperature_c': '39.4', 'spo2': '97'})
    lab_result(e1, 'CSF', {'CGLU': 1.1, 'CPRO': 1.6, 'CWBC': 850, 'GRAM': 'Gram-positive diplococci'}, doctor, hours=5)
    lab_result(e1, 'CBC', {'HB': 13.6, 'WBC': 19.4, 'PLT': 210, 'RBC': 4.8, 'HCT': 41, 'MCV': 86}, doctor, hours=6)
    study(e1, rad, 'ct', 'Head', 'brain', di.ct_head(seed=31), 'No mass, haemorrhage or raised pressure. Safe for lumbar puncture.', 'Normal CT head.', False, hours=7)
    study(e1, rad, 'mri', 'Brain', 'brain', di.mri_brain('meningitis'), 'Diffuse leptomeningeal enhancement. No abscess.', 'Findings consistent with meningitis.', True, hours=2)
    p2 = new_patient('Haddy', 'Fofana', 'F', 67, 'Serrekunda', medical_alerts='Hypertension')
    e2 = Encounter.objects.create(patient=p2, clinician=doctor, department=neuro, reason='Sudden right-sided weakness and slurred speech', status='open',
                                  diagnosis='Acute ischaemic stroke, left MCA', vitals={'bp': '186/104', 'heart_rate': '88', 'temperature_c': '36.8', 'spo2': '96'})
    study(e2, rad, 'ct', 'Head', 'brain', di.ct_head(seed=33), 'Subtle loss of grey-white differentiation in the left insula. No haemorrhage.', 'Early left MCA infarct; no bleed.', True, hours=4)
    study(e2, rad, 'mri', 'Brain', 'brain', di.mri_brain('infarct'), 'Restricted diffusion in the left MCA territory.', 'Acute left MCA territory infarct.', True,
          [{'label': 'Infarct volume', 'value': '38', 'unit': 'mL', 'abnormal': True}], hours=3)
    lab_result(e2, 'GLU', {'FBG': 7.9}, doctor, hours=4)
    lab_result(e2, 'LIPID', {'TC': 6.1, 'LDL': 4.0, 'HDL': 0.9, 'TG': 2.0}, doctor, hours=4)
    p3 = new_patient('Lamin', 'Sarr', 'M', 15, 'Bakau')
    e3 = Encounter.objects.create(patient=p3, clinician=doctor, department=neuro, reason='Staring spells at school, two this week', status='open',
                                  diagnosis='Absence epilepsy', vitals={'bp': '110/70', 'heart_rate': '76', 'temperature_c': '36.6'})
    study(e3, rad, 'eeg', 'Brain', 'brain', di.eeg_strip(True), 'Generalised 3 Hz spike-and-wave discharges during hyperventilation.', 'EEG consistent with absence epilepsy.', True, hours=6)
    study(e3, rad, 'mri', 'Brain', 'brain', di.mri_brain(None, seed=14), 'Normal brain parenchyma and ventricles.', 'Normal MRI brain.', False, hours=26)
    return 3


def featured_imaging(doctor, rad):
    """Imaging for Babucarr Sowe if his record has none (databases seeded before imaging existed)."""
    e = Encounter.objects.filter(patient__first_name='Babucarr', patient__last_name='Sowe', status='open').first()
    if not e or ImagingOrder.objects.filter(encounter__patient=e.patient).exists():
        return 0
    study(e, rad, 'xray', 'Chest PA', 'lungs', di.chest_xray(), 'Enlarged cardiac silhouette with mild upper-lobe venous diversion.', 'Cardiomegaly with mild pulmonary venous congestion.', True,
          [{'label': 'Cardiothoracic ratio', 'value': '0.58', 'unit': '', 'abnormal': True}], hours=3)
    study(e, rad, 'ecg', 'Heart · 12-lead', 'heart', di.ecg_strip(), 'Sinus tachycardia 104/min. ST elevation in V2–V4.', 'Anterior ST elevation. Urgent cardiology review.', True,
          [{'label': 'Heart rate', 'value': '104', 'unit': '/min', 'abnormal': True}], hours=5)
    study(e, rad, 'echo', 'Heart', 'heart', di.echo(), 'Dilated left ventricle with anterior wall hypokinesia.', 'Reduced left ventricular function.', True,
          [{'label': 'Ejection fraction', 'value': '38', 'unit': '%', 'abnormal': True}], hours=2)
    return 3


def population_history(doctor, months=4):
    """Four months of completed visits so the health dashboard has trends, including a recent malaria surge."""
    if Encounter.objects.filter(reason='Outpatient visit (history)').exists():
        return 0
    now = timezone.now()
    pts = list(Patient.objects.all())
    for _ in range(90):   # a broader population: all ages, several towns
        sex = random.choice('MF'); age = random.choice([random.randint(0, 9), random.randint(10, 39), random.randint(18, 45), random.randint(40, 85)])
        pts.append(new_patient(random.choice(FIRST_F if sex == 'F' else FIRST_M), random.choice(LAST), sex, age, random.choice(TOWNS)))
    depts = {d.name: d for d in Department.objects.all()}
    meds = {m.name: m for m in Medication.objects.all()}
    mal, cbc = LabTest.objects.get(code='MAL'), LabTest.objects.get(code='CBC')
    rdt = mal.parameters.get(code='RDT')
    mix = [('Uncomplicated malaria', 22), ('Upper respiratory tract infection', 18), ('Acute gastroenteritis', 10), ('Hypertension review', 9),
           ('Type 2 diabetes review', 7), ('Urinary tract infection', 7), ('Pneumonia', 5), ('Iron-deficiency anaemia', 5), ('Typhoid fever', 3)]
    regimens = {'malaria': [('Artemether/Lumefantrine', 4, 'BD', 3), ('Paracetamol', 2, 'TDS', 3)], 'respiratory': [('Paracetamol', 2, 'QDS', 5)],
                'gastroenteritis': [('ORS', 1, 'TDS', 3), ('Zinc sulfate', 1, 'OD', 10)], 'hypertension': [('Amlodipine', 1, 'OD', 30)],
                'diabetes': [('Metformin', 1, 'BD', 30)], 'urinary': [('Amoxicillin', 1, 'TDS', 7)], 'pneumonia': [('Amoxicillin', 1, 'TDS', 7)],
                'anaemia': [('Ferrous sulfate', 1, 'BD', 30)], 'typhoid': [('Ceftriaxone', 1, 'OD', 7)]}
    made = 0
    for day in range(months * 30, 0, -1):
        surge = day <= 9                                            # rainy-season malaria surge in the last days
        for _ in range(random.randint(4, 8)):
            names, weights = zip(*mix)
            weights = [w * (4 if surge and n.endswith('malaria') else 1) for n, w in zip(names, weights)]
            dx = random.choices(names, weights=weights)[0]
            p = random.choice(pts)
            when = now - timedelta(days=day, hours=random.randint(0, 9))
            key = next((k for k in regimens if k in dx.lower()), None)
            e = Encounter.objects.create(patient=p, clinician=doctor, department=depts.get('Outpatient'), reason='Outpatient visit (history)', diagnosis=dx,
                                         status='completed', completed_at=when + timedelta(hours=1),
                                         outcome=random.choices(['resolved', 'improved', 'no_change', 'worsened'], weights=[62, 25, 9, 4])[0])
            Encounter.objects.filter(pk=e.pk).update(created_at=when)
            if 'malaria' in dx.lower() or (dx.startswith('Upper') and random.random() < .35) or dx.startswith('Typhoid'):
                lr = LabRequest.objects.create(encounter=e, requested_by=doctor)
                o = LabOrder.objects.create(encounter=e, request=lr, test=mal, status='verified', resulted_at=when + timedelta(minutes=40), verified_at=when + timedelta(minutes=50))
                pos = 'malaria' in dx.lower() and random.random() < (.9 if surge else .8)
                val = 'Positive · P. falciparum' if pos else 'Negative'
                LabResultValue.objects.create(order=o, parameter=rdt, value_text=val, flag=rdt.flag_for(val, p.sex))
                LabOrder.objects.filter(pk=o.pk).update(created_at=when)
            if key:
                rx = Prescription.objects.create(encounter=e, allergy_reviewed=True, state='dispensed', signed_by=doctor, signed_at=when)
                lines = list(regimens[key])
                if key == 'respiratory' and random.random() < .45:
                    lines.append(('Amoxicillin', 1, 'TDS', 5))       # some antibiotic over-use, for the stewardship indicator
                for i, (name, per, freq, days) in enumerate(lines):
                    if name in meds:
                        PrescriptionItem.objects.create(prescription=rx, medication=meds[name], units_per_dose=per, frequency=freq, duration_days=days,
                                                        quantity=PrescriptionItem.calculate_quantity(per, freq, days) or 10, sort_order=i)
                Prescription.objects.filter(pk=rx.pk).update(created_at=when)
            made += 1
    return made


def inpatient_charts(doctor, nurse):
    """Signed medicines for current inpatients, with today's earlier doses recorded so the bed page shows a live chart."""
    now = timezone.localtime()
    meds = {m.name: m for m in Medication.objects.all()}
    plans = [[('Ceftriaxone', '1 g', 1, 'iv', 'OD', 5), ('Paracetamol', '500 mg', 2, 'oral', 'QDS', 3)],
             [('Artemether/Lumefantrine', '20/120 mg', 4, 'oral', 'BD', 3), ('Paracetamol', '500 mg', 2, 'oral', 'TDS', 3), ('ORS', '20.5 g', 1, 'oral', 'PRN', 3)],
             [('Amlodipine', '5 mg', 1, 'oral', 'OD', 30), ('Metformin', '500 mg', 1, 'oral', 'BD', 30), ('Ibuprofen', '400 mg', 1, 'oral', 'PRN', 3)]]
    made = 0
    for adm, plan in zip(Admission.objects.filter(discharged_at__isnull=True).select_related('encounter').order_by('admitted_at')[:6], plans * 2):
        e = adm.encounter
        if PrescriptionItem.objects.filter(prescription__encounter=e).exists():
            continue
        start = max(adm.admitted_at, timezone.now() - timedelta(days=1))
        rx = Prescription.objects.create(encounter=e, allergy_reviewed=True, state='signed', signed_by=doctor, signed_at=start)
        Prescription.objects.filter(pk=rx.pk).update(created_at=start)
        from .views import DOSE_HOURS
        for i, (name, dose, per, route, freq, days) in enumerate(plan):
            it = PrescriptionItem.objects.create(prescription=rx, medication=meds[name], dose=dose, units_per_dose=per, route=route, frequency=freq,
                                                 duration_days=days, quantity=PrescriptionItem.calculate_quantity(per, freq, days) or 8, sort_order=i)
            for h in DOSE_HOURS.get(freq, []):
                at = now.replace(hour=h, minute=0, second=0, microsecond=0)
                if at < now - timedelta(hours=1) and at >= start:
                    status = 'refused' if (made + h) % 9 == 0 else 'given'
                    if (made + h) % 7 != 0:                            # leave the odd dose unrecorded so it shows as late
                        MedicationAdministration.objects.create(item=it, scheduled_for=at, status=status, given_by=nurse, given_at=at + timedelta(minutes=random.randint(0, 25)),
                                                                note='Patient declined; doctor informed' if status == 'refused' else '')
        made += 1
    return made


def run_all():
    doctor = staff_user('doctor'); rad = staff_user('radiology') or doctor; nurse = staff_user('nurse') or doctor
    if not doctor:
        return {}
    from .management.commands.bootstrap_hospital import link_patient_locations
    res = {'brain cases': brain_cases(doctor, rad), 'featured imaging': featured_imaging(doctor, rad),
            'history visits': population_history(doctor), 'inpatient charts': inpatient_charts(doctor, nurse)}
    res['bone and injury cases'] = bone_cases(doctor, rad, nurse)
    res['specialist logins'] = network_portal(doctor)
    res['patients placed on map'] = link_patient_locations()
    return res


def bone_cases(doctor, rad, nurse):
    """Fictional bone, spine and injury cases with scans, results, medicines, admissions and referrals."""
    from .models import Bed, Referral, ReferralTask, NetworkFacility, Specialist
    if Encounter.objects.filter(diagnosis__icontains='femoral shaft').exists():
        return 0
    now = timezone.now()
    surg = Department.objects.filter(name='Surgery').first() or Department.objects.first()
    em = Department.objects.filter(name='Emergency').first() or surg
    meds = {m.name: m for m in Medication.objects.all()}
    def rx(enc, lines, state='signed'):
        p = Prescription.objects.create(encounter=enc, allergy_reviewed=True, state=state, signed_by=doctor, signed_at=now - timedelta(hours=3))
        for i, (name, dose, per, route, freq, days) in enumerate(lines):
            if name in meds:
                PrescriptionItem.objects.create(prescription=p, medication=meds[name], dose=dose, units_per_dose=per, route=route, frequency=freq,
                                                duration_days=days, quantity=PrescriptionItem.calculate_quantity(per, freq, days) or 10, sort_order=i)
        return p
    def admit(enc, ward_kind='general'):
        bed = Bed.objects.filter(state='available', kind=ward_kind).first() or Bed.objects.filter(state='available').first()
        if bed:
            a = Admission.objects.create(encounter=enc, bed=bed); Admission.objects.filter(pk=a.pk).update(admitted_at=now - timedelta(hours=20))
            bed.state = 'occupied'; bed.save(update_fields=['state'])
    def refer(enc, speciality, reason, kind='consultation', days=2):
        sp = Specialist.objects.filter(speciality__icontains=speciality, active=True).select_related('facility').first()
        r = Referral.objects.create(encounter=enc, kind=kind, facility=sp.facility if sp else None, specialist=sp, destination=sp.facility.name if sp else f'{speciality} clinic',
                                    speciality=sp.speciality if sp else speciality, reason=reason, urgency='urgent', status='sent', sent_at=now - timedelta(hours=2),
                                    consent_to_share=bool(sp), planned_date=timezone.localdate() + timedelta(days=days) if kind == 'operation' else None)
        if kind == 'operation':
            from .views import PREOP_CHECKLIST
            tests = {t.code: t for t in LabTest.objects.all()}
            for side, k, title, code in PREOP_CHECKLIST:
                ReferralTask.objects.create(referral=r, requested_by_side='receiver' if side == 'sender' else 'sender', assigned_to_side=side, kind=k, title=title,
                                            lab_test=tests.get(code), due=r.planned_date, created_by=doctor)
        return r
    made = 0
    # 1. Road traffic accident: displaced femoral shaft fracture, admitted, referred for fixation (ORIF)
    p = new_patient('Ebrima', 'Touray', 'M', 34, 'Serrekunda')
    e = Encounter.objects.create(patient=p, clinician=doctor, department=em, status='open', reason='Motorbike accident, unable to stand, left thigh deformity',
                                 diagnosis='Closed displaced fracture of left femoral shaft (road traffic accident)', symptoms='Severe left thigh pain after motorbike collision 2 h ago.',
                                 assessment='Shortened, externally rotated left leg; distal pulses present; no open wound.',
                                 vitals={'bp': '104/66', 'heart_rate': '118', 'temperature_c': '36.9', 'spo2': '98', 'pain_score': '9'})
    study(e, rad, 'xray', 'Left femur', 'bone', di.xray_long_bone('femur'), 'Transverse fracture of the mid-shaft of the left femur with lateral displacement and small fragments.',
          'Displaced mid-shaft femoral fracture.', True, [{'label': 'Displacement', 'value': '24', 'unit': 'mm', 'abnormal': True}], hours=5)
    lab_result(e, 'CBC', {'HB': 10.8, 'WBC': 13.2, 'PLT': 260, 'RBC': 3.9, 'HCT': 33, 'MCV': 85}, doctor, hours=4)
    lab_result(e, 'BGRP', {'ABO': 'O+'}, doctor, hours=4)
    rx(e, [('Paracetamol', '1 g', 2, 'oral', 'QDS', 5), ('Ceftriaxone', '1 g', 1, 'iv', 'OD', 1)])
    admit(e); refer(e, 'Orthop', 'Displaced femoral shaft fracture for intramedullary nailing / ORIF. Haemodynamically stable after 1 L saline; Hb 10.8.', 'operation')
    made += 1
    # 2. Lumbar disc herniation with sciatica
    p = new_patient('Fatou', 'Ceesay', 'F', 46, 'Brikama')
    e = Encounter.objects.create(patient=p, clinician=doctor, department=surg, status='open', reason='Low back pain shooting down the right leg for 3 weeks',
                                 diagnosis='L4/L5 disc herniation with right sciatica', assessment='Straight-leg raise positive at 35° on the right; reduced ankle reflex.',
                                 vitals={'bp': '128/82', 'heart_rate': '78', 'pain_score': '7'})
    study(e, rad, 'mri', 'Lumbar spine', 'bone', di.mri_spine('disc'), 'Posterior disc protrusion at L4/L5 indenting the thecal sac and right exiting nerve root.',
          'L4/L5 disc herniation compressing the right L5 nerve root.', True, hours=26)
    rx(e, [('Ibuprofen', '400 mg', 1, 'oral', 'TDS', 7), ('Paracetamol', '500 mg', 2, 'oral', 'QDS', 7)])
    refer(e, 'Physio', 'Lumbar disc herniation with sciatica, no red flags. Please start core strengthening and nerve-glide programme.')
    made += 1
    # 3. Osteoporotic vertebral compression fracture
    p = new_patient('Modou', 'Jallow', 'M', 71, 'Bakau', medical_alerts='Osteoporosis')
    e = Encounter.objects.create(patient=p, clinician=doctor, department=surg, status='open', reason='Sudden mid-back pain after a minor fall at home',
                                 diagnosis='Osteoporotic compression fracture of T12 vertebra', vitals={'bp': '142/86', 'heart_rate': '82', 'pain_score': '8'})
    Condition.objects.get_or_create(patient=p, name='Osteoporosis', defaults={'status': 'active'})
    study(e, rad, 'xray', 'Thoracolumbar spine', 'bone', di.xray_spine(compression=3), 'Anterior wedge compression of T12 with about 40% height loss. Posterior wall intact.',
          'Stable osteoporotic wedge fracture of T12.', True, [{'label': 'Height loss', 'value': '40', 'unit': '%', 'abnormal': True}], hours=8)
    lab_result(e, 'BONE', {'CA': 2.12, 'PHOS': 0.9, 'VITD': 28}, doctor, hours=6)
    rx(e, [('Paracetamol', '1 g', 2, 'oral', 'QDS', 14)])
    made += 1
    # 4. Whiplash / neck injury, normal cervical X-ray
    p = new_patient('Isatou', 'Bah', 'F', 28, 'Kololi')
    e = Encounter.objects.create(patient=p, clinician=doctor, department=em, status='completed', outcome='improved', completed_at=now - timedelta(hours=20),
                                 reason='Neck pain after a car was hit from behind', diagnosis='Whiplash neck injury after road traffic accident', vitals={'bp': '118/74', 'pain_score': '5'})
    study(e, rad, 'xray', 'Cervical spine', 'bone', di.xray_spine('cervical', seed=47), 'Normal alignment C1–C7. No fracture or prevertebral swelling.', 'No cervical spine fracture.', False, hours=26)
    rx(e, [('Paracetamol', '500 mg', 2, 'oral', 'QDS', 5)], state='dispensed')
    made += 1
    # 5. Child: supracondylar humerus fracture
    p = new_patient('Lamin', 'Sanneh', 'M', 9, 'Lamin')
    e = Encounter.objects.create(patient=p, clinician=doctor, department=em, status='open', reason='Fell from a tree onto outstretched hand, swollen elbow',
                                 diagnosis='Supracondylar fracture of right humerus (child)', assessment='Swollen right elbow; radial pulse present; sensation intact.',
                                 vitals={'heart_rate': '104', 'temperature_c': '36.8', 'pain_score': '8'})
    study(e, rad, 'xray', 'Right elbow', 'bone', di.xray_long_bone('humerus'), 'Extension-type supracondylar fracture of the distal humerus, posterior displacement.',
          'Displaced supracondylar fracture (Gartland type III).', True, hours=3)
    rx(e, [('Paracetamol', '250 mg', 1, 'oral', 'QDS', 3), ('Ibuprofen', '200 mg', 1, 'oral', 'TDS', 3)])
    refer(e, 'Orthop', 'Displaced supracondylar fracture in a 9-year-old; neurovascularly intact. Needs closed reduction and pinning today.', 'operation', days=0)
    made += 1
    # 6. Spinal cord injury after a fall from a mango tree
    p = new_patient('Ousman', 'Camara', 'M', 38, 'Farafenni')
    e = Encounter.objects.create(patient=p, clinician=doctor, department=em, status='open', reason='Fell from a mango tree, cannot move or feel legs',
                                 diagnosis='Spinal cord injury at T10 with paraplegia after fall from a tree', assessment='Power 0/5 both legs; sensory level T10; priapism absent.',
                                 vitals={'bp': '96/58', 'heart_rate': '58', 'spo2': '97', 'pain_score': '6'})
    study(e, rad, 'mri', 'Thoracic spine', 'bone', di.mri_spine('cord'), 'Burst fracture of T10 with retropulsion; cord oedema from T9 to T11.', 'T10 burst fracture with spinal cord injury.', True, hours=6)
    lab_result(e, 'CBC', {'HB': 12.9, 'WBC': 11.0, 'PLT': 240, 'RBC': 4.4, 'HCT': 39, 'MCV': 88}, doctor, hours=7)
    rx(e, [('Paracetamol', '1 g', 2, 'oral', 'QDS', 5), ('Ceftriaxone', '1 g', 1, 'iv', 'OD', 3)])
    admit(e); refer(e, 'Neurosurg', 'T10 burst fracture with complete paraplegia (sensory level T10). Log-roll and spinal precautions in place. Request urgent spinal stabilisation.', 'operation', days=1)
    made += 1
    # 7. Knee osteoarthritis (rheumatoid factor negative)
    p = new_patient('Awa', 'Jobe', 'F', 61, 'Banjul')
    e = Encounter.objects.create(patient=p, clinician=doctor, department=surg, status='completed', outcome='improved', completed_at=now - timedelta(days=3),
                                 reason='Painful knees, worse on stairs', diagnosis='Bilateral knee osteoarthritis', vitals={'bp': '136/84', 'pain_score': '5'})
    Condition.objects.get_or_create(patient=p, name='Knee osteoarthritis', defaults={'status': 'active'})
    study(e, rad, 'xray', 'Left knee', 'bone', di.knee_xray(seed=29), 'Medial joint-space narrowing with osteophytes.', 'Moderate osteoarthritis of the knee.', True, hours=80)
    if LabTest.objects.filter(code='RF').exists():
        lab_result(e, 'RF', {'RF': 'Negative'}, doctor, hours=80)
    lab_result(e, 'ESR', {'ESR': 14}, doctor, hours=80)
    made += 1
    # 8. Acute gout (uric acid high)
    p = new_patient('Bakary', 'Fofana', 'M', 52, 'Soma', medical_alerts='Hypertension')
    e = Encounter.objects.create(patient=p, clinician=doctor, department=em, status='open', reason='Hot, swollen big toe overnight', diagnosis='Acute gout of the right big toe',
                                 assessment='Red, hot, exquisitely tender right first MTP joint.', vitals={'bp': '152/94', 'temperature_c': '37.6', 'pain_score': '9'})
    if LabTest.objects.filter(code='URIC').exists():
        lab_result(e, 'URIC', {'URIC': 612}, doctor, hours=2)
    lab_result(e, 'CRP', {'CRP': 48}, doctor, hours=2)
    rx(e, [('Ibuprofen', '400 mg', 1, 'oral', 'TDS', 5)])
    made += 1
    # earlier bone, joint and injury visits for the category counts and trends
    pts = list(Patient.objects.all())
    mix = ['Mechanical low back pain', 'Ankle sprain', 'Distal radius fracture after a fall', 'Knee osteoarthritis review', 'Shoulder dislocation, reduced',
           'Lumbar strain lifting at work', 'Fracture of clavicle', 'Rheumatoid arthritis review', 'Laceration of hand', 'Head injury, minor (road traffic accident)',
           'Burns to forearm', 'Tibial fracture follow-up (healing)', 'Cervical spondylosis', 'Dog bite to leg']
    for _ in range(70):
        when = now - timedelta(days=random.randint(2, 120), hours=random.randint(0, 9))
        pe = Encounter.objects.create(patient=random.choice(pts), clinician=doctor, department=random.choice([surg, em]), reason='Outpatient visit (history)',
                                      diagnosis=random.choice(mix), status='completed', completed_at=when + timedelta(hours=1),
                                      outcome=random.choices(['resolved', 'improved', 'no_change', 'worsened'], weights=[45, 40, 12, 3])[0])
        Encounter.objects.filter(pk=pe.pk).update(created_at=when)
    return made


def network_portal(doctor):
    """Specialist logins, live statuses, an incoming referral, a closed (locked) case and some notifications."""
    from django.contrib.auth import get_user_model
    from .models import NetworkFacility, Notification, Referral, Specialist, StaffProfile
    from .notify import notify
    U = get_user_model()
    if U.objects.filter(username='dr.bojang').exists() or not Specialist.objects.exists():
        return 0
    now = timezone.now()
    notes = {'available': ['Clinic open', 'Free this afternoon', ''], 'busy': ['Clinic running 40 min late', 'Ward round until 11:00'],
             'procedure': ['In theatre until 14:00', 'Cath lab: back around 15:30'], 'on_call': ['On call tonight for emergencies'], 'away': ['At a conference until Friday']}
    for sp in Specialist.objects.all():
        state = random.choices(list(notes), weights=[45, 25, 12, 10, 8])[0]
        sp.presence, sp.presence_note, sp.presence_at = state, random.choice(notes[state]), now - timedelta(minutes=random.randint(3, 240))
        sp.where = 'Teleconsult only' if state == 'away' else f'{sp.facility.name}, clinic room {random.randint(1, 6)}'
        sp.save(update_fields=['presence', 'presence_note', 'presence_at', 'where'])
    made = 0
    for username, name, email in (('dr.bojang', 'Aminata Bojang', 'a.bojang@kotuheart.network.example'), ('dr.kceesay', 'Kebba Ceesay', 'k.ceesay@riverside.network.example')):
        sp = Specialist.objects.filter(name=name).first()
        if not sp:
            continue
        u = U.objects.create_user(username, password='medflow-demo-2026', email=email, first_name=name.split()[0], last_name=name.split()[-1])
        StaffProfile.objects.create(user=u, role='specialist', specialist=sp)
        made += 1
    Referral.objects.filter(created_by__isnull=True, direction='out').update(created_by=doctor)
    # the featured cardiology referral: accepted, record already sent
    for r in Referral.objects.filter(status__in=['accepted', 'transferred'], consent_to_share=True, shared_at__isnull=True):
        r.shared_at = (r.sent_at or now) + timedelta(minutes=20); r.save(update_fields=['shared_at'])
    bojang = Specialist.objects.filter(name='Aminata Bojang').first()
    # a closed case for the learning library
    done = Referral.objects.filter(specialist=bojang, status='sent').exclude(encounter__patient__first_name='Babucarr').first() if bojang else None
    if done:
        done.status, done.accepted_by, done.consent_to_share = 'completed', 'Dr Aminata Bojang', True
        done.shared_at, done.completed_at, done.locked_at = now - timedelta(days=6), now - timedelta(days=2), now - timedelta(days=2)
        done.save()
        Encounter.objects.filter(pk=done.encounter_id).update(outcome='improved', diagnosis=done.encounter.diagnosis or 'Stable angina, medical management')
    # an incoming referral waiting in the hospital inbox
    kotu = NetworkFacility.objects.filter(name='Kotu Heart Centre').first()
    p = Patient.objects.filter(encounters__isnull=False).exclude(first_name='Babucarr').order_by('?').first()
    if kotu and p:
        enc = Encounter.objects.create(patient=p, department=Department.objects.filter(name='General Medicine').first(), reason=f'Referral from {kotu.name}', status='open')
        partner = StaffProfile.objects.filter(role='partner', facility=kotu).select_related('user').first()
        r = Referral.objects.create(encounter=enc, direction='in', from_facility=kotu, created_by=partner.user if partner else None, destination='E-MedFlow hospital',
                                    speciality='General Medicine', urgency='urgent', kind='consultation', status='sent', sent_at=now - timedelta(minutes=25), consent_to_share=True,
                                    reason='Seen in our cardiac clinic: echo normal, chest pain non-cardiac. Poorly controlled diabetes (HbA1c 9.4%). Please take over diabetes care and review medicines.')
        notify([u for u in U.objects.filter(hospital_staff__role__in=['doctor', 'admin'])], f'Incoming referral {r.number} from {kotu.name}', 'Urgent · General Medicine',
               f'/referrals/{r.pk}/', 'referral_new')
    sp_user = U.objects.filter(username='dr.bojang').first()
    if sp_user:
        for r in Referral.objects.filter(specialist=bojang, status='sent')[:2]:
            notify([sp_user], f'New referral {r.number}', f'{r.get_urgency_display()} · {r.get_kind_display()}', f'/referrals/{r.pk}/', 'referral_new')
    Notification.objects.filter(created_at__gte=now - timedelta(minutes=5)).update(emailed_at=now)   # demo: do not send real emails
    return made
