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


class SlotInline(admin.TabularInline):
    model = models.SpecialistSlot
    extra = 3
    fields = ('start', 'minutes', 'mode')


@admin.register(models.Specialist)
class SpecialistAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'speciality', 'facility', 'rating', 'reviews', 'active')
    list_filter = ('facility', 'speciality', 'active')
    search_fields = ('name', 'speciality')
    inlines = [SlotInline]


@admin.register(models.NetworkFacility)
class NetworkFacilityAdmin(admin.ModelAdmin):
    list_display = ('name', 'kind', 'location', 'phone', 'accepts_referrals')
    list_filter = ('kind', 'accepts_referrals')


@admin.register(models.ReferralTask)
class ReferralTaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'referral', 'assigned_to_side', 'kind', 'status', 'due')
    list_filter = ('status', 'assigned_to_side', 'kind')


@admin.register(models.Tariff)
class TariffAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'category', 'amount', 'active')
    list_editable = ('amount', 'active')
    list_filter = ('category', 'active')


class InvoiceLineInline(admin.TabularInline):
    model = models.InvoiceLine
    extra = 0


class PaymentInline(admin.TabularInline):
    model = models.Payment
    extra = 0
    readonly_fields = ('amount', 'method', 'reference', 'received_by', 'received_at', 'voided', 'void_reason')
    can_delete = False
    def has_add_permission(self, request, obj=None): return False


@admin.register(models.Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('patient__first_name', 'patient__last_name', 'patient__mrn')
    inlines = [InvoiceLineInline, PaymentInline]


@admin.register(models.ReferenceRange)
class ReferenceRangeAdmin(admin.ModelAdmin):
    list_display = ('code', 'label', 'source_name', 'kind', 'sex', 'age_min_months', 'age_max_months', 'condition', 'low', 'high', 'unit', 'status')
    list_filter = ('source', 'kind', 'status', 'condition')
    search_fields = ('code', 'label', 'citation_title')
    readonly_fields = ('seed_key', 'source_hash', 'source_checked_at', 'verified_by', 'verified_at')


@admin.register(models.ParameterGuidance)
class ParameterGuidanceAdmin(admin.ModelAdmin):
    list_display = ('code', 'direction', 'title', 'active', 'approved_by', 'updated_at')
    list_filter = ('direction', 'active')
    search_fields = ('code', 'title', 'steps')

    def save_model(self, request, obj, form, change):
        obj.approved_by = obj.approved_by or request.user
        super().save_model(request, obj, form, change)


@admin.register(models.EvidenceItem)
class EvidenceItemAdmin(admin.ModelAdmin):
    list_display = ('key', 'source', 'kind', 'title', 'fetched_at')
    list_filter = ('source',)
    search_fields = ('key', 'title', 'url')


@admin.register(models.EvidenceFetch)
class EvidenceFetchAdmin(admin.ModelAdmin):
    list_display = ('key', 'name', 'status', 'items', 'last_run_at', 'error')
    list_filter = ('status',)


@admin.register(models.AISuggestion)
class AISuggestionAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'lab_request', 'requested_by', 'status', 'provider', 'model_name', 'helpful')
    list_filter = ('status', 'provider', 'helpful')
    readonly_fields = [f.name for f in models.AISuggestion._meta.fields if f.name != 'id']
    has_add_permission = lambda self, request: False
    has_change_permission = lambda self, request, obj=None: False


@admin.register(models.ImagingAIRun)
class ImagingAIRunAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'order', 'image', 'kind', 'requested_by', 'status', 'provider', 'model_name', 'helpful')
    list_filter = ('kind', 'status', 'provider', 'helpful')
    readonly_fields = [f.name for f in models.ImagingAIRun._meta.fields if f.name != 'id']
    has_add_permission = lambda self, request: False
    has_change_permission = lambda self, request, obj=None: False


@admin.register(models.BedSummary)
class BedSummaryAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'admission', 'requested_by', 'status', 'model_name', 'helpful')
    list_filter = ('status', 'helpful')
    readonly_fields = [f.name for f in models.BedSummary._meta.fields if f.name != 'id']
    has_add_permission = lambda self, request: False
    has_change_permission = lambda self, request, obj=None: False


@admin.register(models.LabInsightAsk)
class LabInsightAskAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'patient', 'kind', 'requested_by', 'status', 'model_name', 'helpful')
    list_filter = ('kind', 'status', 'helpful')
    readonly_fields = [f.name for f in models.LabInsightAsk._meta.fields if f.name != 'id']
    has_add_permission = lambda self, request: False
    has_change_permission = lambda self, request, obj=None: False


@admin.register(models.DoctorReport)
class DoctorReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'encounter', 'lab_request', 'status', 'signed_by', 'signed_at', 'created_at')
    list_filter = ('status',)
    readonly_fields = [f.name for f in models.DoctorReport._meta.fields if f.name != 'id']
    has_add_permission = lambda self, request: False
    has_change_permission = lambda self, request, obj=None: False
