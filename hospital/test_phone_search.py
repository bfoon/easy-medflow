"""Phone search the way the front desk uses it: the start of the number, the end, both ends, anywhere, slips of
one digit, the country code ignored, highlighting of what matched (hospital/phones.py)."""
from datetime import timedelta

from django.utils import timezone

from .models import Patient
from .phones import best_match, mark_segments, near_matches, one_edit_apart, parse
from .search import search_patients
from .tests import Base


class PhonePatternTests(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        dob = timezone.localdate() - timedelta(days=11000)
        mk = lambda first, phone, contact='': Patient.objects.create(first_name=first, last_name='Phone', dob=dob, sex='F', phone=phone, emergency_contact=contact)
        cls.long = mk('Long', '+220 346765 6778')          # the example from the request: a 10-digit local number
        cls.awa = mk('Awa', '+220 346 1200')
        cls.isa = mk('Isa', '7346 778')                     # 346 in the middle, ends with 778
        cls.kid = mk('Kid', '', contact='Mother: +220 349 0778')
        cls.code = mk('Code', '+220 220 4455')              # a local number that itself starts with 220

    def names(self, q):
        return [r['p'].first_name for r in search_patients(self.users['doctor'], q=q)['results']]

    def test_starts_with_two_or_three_digits(self):
        self.assertEqual(set(self.names('34')), {'Long', 'Awa', 'Kid'})       # own numbers, and the mother's number
        self.assertEqual(set(self.names('346')), {'Long', 'Awa'})             # not Isa: 346 is in the middle of hers
        self.assertEqual(self.names('346')[-1:] != ['Kid'], True)

    def test_country_code_is_never_matched(self):
        self.assertEqual(self.names('22'), ['Code'])                           # only the number that really starts with 22
        self.assertEqual(self.names('220'), ['Code'])

    def test_ends_with(self):
        for q in ('*778', '…778', '...778'):
            self.assertEqual(set(self.names(q)), {'Long', 'Isa', 'Kid'}, q)
        self.assertEqual(set(self.names('*6778')), {'Long', 'Isa'})               # 7346 778 ends with 6778 too

    def test_both_ends_and_anywhere(self):
        self.assertEqual(self.names('346*778'), ['Long'])
        self.assertEqual(set(self.names('*765*')), {'Long'})
        self.assertEqual(self.names('*612*'), ['Awa'])                          # 346 1200
        self.assertIsNone(parse('*46*'))                                        # two digits anywhere would match half the hospital

    def test_four_digits_rank_start_then_end_then_middle(self):
        Patient.objects.create(first_name='Mid', last_name='Phone', dob=self.long.dob, sex='M', phone='+220 977 8100')
        Patient.objects.create(first_name='Start', last_name='Phone', dob=self.long.dob, sex='M', phone='+220 778 1234')
        self.assertEqual(self.names('778'), ['Start'])                          # 3 digits: starts with only
        self.assertEqual(self.names('7781'), ['Start', 'Mid'])                  # starts with (778 1234) before the middle (977 8100)
        self.assertEqual(self.names('7810'), ['Mid'])                           # 4 digits: also the middle (977 8100)
        self.assertEqual(self.names('6778'), ['Long', 'Isa'])                   # both end in 6778; Long's number is longer, same rank

    def test_whole_number_any_format_ranks_first(self):
        for q in ('+220 346765 6778', '3467656778', '00220 346 765 6778', '346-765-6778'):
            self.assertEqual(self.names(q)[:1], ['Long'], q)

    def test_too_vague_is_not_a_phone_search(self):
        for q in ('3', '*7', '**', '*7*', 'malaria 2024'):
            self.assertIsNone(parse(q), q)

    def test_slips_of_one_digit(self):
        self.assertTrue(one_edit_apart('3415919', '3415918'))     # wrong digit
        self.assertTrue(one_edit_apart('3415919', '3451919'))     # neighbours swapped
        self.assertTrue(one_edit_apart('3415919', '341919'))      # digit missed
        self.assertTrue(one_edit_apart('3415919', '34159199'))    # digit extra
        self.assertTrue(one_edit_apart('3415919', '3419519'))     # 5 and 9 swapped
        self.assertFalse(one_edit_apart('3415919', '3405818'))    # two changes
        res = search_patients(self.users['doctor'], q='346765 6779')
        self.assertTrue(res['near'])
        self.assertEqual([r['p'].first_name for r in res['results']], ['Long'])
        self.assertEqual(near_matches(parse('999 9999'), Patient.objects.all()), [])

    def test_highlights_only_the_matched_digits(self):
        def marked(phone, q):
            return ''.join(f'[{t}]' if hit else t for t, hit in mark_segments(phone, q))
        self.assertEqual(marked('+220 346765 6778', '34'), '+220 [34]6765 6778')
        self.assertEqual(marked('+220 346765 6778', '*778'), '+220 346765 6[778]')
        self.assertEqual(marked('+220 346765 6778', '346*778'), '+220 [346]765 6[778]')
        self.assertEqual(marked('+220 346765 6778', '+220 346765 6778'), '+220 [346765 6778]')
        self.assertIsNone(mark_segments('+220 346765 6778', '99'))
        m = best_match(self.kid.phone_local, self.kid.contact_local, parse('349'))
        self.assertFalse(m['own'])

    def test_stays_in_sync_and_pages_show_highlight(self):
        self.awa.phone = '+220 555 0101'
        self.awa.save(update_fields=['phone'])
        self.assertNotIn('Awa', self.names('346'))
        self.assertEqual(self.names('*0101'), ['Awa'])
        c = self.as_('reception')
        r = c.get('/patients/', {'q': '346'})
        self.assertContains(r, '<mark class="ph-hit">346</mark>', html=False)
        self.assertContains(r, 'starts with 346')
        r = c.get('/checkin/', {'q': '*778'})
        self.assertContains(r, '<mark class="ph-hit">778</mark>', html=False)
        data = c.get('/api/search/', {'q': '346*778'}).json()
        self.assertEqual(data['results'][0]['name'], 'Long Phone')
        self.assertIn(['346', True], [list(x) for x in data['results'][0]['phone']])
        self.assertEqual(data['phone_hint'], 'starts with 346, ends with 778')

    def test_html_in_a_phone_is_escaped(self):
        p = Patient.objects.create(first_name='Bad', last_name='Phone', dob=self.long.dob, sex='M', phone='346 1111 <b>')
        r = self.as_('reception').get('/patients/', {'q': '346'})
        self.assertNotContains(r, '1111 <b>', html=False)
        self.assertContains(r, '<mark class="ph-hit">346</mark> 1111 &lt;b&gt;', html=False)
