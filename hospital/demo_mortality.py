"""FICTIONAL demo data for mortality, the mortuary, autopsy, M&M reviews and study cases (see hospital/mortality.py).

Every story runs through the real service layer, so the data obeys the same rules as real use: verification of death,
the WHO certificate checks, consent before autopsy, the release rules and the anonymisation of study cases. Times are
then moved into the past so the board, the alerts and the 12-month statistics have something to show.

Never run against a database that holds real patient information.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from . import mortality as MT
from .demo_extras import lab_result
from .models import (Admission, Autopsy, Bed, Condition, DeathRecord, Department, Encounter, Location, Medication, Patient, Prescription,
                     PrescriptionItem, StaffProfile, StudyCase, Ward)

NOW = None
STAFF = [('dr.jallow', 'Fatou', 'Jallow', 'doctor'), ('dr.ceesay', 'Lamin', 'Ceesay', 'doctor'), ('nurse.bah', 'Isatou', 'Bah', 'nurse'),
         ('lab.touray', 'Awa', 'Touray', 'lab'), ('manager.camara', 'Mariama', 'Camara', 'management')]
VERIFIED = {'check_no_pulse': 'on', 'check_no_heart_sounds': 'on', 'check_no_breath': 'on', 'check_pupils_fixed': 'on',
            'check_no_response': 'on', 'check_five_minutes': 'on'}
CHECKS = {f'chk_{k}': 'on' for k, _ in MT.STUDY_CHECKS}


# ------------------------------------------------------------------ helpers
def ago(days=0, hours=0, minutes=0):
    return NOW - timedelta(days=days, hours=hours, minutes=minutes)


def local(dt):
    return timezone.localtime(dt).strftime('%Y-%m-%dT%H:%M')


def staff(password):
    U = get_user_model()
    out = {}
    for username, first, last, role in STAFF:
        u = U.objects.filter(username=username).first()
        if not u:
            u = U.objects.create_user(username=username, password=password, first_name=first, last_name=last)
            StaffProfile.objects.get_or_create(user=u, defaults={'role': role})
        out[username.split('.')[0] if username.startswith(('lab', 'manager')) else username] = u
    out['admin'] = U.objects.filter(is_superuser=True).first() or U.objects.filter(hospital_staff__role='admin').first() or out['manager']
    return out


def dept(*names):
    for n in names:
        d = Department.objects.filter(name__icontains=n).first()
        if d:
            return d
    return Department.objects.first()


def med(name, strength='', form='injection', unit='vial', category='other'):
    m = Medication.objects.filter(name=name).first()
    return m or Medication.objects.create(name=name, strength=strength, form=form, unit=unit, category=category)


def patient(first, last, sex, years, days=0, phone='', contact='', conditions=(), at=None):
    """Age is given at the time of death (``at``), not today."""
    dob = ((at or NOW) - timedelta(days=int(years * 365.25) + days)).date()
    p = Patient.objects.create(first_name=first, last_name=last, sex=sex, dob=dob, phone=phone, emergency_contact=contact,
                               location=Location.objects.order_by('?').first())
    for name, status in conditions:
        Condition.objects.create(patient=p, name=name, status=status)
    Patient.objects.filter(pk=p.pk).update(created_at=ago(days=400))
    return p


def visit(p, when, clinician, nurse, department, reason, symptoms='', vitals=None, assessment='', diagnosis='', plan='', status='open'):
    e = Encounter.objects.create(patient=p, department=department, reason=reason, symptoms=symptoms, vitals=vitals or {}, assessment=assessment,
                                 diagnosis=diagnosis, plan=plan, clinician=clinician, attending_nurse=nurse, status=status,
                                 completed_at=when + timedelta(hours=2) if status == 'completed' else None)
    Encounter.objects.filter(pk=e.pk).update(created_at=when)
    e.refresh_from_db()
    return e


def admit(e, when, kind='general'):
    bed = (Bed.objects.filter(state='available', kind=kind).first() or Bed.objects.filter(state='available').first())
    if not bed:
        ward, _ = Ward.objects.get_or_create(name='Overflow ward (demo)')
        n = Bed.objects.filter(ward=ward).count() + 1
        bed = Bed.objects.create(ward=ward, code=f'OV-{n:02d}', kind=kind)
    Bed.objects.filter(pk=bed.pk).update(state='occupied')
    return Admission.objects.create(encounter=e, bed=bed, admitted_at=when)


def labs(e, when, by, results):
    hours = max(1.5, (NOW - when).total_seconds() / 3600)
    for code, values in results.items():
        lab_result(e, code, values, by, hours=hours)


def rx(e, when, by, items):
    p = Prescription.objects.create(encounter=e, state='dispensed', signed_by=by, allergy_reviewed=True)
    for i, (m, dose, route, freq, days, qty) in enumerate(items):
        PrescriptionItem.objects.create(prescription=p, medication=m, dose=dose, route=route, frequency=freq, duration_days=days, quantity=qty, sort_order=i)
    Prescription.objects.filter(pk=p.pk).update(created_at=when)


def die(p, when, by, place='ward', **extra):
    d, _ = MT.record_death(p, by, {'died_at': local(when), 'place': place, **VERIFIED, **extra})
    DeathRecord.objects.filter(pk=d.pk).update(pronounced_at=when + timedelta(minutes=12), created_at=when + timedelta(minutes=12))
    if d.admission_id and when < NOW - timedelta(days=1):                   # long since cleaned and reused
        Bed.objects.filter(pk=d.admission.bed_id).update(state='available')
        Admission.objects.filter(pk=d.admission_id).update(discharged_at=when + timedelta(hours=1))
    return DeathRecord.objects.get(pk=d.pk)


def informed(d, by, after_hours=1, how='in_person', consent='not_asked', notes='', rapid=False, **nok):
    MT.inform_family(d, by, {'informed': 'on', 'nok_how': how, 'informed_at': local(d.died_at + timedelta(hours=after_hours)),
                             'teaching_consent': consent, 'family_notes': notes, 'rapid_release': 'on' if rapid else '', **nok})
    return DeathRecord.objects.get(pk=d.pk)


def certify(d, by, after_hours, **chain):
    MT.certify(d, by, chain)
    d = DeathRecord.objects.get(pk=d.pk)
    d.certified_at = d.died_at + timedelta(hours=after_hours)
    d.content_hash = MT.certificate_hash(d)                                  # the seal covers the time of signing
    d.save(update_fields=['certified_at', 'content_hash'])
    return d


def mortuary(d, by, slot, after_hours=2):
    MT.move_body(d, by, 'mortuary', {'mortuary_slot': slot})
    DeathRecord.objects.filter(pk=d.pk).update(mortuary_in_at=d.died_at + timedelta(hours=after_hours))
    return DeathRecord.objects.get(pk=d.pk)


def release(d, by, after_hours, to, relation, id_doc, notes=''):
    MT.move_body(d, by, 'release', {'released_to': to, 'released_relation': relation, 'released_id_doc': id_doc,
                                    'identity_confirmed': 'on', 'release_notes': notes})
    DeathRecord.objects.filter(pk=d.pk).update(released_at=d.died_at + timedelta(hours=after_hours))
    return DeathRecord.objects.get(pk=d.pk)


def autopsy(d, req, lab, kind, questions, consent=None, sign=None, start=True, after_hours=20, **report):
    a = MT.request_autopsy(d, req, {'kind': kind, 'questions': questions, 'legal_authority': report.pop('legal_authority', '')})
    if consent:
        MT.autopsy_action(a, req, 'consent', consent)
    if start:
        MT.autopsy_action(a, lab, 'start', {})
        a.refresh_from_db()
        if report:
            MT.save_autopsy(a, report)
    if sign:
        MT.autopsy_action(a, lab, 'sign', sign)
        t = d.died_at + timedelta(hours=after_hours)
        Autopsy.objects.filter(pk=a.pk).update(started_at=t - timedelta(hours=3), signed_at=t + timedelta(days=4), completed_at=t + timedelta(days=4),
                                               consent_at=d.died_at + timedelta(hours=3) if consent else None)
    Autopsy.objects.filter(pk=a.pk).update(created_at=d.died_at + timedelta(hours=2))
    a.refresh_from_db()
    return a


def review(d, chair, days_after, final=True, **data):
    MT.save_review(d, chair, {'meeting_date': (d.died_at + timedelta(days=days_after)).date().isoformat(), **data}, finalise=final)
    if final:
        from .models import MortalityReview
        MortalityReview.objects.filter(death=d).update(finalised_at=d.died_at + timedelta(days=days_after))


def publish(d, by, teaching, question=''):
    sc = StudyCase.objects.get(death=d)
    MT.publish_case(sc, by, {'teaching_points': teaching, 'question': question or sc.question, **CHECKS})
    StudyCase.objects.filter(pk=sc.pk).update(published_at=d.died_at + timedelta(days=21), views=random.randint(4, 60))


# ------------------------------------------------------------------ the stories
def run(password='medflow-demo-2026'):
    global NOW
    NOW = timezone.now()
    random.seed(7)
    if DeathRecord.objects.exists():
        return None
    s = staff(password)
    doc, er, nurse, lab, mgr = s['dr.jallow'], s['dr.ceesay'], s['nurse.bah'], s['lab'], s['manager']
    opd, emerg, peds, mat = dept('General Medicine', 'Medicine', 'Outpatient'), dept('Emergency', 'Outpatient'), dept('Paediatric', 'Pediatric', 'Outpatient'), dept('Maternity', 'Antenatal', 'Outpatient')
    artesunate = med('Artesunate', '60 mg', category='antimalarial')
    ceftriaxone = med('Ceftriaxone', '1 g')
    furosemide = med('Furosemide', '40 mg', form='tablet', unit='tablet')
    oxytocin = med('Oxytocin', '10 IU', unit='ampoule')
    amphotericin = med('Amphotericin B', '50 mg')
    amlodipine, metformin, paracetamol = med('Amlodipine', '5 mg', 'tablet', 'tablet'), med('Metformin', '500 mg', 'tablet', 'tablet'), med('Paracetamol', '500 mg', 'tablet', 'tablet')
    told = []

    # 1. Died three hours ago; family asks for same-day burial; certificate not yet written (red alert, body on the ward)
    p = patient('Ebrima', 'Kinteh', 'M', 67, phone='+220 712 4400', contact='Omar Kinteh (son) +220 755 1020',
                conditions=[('Hypertension', 'active'), ('Type 2 diabetes', 'active')])
    e = visit(p, ago(days=2, hours=6), doc, nurse, emerg, 'Sudden right-sided weakness and slurred speech',
              symptoms='Woke with right arm and leg weakness, unable to speak clearly. Stopped his amlodipine two months ago.',
              vitals={'bp': '212/118', 'heart_rate': '96', 'temperature_c': '36.9', 'spo2': '95', 'resp_rate': '20'},
              assessment='Dense right hemiplegia, expressive dysphasia, GCS 12. No CT available today.',
              diagnosis='Stroke, probably haemorrhagic (hypertensive)', plan='Admit, head up 30°, cautious BP lowering, NG feeding, turn 2-hourly.')
    admit(e, ago(days=2, hours=5))
    labs(e, ago(days=2, hours=5), doc, {'GLU': {'FBG': 13.8}, 'RFT': {'CREA': 168, 'UREA': 11.2, 'NA': 134, 'K': 4.9, 'CL': 99}})
    rx(e, ago(days=2, hours=4), doc, [(amlodipine, '10 mg', 'oral', 'OD', 30, 30)])
    d = die(p, ago(hours=3), nurse, place='ward', resuscitation='dnacpr',
            circumstances='GCS fell from 12 to 6 overnight with irregular breathing. Family at the bedside agreed comfort care. Died peacefully.')
    informed(d, nurse, after_hours=0, how='present', rapid=True, nok_name='Omar Kinteh', nok_relation='son', nok_phone='+220 755 1020',
             notes='Muslim family; burial planned for this afternoon. Imam has been called. Body to be washed by the family at home.')
    told.append('Ebrima Kinteh · died 3 h ago, rapid release, no certificate')

    # 2. Dead on arrival 30 hours ago; family not reached; verbal autopsy requested
    p = patient('Musa', 'Bojang', 'M', 45, contact='')
    e = visit(p, ago(hours=30, minutes=20), er, nurse, emerg, 'Brought in dead by neighbours',
              symptoms='Collapsed at home in the evening, complained of chest pain earlier in the day according to neighbours.',
              assessment='No signs of life on arrival. No injuries seen.')
    d = die(p, ago(hours=30, minutes=40), er, place='dead_on_arrival', time_estimated='on', place_detail='Emergency department, ambulance bay',
            circumstances='Brought by taxi by two neighbours about 45 minutes after collapse. Asystole on arrival; no resuscitation, clearly futile.',
            resuscitation='futile')
    mortuary(d, nurse, 'M-03', after_hours=1)
    MT.request_autopsy(d, er, {'kind': 'verbal', 'questions': 'Chest pain then collapse: cardiac cause? Any known illness? Interview family once reached.'})
    told.append('Musa Bojang · dead on arrival, family not reached, no certificate after 30 h')

    # 3. Child with cerebral malaria; certified; clinical autopsy in progress
    p = patient('Binta', 'Jarju', 'F', 7, phone='+220 390 1188', contact='Kaddy Jarju (mother) +220 390 1188')
    e = visit(p, ago(days=5), doc, nurse, peds, 'Fever for 4 days, convulsions this morning',
              symptoms='High fever, vomiting, two generalised convulsions at home. Not given any medicine before coming. Lives far from the health centre.',
              vitals={'temperature_c': '40.1', 'heart_rate': '148', 'resp_rate': '40', 'spo2': '93', 'weight_kg': '19'},
              assessment='Unrousable (Blantyre 2), pale, deep breathing, no neck stiffness.', diagnosis='Severe malaria, cerebral, with severe anaemia',
              plan='IV artesunate, glucose, transfuse, monitor glucose hourly.')
    admit(e, ago(days=5) + timedelta(hours=1), kind='pediatric')
    labs(e, ago(days=5) + timedelta(hours=1), doc, {'MAL': {'RDT': 'Positive'}, 'MPS': {'DENS': 286000, 'SPEC': 'P. falciparum'},
                                                    'CBC': {'HB': 4.9, 'WBC': 14.2, 'PLT': 38, 'RBC': 1.9, 'HCT': 15, 'MCV': 80}, 'GLU': {'FBG': 2.1}})
    rx(e, ago(days=5) + timedelta(hours=2), doc, [(artesunate, '57 mg', 'iv', 'BD', 3, 6)])
    d = die(p, ago(days=2, hours=4), nurse, place='ward', resuscitation='attempted',
            circumstances='Second transfusion running. Respiratory arrest after a prolonged convulsion at 02:10; bag-mask ventilation and CPR for 25 minutes.')
    d = informed(d, nurse, after_hours=0.5, how='present', consent='granted', nok_name='Kaddy Jarju', nok_relation='mother', nok_phone='+220 390 1188',
                 notes='Mother asked whether she brought her too late. Father travelling, arrives tomorrow.')
    d = certify(d, doc, 9, cause_a='Cerebral oedema', interval_a='1 day', cause_b='Cerebral malaria', interval_b='3 days',
                cause_c='Plasmodium falciparum infection', interval_c='5 days', contributing='Severe anaemia', icd_underlying='B50.0', manner='natural')
    d = mortuary(d, nurse, 'M-01', after_hours=3)
    autopsy(d, doc, lab, 'clinical', 'Was the coma due to cerebral malaria alone? Any hypoglycaemic brain injury or bacterial meningitis?',
            consent={'consent_name': 'Kaddy Jarju', 'consent_relation': 'mother', 'consent_scope': 'Full autopsy; brain and spleen may be examined'},
            external_exam='Well-grown child, marked pallor, no rash, no injuries. Cannula sites on both hands.', height_cm='118', weight_kg='18.6',
            organ_brain_weight_g='1290', organ_brain_finding='Swollen with flattened gyri; slate-grey cortex; numerous ring haemorrhages in the white matter.',
            organ_brain_abnormal='on', organ_immune_weight_g='190', organ_immune_finding='Spleen enlarged, soft, dark slate-grey (malaria pigment).',
            organ_immune_abnormal='on', organ_liver_finding='Enlarged, grey-brown; pigment visible on cut surface.', organ_liver_abnormal='on')
    told.append('Binta Jarju · cerebral malaria, autopsy in progress, cabinet M-01')

    # 4. The full learning loop: pneumonia in life, pulmonary embolism at autopsy (Goldman I); published study case
    p = patient('Kebba', 'Sillah', 'M', 54, phone='+220 778 2231', contact='Fatoumata Sillah (wife) +220 778 2232',
                conditions=[('Obesity', 'active'), ('Hypertension', 'active')])
    t0 = ago(days=46)
    e = visit(p, t0, er, nurse, emerg, 'Breathless and coughing for 5 days',
              symptoms='Breathlessness worse over 5 days, dry cough, right-sided chest pain on breathing. Returned 10 days ago from a 2-day bus journey from Dakar. Left calf ached last week.',
              vitals={'bp': '128/84', 'heart_rate': '118', 'temperature_c': '37.6', 'spo2': '89', 'resp_rate': '28', 'weight_kg': '112'},
              assessment='Tachycardic, tachypnoeic; few crackles right base; calves not examined. Chest X-ray: small right effusion, no clear consolidation.',
              diagnosis='Community-acquired pneumonia', plan='IV ceftriaxone, oxygen, paracetamol. Review in the morning.')
    admit(e, t0 + timedelta(hours=1))
    labs(e, t0 + timedelta(hours=1), er, {'CBC': {'HB': 14.1, 'WBC': 10.8, 'PLT': 245, 'RBC': 5.0, 'HCT': 43, 'MCV': 87}, 'CRP': {'CRP': 34},
                                         'TROP': {'TNI': 0.09}})
    rx(e, t0 + timedelta(hours=2), er, [(ceftriaxone, '2 g', 'iv', 'OD', 5, 5), (paracetamol, '1 g', 'oral', 'QDS', 5, 40)])
    d = die(p, t0 + timedelta(days=3, hours=18), nurse, place='ward', resuscitation='attempted',
            circumstances='Got up to the toilet, became suddenly breathless, cyanosed and collapsed. Pulseless electrical activity; CPR for 30 minutes without return of circulation.')
    d = informed(d, er, after_hours=1, how='phone', consent='granted', nok_name='Fatoumata Sillah', nok_relation='wife', nok_phone='+220 778 2232',
                 notes='Wife asked why he died when he was getting antibiotics. Agreed to an autopsy so the family can understand.')
    d = certify(d, er, 6, cause_a='Respiratory failure', interval_a='Hours', cause_b='Lobar pneumonia', interval_b='9 days', manner='natural')
    d = mortuary(d, nurse, 'M-05')
    autopsy(d, er, lab, 'clinical', 'Sudden collapse on day 4 of treatment for pneumonia. Pulmonary embolism? Myocardial infarction?',
            consent={'consent_name': 'Fatoumata Sillah', 'consent_relation': 'wife', 'consent_scope': 'Full autopsy'},
            external_exam='Obese adult man (BMI about 37). Left calf 3 cm larger than right. No injuries.', height_cm='174', weight_kg='112',
            organ_lungs_weight_g='1380', organ_lungs_finding='Large saddle embolus at the bifurcation of the pulmonary trunk; older thrombo-emboli in right lower lobe arteries with a wedge-shaped infarct. No consolidation.',
            organ_lungs_abnormal='on', organ_heart_weight_g='460', organ_heart_finding='Dilated right ventricle. Coronary arteries: mild atheroma, no occlusion.',
            organ_heart_abnormal='on', organ_blood_finding='Occlusive thrombus in the left popliteal and calf veins.', organ_blood_abnormal='on',
            histology='Lung: organising thrombo-emboli of different ages; haemorrhagic infarct right lower lobe. No pneumonia.',
            sign={'anatomical_diagnosis': '1. Massive pulmonary thromboembolism (saddle embolus)\n2. Deep vein thrombosis, left leg\n3. Pulmonary infarct, right lower lobe\n4. Obesity',
                  'cause_a': 'Massive pulmonary embolism', 'cause_b': 'Deep vein thrombosis of the left leg', 'contributing': 'Obesity; prolonged immobility while travelling',
                  'goldman': 'I', 'correlation_notes': 'Pulmonary embolism was not considered. Tachycardia and hypoxia out of proportion to the X-ray, pleuritic pain, recent long journey and a sore calf were all present at admission. Anticoagulation could have prevented death.',
                  'learning_points': 'Hypoxia and tachycardia out of proportion to the chest X-ray: think pulmonary embolism\nAsk about long journeys and examine both calves in every breathless patient\nAssess VTE risk on admission; give prophylaxis to immobile medical patients'})
    d = DeathRecord.objects.get(pk=d.pk)
    d = certify(d, er, 30, cause_a='Massive pulmonary embolism', interval_a='Minutes', cause_b='Deep vein thrombosis of the left leg', interval_b='About 2 weeks',
                contributing='Obesity', icd_underlying='I26.9', manner='natural')        # certificate amended after autopsy, before release
    d = release(d, nurse, 120, 'Fatoumata Sillah', 'wife', 'National ID 0144-2208', notes='Collected by family with funeral car.')
    review(d, doc, 14, summary='Man in his fifties treated for pneumonia; sudden death on day 4. Autopsy: massive pulmonary embolism from a leg DVT, no pneumonia.',
           attendees='2 consultants, 3 medical officers, ward sister, pathologist', preventability='probably', delays=['receiving'],
           factors=['diagnosis', 'guideline', 'monitoring'], went_well='Rapid resuscitation; clear, honest conversation with the family; autopsy requested.',
           lessons='Pulmonary embolism was not in the differential despite classic features\nNo VTE risk assessment on the admission form\nTachycardia persisted for three days without review',
           action_0_text='Add VTE risk assessment to the medical admission form', action_0_owner='Medical director', action_0_due=(d.died_at + timedelta(days=45)).date().isoformat(), action_0_done='on',
           action_1_text='Teaching session: pulmonary embolism in the breathless patient', action_1_owner='Head of medicine', action_1_due=(d.died_at + timedelta(days=30)).date().isoformat(), action_1_done='on',
           action_2_text='Make enoxaparin available on the medical ward', action_2_owner='Chief pharmacist', action_2_due=(d.died_at + timedelta(days=60)).date().isoformat())
    publish(d, doc, 'Unexplained tachycardia and hypoxia need an explanation before they are blamed on pneumonia\nAsk about recent long journeys; examine both legs\nEvery admitted medical patient needs a VTE risk assessment',
            question='Treated as pneumonia, he collapsed on day 4. What killed him, and what clues were present on admission?')
    told.append('Kebba Sillah · missed pulmonary embolism, Goldman I, M&M final, published study case')

    # 5. Maternal death from postpartum haemorrhage; autopsy declined; published
    p = patient('Haddy', 'Sonko', 'F', 29, phone='+220 362 7745', contact='Lamin Sonko (husband) +220 362 7745')
    t0 = ago(days=78)
    e = visit(p, t0, er, nurse, mat, 'Heavy bleeding after home delivery',
              symptoms='Delivered her fifth baby at home 4 hours ago with a traditional birth attendant. Heavy bleeding since. Came 40 km by donkey cart then taxi.',
              vitals={'bp': '68/40', 'heart_rate': '146', 'temperature_c': '35.8', 'spo2': '91', 'resp_rate': '32'},
              assessment='Pale, cold, confused. Uterus boggy, above the umbilicus. Placenta delivered, appears complete. Ongoing bleeding.',
              diagnosis='Primary postpartum haemorrhage, uterine atony, hypovolaemic shock', plan='Two large cannulas, fluids, oxytocin infusion, bimanual compression, cross-match 4 units, call obstetrician.')
    admit(e, t0 + timedelta(minutes=20), kind='maternity')
    labs(e, t0 + timedelta(minutes=30), er, {'CBC': {'HB': 4.6, 'WBC': 16.0, 'PLT': 96, 'RBC': 1.7, 'HCT': 14, 'MCV': 78}, 'BGRP': {'ABO': 'O+'},
                                            'COAG': {'PT': 22, 'INR': 1.9, 'APTT': 52}})
    rx(e, t0 + timedelta(minutes=25), er, [(oxytocin, '40 IU in 1 L', 'iv', 'STAT', 1, 4)])
    d = die(p, t0 + timedelta(hours=6), er, place='maternity', resuscitation='attempted',
            circumstances='Only one unit of O-positive blood available in the bank; relatives tested but none eligible in time. Bleeding continued; cardiac arrest while waiting for theatre.')
    d = informed(d, er, after_hours=0.2, how='in_person', consent='granted', nok_name='Lamin Sonko', nok_relation='husband', nok_phone='+220 362 7745',
                 notes='Baby girl well, with her grandmother. Family agreed that the case can be used to teach, so that other mothers are saved.')
    d = certify(d, er, 4, cause_a='Hypovolaemic shock', interval_a='6 hours', cause_b='Postpartum haemorrhage', interval_b='10 hours',
                cause_c='Uterine atony', interval_c='10 hours', contributing='Severe anaemia in pregnancy; grand multiparity', icd_underlying='O72.1',
                manner='natural', maternal='within_42d')
    d = mortuary(d, nurse, 'M-04')
    a = MT.request_autopsy(d, er, {'kind': 'clinical', 'questions': 'Retained products? Uterine rupture? Amniotic fluid embolism?'})
    MT.autopsy_action(a, er, 'decline', {'note': 'Family declined: wish to bury her today according to custom.'})
    d = release(d, nurse, 9, 'Lamin Sonko', 'husband', 'National ID 0981-3311')
    review(d, mgr, 10, summary='Woman in her late twenties, fifth delivery at home; arrived in shock 4 hours later; died 6 hours after arrival waiting for blood.',
           attendees='Obstetrician, 2 midwives, medical officer, laboratory manager, matron', preventability='possibly', delays=['seeking', 'reaching', 'receiving'],
           factors=['late_presentation', 'blood', 'referral', 'cost', 'theatre'], went_well='Oxytocin and bimanual compression started within 10 minutes of arrival.',
           lessons='The blood bank held one unit of group O\nNo ambulance from the referring village\nNo antenatal visits since the first trimester',
           action_0_text='Monthly blood donation drive with the community', action_0_owner='Laboratory manager', action_0_due=(d.died_at + timedelta(days=30)).date().isoformat(), action_0_done='on',
           action_1_text='Misoprostol for community distribution at antenatal visits', action_1_owner='Head midwife', action_1_due=(d.died_at + timedelta(days=60)).date().isoformat())
    publish(d, mgr, 'Postpartum haemorrhage kills within hours: every delay counts\nKeep a minimum stock of group O blood; organise donors before the emergency\nOffer every pregnant woman a birth plan',
            question='What were the three delays in this death, and which could this hospital change?')
    told.append('Haddy Sonko · maternal death, three delays, autopsy declined, published study case')

    # 6. Heart failure, limited autopsy concordant (Goldman V); study case waiting for the anonymisation check
    p = patient('Omar', 'Gaye', 'M', 72, contact='Isatou Gaye (daughter) +220 701 5550',
                conditions=[('Hypertensive heart disease', 'active'), ('Type 2 diabetes', 'active'), ('Chronic kidney disease', 'active')])
    t0 = ago(days=24)
    e = visit(p, t0, doc, nurse, opd, 'Swollen legs and breathless at night',
              symptoms='Cannot lie flat for two weeks; legs swollen to the knees.', vitals={'bp': '164/98', 'heart_rate': '104', 'spo2': '90', 'resp_rate': '26', 'weight_kg': '81'},
              assessment='Raised JVP, bibasal crackles, pitting oedema to thighs.', diagnosis='Congestive heart failure (hypertensive heart disease)',
              plan='IV furosemide, fluid restriction, daily weights, restart amlodipine.')
    admit(e, t0 + timedelta(hours=1), kind='icu')
    labs(e, t0 + timedelta(hours=1), doc, {'RFT': {'CREA': 242, 'UREA': 18.4, 'NA': 129, 'K': 5.6, 'CL': 95}, 'GLU': {'FBG': 9.8}, 'TROP': {'TNI': 0.06}})
    rx(e, t0 + timedelta(hours=2), doc, [(furosemide, '80 mg', 'iv', 'BD', 5, 10), (metformin, '500 mg', 'oral', 'BD', 30, 60)])
    d = die(p, t0 + timedelta(days=4), nurse, place='icu', resuscitation='dnacpr', circumstances='Worsening kidney function despite treatment. Comfort care agreed with family on day 3.')
    d = informed(d, nurse, after_hours=1, how='phone', consent='policy', nok_name='Isatou Gaye', nok_relation='daughter')
    d = certify(d, doc, 5, cause_a='Congestive heart failure', interval_a='3 weeks', cause_b='Hypertensive heart disease', interval_b='Years',
                contributing='Type 2 diabetes; chronic kidney disease', icd_underlying='I11.0', manner='natural')
    d = mortuary(d, nurse, 'M-06')
    autopsy(d, doc, lab, 'limited', 'Confirm the cause of heart failure. Any silent myocardial infarction?',
            consent={'consent_name': 'Isatou Gaye', 'consent_relation': 'daughter', 'consent_scope': 'Limited to the chest: heart and lungs'},
            organ_heart_weight_g='620', organ_heart_finding='Concentric left ventricular hypertrophy (wall 19 mm), dilated chambers; no infarct; moderate coronary atheroma.',
            organ_heart_abnormal='on', organ_lungs_weight_g='1520', organ_lungs_finding='Heavy, oedematous lungs; bilateral pleural effusions.', organ_lungs_abnormal='on',
            sign={'anatomical_diagnosis': '1. Hypertensive heart disease with cardiac failure\n2. Pulmonary oedema and pleural effusions', 'cause_a': 'Congestive heart failure',
                  'cause_b': 'Hypertensive heart disease', 'goldman': 'V', 'correlation_notes': 'Clinical and autopsy diagnoses agree.',
                  'learning_points': 'Uncontrolled hypertension leads to heart failure; adherence support matters'})
    d = release(d, nurse, 72, 'Isatou Gaye', 'daughter', 'Passport GM-554120')
    review(d, doc, 12, summary='Elderly man with long-standing hypertension, diabetes and kidney disease admitted in heart failure; died on day 4.',
           attendees='Consultant, 2 medical officers, ICU nurse', preventability='not', factors=['patient'],
           went_well='Early, clear goals-of-care discussion with the family.', lessons='Blood pressure uncontrolled for years before admission')
    told.append('Omar Gaye · heart failure, concordant autopsy, study case waiting for review')

    # 7. Family declined teaching use: no study case
    p = patient('Aminata', 'Saidy', 'F', 38, contact='Ousman Saidy (brother)')
    t0 = ago(days=33)
    e = visit(p, t0, doc, nurse, opd, 'Headache for 2 weeks and confusion', symptoms='Severe headache, vomiting, now confused. Stopped her HIV treatment last year.',
              vitals={'temperature_c': '38.4', 'heart_rate': '102', 'bp': '118/72'}, assessment='Neck stiffness, GCS 13. Opening pressure raised.',
              diagnosis='Cryptococcal meningitis, advanced HIV disease', plan='Amphotericin B with fluconazole, therapeutic lumbar punctures.')
    admit(e, t0 + timedelta(hours=2))
    labs(e, t0 + timedelta(hours=2), doc, {'HIV': {'HIV': 'Reactive'}, 'CSF': {'CGLU': 1.2, 'CPRO': 1.4, 'CWBC': 18, 'GRAM': 'Encapsulated yeasts seen'}})
    rx(e, t0 + timedelta(hours=3), doc, [(amphotericin, '60 mg', 'iv', 'OD', 14, 14)])
    d = die(p, t0 + timedelta(days=6), nurse, place='ward', resuscitation='none')
    d = informed(d, nurse, after_hours=2, how='in_person', consent='declined', nok_name='Ousman Saidy', nok_relation='brother',
                 notes='Family asked that her illness stays private. Teaching use declined.')
    d = certify(d, doc, 8, cause_a='Cryptococcal meningitis', interval_a='3 weeks', cause_b='HIV disease', interval_b='Years', icd_underlying='B20.5', manner='natural', maternal='no')
    d = release(d, nurse, 20, 'Ousman Saidy', 'brother', 'National ID 0420-7781')
    review(d, doc, 20, final=False, summary='Woman with advanced HIV who had stopped treatment; cryptococcal meningitis; died on day 6.',
           preventability='possibly', delays=['seeking'], factors=['late_presentation', 'patient'])
    told.append('Aminata Saidy · family declined teaching use, review still a draft')

    # 8. Unclaimed body, 16 days in the mortuary, police informed
    p = patient('Alieu', 'Mbye', 'M', 60)
    d = die(p, ago(days=16, hours=10), er, place='community', time_estimated='on', place_detail='Found at a market stall, brought by police',
            circumstances='Found unresponsive at dawn by traders. Police brought him in. No identity documents; name from a trader who knew him.')
    d = certify(d, er, 20, cause_a='Ischaemic heart disease (probable)', manner='pending', legal_referral='Police, Serrekunda station · ref SK/3381/26')
    d = mortuary(d, nurse, 'M-07', after_hours=1)
    told.append('Alieu Mbye · unclaimed 16 days, police informed, family not found')

    # 9. Road traffic death; medico-legal autopsy scheduled for tomorrow morning
    p = patient('Yusupha', 'Ndow', 'M', 24, phone='+220 744 9031', contact='Mariama Ndow (mother) +220 744 9030')
    e = visit(p, ago(hours=21), er, nurse, emerg, 'Motorcycle collision', symptoms='Rider hit by a minibus. Helmet not worn.',
              vitals={'bp': '72/38', 'heart_rate': '150', 'spo2': '88', 'resp_rate': '34'}, assessment='Distended tender abdomen, left lower rib fractures. FAST positive.',
              diagnosis='Blunt abdominal trauma, haemoperitoneum, suspected splenic rupture', plan='Resuscitate, emergency laparotomy.')
    labs(e, ago(hours=21), er, {'CBC': {'HB': 6.2, 'WBC': 18.0, 'PLT': 180, 'RBC': 2.2, 'HCT': 19, 'MCV': 86}})
    d = die(p, ago(hours=19, minutes=30), er, place='emergency', resuscitation='attempted',
            circumstances='Arrested in the resuscitation bay before theatre was ready. 20 minutes of CPR with massive transfusion.')
    d = informed(d, er, after_hours=1, how='in_person', nok_name='Mariama Ndow', nok_relation='mother', nok_phone='+220 744 9030')
    d = certify(d, er, 3, cause_a='Haemorrhagic shock', interval_a='2 hours', cause_b='Ruptured spleen', interval_b='2 hours',
                cause_c='Blunt abdominal trauma (motorcycle collision)', interval_c='2 hours', manner='accident',
                legal_referral='Police traffic unit, Kanifing · ref KTU/1197/26', icd_underlying='V29.4')
    d = mortuary(d, nurse, 'M-02', after_hours=2)
    a = MT.request_autopsy(d, er, {'kind': 'medicolegal', 'questions': 'Document injuries for the police inquiry. Alcohol and drugs?',
                                   'legal_authority': 'Magistrate, Kanifing · order KM/26/412'})
    MT.autopsy_action(a, lab, 'schedule', {'pathologist': str(lab.pk), 'scheduled_at': local((NOW + timedelta(days=1)).replace(hour=9, minute=0))})
    told.append('Yusupha Ndow · road traffic death, medico-legal autopsy scheduled')

    # 10. Recorded in error, then undone by an administrator
    p = patient('Ndey', 'Fofana', 'F', 51, phone='+220 300 4121', conditions=[('Hypertension', 'active')])
    visit(p, ago(days=1, hours=5), doc, nurse, opd, 'Blood pressure review', vitals={'bp': '150/94'}, diagnosis='Hypertension', status='completed')
    d = die(p, ago(days=1, hours=4), nurse, place='ward')
    MT.revoke(d, s['admin'], 'Wrong patient selected: the death was recorded on the chart of a woman in the next bed. Corrected the same hour.')
    told.append('Ndey Fofana · death recorded in error and undone (patient is active again)')

    # 11. A year of history for the statistics, trends and the clinicopathological chart
    names = [('Momodou', 'Darboe', 'M'), ('Fatou', 'Drammeh', 'F'), ('Bakary', 'Sowe', 'M'), ('Isatou', 'Njie', 'F'), ('Ousman', 'Sarr', 'M'),
             ('Jainaba', 'Manneh', 'F'), ('Sulayman', 'Faye', 'M'), ('Oumie', 'Touray', 'F'), ('Lamin', 'Cham', 'M'), ('Mariama', 'Jobe', 'F'),
             ('Alhagie', 'Kah', 'M'), ('Neneh', 'Badjie', 'F'), ('Modou', 'Secka', 'M'), ('Kaddy', 'Colley', 'F')]
    stories = [  # (age, kind, presenting complaint, chain a..c, icd, place, days in hospital, autopsy goldman or None, cause found)
        (62, 'general', 'Fever and cough', ['Septic shock', 'Lobar pneumonia'], 'J18.1', 'ward', 3, None, None),
        (3, 'pediatric', 'Fever and convulsions', ['Cerebral malaria', 'Plasmodium falciparum infection'], 'B50.0', 'ward', 2, 'V', None),
        (58, 'general', 'Weight loss and cough for 3 months', ['Respiratory failure', 'Pulmonary tuberculosis'], 'A15.0', 'ward', 9, 'V', None),
        (0, 'pediatric', 'Newborn not feeding, fever', ['Neonatal sepsis'], 'P36.9', 'ward', 2, None, None),
        (71, 'general', 'Sudden collapse', ['Haemorrhagic stroke', 'Hypertension'], 'I61.9', 'ward', 1, 'III', None),
        (33, 'general', 'Abdominal pain and fever for 2 weeks', ['Generalised peritonitis', 'Typhoid perforation of the ileum'], 'A01.0', 'theatre', 4, 'V', None),
        (49, 'icu', 'Vomiting and confusion', ['Diabetic ketoacidosis', 'Type 1 diabetes mellitus'], 'E10.1', 'icu', 2, 'II', 'Acute pancreatitis'),
        (21, 'general', 'Severe bone pain', ['Acute chest syndrome', 'Sickle cell crisis'], 'D57.0', 'ward', 3, 'V', None),
        (1, 'pediatric', 'Diarrhoea and vomiting', ['Hypovolaemic shock', 'Acute gastroenteritis with severe dehydration'], 'A09', 'emergency', 0, None, None),
        (66, 'general', 'Chest pain', ['Cardiogenic shock', 'Acute myocardial infarction'], 'I21.9', 'emergency', 0, 'IV', None),
        (27, 'maternity', 'Headache and fits in late pregnancy', ['Eclampsia'], 'O15.0', 'maternity', 1, None, None),
        (55, 'general', 'Yellow eyes and swollen belly', ['Hepatic encephalopathy', 'Liver cirrhosis', 'Chronic hepatitis B'], 'K72.9', 'ward', 6, 'V', None),
        (5, 'pediatric', 'Pale and breathless', ['Heart failure', 'Severe anaemia', 'Plasmodium falciparum infection'], 'D64.9', 'ward', 1, 'V', None),
        (69, 'general', 'Difficulty breathing', ['Septic shock', 'Urinary tract infection'], 'A41.9', 'ward', 5, 'II', 'Infective endocarditis'),
    ]
    published_extra = {2, 6, 10}
    for i, ((first, last, sex), (age, kind, complaint, chain, icd, place, stay, goldman, missed)) in enumerate(zip(names, stories)):
        died = ago(days=40 + i * 23, hours=random.randint(0, 20))
        arrive = died - timedelta(days=stay, hours=random.randint(2, 10))
        p = patient(first, last, sex, age, days=random.randint(2, 6) if age == 0 else random.randint(5, 300), at=died - timedelta(days=stay + 1))
        e = visit(p, arrive, random.choice([doc, er]), nurse, emerg if place == 'emergency' else (peds if kind == 'pediatric' else (mat if kind == 'maternity' else opd)),
                  complaint, diagnosis=chain[-1], vitals={'heart_rate': str(random.randint(96, 140)), 'bp': random.choice(['90/60', '100/64', '86/50', '160/100'])})
        if place not in ('emergency', 'dead_on_arrival'):
            admit(e, arrive + timedelta(hours=1), kind=kind)
        d = die(p, died, nurse, place=place, resuscitation=random.choice(['attempted', 'dnacpr', 'none']))
        maternal = 'within_42d' if kind == 'maternity' else ('no' if sex == 'F' and 10 <= age <= 54 else '')
        lines = {f'cause_{k}': c for k, c in zip('abc', chain)}
        d = informed(d, nurse, after_hours=1, how='in_person', consent='granted' if i in published_extra else 'policy', nok_name=f'{random.choice(["Ebrima", "Awa", "Saikou", "Haddy"])} {last}', nok_relation=random.choice(['son', 'daughter', 'husband', 'wife', 'mother', 'brother']))
        d = certify(d, random.choice([doc, er]), random.randint(3, 14), icd_underlying=icd, manner='natural', maternal=maternal, **lines)
        d = mortuary(d, nurse, f'M-{8 + i % 4:02d}')
        if goldman:
            found = [missed] + chain if missed else chain
            autopsy(d, d.certified_by, lab, 'clinical', f'Confirm {chain[-1].lower()} as the cause of death.',
                    consent={'consent_name': d.nok_name, 'consent_relation': d.nok_relation},
                    sign={'anatomical_diagnosis': '\n'.join(f'{n + 1}. {c}' for n, c in enumerate(found)),
                          **{f'cause_{k}': c for k, c in zip('abcd', found)}, 'goldman': goldman,
                          'correlation_notes': f'Not diagnosed in life: {missed.lower()}.' if missed else 'Autopsy confirms the clinical diagnosis.'})
        d = release(DeathRecord.objects.get(pk=d.pk), nurse, random.randint(6, 40), d.nok_name, d.nok_relation, f'National ID {random.randint(1000, 9999)}-{random.randint(1000, 9999)}')
        if i % 3 != 2:
            review(d, random.choice([doc, mgr]), 14, summary=f'{complaint}; died after {stay} day(s).', preventability=random.choice(['not', 'not', 'possibly', 'probably']),
                   delays=random.sample(['seeking', 'reaching', 'receiving'], k=random.randint(0, 2)),
                   factors=random.sample(['late_presentation', 'staffing', 'medicine', 'lab', 'oxygen', 'referral', 'monitoring'], k=2),
                   lessons='Discussed at the monthly M&M meeting')
        if i in published_extra:
            publish(d, doc, 'Recognise the danger signs early\nEscalate deterioration without delay')
        else:
            StudyCase.objects.filter(death=d, status='draft').delete()   # demo: only a few historical cases go to the library
    return told
