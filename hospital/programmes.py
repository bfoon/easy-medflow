"""Care programmes: the rules behind HIV treatment, hypertension, diabetes, TB, immunisation, antenatal and other
long-term programmes.

* **Templates** create a programme with a ready visit plan (refills, reviews, vaccines, tests) that the team then edits.
* **Planning** keeps every active patient's next visits on the calendar. Refills are due when the medicine given runs
  out (days supplied), not on a fixed date; vaccines follow the child's date of birth; antenatal contacts follow the LMP.
* **The daily sweep** (Celery beat, and also run when a programme page is opened) reminds patients before a visit,
  marks visits missed after the grace period, tells the responsible doctor, nurse and the team members who asked to
  hear, escalates untraced misses to the programme lead and marks patients lost to follow-up.
* **Messages to patients** name only the first name, the clinic and the date. Discreet programmes (HIV, TB, mental
  health) never name the programme or condition. Email and an SMS gateway send by themselves; WhatsApp, SMS without a
  gateway and calls wait in the outbox for staff to send from a phone in one tap.
* **Staff notifications** (bell and email) never contain patient names: only counts and a link that needs a sign-in.
* **Risk** is worked out by rules, without AI: lateness, on-time history, tracing results and off-target measures.
* **AI (optional, per programme)** receives only de-identified data: an aggregate with small numbers hidden (<5) for a
  programme, or a pseudonymous timeline in relative days for one patient. The programme summary is made automatically
  after each visit day (from SUMMARY_HOUR that evening, or the next morning) and the whole care team sees it. Team
  members can also ask their own questions about the programme: only the person who asked sees the answer, and the
  question itself passes the privacy firewall before anything is sent. A privacy firewall checks every request for
  the patients' names, record numbers, phones, emails, addresses, birth dates and any real date, and blocks it if it
  finds one. Notes are never sent.
"""
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

# ------------------------------------------------------------------ what is recorded at a visit
# key: (label, unit, kind, placeholder) — kind: text | number | choice:<a|b|c>
MEASURES = {
    'bp': ('Blood pressure', 'mmHg', 'text', '128/82'),
    'weight': ('Weight', 'kg', 'number', '68'),
    'height': ('Height / length', 'cm', 'number', '74'),
    'muac': ('MUAC (arm circumference)', 'cm', 'number', '13.2'),
    'temperature': ('Temperature', '°C', 'number', '36.8'),
    'glucose': ('Blood glucose', 'mmol/L', 'number', '6.4'),
    'hba1c': ('HbA1c', '%', 'number', '7.1'),
    'viral_load': ('Viral load', 'copies/mL', 'number', '50'),
    'cd4': ('CD4 count', 'cells/µL', 'number', '420'),
    'adherence': ('Adherence (pill count)', '%', 'number', '95'),
    'side_effects': ('Side effects', '', 'choice:none|mild|serious', ''),
    'sputum': ('Sputum smear / GeneXpert', '', 'choice:negative|positive|not done', ''),
    'hb': ('Haemoglobin', 'g/dL', 'number', '11.2'),
    'fundal_height': ('Fundal height', 'cm', 'number', '28'),
    'fetal_hr': ('Fetal heart rate', 'bpm', 'number', '140'),
    'pain_crises': ('Pain crises since last visit', '', 'number', '0'),
    'phq9': ('PHQ-9 score', '', 'number', '6'),
    'seizures': ('Seizures since last visit', '', 'number', '0'),
}
MISS_REASONS = [('', '—'), ('transport', 'Transport / distance'), ('forgot', 'Forgot'), ('felt_well', 'Felt well, thought not needed'),
                ('side_effects', 'Side effects'), ('cost', 'Cost'), ('travel', 'Travelling'), ('work', 'Work or school'),
                ('stigma', 'Fear of being seen / stigma'), ('sick', 'Too sick to come'), ('caregiver', 'No carer to bring them'),
                ('stockout', 'Medicine not available last time'), ('other', 'Other')]
MISS_REASON_LABEL = dict(MISS_REASONS)

