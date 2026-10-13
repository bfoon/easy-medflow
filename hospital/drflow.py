"""Dr. Flow's advice while a doctor prescribes or orders tests, and the patient brief on the chart.

Rule-based and conservative, built on top of clinical.clinical_review (allergies, a few medicine/result combinations,
missing work-up). Added here: drug interactions, duplicate drug classes (also against medicines from the last 30
days), pregnancy, age, G6PD, results that change prescribing, maximum daily doses, duplicate or redundant tests and
tests to consider. Each finding names the reason and the kind of reference it comes from. Absence of a warning is not
proof of safety; a pharmacist still reviews every prescription."""
import re
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

LEVEL_ORDER = {'danger': 0, 'warn': 1, 'info': 2}
NON_SYSTEMIC = {'topical', 'eye', 'ear', 'nasal', 'inhaled'}

# ------------------------------------------------------------------ what each medicine is
CLASSES = {
    'nsaid': ['ibuprofen', 'diclofenac', 'naproxen', 'indometacin', 'meloxicam', 'piroxicam'],
    'aspirin': ['aspirin', 'acetylsalicylic'],
    'warfarin': ['warfarin'],
    'anticoagulant': ['warfarin', 'heparin', 'enoxaparin', 'rivaroxaban', 'apixaban', 'dabigatran'],
    'antiplatelet': ['aspirin', 'acetylsalicylic', 'clopidogrel'],
    'ace_inhibitor': ['lisinopril', 'enalapril', 'captopril', 'ramipril', 'perindopril'],
    'arb': ['losartan', 'valsartan', 'candesartan', 'telmisartan', 'irbesartan'],
    'k_sparing': ['spironolactone', 'amiloride', 'eplerenone', 'triamterene'],
    'potassium': ['potassium chloride', 'potassium citrate'],
    'loop_diuretic': ['furosemide', 'bumetanide', 'torasemide'],
    'thiazide': ['hydrochlorothiazide', 'bendroflumethiazide', 'chlortalidone', 'indapamide'],
    'beta_blocker': ['atenolol', 'propranolol', 'metoprolol', 'bisoprolol', 'carvedilol', 'labetalol'],
    'nonselective_bb': ['propranolol', 'carvedilol', 'labetalol', 'timolol'],
    'aminoglycoside': ['gentamicin', 'amikacin', 'streptomycin', 'kanamycin'],
    'fluoroquinolone': ['ciprofloxacin', 'levofloxacin', 'ofloxacin', 'moxifloxacin', 'norfloxacin'],
    'tetracycline': ['doxycycline', 'tetracycline', 'minocycline'],
    'macrolide_cyp': ['erythromycin', 'clarithromycin'],
    'opioid': ['morphine', 'pethidine', 'tramadol', 'codeine', 'fentanyl', 'oxycodone'],
    'tramadol': ['tramadol'],
    'codeine': ['codeine'],
    'sedative': ['diazepam', 'lorazepam', 'midazolam', 'chlordiazepoxide', 'phenobarbital', 'clonazepam'],
    'benzodiazepine': ['diazepam', 'lorazepam', 'midazolam', 'chlordiazepoxide', 'clonazepam'],
    'ssri': ['fluoxetine', 'sertraline', 'paroxetine', 'citalopram', 'escitalopram'],
    'tca': ['amitriptyline', 'imipramine', 'nortriptyline', 'clomipramine'],
    'rifampicin': ['rifampicin', 'rifampin'],
    'isoniazid': ['isoniazid'],
    'inducer': ['carbamazepine', 'phenytoin', 'phenobarbital'],
    'dolutegravir': ['dolutegravir'],
    'hormonal_contraceptive': ['levonorgestrel', 'ethinylestradiol', 'norethisterone', 'medroxyprogesterone', 'desogestrel', 'etonogestrel'],
    'lumefantrine': ['lumefantrine'],
    'antimalarial': ['lumefantrine', 'artemether', 'artesunate', 'quinine', 'amodiaquine', 'dihydroartemisinin', 'chloroquine'],
    'qt': ['quinine', 'haloperidol', 'erythromycin', 'clarithromycin', 'azithromycin', 'ciprofloxacin', 'levofloxacin', 'moxifloxacin',
           'amitriptyline', 'chloroquine', 'ondansetron', 'fluconazole', 'citalopram', 'escitalopram'],
    'statin': ['atorvastatin', 'simvastatin', 'rosuvastatin', 'pravastatin'],
    'metformin': ['metformin'],
    'sulfonylurea': ['glibenclamide', 'gliclazide', 'glimepiride', 'glipizide'],
    'methotrexate': ['methotrexate'],
    'cotrimoxazole': ['co-trimoxazole', 'cotrimoxazole', 'sulfamethoxazole'],
    'metronidazole': ['metronidazole', 'tinidazole'],
    'chelating': ['ferrous', 'iron', 'zinc', 'calcium carbonate', 'magnesium trisilicate', 'aluminium hydroxide', 'antacid'],
    'steroid': ['prednisolone', 'hydrocortisone', 'dexamethasone', 'methylprednisolone'],
    'digoxin': ['digoxin'],
    'valproate': ['valproate', 'valproic'],
    'misoprostol': ['misoprostol'],
    'ergometrine': ['ergometrine', 'methylergometrine'],
    'oxidant': ['primaquine', 'dapsone', 'nitrofurantoin', 'rasburicase', 'methylene blue', 'tafenoquine'],
    'nitrofurantoin': ['nitrofurantoin'],
    'chloramphenicol': ['chloramphenicol'],
    'ceftriaxone': ['ceftriaxone'],
    'calcium_iv': ['calcium gluconate', 'calcium chloride'],
    'antidopamine': ['metoclopramide', 'haloperidol', 'chlorpromazine', 'prochlorperazine'],
    'promethazine': ['promethazine'],
    'albendazole': ['albendazole', 'mebendazole'],
    'paracetamol': ['paracetamol', 'acetaminophen'],
    'antibiotic': ['amoxicillin', 'ampicillin', 'penicillin', 'cloxacillin', 'flucloxacillin', 'ceftriaxone', 'cefuroxime', 'cefalexin',
                   'cefixime', 'ciprofloxacin', 'levofloxacin', 'metronidazole', 'gentamicin', 'azithromycin', 'erythromycin',
                   'clarithromycin', 'doxycycline', 'tetracycline', 'co-trimoxazole', 'cotrimoxazole', 'nitrofurantoin', 'chloramphenicol'],
    'anti_tb': ['rifampicin', 'isoniazid', 'pyrazinamide', 'ethambutol'],
}
# classes where two different medicines at once is usually a duplication
DUPLICATE_CLASSES = {'nsaid': 'NSAIDs', 'beta_blocker': 'beta-blockers', 'opioid': 'opioids', 'benzodiazepine': 'benzodiazepines',
                     'ssri': 'SSRIs', 'statin': 'statins', 'sulfonylurea': 'sulfonylureas', 'fluoroquinolone': 'fluoroquinolones',
                     'ace_inhibitor': 'ACE inhibitors', 'arb': 'angiotensin receptor blockers', 'steroid': 'systemic steroids',
                     'anticoagulant': 'anticoagulants', 'tetracycline': 'tetracyclines'}

