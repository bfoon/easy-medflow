"""Explainable, display-only laboratory visuals. NEVER produces a diagnosis.

Only verified results may drive patient visuals. Assay-specific reference intervals and
units are read from the validated lab catalogue; none are guessed or converted here.
"""
from decimal import Decimal, InvalidOperation

MARKERS = {
    'hb': {'hgb', 'hb', 'hemoglobin', 'haemoglobin'},
    'hct': {'hct', 'hematocrit', 'haematocrit', 'pcv'},
    'rbc': {'rbc', 'redbloodcellcount', 'redcellcount'},
    'wbc': {'wbc', 'whitebloodcellcount', 'whitecellcount'},
    'plt': {'plt', 'platelets', 'plateletcount'},
    'retic': {'retic', 'reticulocytes', 'reticulocytecount'},
    'hbs': {'hbs', 'hbspercent', 'hemoglobins', 'haemoglobins'},
    'hba': {'hba', 'hbapercent', 'hemoglobina', 'haemoglobina'},
    'hbf': {'hbf', 'hbfpercent', 'hemoglobinf', 'haemoglobinf'},
    'hba2': {'hba2', 'hba2percent', 'hemoglobina2'},
    'ferritin': {'ferritin'},
    'mcv': {'mcv', 'meancorpuscularvolume'},
    'bilirubin': {'totalbilirubin', 'bilirubin'},
}

def normalize(s):
    return ''.join(c for c in str(s).lower() if c.isalnum())

def ratio(value, low, high):
    """Bounded visual displacement from test-specific validated interval."""
    try:
        x, lo, hi = [Decimal(str(v)) for v in (value, low, high)]
        if not (lo < hi) or not all(v.is_finite() for v in (x, lo, hi)):
            return None
        midpoint = (lo + hi) / 2
        return round(float(max(Decimal('-1'), min(Decimal('1'), (x - midpoint) / (hi - lo)))), 3)
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None

def build_hematology_scene(values):
    """Values are dictionaries: code, name, number, unit, low, high, flag,
    verified, test, observed_at. Data are patient-specific; no PHI is required.
    """
    candidates = {}
    for item in values:
        if not item.get('verified') or item.get('number') is None:
            continue
        token = normalize(item.get('code', ''))
        name = normalize(item.get('name', ''))
        key = next((k for k, aliases in MARKERS.items() if token in aliases or name in aliases), None)
        if key is None:
            continue
        # Input should be supplied newest-first: first verified reading per marker wins.
        if key not in candidates:
            level = ratio(item['number'], item.get('low'), item.get('high'))
            candidates[key] = {
                'value': str(item['number']), 'unit': item.get('unit', ''),
                'low': str(item['low']) if item.get('low') is not None else None,
                'high': str(item['high']) if item.get('high') is not None else None,
                'flag': item.get('flag', ''), 'deviation': level,
                'test': item.get('test', ''), 'observed_at': item.get('observed_at', ''),
            }
    hb = candidates.get('hb')
    hb_s = candidates.get('hbs')
    retic = candidates.get('retic')
    platelets = candidates.get('plt')
    wbc = candidates.get('wbc')
    # Sickling shapes only when HbS was MEASURED. A positive HbS signal is not a genotype.
    has_hbs = False
    if hb_s and hb_s['unit'].strip().lower() in ('%', 'percent', 'percentage'):
        try:
            has_hbs = Decimal(hb_s['value']) > 0
        except InvalidOperation:
            pass
    return {
        'markers': candidates,
        'visual': {
            'red_cell_density': max(0.2, min(1.0, 0.65 + ((hb or {}).get('deviation') or 0) * 0.5)) if hb else None,
            'sickled_cell_fraction': min(0.65, max(0, float(Decimal(hb_s['value']) / 100) * 0.65)) if has_hbs else 0,
            'show_sickling': has_hbs,
            'reticulocyte_activity': (retic or {}).get('deviation'),
            'platelet_activity': (platelets or {}).get('deviation'),
            'white_cell_activity': (wbc or {}).get('deviation'),
        },
        'explanations': [
            'The visualization reflects the latest verified laboratory values, not a diagnosis or a microscopic image.',
            'HbS proportion is used only when a validated HbS measurement is recorded. It cannot independently distinguish trait, disease, or recent transfusion.',
            'Cell shapes and quantities are schematic representations; do not infer clinical severity from animation intensity.',
        ],
    }