# ------------------------------------------------------------------ ready-made programmes
D = 1
W = 7
M = 30
EPI_NOTE = 'Follows a typical national EPI schedule. Check it against the current schedule of your EPI unit and edit as needed.'
TEMPLATES = {
    'hiv': {
        'name': 'HIV treatment (ART)', 'kind': 'hiv', 'icon': 'shield-plus', 'color': '#B23A55', 'anchor': 'start', 'discreet': True,
        'description': 'Antiretroviral therapy: monthly refills (longer once stable), adherence support and viral load monitoring.',
        'measures': ['weight', 'adherence', 'side_effects', 'viral_load', 'bp'], 'grace_days': 3, 'escalate_days': 7, 'ltfu_days': 28,
        'steps': [
            {'name': 'ART refill', 'kind': 'refill', 'offset_days': 0, 'repeat_days': 30, 'medicine': 'TDF/3TC/DTG', 'days_supply': 30},
            {'name': 'Adherence counselling', 'kind': 'counselling', 'offset_days': 14},
            {'name': 'Viral load (6 months)', 'kind': 'test', 'offset_days': 6 * M, 'items': ['Viral load']},
            {'name': 'Viral load (12 months)', 'kind': 'test', 'offset_days': 12 * M, 'items': ['Viral load']},
            {'name': 'Yearly viral load', 'kind': 'test', 'offset_days': 24 * M, 'repeat_days': 365, 'items': ['Viral load']},
        ]},
    'hypertension': {
        'name': 'Hypertension care', 'kind': 'hypertension', 'icon': 'heart-pulse', 'color': '#C8323F', 'anchor': 'enrolment',
        'description': 'Blood pressure control: monthly review and refill until controlled, lifestyle advice, yearly kidney check. Target below 140/90.',
        'measures': ['bp', 'weight', 'adherence', 'side_effects'], 'grace_days': 5, 'escalate_days': 14, 'ltfu_days': 60,
        'steps': [
            {'name': 'BP review and refill', 'kind': 'refill', 'offset_days': 30, 'repeat_days': 30, 'medicine': 'Amlodipine 5 mg', 'days_supply': 30},
            {'name': 'Kidney function and urine', 'kind': 'test', 'offset_days': 0, 'repeat_days': 365, 'items': ['Creatinine', 'Urine protein']},
        ]},
    'diabetes': {
        'name': 'Diabetes care', 'kind': 'diabetes', 'icon': 'droplet', 'color': '#4A5FC1', 'anchor': 'enrolment',
        'description': 'Monthly review and refill, HbA1c every 3 months, yearly foot and eye checks.',
        'measures': ['glucose', 'hba1c', 'bp', 'weight', 'adherence'], 'grace_days': 5, 'escalate_days': 14, 'ltfu_days': 60,
        'steps': [
            {'name': 'Diabetes review and refill', 'kind': 'refill', 'offset_days': 30, 'repeat_days': 30, 'medicine': 'Metformin 500 mg', 'days_supply': 30},
            {'name': 'HbA1c', 'kind': 'test', 'offset_days': 90, 'repeat_days': 90, 'items': ['HbA1c']},
            {'name': 'Foot and eye check', 'kind': 'review', 'offset_days': 0, 'repeat_days': 365, 'items': ['Foot exam', 'Eye exam']},
        ]},
    'tb': {
        'name': 'TB treatment (DOTS)', 'kind': 'tb', 'icon': 'lungs', 'color': '#8A4A8F', 'anchor': 'start', 'discreet': True,
        'description': '6-month treatment: 2 months intensive phase, 4 months continuation, with sputum checks at months 2, 5 and 6.',
        'measures': ['weight', 'adherence', 'side_effects', 'sputum'], 'grace_days': 2, 'escalate_days': 5, 'ltfu_days': 28,
        'steps': [
            {'name': 'TB medicine refill', 'kind': 'refill', 'offset_days': 0, 'repeat_days': 14, 'until_days': 180, 'medicine': 'RHZE / RH', 'days_supply': 14},
            {'name': 'Sputum (end of month 2)', 'kind': 'test', 'offset_days': 56, 'items': ['Sputum']},
            {'name': 'Sputum (month 5)', 'kind': 'test', 'offset_days': 150, 'items': ['Sputum']},
            {'name': 'Sputum and outcome (month 6)', 'kind': 'test', 'offset_days': 180, 'items': ['Sputum', 'Treatment outcome']},
        ]},
    'immunisation': {
        'name': 'Childhood immunisation', 'kind': 'immunisation', 'icon': 'shield-check', 'color': '#0F7B78', 'anchor': 'dob',
        'description': 'Routine vaccines from birth to 18 months, counted from the date of birth. ' + EPI_NOTE,
        'measures': ['weight', 'height', 'muac', 'temperature'], 'grace_days': 7, 'escalate_days': 14, 'ltfu_days': 60,
        'reminder_text': 'Hello, this is {clinic}. {name} has a vaccination visit on {date}. Please bring the child health card.',
        'missed_text': 'Hello, this is {clinic}. {name} missed a vaccination visit on {date}. Please come this week so the child stays protected.',
        'steps': [
            {'name': 'At birth', 'kind': 'vaccine', 'offset_days': 0, 'items': ['BCG', 'OPV 0', 'Hepatitis B birth dose']},
            {'name': '8 weeks', 'kind': 'vaccine', 'offset_days': 8 * W, 'items': ['Penta 1', 'OPV 1', 'PCV 1', 'Rota 1']},
            {'name': '12 weeks', 'kind': 'vaccine', 'offset_days': 12 * W, 'items': ['Penta 2', 'OPV 2', 'PCV 2', 'Rota 2']},
            {'name': '16 weeks', 'kind': 'vaccine', 'offset_days': 16 * W, 'items': ['Penta 3', 'OPV 3', 'PCV 3', 'IPV']},
            {'name': '9 months', 'kind': 'vaccine', 'offset_days': 274, 'items': ['Measles-Rubella 1', 'Yellow fever', 'MenA', 'Vitamin A']},
            {'name': '18 months', 'kind': 'vaccine', 'offset_days': 548, 'items': ['Measles-Rubella 2', 'DTP booster', 'Vitamin A']},
        ]},
    'antenatal': {
        'name': 'Antenatal care (8 contacts)', 'kind': 'antenatal', 'icon': 'person-hearts', 'color': '#D2691E', 'anchor': 'lmp',
        'description': 'WHO 2016 model: eight antenatal contacts, counted from the first day of the last menstrual period.',
        'measures': ['bp', 'weight', 'hb', 'fundal_height', 'fetal_hr'], 'grace_days': 5, 'escalate_days': 7, 'ltfu_days': 42,
        'steps': [{'name': f'Contact {i + 1} ({wk} weeks)', 'kind': 'review', 'offset_days': wk * W} for i, wk in enumerate([12, 20, 26, 30, 34, 36, 38, 40])],
    },
    'sickle_cell': {
        'name': 'Sickle cell clinic', 'kind': 'sickle_cell', 'icon': 'droplet-half', 'color': '#9B1C3C', 'anchor': 'enrolment',
        'description': 'Quarterly review, folic acid and hydroxyurea refills, yearly checks.',
        'measures': ['hb', 'weight', 'pain_crises', 'adherence'], 'grace_days': 7, 'escalate_days': 14, 'ltfu_days': 120,
        'steps': [{'name': 'Review and refill', 'kind': 'refill', 'offset_days': 90, 'repeat_days': 90, 'medicine': 'Folic acid, hydroxyurea', 'days_supply': 90}]},
    'mental_health': {
        'name': 'Mental health follow-up', 'kind': 'mental_health', 'icon': 'chat-heart', 'color': '#5A6F7D', 'anchor': 'enrolment', 'discreet': True,
        'description': 'Monthly follow-up and medicine refill, PHQ-9 tracking.',
        'measures': ['phq9', 'adherence', 'side_effects', 'seizures'], 'grace_days': 3, 'escalate_days': 7, 'ltfu_days': 60,
        'steps': [{'name': 'Follow-up and refill', 'kind': 'refill', 'offset_days': 30, 'repeat_days': 30, 'days_supply': 30}]},
    'nutrition': {
        'name': 'Child nutrition (CMAM)', 'kind': 'nutrition', 'icon': 'egg-fried', 'color': '#B8860B', 'anchor': 'enrolment',
        'description': 'Weekly weight and MUAC with ready-to-use therapeutic food until recovery (about 8 weeks).',
        'measures': ['weight', 'muac', 'height', 'temperature'], 'grace_days': 2, 'escalate_days': 4, 'ltfu_days': 14,
        'steps': [{'name': 'Weekly check and RUTF', 'kind': 'refill', 'offset_days': 7, 'repeat_days': 7, 'until_days': 56, 'medicine': 'RUTF', 'days_supply': 7}]},
}
KEYWORDS = {'hiv': ['hiv', 'antiretroviral', r'\bart\b'], 'hypertension': ['hypertension', 'high blood pressure', r'\bhtn\b'],
            'diabetes': ['diabetes', r'\bt2dm\b', r'\bdm\b'], 'tb': ['tuberculosis', r'\btb\b', r'\bptb\b'], 'sickle_cell': ['sickle'],
            'mental_health': ['depression', 'schizophrenia', 'bipolar', 'psychosis', 'anxiety disorder'], 'nutrition': ['malnutrition', r'\bsam\b', 'wasting'],
            'antenatal': ['pregnan', 'antenatal']}
OPEN = ('scheduled', 'reminded', 'missed')


def clinic_name():
    return getattr(settings, 'MEDFLOW_CLINIC_NAME', '') or 'the clinic'