# (class A, class B, level, title, why, reference)
INTERACTIONS = [
    ('anticoagulant', 'nsaid', 'danger', 'Bleeding risk: anticoagulant with an NSAID', 'NSAIDs add to the anticoagulant effect and irritate the stomach. Prefer paracetamol.', 'BNF interactions'),
    ('anticoagulant', 'aspirin', 'warn', 'Bleeding risk: anticoagulant with aspirin', 'Only combine when there is a clear indication (e.g. specialist advice after a stent).', 'BNF interactions'),
    ('warfarin', 'metronidazole', 'danger', 'Warfarin with metronidazole', 'Metronidazole markedly raises the INR. Choose another antibiotic or check the INR within 3-5 days and reduce the warfarin dose.', 'BNF interactions'),
    ('warfarin', 'cotrimoxazole', 'danger', 'Warfarin with co-trimoxazole', 'Co-trimoxazole markedly raises the INR. Avoid or monitor the INR closely.', 'BNF interactions'),
    ('warfarin', 'fluoroquinolone', 'warn', 'Warfarin with a fluoroquinolone', 'May raise the INR. Check the INR during the course.', 'BNF interactions'),
    ('warfarin', 'macrolide_cyp', 'warn', 'Warfarin with a macrolide', 'May raise the INR. Check the INR during the course.', 'BNF interactions'),
    ('warfarin', 'rifampicin', 'danger', 'Warfarin with rifampicin', 'Rifampicin strongly lowers warfarin levels; the INR will fall. Needs specialist dosing and frequent INR checks.', 'BNF interactions'),
    ('ace_inhibitor', 'k_sparing', 'danger', 'High potassium risk: ACE inhibitor with a potassium-sparing diuretic', 'Check potassium and creatinine within a week and regularly after.', 'BNF interactions'),
    ('arb', 'k_sparing', 'danger', 'High potassium risk: ARB with a potassium-sparing diuretic', 'Check potassium and creatinine within a week and regularly after.', 'BNF interactions'),
    ('ace_inhibitor', 'potassium', 'danger', 'High potassium risk: ACE inhibitor with potassium', 'Avoid potassium supplements unless potassium is low and monitored.', 'BNF interactions'),
    ('ace_inhibitor', 'arb', 'danger', 'ACE inhibitor with an ARB', 'Dual blockade raises the risk of kidney injury and high potassium without benefit in most patients.', 'NICE hypertension guidance'),
    ('ace_inhibitor', 'nsaid', 'warn', 'Kidney risk: ACE inhibitor with an NSAID', 'NSAIDs blunt the blood-pressure effect and can cause acute kidney injury, especially if dehydrated or on a diuretic.', 'BNF interactions'),
    ('arb', 'nsaid', 'warn', 'Kidney risk: ARB with an NSAID', 'NSAIDs blunt the blood-pressure effect and can cause acute kidney injury, especially if dehydrated or on a diuretic.', 'BNF interactions'),
    ('methotrexate', 'cotrimoxazole', 'danger', 'Methotrexate with co-trimoxazole', 'Both block folate: risk of severe bone-marrow suppression. Avoid.', 'BNF interactions'),
    ('rifampicin', 'dolutegravir', 'warn', 'Rifampicin with dolutegravir', 'Rifampicin lowers dolutegravir levels. WHO advises an extra 50 mg dolutegravir dose 12 hours after TLD during TB treatment and for 2 weeks after.', 'WHO HIV/TB guidelines'),
    ('rifampicin', 'hormonal_contraceptive', 'warn', 'Rifampicin with hormonal contraception', 'Rifampicin makes pills, implants and patches unreliable. Offer an IUD or depot injection (DMPA).', 'WHO Medical Eligibility Criteria'),
    ('rifampicin', 'lumefantrine', 'danger', 'Rifampicin with artemether-lumefantrine', 'Rifampicin lowers lumefantrine levels a lot and treatment may fail. Use another ACT or IV/IM artesunate as advised.', 'WHO malaria guidelines'),
    ('inducer', 'dolutegravir', 'warn', 'Enzyme-inducing anti-epileptic with dolutegravir', 'Carbamazepine, phenytoin and phenobarbital lower dolutegravir levels; dose adjustment or another anti-epileptic is needed.', 'WHO HIV guidelines'),
    ('inducer', 'hormonal_contraceptive', 'warn', 'Enzyme-inducing anti-epileptic with hormonal contraception', 'Contraception may fail. Offer an IUD or depot injection.', 'WHO Medical Eligibility Criteria'),
    ('inducer', 'lumefantrine', 'warn', 'Enzyme inducer with artemether-lumefantrine', 'May reduce lumefantrine levels and cure rates.', 'WHO malaria guidelines'),
    ('opioid', 'sedative', 'danger', 'Breathing risk: opioid with a sedative', 'Opioids with benzodiazepines or phenobarbital can stop breathing. Use the lowest doses, monitor oxygen and have naloxone ready.', 'BNF interactions'),
    ('tramadol', 'ssri', 'warn', 'Tramadol with an SSRI', 'Risk of serotonin syndrome and seizures.', 'BNF interactions'),
    ('tramadol', 'tca', 'warn', 'Tramadol with a tricyclic antidepressant', 'Risk of seizures and serotonin syndrome.', 'BNF interactions'),
    ('statin', 'macrolide_cyp', 'warn', 'Statin with erythromycin or clarithromycin', 'Raises statin levels: muscle damage risk. Pause the statin during the course or use azithromycin.', 'BNF interactions'),
    ('fluoroquinolone', 'chelating', 'info', 'Separate the doses', 'Iron, zinc, calcium and antacids stop ciprofloxacin being absorbed. Give the antibiotic 2 hours before or 4 hours after.', 'BNF interactions'),
    ('tetracycline', 'chelating', 'info', 'Separate the doses', 'Iron, zinc, calcium and antacids stop doxycycline/tetracycline being absorbed. Give them 2-3 hours apart.', 'BNF interactions'),
    ('aminoglycoside', 'loop_diuretic', 'warn', 'Gentamicin with furosemide', 'More ear and kidney damage together. Monitor creatinine and gentamicin levels where possible.', 'BNF interactions'),
    ('sulfonylurea', 'cotrimoxazole', 'warn', 'Sulfonylurea with co-trimoxazole', 'Raises the risk of low blood sugar. Warn the patient and check glucose.', 'BNF interactions'),
    ('sulfonylurea', 'fluoroquinolone', 'warn', 'Sulfonylurea with a fluoroquinolone', 'Can cause low (or high) blood sugar. Check glucose.', 'BNF interactions'),
    ('digoxin', 'loop_diuretic', 'warn', 'Digoxin with a loop diuretic', 'Low potassium makes digoxin toxic. Check potassium.', 'BNF interactions'),
    ('digoxin', 'thiazide', 'warn', 'Digoxin with a thiazide', 'Low potassium makes digoxin toxic. Check potassium.', 'BNF interactions'),
    ('antidopamine', 'antidopamine', 'warn', 'Two dopamine blockers', 'Metoclopramide with haloperidol (or similar) raises the risk of movement disorders and neuroleptic malignant syndrome.', 'BNF interactions'),
]

