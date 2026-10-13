"""Lab insights: the 3D heart's blood flow uses the newest bedside observation (if recent) over the visit vitals."""
import json
from datetime import timedelta

from django.utils import timezone

from .models import Admission, Bed, BedsideObservation, Encounter
from .test_evidence import Base
from .views import patient_lab_data


class HeartFlowVitalsTests(Base):
    def setUp(self):
        self.e = Encounter.objects.create(patient=self.man, department=self.dept, reason='Breathless', diagnosis='Atrial fibrillation; acute left MCA stroke',
                                          clinician=self.users['doctor'], vitals={'heart_rate': '88', 'bp': '130/80', 'spo2': '97'})

    def test_visit_vitals_when_not_admitted(self):
        d = patient_lab_data(self.man)
        self.assertEqual(d['vitals']['heart_rate'], '88')
        self.assertEqual(d['vitals_meta'], {'source': 'visit'})

    def test_recent_bedside_observation_wins(self):
        adm = Admission.objects.create(encounter=self.e, bed=Bed.objects.filter(state='available').first())
        BedsideObservation.objects.create(admission=adm, taken_at=timezone.now() - timedelta(hours=2), heart_rate=132, systolic=94, diastolic=58,
                                          spo2=88, resp_rate=28, temperature_c=38.2, on_oxygen=True, recorded_by=self.users['nurse'])
        d = patient_lab_data(self.man)
        self.assertEqual((d['vitals']['heart_rate'], d['vitals']['bp'], d['vitals']['spo2']), (132, '94/58', 88))
        self.assertEqual(d['vitals_meta']['source'], 'bedside')
        self.assertAlmostEqual(d['vitals_meta']['hours_ago'], 2, delta=.1)
        self.assertTrue(d['vitals_meta']['on_oxygen'])

    def test_old_bedside_observation_is_ignored(self):
        adm = Admission.objects.create(encounter=self.e, bed=Bed.objects.filter(state='available').first())
        BedsideObservation.objects.create(admission=adm, taken_at=timezone.now() - timedelta(hours=60), heart_rate=40, recorded_by=self.users['nurse'])
        d = patient_lab_data(self.man)
        self.assertEqual(d['vitals']['heart_rate'], '88')
        self.assertEqual(d['vitals_meta']['source'], 'visit')

    def test_page_carries_the_data_and_scripts(self):
        page = self.as_('doctor').get(f'/patients/{self.man.pk}/labs/').content.decode()
        self.assertIn('organs-heart3d.js', page); self.assertIn('anatomy-layers.js', page)
        start = page.index('id="lab-data"'); blob = page[page.index('>', start) + 1:page.index('</script>', start)]
        d = json.loads(blob)
        self.assertEqual(d['vitals_meta']['source'], 'visit')
        self.assertIn('Atrial fibrillation; acute left MCA stroke', d['dx'])

    def test_no_vitals_at_all(self):
        self.e.vitals = {}; self.e.save()
        self.assertIsNone(patient_lab_data(self.man)['vitals_meta'])