def create_from_template(key, user=None, **over):
    """A new programme from a ready-made template (then edited by the team)."""
    from .models_programmes import Programme, ProgrammeMember, ProgrammeStep
    t = dict(TEMPLATES[key])
    steps = t.pop('steps')
    fields = {k: v for k, v in t.items() if k in {f.name for f in Programme._meta.get_fields()}}
    fields.update(over)
    base, n = fields['name'], 2
    while Programme.objects.filter(name=fields['name']).exists():
        fields['name'] = f'{base} ({n})'; n += 1
    with transaction.atomic():
        p = Programme.objects.create(created_by=user, lead=fields.pop('lead', None) or user, **fields)
        for i, s in enumerate(steps):
            ProgrammeStep.objects.create(programme=p, order=i, **s)
        if p.lead:
            ProgrammeMember.objects.get_or_create(programme=p, user=p.lead, defaults={'role': 'lead'})
    return p


# ------------------------------------------------------------------ who may see what
def is_member(user, programme):
    return programme.members.filter(user=user).exists() or programme.lead_id == user.pk


def can_manage(user, programme=None):
    from .access import has
    if user.is_superuser or has(user, 'programme_admin'):
        return True
    return bool(programme and (programme.lead_id == user.pk or programme.members.filter(user=user, role='lead').exists()))


def visible_programmes(user):
    from .access import has
    from .models_programmes import Programme
    qs = Programme.objects.all()
    if user.is_superuser or has(user, 'programme_admin'):
        return qs
    return qs.filter(Q(members__user=user) | Q(lead=user)).distinct()


def care_team_patient_ids(user):
    """Patients in an open enrolment of a programme this user works in: their care team may open the record between
    visits (chronic care happens between visits). Used by access.visible_patient_ids."""
    from .models_programmes import Enrolment
    if not getattr(user, 'pk', None):
        return set()
    return set(Enrolment.objects.filter(status__in=['active', 'paused', 'lost'])
               .filter(Q(programme__members__user=user) | Q(programme__lead=user) | Q(clinician=user) | Q(nurse=user))
               .values_list('patient_id', flat=True))


# ------------------------------------------------------------------ planning
def _first_due(enrolment, step):
    return enrolment.start + timedelta(days=step.offset_days)


def plan(enrolment, today=None):
    """Make sure every step has its next visit on the calendar. Returns the visits created."""
    from .models_programmes import ProgrammeVisit
    today = today or timezone.localdate()
    if enrolment.status != 'active':
        return []
    made = []
    visits = list(enrolment.visits.all())
    for step in enrolment.programme.steps.all():
        mine = [v for v in visits if v.step_id == step.pk]
        limit = enrolment.start + timedelta(days=step.until_days) if step.until_days is not None else None
        if not step.repeat_days:
            if mine:
                continue
            due, title = _first_due(enrolment, step), step.name
            if due < enrolment.enrolled_on:                      # e.g. birth doses for a child enrolled at 5 months
                due, title = max(enrolment.enrolled_on, today), f'{step.name} (catch-up)'
        else:
            if any(v.status in OPEN for v in mine):
                continue
            done = sorted([v for v in mine if v.status == 'attended'], key=lambda v: v.attended_on or v.due)
            if done:
                last = done[-1]
                gap = last.days_supply or step.days_supply or step.repeat_days
                due = (last.attended_on or last.due) + timedelta(days=gap)
            elif mine:                                           # only cancelled ones: carry on from the last planned day
                due = max(v.due for v in mine) + timedelta(days=step.repeat_days)
            else:
                due = _first_due(enrolment, step)
                if due < enrolment.enrolled_on:
                    due = enrolment.enrolled_on
            title = step.name
        if limit and due > limit:
            continue
        v = ProgrammeVisit.objects.create(enrolment=enrolment, step=step, title=title[:120], kind=step.kind, due=due,
                                          items_planned=list(step.items or []), days_supply=step.days_supply if step.kind == 'refill' else None)
        made.append(v)
    return made


def enrol(programme, patient, user=None, **fields):
    from .models_programmes import Enrolment
    with transaction.atomic():
        e = Enrolment.objects.create(programme=programme, patient=patient, enrolled_by=user, **fields)
        plan(e)
    return e


def record_visit(visit, user, attended_on=None, items_done=None, measures=None, days_supply=None, note='', encounter=None, next_due=None):
    """The patient came. The next refill is planned from what they were given; a lost patient is back in care."""
    e = visit.enrolment
    visit.status, visit.attended_on, visit.recorded_by = 'attended', attended_on or timezone.localdate(), user
    visit.items_done = list(items_done or [])
    visit.measures = {k: v for k, v in (measures or {}).items() if k in MEASURES and str(v).strip() != ''}
    if days_supply:
        visit.days_supply = days_supply
    visit.note, visit.encounter = note or visit.note, encounter or visit.encounter
    visit.save()
    returned = False
    if e.status == 'lost':
        e.status, e.lost_since, returned = 'active', None, True
        e.save(update_fields=['status', 'lost_since', 'updated_at'])
    created = plan(e)
    if next_due and created:                          # the clinician chose a different day for the next visit
        nxt = next((v for v in created if v.step_id == visit.step_id), None)
        if nxt:
            nxt.rescheduled_from, nxt.due = nxt.due, next_due
            nxt.save(update_fields=['due', 'rescheduled_from', 'updated_at'])
    return {'returned': returned, 'planned': created}


def reschedule(visit, new_due):
    visit.rescheduled_from = visit.rescheduled_from or visit.due
    visit.due, visit.status, visit.missed_at, visit.reminded_at, visit.escalated_at = new_due, 'scheduled', None, None, None
    visit.save()
    e = visit.enrolment
    if e.status == 'lost':
        e.status, e.lost_since = 'active', None
        e.save(update_fields=['status', 'lost_since', 'updated_at'])
    return visit


def set_status(enrolment, status, today=None):
    """End, pause or restart an enrolment. Ending it cancels the visits still planned."""
    today = today or timezone.localdate()
    enrolment.status = status
    enrolment.ended_on = today if status in ('completed', 'transferred', 'died', 'withdrawn') else None
    if status != 'lost':
        enrolment.lost_since = None
    enrolment.save()
    if status in ('completed', 'transferred', 'died', 'withdrawn', 'paused'):
        enrolment.visits.filter(status__in=['scheduled', 'reminded'] + (['missed'] if status != 'paused' else [])).update(status='cancelled')
    if status == 'active':
        plan(enrolment, today)


# ------------------------------------------------------------------ messages to patients
def _first(p):
    return (p.first_name or '').split()[0] if p.first_name else ''