# pregnancy: class -> (level, why). Artemether-lumefantrine is not listed: WHO (2022) recommends it in all trimesters.
PREGNANCY = {
    'ace_inhibitor': ('danger', 'ACE inhibitors harm the baby\'s kidneys and skull, mostly from the second trimester. Switch to nifedipine, labetalol or methyldopa.'),
    'arb': ('danger', 'ARBs harm the baby\'s kidneys and skull. Switch to nifedipine, labetalol or methyldopa.'),
    'warfarin': ('danger', 'Warfarin causes birth defects (weeks 6-12) and fetal bleeding. Use heparin.'),
    'statin': ('danger', 'Statins are avoided in pregnancy. Stop until after delivery and breastfeeding.'),
    'methotrexate': ('danger', 'Methotrexate causes miscarriage and birth defects. Contraindicated.'),
    'valproate': ('danger', 'Valproate causes neural-tube and developmental defects. Specialist review; avoid in pregnancy.'),
    'misoprostol': ('danger', 'Misoprostol causes uterine contractions and abortion. Only for an obstetric indication (e.g. PPH, induction per protocol).'),
    'ergometrine': ('danger', 'Ergometrine contracts the uterus. Only for the third stage of labour or postpartum haemorrhage, never before delivery.'),
    'tetracycline': ('warn', 'Tetracyclines stain the baby\'s teeth and bones after 15 weeks. Prefer amoxicillin or azithromycin where suitable.'),
    'fluoroquinolone': ('warn', 'Fluoroquinolones are avoided in pregnancy unless there is no safer option.'),
    'aminoglycoside': ('warn', 'Gentamicin can damage the baby\'s hearing. Use only when clearly needed (e.g. sepsis protocol) with monitoring.'),
    'inducer': ('warn', 'Carbamazepine, phenytoin and phenobarbital raise the risk of birth defects. Do not stop suddenly; refer for specialist review and give folic acid.'),
    'oxidant': ('danger', 'Primaquine and similar oxidant drugs can cause haemolysis in a G6PD-deficient baby. Avoid in pregnancy.'),
    'albendazole': ('warn', 'Albendazole/mebendazole are avoided in the first trimester. Deworming is given from the second trimester (WHO).'),
    'chloramphenicol': ('warn', 'Systemic chloramphenicol near term can cause grey baby syndrome. Use another antibiotic if possible.'),
    'codeine': ('info', 'Opioids near delivery can depress the newborn\'s breathing. Use the lowest dose for the shortest time.'),
    'tramadol': ('info', 'Opioids near delivery can depress the newborn\'s breathing. Use the lowest dose for the shortest time.'),
    'cotrimoxazole': ('info', 'A folate antagonist: give folic acid. Still recommended for HIV prophylaxis in pregnancy (WHO).'),
}
TERATOGENS = {'ace_inhibitor', 'arb', 'warfarin', 'statin', 'methotrexate', 'valproate', 'misoprostol', 'inducer', 'tetracycline'}

# adult maximum daily dose in mg (BNF), for medicines with a strength in mg we can parse
MAX_DAILY_MG = {'paracetamol': 4000, 'ibuprofen': 2400, 'diclofenac': 150, 'tramadol': 400, 'metformin': 3000, 'amlodipine': 10,
                'atenolol': 100, 'lisinopril': 80, 'glibenclamide': 15, 'doxycycline': 200, 'ciprofloxacin': 1500, 'azithromycin': 500,
                'amitriptyline': 150, 'haloperidol': 20, 'metoclopramide': 30, 'omeprazole': 80, 'atorvastatin': 80, 'carbamazepine': 1600,
                'fluoxetine': 60, 'hydralazine': 200, 'hydrochlorothiazide': 50, 'prednisolone': None}
