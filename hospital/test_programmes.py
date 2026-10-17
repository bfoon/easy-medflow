"""Care programmes: visit planning, reminders, missed-visit alerts, escalation, lost to follow-up, tracing, risk,
the care team's access, the per-programme AI switch and the privacy firewall."""
from datetime import date, timedelta
from unittest import mock

from django.core import mail
from django.test import override_settings
from django.utils import timezone

from . import programmes as P
from .models import Condition, Encounter, Notification, Patient, StaffProfile
from .models_programmes import Enrolment, ProgrammeAIRun, ProgrammeMember, ProgrammeMessage, ProgrammeVisit, TracingAttempt
from .tests import PW, Base

TODAY = timezone.localdate()


class ProgrammeBase(Base):
    def setUp(self):
        self.doc, self.nurse = self.users['doctor'], self.users['nurse']
        self.patient.phone = '+220 341 5919'
        self.patient.save()

    def htn(self, **kw):
        p = P.create_from_template('hypertension', self.doc, **kw)
        ProgrammeMember.objects.create(programme=p, user=self.nurse, role='nurse')
        return p

    def enrol(self, p, days_ago=0, **kw):
        kw.setdefault('clinician', self.doc)
        kw.setdefault('nurse', self.nurse)
        return P.enrol(p, kw.pop('patient', self.patient), self.doc, enrolled_on=TODAY - timedelta(days=days_ago), **kw)


class PlanningTests(ProgrammeBase):
    def test_template_creates_plan_and_team(self):
        p = P.create_from_template('immunisation', self.doc)
        self.assertEqual(p.anchor, 'dob')
        self.assertEqual(p.steps.count(), 6)
        self.assertEqual(p.steps.first().items, ['BCG', 'OPV 0', 'Hepatitis B birth dose'])
        self.assertTrue(p.members.filter(user=self.doc, role='lead').exists())
        self.assertTrue(P.create_from_template('hiv', self.doc).discreet)
        self.assertEqual(P.create_from_template('immunisation', self.doc).name, 'Childhood immunisation (2)')   # names stay unique

    def test_vaccines_follow_birth_and_late_doses_become_catch_up(self):
        p = P.create_from_template('immunisation', self.doc)
        baby = Patient.objects.create(first_name='Binta', last_name='Sanneh', dob=TODAY - timedelta(days=70), sex='F')
        e = P.enrol(p, baby, self.doc, anchor_date=baby.dob)
        v = {x.step.name: x for x in e.visits.all()}
        self.assertEqual(v['At birth'].due, TODAY)                         # missed birth doses: catch-up now
        self.assertIn('catch-up', v['At birth'].title)
        self.assertEqual(v['12 weeks'].due, baby.dob + timedelta(days=84))  # still to come: on schedule
        self.assertEqual(v['9 months'].items_planned[0], 'Measles-Rubella 1')

    def test_next_refill_is_when_the_medicine_runs_out(self):
        p = self.htn()
        e = self.enrol(p, days_ago=31)
        refill = e.visits.get(kind='refill')
        self.assertEqual(refill.due, TODAY - timedelta(days=1))
        res = P.record_visit(refill, self.nurse, TODAY, measures={'bp': '150/95', 'weight': 'x', 'nonsense': '1'}, days_supply=60)
        refill.refresh_from_db()
        self.assertEqual(refill.measures, {'bp': '150/95', 'weight': 'x'})  # unknown measures dropped
        nxt = e.visits.filter(kind='refill', status='scheduled').get()
        self.assertEqual(nxt.due, TODAY + timedelta(days=60))                # 60 days given, not the usual 30
        self.assertEqual(res['planned'][0], nxt)

    def test_repeats_stop_at_the_end_of_treatment(self):
        p = P.create_from_template('nutrition', self.doc)                    # weekly until day 56
        e = P.enrol(p, self.patient, self.doc, enrolled_on=TODAY - timedelta(days=60))
        for _ in range(12):
            v = e.visits.filter(status='scheduled').order_by('due').first()
            if not v:
                break
            P.record_visit(v, self.nurse, v.due, days_supply=7)
        self.assertLessEqual(max(x.due for x in e.visits.all()), e.start + timedelta(days=56))
        self.assertFalse(e.visits.filter(status='scheduled').exists())

    def test_one_open_enrolment_per_programme(self):
        from django.db import IntegrityError, transaction
        p = self.htn()
        self.enrol(p)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.enrol(p)


