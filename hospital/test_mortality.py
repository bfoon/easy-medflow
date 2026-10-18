"""Mortality: recording a death archives the patient; the WHO certificate rules; the mortuary and release; undoing an
error; autopsy; the M&M review; anonymised study cases in the library; and every page renders."""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.http import QueryDict
from django.test import RequestFactory
from django.utils import timezone

from . import mortality as MT
from . import programmes as P
from .models import (Admission, Autopsy, Bed, DeathRecord, Encounter, LabOrder, LabRequest, LabTest, Patient, Prescription, QueueTicket,
                     StudyCase, Ward)
from .models_programmes import Enrolment, ProgrammeMessage, ProgrammeVisit
from .tests import Base


def form(**kw):
    """Form values as the browser posts them (checkboxes 'on')."""
    q = QueryDict(mutable=True)
    for k, v in kw.items():
        if isinstance(v, list):
            q.setlist(k, v)
        else:
            q[k] = v
    return q


def when(minutes_ago=30):
    return timezone.localtime(timezone.now() - timedelta(minutes=minutes_ago)).strftime('%Y-%m-%dT%H:%M')


VERIFIED = dict(check_no_pulse='on', check_no_breath='on', check_five_minutes='on', check_no_heart_sounds='on')
GOOD_CHAIN = dict(cause_a='Cerebral oedema', interval_a='1 day', cause_b='Cerebral malaria', interval_b='4 days', manner='natural', maternal='no')


class MortalityBase(Base):
    def setUp(self):
        self.doc, self.nurse, self.lab = self.users['doctor'], self.users['nurse'], self.users['lab']
        self.patient.phone, self.patient.emergency_contact = '+220 341 5919', 'Lamin Jallow +220 777 1234'
        self.patient.save()

    def die(self, patient=None, **extra):
        return MT.record_death(patient or self.patient, self.nurse, form(died_at=when(), place='ward', **VERIFIED, **extra))

    def certified(self, **extra):
        d, _ = self.die()
        MT.certify(d, self.doc, form(**{**GOOD_CHAIN, **extra}))
        d.refresh_from_db()
        return d


