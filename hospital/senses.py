"""Eye and ear examination: cleaning the entered values and working out what follows from them.

Mirrored line-for-line in static/hospital/js/senses-figure.js (`MFSenses.compute`), so the animations (what the patient
sees, the eye's pressure and fundus, the sound path through the ear, the audiogram) follow the values while they are
typed. The server recomputes on save and the page redraws from its answer. test_theatre_senses checks both sides.

Grading used:
* Vision — WHO / ICD-11 categories of presenting visual acuity, applied to the better eye.
* Hearing — WHO World Report on Hearing (2021): pure-tone average of 0.5, 1, 2 and 4 kHz in the better ear.
* Air–bone gap of 15 dB or more = conductive component.

Teaching and documentation aid only; it does not replace an ophthalmologist, ENT surgeon or audiologist.
"""
import math

SIDES = ('right', 'left')

# ------------------------------------------------------------------ eyes
ACUITY = ['6/5', '6/6', '6/9', '6/12', '6/18', '6/24', '6/36', '6/60', '3/60', '1/60', 'CF', 'HM', 'PL', 'NPL']
LOGMAR = {'6/5': -0.1, '6/6': 0.0, '6/9': 0.2, '6/12': 0.3, '6/18': 0.5, '6/24': 0.6, '6/36': 0.8, '6/60': 1.0, '3/60': 1.3,
          '1/60': 1.8, 'CF': 2.0, 'HM': 2.3, 'PL': 2.7, 'NPL': 3.0}
ACUITY_LABELS = {'CF': 'Counts fingers', 'HM': 'Hand movements', 'PL': 'Perceives light', 'NPL': 'No perception of light'}
VI = [('none', 'No visual impairment', 0.3), ('mild', 'Mild visual impairment', 0.5), ('moderate', 'Moderate visual impairment', 1.0),
      ('severe', 'Severe visual impairment', 1.3), ('blind', 'Blindness', 99)]
LENS = {'clear': 0, 'early': 1, 'moderate': 2, 'dense': 3, 'mature': 4, 'iol': 0}
LENS_LABELS = {'clear': 'Clear', 'early': 'Early cataract', 'moderate': 'Moderate cataract', 'dense': 'Dense cataract',
               'mature': 'Mature (white) cataract', 'iol': 'Lens implant (after cataract surgery)'}
CONJUNCTIVA = {'normal': 'Normal', 'injected': 'Red / injected', 'pterygium': 'Pterygium', 'haemorrhage': 'Subconjunctival haemorrhage'}
DISCHARGE_EYE = {'none': 'None', 'watery': 'Watery', 'purulent': 'Pus (purulent)'}
CORNEA = {'clear': 'Clear', 'abrasion': 'Abrasion (stains)', 'ulcer': 'Ulcer', 'oedema': 'Hazy / oedema', 'scar': 'Scar'}
CHAMBER = {'deep': 'Deep and quiet', 'shallow': 'Shallow', 'hypopyon': 'Pus level (hypopyon)', 'hyphaema': 'Blood level (hyphaema)'}
REACTION = {'brisk': 'Brisk', 'sluggish': 'Sluggish', 'none': 'Not reacting'}
DR = {'none': 'None', 'mild': 'Mild non-proliferative', 'moderate': 'Moderate non-proliferative', 'severe': 'Severe non-proliferative',
      'proliferative': 'Proliferative'}
AMD = {'none': 'None', 'dry': 'Dry', 'wet': 'Wet'}
FIELD = {'full': 'Full', 'peripheral_loss': 'Peripheral loss', 'central_loss': 'Central loss'}

# ------------------------------------------------------------------ ears
FREQS = ['250', '500', '1000', '2000', '4000', '8000']
PTA_FREQS = ['500', '1000', '2000', '4000']
HEARING = [('normal', 'Normal hearing', 20), ('mild', 'Mild hearing loss', 35), ('moderate', 'Moderate hearing loss', 50),
           ('mod_severe', 'Moderately severe hearing loss', 65), ('severe', 'Severe hearing loss', 80),
           ('profound', 'Profound hearing loss', 95), ('complete', 'Complete hearing loss', 999)]