FREQ_PER_DAY = {'OD': 1, 'BD': 2, 'TDS': 3, 'QDS': 4, 'Q4H': 6, 'Q6H': 4, 'Q8H': 3, 'Q12H': 2, 'MANE': 1, 'NOCTE': 1}


def classes_of(med):
    text = f'{med.name} {med.generic_name}'.casefold()
    return {c for c, words in CLASSES.items() if any(w in text for w in words)}


def _f(level, kind, title, detail, meds=(), basis='', actions=None, ask=None):
    return {'level': level, 'kind': kind, 'title': title, 'detail': detail, 'meds': [str(m) for m in meds], 'basis': basis,
            'actions': actions or [], 'ask': ask}


def _ask(med):
    return {'kind': 'med', 'id': med.pk, 'topic': med.generic_name or med.name}


def _mg(text):
    """'500 mg' → 500, '1 g' → 1000, '80/480 mg' → 80 (first component). None when it cannot be read."""
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:/\s*[\d.,]+\s*)*(mcg|µg|microgram|mg|g)\b', (text or '').lower())
    if not m:
        return None
    n = float(m.group(1).replace(',', '.'))
    return n / 1000 if m.group(2) in ('mcg', 'µg', 'microgram') else n * 1000 if m.group(2) == 'g' else n


# ------------------------------------------------------------------ the patient, as the rules need them
def patient_facts(encounter):
    from .clinical import _latest_values
    p = encounter.patient
    today = timezone.localdate()
    text = ' '.join([encounter.diagnosis or '', encounter.reason or '', encounter.symptoms or '',
                     ' '.join(p.conditions.filter(status='active').values_list('name', flat=True)), p.medical_alerts or '']).lower()
    vals = _latest_values(p, days=365)
    hcg = vals.get('HCG')
    recent_hcg = hcg and (timezone.now() - hcg.order.resulted_at).days <= 30 if hcg and hcg.order.resulted_at else False
    pregnant = None
    if re.search(r'pregnan|antenatal|gestation|trimester|\banc\b|gravid', text):
        pregnant = True
    if recent_hcg:
        pregnant = 'positive' in (hcg.value_text or '').lower() or pregnant
    g6pd = vals.get('G6PD')
    g6pd_status = ('deficient' if g6pd and 'defic' in (g6pd.value_text or '').lower() else 'normal' if g6pd else
                   'deficient' if 'g6pd' in text else None)
    weight = (encounter.vitals or {}).get('weight_kg')
    try:
        weight = float(weight) if weight not in (None, '') else None
    except (TypeError, ValueError):
        weight = None
    return {'age_days': (today - p.dob).days if p.dob else None, 'age': p.age, 'sex': p.sex, 'text': text, 'vals': vals,
            'pregnant': pregnant, 'childbearing': p.sex == 'F' and p.age is not None and 12 <= p.age <= 50, 'g6pd': g6pd_status,
            'weight': weight}


def _flag(P, code):
    v = P['vals'].get(code)
    return v.flag if v else ''


def _shown(P, code):
    v = P['vals'].get(code)
    return f'{v.display} {v.parameter.unit}'.strip() if v else ''


# ------------------------------------------------------------------ prescribing
def current_medicines(encounter, exclude_prescription=None):
    """Medicines from prescriptions in the last 30 days (not cancelled), with where they came from."""
    from .models import PrescriptionItem
    qs = (PrescriptionItem.objects.filter(prescription__encounter__patient=encounter.patient,
                                          prescription__state__in=['draft', 'signed', 'partial', 'dispensed'],
                                          prescription__created_at__gte=timezone.now() - timedelta(days=30))
          .select_related('medication', 'prescription'))
    if exclude_prescription:
        qs = qs.exclude(prescription=exclude_prescription)
    return list(qs)


