"""The clinical library: general information about common diseases, joined with what this hospital has seen and done.

Everything about patients here is anonymous: no names, numbers or dates of birth; ages are shown in bands and dates as
months. A diagnosis with fewer than MIN_CASES cases shows no breakdowns, so nobody can be recognised from them.

The disease notes are short general summaries for orientation, written from WHO and similar guidance; they give no
doses and do not replace the national guidelines or senior advice. Dr. Flow can be asked for more on each page.
"""
import re
from collections import Counter, defaultdict
from datetime import timedelta

from django.utils import timezone
from django.utils.text import slugify

MIN_CASES = 3

# slug: (title, keywords, category, notes{summary, recognise, manage, refer}, source)
DISEASES = {
    'malaria': ('Malaria', ['malaria', 'plasmodium'], 'infectious', {
        'summary': 'A parasite infection spread by Anopheles mosquitoes; Plasmodium falciparum causes most severe disease in West Africa.',
        'recognise': 'Fever, chills, headache, body pains, vomiting. Danger signs: confusion or coma, convulsions, severe anaemia, breathing difficulty, jaundice, dark urine, unable to drink.',
        'manage': 'Confirm with a rapid test or blood film before treating. Uncomplicated: an artemisinin-based combination therapy (ACT). Severe: injectable artesunate, then a full ACT course. Treat fever and check glucose.',
        'refer': 'Any danger sign, pregnancy with severe illness, or not improving after 48 hours.',
        'prevent': 'Insecticide-treated nets, indoor spraying, seasonal malaria chemoprevention for children, preventive treatment in pregnancy.'},
        'WHO Guidelines for malaria'),
    'hypertension': ('Hypertension', ['hypertension', 'high blood pressure', 'hypertensive'], 'cardiovascular', {
        'summary': 'Blood pressure persistently at or above 140/90 mmHg. Usually silent, it is a leading cause of stroke, heart attack, heart failure and kidney disease.',
        'recognise': 'Repeated readings on different days. Look for headache, breathlessness, chest pain, weakness or blurred vision, which suggest organ damage.',
        'manage': 'Less salt, healthy weight, activity, no tobacco, limit alcohol. Medicines: a calcium-channel blocker, thiazide-like diuretic, or ACE inhibitor / angiotensin-receptor blocker, combined when needed. Most adults aim below 140/90.',
        'refer': 'Pressure of 180/120 or more with symptoms or organ damage (hypertensive emergency); pregnancy; young patients.',
        'prevent': 'Check blood pressure in every adult at least once a year.'},
        'WHO guideline for the pharmacological treatment of hypertension (2021)'),
    'diabetes': ('Diabetes mellitus', ['diabetes', 'diabetic', 'hyperglycaemia', 'hyperglycemia'], 'endocrine', {
        'summary': 'Raised blood glucose from too little insulin or insulin resistance. Type 2 is the most common in adults.',
        'recognise': 'Thirst, passing much urine, weight loss, infections, slow-healing wounds; often none. Fasting glucose 7.0 mmol/L or more, or HbA1c 6.5% or more.',
        'manage': 'Diet, activity and weight. Metformin first unless unsuitable; add a sulfonylurea or insulin as needed. Control blood pressure. Check eyes, feet, kidneys and HbA1c regularly.',
        'refer': 'Very high glucose with dehydration or drowsiness, ketoacidosis, foot ulcers, sight-threatening retinopathy.',
        'prevent': 'Healthy weight and activity; screen adults with risk factors.'},
        'WHO HEARTS-D and WHO PEN'),
    'pneumonia': ('Pneumonia', ['pneumonia', 'chest infection', 'lower respiratory tract infection'], 'respiratory', {
        'summary': 'Infection of the lung. A leading cause of death in young children.',
        'recognise': 'Cough, fever, fast breathing, chest indrawing in children, crackles. Oxygen saturation below 90% means severe pneumonia.',
        'manage': 'Oral amoxicillin for non-severe pneumonia in children; oxygen and injectable antibiotics for severe pneumonia. Check for HIV, TB and malnutrition when it recurs.',
        'refer': 'Low oxygen, unable to drink, convulsions, lethargy, or no improvement.',
        'prevent': 'Vaccines (pneumococcal, Hib, measles, pertussis), breastfeeding, clean cooking fuel.'},
        'WHO IMCI and pocket book of hospital care for children'),
    'tuberculosis': ('Tuberculosis', ['tuberculosis', ' tb ', 'pulmonary tb', 'ptb'], 'infectious', {
        'summary': 'Infection with Mycobacterium tuberculosis, usually of the lungs; curable with a full course of treatment.',
        'recognise': 'Cough for two weeks or more, fever, night sweats, weight loss, blood in sputum. Test sputum with a molecular test (GeneXpert) or microscopy.',
        'manage': 'A six-month combination regimen under the national TB programme, with support to complete it. Test for HIV. Trace and screen contacts.',
        'refer': 'Drug-resistant TB, TB meningitis, or very ill patients.',
        'prevent': 'Early diagnosis, infection control, BCG for infants, preventive treatment for contacts and people with HIV.'},
        'WHO consolidated guidelines on tuberculosis'),
    'sickle': ('Sickle cell disease', ['sickle'], 'blood', {
        'summary': 'An inherited haemoglobin disorder (HbSS and others) causing red cells to sickle and block small vessels.',
        'recognise': 'Painful crises, anaemia, jaundice, frequent infections. Emergencies: chest syndrome (chest pain, low oxygen), stroke, splenic sequestration, priapism.',
        'manage': 'Fluids, pain relief and warmth in crises; folic acid; malaria prevention; penicillin and vaccines for children; hydroxyurea for frequent crises. Transfuse for severe anaemia or stroke.',
        'refer': 'Chest syndrome, stroke signs, severe anaemia, fever in a child.',
        'prevent': 'Newborn screening and comprehensive care clinics.'},
        'WHO and national sickle cell guidance'),
    'diarrhoea': ('Diarrhoea and gastroenteritis', ['diarrhoea', 'diarrhea', 'gastroenteritis', 'dysentery'], 'digestive', {
        'summary': 'Loose stools, usually from infection. Dehydration is the main danger, especially in children.',
        'recognise': 'Assess dehydration: thirst, sunken eyes, slow skin pinch, lethargy. Blood in the stool means dysentery.',
        'manage': 'Oral rehydration salts and zinc for children; continue feeding. Severe dehydration: intravenous fluids. Antibiotics only for dysentery or cholera.',
        'refer': 'Severe dehydration, shock, or severe malnutrition.',
        'prevent': 'Safe water, handwashing, sanitation, rotavirus vaccine, breastfeeding.'},
        'WHO/UNICEF diarrhoea treatment guidance'),
    'typhoid': ('Typhoid fever', ['typhoid', 'enteric fever'], 'infectious', {
        'summary': 'Infection with Salmonella Typhi from contaminated food or water.',
        'recognise': 'Fever rising over days, headache, abdominal pain, constipation or diarrhoea. Blood culture is the best test.',
        'manage': 'Antibiotics chosen by local resistance patterns (for example azithromycin or ceftriaxone). Watch for bowel perforation and bleeding.',
        'refer': 'Severe abdominal pain or distension, confusion, bleeding.',
        'prevent': 'Safe water and food, sanitation, typhoid conjugate vaccine.'},
        'WHO typhoid guidance'),
    'hiv': ('HIV infection', [' hiv', 'hiv '], 'infectious', {
        'summary': 'A chronic virus infection that weakens immunity; with treatment people live long healthy lives.',
        'recognise': 'Offer testing widely. Advanced disease: TB, weight loss, oral thrush, recurrent infections.',
        'manage': 'Start antiretroviral therapy for everyone diagnosed (dolutegravir-based first line), monitor viral load, screen for TB, give cotrimoxazole where indicated.',
        'refer': 'Advanced disease, treatment failure, serious opportunistic infections.',
        'prevent': 'Testing, condoms, PrEP, preventing mother-to-child transmission.'},
        'WHO consolidated HIV guidelines'),
    'anaemia': ('Anaemia', ['anaemia', 'anemia'], 'blood', {
        'summary': 'Haemoglobin below the normal level for age, sex and pregnancy.',
        'recognise': 'Tiredness, breathlessness, pale palms and eyelids. Find the cause: iron deficiency, malaria, worms, blood loss, sickle cell, chronic disease.',
        'manage': 'Treat the cause; iron and folate for deficiency; deworming; malaria treatment. Transfuse only for severe anaemia with danger signs.',
        'refer': 'Heart failure, ongoing bleeding, or unexplained severe anaemia.',
        'prevent': 'Iron and folic acid in pregnancy, malaria prevention, deworming.'},
        'WHO haemoglobin thresholds and anaemia guidance'),
    'preeclampsia': ('Pre-eclampsia and eclampsia', ['pre-eclampsia', 'preeclampsia', 'eclampsia'], 'maternal', {
        'summary': 'High blood pressure after 20 weeks of pregnancy with protein in the urine or organ problems; eclampsia adds fits.',
        'recognise': 'Blood pressure 140/90 or more, headache, visual disturbance, upper abdominal pain, swelling, protein in urine.',
        'manage': 'Magnesium sulfate for severe pre-eclampsia and eclampsia, antihypertensives for severe blood pressure, and timely delivery.',
        'refer': 'All severe cases to a unit that can deliver the baby and care for the mother.',
        'prevent': 'Low-dose aspirin and calcium for women at high risk; regular antenatal blood pressure checks.'},
        'WHO recommendations for prevention and treatment of pre-eclampsia and eclampsia'),
    'asthma': ('Asthma', ['asthma'], 'respiratory', {
        'summary': 'Long-term inflammation of the airways with attacks of narrowing.',
        'recognise': 'Wheeze, cough, chest tightness, worse at night or with triggers. Severe attack: cannot complete sentences, low oxygen, silent chest.',
        'manage': 'Inhaled corticosteroid-containing treatment for control; reliever inhaler for symptoms; oxygen, bronchodilators and steroids in attacks. Check inhaler technique.',
        'refer': 'Life-threatening attacks, frequent admissions.',
        'prevent': 'Avoid smoke and triggers; regular review.'},
        'Global Initiative for Asthma (GINA)'),
    'uti': ('Urinary tract infection', ['urinary tract infection', ' uti ', 'pyelonephritis', 'cystitis'], 'renal', {
        'summary': 'Infection of the bladder (cystitis) or kidney (pyelonephritis).',
        'recognise': 'Burning on passing urine, frequency, lower abdominal pain; fever, flank pain and vomiting suggest kidney infection. Urinalysis and culture.',
        'manage': 'Antibiotics according to the local guideline and sensitivity; fluids; review if not better in 48 hours.',
        'refer': 'Sepsis, pregnancy with pyelonephritis, obstruction, recurrent infections in men or children.',
        'prevent': 'Fluids and prompt treatment.'},
        'WHO AWaRe antibiotic book'),
    'stroke': ('Stroke', ['stroke', 'cerebrovascular', ' cva '], 'neurological', {
        'summary': 'Loss of brain function from a blocked vessel (ischaemic) or bleeding (haemorrhagic).',
        'recognise': 'Sudden face droop, arm weakness, speech difficulty (FAST), vision loss, imbalance. Time matters.',
        'manage': 'Brain scan to tell clot from bleed; aspirin for ischaemic stroke once bleeding is excluded; manage blood pressure and glucose; check swallowing before feeding; early rehabilitation.',
        'refer': 'To a centre with CT and stroke care as fast as possible.',
        'prevent': 'Control blood pressure, diabetes, cholesterol; treat atrial fibrillation; stop smoking.'},
        'WHO and stroke care guidance'),
    'heart_failure': ('Heart failure', ['heart failure', 'cardiac failure', ' ccf ', 'cardiomyopathy'], 'cardiovascular', {
        'summary': 'The heart cannot pump enough blood for the body’s needs.',
        'recognise': 'Breathlessness on effort or lying flat, swollen legs, tiredness, raised neck veins, crackles. Echocardiogram confirms.',
        'manage': 'Diuretics for fluid overload; ACE inhibitor or ARB, beta-blocker and mineralocorticoid antagonist for reduced pumping; treat the cause (hypertension, valve disease); limit salt.',
        'refer': 'Breathless at rest, low blood pressure, new heart failure in the young.',
        'prevent': 'Control blood pressure; treat rheumatic heart disease.'},
        'WHO and cardiology society guidance'),
    'cataract': ('Cataract', ['cataract'], 'eye_ent', {
        'summary': 'Clouding of the eye’s lens; the leading cause of blindness worldwide and curable by surgery.',
        'recognise': 'Gradual painless blurring, glare, faded colours; grey or white pupil when dense.',
        'manage': 'Surgery (small-incision or phaco with a lens implant) when it limits daily life; glasses afterwards.',
        'refer': 'Children with cataract urgently; adults when vision limits work or safety.',
        'prevent': 'Sun protection and not smoking slow it; diabetes control.'},
        'WHO World report on vision'),
    'glaucoma': ('Glaucoma', ['glaucoma'], 'eye_ent', {
        'summary': 'Damage to the optic nerve, often with raised eye pressure, causing permanent loss of vision.',
        'recognise': 'Open-angle: no symptoms until late peripheral loss; large cup-to-disc ratio. Acute angle-closure: painful red eye, halos, vomiting, very high pressure — an emergency.',
        'manage': 'Pressure-lowering drops, laser, or surgery (trabeculectomy). Acute angle-closure: lower the pressure at once and refer.',
        'refer': 'Every suspected case to an eye specialist; acute angle-closure the same day.',
        'prevent': 'Eye pressure and disc checks for adults over 40, especially with a family history.'},
        'WHO World report on vision'),
    'otitis': ('Otitis media', ['otitis media', 'ear infection', 'glue ear', 'csom', 'suppurative otitis'], 'eye_ent', {
        'summary': 'Middle-ear infection or fluid. Chronic discharge through a perforation (CSOM) is a common cause of hearing loss.',
        'recognise': 'Acute: ear pain, fever, red bulging drum. Glue ear: dull drum with fluid and hearing loss. CSOM: discharge for two weeks or more with a perforation.',
        'manage': 'Acute: pain relief and antibiotics when indicated. Glue ear: watch, grommets if persistent with hearing loss. CSOM: dry mopping and antibiotic drops, repair once dry.',
        'refer': 'Swelling behind the ear, facial weakness, severe headache (complications), cholesteatoma.',
        'prevent': 'Vaccination, breastfeeding, avoiding smoke.'},
        'WHO primary ear and hearing care'),
    'hearing_loss': ('Hearing loss', ['hearing loss', 'deafness', 'presbycusis'], 'eye_ent', {
        'summary': 'Reduced hearing, graded by WHO from the average threshold in the better ear.',
        'recognise': 'Difficulty following speech, loud TV, tinnitus. Audiogram separates conductive from sensorineural loss.',
        'manage': 'Treat ear disease; hearing aids from moderate loss; cochlear implants for severe-to-profound loss; communication support.',
        'refer': 'Sudden hearing loss (emergency), one-sided loss, children with suspected loss.',
        'prevent': 'Protection from loud noise, vaccination, avoiding ear-toxic medicines.'},
        'WHO World report on hearing (2021)'),
    'diabetic_retinopathy': ('Diabetic retinopathy', ['diabetic retinopathy', 'diabetic maculopathy'], 'eye_ent', {
        'summary': 'Damage to the retina’s blood vessels from diabetes; a leading cause of preventable blindness in adults.',
        'recognise': 'Often no symptoms until late. Microaneurysms, haemorrhages and exudates; new vessels in proliferative disease.',
        'manage': 'Control glucose and blood pressure; laser or anti-VEGF injections for proliferative disease and maculopathy.',
        'refer': 'Severe or proliferative retinopathy and maculopathy.',
        'prevent': 'Retinal screening at least yearly for everyone with diabetes.'},
        'WHO and diabetic eye screening guidance'),
    'appendicitis': ('Appendicitis', ['appendicitis'], 'digestive', {
        'summary': 'Inflammation of the appendix; the most common abdominal surgical emergency.',
        'recognise': 'Pain starting around the navel and moving to the right lower abdomen, fever, vomiting, tenderness. Scores such as Alvarado and ultrasound help.',
        'manage': 'Appendicectomy with antibiotics; fluids and pain relief before surgery.',
        'refer': 'Suspected perforation or abscess needs urgent surgery.',
        'prevent': '—'},
        'Surgical society guidance'),
    'hernia': ('Inguinal hernia', ['hernia'], 'digestive', {
        'summary': 'Bowel or fat pushing through a weakness in the groin.',
        'recognise': 'A groin lump that comes and goes with standing or coughing. Painful, tense, irreducible lump means incarceration or strangulation.',
        'manage': 'Planned mesh repair; emergency surgery if strangulated.',
        'refer': 'Irreducible or painful hernia immediately.',
        'prevent': '—'},
        'Surgical society guidance'),
}

