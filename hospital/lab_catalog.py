"""Standard laboratory catalogue loaded by `bootstrap_hospital`.

Reference intervals are typical adult values for illustration. Every laboratory must validate and replace them
with its own analyser- and population-specific ranges (Configuration → Lab parameters) before clinical use.
"""


def N(code, name, unit, lo=None, hi=None, clo=None, chi=None, dec=1, flo=None, fhi=None, sys=''):
    return dict(code=code, name=name, kind='number', unit=unit, ref_low=lo, ref_high=hi, critical_low=clo, critical_high=chi,
                decimals=dec, female_ref_low=flo, female_ref_high=fhi, body_system=sys)


def C(code, name, choices, abnormal, sys=''):
    return dict(code=code, name=name, kind='choice', choices=choices, abnormal_choices=abnormal, body_system=sys)


def T(code, name, sys=''):
    return dict(code=code, name=name, kind='text', body_system=sys)


GRADES = ['Negative', 'Trace', '1+', '2+', '3+']
CATALOG = [
    ('hematology', 'Hematology', '#C8323F', [
        ('CBC', 'Complete Blood Count', 'blood', 'Whole blood', 'Purple-top EDTA', 4, [
            N('HB', 'Haemoglobin', 'g/dL', 13.5, 17.5, 7, 20, 1, 12.0, 15.5),
            N('WBC', 'White cell count', '×10⁹/L', 4.0, 11.0, 2.0, 30.0, 1, sys='immune'),
            N('PLT', 'Platelets', '×10⁹/L', 150, 400, 50, 1000, 0),
            N('RBC', 'Red cell count', '×10¹²/L', 4.5, 5.9, None, None, 2, 4.1, 5.1),
            N('HCT', 'Haematocrit', '%', 41, 53, 20, 60, 1, 36, 46),
            N('MCV', 'Mean cell volume', 'fL', 80, 100, None, None, 0)]),
        ('HB', 'Haemoglobin', 'blood', 'Whole blood', 'Purple-top EDTA', 1, [N('HB', 'Haemoglobin', 'g/dL', 13.5, 17.5, 7, 20, 1, 12.0, 15.5)]),
        ('ESR', 'Erythrocyte Sedimentation Rate', 'immune', 'Whole blood', 'Black-top citrate', 2, [N('ESR', 'ESR', 'mm/hr', 0, 20, None, None, 0)]),
        ('MAL', 'Malaria RDT', 'blood', 'Capillary blood', 'Finger prick', 1, [
            C('RDT', 'Malaria antigen', ['Negative', 'Positive · P. falciparum', 'Positive · non-falciparum'], ['Positive · P. falciparum', 'Positive · non-falciparum'])]),
        ('MPS', 'Malaria Blood Film', 'blood', 'Whole blood', 'Purple-top EDTA', 2, [
            N('DENS', 'Parasite density', '/µL', None, 0, None, 100000, 0), C('SPEC', 'Species seen', ['None', 'P. falciparum', 'P. malariae', 'P. ovale', 'P. vivax'], ['P. falciparum', 'P. malariae', 'P. ovale', 'P. vivax'])]),
        ('BGRP', 'Blood Group & Rhesus', 'blood', 'Whole blood', 'Purple-top EDTA', 1, [
            C('ABO', 'Blood group', ['A+', 'A−', 'B+', 'B−', 'AB+', 'AB−', 'O+', 'O−'], [])]),
    ]),
    ('chemistry', 'Clinical Chemistry', '#4A5FC1', [
        ('GLU', 'Blood Glucose (fasting)', 'pancreas', 'Plasma', 'Grey-top fluoride', 1, [N('FBG', 'Fasting glucose', 'mmol/L', 3.9, 5.5, 2.8, 22.2)]),
        ('HBA1C', 'HbA1c', 'pancreas', 'Whole blood', 'Purple-top EDTA', 24, [N('A1C', 'HbA1c', '%', 4.0, 5.6, None, 14)]),
        ('LFT', 'Liver Function Panel', 'liver', 'Serum', 'Gold-top SST', 6, [
            N('ALT', 'ALT', 'U/L', 7, 56, None, 1000, 0), N('AST', 'AST', 'U/L', 10, 40, None, 1000, 0),
            N('ALP', 'Alkaline phosphatase', 'U/L', 44, 147, None, None, 0), N('TBIL', 'Total bilirubin', 'µmol/L', 3, 21, None, 300, 0),
            N('ALB', 'Albumin', 'g/L', 35, 50, 20, None, 0)]),
        ('RFT', 'Renal Function Panel', 'kidneys', 'Serum', 'Gold-top SST', 6, [
            N('CREA', 'Creatinine', 'µmol/L', 62, 115, None, 700, 0, 53, 97), N('UREA', 'Urea', 'mmol/L', 2.5, 7.1, None, 30),
            N('NA', 'Sodium', 'mmol/L', 135, 145, 120, 160, 0), N('K', 'Potassium', 'mmol/L', 3.5, 5.1, 2.8, 6.2),
            N('CL', 'Chloride', 'mmol/L', 98, 107, None, None, 0)]),
        ('PANC', 'Pancreatic Enzymes', 'pancreas', 'Serum', 'Gold-top SST', 6, [
            N('LIPA', 'Lipase', 'U/L', 13, 60, None, 600, 0), N('AMY', 'Amylase', 'U/L', 30, 110, None, 1000, 0)]),
        ('CRP', 'C-Reactive Protein', 'immune', 'Serum', 'Gold-top SST', 4, [N('CRP', 'CRP', 'mg/L', 0, 5, None, 200, 1)]),
        ('BONE', 'Bone Profile', 'bone', 'Serum', 'Gold-top SST', 24, [
            N('CA', 'Calcium (adjusted)', 'mmol/L', 2.2, 2.6, 1.75, 3.25, 2), N('PHOS', 'Phosphate', 'mmol/L', 0.8, 1.5, 0.3, None, 2),
            N('VITD', 'Vitamin D (25-OH)', 'nmol/L', 50, 125, None, None, 0)]),
    ]),
    ('cardiac', 'Cardiac Markers', '#D7263D', [
        ('TROP', 'Troponin I (high-sensitivity)', 'heart', 'Serum', 'Gold-top SST', 1, [N('TNI', 'Troponin I', 'ng/L', 0, 34, None, 100, 0, 0, 16)]),
        ('CARD', 'Cardiac Panel', 'heart', 'Serum', 'Gold-top SST', 2, [
            N('CKMB', 'CK-MB', 'U/L', 0, 25, None, 100, 0), N('BNP', 'BNP', 'pg/mL', 0, 100, None, 900, 0)]),
        ('LIPID', 'Lipid Profile', 'heart', 'Serum (fasting)', 'Gold-top SST', 24, [
            N('TC', 'Total cholesterol', 'mmol/L', None, 5.2), N('LDL', 'LDL cholesterol', 'mmol/L', None, 3.4),
            N('HDL', 'HDL cholesterol', 'mmol/L', 1.0, None, None, None, 1, 1.3, None), N('TG', 'Triglycerides', 'mmol/L', None, 1.7, None, 11.3)]),
    ]),
    ('endocrine', 'Endocrinology', '#8A4A8F', [
        ('TFT', 'Thyroid Function', 'thyroid', 'Serum', 'Gold-top SST', 24, [
            N('TSH', 'TSH', 'mIU/L', 0.4, 4.0, 0.01, 50, 2), N('FT4', 'Free T4', 'pmol/L', 12, 22, 5, 60, 1)]),
        ('HCG', 'Pregnancy Test (β-hCG)', 'reproductive', 'Urine', 'Sterile container', 1, [C('HCG', 'β-hCG', ['Negative', 'Positive'], [])]),
        ('PSA', 'Prostate-Specific Antigen', 'reproductive', 'Serum', 'Gold-top SST', 24, [N('PSA', 'PSA', 'ng/mL', 0, 4, None, None, 2)]),
    ]),
    ('urinalysis', 'Urinalysis', '#E0912A', [
        ('UA', 'Urinalysis', 'bladder', 'Urine (midstream)', 'Sterile container', 1, [
            C('APP', 'Appearance', ['Clear', 'Slightly cloudy', 'Cloudy', 'Bloody'], ['Cloudy', 'Bloody']),
            N('PH', 'pH', '', 4.5, 8.0, None, None, 1), N('SG', 'Specific gravity', '', 1.005, 1.030, None, None, 3),
            C('PRO', 'Protein', GRADES, GRADES[2:], 'kidneys'), C('UGLU', 'Glucose', GRADES, GRADES[1:]),
            C('NIT', 'Nitrite', ['Negative', 'Positive'], ['Positive']), C('LEU', 'Leukocytes', GRADES, GRADES[2:]),
            C('UBLD', 'Blood', GRADES, GRADES[1:])]),
    ]),
    ('microbiology', 'Microbiology & Parasitology', '#5E7D2B', [
        ('STL', 'Stool Microscopy', 'stomach', 'Stool', 'Stool container', 24, [
            C('OVA', 'Ova & parasites', ['None seen', 'Present'], ['Present']), C('FOB', 'Occult blood', ['Negative', 'Positive'], ['Positive']),
            T('NOTE', 'Microscopy findings')]),
        ('AFB', 'Sputum AFB Smear', 'lungs', 'Sputum', 'Sputum pot', 24, [C('AFB', 'Acid-fast bacilli', ['Negative', 'Scanty', '1+', '2+', '3+'], ['Scanty', '1+', '2+', '3+'])]),
        ('XPERT', 'GeneXpert MTB/RIF', 'lungs', 'Sputum', 'Sputum pot', 4, [
            C('MTB', 'M. tuberculosis', ['Not detected', 'Detected'], ['Detected']), C('RIF', 'Rifampicin resistance', ['Not detected', 'Detected', 'Indeterminate'], ['Detected'])]),
        ('CSF', 'CSF Analysis', 'brain', 'Cerebrospinal fluid', 'Sterile tubes ×3', 4, [
            N('CGLU', 'CSF glucose', 'mmol/L', 2.2, 3.9, 1.0, None), N('CPRO', 'CSF protein', 'g/L', 0.15, 0.45, None, 2.0, 2),
            N('CWBC', 'CSF white cells', 'cells/µL', 0, 5, None, 100, 0), T('GRAM', 'Gram stain')]),
    ]),
    ('serology', 'Serology & Immunology', '#5A6F7D', [
        ('HIV', 'HIV 1/2 Rapid Test', 'immune', 'Whole blood', 'Finger prick', 1, [C('HIV', 'HIV 1/2 antibody', ['Non-reactive', 'Reactive', 'Indeterminate'], ['Reactive', 'Indeterminate'])]),
        ('HBSAG', 'Hepatitis B Surface Antigen', 'liver', 'Serum', 'Gold-top SST', 1, [C('HBS', 'HBsAg', ['Non-reactive', 'Reactive'], ['Reactive'])]),
    ]),
    ('blood-gas', 'Blood Gas', '#0F7B78', [
        ('ABG', 'Arterial Blood Gas', 'lungs', 'Arterial blood', 'Heparinised syringe', 1, [
            N('PH', 'pH', '', 7.35, 7.45, 7.20, 7.60, 2), N('PCO2', 'pCO₂', 'kPa', 4.7, 6.0, None, 9.0, 1),
            N('PO2', 'pO₂', 'kPa', 10.5, 13.5, 6.7, None, 1), N('HCO3', 'Bicarbonate', 'mmol/L', 22, 26, 10, 40, 0),
            N('SAO2', 'O₂ saturation', '%', 95, 100, 85, None, 0)]),
    ]),
]