class SweepTests(ProgrammeBase):
    def test_reminder_before_the_visit_waits_in_the_outbox_without_naming_a_discreet_programme(self):
        p = P.create_from_template('hiv', self.doc, reminder_text='Hi {name}, your HIV refill at {clinic} is on {date}')
        e = self.enrol(p, days_ago=0, anchor_date=TODAY + timedelta(days=2))
        P.sweep()
        m = ProgrammeMessage.objects.get(kind='reminder')
        self.assertEqual((m.status, m.channel, m.to), ('pending', 'sms', '2203415919'))
        self.assertIn('Awa', m.text)
        self.assertNotIn('Jallow', m.text)                                   # first name only
        self.assertNotIn('HIV', m.text)
        self.assertNotIn(p.name, m.text)
        self.assertEqual(e.visits.get(kind='refill').status, 'reminded')
        self.assertIn('wa.me/2203415919', P.send_links(m)['whatsapp'])
        P.sweep()
        self.assertEqual(ProgrammeMessage.objects.count(), 1)                # only once

    def test_no_reminders_without_consent(self):
        p = self.htn()
        e = self.enrol(p, days_ago=29, consent_reminders=False)
        P.sweep()
        self.assertFalse(ProgrammeMessage.objects.exists())
        self.assertEqual(e.visits.get(kind='refill').status, 'scheduled')

    @override_settings(NOTIFY_EMAIL_SYNC=True)
    def test_missed_visit_tells_the_team_without_patient_details(self):
        self.doc.email, self.nurse.email = 'doc@x.gm', 'nurse@x.gm'
        self.doc.save(); self.nurse.save()
        p = self.htn()
        other = StaffProfile.objects.get(user=self.users['pharmacy']).user
        ProgrammeMember.objects.create(programme=p, user=other, role='pharmacist', notify=False)
        e = self.enrol(p, days_ago=40)       # refill due 10 days ago and the yearly kidney test due on day 0; grace 5
        with self.captureOnCommitCallbacks(execute=True):
            out = P.sweep()
        self.assertEqual(out['missed'], 2)
        self.assertEqual(Notification.objects.filter(user=self.nurse, kind='programme').get().title, 'Hypertension care: 2 missed visits')   # one grouped alert
        self.assertEqual(e.visits.get(kind='refill').status, 'missed')
        to = set(Notification.objects.filter(kind='programme').values_list('user__username', flat=True))
        self.assertEqual(to, {'doctor', 'nurse'})                            # responsible + members who asked; not the pharmacist
        n = Notification.objects.filter(kind='programme').first()
        for secret in ('Awa', 'Jallow', self.patient.mrn, '3415919'):
            self.assertNotIn(secret, n.title + n.body)
            for m in mail.outbox:
                self.assertNotIn(secret, m.subject + m.body)
        self.assertTrue(ProgrammeMessage.objects.filter(kind='missed').exists())   # "we missed you" to the patient

    def test_untraced_miss_is_escalated_to_the_lead_and_then_lost_to_follow_up(self):
        p = self.htn(lead=self.doc)
        p.grace_days, p.escalate_days, p.ltfu_days = 2, 3, 20
        p.save()
        e = self.enrol(p, days_ago=30 + 10)
        P.sweep(TODAY)
        v = e.visits.get(kind='refill')
        self.assertIsNotNone(v.escalated_at)
        self.assertTrue(Notification.objects.filter(user=self.doc, title__contains='not traced').exists())
        P.sweep(TODAY + timedelta(days=15))
        e.refresh_from_db()
        self.assertEqual(e.status, 'lost')
        self.assertTrue(Notification.objects.filter(title__contains='lost to follow-up').exists())
        res = P.record_visit(v, self.nurse, TODAY + timedelta(days=15))     # the patient comes back
        e.refresh_from_db()
        self.assertTrue(res['returned'])
        self.assertEqual((e.status, e.lost_since), ('active', None))

    def test_a_traced_miss_is_not_escalated(self):
        p = self.htn()
        p.grace_days, p.escalate_days = 2, 3
        p.save()
        e = self.enrol(p, days_ago=34)
        P.sweep(TODAY - timedelta(days=1))
        TracingAttempt.objects.create(enrolment=e, outcome='reached', by=self.nurse)
        P.sweep(TODAY + timedelta(days=5))
        self.assertIsNone(e.visits.get(kind='refill').escalated_at)


