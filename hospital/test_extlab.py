"""Outside laboratories (send-outs), the one-time link, network labs, and the printed request and prescription."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import extlab
from .models import (AuditEvent, Department, Encounter, LabOrder, LabRequest, LabTest, Medication, NetworkFacility, Notification,
                     Patient, Prescription, PrescriptionItem, StaffProfile)
from .models_extlab import MAX_PHONE_ATTEMPTS, ExternalLabReferral

PW = 'test-only-Pa55word!'


@override_settings(NOTIFY_EMAIL_SYNC=True, MEDICAL_EVIDENCE_FETCH=False, HOSPITAL_PHONE='+220 400 0000')
class ExtLabBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('bootstrap_hospital', verbosity=0)
        U = get_user_model()
        cls.users = {}
        for role in ['doctor', 'lab', 'pharmacy', 'reception']:
            u = U.objects.create_user(username=role, password=PW, first_name=role.title())
            StaffProfile.objects.create(user=u, role=role, license_number='GMC-123' if role == 'doctor' else '')
            cls.users[role] = u
        cls.net_lab = NetworkFacility.objects.create(name='Kanifing Diagnostics', kind='diagnostic', location='Kanifing', phone='+220 446 1111')
        cls.other_net = NetworkFacility.objects.create(name='Brikama Lab', kind='diagnostic', location='Brikama', phone='+220 446 2222')
        cls.dir_only = NetworkFacility.objects.create(name='Directory Only Lab', kind='diagnostic', email='lab@example.gm')
        for name, fac in [('partner', cls.net_lab), ('partner2', cls.other_net)]:
            u = U.objects.create_user(username=name, password=PW)
            StaffProfile.objects.create(user=u, role='partner', facility=fac)
            cls.users[name] = u
        cls.patient = Patient.objects.create(first_name='Awa', last_name='Jallow', dob=date(1990, 1, 1), sex='F', phone='+220 341 5919')
        cls.hb = LabTest.objects.get(code='HB')
        cls.mal = LabTest.objects.get(code='MAL')

    def setUp(self):
        self.enc = Encounter.objects.create(patient=self.patient, clinician=self.users['doctor'], department=Department.objects.first(), reason='Fever', status='open')
        self.lr = LabRequest.objects.create(encounter=self.enc, requested_by=self.users['doctor'], clinical_notes='Fever 3 days')
        for t in (self.hb, self.mal):
            LabOrder.objects.create(encounter=self.enc, request=self.lr, test=t)

    def as_(self, who):
        c = Client()
        c.login(username=who, password=PW)
        return c

    def send(self, **kw):
        data = {'where': 'other', 'lab_name': 'Westfield Medical Lab', 'lab_phone': '7001122', 'patient_phone': '3415919', 'days': '14'}
        data.update(kw)
        self.doc = self.as_('doctor')                 # the one-time link is held in this client's session
        return self.doc.post(reverse('extlab_new', args=[self.lr.pk]), data)


class LinkTests(ExtLabBase):
    def token_of(self, client=None):
        """The plain link is shown once on the detail page; read it from there."""
        s = ExternalLabReferral.objects.get()
        html = (client or self.doc).get(reverse('extlab_detail', args=[s.pk])).content.decode()
        start = html.index('/xl/') + 4
        return s, html[start:html.index('/', start)], html

    def test_send_out_with_link_shows_it_once_and_stores_only_a_hash(self):
        c = self.as_('doctor')
        r = c.post(reverse('extlab_new', args=[self.lr.pk]), {'where': 'other', 'lab_name': 'Westfield Medical Lab', 'lab_phone': '7001122', 'patient_phone': '3415919'})
        s = ExternalLabReferral.objects.get()
        self.assertRedirects(r, reverse('extlab_detail', args=[s.pk]), fetch_redirect_response=False)
        self.assertEqual((s.channel, s.status, s.phone_local), ('link', 'sent', '3415919'))
        html = c.get(reverse('extlab_detail', args=[s.pk])).content.decode()
        start = html.index('/xl/') + 4
        token = html[start:html.index('/', start)]
        self.assertNotEqual(s.token_hash, token)
        self.assertEqual(s.token_hash, extlab.sha(token))
        self.assertIn('wa.me/2207001122', html)
        self.assertNotIn('/xl/', c.get(reverse('extlab_detail', args=[s.pk])).content.decode())      # gone on the next visit

    def test_requires_phone_and_contact_and_blocks_second_sendout(self):
        self.send(patient_phone='12')
        self.send(lab_phone='')
        self.assertFalse(ExternalLabReferral.objects.exists())
        self.send()
        self.send()
        self.assertEqual(ExternalLabReferral.objects.count(), 1)

    def test_request_leaves_the_lab_board_while_out(self):
        self.send()
        board = self.as_('lab').get(reverse('labs')).context['board']
        self.assertNotIn(self.lr.pk, [r.pk for lane in board for r in lane['requests']])

    def test_wrong_phone_counts_and_locks_after_five(self):
        self.send()
        s = ExternalLabReferral.objects.get()
        token = extlab.reissue(s)
        lab = Client()
        for i in range(MAX_PHONE_ATTEMPTS - 1):
            r = lab.post(reverse('xl_open', args=[token]), {'phone': '9999999'})
            self.assertContains(r, 'does not match')
            self.assertNotContains(r, 'Jallow')
        r = lab.post(reverse('xl_open', args=[token]), {'phone': '9999999'})
        self.assertContains(r, 'Link locked', status_code=410)
        s.refresh_from_db()
        self.assertTrue(s.is_locked)
        self.assertTrue(Notification.objects.filter(user=self.users['doctor'], kind='lab_sendout_locked').exists())
        self.assertContains(lab.post(reverse('xl_open', args=[token]), {'phone': '3415919'}), 'Link locked', status_code=410)

    def test_correct_phone_claims_link_for_one_device_only(self):
        self.send()
        c = self.doc
        s, token, _ = self.token_of()
        lab = Client()
        self.assertNotContains(lab.get(reverse('xl_open', args=[token])), 'Jallow')
        r = lab.post(reverse('xl_open', args=[token]), {'phone': '+220 341-5919'})          # typed differently: still matches
        self.assertRedirects(r, reverse('xl_work', args=[token]))
        self.assertContains(lab.get(reverse('xl_work', args=[token])), 'Awa Jallow')
        s.refresh_from_db()
        self.assertEqual(s.status, 'arrived')
        other = Client()
        self.assertContains(other.get(reverse('xl_open', args=[token])), 'already opened on another device', status_code=403)
        self.assertRedirects(other.get(reverse('xl_work', args=[token])), reverse('xl_open', args=[token]), target_status_code=403)

    def test_reissue_kills_old_link(self):
        self.send()
        c = self.doc
        s, old, _ = self.token_of()
        c.post(reverse('extlab_action', args=[s.pk, 'reissue']))
        self.assertContains(Client().get(reverse('xl_open', args=[old])), 'not valid', status_code=404)

    def test_lab_records_sample_and_sends_results_back(self):
        self.send()
        c = self.doc
        s, token, _ = self.token_of()
        lab = Client()
        lab.post(reverse('xl_open', args=[token]), {'phone': '3415919'})
        lab.post(reverse('xl_work', args=[token]), {'action': 'collected', 'specimen_ref': 'WF-889'})
        s.refresh_from_db()
        self.assertEqual((s.status, s.specimen_ref), ('collected', 'WF-889'))
        hb_order, mal_order = LabOrder.objects.get(test=self.hb), LabOrder.objects.get(test=self.mal)
        hb_p, mal_p = self.hb.parameters.get(), self.mal.parameters.get()
        # missing name and a value: refused
        r = lab.post(reverse('xl_work', args=[token]), {'action': 'results', f'p_{hb_order.pk}_{hb_p.pk}': '11.2'})
        self.assertContains(r, 'Enter every value for: Malaria RDT')
        r = lab.post(reverse('xl_work', args=[token]), {
            'action': 'results', 'reported_by_name': 'Isatou Ceesay', f'p_{hb_order.pk}_{hb_p.pk}': '6.1',
            f'p_{mal_order.pk}_{mal_p.pk}': 'Positive · P. falciparum', 'lab_comment': 'Repeat Hb tomorrow'})
        self.assertContains(r, 'Results sent')
        self.assertNotContains(r, 'Jallow')
        s.refresh_from_db()
        hb_order.refresh_from_db()
        self.assertEqual(s.status, 'reported')
        self.assertEqual(s.token_hash, '')
        self.assertEqual(hb_order.status, 'resulted')
        self.assertEqual(hb_order.values.get().flag, 'LL')                    # 6.1 g/dL is below the critical limit
        self.assertIn('Reported by Westfield Medical Lab (Isatou Ceesay), sample WF-889', hb_order.result)
        self.assertTrue(Notification.objects.filter(user=self.users['doctor'], kind='lab_critical').exists())
        self.assertContains(lab.get(reverse('xl_open', args=[token])), 'not valid', status_code=404)
        # back on the hospital board for verification, then verified as usual
        board = self.as_('lab').get(reverse('labs')).context['board']
        self.assertIn(self.lr.pk, [r.pk for lane in board if lane['key'] == 'resulted' for r in lane['requests']])
        self.as_('lab').post(reverse('lab_request_action', args=[self.lr.pk, 'verify']))
        self.assertEqual(LabRequest.objects.get(pk=self.lr.pk).stage, 'verified')

    def test_report_file_alone_is_enough(self):
        self.send()
        c = self.doc
        s, token, _ = self.token_of()
        lab = Client()
        lab.post(reverse('xl_open', args=[token]), {'phone': '3415919'})
        bad = SimpleUploadedFile('r.pdf', b'not a pdf', content_type='application/pdf')
        self.assertContains(lab.post(reverse('xl_work', args=[token]), {'action': 'results', 'reported_by_name': 'X', 'report_file': bad}), 'not a real PDF')
        pdf = SimpleUploadedFile('r.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf')
        lab.post(reverse('xl_work', args=[token]), {'action': 'results', 'reported_by_name': 'X', 'report_file': pdf})
        s.refresh_from_db()
        self.assertEqual(s.status, 'reported')
        self.assertIn('See the attached lab report', LabOrder.objects.get(test=self.mal).result)
        r = c.get(reverse('extlab_file', args=[s.pk]))
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertEqual(Client().get(reverse('extlab_file', args=[s.pk])).status_code, 302)      # needs sign-in
        s.report_file.delete(save=False)

    def test_cancel_closes_link(self):
        self.send()
        c = self.doc
        s, token, _ = self.token_of()
        c.post(reverse('extlab_action', args=[s.pk, 'cancel']), {'reason': 'Tested here'})
        s.refresh_from_db()
        self.assertEqual(s.status, 'cancelled')
        self.assertContains(Client().get(reverse('xl_open', args=[token])), 'not valid', status_code=404)

    def test_expired_link_refused(self):
        self.send()
        s = ExternalLabReferral.objects.get()
        token = extlab.reissue(s)
        ExternalLabReferral.objects.filter(pk=s.pk).update(expires_at=timezone.now() - timedelta(hours=1))
        self.assertContains(Client().get(reverse('xl_open', args=[token])), 'expired', status_code=410)

    def test_directory_lab_without_login_gets_a_link(self):
        self.send(where='network', facility=self.dir_only.pk, lab_phone='')
        self.assertEqual(ExternalLabReferral.objects.get().channel, 'link')

    def test_order_form_can_go_straight_to_outside_lab(self):
        r = self.as_('doctor').post(reverse('lab_new'), {'encounter': self.enc.pk, 'tests': [self.hb.pk], 'where': 'outside'})
        lr = LabRequest.objects.latest('pk')
        self.assertRedirects(r, reverse('extlab_new', args=[lr.pk]), fetch_redirect_response=False)


class NetworkTests(ExtLabBase):
    def test_network_lab_opens_with_phone_number_only(self):
        self.send(where='network', facility=self.net_lab.pk)
        s = ExternalLabReferral.objects.get()
        self.assertEqual((s.channel, s.token_hash), ('network', ''))
        self.assertTrue(Notification.objects.filter(user=self.users['partner'], kind='lab_sendout').exists())
        p = self.as_('partner')
        page = p.get(reverse('xl_network')).content.decode()
        self.assertIn('Awa J.', page)
        self.assertNotIn('Jallow', page)                                   # no full name before the phone number
        self.assertRedirects(p.get(reverse('xl_network_work', args=[s.pk])), reverse('xl_network'))
        r = p.post(reverse('xl_network'), {'phone': '00220 3415919'})
        self.assertRedirects(r, reverse('xl_network_work', args=[s.pk]))
        self.assertContains(p.get(reverse('xl_network_work', args=[s.pk])), 'Awa Jallow')
        hb_order, mal_order = LabOrder.objects.get(test=self.hb), LabOrder.objects.get(test=self.mal)
        p.post(reverse('xl_network_work', args=[s.pk]), {'action': 'results', f'p_{hb_order.pk}_{self.hb.parameters.get().pk}': '12.5',
                                                         f'p_{mal_order.pk}_{self.mal.parameters.get().pk}': 'Negative'})
        s.refresh_from_db()
        self.assertEqual((s.status, s.reported_by), ('reported', self.users['partner']))
        self.assertEqual(LabOrder.objects.get(test=self.hb).values.get().entered_by, self.users['partner'])

    def test_other_facility_cannot_find_it(self):
        self.send(where='network', facility=self.net_lab.pk)
        s = ExternalLabReferral.objects.get()
        p2 = self.as_('partner2')
        self.assertContains(p2.post(reverse('xl_network'), {'phone': '3415919'}), 'No open request')
        self.assertEqual(p2.get(reverse('xl_network_work', args=[s.pk])).status_code, 404)
        self.assertTrue(AuditEvent.objects.filter(actor=self.users['partner2'], action='lab_sendout_lookup_failed').exists())

    def test_staff_cannot_use_partner_portal(self):
        self.assertEqual(self.as_('doctor').get(reverse('xl_network')).status_code, 403)


class PrintTests(ExtLabBase):
    def rx(self, state='signed'):
        p = Prescription.objects.create(encounter=self.enc, state=state, signed_by=self.users['doctor'], signed_at=timezone.now())
        PrescriptionItem.objects.create(prescription=p, medication=Medication.objects.get(name='Amoxicillin'), dose='500 mg', frequency='TDS', duration_days=5, quantity=15)
        return p

    def test_lab_request_print_has_patient_slip_when_sent_out(self):
        c = self.as_('doctor')
        r = c.get(reverse('lab_request_print', args=[self.lr.pk]))
        self.assertContains(r, 'Laboratory request')
        self.assertNotContains(r, 'Patient copy')
        self.send()
        s = ExternalLabReferral.objects.get()
        r = c.get(reverse('lab_request_print', args=[self.lr.pk]) + '?size=a5')
        self.assertContains(r, 'Patient copy')
        self.assertContains(r, s.reference)
        self.assertContains(r, 'ending in <b>919</b>', html=False)
        self.assertContains(r, '--tube:#9B7BD4')                           # purple-top EDTA chip for haemoglobin

    def test_prescription_print_and_public_check(self):
        p = self.rx()
        r = self.as_('pharmacy').get(reverse('prescription_print', args=[p.pk]))
        self.assertContains(r, 'fifteen')
        self.assertContains(r, 'GMC-123')
        html = r.content.decode()
        start = html.index('/rx/') + 4
        token = html[start:html.index('/', start)]
        check = Client().get(reverse('rx_verify', args=[token]))
        self.assertContains(check, 'Genuine and valid')
        self.assertContains(check, 'AJ · born 1990')
        self.assertNotContains(check, 'Jallow')
        Prescription.objects.filter(pk=p.pk).update(state='dispensed')
        self.assertContains(Client().get(reverse('rx_verify', args=[token])), 'Already dispensed')
        self.assertEqual(Client().get(reverse('rx_verify', args=['forged'])).status_code, 404)

    def test_draft_prints_watermark(self):
        p = self.rx('draft')
        self.assertContains(self.as_('doctor').get(reverse('prescription_print', args=[p.pk])), 'DRAFT · NOT VALID')

    def test_quantity_words(self):
        self.assertEqual([extlab.in_words(n) for n in (0, 15, 42, 100, 115, 1005, 2500)],
                         ['zero', 'fifteen', 'forty-two', 'one hundred', 'one hundred and fifteen', 'one thousand and five', 'two thousand five hundred'])


class PageSmokeTests(ExtLabBase):
    """Every new or changed page renders, in each state."""
    def test_pages(self):
        d = self.as_('doctor')
        for u in [reverse('extlab_new', args=[self.lr.pk]), reverse('lab_new'), reverse('lab_request_detail', args=[self.lr.pk]), reverse('extlab_list')]:
            self.assertEqual(d.get(u).status_code, 200, u)
        self.send(where='network', facility=self.net_lab.pk)
        s = ExternalLabReferral.objects.get()
        for u in [reverse('lab_request_detail', args=[self.lr.pk]), reverse('extlab_detail', args=[s.pk]), reverse('extlab_list'), reverse('labs'), reverse('lab_request_print', args=[self.lr.pk])]:
            r = d.get(u); self.assertEqual(r.status_code, 200, u)
        p = self.as_('partner')
        self.assertEqual(p.get(reverse('xl_network')).status_code, 200)
        p.post(reverse('xl_network'), {'phone': '3415919'})
        p.post(reverse('xl_network_work', args=[s.pk]), {'action': 'collected'})
        r = p.get(reverse('xl_network_work', args=[s.pk])); self.assertContains(r, 'Recorded')
        self.assertEqual(p.get(reverse('dashboard'), follow=True).status_code, 200)
        rx = Prescription.objects.create(encounter=self.enc, state='draft')
        PrescriptionItem.objects.create(prescription=rx, medication=Medication.objects.get(name='Amoxicillin'), quantity=10)
        for u in [reverse('prescription_detail', args=[rx.pk]), reverse('prescription_print', args=[rx.pk]) + '?size=a4&copy=1']:
            self.assertEqual(d.get(u).status_code, 200, u)
        r = self.as_('lab').get(reverse('lab_request_detail', args=[self.lr.pk]))
        self.assertContains(r, 'With Kanifing Diagnostics'); self.assertNotContains(r, 'Process &amp; enter')
        # expired + locked states render on the board and detail
        ExternalLabReferral.objects.filter(pk=s.pk).update(locked_at='2026-01-01T00:00Z')
        self.assertContains(d.get(reverse('extlab_list')), 'Locked')
        self.assertEqual(d.get(reverse('extlab_detail', args=[s.pk])).status_code, 200)
