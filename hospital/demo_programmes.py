"""Fictional care programme data for the demo: hypertension, HIV treatment and childhood immunisation, each with a care
team, enrolled patients and a history of on-time, late and missed visits, tracing calls and reminders."""
import random
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from . import programmes as P


def _user(username):
    return get_user_model().objects.filter(username=username).first()


def _simulate(e, rng, today, profile, measure):
    """Walk the plan forward from enrolment: patients come on time, late, or (recently) not at all."""
    from .models_programmes import ProgrammeVisit
    stop_at = today - timedelta(days=rng.randint(40, 70)) if profile == 'lost' else None
    for _ in range(60):
        v = ProgrammeVisit.objects.filter(enrolment=e, status__in=['scheduled', 'reminded']).order_by('due').first()
        if v is None or v.due >= today:
            break
        if stop_at and v.due >= stop_at:
            break                                    # stopped coming: the sweep marks them missed, then lost
        recent = (today - v.due).days < 12
        r = rng.random()
        if profile == 'drifting' and recent:
            break                                    # due recently and not come: the sweep marks it missed
        if profile == 'good':
            delay = 0 if r < .8 else rng.randint(1, 3)
        elif profile == 'late':
            delay = rng.randint(0, 2) if r < .5 else rng.randint(5, 14)
        else:
            delay = rng.randint(0, 3) if r < .6 else rng.randint(4, 12)
        came = v.due + timedelta(days=delay)
        if came >= today:
            break
        if delay > e.programme.grace_days:            # it was missed first, then the patient came back
            v.status, v.missed_at = 'missed', timezone.make_aware(timezone.datetime.combine(v.due + timedelta(days=e.programme.grace_days + 1), timezone.datetime.min.time()))
            v.save(update_fields=['status', 'missed_at'])
            from .models_programmes import TracingAttempt
            t = TracingAttempt.objects.create(enrolment=e, visit=v, method=rng.choice(['call', 'call', 'sms', 'home']), outcome=rng.choice(['reached', 'reached', 'no_answer', 'rescheduled']),
                                              reason=rng.choice(['transport', 'forgot', 'work', 'felt_well', 'cost', 'travel']), by=e.nurse)
            TracingAttempt.objects.filter(pk=t.pk).update(created_at=v.missed_at + timedelta(hours=20))
        P.record_visit(v, e.nurse or e.clinician, came, v.items_planned, measure(v, came), v.days_supply)