def rx_findings(encounter, lines, exclude_prescription=None):
    """lines: [{'med': Medication, 'dose', 'units', 'frequency', 'days', 'quantity', 'route'}] being prescribed now."""
    from .clinical import clinical_review
    P = patient_facts(encounter)
    F = []
    new = [(ln, classes_of(ln['med']) if ln.get('route') not in NON_SYSTEMIC else set()) for ln in lines if ln.get('med')]
    existing = [(i, classes_of(i.medication) if i.route not in NON_SYSTEMIC else set()) for i in current_medicines(encounter, exclude_prescription)
                if i.medication_id not in {ln['med'].pk for ln, _ in new}]
    everything = [(ln['med'], c, 'now') for ln, c in new] + [(i.medication, c, i.prescription.number) for i, c in existing]

    # 1. the existing safety review (allergies by class, kidney/NSAID, metformin/creatinine, critical results...)
    for x in clinical_review(encounter, [ln['med'] for ln, _ in new]):
        if x['kind'] in ('allergy', 'contra', 'stewardship'):
            F.append({**x, 'meds': [], 'basis': 'Hospital safety rules', 'ask': None})

    # 2. interactions: at least one side must be something being prescribed now
    seen = set()
    for a, b, level, title, why, ref in INTERACTIONS:
        for m1, c1, src1 in everything:
            for m2, c2, src2 in everything:
                if m1.pk == m2.pk or 'now' not in (src1, src2) or a not in c1 or b not in c2:
                    continue
                key = (title, frozenset((m1.pk, m2.pk)))
                if key in seen:
                    continue
                seen.add(key)
                other = m2 if src1 == 'now' else m1
                src = src2 if src1 == 'now' else src1
                F.append(_f(level, 'interaction', title, why + (f' {other} is already prescribed ({src}).' if src != 'now' else ''),
                            (m1, m2), ref, ask=_ask(m1 if src1 == 'now' else m2)))
    qt = [(m, s) for m, c, s in everything if 'qt' in c]
    if len({m.pk for m, _ in qt}) >= 2 and any(s == 'now' for _, s in qt):
        F.append(_f('warn', 'interaction', 'Two medicines that lengthen the QT interval', 'Together they raise the risk of a dangerous heart rhythm. '
                    'Check an ECG and potassium/magnesium if both are needed.', [m for m, _ in qt], 'BNF interactions'))

    # 3. duplicate classes
    for cls, label in DUPLICATE_CLASSES.items():
        members = [(m, s) for m, c, s in everything if cls in c]
        if len({m.pk for m, _ in members}) >= 2 and any(s == 'now' for _, s in members):
            where = ', '.join(f'{m}' + (f' ({s})' if s != 'now' else '') for m, s in members)
            F.append(_f('warn', 'duplicate', f'Two {label}', f'{where}. Using two from the same class rarely adds benefit and adds side effects.',
                        [m for m, _ in members], 'Prescribing good practice'))
    aspirin_now = [m for m, c, s in everything if 'aspirin' in c]
    nsaid_now = [m for m, c, s in everything if 'nsaid' in c]
    if aspirin_now and nsaid_now and any(s == 'now' for m, c, s in everything if ('aspirin' in c or 'nsaid' in c)):
        F.append(_f('warn', 'duplicate', 'Aspirin with another NSAID', 'More stomach bleeding; ibuprofen can also block the heart-protective effect of low-dose aspirin.',
                    aspirin_now + nsaid_now, 'BNF interactions'))

    # 4. per medicine: pregnancy, age, G6PD, results, conditions, dose
    age, days_old = P['age'], P['age_days']
    for ln, c in new:
        m = ln['med']
        ask = _ask(m)
        if P['pregnant']:
            for cls in sorted(c & set(PREGNANCY)):
                level, why = PREGNANCY[cls]
                F.append(_f(level, 'pregnancy', f'{m.name} in pregnancy', why, [m], 'WHO / BNF pregnancy guidance', ask=ask))
        elif P['childbearing'] and c & TERATOGENS and P['pregnant'] is None:
            F.append(_f('info', 'pregnancy', f'Check pregnancy before {m.name}', f'{m.name} can harm an unborn baby. Ask about pregnancy or do a pregnancy test.',
                        [m], 'WHO / BNF pregnancy guidance', _order('HCG', encounter), ask))
        if age is not None:
            if 'tetracycline' in c and age < 8:
                F.append(_f('warn', 'age', f'{m.name} under 8 years', 'Tetracyclines stain developing teeth. Use only for specific indications (e.g. severe rickettsial infection).', [m], 'BNF for Children', ask=ask))
            if 'aspirin' in c and age < 16:
                F.append(_f('danger', 'age', f'Aspirin under 16 years', 'Risk of Reye\'s syndrome. Avoid unless a specialist indication (e.g. Kawasaki disease).', [m], 'BNF for Children', ask=ask))
            if c & {'codeine', 'tramadol'} and age < 12:
                F.append(_f('danger', 'age', f'{m.name} under 12 years', 'Unpredictable conversion to morphine can stop breathing in children. Contraindicated.', [m], 'BNF for Children / FDA', ask=ask))
            if 'promethazine' in c and age < 2:
                F.append(_f('danger', 'age', 'Promethazine under 2 years', 'Can cause fatal breathing depression in young children.', [m], 'BNF for Children', ask=ask))
            if 'fluoroquinolone' in c and age < 18:
                F.append(_f('info', 'age', f'{m.name} in a child', 'Fluoroquinolones are used in children only when the benefit outweighs the joint risk.', [m], 'BNF for Children', ask=ask))
            if age < 12 and not P['weight'] and c & {'antibiotic', 'antimalarial', 'paracetamol', 'nsaid'}:
                F.append(_f('info', 'age', f'Weigh the child for {m.name}', 'Children\'s doses are by weight and no weight is recorded for this visit.', [m], 'WHO Pocket Book of Hospital Care for Children', ask=ask))
            if age >= 65 and c & {'benzodiazepine', 'tca', 'sulfonylurea'}:
                F.append(_f('warn', 'age', f'{m.name} in an older person', 'Higher risk of falls, confusion or low blood sugar. Start low; prefer safer options (e.g. gliclazide over glibenclamide).', [m], 'Beers criteria', ask=ask))
        if days_old is not None and days_old < 28:
            if 'ceftriaxone' in c and any('calcium_iv' in cc for _, cc, _s in everything):
                F.append(_f('danger', 'age', 'Ceftriaxone with IV calcium in a newborn', 'Can form fatal precipitates in the lungs and kidneys. Do not give together in neonates.', [m], 'BNF for Children', ask=ask))
            if 'chloramphenicol' in c:
                F.append(_f('danger', 'age', 'Chloramphenicol in a newborn', 'Grey baby syndrome. Avoid unless no alternative and levels can be checked.', [m], 'WHO Pocket Book', ask=ask))
            if 'ceftriaxone' in c and _flag(P, 'TBIL') in ('H', 'HH'):
                F.append(_f('warn', 'age', 'Ceftriaxone with jaundice in a newborn', 'Ceftriaxone can displace bilirubin. Cefotaxime is preferred in jaundiced neonates.', [m], 'WHO Pocket Book', ask=ask))
        # G6PD
        if 'oxidant' in c:
            if P['g6pd'] == 'deficient':
                F.append(_f('danger', 'g6pd', f'{m.name} with G6PD deficiency', 'Can cause severe haemolysis. Avoid.', [m], 'WHO malaria guidelines / BNF', ask=ask))
            elif P['g6pd'] is None:
                F.append(_f('warn', 'g6pd', f'G6PD status unknown for {m.name}', 'Test G6PD before primaquine, dapsone or similar oxidant drugs.', [m],
                            'WHO malaria guidelines', _order('G6PD', encounter), ask))
        if 'cotrimoxazole' in c and P['g6pd'] == 'deficient':
            F.append(_f('warn', 'g6pd', f'{m.name} with G6PD deficiency', 'Sulfonamides can trigger haemolysis. Watch for dark urine and falling haemoglobin.', [m], 'BNF', ask=ask))
        # results that change prescribing
        if c & {'ace_inhibitor', 'arb', 'k_sparing', 'potassium'} and _flag(P, 'K') in ('H', 'HH'):
            F.append(_f('danger', 'result', f'{m.name} with high potassium', f'Potassium {_shown(P, "K")}. This medicine raises potassium further.', [m], 'BNF', ask=ask))
        if 'digoxin' in c and _flag(P, 'K') in ('L', 'LL'):
            F.append(_f('danger', 'result', 'Digoxin with low potassium', f'Potassium {_shown(P, "K")}. Low potassium makes digoxin toxic; correct it first.', [m], 'BNF', ask=ask))
        if c & {'anticoagulant', 'antiplatelet', 'nsaid'} and _flag(P, 'PLT') in ('L', 'LL'):
            F.append(_f('danger' if _flag(P, 'PLT') == 'LL' else 'warn', 'result', f'{m.name} with low platelets', f'Platelets {_shown(P, "PLT")}. Bleeding risk.', [m], 'BNF', ask=ask))
        if c & {'warfarin', 'nsaid', 'antiplatelet'} and _flag(P, 'INR') in ('H', 'HH'):
            F.append(_f('warn', 'result', f'{m.name} with a raised INR', f'INR {_shown(P, "INR")}. Bleeding risk.', [m], 'BNF', ask=ask))
        if c & {'isoniazid', 'rifampicin', 'methotrexate', 'valproate', 'statin'} and _flag(P, 'ALT') in ('H', 'HH'):
            F.append(_f('warn', 'result', f'{m.name} with raised liver enzymes', f'ALT {_shown(P, "ALT")}. This medicine can injure the liver; check a baseline and monitor.', [m], 'WHO TB guidelines / BNF', ask=ask))
        if 'nitrofurantoin' in c and _flag(P, 'CREA') in ('H', 'HH'):
            F.append(_f('warn', 'result', 'Nitrofurantoin with reduced kidney function', f'Creatinine {_shown(P, "CREA")}. Avoid if eGFR is below 45: it does not work and is more toxic.', [m], 'BNF', ask=ask))
        if 'aminoglycoside' in c and _flag(P, 'CREA') in ('H', 'HH'):
            F.append(_f('warn', 'result', f'{m.name} with reduced kidney function', f'Creatinine {_shown(P, "CREA")}. Adjust the dose or interval and monitor levels.', [m], 'BNF', ask=ask))
        if 'sulfonylurea' in c and (_flag(P, 'FBG') in ('L', 'LL') or _flag(P, 'CGLU') in ('L', 'LL')):
            F.append(_f('danger', 'result', f'{m.name} with low blood sugar', 'A recent glucose is low. Sulfonylureas can cause prolonged hypoglycaemia.', [m], 'BNF', ask=ask))
        if 'antimalarial' in c:
            rdt, film = P['vals'].get('RDT'), P['vals'].get('SPEC')
            recent = [v for v in (rdt, film) if v and v.order.resulted_at and (timezone.now() - v.order.resulted_at).days <= 3]
            positive = any('positive' in (v.value_text or '').lower() or (v.value_text and v.value_text.lower().startswith('p.')) for v in recent)
            if recent and not positive:
                F.append(_f('warn', 'result', f'{m.name} with a negative malaria test', 'The malaria test in the last 3 days was negative. Look for another cause of fever unless severe malaria is strongly suspected.', [m], 'WHO malaria guidelines', ask=ask))
            elif not recent:
                F.append(_f('info', 'result', f'Confirm malaria before {m.name}', 'WHO recommends a parasitological test (RDT or film) before treatment.', [m], 'WHO malaria guidelines', _order('MAL', encounter), ask))
        # conditions
        t = P['text']
        if 'nonselective_bb' in c and any(w in t for w in ('asthma', 'copd', 'wheez')):
            F.append(_f('danger', 'condition', f'{m.name} with asthma', 'Non-selective beta-blockers can cause severe bronchospasm.', [m], 'BNF', ask=ask))
        elif 'beta_blocker' in c and any(w in t for w in ('asthma', 'copd', 'wheez')):
            F.append(_f('warn', 'condition', f'{m.name} with asthma', 'Even cardioselective beta-blockers can worsen asthma. Use only if clearly needed.', [m], 'BNF', ask=ask))
        if 'ergometrine' in c and (any(w in t for w in ('hypertens', 'eclampsia', 'pre-eclampsia', 'preeclampsia')) or _bp_high(encounter)):
            F.append(_f('danger', 'condition', 'Ergometrine with high blood pressure', 'Ergometrine can cause a dangerous rise in blood pressure, stroke or seizures. Use oxytocin instead.', [m], 'WHO PPH guidelines', ask=ask))
        if c & {'tramadol'} and any(w in t for w in ('epilep', 'seizure', 'convuls')):
            F.append(_f('warn', 'condition', 'Tramadol with epilepsy', 'Tramadol lowers the seizure threshold.', [m], 'BNF', ask=ask))
        if c & {'steroid', 'aspirin'} and any(w in t for w in ('peptic', 'ulcer', 'gi bleed', 'melaena', 'haematemesis')):
            F.append(_f('warn', 'condition', f'{m.name} with peptic ulcer disease', 'Raises the risk of bleeding. Add stomach protection (e.g. omeprazole) or choose another option.', [m], 'BNF', ask=ask))
        if 'paracetamol' in c and any(w in t for w in ('liver', 'hepat', 'cirrhos')):
            F.append(_f('warn', 'condition', 'Paracetamol with liver disease', 'Keep to 2-3 g a day at most.', [m], 'BNF', ask=ask))
        # dose and course
        per_day = FREQ_PER_DAY.get(ln.get('frequency') or '')
        key = next((k for k in MAX_DAILY_MG if k in f'{m.name} {m.generic_name}'.lower()), None)
        if key and MAX_DAILY_MG[key] and per_day and (age is None or age >= 18):
            per_dose = _mg(ln.get('dose')) or ((_mg(m.strength) or 0) * float(ln.get('units') or 1)) or None
            if per_dose and per_dose * per_day > MAX_DAILY_MG[key] + 0.01:
                F.append(_f('danger', 'dose', f'{m.name}: {per_dose * per_day:g} mg a day', f'Above the usual adult maximum of {MAX_DAILY_MG[key]:g} mg a day '
                            f'({per_dose:g} mg × {per_day} a day). Check the dose.', [m], 'BNF', ask=ask))
        try:
            days = int(ln.get('days') or 0)
        except (TypeError, ValueError):
            days = 0
        if 'antibiotic' in c and 'anti_tb' not in c and days > 14:
            F.append(_f('info', 'dose', f'{m.name} for {days} days', 'Longer than most antibiotic courses. Check the indication and plan a review.', [m], 'WHO AWaRe antibiotic book', ask=ask))
    return _dedupe(F)


