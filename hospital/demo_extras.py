"""Extra fictional demo data: brain cases and scans, imaging, four months of visits for the health dashboard,
and inpatient medication charts. Used by seed_demo and by seed_demo_extras (for databases that already exist)."""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.utils import timezone

from . import demo_images as di
from .models import (Admission, Department, Encounter, ImagingImage, ImagingOrder, LabOrder, LabRequest, LabResultValue, LabTest,
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
    res['patients placed on map'] = link_patient_locations()
    return res
