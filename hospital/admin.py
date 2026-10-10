from django.contrib import admin
from . import models
for name in ('Department','StaffProfile','Patient','Allergy','Condition','Encounter','QueueTicket','Attendance','Medication','StockBatch','Dispense','Ward','Bed','Admission','Referral','FormDefinition','FormSubmission','WorkflowDefinition','WorkflowRun','WorkflowAction','Signature','AuditEvent'):
    model=getattr(models,name)
    cls=type(f'{name}Admin',(admin.ModelAdmin,),{'list_per_page':35})
    if name in ('Signature','AuditEvent','Dispense','WorkflowAction'):
        cls.readonly_fields=[f.name for f in model._meta.fields if f.name!='id']
        cls.has_add_permission=lambda self,request:False
        cls.has_change_permission=lambda self,request,obj=None:False
        cls.has_delete_permission=lambda self,request,obj=None:False
    admin.site.register(model,cls)


class LabParameterInline(admin.TabularInline):
    model = models.LabParameter
    extra = 1
    fields = ('sort_order', 'code', 'name', 'kind', 'unit', 'decimals', 'ref_low', 'ref_high', 'female_ref_low', 'female_ref_high',
              'critical_low', 'critical_high', 'choices', 'abnormal_choices', 'body_system')


@admin.register(models.LabCategory)
class LabCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'color', 'sort_order')
    list_editable = ('sort_order',)
    prepopulated_fields = {'code': ('name',)}


@admin.register(models.LabTest)
class LabTestAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'category', 'body_system', 'sample_type', 'turnaround_hours', 'active')
    list_filter = ('category', 'body_system', 'active')
    search_fields = ('name', 'code', 'parameters__name')
    inlines = [LabParameterInline]


class LabResultValueInline(admin.TabularInline):
    model = models.LabResultValue
    extra = 0
    readonly_fields = ('parameter', 'value_number', 'value_text', 'flag', 'entered_by', 'acknowledged_by', 'acknowledged_at')
    can_delete = False


@admin.register(models.LabOrder)
class LabOrderAdmin(admin.ModelAdmin):
    list_display = ('test', 'encounter', 'status', 'abnormal', 'performed_by', 'created_at')
    list_filter = ('status', 'abnormal', 'test__category')
    inlines = [LabResultValueInline]


class PrescriptionItemInline(admin.TabularInline):
    model = models.PrescriptionItem
    extra = 0
    fields = ('sort_order', 'medication', 'dose', 'units_per_dose', 'route', 'frequency', 'duration_days', 'quantity', 'instructions')


@admin.register(models.Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'encounter', 'state', 'signed_by', 'created_at')
    list_filter = ('state',)
    inlines = [PrescriptionItemInline]


class LabOrderInline(admin.TabularInline):
    model = models.LabOrder
    extra = 0
    fields = ('test', 'status', 'abnormal', 'performed_by', 'verified_by')
    readonly_fields = ('abnormal', 'performed_by', 'verified_by')


@admin.register(models.LabRequest)
class LabRequestAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'priority', 'specimen_id', 'requested_by', 'created_at')
    list_filter = ('priority',)
    inlines = [LabOrderInline]