def _bp_high(encounter):
    bp = str((encounter.vitals or {}).get('bp') or '')
    m = re.match(r'\s*(\d{2,3})\s*/\s*(\d{2,3})', bp)
    return bool(m and (int(m.group(1)) >= 140 or int(m.group(2)) >= 90))


def _order(code, encounter):
    from .models import LabTest
    t = LabTest.objects.filter(code=code, active=True).first()
    return [{'label': f'Order {t.name}', 'url': reverse('lab_new') + f'?encounter={encounter.pk}&test={t.pk}', 'test': t.pk}] if t else []


def _dedupe(F):
    out, seen = [], set()
    for x in sorted(F, key=lambda f: LEVEL_ORDER[f['level']]):
        k = (x['title'].lower(), x['detail'][:60].lower())
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def blocking(findings):
    """Serious medicine-specific warnings: saving needs a written clinical justification (allergies have their own gate)."""
    return [f for f in findings if f['level'] == 'danger' and f['kind'] != 'allergy' and f['meds']]


# ------------------------------------------------------------------ test ordering
REPEAT_WINDOW_DAYS = {'BGRP': None, 'G6PD': None, 'HBEP': None, 'SICK': None,  # does not change: once is enough
                      'HBA1C': 90, 'LIPID': 90, 'TFT': 42, 'FERR': 30, 'PSA': 90, 'HBSAG': 30, 'RF': 90}