def message_text(enrolment, visit, kind):
    pr, p = enrolment.programme, enrolment.patient
    custom = pr.reminder_text if kind == 'reminder' else pr.missed_text
    if custom:
        text = custom
    elif kind == 'reminder':
        text = ('Hello {name}, this is a reminder of your appointment at {clinic} on {date}. Please bring your clinic card.' if pr.discreet else
                'Hello {name}, this is a reminder of your {programme} appointment at {clinic} on {date}. Please bring your clinic card.')
    else:
        text = ('Hello {name}, we missed you at {clinic} on {date}. Please come as soon as you can, or call us to agree a new day.' if pr.discreet else
                'Hello {name}, we missed you at your {programme} appointment at {clinic} on {date}. Please come as soon as you can, or call us to agree a new day.')
    out = text.format_map(defaultdict(str, name=_first(p), clinic=clinic_name(), date=visit.due.strftime('%a %d %b'), programme=pr.name))
    if pr.discreet:                                   # never name the condition, even in a custom text
        out = re.sub(rf'(?i)\b{re.escape(pr.name)}\b', 'clinic', out)
        out = re.sub(r'(?i)\b(hiv|aids|art|antiretroviral|tb|tuberculosis|mental health|psychiatr\w*)\b', '', out)
        out = re.sub(r'\s{2,}', ' ', out).strip()
    return out[:480]


def phone_for(enrolment):
    from .phones import digits
    d = digits(enrolment.contact_phone or enrolment.patient.phone)
    if len(d) == 7:                                   # Gambian local number
        d = '220' + d
    return d


def dispatch(msg):
    """Send now when a channel can send by itself; otherwise leave it in the outbox for staff."""
    e = msg.enrolment
    try:
        if msg.channel == 'email':
            if not e.patient.email:
                msg.status, msg.error = 'pending', 'No email address: send another way.'
            else:
                from django.core.mail import send_mail
                send_mail(f'{clinic_name()}: appointment', msg.text, settings.DEFAULT_FROM_EMAIL, [e.patient.email], fail_silently=False)
                msg.status, msg.sent_at, msg.to = 'sent', timezone.now(), e.patient.email
        elif msg.channel == 'sms' and getattr(settings, 'PROGRAMME_SMS_URL', ''):
            import urllib.request
            body = json.dumps({'to': msg.to, 'message': msg.text}).encode()
            req = urllib.request.Request(settings.PROGRAMME_SMS_URL, data=body, method='POST',
                                         headers={'Content-Type': 'application/json', 'Authorization': f"Bearer {getattr(settings, 'PROGRAMME_SMS_TOKEN', '')}"})
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status >= 300:
                    raise RuntimeError(f'gateway answered {r.status}')
            msg.status, msg.sent_at = 'sent', timezone.now()
        else:
            msg.status = 'pending'                    # WhatsApp, a call, or SMS without a gateway: staff send it
    except Exception as exc:
        msg.status, msg.error = 'failed', f'{exc.__class__.__name__}: {exc}'[:300]
    msg.save()
    return msg


def queue_message(visit, kind):
    from .models_programmes import ProgrammeMessage
    e = visit.enrolment
    if not e.consent_reminders or e.channel == 'none':
        return None
    if visit.messages.filter(kind=kind).exists():
        return None
    m = ProgrammeMessage.objects.create(enrolment=e, visit=visit, kind=kind, channel=e.channel, to=phone_for(e) if e.channel != 'email' else e.patient.email,
                                        text=message_text(e, visit, kind))
    return dispatch(m)


def send_links(msg):
    """One-tap links for staff: WhatsApp, SMS and a phone call, with the message filled in."""
    from urllib.parse import quote
    d = msg.to if msg.channel != 'email' else phone_for(msg.enrolment)
    return {'whatsapp': f'https://wa.me/{d}?text={quote(msg.text)}' if d else '', 'sms': f'sms:+{d}?body={quote(msg.text)}' if d else '',
            'call': f'tel:+{d}' if d else '', 'email': f'mailto:{msg.enrolment.patient.email}?subject={quote("Appointment")}&body={quote(msg.text)}' if msg.enrolment.patient.email else ''}


# ------------------------------------------------------------------ the daily sweep
def _staff_for(e):
    people = [e.clinician, e.nurse]
    people += [m.user for m in e.programme.members.all() if m.notify]
    seen, out = set(), []
    for u in people:                     # someone can be both the responsible nurse and a team member: count them once
        if u and u.is_active and u.pk not in seen:
            seen.add(u.pk); out.append(u)
    return out


def sweep(today=None):
    """Plan, remind, mark missed, notify, escalate and mark lost to follow-up. Safe to run as often as you like."""
    from .models_programmes import Enrolment, ProgrammeVisit
    from .notify import notify
    today = today or timezone.localdate()
    now = timezone.now()
    out = Counter()
    for e in Enrolment.objects.filter(status='active', programme__active=True).select_related('programme', 'patient'):
        out['planned'] += len(plan(e, today))
    # reminders before the visit
    for v in (ProgrammeVisit.objects.filter(status='scheduled', reminded_at__isnull=True, due__gte=today, enrolment__status='active', enrolment__programme__active=True)
              .select_related('enrolment__programme', 'enrolment__patient')):
        if (v.due - today).days > v.enrolment.programme.reminder_days:
            continue
        m = queue_message(v, 'reminder')
        v.reminded_at = now
        if m:
            v.status = 'reminded'; out['reminders'] += 1
        v.save(update_fields=['reminded_at', 'status', 'updated_at'])
    # missed visits
    missed_by = defaultdict(lambda: defaultdict(int))        # user -> programme -> count
    for v in (ProgrammeVisit.objects.filter(status__in=['scheduled', 'reminded'], enrolment__status='active', enrolment__programme__active=True)
              .select_related('enrolment__programme', 'enrolment__patient', 'enrolment__clinician', 'enrolment__nurse')
              .prefetch_related('enrolment__programme__members__user')):
        e = v.enrolment
        if (today - v.due).days <= e.programme.grace_days:
            continue
        v.status, v.missed_at = 'missed', now
        v.save(update_fields=['status', 'missed_at', 'updated_at'])
        if queue_message(v, 'missed'):
            v.missed_message_at = now
            v.save(update_fields=['missed_message_at', 'updated_at'])
        out['missed'] += 1
        for u in _staff_for(e):
            missed_by[u][e.programme] += 1
    for u, progs in missed_by.items():
        for pr, n in progs.items():
            notify([u], f'{pr.name}: {n} missed visit{"s" if n != 1 else ""}',
                   f'{n} patient{"s" if n != 1 else ""} did not come for a planned visit. Open the programme to trace them.',
                   url=reverse('programme_detail', args=[pr.pk]) + '?tab=missed', kind='programme')
    # escalate misses nobody has traced
    lead_counts = defaultdict(lambda: defaultdict(int))
    for v in (ProgrammeVisit.objects.filter(status='missed', escalated_at__isnull=True, enrolment__status='active')
              .select_related('enrolment__programme__lead')):
        pr = v.enrolment.programme
        if (today - v.due).days <= pr.grace_days + pr.escalate_days:
            continue
        if v.enrolment.tracing.filter(created_at__gte=v.missed_at or now, outcome__in=['reached', 'rescheduled']).exists():
            continue
        v.escalated_at = now
        v.save(update_fields=['escalated_at', 'updated_at'])
        out['escalated'] += 1
        if pr.lead:
            lead_counts[pr.lead][pr] += 1
    for u, progs in lead_counts.items():
        for pr, n in progs.items():
            notify([u], f'{pr.name}: {n} missed visit{"s" if n != 1 else ""} not traced',
                   f'Still not traced {pr.escalate_days} days after the grace period. Please assign follow-up.',
                   url=reverse('programme_detail', args=[pr.pk]) + '?tab=missed', kind='programme')
    # lost to follow-up
    lost = defaultdict(list)
    for e in Enrolment.objects.filter(status='active', visits__status='missed').distinct().select_related('programme__lead', 'clinician', 'nurse'):
        oldest = e.visits.filter(status='missed').order_by('due').first()
        if oldest and (today - oldest.due).days > e.programme.ltfu_days:
            e.status, e.lost_since = 'lost', today
            e.save(update_fields=['status', 'lost_since', 'updated_at'])
            out['lost'] += 1
            for u in {e.programme.lead, e.clinician, e.nurse} - {None}:
                lost[(u, e.programme)].append(e)
    for (u, pr), es in lost.items():
        notify([u], f'{pr.name}: {len(es)} patient{"s" if len(es) != 1 else ""} lost to follow-up',
               f'No visit for more than {pr.ltfu_days} days. They stay on the tracing list until they return or the enrolment is closed.',
               url=reverse('programme_detail', args=[pr.pk]) + '?tab=missed', kind='programme')
    from .models_programmes import Programme
    for pr in Programme.objects.filter(active=True, ai_enabled=True):
        if maybe_auto_summary(pr):
            out['summaries'] += 1
    return dict(out)