CANAL = {'clear': 'Clear', 'wax': 'Some wax', 'impacted_wax': 'Impacted wax', 'otitis_externa': 'Swollen, inflamed (otitis externa)',
         'foreign_body': 'Foreign body'}
TM = {'normal': 'Normal', 'retracted': 'Retracted', 'effusion': 'Fluid behind it', 'bulging': 'Red and bulging', 'perforation': 'Perforated',
      'cholesteatoma': 'Cholesteatoma (retraction pocket with debris)', 'grommet': 'Grommet in place', 'scarred': 'Scarred'}
DISCHARGE_EAR = {'none': 'None', 'mucoid': 'Mucoid', 'purulent': 'Pus', 'bloody': 'Blood'}
TYMPANOGRAM = {'': 'Not done', 'A': 'A · normal', 'As': 'As · stiff', 'Ad': 'Ad · floppy', 'B': 'B · flat', 'C': 'C · negative pressure'}
TYPE_LABELS = {'normal': 'Normal', 'conductive': 'Conductive', 'sensorineural': 'Sensorineural', 'mixed': 'Mixed',
               'conductive_probable': 'Probably conductive', 'sensorineural_probable': 'Probably sensorineural'}
BLOCK = {'clear': 0, 'wax': 0.35, 'impacted_wax': 0.92, 'otitis_externa': 0.6, 'foreign_body': 0.75}
MOBILITY_TYMP = {'A': 1, 'As': 0.5, 'Ad': 1.5, 'B': 0.08, 'C': 0.55}
MOBILITY_TM = {'normal': 1, 'retracted': 0.6, 'effusion': 0.25, 'bulging': 0.1, 'perforation': 0.7, 'cholesteatoma': 0.3, 'grommet': 0.9, 'scarred': 0.7}

# Procedures in the theatre catalogue that the findings can lead to (codes of ProcedureType)
PROCEDURES = {'cataract': 'Cataract surgery', 'trabeculectomy': 'Trabeculectomy', 'pterygium': 'Pterygium excision',
              'ear-microsuction': 'Ear microsuction', 'grommet': 'Myringotomy and grommet', 'tympanoplasty': 'Tympanoplasty',
              'mastoidectomy': 'Mastoidectomy'}

ORDER = {'high': 0, 'warn': 1, 'info': 2}


# ------------------------------------------------------------------ helpers
def rnd(x, d=0):
    m = 10 ** d
    return math.floor(x * m + 0.5) / m


def fmt(x):
    return str(int(x)) if float(x).is_integer() else str(x)


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _num(v, lo, hi):
    if v is None or v == '' or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return clamp(x, lo, hi)


def _pick(v, allowed, default):
    return v if v in allowed else default


def _txt(v, n):
    return str(v or '').strip()[:n]


# ------------------------------------------------------------------ cleaning
def clean_eye(raw):
    raw = raw if isinstance(raw, dict) else {}
    r = raw.get('retina') if isinstance(raw.get('retina'), dict) else {}
    iop = _num(raw.get('iop'), 0, 80)
    cdr = _num(raw.get('cdr'), 0, 1)
    pupil = _num(raw.get('pupil_mm'), 1, 9)
    htn = _num(r.get('htn'), 0, 4)
    return {
        'examined': bool(raw.get('examined')),
        'va': _pick(raw.get('va'), ACUITY, ''), 'pinhole': _pick(raw.get('pinhole'), ACUITY, ''),
        'iop': None if iop is None else int(rnd(iop)), 'cdr': None if cdr is None else rnd(cdr * 20) / 20,
        'lens': _pick(raw.get('lens'), LENS, 'clear'),
        'pupil_mm': 4 if pupil is None else rnd(pupil * 2) / 2, 'reaction': _pick(raw.get('reaction'), REACTION, 'brisk'), 'rapd': bool(raw.get('rapd')),
        'conjunctiva': _pick(raw.get('conjunctiva'), CONJUNCTIVA, 'normal'), 'discharge': _pick(raw.get('discharge'), DISCHARGE_EYE, 'none'),
        'cornea': _pick(raw.get('cornea'), CORNEA, 'clear'), 'chamber': _pick(raw.get('chamber'), CHAMBER, 'deep'),
        'field': _pick(raw.get('field'), FIELD, 'full'),
        'retina': {'dr': _pick(r.get('dr'), DR, 'none'), 'maculopathy': bool(r.get('maculopathy')), 'htn': 0 if htn is None else int(rnd(htn)),
                   'papilloedema': bool(r.get('papilloedema')), 'detachment': bool(r.get('detachment')), 'amd': _pick(r.get('amd'), AMD, 'none')},
    }


