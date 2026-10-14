"""Access & roles: capabilities, groups, patient scope, emergency access, pharmacy rights, the library and Dr. Flow."""
import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from . import access as A
from . import library as L
from .models import (AccessGroup, Admission, AuditEvent, Bed, Encounter, LabOrder, LabTest, Notification, Patient, Prescription,
                     PrescriptionItem, SenseExam, StaffProfile, StockBatch, SurgicalCase, ProcedureType)
from .tests import PW, Base


class AccessBase(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        U = get_user_model()
        u = U.objects.create_user(username='admin', password=PW)
        StaffProfile.objects.create(user=u, role='admin')
        cls.users['admin'] = u
        cls.other = Patient.objects.create(first_name='Musa', last_name='Bah', dob=date(1980, 5, 5), sex='M')

    def group(self, name, caps, *members):
        g = AccessGroup.objects.create(name=name, capabilities=['all', *caps])
        g.members.set([self.users[m] for m in members])
        return g


class CapabilityTests(AccessBase):
    def test_without_groups_roles_keep_their_standard_access(self):
        doc, ph = self.users['doctor'], self.users['pharmacy']
        self.assertTrue(A.has(doc, 'clinical'))
        self.assertTrue(A.has(doc, 'drflow'))
        self.assertFalse(A.has(doc, 'all_patients'))           # doctors see patients in their care
        self.assertTrue(A.has(ph, 'pharmacy_stock'))
        self.assertFalse(A.has(ph, 'patient_records'))         # pharmacists do not open charts
        self.assertTrue(A.has(self.users['reception'], 'all_patients'))
        self.assertTrue(all(A.has(self.users['admin'], c) for c in A.CAP_KEYS))

    def test_a_group_replaces_the_role_defaults(self):
        self.group('Pharmacy assistants', ['pharmacy_view'], 'pharmacy')
        ph = get_user_model().objects.get(username='pharmacy')
        self.assertEqual(A.caps(ph), {'all', 'pharmacy_view'})
        c = self.as_('pharmacy')
        r = c.get('/pharmacy/')
        self.assertContains(r, 'You can see which medicines are available')
        self.assertNotContains(r, 'ready to dispense')               # no prescription lanes, so no patient names
        batch = StockBatch.objects.first()
        self.assertEqual(c.post(f'/pharmacy/batches/{batch.pk}/quarantine/').status_code, 403)    # cannot update stock
        e = self.encounter()
        p = Prescription.objects.create(encounter=e, signed_by=self.users['doctor'], state='signed')
        PrescriptionItem.objects.create(prescription=p, medication=self.med, dose='500 mg', frequency='TDS', duration_days=5, quantity=15)
        self.assertEqual(c.post(f'/prescriptions/{p.pk}/dispense/').status_code, 403)               # cannot dispense
        self.assertEqual(c.post(f'/prescriptions/items/{p.items.first().pk}/unavailable/').status_code, 403)   # cannot revise issuance

    def test_pharmacist_can_dispense_without_seeing_charts(self):
        e = self.encounter()
        c = self.as_('pharmacy')
        self.assertEqual(c.get(f'/patients/{self.patient.pk}/').status_code, 403)
        p = Prescription.objects.create(encounter=e, signed_by=self.users['doctor'], state='signed')
        self.assertEqual(c.get(f'/prescriptions/{p.pk}/').status_code, 200)   # the prescription is part of the job

    def test_operation_note_follows_the_capability(self):
        e = self.encounter()
        case = SurgicalCase.objects.create(encounter=e, procedure_type=ProcedureType.objects.get(code='circumcision'), status='operating')
        self.assertEqual(self.as_('nurse').post(f'/theatre/cases/{case.pk}/note/', {'procedure_performed': 'x'}).status_code, 403)
        self.client.logout()
        self.group('Theatre nurses', ['clinical', 'patient_records', 'theatre', 'theatre_view', 'operation_note'], 'nurse')
        self.assertEqual(self.as_('nurse').post(f'/theatre/cases/{case.pk}/note/', {'procedure_performed': 'Circumcision'}).status_code, 302)


class PatientScopeTests(AccessBase):
    def test_doctor_sees_visiting_patients_only(self):
        c = self.as_('doctor')
        r = c.get(f'/patients/{self.patient.pk}/')
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, 'Emergency access', status_code=403)
        self.assertEqual(c.get(f'/patients/{self.patient.pk}/labs/').status_code, 403)
        e = self.encounter()
        self.assertEqual(c.get(f'/patients/{self.patient.pk}/').status_code, 200)
        self.assertEqual(c.get(f'/encounters/{e.pk}/eyes-ears/').status_code, 200)
        # lists and search only show patients in care
        page = c.get('/patients/').content.decode()
        self.assertIn('Jallow', page); self.assertNotIn('Musa Bah', page)
        names = [x['name'] for x in c.get('/api/search/?q=Bah').json()['results']]
        self.assertEqual(names, [])
        self.assertEqual(self.as_('reception').get(f'/patients/{self.other.pk}/').status_code, 200)   # reception sees everyone

    def test_admitted_patients_and_the_grace_period(self):
        e = Encounter.objects.create(patient=self.other, department=self.dept, reason='Fever')
        Admission.objects.create(encounter=e, bed=Bed.objects.filter(state='available').first())
        e.status = 'completed'; e.save()
        self.assertEqual(self.as_('nurse').get(f'/patients/{self.other.pk}/').status_code, 200)       # still admitted
        Admission.objects.filter(encounter=e).update(discharged_at=timezone.now() - timedelta(hours=2))
        Encounter.objects.filter(pk=e.pk).update(completed_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(self.client.get(f'/patients/{self.other.pk}/').status_code, 200)             # within 12 hours
        Admission.objects.filter(encounter=e).update(discharged_at=timezone.now() - timedelta(hours=20))
        Encounter.objects.filter(pk=e.pk).update(completed_at=timezone.now() - timedelta(hours=20))
        self.assertEqual(self.client.get(f'/patients/{self.other.pk}/').status_code, 403)

    def test_emergency_access_is_reasoned_logged_and_reported(self):
        c = self.as_('doctor')
        url = f'/access/emergency/{self.other.pk}/'
        c.post(url, {'reason': 'need'})
        self.assertEqual(c.get(f'/patients/{self.other.pk}/').status_code, 403)                       # too short
        r = c.post(url, {'reason': 'Brought in unconscious, need allergies', 'next': f'/patients/{self.other.pk}/'})
        self.assertRedirects(r, f'/patients/{self.other.pk}/')
        ev = AuditEvent.objects.get(action='break_glass')
        self.assertEqual((ev.target, ev.details['reason']), (f'patient:{self.other.pk}', 'Brought in unconscious, need allergies'))
        self.assertTrue(Notification.objects.filter(user=self.users['admin'], kind='access').exists())
        self.assertEqual(c.post(url, {'reason': 'x' * 20, 'next': 'https://evil.example/'}).url, f'/patients/{self.other.pk}/')   # no open redirect
        c.logout()
        self.group('Students', ['clinical', 'patient_records'], 'nurse')                             # no break_glass
        self.assertEqual(self.as_('nurse').post(url, {'reason': 'x' * 20}).status_code, 403)

    def test_partner_portal_unaffected(self):
        self.assertIsNone(A.PatientScopeMiddleware(lambda r: None).process_view(type('R', (), {'user': type('U', (), {'is_authenticated': False})()})(), None, (), {}))


class AccessAdminTests(AccessBase):
    def test_only_access_admins_manage(self):
        self.assertEqual(self.as_('doctor').get('/access/').status_code, 403)
        self.client.logout()
        c = self.as_('admin')
        self.assertContains(c.get('/access/'), 'Create the standard groups')

    def test_standard_groups_groups_and_members(self):
        c = self.as_('admin')
        c.post('/access/groups/standard/')
        self.assertEqual(AccessGroup.objects.count(), len(A.STANDARD_GROUPS))
        view_only = AccessGroup.objects.get(name='Pharmacy assistants (view only)')
        self.assertNotIn('pharmacy_stock', view_only.capabilities)
        docs = AccessGroup.objects.get(name='Doctors')
        self.assertIn('clinical', docs.capabilities); self.assertNotIn('all_patients', docs.capabilities)
        # edit a group: unknown keys are dropped, 'all' is always kept
        c.post(f'/access/groups/{docs.pk}/', {'name': 'Doctors', 'cap': ['clinical', 'patient_records', 'all_patients', 'hack']})
        docs.refresh_from_db()
        self.assertEqual(sorted(docs.capabilities), ['all', 'all_patients', 'clinical', 'patient_records'])
        # allocate the doctor; their access is now exactly the group's
        doc = self.users['doctor']
        c.post(f'/access/staff/{doc.pk}/', {'role': 'doctor', 'active': 'on', 'groups': [docs.pk]})
        self.assertEqual(list(doc.access_groups.all()), [docs])
        self.client.logout()
        self.assertEqual(self.as_('doctor').get(f'/patients/{self.other.pk}/').status_code, 200)    # all_patients granted
        self.assertEqual(self.client.get('/library/').status_code, 403)                              # library not in the group
        self.assertTrue(AuditEvent.objects.filter(action='access_member', target=f'user:{doc.pk}').exists())

    def test_admin_cannot_lock_themselves_out(self):
        c = self.as_('admin')
        g = self.group('Clerks', ['reception'])
        r = c.post(f'/access/staff/{self.users["admin"].pk}/', {'role': 'admin', 'groups': [g.pk]}, follow=True)
        self.assertContains(r, 'cannot remove your own access')
        self.assertFalse(self.users['admin'].access_groups.exists())

    def test_only_superusers_change_superusers(self):
        su = get_user_model().objects.create_superuser('root', 'r@x.org', PW)
        self.assertEqual(self.as_('admin').post(f'/access/staff/{su.pk}/', {'groups': []}).status_code, 403)


class LibraryAndDrFlowTests(AccessBase):
    def test_curated_diseases_use_real_categories(self):
        from .categories import INFO
        self.assertEqual([k for k, v in L.DISEASES.items() if v[2] not in INFO], [])

    def test_matching(self):
        self.assertEqual(L.match('Right cataract; diabetic retinopathy')[0], 'cataract')
        self.assertEqual(L.match('Hypertensive retinopathy')[0], 'hypertension')
        self.assertEqual(L.match('Constitutional delay')[0], 'dx-constitutional-delay')
        self.assertEqual(L.match('Sickle cell anaemia crisis')[0], 'sickle')

    def test_library_is_anonymous_and_hides_small_numbers(self):
        for i in range(2):
            Encounter.objects.create(patient=self.patient, department=self.dept, reason='Fever', diagnosis='Severe malaria', outcome='resolved')
        c = self.as_('doctor')
        self.assertContains(c.get('/library/?q=malaria'), 'Malaria')
        self.assertContains(c.get('/library/?cat=infectious'), 'Malaria')
        r = c.get('/library/malaria/')
        self.assertContains(r, 'Figures appear from 3 cases')
        Encounter.objects.create(patient=self.other, department=self.dept, reason='Fever', diagnosis='Malaria, uncomplicated', outcome='improved')
        r = c.get('/library/malaria/').content.decode()
        self.assertIn('Anonymous case log', r)
        for secret in ('Jallow', 'Musa', self.patient.mrn, self.other.mrn):
            self.assertNotIn(secret, r)
        self.assertEqual(c.get('/library/dx-nothing-here/').status_code, 404)
        self.assertEqual(self.as_('reception').get('/library/').status_code, 403)

    def test_drflow_for_pharmacists_but_not_for_other_patients(self):
        e_other = Encounter.objects.create(patient=self.other, department=self.dept, reason='Cough', status='completed', completed_at=timezone.now() - timedelta(days=3))
        j = self.as_('pharmacy').post('/drflow/ask/', {'kind': 'med', 'id': self.med.pk, 'encounter': e_other.pk}).json()
        self.assertIn('In the pharmacy', [f['label'] for f in j['facts']])
        self.assertEqual(j['warnings'], [])                       # the patient outside their care is ignored
        self.assertFalse(AuditEvent.objects.filter(action='drflow_ask', details__personal=True).exists())
        self.assertEqual(self.as_('reception').post('/drflow/ask/', {'kind': 'med', 'id': self.med.pk}).status_code, 403)

    def test_drflow_and_buttons_on_pages(self):
        e = self.encounter()
        c = self.as_('doctor')
        self.assertContains(c.get(f'/encounters/{e.pk}/eyes-ears/'), 'data-drflow-page')
        chart = c.get(f'/patients/{self.patient.pk}/').content.decode()
        self.assertNotIn('bi-eye"></i>Eyes &amp; ears</a>', chart)            # no examination yet
        c.post(f'/encounters/{e.pk}/eyes-ears/', json.dumps({'exam': {'eyes': {'right': {'examined': True, 'va': '6/6'}}}}), content_type='application/json')
        case = SurgicalCase.objects.create(encounter=e, procedure_type=ProcedureType.objects.get(code='cataract'), side='right')
        chart = c.get(f'/patients/{self.patient.pk}/').content.decode()
        self.assertIn('bi-eye"></i>Eyes &amp; ears</a>', chart)
        self.assertIn(f'/theatre/cases/{case.pk}/', chart)
        labs = c.get(f'/patients/{self.patient.pk}/labs/').content.decode()
        self.assertIn('Eyes &amp; ears', labs); self.assertIn(f'/theatre/cases/{case.pk}/', labs)
        self.assertContains(c.get(f'/theatre/cases/{case.pk}/'), 'data-drflow-page')
        self.client.logout()
        self.assertContains(self.as_('pharmacy').get('/pharmacy/'), 'data-drflow-page')