def ensure_swept(force=False):
    """Run the sweep at most every 30 minutes from page views, in case the background scheduler is not running."""
    from django.core.cache import cache
    if force or cache.add('programme-sweep-lock', 1, 30 * 60):
        try:
            return sweep()
        except Exception:            # the pages must work even if a sweep fails
            cache.delete('programme-sweep-lock')
            raise
    return None


# ------------------------------------------------------------------ risk, by rules (no AI)
def _bp(v):
    m = re.match(r'\s*(\d{2,3})\s*/\s*(\d{2,3})', str(v or ''))
    return (int(m.group(1)), int(m.group(2))) if m else None


def _num(v):
    try:
        return float(str(v).replace(',', '.'))
    except (TypeError, ValueError):
        return None


def latest_measures(visits):
    out = {}
    for v in sorted([v for v in visits if v.status == 'attended'], key=lambda v: v.attended_on or v.due):
        for k, val in (v.measures or {}).items():
            out[k] = (val, v.attended_on or v.due)
    return out


def risk(enrolment, visits=None, tracing=None, today=None):
    """(level, score, reasons) for a patient in a programme, worked out by rules."""
    today = today or timezone.localdate()
    visits = list(visits if visits is not None else enrolment.visits.all())
    tracing = list(tracing if tracing is not None else enrolment.tracing.all())
    pr, score, why = enrolment.programme, 0, []
    def bump(n, text):
        nonlocal score
        score += n; why.append(text)
    open_missed = [v for v in visits if v.status == 'missed']
    if open_missed:
        late = max((today - v.due).days for v in open_missed)
        bump(3 if late > 14 else 2, f'{late} days late for a visit')
    past = sorted([v for v in visits if v.status in ('attended', 'missed') and v.due <= today], key=lambda v: v.due)[-6:]
    if len(past) >= 3:
        on_time = sum(1 for v in past if v.status == 'attended' and v.attended_on and (v.attended_on - v.due).days <= pr.grace_days)
        rate = on_time / len(past)
        if rate < .6:
            bump(2, f'on time for {on_time} of the last {len(past)} visits')
        elif rate < .8:
            bump(1, f'on time for {on_time} of the last {len(past)} visits')
    streak = 0
    for v in reversed(past):
        if v.status != 'missed':
            break
        streak += 1
    if streak >= 2:
        bump(2, f'{streak} visits missed in a row')
    outcomes = [t.outcome for t in tracing[:4]]
    if outcomes.count('no_answer') + outcomes.count('wrong_number') >= 2:
        bump(1, 'cannot be reached by phone')
    if 'refused' in outcomes:
        bump(3, 'said they do not want to continue')
    lm = latest_measures(visits)
    if 'bp' in lm and _bp(lm['bp'][0]):
        s, d = _bp(lm['bp'][0])
        if s >= 160 or d >= 100:
            bump(2, f'blood pressure {s}/{d}')
        elif s >= 140 or d >= 90:
            bump(1, f'blood pressure {s}/{d} above target')
    checks = [('viral_load', lambda x: (3, f'viral load {int(x)} (not suppressed)') if x > 1000 else (1, f'viral load {int(x)} detectable') if x > 50 else None),
              ('hba1c', lambda x: (2, f'HbA1c {x}%') if x >= 9 else (1, f'HbA1c {x}% above target') if x >= 7 else None),
              ('adherence', lambda x: (2, f'adherence {int(x)}%') if x < 85 else (1, f'adherence {int(x)}%') if x < 95 else None),
              ('muac', lambda x: (3, f'MUAC {x} cm (severe wasting)') if x < 11.5 else (2, f'MUAC {x} cm (moderate wasting)') if x < 12.5 else None),
              ('phq9', lambda x: (2, f'PHQ-9 {int(x)} (moderately severe or worse)') if x >= 15 else None),
              ('pain_crises', lambda x: (2, f'{int(x)} pain crises since last visit') if x >= 2 else None)]
    for k, rule in checks:
        x = _num(lm.get(k, (None,))[0]) if k in lm else None
        r = rule(x) if x is not None else None
        if r:
            bump(*r)
    if str(lm.get('side_effects', ('',))[0]) == 'serious':
        bump(2, 'serious side effects')
    if str(lm.get('sputum', ('',))[0]) == 'positive' and (today - enrolment.start).days >= 56:
        bump(2, 'sputum still positive after 2 months')
    level = 'high' if score >= 5 else 'medium' if score >= 2 else 'low'
    return level, score, why


