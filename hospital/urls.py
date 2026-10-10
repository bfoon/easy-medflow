from django.urls import path
from . import views as v

urlpatterns = [
    path('', v.dashboard, name='dashboard'),
    path('api/pulse/', v.api_pulse, name='api_pulse'),
    path('api/search/', v.api_search, name='api_search'),
    path('api/queue/', v.api_queue, name='api_queue'),
    path('api/rx-check/', v.api_rx_check, name='api_rx_check'),

    path('patients/', v.patients, name='patients'),
    path('patients/new/', v.patient_new, name='patient_new'),
    path('patients/<int:pk>/', v.patient_chart, name='patient_chart'),
    path('patients/<int:pk>/allergies/new/', v.allergy_new, name='allergy_new'),
    path('patients/<int:pk>/conditions/new/', v.condition_new, name='condition_new'),

    path('encounters/new/', v.encounter_new, name='encounter_new'),
    path('encounters/<int:pk>/', v.encounter_detail, name='encounter_detail'),
    path('encounters/<int:pk>/complete/', v.encounter_complete, name='encounter_complete'),

    path('queue/', v.queue, name='queue'),
    path('queue/display/', v.queue_display, name='queue_display'),
    path('queue/new/', v.ticket_new, name='ticket_new'),
    path('queue/<int:pk>/<str:state>/', v.ticket_transition, name='ticket_transition'),

    path('referrals/', v.referrals, name='referrals'),
    path('referrals/new/', v.referral_new, name='referral_new'),
    path('referrals/<int:pk>/<str:state>/', v.referral_transition, name='referral_transition'),

    path('labs/', v.labs, name='labs'),
    path('labs/new/', v.lab_new, name='lab_new'),
    path('labs/mine/', v.lab_mine, name='lab_mine'),
    path('labs/catalog/', v.lab_catalog, name='lab_catalog'),
    path('labs/view/', v.set_lab_view, name='set_lab_view'),
    path('labs/values/<int:pk>/ack/', v.lab_ack, name='lab_ack'),
    path('labs/requests/<int:pk>/results/', v.lab_results_entry, name='lab_results_entry'),
    path('labs/requests/<int:pk>/<str:step>/', v.lab_request_action, name='lab_request_action'),
    path('labs/tests/<int:pk>/cancel/', v.lab_order_cancel, name='lab_order_cancel'),
    path('patients/<int:pk>/labs/', v.patient_labs, name='patient_labs'),

    path('pharmacy/', v.pharmacy, name='pharmacy'),
    path('prescriptions/new/', v.prescription_new, name='prescription_new'),
    path('prescriptions/<int:pk>/sign/', v.prescription_sign, name='prescription_sign'),
    path('prescriptions/<int:pk>/dispense/', v.prescription_dispense, name='prescription_dispense'),

    path('beds/', v.beds, name='beds'),
    path('beds/<int:pk>/ready/', v.bed_ready, name='bed_ready'),
    path('admissions/new/', v.admission_new, name='admission_new'),
    path('admissions/<int:pk>/discharge/', v.admission_discharge, name='admission_discharge'),

    path('attendance/', v.attendance, name='attendance'),

    path('studio/', v.studio, name='studio'),
    path('studio/forms/new/', v.form_definition_new, name='form_definition_new'),
    path('studio/workflows/new/', v.workflow_definition_new, name='workflow_definition_new'),
    path('studio/fill/', v.fill_form_pick, name='fill_form_pick'),
    path('studio/forms/<int:pk>/fill/<int:patient_id>/', v.fill_form, name='fill_form'),
    path('studio/submissions/<int:pk>/sign/', v.submission_sign, name='submission_sign'),
    path('studio/runs/<int:pk>/<str:action>/', v.workflow_act, name='workflow_act'),
]