def _thresholds(raw, freqs):
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for f in freqs:
        v = _num(raw.get(f), -10, 120)
        if v is not None:
            out[f] = int(rnd(v / 5) * 5)       # audiometers step in 5 dB
    return out


def clean_ear(raw):
    raw = raw if isinstance(raw, dict) else {}
    perf = _num(raw.get('perforation_pct'), 0, 100)
    tm = _pick(raw.get('tm'), TM, 'normal')
    return {
        'examined': bool(raw.get('examined')),
        'ac': _thresholds(raw.get('ac'), FREQS), 'bc': _thresholds(raw.get('bc'), PTA_FREQS),
        'canal': _pick(raw.get('canal'), CANAL, 'clear'), 'tm': tm,
        'perforation_pct': (25 if perf is None else int(rnd(perf))) if tm == 'perforation' else 0,
        'discharge': _pick(raw.get('discharge'), DISCHARGE_EAR, 'none'), 'tympanogram': _pick(raw.get('tympanogram'), TYMPANOGRAM, ''),
        'rinne': _pick(raw.get('rinne'), ('', 'positive', 'negative'), ''),
    }


def clean_exam(raw):
    raw = raw if isinstance(raw, dict) else {}
    eyes = raw.get('eyes') if isinstance(raw.get('eyes'), dict) else {}
    ears = raw.get('ears') if isinstance(raw.get('ears'), dict) else {}
    sym = raw.get('symptoms') if isinstance(raw.get('symptoms'), dict) else {}
    return {
        'eyes': {s: clean_eye(eyes.get(s)) for s in SIDES},
        'ears': {s: clean_ear(ears.get(s)) for s in SIDES},
        'weber': _pick(raw.get('weber'), ('', 'central', 'right', 'left'), ''),
        'symptoms': {k: bool(sym.get(k)) for k in ('eye_pain', 'photophobia', 'tinnitus', 'vertigo', 'sudden_loss', 'ear_pain')},
        'notes': _txt(raw.get('notes'), 2000),
    }


# ------------------------------------------------------------------ eyes: computing
def vi_category(lm):
    for key, label, upper in VI:
        if lm <= upper:
            return key, label
    return 'blind', 'Blindness'


