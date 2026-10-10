from django import forms
from .models import *
class StyledModelForm(forms.ModelForm):
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw)
        for field in self.fields.values():
            field.widget.attrs['class']='form-select' if isinstance(field.widget,forms.Select) else 'form-control'

class PatientForm(StyledModelForm):
    class Meta:
        model=Patient
        fields=['first_name','last_name','dob','sex','phone','address','emergency_contact','blood_group','medical_alerts']
        widgets={'dob':forms.DateInput(attrs={'type':'date'})}
class EncounterForm(StyledModelForm):
    class Meta:
        model=Encounter
        fields=['patient','clinician','department','reason','symptoms','assessment','diagnosis','plan','vitals','status']
class TicketForm(StyledModelForm):
    class Meta:
        model=QueueTicket
        fields=['patient','encounter','department','priority']
    def clean(self):
        data=super().clean()
        if data.get('encounter') and data.get('patient') and data['encounter'].patient_id!=data['patient'].id:raise forms.ValidationError('Encounter must belong to the patient')
        return data
class ReferralForm(StyledModelForm):
    class Meta:
        model=Referral
        fields=['encounter','destination','speciality','reason','urgency','status','contact','transfer_notes','accepted_by']
class LabOrderForm(StyledModelForm):
    class Meta:
        model=LabOrder
        fields=['encounter','test','status','specimen_id','result','reference_range']
class PrescriptionForm(StyledModelForm):
    class Meta:
        model=Prescription
        fields=['encounter','medication','directions','quantity','allergy_reviewed','override_reason']
class FormDefinitionForm(StyledModelForm):
    class Meta:
        model=FormDefinition
        fields=['name','slug','schema','published']
class WorkflowDefinitionForm(StyledModelForm):
    class Meta:
        model=WorkflowDefinition
        fields=['name','steps','active']
class AdmissionForm(StyledModelForm):
    class Meta:
        model=Admission
        fields=['encounter','bed']
