"""Add sample referral facilities, specialists and bookable appointment slots to the referral network.

Safe to run more than once and on a database that already has data: nothing is wiped, existing facilities and
specialists are reused by name, and only missing future slots are added. All names, phone numbers and emails are
FICTIONAL samples; edit or remove them under Configuration → Network facilities before going live.

    python manage.py seed_network                 # add facilities, specialists, 21 days of slots
    python manage.py seed_network --days 30       # slots for the next 30 days
    python manage.py seed_network --slots-only    # just top up slots for every active specialist
    python manage.py seed_network --remove        # take the sample entries out again
"""
import random
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

SAMPLE_DOMAIN = 'sample-network.example'
LANG = 'English, Wolof, Mandinka'

# name, kind, town, phone, capabilities
FACILITIES = [
    # the six facilities the demo seed also uses, so the two commands share one network
    ('Kotu Heart Centre', 'clinic', 'Kotu', '+220 446 1200', 'Cath lab, Echocardiography, Cardiac ICU, Stress testing'),
    ('Banjul Regional Teaching Hospital', 'hospital', 'Banjul', '+220 422 8000', 'ICU, General surgery, Neurosurgery, CT, MRI, Dialysis'),
    ('Riverside Orthopaedic & Spine Clinic', 'clinic', 'Bakau', '+220 449 3311', 'Orthopaedic theatre, Physiotherapy, X-ray'),
    ('Atlantic Diagnostics', 'diagnostic', 'Kololi', '+220 446 7788', 'MRI, CT, Ultrasound, Mammography'),
    ('Brikama Mother & Child Centre', 'maternity', 'Brikama', '+220 448 2020', 'Obstetric theatre, NICU, Ultrasound'),
    ('Serene Rehabilitation Centre', 'rehab', 'Lamin', '+220 445 9090', 'Physiotherapy, Speech therapy, Occupational therapy'),
    # specialist clinics in the Greater Banjul Area
    ('Westfield Gastro & Liver Clinic', 'clinic', 'Serrekunda', '+220 437 5120', 'Endoscopy, Colonoscopy, Liver clinic, Abdominal ultrasound, H. pylori breath test'),
    ('Latrikunda Kidney & Urology Centre', 'clinic', 'Latrikunda', '+220 439 2214', 'Haemodialysis, Cystoscopy, Lithotripsy, Prostate clinic, Urodynamics'),
    ('Kololi Oncology & Haematology Unit', 'clinic', 'Kololi', '+220 446 3390', 'Chemotherapy, Haematology clinic, Blood transfusion, Sickle cell clinic'),
    ('Fajara Eye & ENT Clinic', 'clinic', 'Fajara', '+220 449 6602', 'Cataract surgery, Glaucoma clinic, Audiology, ENT theatre'),
    ('Brusubi Mind & Wellbeing Centre', 'clinic', 'Brusubi', '+220 446 9935', 'Psychiatry, Psychology, Addiction support, Child mental health'),
    ('Sukuta Dental & Maxillofacial Clinic', 'clinic', 'Sukuta', '+220 446 4471', 'Dental surgery, Orthodontics, Maxillofacial surgery, Dental X-ray'),
    ('Bakau Skin & Wound Clinic', 'clinic', 'Bakau', '+220 449 1186', 'Dermatology, Wound care, Burns dressing, Skin biopsy'),
    ('Abuko Endocrine & Diabetes Centre', 'clinic', 'Abuko', '+220 439 7740', 'Diabetes clinic, Thyroid clinic, Diabetic foot care, Dietetics'),
    ('Lamin Infectious Disease & TB Clinic', 'clinic', 'Lamin', '+220 445 3307', 'TB treatment, HIV care, GeneXpert, Hepatitis clinic'),
    ('Brikama Imaging Centre', 'diagnostic', 'Brikama', '+220 448 6650', 'CT, X-ray, Ultrasound, DEXA bone scan, Echocardiography'),
    ('Gunjur Prosthetics & Rehabilitation', 'rehab', 'Gunjur', '+220 448 9921', 'Prosthetics, Orthotics, Physiotherapy, Wheelchair fitting'),
    # regional referral hospitals up-country
    ('North Bank Regional Hospital', 'hospital', 'Farafenni', '+220 573 5010', 'ICU, General surgery, Maternity theatre, X-ray, Ultrasound, Blood bank'),
    ('Central River Referral Hospital', 'hospital', 'Bansang', '+220 567 4120', 'Paediatric ward, TB unit, General surgery, X-ray, Laboratory'),
    ('Upper River District Hospital', 'hospital', 'Basse', '+220 566 8030', 'Maternity, General surgery, Ultrasound, Laboratory, Blood bank'),
    ('Lower River Health Centre', 'hospital', 'Soma', '+220 553 2250', 'Maternity, Minor theatre, Ultrasound, Laboratory'),
    ('Kerewan Community Maternity', 'maternity', 'Kerewan', '+220 572 1144', 'Midwife-led births, Antenatal clinic, Ultrasound, Family planning'),
]

