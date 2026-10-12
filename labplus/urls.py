from django.urls import path
from . import views
app_name='labplus'
urlpatterns=[
 path('',views.dashboard,name='dashboard'),
 path('requests/<int:request_id>/accession/',views.accession,name='accession'),
 path('specimens/<int:pk>/transition/',views.transition,name='transition'),
 path('specimens/<int:pk>/recollect/',views.recollect,name='recollect'),
 path('qc/record/',views.qc_run,name='qc_run'),
 path('critical/<int:pk>/call/',views.critical_call,name='critical_call'),
]