class ArchivingTests(MortalityBase):
    def test_recording_a_death_archives_everything_that_was_open(self):
        enc = self.encounter()
        ward = Ward.objects.create(name='Mortality test ward')
        bed = Bed.objects.create(ward=ward, code='MT-1', state='occupied')
        Admission.objects.create(encounter=enc, bed=bed)
        QueueTicket.objects.create(patient=self.patient, encounter=enc, department=self.dept)
        test = LabTest.objects.first() or LabTest.objects.create(code='MT', name='Malaria RDT')
        req = LabRequest.objects.create(encounter=enc, requested_by=self.doc)
        LabOrder.objects.create(encounter=enc, request=req, test=test)
        Prescription.objects.create(encounter=enc, state='signed')
        prog = P.create_from_template('hypertension', self.doc)
        en = P.enrol(prog, self.patient, self.doc)
        ProgrammeMessage.objects.create(enrolment=en, kind='reminder', channel='sms', to='+2203415919', text='Your visit is tomorrow')

        d, summary = self.die()

        self.patient.refresh_from_db()
        self.assertIsNotNone(self.patient.deceased_at)
        enc.refresh_from_db()
        self.assertEqual((enc.status, enc.outcome), ('completed', 'died'))
        self.assertIsNotNone(Admission.objects.get(encounter=enc).discharged_at)
        self.assertEqual(Bed.objects.get(pk=bed.pk).state, 'cleaning')
        self.assertEqual(QueueTicket.objects.get().status, 'cancelled')
        self.assertEqual(LabOrder.objects.get().status, 'cancelled')
        self.assertEqual(Prescription.objects.get().state, 'cancelled')
        self.assertEqual(Enrolment.objects.get(pk=en.pk).status, 'died')
        self.assertFalse(ProgrammeVisit.objects.filter(enrolment=en, status__in=['scheduled', 'reminded']).exists())
        self.assertEqual(ProgrammeMessage.objects.get().status, 'skipped')       # no reminder SMS to a grieving family
        self.assertEqual(summary['reminders stopped'], 1)
        self.assertTrue(d.archive_log)
        self.assertEqual(d.admission.bed, bed)
        self.assertEqual(Encounter.objects.filter(patient=self.patient).count(), 1)   # nothing deleted

    def test_verification_time_and_duplicates_are_checked(self):
        with self.assertRaises(ValidationError):
            MT.record_death(self.patient, self.nurse, form(died_at=when(), place='ward'))                    # no verification
        future = timezone.localtime(timezone.now() + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M')
        with self.assertRaises(ValidationError):
            MT.record_death(self.patient, self.nurse, form(died_at=future, place='ward', **VERIFIED))
        MT.record_death(self.patient, self.nurse, form(died_at=when(), place='community'))                    # reported death: allowed
        with self.assertRaises(ValidationError):
            self.die()

    def test_deceased_leave_active_lists_and_cannot_be_checked_in(self):
        self.die()
        c = self.as_('reception')
        self.assertNotContains(c.get('/patients/'), 'Awa Jallow')
        self.assertContains(self.as_('doctor').get('/mortality/archive/'), 'Awa Jallow')
        self.as_('reception')
        r = c.post('/checkin/', {'patient': self.patient.pk, 'department': self.dept.pk})
        self.assertEqual(QueueTicket.objects.count(), 0)
        self.assertEqual(r.status_code, 302)
        from .forms import EncounterForm, TicketForm
        self.assertNotIn(self.patient, EncounterForm().fields['patient'].queryset)
        self.assertNotIn(self.patient, TicketForm().fields['patient'].queryset)

    def test_search_hides_deceased_unless_asked(self):
        self.die()
        from .search import search_patients
        self.assertEqual(search_patients(self.doc, q='Jallow')['total'], 0)
        self.assertEqual(search_patients(self.doc, q='Jallow')['archived'], 1)
        self.assertEqual(search_patients(self.doc, q='Jallow', status=['deceased'])['total'], 1)

    def test_reviewers_and_pathology_can_open_deceased_records(self):
        self.die()
        from .access import visible_patient_ids
        rq = RequestFactory().get('/')
        rq.session = {}
        rq.user = self.doc
        self.assertIn(self.patient.pk, visible_patient_ids(rq))


class CertificateTests(MortalityBase):
    def test_who_rules(self):
        d, _ = self.die()
        bad = [dict(cause_a='', manner='natural', maternal='no'),                                   # Part I(a) required
               dict(cause_a='Cardiac arrest', manner='natural', maternal='no'),                     # mode of dying only
               dict(cause_a='Sepsis', cause_c='Pneumonia', manner='natural', maternal='no'),         # gap
               dict(cause_a='Head injury', manner='accident', maternal='no'),                       # not reported to police
               dict(cause_a='Sepsis', manner='natural')]                                            # woman 36: pregnancy question
        for b in bad:
            with self.assertRaises(ValidationError, msg=b):
                MT.certify(d, self.doc, form(**b))
        MT.certify(d, self.doc, form(cause_a='Cardiac arrest', cause_b='Myocardial infarction', manner='natural', maternal='no'))  # fine with a cause beneath

    def test_signed_certificate_is_sealed_and_prepares_a_study_case(self):
        d = self.certified()
        self.assertEqual(d.status, 'certified')
        self.assertEqual(d.underlying_cause, 'Cerebral malaria')
        self.assertEqual(MT.certificate_hash(d), d.content_hash)
        sc = StudyCase.objects.get(death=d)
        self.assertEqual((sc.status, sc.slug), ('draft', 'malaria'))
        DeathRecord.objects.filter(pk=d.pk).update(cause_b='Typhoid')                                # tampering breaks the seal
        r = self.client.get(f'/deaths/verify/{d.verify_token}/')
        self.assertContains(r, 'Content mismatch')
        self.assertNotContains(r, 'Typhoid')


class BodyTests(MortalityBase):
    def test_mortuary_and_release_rules(self):
        d, _ = self.die()
        MT.move_body(d, self.nurse, 'mortuary', form(mortuary_slot='M-01'))
        other, _ = self.die(Patient.objects.create(first_name='Musa', last_name='Bah', dob='1950-02-02', sex='M'))
        with self.assertRaises(ValidationError):
            MT.move_body(other, self.nurse, 'mortuary', form(mortuary_slot='m-01'))                   # cabinet taken
        release = form(released_to='Lamin Jallow', released_relation='brother', released_id_doc='ID 123', identity_confirmed='on')
        with self.assertRaises(ValidationError):
            MT.move_body(d, self.nurse, 'release', release)                                          # no certificate yet
        MT.certify(d, self.doc, form(**GOOD_CHAIN))
        with self.assertRaises(ValidationError):
            MT.move_body(d, self.nurse, 'release', form(released_to='Lamin'))                        # no ID, no identification
        MT.move_body(d, self.nurse, 'release', release)
        d.refresh_from_db()
        self.assertEqual((d.status, d.body_status), ('released', 'released'))
        with self.assertRaises(ValidationError):
            MT.certify(d, self.doc, form(**GOOD_CHAIN))                                              # locked after release


class RevokeTests(MortalityBase):
    def test_error_is_undone_exactly(self):
        prog = P.create_from_template('hypertension', self.doc)
        en = P.enrol(prog, self.patient, self.doc)
        planned = set(en.visits.filter(status='scheduled').values_list('pk', flat=True))
        msg = ProgrammeMessage.objects.create(enrolment=en, kind='reminder', channel='sms', to='x', text='Visit')
        d, _ = self.die()
        with self.assertRaises(ValidationError):
            MT.revoke(d, self.users['doctor'], 'oops')                                              # needs a real reason
        r = self.as_('doctor').post(f'/deaths/{d.pk}/revoke/', {'reason': 'Wrong patient selected at the bedside'})
        self.assertEqual(r.status_code, 403)                                                         # administrators only
        MT.revoke(d, self.doc, 'Wrong patient selected at the bedside')
        self.patient.refresh_from_db()
        self.assertIsNone(self.patient.deceased_at)
        self.assertEqual(Enrolment.objects.get(pk=en.pk).status, 'active')
        self.assertEqual(set(en.visits.filter(status='scheduled').values_list('pk', flat=True)), planned)
        self.assertEqual(ProgrammeMessage.objects.get(pk=msg.pk).status, 'pending')
        self.assertIsNone(self.patient.death_record)
        self.die()                                                                                   # can be recorded again later


class AutopsyTests(MortalityBase):
    def test_consent_examination_and_signature(self):
        d = self.certified()
        MT.move_body(d, self.nurse, 'mortuary', form(mortuary_slot='M-02'))
        a = MT.request_autopsy(d, self.doc, form(kind='clinical', questions='Was the malaria cerebral? Any other cause?'))
        self.assertIn('Cerebral malaria', a.clinical_diagnosis)
        with self.assertRaises(ValidationError):
            MT.autopsy_action(a, self.lab, 'start', form())                                         # no consent yet
        MT.autopsy_action(a, self.nurse, 'consent', form(consent_name='Lamin Jallow', consent_relation='brother'))
        MT.autopsy_action(a, self.lab, 'start', form())
        d.refresh_from_db()
        self.assertEqual(d.body_status, 'autopsy')
        with self.assertRaises(ValidationError):                                                     # body cannot leave mid-autopsy
            MT.move_body(d, self.nurse, 'release', form(released_to='L', released_id_doc='1', identity_confirmed='on'))
        a.refresh_from_db()
        MT.save_autopsy(a, form(organ_brain_finding='Swollen, petechial haemorrhages', organ_brain_weight_g='1480', organ_brain_abnormal='on'))
        a.refresh_from_db()
        self.assertTrue(a.organs['brain']['abnormal'])
        with self.assertRaises(ValidationError):
            MT.autopsy_action(a, self.lab, 'sign', form())                                          # incomplete
        MT.autopsy_action(a, self.lab, 'sign', form(cause_a='Cerebral oedema', cause_b='Cerebral malaria', anatomical_diagnosis='Cerebral malaria',
                                                   goldman='V', learning_points='Check glucose\nGive artesunate early'))
        a.refresh_from_db(); d.refresh_from_db()
        self.assertEqual(a.status, 'final')
        self.assertEqual(MT.autopsy_hash(a), a.content_hash)
        self.assertEqual(d.body_status, 'mortuary')
        with self.assertRaises(ValidationError):
            MT.save_autopsy(a, form(histology='changed'))                                           # sealed
        MT.autopsy_action(a, self.lab, 'addendum', form(text='Late culture negative'))
        self.assertIn('autopsy', StudyCase.objects.get(death=d).snapshot)

    def test_only_verbal_after_release(self):
        d = self.certified()
        MT.move_body(d, self.nurse, 'release', form(released_to='L J', released_id_doc='ID', identity_confirmed='on'))
        with self.assertRaises(ValidationError):
            MT.request_autopsy(d, self.doc, form(kind='clinical', questions='What happened here?'))
        a = MT.request_autopsy(d, self.doc, form(kind='verbal', questions='Course of the illness at home'))
        MT.autopsy_action(a, self.lab, 'start', form())                                             # interview: no body consent step


class StudyCaseTests(MortalityBase):
    def test_snapshot_is_anonymous(self):
        enc = self.encounter()
        enc.symptoms = 'Awa Jallow brought by brother Lamin on 12/03/2026, phone +220 777 1234, MRN ' + self.patient.mrn
        enc.diagnosis = 'Severe malaria'
        enc.save()
        d = self.certified()
        text = str(MT.build_snapshot(d))
        for leak in ('Awa', 'Jallow', 'Lamin', '12/03/2026', '777 1234', self.patient.mrn, '1990'):
            self.assertNotIn(leak, text)
        self.assertIn('[name]', text)

    def test_publication_needs_consent_and_checks(self):
        d = self.certified()
        sc = d.study_case
        checks = {f'chk_{k}': 'on' for k, _ in MT.STUDY_CHECKS}
        with self.assertRaises(ValidationError):
            MT.publish_case(sc, self.doc, form(**checks))                                            # family not asked
        MT.inform_family(d, self.nurse, form(teaching_consent='granted'))
        with self.assertRaises(ValidationError):
            MT.publish_case(sc, self.doc, form())                                                    # checks missing
        with self.assertRaises(ValidationError):
            MT.publish_case(sc, self.doc, form(title='Malaria in Awa', **checks))                    # a name in the title
        MT.publish_case(sc, self.doc, form(teaching_points='Check glucose', **checks))
        sc.refresh_from_db()
        self.assertEqual(sc.status, 'published')
        r = self.as_('nurse').get(f'/library/cases/{sc.code}/')
        self.assertContains(r, 'Cerebral malaria')
        self.assertNotContains(r, 'Jallow')
        self.assertContains(self.client.get('/library/malaria/'), sc.code)
        d.refresh_from_db()
        MT.inform_family(d, self.nurse, form(teaching_consent='declined'))                           # family changes its mind
        sc.refresh_from_db()
        self.assertEqual(sc.status, 'withdrawn')
        self.assertEqual(self.client.get(f'/library/cases/{sc.code}/').status_code, 404)


class ReviewTests(MortalityBase):
    def test_final_review_closes_the_death(self):
        d = self.certified()
        MT.move_body(d, self.nurse, 'release', form(released_to='L J', released_id_doc='ID', identity_confirmed='on'))
        with self.assertRaises(ValidationError):
            MT.save_review(d, self.doc, form(summary='x'), finalise=True)
        MT.save_review(d, self.doc, form(summary='Late presentation of cerebral malaria', preventability='possibly', delays=['seeking', 'receiving'],
                                         factors=['late_presentation', 'lab'], lessons='Triage fever with altered consciousness as emergency',
                                         action_0_text='Glucose meters on every ward', action_0_owner='Matron'), finalise=True)
        d.refresh_from_db()
        self.assertEqual(d.status, 'closed')
        self.assertEqual(d.review.delays, ['seeking', 'receiving'])


class PageTests(MortalityBase):
    def test_every_page_renders(self):
        enc = self.encounter()
        enc.diagnosis = 'Severe malaria'; enc.save()
        doc = self.as_('doctor')
        self.assertContains(doc.get(f'/patients/{self.patient.pk}/'), 'Record death')
        self.assertEqual(doc.get(f'/patients/{self.patient.pk}/death/').status_code, 200)
        r = doc.post(f'/patients/{self.patient.pk}/death/', {'died_at': when(), 'place': 'ward', 'confirm_name': 'wrong', **VERIFIED})
        self.assertFalse(DeathRecord.objects.exists())                                              # name confirmation
        r = doc.post(f'/patients/{self.patient.pk}/death/', {'died_at': when(), 'place': 'ward', 'confirm_name': 'jallow', **VERIFIED})
        d = DeathRecord.objects.get()
        self.assertRedirects(r, f'/deaths/{d.pk}/')
        r = doc.post(f'/deaths/{d.pk}/certificate/', {'cause_a': 'Cardiac arrest', 'manner': 'natural', 'maternal': 'no'})
        self.assertContains(r, 'value="Cardiac arrest"')                                            # form keeps what was typed
        doc.post(f'/deaths/{d.pk}/certificate/', GOOD_CHAIN)
        doc.post(f'/deaths/{d.pk}/autopsy/', {'kind': 'clinical', 'questions': 'Was the malaria cerebral?'})
        a = Autopsy.objects.get()
        doc.post(f'/deaths/{d.pk}/family/', {'informed': 'on', 'nok_name': 'Lamin', 'nok_how': 'in_person', 'teaching_consent': 'policy'})
        pages = ['/mortality/', '/mortality/?tab=mortuary', '/mortality/?tab=learning', '/mortality/archive/', f'/deaths/{d.pk}/',
                 f'/deaths/{d.pk}/certificate/', f'/deaths/{d.pk}/certificate/print/', f'/deaths/{d.pk}/review/', f'/autopsies/{a.pk}/',
                 f'/autopsies/{a.pk}/print/', f'/patients/{self.patient.pk}/', '/library/', '/library/cases/', '/library/malaria/',
                 f'/library/cases/{d.study_case.code}/', '/search/?q=Jallow', '/search/?status=deceased', '/patients/']
        for url in pages:
            self.assertEqual(doc.get(url).status_code, 200, url)
        self.client.logout()
        self.assertContains(self.client.get(f'/deaths/verify/{d.verify_token}/'), 'Genuine')
        lab = self.as_('lab')
        lab.post(f'/autopsies/{a.pk}/consent/', {'consent_name': 'Lamin', 'consent_relation': 'brother'})
        lab.post(f'/autopsies/{a.pk}/start/')
        self.assertContains(lab.get(f'/autopsies/{a.pk}/'), 'Organ by organ')
        self.assertEqual(self.as_('reception').get('/mortality/').status_code, 403)
