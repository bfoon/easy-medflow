"""Dr. Flow's pharmacy and bedside context: the clinical facts are there, the personal data is not."""
import json
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from . import dr_flow_context as D
from .clinical import deidentified_context
from .models import (Admission, Allergy, Bed, BedsideObservation, BedsideState, Encounter, ImagingAIRun, ImagingImage,
                     ImagingOrder, Medication, MedicationAdministration, Prescription, PrescriptionItem, StockBatch,
                     StockLocation, Supplier)
from .test_evidence import Base

SECRET_BATCH, SECRET_SUPPLIER = 'BATCH-ZX9931', 'Secret Pharma Supplies Ltd'


class DrFlowContextTests(Base):
    def setUp(self):
        p = self.man
        p.phone = '+220 7712345'; p.save()
        now = timezone.now()
        self.e = Encounter.objects.create(patient=p, department=self.dept, reason='Breathless', diagnosis='Pneumonia',
                                          clinician=self.users['doctor'], vitals={'weight_kg': '60'})
        Allergy.objects.create(patient=p, substance='Penicillin', reaction='Rash after Lamin took it', severity='severe')
        # pharmacy: one medicine in stock, one out of stock
        sup = Supplier.objects.create(name=SECRET_SUPPLIER)
        self.cef = Medication.objects.create(name='Ceftriaxone', generic_name='Ceftriaxone', strength='1 g', form='Vial', category='antibiotic', reorder_level=5)
        self.dox = Medication.objects.create(name='Doxycycline', generic_name='Doxycycline', strength='100 mg', form='Capsule', category='antibiotic')
        batch = StockBatch.objects.create(medication=self.cef, batch_number=SECRET_BATCH, expiry=date.today() + timedelta(days=200),
                                          quantity=40, store=StockLocation.dispensing(), supplier=sup)
        rx = Prescription.objects.create(encounter=self.e, state='dispensed', notes='Call Lamin Ceesay on +220 7712345',
                                         override_reason='Lamin says penicillin rash was mild', signed_by=self.users['doctor'])
        self.item = PrescriptionItem.objects.create(prescription=rx, medication=self.cef, dose='1 g', route='iv', frequency='OD',
                                                    duration_days=5, quantity=5, instructions='Give slowly; Ceesay prefers left arm',
                                                    availability_note='Told Lamin to wait')
        from .models import Dispense
        Dispense.objects.create(prescription=rx, item=self.item, batch=batch, quantity=5, dispensed_by=self.users['pharmacy'])
        MedicationAdministration.objects.create(item=self.item, scheduled_for=now - timedelta(hours=10), given_at=now - timedelta(hours=10),
                                                status='given', given_by=self.users['nurse'], note='Lamin asleep after')
        MedicationAdministration.objects.create(item=self.item, scheduled_for=now - timedelta(hours=2), status='missed',
                                                given_by=self.users['nurse'])
        # bedside: ICU bed, oxygen, chest drain, two observations
        self.bed = Bed.objects.filter(state='available').first()
        self.bed.kind = 'icu'; self.bed.save()
        self.adm = Admission.objects.create(encounter=self.e, bed=self.bed, admitted_at=now - timedelta(days=3),
                                            discharge_notes='Lamin family in room 4')
        BedsideState.objects.create(admission=self.adm, devices={
            'oxygen': {'on': True, 'device': 'mask', 'flow_l_min': 8},
            'iv': {'on': True, 'fluid': 'saline', 'rate_ml_h': 100, 'bag_ml': 1000, 'remaining_ml': 30, 'note': 'Ceesay pulled line'},
            'chest_drain': {'on': True, 'side': 'right', 'bubbling': True}})
        BedsideObservation.objects.create(admission=self.adm, taken_at=now - timedelta(hours=1), heart_rate=118, systolic=96, diastolic=60,
                                          resp_rate=26, spo2=91, temperature_c=38.6, on_oxygen=True, recorded_by=self.users['nurse'])
        BedsideObservation.objects.create(admission=self.adm, taken_at=now - timedelta(hours=30), heart_rate=90, recorded_by=self.users['nurse'])

    def secrets(self):
        p = self.man
        return ['Lamin', 'Ceesay', p.mrn, '7712345', '1980-05-01', self.bed.code, self.bed.ward.name, SECRET_BATCH, SECRET_SUPPLIER,
                'room 4', 'Rash after', str(date.today().year) + '-']

    def test_pharmacy_section(self):
        ph = D.pharmacy_context(self.e)
        m = ph['current_and_recent_medicines'][0]
        self.assertEqual((m['medicine'], m['route'], m['dispensed'], m['pharmacy_stock_now']), ('Ceftriaxone 1 g vial', 'Intravenous (IV)', 'fully', 'in stock'))
        self.assertEqual(m['doses_last_48h'], {'given': 1, 'missed': 1})
        self.assertAlmostEqual(m['hours_since_last_dose_given'], 10, delta=0.2)
        self.assertTrue(m['allergy_warning_overridden'])
        self.assertIn('[patient]', m['instructions'])
        self.assertEqual(ph['allergies'], [{'substance': 'Penicillin', 'severity': 'severe'}])
        antibiotics = ' '.join(ph['hospital_formulary']['Antibiotics'])
        self.assertIn('Ceftriaxone 1 g vial (in stock', antibiotics)
        self.assertIn('Doxycycline 100 mg capsule (out of stock', antibiotics)

    def test_bedside_section(self):
        bd = D.bedside_context(self.e)
        self.assertEqual((bd['admitted'], bd['bed_type'], bd['days_since_admission']), (True, 'ICU', 3))
        self.assertEqual(bd['devices']['oxygen']['device'], 'mask')
        self.assertEqual(bd['devices']['chest_drain']['side'], 'right')
        self.assertNotIn('note', bd['devices']['iv_fluid'])
        self.assertTrue(any('bubbling' in w for w in bd['device_warnings']))
        self.assertEqual(len(bd['observations_last_24h']), 1)          # the 30-hour-old one is left out
        o = bd['observations_last_24h'][0]
        self.assertEqual((o['spo2'], o['bp'], o['on_oxygen']), (91, '96/60', True))

    def test_no_personal_data_anywhere(self):
        blob = json.dumps(deidentified_context(self.e), default=str)
        self.assertIn('pharmacy', blob); self.assertIn('bedside', blob)
        for s in self.secrets():
            self.assertNotIn(s, blob, s)

    def test_imaging_context_includes_both_without_personal_data(self):
        from . import imaging_ai
        import io, tempfile, shutil
        from PIL import Image
        b = io.BytesIO(); Image.new('RGB', (20, 20)).save(b, 'PNG')
        media = tempfile.mkdtemp()
        with override_settings(MEDIA_ROOT=media):
            o = ImagingOrder.objects.create(encounter=self.e, modality='xray', region='Chest AP', status='acquired')
            img = ImagingImage.objects.create(order=o, file=SimpleUploadedFile('c.png', b.getvalue()))
            r = ImagingAIRun.objects.create(image=img, order=o, kind='question', question='Is the drain in?')
            ctx = imaging_ai.image_context(r, include_draft=True)
        shutil.rmtree(media, ignore_errors=True)
        self.assertEqual(ctx['bedside']['devices']['chest_drain']['side'], 'right')
        self.assertEqual(ctx['pharmacy']['current_and_recent_medicines'][0]['medicine'], 'Ceftriaxone 1 g vial')
        blob = json.dumps(ctx, default=str)
        for s in self.secrets():
            self.assertNotIn(s, blob, s)

    def test_switches_and_not_admitted(self):
        with override_settings(CLINICAL_AI_SHARE_PHARMACY=False, CLINICAL_AI_SHARE_BEDSIDE=False):
            ctx = deidentified_context(self.e)
            self.assertNotIn('pharmacy', ctx); self.assertNotIn('bedside', ctx)
            self.assertIn('medicines', ctx)                           # the older short list comes back
        self.adm.discharged_at = timezone.now() - timedelta(days=2); self.adm.save()
        self.assertEqual(D.bedside_context(self.e), {'admitted': False, 'last_discharged_days_ago': 2})

    def test_scrub_keeps_doses(self):
        out = D.scrub('Benzathine penicillin 2 400 000 IU, call +220 7712345 or 3998877', self.man)
        self.assertIn('2 400 000 IU', out)
        self.assertNotIn('7712345', out); self.assertNotIn('3998877', out)