def compute_eye(e, side, sym, ctx, alerts, procs):
    if not e['examined']:
        return None
    where = f'{side} eye'
    lm = LOGMAR.get(e['va']) if e['va'] else None
    ph = LOGMAR.get(e['pinhole']) if e['pinhole'] else None
    cat = vi_category(lm) if lm is not None else (None, None)
    grade = LENS[e['lens']]
    iop, cdr, r = e['iop'], e['cdr'], e['retina']
    refractive = lm is not None and ph is not None and rnd(lm - ph, 1) >= 0.2

    def add(level, text):
        alerts.append({'level': level, 'text': text})

    def proc(code, reason):
        if not any(p['code'] == code and p['side'] == side for p in procs):
            procs.append({'code': code, 'side': side, 'reason': reason})

    if e['va'] == 'NPL':
        add('high', f'No perception of light in the {where}: the eye is blind.')
    # pressure and the optic nerve
    iop_state = None
    if iop is not None:
        iop_state = 'low' if iop < 6 else 'normal' if iop <= 21 else 'raised' if iop < 30 else 'high' if iop < 40 else 'very_high'
        closure = iop >= 40 and (e['chamber'] == 'shallow' or e['reaction'] != 'brisk' or sym.get('eye_pain'))
        if closure:
            add('high', f'Possible acute angle-closure glaucoma in the {where} (pressure {iop} mmHg): an emergency. Lower the pressure now and refer the same day.')
        elif iop >= 30:
            add('high', f'Pressure {iop} mmHg in the {where} is very high: start treatment and refer this week.')
        elif iop > 21:
            add('warn', f'Pressure {iop} mmHg in the {where} is raised (normal 10–21).')
        elif iop < 6:
            add('warn', f'Pressure {iop} mmHg in the {where} is very low: look for a wound leak or perforation.')
    glaucoma = None
    if cdr is not None:
        if cdr >= 0.7 and iop is not None and iop > 21:
            glaucoma = 'likely'
            add('warn', f'Glaucoma likely in the {where}: cup-to-disc {fmt(cdr)} with pressure {iop} mmHg. Start pressure-lowering drops and check the visual field.')
            proc('trabeculectomy', f'Glaucoma ({where}) if the pressure stays uncontrolled on drops')
        elif cdr >= 0.7 or (cdr >= 0.6 and iop is not None and iop > 21):
            glaucoma = 'suspect'
            add('warn', f'Glaucoma suspect in the {where} (cup-to-disc {fmt(cdr)}): repeat the pressure and test the visual field.')
    # lens
    if grade >= 3 or (grade >= 2 and lm is not None and lm >= 0.5):
        add('warn', f'Cataract is reducing vision in the {where}' + (f' ({e["va"]})' if e['va'] else '') + ': cataract surgery should restore sight.')
        proc('cataract', f'{LENS_LABELS[e["lens"]]} in the {where}' + (f', vision {e["va"]}' if e['va'] else ''))
    elif grade >= 1:
        add('info', f'Early cataract in the {where}: review yearly; surgery when it limits daily life.')
    if refractive:
        add('info', f'Vision in the {where} improves with a pinhole ({e["va"]} → {e["pinhole"]}): glasses should help.')
    # retina
    dr = r['dr']
    if dr == 'proliferative':
        add('high', f'Proliferative diabetic retinopathy in the {where}: urgent laser or anti-VEGF treatment; risk of bleeding and blindness.')
    elif dr == 'severe':
        add('high', f'Severe non-proliferative diabetic retinopathy in the {where}: refer to an eye specialist within 2–4 weeks.')
    elif dr == 'moderate':
        add('warn', f'Moderate diabetic retinopathy in the {where}: refer, and review every 3–6 months.')
    elif dr == 'mild':
        add('info', f'Mild diabetic retinopathy in the {where}: review in 12 months; control sugar and blood pressure.')
    if r['maculopathy']:
        add('high', f'Diabetic maculopathy in the {where}: refer for laser or anti-VEGF to protect central vision.')
    sbp, dbp = ctx.get('systolic'), ctx.get('diastolic')
    crisis = (sbp is not None and sbp >= 180) or (dbp is not None and dbp >= 120)
    if r['htn'] >= 3 and crisis:
        add('high', f'Hypertensive retinopathy grade {r["htn"]} with blood pressure {fmt(sbp) if sbp is not None else "?"}/{fmt(dbp) if dbp is not None else "?"}: hypertensive emergency. Lower the pressure in a monitored bed.')
    elif r['htn'] == 4:
        add('high', f'Hypertensive retinopathy grade 4 (disc swelling) in the {where}: malignant hypertension until proven otherwise.')
    elif r['htn'] >= 1:
        add('warn' if r['htn'] >= 3 else 'info', f'Hypertensive retinopathy grade {r["htn"]} in the {where}: control the blood pressure.')
    if r['detachment']:
        add('high', f'Retinal detachment in the {where}: emergency referral for surgery today; keep the patient still.')
    if r['amd'] == 'wet':
        add('high', f'Wet macular degeneration in the {where}: urgent anti-VEGF injections to save central vision.')
    elif r['amd'] == 'dry':
        add('info', f'Dry macular degeneration in the {where}: stop smoking; low-vision aids; watch for sudden distortion.')
    # front of the eye
    if e['chamber'] == 'hypopyon':
        add('high', f'Pus in the front chamber of the {where} (hypopyon): severe infection or ulcer; same-day eye surgeon.')
    elif e['chamber'] == 'hyphaema':
        add('high', f'Blood in the front chamber of the {where} (hyphaema): rest with the head up, check the pressure daily.')
    if e['cornea'] == 'ulcer':
        add('high', f'Corneal ulcer in the {where}: same-day eye review and intensive antibiotic drops; no steroid drops.')
    elif e['cornea'] == 'abrasion':
        add('warn', f'Corneal abrasion in the {where}: antibiotic ointment and review in 24–48 hours.')
    elif e['cornea'] == 'oedema':
        add('warn', f'Hazy cornea in the {where}: check the pressure.')
    if e['conjunctiva'] == 'injected' and e['discharge'] == 'purulent':
        add('info', f'Bacterial conjunctivitis likely in the {where}: antibiotic drops; wash hands and do not share towels.')
    elif e['conjunctiva'] == 'injected' and e['discharge'] == 'watery':
        add('info', f'Viral or allergic conjunctivitis likely in the {where}: cool compresses; very contagious if viral.')
    elif e['conjunctiva'] == 'pterygium':
        add('info', f'Pterygium in the {where}: sun protection; remove it if it grows towards the pupil.')
        proc('pterygium', f'Pterygium in the {where}')
    elif e['conjunctiva'] == 'haemorrhage':
        add('info', f'Subconjunctival haemorrhage in the {where}: harmless and clears in 2 weeks' + ('; the blood pressure is high, treat it.' if crisis or (sbp is not None and sbp >= 160) else '; check the blood pressure.'))
    if e['rapd']:
        add('warn', f'Relative afferent pupil defect in the {where}: optic nerve or severe retinal disease; urgent review.')
    if e['reaction'] == 'none' and e['pupil_mm'] >= 6 and not (iop is not None and iop >= 40):
        add('high', f'Fixed dilated pupil in the {where} ({fmt(e["pupil_mm"])} mm): urgent neurological review.')

    # what the patient sees (drives the vision simulation)
    scotoma = max(0.18 if r['maculopathy'] else 0, {'none': 0, 'dry': 0.12, 'wet': 0.24}[r['amd']], 0.2 if e['field'] == 'central_loss' else 0)
    field = 1.0 if cdr is None else clamp(1 - max(0, cdr - 0.5) * 1.8, 0.15, 1)
    if e['field'] == 'peripheral_loss':
        field = min(field, 0.55)
    haze = min(1, grade * 0.2 + (0.35 if e['cornea'] in ('oedema', 'scar') else 0) + (0.3 if e['chamber'] in ('hypopyon', 'hyphaema') else 0))
    vision = {'blur': rnd(clamp(lm if lm is not None else 0, 0, 2.3) * 6, 1), 'haze': rnd(haze, 2), 'tint': rnd(grade * 0.12, 2),
              'field': rnd(field, 2), 'scotoma': rnd(scotoma, 2), 'spots': {'none': 0, 'mild': 2, 'moderate': 5, 'severe': 9, 'proliferative': 14}[dr],
              'floaters': dr == 'proliferative', 'curtain': 0.45 if r['detachment'] else 0,
              'dark': {'NPL': 1, 'PL': 0.9, 'HM': 0.6}.get(e['va'], 0)}
    outflow = 1.0 if iop is None or iop <= 21 else rnd(21 / iop, 2)
    if e['chamber'] == 'shallow' and iop is not None and iop >= 30:
        outflow = 0.15
    return {'logmar': lm, 'pinhole_logmar': ph, 'category': cat[0], 'category_label': cat[1], 'refractive': refractive,
            'lens_grade': grade, 'iop_state': iop_state, 'glaucoma': glaucoma, 'outflow': outflow, 'vision': vision}