# facility, name, title, speciality, rating, reviews, telehealth, consult fee (dalasi), bio
SPECIALISTS = [
    # heart, brain, surgery (shared with the demo seed)
    ('Kotu Heart Centre', 'Aminata Bojang', 'Dr', 'Interventional cardiology', 4.9, 142, True, 1000, 'Coronary angiography and stenting; 15 years in acute coronary care.'),
    ('Kotu Heart Centre', 'Pa Modou Saine', 'Dr', 'Cardiology', 4.6, 88, True, 750, 'Heart failure and echocardiography.'),
    ('Kotu Heart Centre', 'Fatoumata Kinteh', 'Dr', 'Cardiothoracic surgery', 4.7, 41, False, 1000, 'Valve and bypass surgery.'),
    ('Kotu Heart Centre', 'Rohey Faal', 'Dr', 'Paediatric cardiology', 4.8, 37, True, 900, 'Congenital heart disease and rheumatic heart disease in children.'),
    ('Banjul Regional Teaching Hospital', 'Lamin Jatta', 'Dr', 'Nephrology', 4.5, 63, True, 750, 'Acute kidney injury and dialysis.'),
    ('Banjul Regional Teaching Hospital', 'Ndey Secka', 'Dr', 'Neurology', 4.4, 57, True, 750, 'Stroke and epilepsy.'),
    ('Banjul Regional Teaching Hospital', 'Ousman Fofana', 'Dr', 'Neurosurgery', 4.2, 22, False, 1000, 'Head and spine trauma.'),
    ('Banjul Regional Teaching Hospital', 'Haddy Nyang', 'Dr', 'General surgery', 4.3, 104, False, 500, 'Abdominal and emergency surgery.'),
    ('Banjul Regional Teaching Hospital', 'Momodou Colley', 'Dr', 'Endocrinology', 4.8, 76, True, 750, 'Diabetes and thyroid disease.'),
    ('Banjul Regional Teaching Hospital', 'Awa Ceesay', 'Dr', 'Ophthalmology', 3.9, 12, False, 500, 'Cataract and glaucoma.'),
    ('Banjul Regional Teaching Hospital', 'Sheriff Saidy', 'Dr', 'Pulmonology', 4.5, 49, True, 750, 'Asthma, COPD and post-TB lung disease; runs the chest clinic.'),
    ('Banjul Regional Teaching Hospital', 'Binta Jammeh', 'Dr', 'Paediatric surgery', 4.6, 31, False, 750, 'Hernias, congenital anomalies and childhood trauma.'),
    # bones and joints
    ('Riverside Orthopaedic & Spine Clinic', 'Kebba Ceesay', 'Dr', 'Orthopaedics', 4.6, 95, False, 750, 'Fractures and joint replacement.'),
    ('Riverside Orthopaedic & Spine Clinic', 'Isatou Mbye', 'Dr', 'Spine surgery', 4.1, 18, False, 1000, 'Degenerative spine disease.'),
    ('Riverside Orthopaedic & Spine Clinic', 'Alieu Badjie', 'Dr', 'Rheumatology', 4.7, 58, True, 750, 'Rheumatoid arthritis, gout and lupus; joint injections.'),
    ('Riverside Orthopaedic & Spine Clinic', 'Jainaba Gaye', 'Dr', 'Sports medicine', 4.4, 26, True, 500, 'Ligament injuries and return-to-play programmes.'),
    # imaging
    ('Atlantic Diagnostics', 'Yusupha Darboe', 'Dr', 'Radiology', 4.5, 120, True, 0, 'MRI and CT reporting.'),
    ('Atlantic Diagnostics', 'Sainabou Touray', 'Dr', 'Breast imaging', 4.7, 34, False, 500, 'Mammography and breast ultrasound.'),
    ('Brikama Imaging Centre', 'Omar Sonko', 'Dr', 'Radiology', 4.3, 44, True, 0, 'Ultrasound, CT and DEXA bone density reporting.'),
    ('Brikama Imaging Centre', 'Adama Touray', 'Ms', 'Sonography', 4.6, 81, False, 300, 'Obstetric and abdominal ultrasound.'),
    # mothers and children
    ('Brikama Mother & Child Centre', 'Mariama Drammeh', 'Dr', 'Obstetrics & gynaecology', 4.8, 160, False, 750, 'High-risk pregnancy.'),
    ('Brikama Mother & Child Centre', 'Bakary Sanneh', 'Dr', 'Neonatology', 4.6, 49, False, 750, 'Newborn intensive care.'),
    ('Brikama Mother & Child Centre', 'Kaddy Jallow', 'Dr', 'Paediatrics', 4.4, 71, True, 500, 'General paediatrics.'),
    ('Kerewan Community Maternity', 'Fatou Bittaye', 'Ms', 'Midwifery', 4.7, 92, False, 0, 'Senior midwife; antenatal care and normal births.'),
    ('Kerewan Community Maternity', 'Sona Jobarteh', 'Ms', 'Family planning', 4.5, 40, True, 0, 'Contraception counselling and implants.'),
    # rehabilitation
    ('Serene Rehabilitation Centre', 'Ebrima Sowe', 'Mr', 'Physiotherapy', 4.3, 39, True, 400, 'Post-surgical and stroke rehabilitation.'),
    ('Serene Rehabilitation Centre', 'Neneh Cham', 'Ms', 'Speech therapy', 4.6, 23, True, 400, 'Speech and swallowing after stroke; children with speech delay.'),
    ('Gunjur Prosthetics & Rehabilitation', 'Musa Kujabi', 'Mr', 'Prosthetics & orthotics', 4.5, 29, False, 500, 'Lower-limb prostheses and diabetic foot orthoses.'),
    ('Gunjur Prosthetics & Rehabilitation', 'Ramatoulie Njie', 'Ms', 'Occupational therapy', 4.4, 17, True, 400, 'Daily-living skills and home adaptations.'),
    # stomach, liver and gut
    ('Westfield Gastro & Liver Clinic', 'Modou Lamin Sarr', 'Dr', 'Gastroenterology', 4.8, 113, True, 900, 'Upper GI endoscopy, ulcer bleeding and H. pylori.'),
    ('Westfield Gastro & Liver Clinic', 'Oumie Ceesay', 'Dr', 'Hepatology', 4.6, 54, True, 900, 'Hepatitis B treatment and liver cirrhosis.'),
    ('Westfield Gastro & Liver Clinic', 'Saikou Drammeh', 'Dr', 'Colorectal surgery', 4.4, 27, False, 1000, 'Colonoscopy, haemorrhoids and bowel cancer surgery.'),
    ('Westfield Gastro & Liver Clinic', 'Haddy Jobe', 'Ms', 'Dietetics', 4.5, 46, True, 300, 'Nutrition for diabetes, kidney disease and malnutrition.'),
    # kidneys and bladder
    ('Latrikunda Kidney & Urology Centre', 'Abdoulie Touray', 'Dr', 'Urology', 4.6, 67, False, 900, 'Prostate disease, kidney stones and cystoscopy.'),
    ('Latrikunda Kidney & Urology Centre', 'Mariama Jallow', 'Dr', 'Nephrology', 4.7, 51, True, 750, 'Chronic kidney disease and haemodialysis.'),
    ('Latrikunda Kidney & Urology Centre', 'Lamin Manneh', 'Dr', 'Paediatric urology', 4.3, 14, False, 750, 'Urinary problems in children.'),
    # blood and cancer
    ('Kololi Oncology & Haematology Unit', 'Isatou Sanyang', 'Dr', 'Haematology', 4.8, 62, True, 900, 'Sickle cell disease, anaemia and bleeding disorders.'),
    ('Kololi Oncology & Haematology Unit', 'Ebrima Camara', 'Dr', 'Medical oncology', 4.5, 38, True, 1000, 'Breast, cervical and prostate cancer treatment.'),
    ('Kololi Oncology & Haematology Unit', 'Awa Marong', 'Dr', 'Palliative care', 4.9, 44, True, 500, 'Pain and symptom control; home-care support.'),
    # eyes, ears, skin, teeth
    ('Fajara Eye & ENT Clinic', 'Yankuba Sillah', 'Dr', 'Ophthalmology', 4.7, 98, False, 750, 'Cataract surgery and diabetic eye screening.'),
    ('Fajara Eye & ENT Clinic', 'Kumba Fatty', 'Dr', 'ENT surgery', 4.5, 43, False, 750, 'Tonsils, sinuses and chronic ear infection.'),
    ('Fajara Eye & ENT Clinic', 'Pa Alieu Joof', 'Mr', 'Audiology', 4.4, 21, True, 400, 'Hearing tests and hearing-aid fitting.'),
    ('Bakau Skin & Wound Clinic', 'Fatoumatta Sowe', 'Dr', 'Dermatology', 4.6, 76, True, 750, 'Eczema, fungal infection and skin biopsy.'),
    ('Bakau Skin & Wound Clinic', 'Bubacarr Jawara', 'Mr', 'Wound care nursing', 4.5, 33, False, 300, 'Diabetic ulcers and burns dressings.'),
    ('Sukuta Dental & Maxillofacial Clinic', 'Nyima Ceesay', 'Dr', 'Dentistry', 4.4, 88, False, 500, 'Fillings, extractions and root canals.'),
    ('Sukuta Dental & Maxillofacial Clinic', 'Alagie Bah', 'Dr', 'Maxillofacial surgery', 4.6, 19, False, 1000, 'Jaw fractures, facial infections and oral tumours.'),
    # mind
    ('Brusubi Mind & Wellbeing Centre', 'Ndey Isatou Njie', 'Dr', 'Psychiatry', 4.7, 52, True, 750, 'Depression, psychosis and bipolar disorder.'),
    ('Brusubi Mind & Wellbeing Centre', 'Momodou Sabally', 'Mr', 'Clinical psychology', 4.6, 35, True, 500, 'Talking therapies for anxiety and trauma.'),
    ('Brusubi Mind & Wellbeing Centre', 'Kaddijatou Bah', 'Dr', 'Child & adolescent psychiatry', 4.5, 16, True, 750, 'ADHD, autism and teenage mental health.'),
    # hormones and diabetes
    ('Abuko Endocrine & Diabetes Centre', 'Ousainou Jarju', 'Dr', 'Endocrinology', 4.7, 64, True, 750, 'Type 1 and type 2 diabetes, thyroid nodules.'),
    ('Abuko Endocrine & Diabetes Centre', 'Bintou Darboe', 'Ms', 'Diabetes education', 4.8, 71, True, 200, 'Insulin starts, glucose monitoring and foot care.'),
    # infection
    ('Lamin Infectious Disease & TB Clinic', 'Sulayman Jabbi', 'Dr', 'Infectious diseases', 4.6, 58, True, 500, 'HIV, drug-resistant TB and hepatitis.'),
    ('Lamin Infectious Disease & TB Clinic', 'Aji Fatou Secka', 'Ms', 'TB programme nursing', 4.7, 47, True, 0, 'Treatment support and contact tracing.'),
    # regional hospitals
    ('North Bank Regional Hospital', 'Kebba Fatty', 'Dr', 'General surgery', 4.3, 39, False, 300, 'Emergency surgery and caesarean sections.'),
    ('North Bank Regional Hospital', 'Amie Touray', 'Dr', 'Internal medicine', 4.4, 45, True, 300, 'Hypertension, diabetes and severe malaria.'),
    ('Central River Referral Hospital', 'Lamin Krubally', 'Dr', 'Paediatrics', 4.6, 61, True, 300, 'Severe malaria and malnutrition in children.'),
    ('Central River Referral Hospital', 'Mai Sanneh', 'Dr', 'Internal medicine', 4.2, 28, True, 300, 'TB and HIV co-infection.'),
    ('Upper River District Hospital', 'Yaya Bah', 'Dr', 'Obstetrics & gynaecology', 4.4, 36, False, 300, 'Emergency obstetric care.'),
    ('Upper River District Hospital', 'Fanta Suso', 'Ms', 'Midwifery', 4.6, 55, False, 0, 'Antenatal and postnatal care.'),
    ('Lower River Health Centre', 'Ebou Jallow', 'Dr', 'Family medicine', 4.3, 24, True, 200, 'General clinics and referral triage.'),
]