# ------------------------------------------------------------------ programme numbers
def stats(programme, today=None):
    from .models_programmes import ProgrammeVisit
    today = today or timezone.localdate()
    es = programme.enrolments.all()
    by = Counter(es.values_list('status', flat=True))
    vq = ProgrammeVisit.objects.filter(enrolment__programme=programme)
    recent = list(vq.filter(due__gte=today - timedelta(days=90), due__lt=today - timedelta(days=programme.grace_days)).exclude(status='cancelled')
                  .values('status', 'due', 'attended_on'))
    done = [v for v in recent if v['status'] in ('attended', 'missed')]
    on_time = sum(1 for v in done if v['status'] == 'attended' and v['attended_on'] and (v['attended_on'] - v['due']).days <= programme.grace_days)
    old = es.filter(enrolled_on__lte=today - timedelta(days=180))
    retained = old.filter(status__in=['active', 'paused', 'completed']).count()
    weeks = []
    for i in range(11, -1, -1):
        start = today - timedelta(days=today.weekday()) - timedelta(weeks=i)
        wk = [v for v in vq.filter(due__gte=start, due__lt=start + timedelta(days=7)).exclude(status='cancelled').values('status')]
        weeks.append({'label': start.strftime('%d %b'), 'attended': sum(1 for v in wk if v['status'] == 'attended'),
                      'missed': sum(1 for v in wk if v['status'] == 'missed'), 'planned': sum(1 for v in wk if v['status'] in ('scheduled', 'reminded'))})
    return {
        'active': by['active'], 'paused': by['paused'], 'lost': by['lost'], 'closed': sum(by[k] for k in ('completed', 'transferred', 'died', 'withdrawn')),
        'due_today': vq.filter(due__lte=today, status__in=['scheduled', 'reminded'], enrolment__status='active').count(),   # today and overdue within the grace period
        'due_week': vq.filter(due__gt=today, due__lte=today + timedelta(days=7), status__in=['scheduled', 'reminded'], enrolment__status='active').count(),
        'missed': vq.filter(status='missed', enrolment__status__in=['active', 'lost']).count(),
        'on_time_pct': round(100 * on_time / len(done)) if done else None, 'on_time_n': len(done),
        'retention_pct': round(100 * retained / old.count()) if old.count() else None, 'retention_n': old.count(),
        'weeks': weeks, 'week_max': max([w['attended'] + w['missed'] + w['planned'] for w in weeks] + [1]),
        'pending_messages': programme.enrolments.filter(messages__status__in=['pending', 'failed']).count(),
    }


def patterns(programme, today=None):
    """Plain findings for the team, without AI: why visits are missed, which weekday, and how well controlled people are."""
    from .models_programmes import ProgrammeVisit, TracingAttempt
    today = today or timezone.localdate()
    out = []
    reasons = Counter(TracingAttempt.objects.filter(enrolment__programme=programme, created_at__gte=timezone.now() - timedelta(days=180))
                      .exclude(reason='').values_list('reason', flat=True))
    if reasons:
        top = ', '.join(f'{MISS_REASON_LABEL.get(k, k).lower()} ({n})' for k, n in reasons.most_common(3))
        out.append(('info', 'chat-left-quote', f'Most common reasons for missing a visit (last 6 months): {top}.'))
    missed = list(ProgrammeVisit.objects.filter(enrolment__programme=programme, status='missed', due__gte=today - timedelta(days=180)).values_list('due', flat=True))
    if len(missed) >= 5:
        day, n = Counter(d.strftime('%A') for d in missed).most_common(1)[0]
        if n / len(missed) >= .3:
            out.append(('warn', 'calendar-x', f'{round(100 * n / len(missed))}% of missed visits fall on a {day}. Consider moving those appointments.'))
    latest = {}
    for v in (ProgrammeVisit.objects.filter(enrolment__programme=programme, enrolment__status='active', status='attended').exclude(measures={})
              .order_by('attended_on').values('enrolment_id', 'measures')):
        latest.setdefault(v['enrolment_id'], {}).update(v['measures'])
    def share(key, ok):
        vals = [m[key] for m in latest.values() if key in m]
        good = [x for x in vals if ok(x)]
        return (len(good), len(vals)) if vals else None
    for key, ok, text in [('bp', lambda x: (_bp(x) or (999, 999))[0] < 140 and (_bp(x) or (999, 999))[1] < 90, 'have blood pressure below 140/90'),
                          ('viral_load', lambda x: (_num(x) or 1e9) < 1000, 'are virally suppressed (<1000 copies/mL)'),
                          ('hba1c', lambda x: (_num(x) or 99) < 7, 'have HbA1c below 7%'),
                          ('adherence', lambda x: (_num(x) or 0) >= 95, 'report adherence of 95% or more')]:
        s = share(key, ok)
        if s and s[1] >= 3:
            pct = round(100 * s[0] / s[1])
            out.append(('ok' if pct >= 80 else 'warn', 'bullseye', f'{pct}% of patients with a recent reading {text} ({s[0]} of {s[1]}).'))
    return out


# ------------------------------------------------------------------ eligible patients not yet enrolled
def eligible(programme, limit=60):
    from .models import Condition, Encounter, Patient
    enrolled = set(programme.enrolments.filter(status__in=['active', 'paused', 'lost']).values_list('patient_id', flat=True))
    found = {}
    words = KEYWORDS.get(programme.kind, [])
    if words:
        rx = re.compile('|'.join(w if w.startswith('\\b') else re.escape(w) for w in words), re.I)
        for pid, name in Condition.objects.filter(status='active').values_list('patient_id', 'name'):
            if pid not in enrolled and rx.search(name or ''):
                found.setdefault(pid, f'Condition: {name}')
        for pid, dx in Encounter.objects.exclude(diagnosis='').order_by('-created_at').values_list('patient_id', 'diagnosis')[:3000]:
            if pid not in enrolled and rx.search(dx or ''):
                found.setdefault(pid, f'Diagnosis: {dx[:60]}')
    if programme.kind == 'hypertension':
        for e in Encounter.objects.exclude(vitals={}).order_by('-created_at').values('patient_id', 'vitals')[:2000]:
            bp = _bp((e['vitals'] or {}).get('bp'))
            if e['patient_id'] not in enrolled and bp and (bp[0] >= 140 or bp[1] >= 90):
                found.setdefault(e['patient_id'], f'Blood pressure {bp[0]}/{bp[1]} at a visit')
    if programme.kind in ('immunisation', 'nutrition'):
        cutoff = timezone.localdate() - timedelta(days=2 * 365 if programme.kind == 'immunisation' else 5 * 365)
        for pid in Patient.objects.filter(dob__gte=cutoff, deceased_at__isnull=True).values_list('pk', flat=True):
            if pid not in enrolled:
                found.setdefault(pid, 'Child under 2' if programme.kind == 'immunisation' else 'Child under 5')
    pats = {p.pk: p for p in Patient.objects.filter(pk__in=list(found)[:limit * 2], deceased_at__isnull=True)}
    return [(pats[k], why) for k, why in found.items() if k in pats][:limit]


# ------------------------------------------------------------------ AI: de-identified only, behind a firewall
class PIIBlocked(Exception):
    """The privacy check found something that could identify a patient: nothing was sent."""


def _age_band(p):
    a = p.age
    if a is None:
        return 'unknown'
    if a < 1:
        return 'under 1'
    if a < 5:
        return '1-4'
    if a < 18:
        return '5-17'
    return f'{a // 10 * 10}-{a // 10 * 10 + 9}'


def _small(n):
    """Hide small numbers (1-4) in aggregates so nobody can be singled out."""
    return '<5' if 0 < n < 5 else n