AGE_BANDS = [(0, 4, '0–4'), (5, 14, '5–14'), (15, 29, '15–29'), (30, 49, '30–49'), (50, 64, '50–64'), (65, 200, '65+')]


def _band(age):
    if age is None:
        return '?'
    return next(l for lo, hi, l in AGE_BANDS if lo <= age <= hi)


def _clean(dx):
    first = re.split(r'[;\n]|, ', dx.strip())[0].strip().rstrip('.')
    return first[:80]


# specific diagnoses are checked before general ones ("diabetic retinopathy" before "diabetes", "sickle cell anaemia" before "anaemia")
ORDER = ['diabetic_retinopathy', 'preeclampsia', 'cataract', 'glaucoma', 'otitis', 'hearing_loss', 'sickle', 'appendicitis', 'hernia',
         'tuberculosis', 'typhoid', 'malaria', 'pneumonia', 'stroke', 'heart_failure', 'hypertension', 'diabetes', 'hiv', 'asthma', 'uti',
         'diarrhoea', 'anaemia']


def match(dx):
    """(slug, title) of the curated disease this diagnosis is about: the one written first, the more specific keyword winning
    a tie ("diabetic retinopathy" over "diabetic"). Otherwise a slug made from the diagnosis's own first words."""
    text = ' ' + re.sub(r'[^a-z0-9-]+', ' ', dx.lower()) + ' '
    best = None
    for rank, slug in enumerate(ORDER):
        for k in DISEASES[slug][1]:
            i = text.find(k)
            if i >= 0:
                key = (i, -len(k), rank)
                if best is None or key < best[0]:
                    best = (key, slug)
    if best:
        return best[1], DISEASES[best[1]][0]
    label = _clean(dx)
    return 'dx-' + slugify(label)[:60], label[:1].upper() + label[1:]