DEFAULT_REPEAT_DAYS = 3


def lab_findings(encounter, tests):
    """Advice on a test order: already ordered or recently done, overlapping tests, tests to consider, critical results."""
    from .clinical import clinical_review
    from .models import LabOrder, LabTest
    P = patient_facts(encounter)
    F = []
    chosen = {t.code for t in tests}
    params = {t.pk: {p.code for p in t.parameters.all()} for t in tests}
    pending = {o.test_id: o for o in LabOrder.objects.filter(encounter=encounter).exclude(status__in=['cancelled']).select_related('request', 'test')
               if o.status in ('ordered', 'collected', 'processing')}
    for t in tests:
        ask = {'kind': 'test', 'id': t.pk, 'topic': t.name}
        if t.pk in pending:
            o = pending[t.pk]
            F.append(_f('warn', 'duplicate', f'{t.name} is already ordered', f'{o.request.number if o.request else "This visit"} is {o.get_status_display().lower()}. A second sample is not needed.',
                        basis='This visit', ask=ask))
            continue
        window = REPEAT_WINDOW_DAYS.get(t.code, DEFAULT_REPEAT_DAYS)
        last = (LabOrder.objects.filter(encounter__patient=encounter.patient, test=t, status__in=['resulted', 'verified'])
                .order_by('-resulted_at').prefetch_related('values__parameter').first())
        if last and last.resulted_at:
            age = (timezone.now() - last.resulted_at).days
            if window is None or age <= window:
                vals = ', '.join(f'{v.parameter.name} {v.display} {v.parameter.unit}'.strip() + (f' ({v.get_flag_display().lower()})' if v.flag not in ('', 'N') else '')
                                 for v in list(last.values.all())[:4])
                when = 'today' if age == 0 else 'yesterday' if age == 1 else f'{age} days ago'
                why = 'This result does not change, so repeating it is rarely needed.' if window is None else f'Done {when}.'
                F.append(_f('warn', 'repeat', f'{t.name} was done on {timezone.localtime(last.resulted_at):%d %b %Y}',
                            f'{why} Result: {vals or "see the record"}.', basis='Patient record', ask=ask,
                            actions=[{'label': 'Open result', 'url': reverse('lab_request_detail', args=[last.request_id])}] if last.request_id else []))
    for a in tests:
        for b in tests:
            if a.pk != b.pk and params[a.pk] and params[a.pk] < params[b.pk]:
                F.append(_f('info', 'overlap', f'{b.name} already includes {a.name}', f'Every value in {a.name} is part of {b.name}. You can untick {a.name}.',
                            basis='Lab catalogue', actions=[{'label': f'Untick {a.name}', 'untick': a.pk}]))
    # tests to consider
    t = P['text']

    def consider(code, title, why, basis):
        if code in chosen or code in pending_codes:
            return
        test = LabTest.objects.filter(code=code, active=True).first()
        if test:
            F.append(_f('info', 'suggest', title, why, basis=basis, actions=[{'label': f'Add {test.name}', 'test': test.pk}],
                        ask={'kind': 'test', 'id': test.pk, 'topic': test.name}))
    pending_codes = {o.test.code for o in pending.values()}
    recent = set(P['vals'])
    if P['pregnant'] and re.search(r'\b(antenatal|anc|booking)\b', t):
        for code, param, name in (('HB', 'HB', 'Haemoglobin'), ('HIV', 'HIV', 'HIV test'), ('HBSAG', 'HBS', 'Hepatitis B'),
                                  ('BGRP', 'ABO', 'Blood group'), ('UA', 'PRO', 'Urinalysis')):
            if param not in recent:
                consider(code, f'Antenatal booking: {name}', 'Part of the WHO antenatal booking tests (with syphilis screening).', 'WHO antenatal care recommendations 2016')
    if any(w in t for w in ('fever', 'pyrexia', 'febrile')) and not recent & {'RDT', 'DENS'} and not chosen & {'MAL', 'MPS'}:
        consider('MAL', 'Fever: test for malaria', 'Every suspected malaria case should be tested before treatment.', 'WHO malaria guidelines')
    if any(w in t for w in ('jaundice', 'icter', 'yellow eyes')) and 'ALT' not in recent:
        consider('LFT', 'Jaundice: liver function', 'Bilirubin and liver enzymes help separate liver from blood causes.', 'Standard work-up')
    if _flag(P, 'HB') in ('L', 'LL') and _flag(P, 'MCV') in ('L', 'LL') and 'FERR' not in recent:
        consider('FERR', 'Small red cells: check iron', f'Hb {_shown(P, "HB")}, MCV {_shown(P, "MCV")}. Ferritin separates iron deficiency from thalassaemia trait.', 'WHO anaemia guidance')
    meds = {c for i in current_medicines(encounter) for c in classes_of(i.medication)}
    if 'anti_tb' in meds and 'ALT' not in recent:
        consider('LFT', 'On TB treatment: baseline liver tests', 'Isoniazid, rifampicin and pyrazinamide can injure the liver.', 'WHO TB guidelines')
    if 'dolutegravir' in meds or 'tenofovir' in ' '.join(i.medication.generic_name for i in current_medicines(encounter)).lower():
        if 'CREA' not in recent:
            consider('RFT', 'On tenofovir: kidney function', 'Check creatinine at baseline and during tenofovir treatment.', 'WHO HIV guidelines')
    if meds & {'ace_inhibitor', 'arb', 'k_sparing'} and 'K' not in recent:
        consider('RFT', 'On an ACE inhibitor/ARB: potassium and creatinine', 'Check within 1-2 weeks of starting or changing the dose.', 'NICE hypertension guidance')
    if meds & {'metformin'} and 'CREA' not in recent:
        consider('RFT', 'On metformin: kidney function', 'Check eGFR at least yearly; reduce or stop metformin as it falls.', 'BNF')
    if meds & {'oxidant'} and P['g6pd'] is None:
        consider('G6PD', 'G6PD before oxidant drugs', 'Primaquine and dapsone can cause haemolysis in G6PD deficiency.', 'WHO malaria guidelines')
    # from the hospital's existing review: missing work-up and critical results nobody has acknowledged
    for x in clinical_review(encounter, (), tests):
        if x['kind'] in ('missing', 'result', 'mismatch'):
            acts = []
            for a in x.get('actions', []):
                m = re.search(r'test=(\d+)', a.get('url', ''))
                acts.append({'label': a['label'], 'test': int(m.group(1))} if m else a)
            F.append({**x, 'actions': acts, 'meds': [], 'basis': 'Hospital safety rules', 'ask': None})
    return _dedupe(F)


