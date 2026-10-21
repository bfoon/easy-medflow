"""Wards: details, the live snapshot (NEWS2, observations due, fit), pages, editing with bulk beds, and the handover board."""
from datetime import date, time, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from . import wards as W
from .models import (Admission, Bed, BedsideObservation, Department, Encounter, Notification, Patient, StaffProfile, Ward, WardNote)

PW = 'test-only-Pa55word!'


@override_settings(NOTIFY_EMAIL_SYNC=True)
class WardBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('bootstrap_hospital', verbosity=0)
        U = get_user_model()
        cls.u = {}
        for role in ['nurse', 'doctor', 'reception']:
            user = U.objects.create_user(username=role, password=PW, first_name=role.title(), last_name='Test')
            StaffProfile.objects.create(user=user, role=role)
            cls.u[role] = user
        cls.mw = Ward.objects.get(code='MW')
        cls.gw = Ward.objects.get(code='GW')
        cls.mw.nurse_in_charge = cls.u['nurse']
        cls.mw.save()

    def as_(self, who):
        c = Client()
        c.login(username=who, password=PW)
        return c

    def admit(self, ward, first='Awa', sex='F', dob=date(1990, 1, 1)):
        p = Patient.objects.create(first_name=first, last_name='Jallow', dob=dob, sex=sex)
        e = Encounter.objects.create(patient=p, clinician=self.u['doctor'], department=Department.objects.first(), reason='Fever')
        bed = Bed.objects.filter(ward=ward, state='available').order_by('code').first()
        bed.state = 'occupied'
        bed.save()
        return Admission.objects.create(encounter=e, bed=bed)

    def obs(self, a, minutes_ago=10, **kw):
        values = dict(heart_rate=80, systolic=120, resp_rate=16, spo2=98, temperature_c=37)
        values.update(kw)
        o = BedsideObservation.objects.create(admission=a, recorded_by=self.u['nurse'], **values)
        BedsideObservation.objects.filter(pk=o.pk).update(taken_at=timezone.now() - timedelta(minutes=minutes_ago))
        return o


class SnapshotTests(WardBase):
    def test_seeded_wards_have_details(self):
        self.assertEqual((self.mw.kind, self.mw.sex_policy), ('maternity', 'female'))
        self.assertEqual(Ward.objects.get(code='PW').age_group, 'children')
        self.assertTrue(self.mw.visiting_from)

    def test_news2_drives_acuity_and_observation_timing(self):
        calm = self.admit(self.gw, 'Calm')
        sick = self.admit(self.gw, 'Sick')
        none = self.admit(self.gw, 'New')
        self.obs(calm, minutes_ago=30)                                         # NEWS2 0 → next in 12 h
        self.obs(sick, minutes_ago=90, resp_rate=26, spo2=91, heart_rate=120)  # NEWS2 high → every 15 min: overdue
        rows = {r['p'].first_name: r for r in W.snapshot(self.gw)['rows'] if r['a']}
        self.assertEqual(rows['Calm']['acuity'], 'stable')
        self.assertFalse(rows['Calm']['obs_overdue'])
        self.assertTrue(rows['Calm']['obs_label'].startswith('in 11 h'))
        self.assertEqual(rows['Sick']['acuity'], 'critical')
        self.assertTrue(rows['Sick']['obs_overdue'])
        self.assertEqual(rows['New']['acuity'], 'unknown')
        snap = W.snapshot(self.gw)
        self.assertEqual(snap['attention'][0]['p'].first_name, 'Sick')       # most urgent first
        self.assertEqual(snap['stats']['acuity']['critical'], 1)

    def test_patient_who_does_not_fit_is_flagged(self):
        a = self.admit(self.mw, 'Omar', sex='M')
        child = self.admit(self.gw, 'Lamin', dob=timezone.localdate() - timedelta(days=365 * 8))
        rows = {r['p'].first_name: r for r in W.snapshot(self.mw)['rows'] + W.snapshot(self.gw)['rows'] if r['a']}
        self.assertIn('Man on a women-only ward', rows['Omar']['misfit'])
        self.assertTrue(any('Child' in m for m in rows['Lamin']['misfit']))
        self.assertTrue(a and child)

    def test_slow_cleaning_flagged(self):
        b = Bed.objects.filter(ward=self.gw).first()
        Bed.objects.filter(pk=b.pk).update(state='cleaning', updated_at=timezone.now() - timedelta(hours=3))
        att = W.snapshot(self.gw)['attention']
        self.assertTrue(any('Cleaning for 3 h' in x['text'] for x in att))

    def test_visiting_states(self):
        w = Ward(visiting_from=time(16), visiting_to=time(18))
        at = lambda h, m=0: timezone.localtime().replace(hour=h, minute=m)
        self.assertEqual(W.visiting(w, at(17))['state'], 'open')
        self.assertEqual(W.visiting(w, at(15, 0))['state'], 'soon')
        self.assertEqual(W.visiting(w, at(9))['state'], 'closed')
        self.assertEqual(W.visiting(Ward())['state'], 'none')

    def test_existing_wards_described_by_migration(self):
        import importlib
        from django.apps import apps
        mig = importlib.import_module('hospital.migrations.0034_ward_details')
        w = Ward.objects.create(name='Female Surgical Ward')
        Bed.objects.create(ward=w, code='FSW-01')
        mig.describe_existing(apps, None)
        w.refresh_from_db()
        self.assertEqual((w.kind, w.sex_policy, w.age_group, w.code), ('surgical', 'female', 'adult', 'FSW'))