class RiskAndPrivacyTests(ProgrammeBase):
    def test_risk_by_rules(self):
        p = self.htn()
        e = self.enrol(p, days_ago=40)
        v = e.visits.get(kind='refill')
        P.record_visit(v, self.nurse, v.due, measures={'bp': '172/104', 'adherence': '80'})
        level, score, why = P.risk(e)
        self.assertEqual((level, score), ('medium', 4))                    # uncontrolled and poor adherence, but coming
        self.assertIn('blood pressure 172/104', why)
        self.assertIn('adherence 80%', why)
        P.sweep(TODAY + timedelta(days=45))                                 # then misses the next refill by weeks
        level, score, why = P.risk(e, today=TODAY + timedelta(days=45))
        self.assertEqual(level, 'high')
        self.assertTrue(any('days late' in w for w in why))

    def test_firewall_blocks_identifiers_and_real_dates(self):
        ok = {'patient': {'sex': 'F', 'age_band': '30-39'}, 'visits': [{'day_due': 30, 'measures': {'Blood pressure': '150/90'}}]}
        self.assertTrue(P.firewall(ok, [self.patient]))
        for bad in ({'note': 'Awa came late'}, {'x': self.patient.mrn}, {'x': 'call 3415919'}, {'x': 'call 341 5919'}, {'x': 'ring 990-1234'}, {'x': '1990-01-01'}, {'x': 'seen 2026-10-01'}, {'x': 'a@b.gm'}):
            with self.assertRaises(P.PIIBlocked):
                P.firewall(bad, [self.patient])

    def test_ai_contexts_are_de_identified_and_pass_the_firewall(self):
        Condition.objects.create(patient=self.patient, name='Asthma (Awa Jallow, MF-ABCDEF1234)', status='active')
        p = self.htn()
        e = self.enrol(p, days_ago=40, notes='Lives with Awa Jallow senior, 3415919')
        v = e.visits.get(kind='refill')
        P.record_visit(v, self.nurse, v.due, measures={'bp': '150/95'}, note='Awa said transport is hard')
        TracingAttempt.objects.create(enrolment=e, outcome='reached', reason='transport', note='spoke to Awa', by=self.nurse)
        pc = P.patient_context(e)
        self.assertTrue(P.firewall(pc, [self.patient]))
        self.assertEqual(pc['patient']['age_band'], '30-39')
        self.assertEqual(pc['tracing'][0]['reason'], 'Transport / distance')
        self.assertNotIn('transport is hard', str(pc))                     # notes never leave
        cc = P.cohort_context(p)
        self.assertTrue(P.firewall(cc, [self.patient]))
        self.assertEqual(cc['patients']['active'], '<5')                   # small numbers hidden

    @override_settings(CLINICAL_AI_ENABLED=True, ANTHROPIC_API_KEY='k')
    def test_ai_switch_is_per_programme_and_blocked_requests_send_nothing(self):
        p = self.htn()
        e = self.enrol(p, days_ago=40)
        c = self.as_('nurse')
        self.assertEqual(c.post(f'/programmes/ai/patient/{e.pk}/ask/').status_code, 403)     # AI off for this programme
        p.ai_enabled = True
        p.save()
        with mock.patch('hospital.medical_ai._ask', return_value=('## Summary\nOn track.', [], 0)) as ask, \
             mock.patch('hospital.evidence_views._dispatch', side_effect=lambda t, pk: P.run_ai(pk)):
            r = c.post(f'/programmes/ai/patient/{e.pk}/ask/').json()
            self.assertEqual(r['run']['status'], 'done')
            sent = ask.call_args[0][0]
            self.assertNotIn('Awa', str(sent))
            self.assertEqual(len(ProgrammeAIRun.objects.get().context_digest), 64)
            with mock.patch('hospital.programmes.patient_context', return_value={'name': 'Awa Jallow'}):
                r = c.post(f'/programmes/ai/patient/{e.pk}/ask/').json()
            self.assertEqual(r['run']['status'], 'blocked')
            self.assertEqual(ask.call_count, 1)                              # the blocked request never reached the AI
        preview = c.get(f'/programmes/ai/cohort/{p.pk}/context/').json()
        self.assertTrue(preview['ok'])