def pii_tokens(patients):
    toks = set()
    for p in patients:
        for name in (p.first_name or '').split() + (p.last_name or '').split():
            if len(name) >= 3:
                toks.add(('name', name.lower()))
        toks.add(('record number', (p.mrn or '').lower()))
        for ph in [p.phone, p.emergency_contact] + [e.contact_phone for e in p.enrolments.all()]:
            for d in re.findall(r'\d{6,}', re.sub(r'[\s\-().+]', '', ph or '')):
                toks.add(('phone', d))
                if len(d) > 7:
                    toks.add(('phone', d[-7:]))          # the local number without the 220 country code
        if p.email:
            toks.add(('email', p.email.lower()))
        if p.dob:
            for f in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d %b %Y'):
                toks.add(('date of birth', p.dob.strftime(f).lower()))
        for chunk in re.split(r'[,\n]', p.address or ''):
            if len(chunk.strip()) >= 6:
                toks.add(('address', chunk.strip().lower()))
    return {t for t in toks if t[1]}


def firewall(ctx, patients):
    """Raise PIIBlocked when the context contains anything that identifies a patient, or any real date or record number."""
    text = json.dumps(ctx, ensure_ascii=False, default=str).lower()
    found = set()
    for kind, tok in pii_tokens(patients):
        if re.search(rf'(?<![\w]){re.escape(tok)}(?![\w])', text):
            found.add(kind)
    if re.search(r'\bmf-[0-9a-f]{6,}\b', text):
        found.add('record number')
    if re.search(r'\b(19|20)\d\d-\d\d-\d\d\b|\b\d{1,2}/\d{1,2}/(19|20)\d\d\b', text):
        found.add('date')
    if re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', text):
        found.add('email')
    if re.search(r'\+?\d[\d ]{8,}\d', text) or re.search(r'(?<![\d.])\d{3}[\s-]\d{4}(?![\d.])', text):
        found.add('phone-like number')
    if found:
        raise PIIBlocked('Not sent: the request contained ' + ', '.join(sorted(found)) + '.')
    return True


def cohort_context(programme, today=None):
    """Aggregate numbers only, small numbers hidden. No patient appears individually."""
    from .models_programmes import ProgrammeVisit, TracingAttempt
    today = today or timezone.localdate()
    es = list(programme.enrolments.select_related('patient'))
    st = stats(programme, today)
    ages = Counter(_age_band(e.patient) for e in es if e.open)
    sexes = Counter(e.patient.sex for e in es if e.open)
    months = []
    for i in range(6, 0, -1):
        a, b = today - timedelta(days=30 * i), today - timedelta(days=30 * (i - 1))
        vs = list(ProgrammeVisit.objects.filter(enrolment__programme=programme, due__gte=a, due__lt=b).exclude(status='cancelled').values_list('status', flat=True))
        months.append({'month': f'-{i}', 'attended': _small(vs.count('attended')), 'missed': _small(vs.count('missed'))})
    reasons = Counter(TracingAttempt.objects.filter(enrolment__programme=programme).exclude(reason='').values_list('reason', flat=True))
    outcomes = Counter(TracingAttempt.objects.filter(enrolment__programme=programme).values_list('outcome', flat=True))
    levels = Counter(risk(e)[0] for e in es if e.status == 'active')
    return {
        'programme_type': programme.get_kind_display(),
        'visit_plan': [{'step': s.name, 'type': s.get_kind_display(), 'day': s.offset_days, 'repeat_every_days': s.repeat_days} for s in programme.steps.all()],
        'rules': {'grace_days': programme.grace_days, 'lost_to_follow_up_after_days': programme.ltfu_days, 'reminder_days_before': programme.reminder_days},
        'patients': {k: _small(v) for k, v in {'active': st['active'], 'paused': st['paused'], 'lost_to_follow_up': st['lost'], 'closed': st['closed']}.items()},
        'age_bands': {k: _small(v) for k, v in ages.items()}, 'sex': {k: _small(v) for k, v in sexes.items()},
        'on_time_percent_last_90_days': st['on_time_pct'], 'retention_percent_at_6_months': st['retention_pct'],
        'missed_visits_open': _small(st['missed']), 'monthly_visits': months,
        'reasons_for_missing': {MISS_REASON_LABEL.get(k, k): _small(v) for k, v in reasons.items()},
        'tracing_outcomes': {k: _small(v) for k, v in outcomes.items()},
        'risk_levels': {k: _small(v) for k, v in levels.items()},
        'control_findings': [t for _lvl, _icon, t in patterns(programme, today) if '%' in t],
        'by_step_last_180_days': step_counts(programme, today),
        'last_visit_day': day_activity(programme, last_visit_day(programme, today)),
    }


def step_counts(programme, today):
    from .models_programmes import ProgrammeVisit
    rows = Counter((v['title'].replace(' (catch-up)', ''), v['status']) for v in ProgrammeVisit.objects.filter(
        enrolment__programme=programme, due__gte=today - timedelta(days=180), due__lte=today).values('title', 'status'))
    steps = sorted({t for t, _s in rows})
    return [{'step': s, 'attended': _small(rows[(s, 'attended')]), 'missed': _small(rows[(s, 'missed')])} for s in steps]


def last_visit_day(programme, upto):
    """The most recent day, up to `upto`, on which visits happened or were missed in this programme."""
    from .models_programmes import ProgrammeVisit
    vq = ProgrammeVisit.objects.filter(enrolment__programme=programme)
    days = [vq.filter(attended_on__lte=upto).order_by('-attended_on').values_list('attended_on', flat=True).first(),
            vq.filter(status='missed', due__lte=upto).order_by('-due').values_list('due', flat=True).first()]
    days = [d for d in days if d]
    return max(days) if days else None


def day_activity(programme, day):
    """What happened on one visit day, as counts (the day itself is not sent)."""
    from .models_programmes import ProgrammeVisit
    if not day:
        return None
    vq = ProgrammeVisit.objects.filter(enrolment__programme=programme)
    came = list(vq.filter(attended_on=day).values('due', 'measures'))
    return {'came': _small(len(came)), 'came_late': _small(sum(1 for v in came if (day - v['due']).days > programme.grace_days)),
            'missed_that_day': _small(vq.filter(status='missed', due=day).count()),
            'new_enrolments': _small(programme.enrolments.filter(enrolled_on=day).count()),
            'days_ago': (timezone.localdate() - day).days}


