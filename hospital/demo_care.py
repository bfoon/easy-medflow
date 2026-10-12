"""Fictional demo content for the bedside scene, injury & burns assessments, form templates and flows."""
from datetime import date, timedelta

from django.utils import timezone

from . import bedside as B
from . import flows
from . import formkit as F
from . import injury as I


def run(doctor, nurse):
    from .models import (Admission, Bed, BedsideObservation, BedsideState, Department, Encounter, FormDefinition, FormSubmission,
                         FormVersion, InjuryAssessment, Patient, WorkflowDefinition)
    if FormDefinition.objects.filter(slug='burns-assessment').exists():
        return 0
    now = timezone.now()
    made = 0

    # ---- a burns patient in the ICU
    p = Patient.objects.create(first_name='Lamin', last_name='Ceesay', dob=date(1994, 3, 2), sex='M', phone='7712345',
                               medical_alerts='Burns: fluid balance chart', blood_group='O+')
    em = Department.objects.filter(name='Emergency').first() or Department.objects.first()
    e = Encounter.objects.create(patient=p, department=em, clinician=doctor, reason='Burns from a gas cylinder fire',
                                 diagnosis='Flame burns to chest, abdomen and left arm with possible inhalation injury',
                                 vitals={'bp': '102/64', 'heart_rate': '118', 'temperature_c': '37.9', 'spo2': '93', 'resp_rate': '24', 'weight_kg': '72'})
    bed = Bed.objects.filter(state='available', kind='icu').first() or Bed.objects.filter(state='available').first()
    if bed:
        adm = Admission.objects.create(encounter=e, bed=bed)
        Admission.objects.filter(pk=adm.pk).update(admitted_at=now - timedelta(hours=3))
        bed.state = 'occupied'; bed.save(update_fields=['state'])
        burn_time = timezone.localtime(now - timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M')
        data = I.clean_assessment({'burn': {'cause': 'flame', 'time': burn_time, 'inhalation': True, 'given_ml': 900},
                                   'burns': [{'region': 'chest', 'depth': 'deep_partial', 'pct': 85}, {'region': 'abdomen', 'depth': 'superficial_partial', 'pct': 70},
                                             {'region': 'upper_back', 'depth': 'superficial_partial', 'pct': 60},
                                             {'region': 'upper_arm', 'side': 'left', 'view': 'front', 'depth': 'deep_partial', 'pct': 100, 'circumferential': True},
                                             {'region': 'forearm', 'side': 'left', 'view': 'front', 'depth': 'full', 'pct': 60},
                                             {'region': 'forearm', 'side': 'left', 'view': 'back', 'depth': 'superficial_partial', 'pct': 50},
                                             {'region': 'head', 'view': 'front', 'depth': 'superficial', 'pct': 40}]})
        vitals = {'heart_rate': 118, 'systolic': 102, 'diastolic': 64, 'resp_rate': 24, 'spo2': 93, 'temperature_c': 37.9, 'consciousness': 'A', 'on_oxygen': True}
        c = I.compute(data, age=p.age, weight_kg=72, vitals=vitals)
        InjuryAssessment.objects.create(encounter=e, patient=p, data=data, computed=c, weight_kg=72, assessed_by=doctor)
        rate = (c['fluids'] or {}).get('catch_up_ml_h') or (c['fluids'] or {}).get('rate_first_ml_h') or 300
        BedsideState.objects.create(admission=adm, updated_by=nurse, devices=B.clean_devices({
            'iv': {'on': True, 'fluid': 'ringers', 'bag_ml': 1000, 'remaining_ml': 720, 'rate_ml_h': rate, 'drop_factor': 20, 'site': 'hand_r', 'pump': True},
            'oxygen': {'on': True, 'device': 'nrb', 'flow_l_min': 15}, 'catheter': {'on': True, 'bag_ml': 180, 'output_ml_h': 30},
            'monitor': {'on': True}, 'pulse_ox': {'on': True}, 'bp_cuff': {'on': True, 'interval_min': 15}, 'bed': {'head_deg': 30, 'rails': True}}))
        BedsideObservation.objects.create(admission=adm, recorded_by=nurse, news2=B.news2(vitals)['total'], **vitals)
        made += 1

    # ---- the spinal cord injury case from the bone demo, and everyone else in a bed
    for adm in Admission.objects.filter(discharged_at__isnull=True).select_related('encounter__patient'):
        enc, pt = adm.encounter, adm.encounter.patient
        if 'spinal cord injury' in (enc.diagnosis or '').lower() and not InjuryAssessment.objects.filter(encounter=enc).exists():
            data = I.clean_assessment({'spine': {'level': 'T10', 'asia': 'A', 'type': 'fracture', 'immobilised': True},
                                       'injuries': [{'type': 'abrasion', 'region': 'forearm', 'side': 'right', 'view': 'back', 'severity': 'minor'},
                                                    {'type': 'contusion', 'region': 'lower_back', 'view': 'back', 'severity': 'moderate'}]})
            InjuryAssessment.objects.create(encounter=enc, patient=pt, data=data, computed=I.compute(data, age=pt.age, weight_kg=68), weight_kg=68, assessed_by=doctor)
            dev = {'iv': {'on': True, 'fluid': 'saline', 'bag_ml': 1000, 'remaining_ml': 450, 'rate_ml_h': 83, 'drop_factor': 20, 'site': 'forearm_l'},
                   'catheter': {'on': True, 'bag_ml': 640, 'output_ml_h': 55}, 'bed': {'head_deg': 0, 'rails': True}}
            obs = {'heart_rate': 64, 'systolic': 108, 'diastolic': 66, 'resp_rate': 16, 'spo2': 97, 'temperature_c': 36.9}
        elif hasattr(adm, 'bedside') and BedsideState.objects.filter(admission=adm).exists():
            continue
        else:
            dx = (enc.diagnosis or '').lower()
            sick = any(k in dx for k in ('malaria', 'sepsis', 'crisis', 'eclampsia'))
            dev = {'iv': {'on': True, 'fluid': 'dextrose_saline' if 'malaria' in dx else 'saline', 'bag_ml': 500 if 'eclampsia' in dx else 1000,
                          'remaining_ml': 300 + (adm.pk * 97) % 600, 'rate_ml_h': 125 if sick else 80, 'drop_factor': 20,
                          'pump': 'eclampsia' in dx, 'site': 'hand_l'},
                   'oxygen': {'on': 'crisis' in dx, 'device': 'nasal', 'flow_l_min': 2},
                   'catheter': {'on': 'eclampsia' in dx, 'bag_ml': 260, 'output_ml_h': 35}, 'bed': {'head_deg': 30}}
            obs = {'heart_rate': 108 if sick else 84, 'systolic': 118 if 'eclampsia' not in dx else 162, 'diastolic': 74 if 'eclampsia' not in dx else 104,
                   'resp_rate': 22 if sick else 16, 'spo2': 95 if 'crisis' in dx else 98, 'temperature_c': 38.8 if 'malaria' in dx else 37.0}
        dev.update({'monitor': {'on': True}, 'pulse_ox': {'on': True}, 'bp_cuff': {'on': True}})
        BedsideState.objects.update_or_create(admission=adm, defaults={'devices': B.clean_devices(dev), 'updated_by': nurse})
        o = B.clean_observation(obs); o['on_oxygen'] = dev.get('oxygen', {}).get('on', False)
        BedsideObservation.objects.create(admission=adm, recorded_by=nurse, news2=B.news2(o)['total'], **o)
        made += 1

    # ---- form templates and two flows
    from .studio_views import TEMPLATES
    forms = {}
    for key, slug in (('consent', 'surgical-consent'), ('burns', 'burns-assessment'), ('falls', 'falls-risk'), ('admission', 'nursing-admission')):
        schema, errs = F.clean_schema(TEMPLATES[key]['schema'])
        f = FormDefinition.objects.create(name=TEMPLATES[key]['name'], slug=slug, schema=schema, published=True)
        FormVersion.objects.create(definition=f, version=1, schema=schema, published_by=doctor)
        forms[key] = f
    g, errs = flows.clean_graph({'nodes': [
        {'id': 'start', 'type': 'start', 'label': 'Start', 'x': 40, 'y': 140},
        {'id': 'blood', 'type': 'condition', 'label': 'Transfusion possible?', 'x': 250, 'y': 140, 'config': {'rules': {'all': [{'field': 'blood', 'op': 'eq', 'value': 'yes'}]}}},
        {'id': 'lab', 'type': 'notify', 'label': 'Tell the blood bank', 'x': 480, 'y': 30, 'config': {'assign': {'mode': 'role', 'role': 'lab'}, 'message': 'Group and save needed before surgery'}},
        {'id': 'surgeon', 'type': 'approval', 'label': 'Surgeon approves', 'x': 710, 'y': 140, 'config': {'assign': {'mode': 'role', 'role': 'doctor'}, 'mode': 'any', 'due_hours': 12, 'escalate_role': 'management', 'allow_return': True}},
        {'id': 'sign', 'type': 'signature', 'label': 'Patient signs, nurse witnesses', 'x': 940, 'y': 140, 'config': {'signers': [{'source': 'patient', 'as': 'in_person', 'order': 1}, {'source': 'initiator', 'as': 'witness', 'order': 1}], 'require_full_read': True}},
        {'id': 'done', 'type': 'end', 'label': 'Consent complete', 'x': 1170, 'y': 140, 'config': {'outcome': 'completed'}}],
        'edges': [{'from': 'start', 'to': 'blood'}, {'from': 'blood', 'port': 'yes', 'to': 'lab'}, {'from': 'blood', 'port': 'no', 'to': 'surgeon'},
                  {'from': 'lab', 'to': 'surgeon'}, {'from': 'surgeon', 'port': 'approved', 'to': 'sign'}, {'from': 'sign', 'port': 'signed', 'to': 'done'}]}, forms['consent'].schema)
    consent_flow = WorkflowDefinition.objects.create(name='Surgical consent sign-off', graph=g, form=forms['consent'],
                                                     description='Surgeon approval, then the patient signs in person with a nurse as witness')
    g2, _ = flows.clean_graph({'nodes': [
        {'id': 'start', 'type': 'start', 'label': 'Start', 'x': 40, 'y': 120},
        {'id': 'risk', 'type': 'route', 'label': 'Falls risk', 'x': 280, 'y': 120, 'config': {'branches': [{'id': 'high', 'label': 'High (45+)', 'rules': {'all': [{'field': 'score', 'op': 'gte', 'value': '45'}]}}]}},
        {'id': 'review', 'type': 'review', 'label': 'Ward sister reviews the plan', 'x': 540, 'y': 40, 'config': {'assign': {'mode': 'role', 'role': 'nurse'}, 'due_hours': 4, 'escalate_role': 'doctor'}},
        {'id': 'end', 'type': 'end', 'label': 'Filed', 'x': 800, 'y': 120, 'config': {'outcome': 'completed'}}],
        'edges': [{'from': 'start', 'to': 'risk'}, {'from': 'risk', 'port': 'high', 'to': 'review'}, {'from': 'risk', 'port': 'otherwise', 'to': 'end'}, {'from': 'review', 'to': 'end'}]}, forms['falls'].schema)
    WorkflowDefinition.objects.create(name='Falls risk review', graph=g2, form=forms['falls'], description='High scores go to the ward sister within 4 hours')
    # one consent waiting for the surgeon
    pt = Patient.objects.exclude(pk=p.pk).order_by('pk').first()
    if pt:
        vals, errs, _ = F.evaluate_form(forms['consent'].schema, {'procedure': 'Open reduction and internal fixation, right tibia', 'side': 'Right', 'anaesthesia': 'General',
                                                                  'risks': ['Bleeding', 'Infection', 'Risk of anaesthesia'], 'blood': 'yes', 'blood_consent': 'yes', 'understood': True})
        s = FormSubmission.objects.create(definition=forms['consent'], patient=pt, encounter=pt.encounters.order_by('-created_at').first(),
                                          values=vals, schema_snapshot=forms['consent'].schema, submitted_by=nurse)
        flows.start_run(consent_flow, s, nurse)
    return made