class AccessTests(ProgrammeBase):
    def test_team_member_can_follow_enrolled_patients_between_visits(self):
        p = self.htn()
        e = self.enrol(p)
        c = self.as_('nurse')
        self.assertEqual(c.get(f'/patients/{self.patient.pk}/').status_code, 200)            # no open visit, but in the programme
        self.assertEqual(c.get(f'/programmes/enrolments/{e.pk}/').status_code, 200)
        ProgrammeMember.objects.filter(user=self.nurse).delete()
        Enrolment.objects.filter(pk=e.pk).update(nurse=None)
        self.assertEqual(c.get(f'/programmes/{p.pk}/').status_code, 403)                      # not in the team any more
        self.assertEqual(c.get(f'/patients/{self.patient.pk}/').status_code, 403)

    def test_only_programme_admins_create_programmes(self):
        self.assertEqual(self.as_('nurse').post('/programmes/new/', {'template': 'hiv'}).status_code, 403)
        self.assertEqual(self.as_('reception').get('/programmes/').status_code, 403)


class PageTests(ProgrammeBase):
    def setUp(self):
        super().setUp()
        self.p = self.htn()
        self.e = self.enrol(self.p, days_ago=40)
        P.sweep()

    def test_every_tab_renders(self):
        c = self.as_('doctor')
        self.assertContains(c.get('/programmes/'), 'Hypertension care')
        for tab in ('today', 'missed', 'patients', 'plan', 'team', 'insights', 'outbox'):
            self.assertEqual(c.get(f'/programmes/{self.p.pk}/?tab={tab}').status_code, 200, tab)
        self.assertContains(c.get(f'/programmes/{self.p.pk}/?tab=missed'), self.patient.full_name)
        self.assertContains(c.get(f'/patients/{self.patient.pk}/'), 'Care programmes')            # chart panel
        for url in (f'/programmes/enrolments/{self.e.pk}/', f'/programmes/{self.p.pk}/?tab=outbox'):
            page = c.get(url).content.decode()
            self.assertNotIn('ProgrammeMessage object', page)        # reminders must not leak into the toast messages
            self.assertNotIn("'links'", page)
        self.assertContains(c.get(f'/programmes/{self.p.pk}/?tab=outbox'), 'we missed you')

    def test_record_trace_and_move_visits(self):
        c = self.as_('nurse')
        v = self.e.visits.get(status='missed', kind='refill')
        r = c.post(f'/programmes/enrolments/{self.e.pk}/trace/', {'visit': v.pk, 'method': 'call', 'outcome': 'rescheduled', 'reason': 'transport',
                                                                  'due': (TODAY + timedelta(days=3)).isoformat()})
        self.assertEqual(r.status_code, 302)
        v.refresh_from_db()
        self.assertEqual((v.status, v.due), ('scheduled', TODAY + timedelta(days=3)))
        self.assertEqual(TracingAttempt.objects.get().reason, 'transport')
        r = c.post(f'/programmes/visits/{v.pk}/record/', {'attended_on': TODAY.isoformat(), 'days_supply': 30, 'm_bp': '138/86', 'm_weight': '71'})
        self.assertEqual(r.status_code, 302)
        v.refresh_from_db()
        self.assertEqual((v.status, v.measures['bp']), ('attended', '138/86'))
        bad = self.e.visits.filter(status='scheduled', kind='refill').get()
        self.assertContains(c.post(f'/programmes/visits/{bad.pk}/record/', {'attended_on': TODAY.isoformat(), 'm_bp': 'high'}), 'Please check')

    def test_enrol_search_bulk_and_team(self):
        c = self.as_('doctor')
        kid = Patient.objects.create(first_name='Lamin', last_name='Jobe', dob=date(1980, 5, 1), sex='M', phone='7712345')
        self.assertEqual(c.get(f'/programmes/{self.p.pk}/patient-search/?q=jobe').json()['results'][0]['id'], kid.pk)
        self.assertTrue(c.get(f'/programmes/{self.p.pk}/patient-search/?q=jallow').json()['results'][0]['enrolled'])
        r = c.post(f'/programmes/{self.p.pk}/enrol/', {'patient': kid.pk, 'enrolled_on': TODAY.isoformat(), 'channel': 'whatsapp', 'consent_reminders': 'on'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Enrolment.objects.filter(patient=kid, programme=self.p, channel='whatsapp').exists())
        other = Patient.objects.create(first_name='Musa', last_name='Ceesay', dob=date(1970, 1, 1), sex='M')
        Encounter.objects.create(patient=other, department=self.dept, reason='Check', vitals={'bp': '168/102'})
        rows = dict((x.pk, why) for x, why in P.eligible(self.p))
        self.assertIn('168/102', rows[other.pk])
        c.post(f'/programmes/{self.p.pk}/eligible/', {'patient': [other.pk]})
        self.assertTrue(Enrolment.objects.filter(patient=other).exists())
        c.post(f'/programmes/{self.p.pk}/team/', {'act': 'add', 'user': self.users['pharmacy'].pk, 'role': 'pharmacist'})
        self.assertTrue(self.p.members.filter(user=self.users['pharmacy'], role='pharmacist').exists())

    def test_settings_save_team_and_plan(self):
        c = self.as_('doctor')
        r = c.get(f'/programmes/{self.p.pk}/edit/')
        self.assertContains(r, 'Visit plan')
        data = {'name': 'Hypertension · Serrekunda', 'kind': 'hypertension', 'color': '#C8323F', 'icon': 'heart-pulse', 'active': 'on', 'lead': self.doc.pk,
                'anchor': 'enrolment', 'measures': ['bp', 'weight'], 'reminder_days': 1, 'grace_days': 4, 'escalate_days': 10, 'ltfu_days': 45,
                'nurses': [self.nurse.pk], 'ai_enabled': 'on',
                'steps-TOTAL_FORMS': 3, 'steps-INITIAL_FORMS': 2, 'steps-MIN_NUM_FORMS': 0, 'steps-MAX_NUM_FORMS': 1000}
        for i, s in enumerate(self.p.steps.all()):
            data.update({f'steps-{i}-id': s.pk, f'steps-{i}-programme': self.p.pk, f'steps-{i}-order': i, f'steps-{i}-name': s.name, f'steps-{i}-kind': s.kind,
                         f'steps-{i}-offset_days': s.offset_days, f'steps-{i}-repeat_days': s.repeat_days or '', f'steps-{i}-items': ', '.join(s.items),
                         f'steps-{i}-medicine': s.medicine, f'steps-{i}-days_supply': s.days_supply or ''})
        data.update({'steps-2-order': 3, 'steps-2-name': 'Lifestyle counselling', 'steps-2-kind': 'counselling', 'steps-2-offset_days': 14, 'steps-2-items': 'Salt, Exercise'})
        r = c.post(f'/programmes/{self.p.pk}/edit/', data)
        self.assertEqual(r.status_code, 302, r.content[:3000])
        self.p.refresh_from_db()
        self.assertEqual((self.p.name, self.p.ltfu_days, self.p.ai_enabled, self.p.measures), ('Hypertension · Serrekunda', 45, True, ['bp', 'weight']))
        self.assertEqual(self.p.steps.get(name='Lifestyle counselling').items, ['Salt', 'Exercise'])
        self.assertEqual(set(self.p.members.values_list('user__username', flat=True)), {'doctor', 'nurse'})

    def test_outbox_mark_sent(self):
        m = ProgrammeMessage.objects.filter(status='pending').first()
        r = self.as_('nurse').post(f'/programmes/messages/{m.pk}/', {'act': 'sent'}, HTTP_ACCEPT='application/json')
        self.assertEqual(r.json()['status'], 'Sent')
        m.refresh_from_db()
        self.assertEqual(m.sent_by, self.nurse)