# ------------------------------------------------------------------ ears: computing
def _avg(values):
    return rnd(sum(values) / len(values), 1) if values else None


def hearing_grade(pta):
    for key, label, upper in HEARING:
        if pta < upper:
            return key, label
    return 'complete', 'Complete hearing loss'


def compute_ear(a, side, sym, ctx, alerts, procs):
    if not a['examined']:
        return None
    where = f'{side} ear'
    ac, bc = a['ac'], a['bc']
    pta_vals = [ac[f] for f in PTA_FREQS if f in ac]
    pta = _avg(pta_vals) if len(pta_vals) >= 3 else None
    bc_vals = [bc[f] for f in PTA_FREQS if f in bc]
    bc_pta = _avg(bc_vals) if bc_vals else None
    gaps = [ac[f] - bc[f] for f in PTA_FREQS if f in ac and f in bc]
    gap = _avg(gaps)
    grade = hearing_grade(pta) if pta is not None else (None, None)
    signs = (a['canal'] in ('impacted_wax', 'foreign_body', 'otitis_externa') or a['tm'] in ('effusion', 'bulging', 'perforation', 'cholesteatoma')
             or a['tympanogram'] in ('B', 'C') or a['rinne'] == 'negative')
    kind = None
    if pta is not None:
        if pta < 20 and (gap is None or gap < 15):
            kind = 'normal'
        elif gap is not None:
            kind = ('mixed' if bc_pta is not None and bc_pta >= 20 else 'conductive') if gap >= 15 else 'sensorineural'
        else:
            kind = 'conductive_probable' if signs else 'sensorineural_probable'
    notch = '4000' in ac and '2000' in ac and ac['4000'] - ac['2000'] >= 15 and ('8000' not in ac or ac['4000'] - ac['8000'] >= 5)
    lows = [ac[f] for f in ('250', '500') if f in ac]
    highs = [ac[f] for f in ('4000', '8000') if f in ac]
    sloping = bool(lows and highs) and _avg(highs) - _avg(lows) >= 20
    low_tone = bool(lows and highs) and _avg(lows) - _avg(highs) >= 10

    def add(level, text):
        alerts.append({'level': level, 'text': text})

    def proc(code, reason):
        if not any(p['code'] == code and p['side'] == side for p in procs):
            procs.append({'code': code, 'side': side, 'reason': reason})

    neural = kind in ('sensorineural', 'mixed', 'sensorineural_probable')
    if sym.get('sudden_loss') and neural:
        add('high', f'Sudden sensorineural hearing loss in the {where}: an emergency. Start oral steroids within 72 hours and see ENT today.')
    if notch and neural:
        add('info', f'Dip at 4 kHz in the {where}: typical of noise damage; protect the ears from loud noise.')
    if sloping and neural and ctx.get('age') is not None and ctx['age'] >= 60:
        add('info', f'High-frequency loss sloping down in the {where}: age-related hearing loss (presbycusis).')
    if low_tone and neural and sym.get('vertigo') and sym.get('tinnitus'):
        add('warn', f'Low-tone loss with vertigo and tinnitus in the {where}: possible Ménière’s disease; refer to ENT.')
    # otoscopy
    if a['canal'] == 'impacted_wax':
        add('warn', f'Impacted wax in the {where}: remove it (microsuction or syringing) and test the hearing again.')
        proc('ear-microsuction', f'Impacted wax in the {where}')
    elif a['canal'] == 'foreign_body':
        add('warn', f'Foreign body in the {where}: remove it under direct vision; do not syringe batteries or seeds.')
        proc('ear-microsuction', f'Foreign body in the {where}')
    elif a['canal'] == 'otitis_externa':
        if ctx.get('diabetic') and ctx.get('age') is not None and ctx['age'] >= 60:
            add('high', f'Otitis externa in an older person with diabetes ({where}): rule out necrotising (malignant) otitis externa.')
        else:
            add('warn', f'Otitis externa in the {where}: clean the canal, antibiotic–steroid drops, keep it dry.')
    if a['tm'] == 'bulging':
        add('warn', f'Acute otitis media in the {where}: pain relief; antibiotics if severe, under 2 years old, or discharging.')
    elif a['tm'] == 'effusion':
        add('info', f'Fluid behind the {where} drum (glue ear): watch for 3 months; grommets if it persists with hearing loss.')
        if pta is not None and pta >= 25:
            proc('grommet', f'Glue ear in the {where} with hearing loss ({fmt(pta)} dB)')
    elif a['tm'] == 'perforation':
        if a['discharge'] in ('mucoid', 'purulent'):
            add('warn', f'Chronic suppurative otitis media in the {where} ({a["perforation_pct"]}% perforation, discharging): dry mopping and antibiotic drops; repair once dry.')
        else:
            add('info', f'Dry perforation of the {where} drum ({a["perforation_pct"]}%): a tympanoplasty can close it and improve hearing.')
        proc('tympanoplasty', f'{a["perforation_pct"]}% perforation of the {where} drum')
    elif a['tm'] == 'cholesteatoma':
        add('high', f'Cholesteatoma in the {where}: it erodes bone and can reach the brain; refer for mastoid surgery.')
        proc('mastoidectomy', f'Cholesteatoma in the {where}')
    elif a['tm'] == 'retracted':
        add('info', f'Retracted {where} drum: Eustachian tube not opening well.')
    if a['discharge'] == 'bloody':
        add('warn', f'Blood from the {where}: after head injury, suspect a skull-base fracture.')

    # the sound path (drives the ear animation and the hearing simulation)
    block = BLOCK[a['canal']]
    mob = MOBILITY_TYMP[a['tympanogram']] if a['tympanogram'] else MOBILITY_TM[a['tm']]
    fluid = {'effusion': 0.65, 'bulging': 1}.get(a['tm'], 0)
    if gap is not None:
        conduct = clamp(1 - max(0, gap) / 60, 0.05, 1)
    else:
        conduct = clamp(1 - (block * 0.7 + (1 - min(1, mob)) * 0.5), 0.05, 1)
    conductive_only = kind in ('conductive', 'conductive_probable')
    cochlea = {}
    for f in FREQS:
        th = bc[f] if f in bc else (None if conductive_only else ac.get(f))
        cochlea[f] = 0 if th is None else rnd(clamp((th - 15) / 90, 0, 1), 2)
    return {'pta': pta, 'grade': grade[0], 'grade_label': grade[1], 'bc_pta': bc_pta, 'gap': gap, 'type': kind,
            'type_label': TYPE_LABELS.get(kind) if kind else None, 'notch': notch, 'sloping': sloping,
            'block': block, 'mobility': mob, 'fluid': fluid, 'conduct': rnd(conduct, 2), 'cochlea': cochlea,
            'signal': rnd(clamp(1 - pta / 100, 0, 1), 2) if pta is not None else 1}