class PageTests(WardBase):
    def test_overview_and_ward_page(self):
        a = self.admit(self.mw)
        self.obs(a, resp_rate=26)
        c = self.as_('doctor')
        r = c.get('/wards/')
        self.assertContains(r, 'Maternity Ward')
        self.assertContains(r, 'Women only')
        r = c.get(f'/wards/{self.mw.pk}/')
        self.assertContains(r, 'Awa Jallow')
        self.assertContains(r, 'Nurse Test')                                   # nurse in charge
        self.assertContains(r, 'Not set')                                      # no lead clinician (never "System")
        self.assertNotContains(r, 'System')
        self.assertContains(r, 'news n-')

    def test_station_screen_shows_initials_only(self):
        self.admit(self.mw)
        r = self.as_('nurse').get(f'/wards/{self.mw.pk}/?screen=1')
        self.assertContains(r, '>AJ<', html=False)
        self.assertNotContains(r, 'Jallow')
        self.assertContains(r, 'http-equiv="refresh"', html=False)

    def test_handover_sheet(self):
        self.admit(self.mw)
        WardNote.objects.create(ward=self.mw, text='Theatre 08:00', author=self.u['nurse'])
        r = self.as_('nurse').get(f'/wards/{self.mw.pk}/handover/')
        self.assertContains(r, 'Shift handover')
        self.assertContains(r, 'Awa Jallow')
        self.assertContains(r, 'Theatre 08:00')

    def test_bed_ready_returns_to_ward(self):
        b = Bed.objects.filter(ward=self.mw).first()
        b.state = 'cleaning'
        b.save()
        r = self.as_('nurse').post(f'/beds/{b.pk}/ready/', {'next': f'/wards/{self.mw.pk}/'})
        self.assertRedirects(r, f'/wards/{self.mw.pk}/', fetch_redirect_response=False)
        r = self.as_('nurse').post(f'/beds/{b.pk}/ready/', {'next': 'https://evil.example/'})
        self.assertEqual(r.status_code, 400)                                   # bed already ready; never redirects off-site


class EditTests(WardBase):
    def test_create_ward_with_beds(self):
        r = self.as_('nurse').post('/wards/new/', {'name': 'Female Medical Ward', 'code': 'fmw', 'kind': 'medical', 'sex_policy': 'female',
                                                    'age_group': 'adult', 'visiting_from': '16:00', 'visiting_to': '18:00', 'add_beds': '3', 'bed_kind': 'general'})
        w = Ward.objects.get(name='Female Medical Ward')
        self.assertRedirects(r, f'/wards/{w.pk}/', fetch_redirect_response=False)
        self.assertEqual(sorted(w.bed_set.values_list('code', flat=True)), ['FMW-01', 'FMW-02', 'FMW-03'])
        self.as_('nurse').post(f'/wards/{w.pk}/edit/', {'name': w.name, 'code': 'FMW', 'kind': 'medical', 'add_beds': '2', 'bed_kind': 'general'})
        self.assertIn('FMW-05', w.bed_set.values_list('code', flat=True))     # continues numbering

    def test_validation_and_closing(self):
        c = self.as_('nurse')
        self.assertContains(c.post('/wards/new/', {'name': 'maternity ward'}), 'Another ward already has this name')
        self.assertContains(c.post('/wards/new/', {'name': 'X', 'visiting_from': '16:00'}), 'Give both the start and the end')
        c.post(f'/wards/{self.gw.pk}/edit/', {'name': self.gw.name, 'kind': 'general', 'closed': '1'})
        self.gw.refresh_from_db()
        self.assertFalse(self.gw.active)
        self.assertNotContains(c.get('/wards/'), '>General Ward<', html=False)
        c.post(f'/wards/{self.gw.pk}/edit/', {'name': self.gw.name, 'kind': 'general'})
        self.gw.refresh_from_db()
        self.assertTrue(self.gw.active)

    def test_reception_cannot_edit(self):
        self.assertEqual(self.as_('reception').get('/wards/new/').status_code, 403)


class HandoverBoardTests(WardBase):
    def test_note_and_alert(self):
        a = self.admit(self.mw)
        c = self.as_('doctor')
        c.post(f'/wards/{self.mw.pk}/notes/', {'kind': 'handover', 'text': 'Nil by mouth from midnight', 'patient': a.encounter.patient_id})
        n = WardNote.objects.get()
        self.assertEqual((n.patient, n.shift in ('day', 'night')), (a.encounter.patient, True))
        c.post(f'/wards/{self.mw.pk}/notes/', {'kind': 'alert', 'text': 'Oxygen supply low'})
        self.assertTrue(Notification.objects.filter(user=self.u['nurse'], kind='ward_alert').exists())
        r = c.get(f'/wards/{self.mw.pk}/')
        self.assertContains(r, 'wd-alert')
        alert = WardNote.objects.get(kind='alert')
        c.post(f'/wards/{self.mw.pk}/notes/{alert.pk}/resolve/')
        alert.refresh_from_db()
        self.assertIsNotNone(alert.resolved_at)
        self.assertNotContains(c.get(f'/wards/{self.mw.pk}/'), 'class="wd-alert"', html=False)

    def test_patient_must_be_on_this_ward(self):
        other = self.admit(self.gw, 'Other')
        self.as_('nurse').post(f'/wards/{self.mw.pk}/notes/', {'text': 'x', 'patient': other.encounter.patient_id})
        self.assertIsNone(WardNote.objects.get().patient)

    def test_reception_cannot_write(self):
        self.assertEqual(self.as_('reception').post(f'/wards/{self.mw.pk}/notes/', {'text': 'x'}).status_code, 403)