def _cases():
    from .models import Encounter
    return Encounter.objects.exclude(diagnosis='').select_related('patient', 'department').order_by('-created_at')


def index(q='', cat=''):
    from .categories import INFO, classify
    groups = defaultdict(lambda: {'n': 0, 'recent': 0})
    since = timezone.now() - timedelta(days=90)
    from .models import Encounter
    for e in Encounter.objects.exclude(diagnosis='').only('diagnosis', 'created_at', 'category'):
        slug, title = match(e.diagnosis)
        g = groups[slug]
        g.update(slug=slug, title=title, curated=slug in DISEASES, cat=DISEASES[slug][2] if slug in DISEASES else (e.category or classify(e.diagnosis)))
        g['n'] += 1
        g['recent'] += e.created_at >= since
    for slug, (title, _k, catk, *_r) in DISEASES.items():   # curated notes are listed even before the first case
        if slug not in groups:
            groups[slug].update(slug=slug, title=title, curated=True, cat=catk)
    rows = list(groups.values())
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r['title'].lower() or (r['curated'] and any(ql in k for k in DISEASES[r['slug']][1]))]
    if cat:
        rows = [r for r in rows if r['cat'] == cat]
    rows.sort(key=lambda r: (-r['n'], r['title']))
    cats = Counter()
    for r in groups.values():
        cats[r['cat']] += r['n']
    return {'rows': rows, 'cats': [dict(INFO[k], n=n) for k, n in cats.most_common() if k in INFO and n]}