def patient_context(enrolment, today=None):
    """One patient, pseudonymous: sex, age band, and the visit history in days since enrolment. No names, numbers,
    places, real dates, staff names or notes."""
    from .dr_flow_context import scrub
    today = today or timezone.localdate()
    e, p = enrolment, enrolment.patient
    rel = lambda d: (d - e.enrolled_on).days if d else None
    visits = sorted(e.visits.exclude(status='cancelled'), key=lambda v: v.due)
    level, score, why = risk(e, visits)
    return {
        'patient': {'sex': p.sex, 'age_band': _age_band(p), 'days_in_programme': (today - e.enrolled_on).days, 'status': e.get_status_display()},
        'programme_type': e.programme.get_kind_display(),
        'other_active_conditions': [scrub(c, p, 80) for c in p.conditions.filter(status='active').values_list('name', flat=True)][:8],
        'allergies': list(p.allergies.filter(status='active').values_list('substance', flat=True))[:8],
        'visits': [{'day_due': rel(v.due), 'type': v.get_kind_display(), 'status': v.status, 'came_days_late': (v.attended_on - v.due).days if v.attended_on else None,
                    'given': [str(i)[:40] for i in v.items_done], 'days_of_medicine_given': v.days_supply if v.status == 'attended' else None,
                    'measures': {MEASURES[k][0]: str(val)[:20] for k, val in (v.measures or {}).items() if k in MEASURES}}
                   for v in visits if v.due <= today + timedelta(days=60)][-15:],
        'tracing': [{'day': rel(timezone.localtime(t.created_at).date()), 'method': t.get_method_display(), 'outcome': t.get_outcome_display(),
                     'reason': MISS_REASON_LABEL.get(t.reason, '')} for t in e.tracing.all()[:8]],
        'risk_by_rules': {'level': level, 'reasons': why},
        'today_is_day': rel(today),
    }


COHORT_TASK = """You are writing the daily summary for the care team of a long-term treatment or prevention programme at a
hospital in The Gambia. Every team member reads it. Use only the aggregate, de-identified numbers provided (numbers 1-4 are
shown as "<5" on purpose). Start with one sentence: how the programme is doing. Then use exactly these headings:
## Since the last visit day
(who came, came late or missed on the last visit day, from "last_visit_day"; say if nothing happened)
## What stands out
(retention, missed visits, trends by month, reasons for missing, control of the condition)
## Interventions to try
(numbered, practical, low-cost, suited to the reasons given: e.g. appointment days, multi-month dispensing, community follow-up,
transport support, SMS reminders, adherence clubs, family planning of visits; each with a one-line reason)
## What to measure next month
Do not guess about individual patients. Do not invent numbers."""

PATIENT_TASK = """Write a short follow-up plan for the care team of this patient in a long-term programme.
Use only the de-identified data provided (days are counted from enrolment; there are no names, places or dates on purpose).
Use exactly these headings:
## Summary
(one or two sentences: engagement, control, risk)
## Likely barriers
(from the coded reasons, tracing outcomes and pattern of visits; say when it is unclear)
## Next contact
(numbered: what to say and do at the next call or visit, adherence support, what to check, tests that are due)
## Escalate if
(clear triggers to involve the doctor or programme lead)
Be respectful and non-judgemental. Never try to identify the patient. Do not invent results."""


QUESTION_TASK = """A member of the care team of this long-term programme asks the question below. Answer it for them, briefly
and practically, using only the aggregate, de-identified programme data provided (numbers 1-4 are shown as "<5" on
purpose) and general clinical and public-health knowledge. If the data cannot answer it, say so and say what the team
could record to answer it next time. Never try to identify or describe an individual patient. If the question asks for
personal details of a patient, explain that they are not shared with the AI and answer at programme level instead.
Question: """

SUMMARY_HOUR = 19        # from this hour the day's summary is made; otherwise the previous visit day is summarised


def ai_allowed(programme):
    from .medical_ai import enabled
    return bool(programme.ai_enabled and enabled())


def ai_context(run):
    if run.kind in ('cohort', 'question'):
        ctx = cohort_context(run.programme)
        if run.kind == 'question':
            ctx['question'] = run.question
        patients = [e.patient for e in run.programme.enrolments.select_related('patient').prefetch_related('patient__enrolments')]
    else:
        ctx = patient_context(run.enrolment)
        patients = [run.enrolment.patient]
    return ctx, patients


def digest(ctx):
    return hashlib.sha256(json.dumps(ctx, sort_keys=True, default=str).encode()).hexdigest()


def run_ai(pk):
    """Worker entry point: build the de-identified context, pass the firewall, ask, store the answer."""
    from . import medical_ai
    from .models_programmes import ProgrammeAIRun
    r = ProgrammeAIRun.objects.select_related('programme', 'enrolment__patient').get(pk=pk)
    if r.status not in ('queued', 'running'):
        return r
    r.status, r.model_name = 'running', medical_ai.model_name()
    r.save(update_fields=['status', 'model_name', 'updated_at'])
    try:
        if not ai_allowed(r.programme):
            raise RuntimeError('AI is switched off for this programme')
        ctx, patients = ai_context(r)
        firewall(ctx, patients)
        r.context_digest = digest(ctx)
        task = {'cohort': COHORT_TASK, 'question': QUESTION_TASK + r.question, 'patient': PATIENT_TASK}[r.kind]
        text, _sources, _ = medical_ai._ask(ctx, f'programme_{r.kind}', task, system=medical_ai.GENERAL_SYSTEM_PROMPT)
        if not (text or '').strip():
            raise RuntimeError('The AI service returned no text')
        r.text, r.status = text.strip(), 'done'
    except PIIBlocked as exc:
        r.status, r.error = 'blocked', str(exc)[:500]
    except Exception as exc:
        r.status, r.error = 'failed', f'{exc.__class__.__name__}: {exc}'[:500]
    r.finished_at = timezone.now()
    r.save()
    return r


def queue_ai(run):
    """Hand an AI request to the worker. If the worker cannot be reached, answer in a background thread so a page
    (or the sweep run from a page view) never waits for the AI."""
    from .tasks import programme_ai_task
    try:
        programme_ai_task.apply_async(args=[run.pk], retry=False)
    except Exception:
        import threading
        threading.Thread(target=run_ai, args=(run.pk,), daemon=True).start()
    return run


def maybe_auto_summary(programme, now=None):
    """Make the shared programme summary once per visit day. Returns the new run, or None when nothing is due."""
    from .models_programmes import ProgrammeAIRun
    if not ai_allowed(programme):
        return None
    now = timezone.localtime(now or timezone.now())
    upto = now.date() if now.hour >= SUMMARY_HOUR else now.date() - timedelta(days=1)
    day = last_visit_day(programme, upto)
    if not day:
        return None
    runs = ProgrammeAIRun.objects.filter(programme=programme, kind='cohort')
    if runs.filter(auto=True, covers_day__gte=day).exclude(status='failed').exists():
        return None
    if any(r.busy for r in runs.filter(status__in=['queued', 'running'])):
        return None
    if runs.filter(auto=True, covers_day=day, status='failed').count() >= 3:
        return None                                   # stop retrying a day the AI keeps failing on
    r = ProgrammeAIRun.objects.create(programme=programme, kind='cohort', auto=True, covers_day=day)
    return queue_ai(r)


def check_question(programme, text):
    """Raise PIIBlocked if a question mentions anything that identifies a patient (before anything is saved or sent)."""
    patients = [e.patient for e in programme.enrolments.select_related('patient').prefetch_related('patient__enrolments')]
    return firewall({'question': text}, patients)


def latest_summary(programme):
    from .models_programmes import ProgrammeAIRun
    return ProgrammeAIRun.objects.filter(programme=programme, kind='cohort', status='done').first()
