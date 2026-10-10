from django import forms
from .models import Patient,Encounter,QueueTicket,Prescription,LabOrder,VitalSign,Allergy,Problem

class StyledModelForm(forms.ModelForm):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for field in self.fields.values():
            if isinstance(field.widget,forms.CheckboxInput):field.widget.attrs['class']='form-check-input'
            else: field.widget.attrs['class']='form-select' if isinstance(field.widget,forms.Select) else 'form-control'

class PatientForm(StyledModelForm):
    class Meta:
        model=Patient
        fields=['first_name','last_name','dob','sex','phone','address','emergency_contact','blood_type','medical_alert']
        widgets={'dob':forms.DateInput(attrs={'type':'date'})}

class EncounterForm(StyledModelForm):
    class Meta:
        model=Encounter
        fields=['department','chief_complaint','history','examination','assessment','plan','diagnosis']
        widgets={k:forms.Textarea(attrs={'rows':2}) for k in ['chief_complaint','history','examination','assessment','plan']}

class TicketForm(StyledModelForm):
    class Meta:
        model=QueueTicket
        fields=['department','priority']

class PrescriptionForm(StyledModelForm):
    class Meta:
        model=Prescription
        fields=['medicine','dose','frequency','duration','quantity','instructions']

class LabOrderForm(StyledModelForm):
    class Meta:
        model=LabOrder
        fields=['test']
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['test'].queryset=self.fields['test'].queryset.filter(available=True)

class VitalForm(StyledModelForm):
    class Meta:
        model=VitalSign
        fields=['temperature_c','pulse_bpm','systolic','diastolic','spo2','weight_kg']

class AllergyForm(StyledModelForm):
    class Meta:
        model=Allergy
        fields=['substance','reaction','severity','verified']

class ProblemForm(StyledModelForm):
    class Meta:
        model=Problem
        fields=['title','code','onset','active','notes']
        widgets={'onset':forms.DateInput(attrs={'type':'date'})}