# ------------------------------------------------------------------ patient brief for the chart
def patient_brief(patient):
    """What Dr. Flow says when the chart opens: safety-critical first, short."""
    from .clinical import _latest_values
    from .models import DoctorReport, Encounter, LabRequest, Prescription
    lines, alerts = [], 0
    allergies = list(patient.allergies.filter(status='active').values_list('substance', 'severity'))
    if allergies:
        lines.append({'level': 'danger', 'text': 'Allergic to ' + ', '.join(f'{s}' + (f' ({sev})' if sev in ('severe', 'moderate') else '') for s, sev in allergies)})
        alerts += 1
    vals = _latest_values(patient, days=30)
    crit = [v for v in vals.values() if v.flag in ('HH', 'LL') and not v.acknowledged_at]
    if crit:
        lines.append({'level': 'danger', 'text': 'Critical, not yet reviewed: ' + ', '.join(f'{v.parameter.name} {v.display} {v.parameter.unit}'.strip() for v in crit[:3])})
        alerts += 1
    if patient.medical_alerts:
        lines.append({'level': 'warn', 'text': patient.medical_alerts[:160]})
    enc = Encounter.objects.filter(patient=patient, status='open').order_by('-created_at').first()
    if enc:
        P = patient_facts(enc)
        if P['pregnant']:
            lines.append({'level': 'warn', 'text': 'Pregnant: I will check every medicine for pregnancy safety.'})
        if P['g6pd'] == 'deficient':
            lines.append({'level': 'warn', 'text': 'G6PD deficient: avoid primaquine, dapsone and nitrofurantoin.'})
        pend = LabRequest.objects.filter(encounter=enc).exclude(orders__status__in=['resulted', 'verified', 'cancelled']).distinct().count()
        if pend:
            lines.append({'level': 'info', 'text': f'{pend} lab request{"s" if pend != 1 else ""} still in the lab for this visit.'})
    conds = list(patient.conditions.filter(status='active').values_list('name', flat=True)[:4])
    if conds:
        lines.append({'level': 'info', 'text': 'Active: ' + ', '.join(conds)})
    drafts = Prescription.objects.filter(encounter__patient=patient, state='draft').count()
    reports = DoctorReport.objects.filter(encounter__patient=patient, status='draft').count()
    if drafts or reports:
        bits = ([f'{drafts} draft prescription{"s" if drafts != 1 else ""}'] if drafts else []) + ([f'{reports} draft report{"s" if reports != 1 else ""}'] if reports else [])
        lines.append({'level': 'info', 'text': ' and '.join(bits) + ' waiting for you.'})
    return {'lines': lines[:6], 'alerts': alerts, 'encounter': enc.pk if enc else None, 'first_name': patient.first_name}
