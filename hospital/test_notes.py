"""Editable clinical and nursing notes, their history, and Dr. Flow's help with them (notes_ai.py, notes_views.py)."""
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings

from . import notes_ai as N
from .models import ClinicalNoteAsk, Encounter, NoteRevision, StaffProfile
from .tests import PW, Base

AI_ON = override_settings(CLINICAL_AI_ENABLED=True, CLINICAL_AI_PROVIDER='endpoint', CLINICAL_AI_ENDPOINT='https://ai.example.org/notes')
CLINICAL = {'section': 'clinical', 'symptoms': 'Fever for 3 days', 'assessment': 'Looks unwell', 'diagnosis': 'Malaria', 'plan': 'RDT, review'}


class NotesBase(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        U = get_user_model()
        for name, role in [('doctor2', 'doctor'), ('nurse2', 'nurse')]:
            u = U.objects.create_user(username=name, password=PW, first_name=name.title())
            StaffProfile.objects.create(user=u, role=role)
            cls.users[name] = u
        U.objects.create_user(username='root', password=PW, is_superuser=True, is_staff=True)
        cls.users['nurse'].first_name, cls.users['nurse'].last_name = 'Isatou', 'Sanneh'
        cls.users['nurse'].save()

    def setUp(self):
        self.e = self.encounter()

    def save(self, who, data, pk=None):
        return self.as_(who).post(f'/encounters/{pk or self.e.pk}/notes/', data)


class WhoMayEditTests(NotesBase):
    def test_attending_doctor_edits_and_the_change_is_kept(self):
        r = self.save('doctor', {**CLINICAL, 'ai_assisted': '1'})
        self.assertEqual(r.status_code, 302)
        self.e.refresh_from_db()
        self.assertEqual((self.e.symptoms, self.e.diagnosis, self.e.plan), ('Fever for 3 days', 'Malaria', 'RDT, review'))
        rev = NoteRevision.objects.get(encounter=self.e)
        self.assertEqual(rev.section, 'clinical')
        self.assertEqual(rev.edited_by, self.users['doctor'])
        self.assertTrue(rev.ai_assisted)
        self.assertEqual(rev.before['diagnosis'], '')
        self.assertEqual(rev.after['diagnosis'], 'Malaria')
        self.assertIn(('Diagnosis', '', 'Malaria'), rev.changed)
        # saving the same text again records nothing new
        self.save('doctor', CLINICAL)
        self.assertEqual(NoteRevision.objects.filter(encounter=self.e).count(), 1)

    def test_another_doctor_cannot_change_the_notes(self):
        page = self.as_('doctor2').get(f'/encounters/{self.e.pk}/').content.decode()
        self.assertNotIn('data-notes-edit="clinical"', page)
        self.assertNotIn('notes-form', page)
        self.assertEqual(self.save('doctor2', CLINICAL).status_code, 403)
        self.assertEqual(self.save('doctor2', {'section': 'nursing', 'nursing_notes': 'x'}).status_code, 403)
        self.e.refresh_from_db()
        self.assertEqual((self.e.symptoms, self.e.nursing_notes), ('', ''))

    def test_the_first_doctor_to_write_becomes_the_attending_doctor(self):
        self.e.clinician = None
        self.e.save()
        self.assertEqual(self.save('doctor2', CLINICAL).status_code, 302)
        self.e.refresh_from_db()
        self.assertEqual(self.e.clinician, self.users['doctor2'])
        self.assertEqual(self.save('doctor', CLINICAL | {'plan': 'changed'}).status_code, 403)

    def test_superuser_can_do_what_any_doctor_can(self):
        self.client.login(username='root', password=PW)
        page = self.client.get(f'/encounters/{self.e.pk}/').content.decode()
        self.assertIn('data-notes-edit="clinical"', page)
        self.assertIn('name="attending_nurse"', page)
        self.assertEqual(self.client.post(f'/encounters/{self.e.pk}/notes/', CLINICAL).status_code, 302)
        self.client.post(f'/encounters/{self.e.pk}/notes/', {'section': 'nursing', 'nursing_notes': 'Comfortable', 'attending_nurse': self.users['nurse2'].pk})
        self.e.refresh_from_db()
        self.assertEqual((self.e.diagnosis, self.e.nursing_notes, self.e.attending_nurse), ('Malaria', 'Comfortable', self.users['nurse2']))
        self.assertEqual(self.e.clinician, self.users['doctor'])          # a superuser editing does not take over the visit

    def test_nurse_writes_the_nursing_notes_and_becomes_the_attending_nurse(self):
        page = self.as_('nurse').get(f'/encounters/{self.e.pk}/').content.decode()
        self.assertIn('data-notes-edit="nursing"', page)
        self.assertNotIn('data-notes-edit="clinical"', page)
        self.assertNotIn('name="attending_nurse"', page)                 # a nurse does not pick the nurse
        self.assertEqual(self.save('nurse', CLINICAL).status_code, 403)
        self.assertEqual(self.save('nurse', {'section': 'nursing', 'nursing_notes': 'T 38.6, fluids given'}).status_code, 302)
        self.e.refresh_from_db()
        self.assertEqual((self.e.nursing_notes, self.e.attending_nurse), ('T 38.6, fluids given', self.users['nurse']))
        self.assertIn('Isatou Sanneh', self.as_('doctor').get(f'/encounters/{self.e.pk}/').content.decode())
        self.assertEqual(self.save('nurse2', {'section': 'nursing', 'nursing_notes': 'x'}).status_code, 403)   # another nurse now
        self.assertEqual(self.save('doctor', {'section': 'nursing', 'nursing_notes': 'Doctor added a line'}).status_code, 302)

    def test_only_a_nurse_can_be_chosen_as_attending_nurse(self):
        self.save('doctor', {'section': 'nursing', 'nursing_notes': '', 'attending_nurse': self.users['doctor2'].pk})
        self.e.refresh_from_db()
        self.assertIsNone(self.e.attending_nurse)
        self.save('doctor', {'section': 'nursing', 'nursing_notes': '', 'attending_nurse': self.users['nurse2'].pk})
        self.e.refresh_from_db()
        self.assertEqual(self.e.attending_nurse, self.users['nurse2'])

    def test_a_closed_visit_is_read_only(self):
        self.save('doctor', CLINICAL)
        Encounter.objects.filter(pk=self.e.pk).update(status='completed')
        self.encounter()                       # a new open visit keeps the patient within the doctor's access
        page = self.as_('doctor').get(f'/encounters/{self.e.pk}/').content.decode()
        self.assertNotIn('notes-form', page)
        self.assertIn('Visit closed', page)
        self.save('doctor', CLINICAL | {'diagnosis': 'Changed later'})
        self.client.login(username='root', password=PW)
        self.client.post(f'/encounters/{self.e.pk}/notes/', CLINICAL | {'diagnosis': 'Changed by root'})
        self.e.refresh_from_db()
        self.assertEqual(self.e.diagnosis, 'Malaria')
        self.assertEqual(NoteRevision.objects.filter(encounter=self.e).count(), 1)

    def test_staff_without_clinical_access_cannot_edit(self):
        self.assertEqual(self.save('reception', CLINICAL).status_code, 403)

    def test_patients_outside_the_doctors_access_are_blocked(self):
        Encounter.objects.filter(pk=self.e.pk).update(status='completed')      # no open visit: records closed to the doctor
        self.assertEqual(self.as_('doctor').get(f'/encounters/{self.e.pk}/notes/ai/context/').status_code, 403)
        self.assertEqual(self.save('doctor', CLINICAL).status_code, 403)

    def test_history_is_shown_on_the_visit(self):
        self.save('doctor', CLINICAL)
        self.save('doctor', CLINICAL | {'diagnosis': 'Severe malaria'})
        page = self.as_('doctor').get(f'/encounters/{self.e.pk}/').content.decode()
        self.assertIn('Change history', page)
        self.assertIn('Severe malaria', page)


class DeidentifyTests(NotesBase):
    def setUp(self):
        super().setUp()
        p = self.patient
        p.phone, p.emergency_contact = '+220 7712345', 'Lamin Touray (brother) 3301234'
        p.save()
        self.users['doctor2'].first_name, self.users['doctor2'].last_name = 'Fatou', 'Ceesay'
        self.users['doctor2'].save()
        N._staff_cache['at'] = None
        self.text = (f'Awa Jallow, {p.mrn}, phone +220 7712345. awa says her brother Lamin brought her. Mrs Binta Sowe gave paracetamol. '
                     'Seen with Dr Ceesay and Fatou. BP 120/80, 2 400 000 IU benzathine.')
        self.secrets = ['Awa', 'Jallow', p.mrn, '7712345', 'Lamin', 'Binta', 'Sowe', 'Ceesay', 'Fatou']

    def test_deidentify_removes_the_patient_and_other_people(self):
        t = N.deidentify(self.text, self.patient)
        for s in self.secrets:
            self.assertNotIn(s, t)
        self.assertIn('BP 120/80', t)
        self.assertIn('2 400 000 IU', t)                                  # doses are not mistaken for phone numbers

    def test_numbered_placeholders_put_every_detail_back(self):
        m = {}
        t = N.pseudonymise(self.text, self.patient, m)
        for s in self.secrets:
            self.assertNotIn(s, t)
        self.assertEqual(N.restore(t, m), self.text)
        full = next(ph for ph, orig in m.items() if orig == 'Awa Jallow')  # the full name is one detail, "awa" alone another
        self.assertEqual(t.count(full), 1)
        self.assertEqual(N.pseudonymise('Awa Jallow again', self.patient, m), f'{full} again')   # same detail, same placeholder

    def test_what_the_ai_sees_has_no_identifiers(self):
        self.e.symptoms, self.e.nursing_notes = self.text, 'Lamin visited at 18:00'
        self.e.save()
        r = self.as_('doctor').get(f'/encounters/{self.e.pk}/notes/ai/context/')
        body = json.dumps(r.json())
        for s in self.secrets:
            self.assertNotIn(s, body)
        self.assertIn('benzathine', body)
        self.assertIn('nursing_notes', r.json()['context']['notes'])


@AI_ON
class NotesAITests(NotesBase):
    def setUp(self):
        super().setUp()
        self.patient.phone = '+220 7712345'
        self.patient.save()
        self.e.symptoms, self.e.assessment = 'Awa c/o fevr and hedache x3 days', 'T 38.9'
        self.e.save()

    def ask(self, who, **data):
        return self.as_(who).post(f'/encounters/{self.e.pk}/notes/ai/', data)

    def test_improve_returns_a_suggestion_with_the_names_put_back(self):
        sent = {}

        def fake(ctx, task, task_text, system=None):
            sent.update(ctx=ctx, task=task)
            d = ctx['draft']
            return '```json\n' + json.dumps({'symptoms': d['symptoms'].replace('fevr', 'fever').replace('hedache', 'headache'),
                                             'assessment': d['assessment'], 'changes': ["'fevr' → 'fever'"]}) + '\n```', [], []
        with mock.patch('hospital.medical_ai._ask', side_effect=fake):
            r = self.ask('doctor', kind='improve', section='clinical', symptoms=self.e.symptoms, assessment=self.e.assessment)
        a = r.json()['ask']
        self.assertEqual(a['status'], 'done')
        self.assertEqual(a['fields']['symptoms'], 'Awa c/o fever and headache x3 days')     # the real name is back
        self.assertEqual(a['changes'], ["'fevr' → 'fever'"])
        self.assertEqual(sent['task'], 'notes_improve')
        dumped = json.dumps(sent['ctx'])
        self.assertNotIn('Awa', dumped)
        self.assertIn('[patient 1]', dumped)
        self.e.refresh_from_db()
        self.assertEqual(self.e.symptoms, 'Awa c/o fevr and hedache x3 days')            # nothing saved until the clinician saves

    def test_an_unreadable_answer_fails_cleanly(self):
        with mock.patch('hospital.medical_ai._ask', return_value=('I improved it for you!', [], [])):
            a = self.ask('doctor', kind='correct', section='clinical', symptoms='hedache').json()['ask']
        self.assertEqual(a['status'], 'failed')
        self.assertIn('could not be read', a['error'])

    def test_only_someone_who_may_edit_can_ask_for_a_rewrite(self):
        self.assertEqual(self.ask('doctor2', kind='improve', section='clinical', symptoms='x').status_code, 403)
        self.assertEqual(self.ask('nurse', kind='improve', section='clinical', symptoms='x').status_code, 403)
        with mock.patch('hospital.medical_ai._ask', return_value=('{"nursing_notes": "Fluids given."}', [], [])):
            r = self.ask('nurse', kind='correct', section='nursing', nursing_notes='fluids givn')
        self.assertEqual(r.json()['ask']['fields'], {'nursing_notes': 'Fluids given.'})

    def test_suggestions_read_the_notes_without_the_name(self):
        sent = {}

        def fake(ctx, task, task_text, system=None):
            sent.update(ctx=ctx, task=task, text=task_text)
            return '## Suggested tests\n- Malaria RDT', [], []
        with mock.patch('hospital.medical_ai._ask', side_effect=fake):
            a = self.ask('doctor2', kind='suggest').json()['ask']             # any clinician may ask, not only the attending one
        self.assertEqual(a['status'], 'done')
        self.assertIn('Malaria RDT', a['html'])
        self.assertIn('fevr and hedache', sent['ctx']['notes']['symptoms'])
        dumped = json.dumps(sent['ctx'])
        for s in ['Awa', 'Jallow', self.patient.mrn, '7712345']:
            self.assertNotIn(s, dumped)
        self.assertIn('## Suggested tests', sent['text'])

    def test_questions_are_scrubbed_and_remember_earlier_answers(self):
        calls = []

        def fake(ctx, task, task_text, system=None):
            calls.append((ctx, task_text))
            return f'## Answer\nanswer {len(calls)}', [], []
        with mock.patch('hospital.medical_ai._ask', side_effect=fake):
            self.ask('doctor', kind='question', question='Why is Awa Jallow febrile?')
            self.ask('nurse', kind='question', question='Should we repeat the RDT?')
        q = ClinicalNoteAsk.objects.filter(kind='question').order_by('pk').first()
        self.assertEqual(q.question, 'Why is [patient] febrile?')
        self.assertIn('Why is [patient] febrile?', calls[0][1])
        self.assertEqual(calls[1][0]['earlier_questions'][0]['answer'], '## Answer\nanswer 1')
        self.assertEqual(self.ask('doctor', kind='question', question='').status_code, 400)

    def test_questions_are_allowed_on_a_closed_visit_but_rewrites_are_not(self):
        Encounter.objects.filter(pk=self.e.pk).update(status='completed')
        self.encounter()                       # still being seen, so within the doctor's access
        self.assertEqual(self.ask('doctor', kind='improve', section='clinical', symptoms='x').status_code, 403)
        with mock.patch('hospital.medical_ai._ask', return_value=('## Answer\nok', [], [])):
            self.assertEqual(self.ask('doctor', kind='question', question='What was the plan?').json()['ask']['status'], 'done')

    def test_status_and_rating(self):
        with mock.patch('hospital.medical_ai._ask', return_value=('## Answer\nok', [], [])):
            pk = self.ask('doctor', kind='question', question='What next?').json()['ask']['id']
        self.assertEqual(self.as_('doctor').get(f'/notes/ai/{pk}/').json()['ask']['status'], 'done')
        self.assertEqual(self.as_('doctor').post(f'/notes/ai/{pk}/rate/', {'helpful': '1'}).status_code, 200)
        self.assertTrue(ClinicalNoteAsk.objects.get(pk=pk).helpful)

    @override_settings(CLINICAL_AI_ENABLED=False)
    def test_without_ai_the_buttons_are_hidden_and_requests_refused(self):
        page = self.as_('doctor').get(f'/encounters/{self.e.pk}/').content.decode()
        self.assertNotIn('data-rewrite=', page)
        self.assertNotIn('notes-assist', page)
        self.assertIn('data-notes-edit="clinical"', page)                 # editing works without AI
        self.assertEqual(self.ask('doctor', kind='suggest').status_code, 400)
