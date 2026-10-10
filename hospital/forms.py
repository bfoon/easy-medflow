from django import forms
from .models import (PrescriptionItem, Medication, Patient, Encounter, QueueTicket, Referral, LabOrder, Prescription,
                     FormDefinition, WorkflowDefinition, Admission, Allergy, Condition, Bed)


class StyledMixin:
    def _style(self):
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs['class'] = 'form-check-input'
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs['class'] = 'form-select'
            else:
                w.attrs['class'] = 'form-control'
            if isinstance(w, forms.Textarea):
                w.attrs.setdefault('rows', 3)


class StyledModelForm(StyledMixin, forms.ModelForm):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._style()


class PatientForm(StyledModelForm):
    class Meta:
        model = Patient
        fields = ['first_name', 'last_name', 'dob', 'sex', 'phone', 'address', 'emergency_contact', 'blood_group', 'medical_alerts']
        widgets = {'dob': forms.DateInput(attrs={'type': 'date'}), 'address': forms.Textarea(attrs={'rows': 2}),
                   'medical_alerts': forms.Textarea(attrs={'rows': 2})}
        labels = {'dob': 'Date of birth', 'blood_group': 'Blood group'}


VITAL_FIELDS = [
    ('bp', 'Blood pressure', 'mmHg', '120/80'),
    ('heart_rate', 'Heart rate', 'bpm', '72'),
    ('temperature_c', 'Temperature', '°C', '36.8'),
    ('spo2', 'SpO₂', '%', '98'),
    ('resp_rate', 'Respiratory rate', '/min', '16'),
    ('weight_kg', 'Weight', 'kg', '70'),
]


class EncounterForm(StyledModelForm):
    """Vitals are captured as discrete inputs and stored as a JSON object with units."""
    class Meta:
        model = Encounter
        fields = ['patient', 'clinician', 'department', 'reason', 'symptoms', 'assessment', 'diagnosis', 'plan', 'status']
        labels = {'reason': 'Reason for visit'}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        existing = (self.instance.vitals or {}) if self.instance and self.instance.pk else {}
        for key, label, unit, ph in VITAL_FIELDS:
            self.fields[f'v_{key}'] = forms.CharField(
                label=f'{label} ({unit})', required=False, max_length=20, initial=existing.get(key, ''),
                widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': ph, 'data-vital': key}))

    @property
    def vital_fields(self):
        return [self[f'v_{k}'] for k, *_ in VITAL_FIELDS]

    @property
    def core_fields(self):
        return [f for f in self if not f.name.startswith('v_')]

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.vitals = {k: self.cleaned_data[f'v_{k}'].strip() for k, *_ in VITAL_FIELDS if self.cleaned_data.get(f'v_{k}', '').strip()}
        if commit:
            obj.save()
        return obj


class TicketForm(StyledModelForm):
    class Meta:
        model = QueueTicket
        fields = ['patient', 'department', 'priority', 'counter', 'encounter']

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields['encounter'].queryset = Encounter.objects.filter(status='open').select_related('patient')

    def clean(self):
        data = super().clean()
        if data.get('encounter') and data.get('patient') and data['encounter'].patient_id != data['patient'].id:
            raise forms.ValidationError('That visit belongs to a different patient.')
        return data


class ReferralForm(StyledModelForm):
    class Meta:
        model = Referral
        fields = ['encounter', 'destination', 'speciality', 'reason', 'urgency', 'status', 'contact', 'transfer_notes', 'accepted_by']


class LabOrderForm(StyledModelForm):
    class Meta:
        model = LabOrder
        fields = ['encounter', 'test', 'specimen_id']

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields['encounter'].queryset = Encounter.objects.filter(status='open').select_related('patient')
        self.fields['test'].queryset = self.fields['test'].queryset.filter(active=True)


class PrescriptionForm(StyledModelForm):
    class Meta:
        model = Prescription
        fields = ['encounter', 'allergy_reviewed', 'override_reason', 'notes']
        labels = {'allergy_reviewed': "I have reviewed this patient's documented allergies",
                  'override_reason': 'Clinical justification (required if a possible allergy match is shown)', 'notes': 'Notes for the pharmacist'}
        widgets = {'override_reason': forms.Textarea(attrs={'rows': 2}), 'notes': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields['encounter'].queryset = Encounter.objects.filter(status='open').select_related('patient')
        self.fields['encounter'].label = 'Visit'


class PrescriptionItemForm(StyledModelForm):
    class Meta:
        model = PrescriptionItem
        fields = ['medication', 'dose', 'units_per_dose', 'route', 'frequency', 'duration_days', 'quantity', 'instructions']
        labels = {'units_per_dose': 'Per dose', 'duration_days': 'Days', 'quantity': 'Total qty'}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields['medication'].queryset = Medication.objects.filter(active=True).order_by('name')
        self.fields['quantity'].required = False
        self.fields['units_per_dose'].widget.attrs.update({'step': '0.25', 'min': '0.25'})
        self.fields['duration_days'].widget.attrs.update({'min': '1'})
        self.fields['dose'].widget.attrs['placeholder'] = 'e.g. 500 mg'
        self.fields['instructions'].widget.attrs['placeholder'] = 'e.g. after food'

    def clean(self):
        data = super().clean()
        if self.cleaned_data.get('DELETE') or not data.get('medication'):
            return data
        if not data.get('quantity'):
            q = PrescriptionItem.calculate_quantity(data.get('units_per_dose'), data.get('frequency'), data.get('duration_days'))
            if q is None:
                self.add_error('quantity', 'Enter the total quantity for “when required” or “as directed” medicines.')
            else:
                data['quantity'] = q
                self.instance.quantity = q
        return data


PrescriptionItemFormSet = forms.inlineformset_factory(
    Prescription, PrescriptionItem, form=PrescriptionItemForm, extra=0, min_num=1, validate_min=True, can_delete=True, max_num=30)


class AllergyForm(StyledModelForm):
    class Meta:
        model = Allergy
        fields = ['substance', 'reaction', 'severity', 'status']


class ConditionForm(StyledModelForm):
    class Meta:
        model = Condition
        fields = ['name', 'code', 'status', 'onset', 'notes']
        widgets = {'onset': forms.DateInput(attrs={'type': 'date'})}


class FormDefinitionForm(StyledModelForm):
    class Meta:
        model = FormDefinition
        fields = ['name', 'slug', 'schema', 'published']
        widgets = {'schema': forms.HiddenInput()}


class WorkflowDefinitionForm(StyledModelForm):
    class Meta:
        model = WorkflowDefinition
        fields = ['name', 'steps', 'active']
        widgets = {'steps': forms.HiddenInput()}


class AdmissionForm(StyledModelForm):
    class Meta:
        model = Admission
        fields = ['encounter', 'bed']

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields['encounter'].queryset = Encounter.objects.filter(status='open').select_related('patient')
        self.fields['bed'].queryset = Bed.objects.filter(state='available').select_related('ward')
