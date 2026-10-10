from django.contrib import admin
from . import models
for name in ('Department','StaffProfile','Patient','Allergy','Condition','Encounter','QueueTicket','Attendance','LabTest','LabOrder','Medication','StockBatch','Prescription','Dispense','Ward','Bed','Admission','Referral','FormDefinition','FormSubmission','WorkflowDefinition','WorkflowRun','WorkflowAction','Signature','AuditEvent'):
    model=getattr(models,name)
    cls=type(f'{name}Admin',(admin.ModelAdmin,),{'list_per_page':35})
    if name in ('Signature','AuditEvent','Dispense','WorkflowAction'):
        cls.readonly_fields=[f.name for f in model._meta.fields if f.name!='id']
        cls.has_add_permission=lambda self,request:False
        cls.has_change_permission=lambda self,request,obj=None:False
        cls.has_delete_permission=lambda self,request,obj=None:False
    admin.site.register(model,cls)