VIDEO_SHARE = .3          # share of telehealth slots offered as video calls
TIMES = [8.5, 9, 9.5, 10, 10.5, 11, 11.5, 14, 14.5, 15, 15.5, 16]


class Command(BaseCommand):
    help = 'Add sample referral facilities, specialists and appointment slots (fictional; safe to rerun).'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=21, help='How many days ahead to offer appointment slots (default 21)')
        parser.add_argument('--slots-only', action='store_true', help='Only top up future slots for every active specialist')
        parser.add_argument('--remove', action='store_true', help='Remove the sample facilities (those with referrals are set to not accepting)')
        parser.add_argument('--force', action='store_true', help='Allow when DEBUG is False (the entries are fictional samples)')

    def handle(self, *args, days=21, slots_only=False, remove=False, force=False, **kw):
        if not settings.DEBUG and not force:
            raise CommandError('DEBUG is False. These are FICTIONAL sample facilities and specialists; '
                               'run again with --force if you want them on this server (remove later with --remove --force).')
        from hospital.management.dbcheck import require_up_to_date_database
        require_up_to_date_database()
        from hospital.models import NetworkFacility, Specialist
        if remove:
            return self.remove(NetworkFacility)
        days = max(1, min(days, 90))
        with transaction.atomic():
            made_f = made_s = 0
            if not slots_only:
                fac = {}
                for name, kind, town, phone, caps in FACILITIES:
                    slug = name.lower().replace('&', '').split()[0]
                    fac[name], created = NetworkFacility.objects.get_or_create(name=name, defaults={
                        'kind': kind, 'location': town, 'phone': phone, 'capabilities': caps, 'accepts_referrals': True,
                        'email': f'{slug}@{SAMPLE_DOMAIN}'})
                    made_f += created
                for fname, name, title, spec, rating, reviews, tele, fee, bio in SPECIALISTS:
                    _, created = Specialist.objects.get_or_create(facility=fac[fname], name=name, defaults={
                        'title': title, 'speciality': spec, 'rating': rating, 'reviews': reviews, 'telehealth': tele,
                        'consult_fee': fee, 'bio': bio, 'languages': LANG, 'active': True})
                    made_s += created
            slots = self.top_up_slots(Specialist.objects.filter(active=True), days)
        self.stdout.write(self.style.SUCCESS(f'Referral network: {made_f} facilities and {made_s} specialists added, {slots} appointment slots added '
                                             f'(next {days} days). Existing entries were kept.'))
        if not slots_only:
            self.stdout.write('All sample names, phone numbers and emails are fictional. Edit them under Configuration → Network facilities.')

    def top_up_slots(self, specialists, days):
        """Add weekday slots that don't exist yet. A seeded random per specialist keeps reruns stable, so nothing doubles up."""
        from hospital.models import SpecialistSlot
        now = timezone.now()
        day0 = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
        added = 0
        for sp in specialists:
            have = set(sp.slots.filter(start__gte=now).values_list('start', flat=True))
            new = []
            for d in range(1, days + 1):
                day = day0 + timedelta(days=d)
                rng = random.Random(f'{sp.pk}-{day:%Y%m%d}')
                if day.weekday() >= 5 or rng.random() < .2:       # weekends off, and the odd day of leave or theatre
                    continue
                for h in sorted(rng.sample(TIMES, rng.randint(3, 7))):
                    start = day + timedelta(hours=h)
                    if start in have:
                        continue
                    mode = 'video' if sp.telehealth and rng.random() < VIDEO_SHARE else 'in_person'
                    new.append(SpecialistSlot(specialist=sp, start=start, minutes=30, mode=mode))
            SpecialistSlot.objects.bulk_create(new, ignore_conflicts=True)
            added += len(new)
        return added

    def remove(self, NetworkFacility):
        sample = NetworkFacility.objects.filter(email__endswith='@' + SAMPLE_DOMAIN)
        kept_ids = list(sample.filter(referrals__isnull=False).values_list('pk', flat=True).distinct())
        n_kept = NetworkFacility.objects.filter(pk__in=kept_ids).update(accepts_referrals=False)
        deleted = sample.exclude(pk__in=kept_ids)
        n_del = deleted.count()
        deleted.delete()   # specialists and their slots go with the facility
        self.stdout.write(self.style.SUCCESS(f'Removed {n_del} sample facilities with their specialists. '
                                             f'{n_kept} with existing referrals were kept but set to not accepting referrals.'))
