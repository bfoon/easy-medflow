from django.urls import path
from . import views as v
urlpatterns=[
 path('',v.dashboard,name='dashboard'),
 path('patients/',v.patients,name='patients'),path('patients/new/',v.patient_new,name='patient_new'),path('patients/<int:pk>/',v.patient_chart,name='patient_chart'),
 path('encounters/new/',v.encounter_new,name='encounter_new'),
 path('queue/',v.queue,name='queue'),path('queue/new/',v.ticket_new,name='ticket_new'),path('queue/<int:pk>/<str:state>/',v.ticket_transition,name='ticket_transition'),
 path('referrals/',v.referrals,name='referrals'),path('referrals/new/',v.referral_new,name='referral_new'),
 path('labs/',v.labs,name='labs'),path('labs/new/',v.lab_new,name='lab_new'),
 path('pharmacy/',v.pharmacy,name='pharmacy'),path('prescriptions/new/',v.prescription_new,name='prescription_new'),path('prescriptions/<int:pk>/sign/',v.prescription_sign,name='prescription_sign'),path('prescriptions/<int:pk>/dispense/',v.prescription_dispense,name='prescription_dispense'),
 path('beds/',v.beds,name='beds'),path('admissions/new/',v.admission_new,name='admission_new'),path('admissions/<int:pk>/discharge/',v.admission_discharge,name='admission_discharge'),
 path('attendance/',v.attendance,name='attendance'),
 path('studio/',v.studio,name='studio'),path('studio/forms/new/',v.form_definition_new,name='form_definition_new'),path('studio/workflows/new/',v.workflow_definition_new,name='workflow_definition_new'),path('studio/forms/<int:pk>/fill/<int:patient_id>/',v.fill_form,name='fill_form'),
 path('studio/submissions/<int:pk>/sign/',v.submission_sign,name='submission_sign'),path('studio/runs/<int:pk>/<str:action>/',v.workflow_act,name='workflow_act'),
]
