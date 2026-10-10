from django.contrib import admin
from . import models as m
@admin.register(m.Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display=('mrn','first_name','last_name','phone','created_at')
    search_fields=('mrn','first_name','last_name','phone')
    readonly_fields=('mrn',)
@admin.register(m.QueueTicket)
class QueueTicketAdmin(admin.ModelAdmin):
    list_display=('number','patient','department','priority','status','created_at')
    list_filter=('department','status','priority')
@admin.register(m.Encounter)
class EncounterAdmin(admin.ModelAdmin):
    list_display=('id','patient','department','clinician','status','created_at')
    list_filter=('status','department')
@admin.register(m.Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display=('id','encounter','medicine','status','quantity')
    readonly_fields=('signed_at',)
for model in [m.Department,m.StaffProfile,m.Allergy,m.Problem,m.VitalSign,m.Medicine,m.StockBatch,m.Dispense,m.LabTest,m.LabOrder,m.Bed,m.Admission,m.Attendance,m.AuditEvent,m.Invoice,m.AIReviewLog]:
    admin.site.register(model)