# ------------------------------------------------------------------ the whole examination
def compute(data, ctx=None):
    """ctx: age, diabetic, hba1c, systolic, diastolic (from the chart), all optional."""
    ctx = ctx or {}
    sym = data.get('symptoms') or {}
    alerts, procs = [], []
    eyes = {s: compute_eye(data['eyes'][s], s, sym, ctx, alerts, procs) for s in SIDES}
    ears = {s: compute_ear(data['ears'][s], s, sym, ctx, alerts, procs) for s in SIDES}

    # both eyes together
    seen = [eyes[s] for s in SIDES if eyes[s] and eyes[s]['logmar'] is not None]
    vision = None
    if seen:
        best = min(x['logmar'] for x in seen)
        cat = vi_category(best)
        vision = {'better_logmar': best, 'category': cat[0], 'label': cat[1]}
        if len(seen) == 2 and cat[0] == 'blind':
            alerts.append({'level': 'high', 'text': 'Blindness (the better eye sees less than 3/60): refer for rehabilitation and treat any cause that can be reversed.'})
        elif len(seen) == 2 and cat[0] in ('moderate', 'severe'):
            alerts.append({'level': 'warn', 'text': f'{cat[1]} (better eye): affects reading, work and moving about safely.'})
    cdrs = [data['eyes'][s]['cdr'] for s in SIDES if eyes[s] and data['eyes'][s]['cdr'] is not None]
    if len(cdrs) == 2 and rnd(abs(cdrs[0] - cdrs[1]), 2) >= 0.2:
        alerts.append({'level': 'warn', 'text': f'Cup-to-disc ratios differ by {fmt(rnd(abs(cdrs[0] - cdrs[1]), 2))} between the eyes: a sign of glaucoma.'})
    if any(eyes[s] and data['eyes'][s]['retina']['papilloedema'] for s in SIDES):
        alerts.append({'level': 'high', 'text': 'Papilloedema (swollen optic discs): raised pressure inside the skull until proven otherwise; urgent brain scan.'})
    any_dr = any(eyes[s] and data['eyes'][s]['retina']['dr'] != 'none' for s in SIDES)
    if any_dr and ctx.get('hba1c') is not None and ctx['hba1c'] >= 8:
        alerts.append({'level': 'warn', 'text': f'HbA1c {fmt(ctx["hba1c"])}% with diabetic retinopathy: better sugar control slows the damage.'})
    if ctx.get('diabetic') and any(eyes[s] for s in SIDES) and not any_dr:
        alerts.append({'level': 'info', 'text': 'Diabetes with no retinopathy seen: screen the eyes again in 12 months.'})

    # both ears together
    ptas = [ears[s]['pta'] for s in SIDES if ears[s] and ears[s]['pta'] is not None]
    hearing = None
    if ptas:
        best = min(ptas)
        g = hearing_grade(best)
        hearing = {'better_pta': best, 'grade': g[0], 'label': g[1], 'aid': len(ptas) == 2 and best >= 35}
        if hearing['aid']:
            alerts.append({'level': 'warn', 'text': f'{g[1]} in the better ear ({fmt(best)} dB): offer hearing aids and check again in a year.'})
        if len(ptas) == 2 and best >= 80 and all(ears[s]['type'] in ('sensorineural', 'sensorineural_probable') for s in SIDES):
            alerts.append({'level': 'info', 'text': 'Severe-to-profound sensorineural loss in both ears: assess for a cochlear implant.'})
    if len(ptas) == 2 and abs(ptas[0] - ptas[1]) >= 15 and all(ears[s]['type'] in ('sensorineural', 'sensorineural_probable', 'normal') for s in SIDES):
        alerts.append({'level': 'warn', 'text': f'Hearing differs by {fmt(rnd(abs(ptas[0] - ptas[1]), 1))} dB between the ears without a conductive cause: MRI to exclude a vestibular schwannoma.'})
    if data.get('weber') in SIDES:
        other = 'left' if data['weber'] == 'right' else 'right'
        alerts.append({'level': 'info', 'text': f'Weber test heard in the {data["weber"]} ear: conductive loss on the {data["weber"]} or sensorineural loss on the {other}.'})

    seen_text = set()
    alerts = [a for a in alerts if not (a['text'] in seen_text or seen_text.add(a['text']))]   # same message from both sides once
    alerts.sort(key=lambda a: ORDER[a['level']])
    return {'eyes': eyes, 'ears': ears, 'vision': vision, 'hearing': hearing, 'alerts': alerts, 'procedures': procs}