def run():
    from .models import Condition, Patient
    from .models_programmes import Programme, ProgrammeMember
    if Programme.objects.exists():
        return 0
    doc, doc2, nurse = _user('dr.jallow'), _user('dr.ceesay'), _user('nurse.bah')
    if not doc:
        return 0
    rng, today = random.Random(11), timezone.localdate()
    made = 0

    # ---------------- hypertension
    htn = P.create_from_template('hypertension', doc, name='Hypertension care', ai_enabled=True)
    for u, role in ((doc2, 'doctor'), (nurse, 'nurse')):
        if u:
            ProgrammeMember.objects.get_or_create(programme=htn, user=u, defaults={'role': role})
    pats = list(Patient.objects.filter(conditions__name__icontains='hypertension', deceased_at__isnull=True).distinct()[:12])
    pats += [x for x, _why in P.eligible(htn) if x not in pats and (x.age or 0) >= 18][:12 - len(pats)]     # high readings at visits
    profiles = ['good', 'good', 'good', 'late', 'drifting', 'good', 'lost', 'late', 'good', 'drifting', 'good', 'good']
    for i, p in enumerate(pats):
        base = rng.randint(150, 178)
        e = P.enrol(htn, p, doc, enrolled_on=today - timedelta(days=rng.randint(150, 320)), clinician=rng.choice([doc, doc2 or doc]), nurse=nurse,
                    channel=rng.choice(['sms', 'whatsapp', 'sms']))
        prof = profiles[i % len(profiles)]

        def bp(v, came, base=base, e=e, prof=prof):
            days = (came - e.enrolled_on).days
            s = base - min(30, days // 9) + rng.randint(-6, 6) + (12 if prof in ('late', 'drifting') else 0)
            return {'bp': f'{s}/{int(s * .62) + rng.randint(-4, 4)}', 'weight': str(rng.randint(64, 92)), 'adherence': str(rng.choice([100, 95, 90, 80] if prof != 'good' else [100, 100, 95])),
                    'side_effects': rng.choice(['none', 'none', 'none', 'mild'])}
        _simulate(e, rng, today, prof, bp)
        made += 1

    # ---------------- HIV treatment (discreet reminders)
    hiv = P.create_from_template('hiv', doc2 or doc, name='HIV treatment (ART)')
    if nurse:
        ProgrammeMember.objects.get_or_create(programme=hiv, user=nurse, defaults={'role': 'nurse'})
    ProgrammeMember.objects.get_or_create(programme=hiv, user=doc, defaults={'role': 'doctor'})
    pats = list(Patient.objects.filter(conditions__name__icontains='hiv', deceased_at__isnull=True).distinct()[:8])
    if len(pats) < 6:      # make sure the demo has a few
        extra = list(Patient.objects.filter(deceased_at__isnull=True, dob__lte=today - timedelta(days=20 * 365)).exclude(pk__in=[x.pk for x in pats])
                     .exclude(enrolments__isnull=False).order_by('pk')[:6 - len(pats)])
        for p in extra:
            Condition.objects.create(patient=p, name='HIV, on ART', status='active', onset=today - timedelta(days=900))
        pats += extra
    for i, p in enumerate(pats):
        start = today - timedelta(days=rng.randint(200, 500))
        e = P.enrol(hiv, p, doc2 or doc, enrolled_on=start, anchor_date=start, clinician=doc2 or doc, nurse=nurse, channel='sms')
        prof = ['good', 'late', 'good', 'drifting', 'lost', 'good'][i % 6]

        def art(v, came, e=e, prof=prof):
            m = {'weight': str(rng.randint(52, 80)), 'adherence': str(rng.choice([100, 98, 95] if prof == 'good' else [95, 85, 80, 70])), 'side_effects': rng.choice(['none', 'none', 'mild'])}
            if v.kind == 'test':
                m['viral_load'] = str(rng.choice([20, 40, 50]) if prof == 'good' else rng.choice([50, 400, 1800, 12000]))
            return m
        _simulate(e, rng, today, prof, art)
        made += 1

    # ---------------- childhood immunisation
    imm = P.create_from_template('immunisation', nurse or doc, name='Childhood immunisation')
    ProgrammeMember.objects.get_or_create(programme=imm, user=doc, defaults={'role': 'doctor'})
    kids = list(Patient.objects.filter(dob__gte=today - timedelta(days=700), deceased_at__isnull=True)[:6])
    names = [('Binta', 'Sanneh', 'F'), ('Lamin', 'Jobe', 'M'), ('Aminata', 'Touray', 'F'), ('Ousman', 'Bojang', 'M'), ('Fatou', 'Manneh', 'F')]
    for (fn, ln, sex), age_days in zip(names, [30, 75, 125, 200, 420]):
        if len(kids) >= 6:
            break
        kids.append(Patient.objects.create(first_name=fn, last_name=ln, sex=sex, dob=today - timedelta(days=age_days), phone=f'+220 7{rng.randint(100000, 999999)}',
                                           emergency_contact=f'Mother: +220 3{rng.randint(100000, 999999)}'))
    for i, k in enumerate(kids):
        e = P.enrol(imm, k, nurse or doc, enrolled_on=k.dob, anchor_date=k.dob, clinician=doc, nurse=nurse, channel='sms', contact_phone=f'+220 3{rng.randint(100000, 999999)}')
        _simulate(e, rng, today, 'drifting' if i == 2 else 'good', lambda v, came, k=k: {'weight': f'{3.2 + (came - k.dob).days * .018:.1f}', 'temperature': '36.7'})
        made += 1

    P.sweep(today)
    return made
