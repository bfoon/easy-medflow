from django.urls import path
from . import views as v
urlpatterns=[
 path('',v.dashboard,name='dashboard'),
 path('patients/',v.patient_list,name='patients'),path('patients/new/',v.patient_add,name='patient_add'),path('patients/<int:pk>/',v.patient_detail,name='patient_detail'),
 path('patients/<int:pk>/allergies/new/',v.allergy_add,name='allergy_add'),path('patients/<int:pk>/problems/new/',v.problem_add,name='problem_add'),
 path('patients/<int:pk>/encounters/new/',v.encounter_add,name='encounter_add'),path('patients/<int:pk>/ticket/new/',v.ticket_add,name='ticket_add'),
 path('encounters/<int:pk>/',v.encounter_detail,name='encounter_detail'),path('encounters/<int:pk>/vitals/new/',v.vital_add,name='vital_add'),
 path('encounters/<int:pk>/prescriptions/new/',v.prescription_add,name='prescription_add'),path('prescriptions/<int:pk>/sign/',v.prescription_sign,name='prescription_sign'),
 path('encounters/<int:pk>/lab/new/',v.lab_add,name='lab_add'),path('encounters/<int:pk>/admit/',v.admission_add,name='admission_add'),
 path('queue/',v.queue,name='queue'),path('tickets/<int:pk>/status/',v.ticket_update,name='ticket_update'),
 path('pharmacy/',v.pharmacy,name='pharmacy'),path('pharmacy/<int:pk>/dispense/',v.dispense,name='dispense'),
 path('laboratory/',v.laboratory,name='laboratory'),path('laboratory/<int:pk>/result/',v.lab_result,name='lab_result'),
 path('beds/',v.beds,name='beds'),path('admissions/<int:pk>/discharge/',v.discharge_patient,name='discharge'),
 path('attendance/',v.attendance,name='attendance'),path('attendance/toggle/',v.attendance_toggle,name='attendance_toggle'),
 path('encounters/<int:pk>/ai/',v.ai_status,name='ai_status'),
]
