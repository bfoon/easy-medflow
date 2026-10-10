from django.test import TestCase
from django.contrib.auth import get_user_model
from datetime import date,timedelta
from .models import Patient,Allergy,Medication,StockBatch,Encounter,Department
from .services import prescription_warnings,availability

class SafetySupportTests(TestCase):
    def setUp(self):
        u=get_user_model().objects.create_user(username='clinician',password='test-not-for-use')
        self.patient=Patient.objects.create(first_name='A',last_name='B',dob=date(1990,1,1),sex='F')
        self.encounter=Encounter.objects.create(patient=self.patient,reason='Assessment',clinician=u)
        self.med=Medication.objects.create(name='Amoxicillin',generic_name='amoxicillin')
    def test_exact_name_warning(self):
        Allergy.objects.create(patient=self.patient,substance='amoxicillin',reaction='rash',severity='severe')
        w=prescription_warnings(self.encounter,self.med,5)
        self.assertEqual(len(w['possible_allergy_matches']),1)
    def test_expired_stock_is_not_available(self):
        StockBatch.objects.create(medication=self.med,batch_number='old',expiry=date.today()-timedelta(days=1),quantity=200)
        StockBatch.objects.create(medication=self.med,batch_number='new',expiry=date.today()+timedelta(days=3),quantity=7)
        self.assertEqual(availability(self.med),7)
