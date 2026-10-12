from django.contrib import admin
from .models import Specimen, SpecimenEvent, Analyzer, ReagentLot, QualityControl, CriticalCommunication, LabIncident
@admin.register(Specimen)
class SpecimenAdmin(admin.ModelAdmin):
    list_display=('accession','request','sample_type','status','created_at')
    search_fields=('accession','request__encounter__patient__mrn')
    list_filter=('status','sample_type')
    readonly_fields=('accession',)
@admin.register(SpecimenEvent)
class EventAdmin(admin.ModelAdmin):
    list_display=('specimen','action','actor','at')
    readonly_fields=('specimen','action','from_status','to_status','actor','note','at')
    def has_add_permission(self,request):return False
    def has_change_permission(self,request,obj=None):return False
for model in (Analyzer,ReagentLot,QualityControl,CriticalCommunication,LabIncident):admin.site.register(model)
