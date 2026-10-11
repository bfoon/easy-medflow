"""Disease categories for finding patients quickly. Loosely follows the ICD-10 chapters, with plain names.

A diagnosis or condition is filed under the first category whose keywords it contains. Order matters: specific
diseases come first, the organ systems next, and generic words such as "infection" or "fever" last.
"""
import re

# key, label, ICD-10 chapter letters (for reference), Bootstrap icon, colour, keywords
CATEGORIES = [
    ('infectious', 'Infections & tropical', 'A–B', 'bi-bug', '#5E7D2B',
     ['malaria', 'typhoid', 'tubercul', ' tb ', 'hiv', 'cholera', 'measles', 'dengue', 'sepsis', 'septic', 'schistosom', 'worm', 'helminth', 'tetanus', 'yellow fever', 'ebola', 'covid', 'mpox']),
    ('musculoskeletal', 'Bones, joints & spine', 'M', 'bi-person-standing', '#B8860B',
     ['fracture', 'spine', 'spinal', 'vertebr', 'disc ', 'disc,', 'disc prolapse', 'disc herniation', 'back pain', 'backache', 'lumbar', 'cervical spine', 'sciatica',
      'osteo', 'arthritis', 'arthrosis', 'gout', 'sprain', 'dislocat', 'ligament', 'tendon', 'meniscus', 'joint', 'bone', 'scoliosis', 'rheumat', 'whiplash',
      'paraplegi', 'tetraplegi', 'cord injury', 'supracondylar', 'femur', 'femoral', 'tibia', 'radius', 'humerus', 'clavicle', 'pelvic fracture', 'hip fracture']),
    ('injury', 'Injuries & trauma', 'S–T', 'bi-bandaid', '#C2410C',
     ['injury', 'injuries', 'trauma', 'burn', 'wound', 'laceration', 'road traffic', ' rta ', 'assault', 'bite', 'poison', 'overdose', 'concussion', 'fall from']),
    ('maternal', "Pregnancy & women's health", 'O / N7–N9', 'bi-balloon-heart', '#C2477A',
     ['pregnan', 'antenatal', 'eclampsia', 'labour', 'labor', 'postpartum', 'postnatal', 'miscarriage', 'obstetric', 'delivery', 'caesarean', 'ectopic',
      'pelvic inflammatory', 'fibroid', 'menstrua', 'amenorrh', 'ovarian cyst', 'vaginal', 'infertility', 'gynae', 'gyneco', 'family planning']),
    ('neurological', 'Brain & nerves', 'G', 'bi-lightning', '#7C3AED',
     ['stroke', 'epilep', 'seizure', 'convuls', 'meningitis', 'encephal', 'migraine', 'headache', 'neuropath', 'palsy', 'absence', 'dementia', 'parkinson', 'neuro']),
    ('cardiovascular', 'Heart & circulation', 'I', 'bi-heart-pulse', '#C8323F',
     ['hypertension', 'coronary', 'heart', 'cardiac', 'angina', 'arrhythm', 'infarct', 'atrial', 'cardiomyopathy', 'thrombosis', 'dvt', 'embolism']),
    ('respiratory', 'Lungs & breathing', 'J', 'bi-lungs', '#0E7490',
     ['pneumonia', 'respiratory', 'asthma', 'copd', 'bronch', 'urti', 'cough', 'sinusitis', 'pharyngitis', 'influenza', 'lung']),
    ('renal', 'Kidney & urinary', 'N', 'bi-droplet-half', '#4A5FC1',
     ['urinary', ' uti ', 'kidney', 'renal', 'nephr', 'pyelo', 'cystitis', 'prostat', 'urolith', 'kidney stone']),
    ('digestive', 'Stomach, liver & gut', 'K', 'bi-egg-fried', '#B45309',
     ['gastr', 'peptic', 'duodenal', 'diarrh', 'dysentery', 'liver', 'hepat', 'cirrho', 'cholelith', 'gallstone', 'cholecyst', 'appendic', 'hernia', 'constipat', 'dyspeps',
      'pancreat', 'colitis', 'bowel', 'vomiting', 'h. pylori']),
    ('endocrine', 'Diabetes, thyroid & metabolism', 'E', 'bi-capsule', '#0F7B78',
     ['diabet', 'thyroid', 'obesity', 'malnutrition', 'dehydration', 'metabolic', 'hypoglyc', 'hyperkal', 'electrolyte']),
    ('blood', 'Blood & anaemia', 'D', 'bi-droplet', '#9F1239',
     ['anaemia', 'anemia', 'sickle', 'thalass', 'bleeding disorder', 'thrombocytop', 'leukaem', 'leukem']),
    ('mental', 'Mental health', 'F', 'bi-emoji-neutral', '#6D28D9',
     ['depress', 'anxiety', 'psychos', 'schizo', 'bipolar', 'substance', 'alcohol use', 'mental', 'insomnia']),
    ('skin', 'Skin', 'L', 'bi-hand-index-thumb', '#A16207',
     ['skin', 'rash', 'dermat', 'eczema', 'cellulitis', 'abscess', 'scabies', 'tinea', 'fungal', 'impetigo', 'ulcer of skin']),
    ('eye_ent', 'Eyes, ears, nose & throat', 'H', 'bi-eye', '#0369A1',
     ['eye', 'conjunctiv', 'cataract', 'glaucoma', 'otitis', ' ear ', 'tonsil', 'epistaxis', 'hearing']),
    ('cancer', 'Cancer', 'C', 'bi-radioactive', '#334155',
     ['cancer', 'tumour', 'tumor', 'carcinoma', 'lymphoma', 'malignan', 'metasta', 'sarcoma']),
    ('infectious_generic', None, None, None, None, ['infection', 'fever', 'febrile']),   # generic words: filed under infections
]
OTHER = ('other', 'Other / not classified', '', 'bi-three-dots', '#64748B')

CHOICES = [(c[0], c[1]) for c in CATEGORIES if c[1]] + [(OTHER[0], OTHER[1])]
INFO = {c[0]: {'key': c[0], 'label': c[1], 'icd': c[2], 'icon': c[3], 'color': c[4]} for c in CATEGORIES if c[1]}
INFO[OTHER[0]] = dict(zip(('key', 'label', 'icd', 'icon', 'color'), OTHER))


def classify(*texts):
    """Category key for a diagnosis or condition text; '' when there is no text at all."""
    t = ' ' + re.sub(r'[\s,;:/()\-.]+', ' ', ' '.join(x for x in texts if x)).lower() + ' '
    if not t.strip():
        return ''
    for key, _label, _icd, _icon, _colour, words in CATEGORIES:
        if any(w in t for w in words):
            return 'infectious' if key == 'infectious_generic' else key
    return OTHER[0]