def detail(slug):
    """General notes plus the hospital's anonymous experience with this diagnosis."""
    from .models import LabOrder, PrescriptionItem, SurgicalCase
    encs = [e for e in _cases().prefetch_related('admissions') if match(e.diagnosis)[0] == slug]
    if slug in DISEASES:
        title, _k, catk, notes, source = DISEASES[slug]
    elif encs:
        title, notes, source, catk = match(encs[0].diagnosis)[1], None, None, encs[0].category
    else:
        return None
    out = {'slug': slug, 'title': title, 'notes': notes, 'source': source, 'cat': catk, 'n': len(encs), 'enough': len(encs) >= MIN_CASES,
           'min': MIN_CASES}
    # learning from deaths: published anonymised study cases (shown whatever the case count: each was checked before publishing)
    from .mortality import deaths_for_slug, published_cases
    out['study_cases'] = list(published_cases(slug)[:6])
    if not out['enough']:
        return out
    deaths = deaths_for_slug(slug)
    out['deaths'] = deaths if deaths >= MIN_CASES or deaths == 0 else None     # small numbers are hidden, like every other figure
    out['deaths_few'] = 0 < deaths < MIN_CASES
    ids = [e.pk for e in encs]
    outcomes = Counter(e.get_outcome_display() for e in encs if e.outcome)
    out['outcomes'] = [{'label': k, 'n': v, 'pct': round(v * 100 / max(1, sum(outcomes.values())))} for k, v in outcomes.most_common()]
    out['ages'] = [{'label': l, 'n': sum(1 for e in encs if _band(e.patient.age) == l)} for _lo, _hi, l in AGE_BANDS]
    out['sex'] = {'F': sum(1 for e in encs if e.patient.sex == 'F'), 'M': sum(1 for e in encs if e.patient.sex == 'M')}
    meds = Counter(PrescriptionItem.objects.filter(prescription__encounter_id__in=ids).values_list('medication__name', flat=True))
    out['meds'] = [{'name': k, 'n': v} for k, v in meds.most_common(8)]
    tests = Counter(LabOrder.objects.filter(encounter_id__in=ids).exclude(status='cancelled').values_list('test__name', flat=True))
    out['tests'] = [{'name': k, 'n': v} for k, v in tests.most_common(8)]
    ops = Counter(SurgicalCase.objects.filter(encounter_id__in=ids).exclude(status='cancelled').values_list('procedure', flat=True))
    out['operations'] = [{'name': k, 'n': v} for k, v in ops.most_common(6)]
    stays = []
    for e in encs:
        for a in e.admissions.all():
            end = a.discharged_at or timezone.now()
            stays.append((end - a.admitted_at).total_seconds() / 86400)
    out['admitted'] = len(stays)
    out['stay_days'] = round(sorted(stays)[len(stays) // 2], 1) if stays else None
    # cases per month for the last 12 months
    today = timezone.localdate()
    months = []
    for i in range(11, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12; y -= 1
        months.append((y, m))
    per = Counter((timezone.localtime(e.created_at).year, timezone.localtime(e.created_at).month) for e in encs)
    out['trend'] = [{'label': f'{m:02d}/{str(y)[2:]}', 'n': per.get((y, m), 0)} for y, m in months]
    out['peak'] = max(1, max(t['n'] for t in out['trend']))
    # anonymous case log: what was done and how it ended
    meds_by = defaultdict(set)
    for eid, name in PrescriptionItem.objects.filter(prescription__encounter_id__in=ids[:40]).values_list('prescription__encounter_id', 'medication__name'):
        meds_by[eid].add(name)
    ops_by = defaultdict(set)
    for eid, name in SurgicalCase.objects.filter(encounter_id__in=ids[:40]).exclude(status='cancelled').values_list('encounter_id', 'procedure'):
        ops_by[eid].add(name)
    out['log'] = [{'month': timezone.localtime(e.created_at).strftime('%b %Y'), 'age': _band(e.patient.age), 'sex': e.patient.sex,
                   'dept': str(e.department or ''), 'treatment': sorted(meds_by[e.pk])[:4], 'ops': sorted(ops_by[e.pk]),
                   'outcome': e.get_outcome_display() if e.outcome else ('Ongoing' if e.status == 'open' else '—'),
                   'admitted': e.admissions.exists()} for e in encs[:15]]
    return out
