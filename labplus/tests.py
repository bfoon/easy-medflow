from django.test import SimpleTestCase
from django.core.exceptions import ValidationError
from decimal import Decimal
from .models import QualityControl
from .views import TRANSITIONS
class LabWorkflowTests(SimpleTestCase):
    def test_rejected_specimen_cannot_be_released(self):
        self.assertEqual(TRANSITIONS['rejected'],set())
    def test_no_shortcut_from_expected_to_received(self):
        self.assertNotIn('received',TRANSITIONS['expected'])
    def test_qc_requires_positive_sd(self):
        q=QualityControl(sd=Decimal('0'))
        with self.assertRaises(ValidationError):q.clean()
