"""Phone-number search in every format, and work boards that keep showing new requests however many exist."""
from datetime import timedelta

from django.utils import timezone

from .models import Encounter, ImagingOrder, LabOrder, LabRequest, LabTest, Patient
from .phones import contact_digits, digits, is_phone_query
from .search import search_patients
from .tests import Base


class PhoneSearchTests(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.p = Patient.objects.create(first_name='Musa', last_name='Bojang', dob=timezone.localdate() - timedelta(days=9000), sex='M',
                                       phone='+220 341 5919', emergency_contact='Wife Isatou, (220) 771-2345')
        cls.local = Patient.objects.create(first_name='Binta', last_name='Sanneh', dob=timezone.localdate() - timedelta(days=12000), sex='F', phone='990 4411')

    def found(self, q, who=None):
        return any(r['p'].pk == (who or self.p).pk for r in search_patients(self.users['doctor'], q=q)['results'])

    def test_helpers(self):
        self.assertEqual(digits('00220 341-5919'), '2203415919')
        self.assertEqual(contact_digits('Mother: +220 771 2345 / 990 1234, house 12'), '2207712345 9901234')
        self.assertTrue(is_phone_query('+220 341 5919'))
        self.assertFalse(is_phone_query('malaria 2024'))
        self.assertTrue(is_phone_query('341'))             # short searches are allowed now: the number starts with 341
        self.assertFalse(is_phone_query('3'))
        self.assertEqual(self.p.phone_digits, '2203415919')

    def test_every_way_of_typing_the_number(self):
        for q in ['+220 341 5919', '3415919', '341 5919', '341-5919', '+2203415919', '2203415919', '00220 3415919', '(220) 341 5919', '5919']:
            self.assertTrue(self.found(q), q)
        wrong = search_patients(self.users['doctor'], q='341 5918')        # one digit off: never an exact match,
        self.assertTrue(wrong['near'])                                     # only offered as "one digit different"
        self.assertTrue(all(r['why'][0].startswith('Close number') for r in wrong['results']))

    def test_country_code_finds_number_stored_without_it(self):
        self.assertTrue(self.found('+220 990 4411', self.local))

    def test_emergency_contact_number(self):
        res = search_patients(self.users['doctor'], q='771 2345')['results']
        self.assertEqual([r['p'] for r in res], [self.p])
        self.assertTrue(res[0]['why'][0].startswith('Emergency contact'))

    def test_phone_stays_in_sync_when_edited(self):
        self.p.phone = '+220 222 3333'
        self.p.save(update_fields=['phone'])
        self.assertTrue(self.found('2223333'))
        self.assertFalse(self.found('3415919'))

    def test_quick_search_patient_list_and_checkin(self):
        c = self.as_('reception')
        self.assertIn('Musa Bojang', [r['name'] for r in c.get('/api/search/', {'q': '341 5919'}).json()['results']])
        self.assertContains(c.get('/patients/', {'q': '+220 341-5919'}), 'Bojang')
        from .views import find_patients
        self.assertEqual(find_patients('341 5919')[0], [self.p])


class BoardCutoffTests(Base):
    """The lab and imaging boards used to load the 300 oldest requests and pick the open ones from those."""

    def test_new_lab_order_shows_after_300_older_requests(self):
        e = self.encounter()
        test = LabTest.objects.filter(active=True).first()
        old = timezone.now() - timedelta(days=200)
        reqs = LabRequest.objects.bulk_create([LabRequest(encounter=e, requested_by=self.users['doctor'], created_at=old, updated_at=old) for _ in range(310)])
        LabOrder.objects.bulk_create([LabOrder(encounter=e, request=r, test=test, status='verified') for r in reqs])
        c = self.as_('doctor')
        c.post('/labs/new/', {'encounter': e.pk, 'tests': [test.pk], 'priority': 'routine'})
        new = LabRequest.objects.order_by('-pk').first()
        self.client.logout()
        r = self.as_('lab').get('/labs/')
        self.assertIn(new, [x for lane in r.context['board'] for x in lane['requests']])
        self.assertEqual(len(r.context['done']), 20)

    def test_new_imaging_request_shows_after_300_older_requests(self):
        e = self.encounter()
        old = timezone.now() - timedelta(days=200)
        ImagingOrder.objects.bulk_create([ImagingOrder(encounter=e, modality='xray', region='Old', status='reported', created_at=old, updated_at=old) for _ in range(310)])
        new = ImagingOrder.objects.create(encounter=e, modality='xray', region='Chest PA', requested_by=self.users['doctor'])
        r = self.as_('doctor').get('/imaging/')
        self.assertIn(new, [x for lane in r.context['board'] for x in lane['orders']])