def summary(computed, data):
    bits = []
    v, h = computed.get('vision'), computed.get('hearing')
    if v:
        bits.append(v['label'])
    for s in SIDES:
        e = (computed.get('eyes') or {}).get(s)
        if e and e.get('glaucoma'):
            bits.append(f'glaucoma {e["glaucoma"]} ({s[0].upper()})')
    if h:
        bits.append(f'{h["label"]} ({fmt(h["better_pta"])} dB)')
    n = sum(1 for a in computed.get('alerts', []) if a['level'] == 'high')
    if n:
        bits.append(f'{n} urgent finding{"s" if n > 1 else ""}')
    return ' · '.join(bits) or 'No findings recorded'


def catalogue():
    return {'acuity': ACUITY, 'acuity_labels': ACUITY_LABELS, 'logmar': LOGMAR, 'lens': LENS_LABELS, 'lens_grade': LENS,
            'conjunctiva': CONJUNCTIVA, 'discharge_eye': DISCHARGE_EYE, 'cornea': CORNEA, 'chamber': CHAMBER, 'reaction': REACTION,
            'dr': DR, 'amd': AMD, 'field': FIELD, 'freqs': FREQS, 'pta_freqs': PTA_FREQS, 'canal': CANAL, 'tm': TM,
            'discharge_ear': DISCHARGE_EAR, 'tympanogram': TYMPANOGRAM, 'types': TYPE_LABELS, 'procedures': PROCEDURES,
            'vi': [[k, l, u] for k, l, u in VI], 'hearing': [[k, l, u] for k, l, u in HEARING],
            'block': BLOCK, 'mobility_tymp': MOBILITY_TYMP, 'mobility_tm': MOBILITY_TM}
