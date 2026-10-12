# E-MedFlow HMS — Django / Bootstrap / PostgreSQL / Redis / Docker

An extendable **hospital-management MVP / developer starter**, not a certified electronic health record, medical device, or production-ready clinical decision support system. Treat all data as sensitive; do not process real patient information until a qualified security, privacy, and clinical team signs off.

## Quick start with Docker

```bash
docker compose up -d --build
docker compose ps          # db, redis, web and worker should all be running
docker compose logs -f web # wait for "E-MedFlow is starting at http://localhost:8000"
```

Open http://localhost:8000 and sign in as `admin` / `medflow-admin-2026`. No `.env` file is needed.

| Service | What it is | Reach it from your machine |
| --- | --- | --- |
| `db` | PostgreSQL 16 (database `medflow`, user `medflow`, password `medflow-dev-password`) | `localhost:5433` |
| `redis` | Redis 7, message broker for background jobs | internal only |
| `web` | E-MedFlow (Django dev server, auto-reloads when you edit code) | http://localhost:8000 |
| `worker` | Celery worker for background jobs | internal only |

On first start `web` applies migrations, loads the standard configuration and lab catalogue, adds fictional demo data
and creates the admin account. Restarts keep your data and skip the demo seed. Demo staff accounts use the password
`medflow-demo-2026` (`dr.jallow`, `nurse.bah`, `lab.touray`, `pharm.njie`, …).

| Task | Command |
| --- | --- |
| Follow logs of everything | `docker compose logs -f` |
| Run tests | `docker compose exec web python manage.py test hospital` |
| Database shell | `docker compose exec db psql -U medflow` |
| Django shell | `docker compose exec web python manage.py shell` |
| Stop | `docker compose down` |
| Reset to fresh demo data (deletes the database) | `docker compose down -v` then `up -d --build` |

These credentials are for local use only. For real patients use the production stack below.

### Troubleshooting Docker

| Message | Cause and fix |
| --- | --- |
| `failed to resolve host 'db'` / `Could not reach the database at db:5432` | The `db` container is not running, or this container is not part of the compose stack. Run `docker compose ps -a` and `docker compose logs db`. Start everything with `docker compose up -d`, and run commands with `docker compose exec web python manage.py …`. In PyCharm use a **Docker Compose** interpreter with service `web`, not a plain Docker interpreter. |
| `Bind for 127.0.0.1:8000 failed: port is already allocated` | Another program (often a PyCharm run configuration) or an older E-MedFlow stack uses port 8000. Stop it, or start with `$env:MEDFLOW_PORT=8080; docker compose up -d`. |
| Running Django directly in PyCharm against the Docker database | Set `POSTGRES_HOST=localhost`, `POSTGRES_PORT=5433`, `POSTGRES_PASSWORD=medflow-dev-password`, `DJANGO_DEBUG=True`. Or use `USE_SQLITE=True` for a local file database. |

| Buttons do nothing, the side panel shows at the bottom of the page, or animations are missing after an update | The browser is using old CSS/JavaScript from its cache. From this version every CSS/JS link carries a content fingerprint, so this cannot recur; press **Ctrl+F5** once after installing it. |

After a reboot or a Docker Desktop restart, `web` and `worker` wait up to 90 seconds for the database instead of crashing.

## Quick start (local, no Docker)

```bash
pip install -r requirements.txt
export USE_SQLITE=True DJANGO_DEBUG=True
python manage.py migrate
python manage.py seed_demo            # FICTIONAL demo data; refuses to run when DEBUG=False
python manage.py createsuperuser
python manage.py runserver
```

Open http://localhost:8000. Demo staff accounts (password `medflow-demo-2026`): `dr.jallow`, `dr.ceesay`,
`nurse.bah`, `reception.sowe`, `lab.touray`, `pharm.njie`, `manager.camara`. Change or delete them before any real use.

## Docker / production

```bash
cp .env.example .env
# Set strong DJANGO_SECRET_KEY and POSTGRES_PASSWORD in .env.
docker compose -f compose.prod.yml up -d --build
docker compose -f compose.prod.yml exec web python manage.py createsuperuser
```

Boot runs committed migrations, `collectstatic` and the idempotent `bootstrap_hospital` seed (departments, lab
catalog, 4 wards / 26 beds, medication catalog; no patients). All CSS, icons and fonts are self-hosted under
`hospital/static/hospital/vendor/`, so the app works on an intranet with no internet access. Put it behind HTTPS and
set `SECURE_SSL_REDIRECT=True` and `SECURE_HSTS_SECONDS` when the deployment is permanently on HTTPS.

After creating staff users, add a **Staff profile** in `/admin/` with a role (doctor, nurse, reception, lab,
pharmacy, finance, management, admin). Superusers may access everything; other accounts need an active profile.

## Interface

- **Overview** — a live “hospital pulse” ECG trace whose rate rises with waiting-room load (calm / busy / surging),
  a six-stage patient-flow strip, weekly arrivals, occupancy, department load, urgent patients, low stock, audit feed.
  Refreshes every 15 s via `/api/pulse/`.
- **Queue** — drag-and-drop board (waiting → called → in consultation), triage colour stripes, live wait times,
  “calling to Room N”. Invalid transitions are rejected server-side.
- **Waiting-room display** (`/queue/display/`) — full-screen TV board with flip animation and optional chime.
  Shows ticket codes only (e.g. `EM004`), never patient names.
- **Patient chart** — wristband header, persistent allergy strip, merged timeline, latest vitals, forms and e-sign.
- **Laboratory** — collect → process → result → verify pipeline. **Pharmacy** — draft → signed → dispensed lanes,
  stock meters, live allergy/stock check while prescribing. **Beds** — ward floor map with discharge → cleaning → ready.
- **Referrals** — progress tracker with enforced transitions. **Attendance** — clock in/out with shift ring.
- **Forms & approvals** — form designer (24 field types, pages, rules, formulas, live preview, undo/redo), flow designer
  with a simulator, a task inbox with deadlines, and an animated map of where each request is.
- **E-sign** — DocuSign-style envelopes: place fields on any PDF, signing order, links for outside signers with access
  codes, patients signing in person with a witness, a sealed PDF with a certificate page, and a public verify page.
- **Bedside and injuries** — an animated bed scene and an injury & burns body map, both drawn from the values entered.
- **Search** — press `Ctrl K` (or `/`) anywhere to find a patient by name, MRN or phone, or jump to a page. Phone
  numbers work however they are typed (`+220 341 5919`, `3415919`, `341-5919`, `00220…`, or just the last 4 digits) and
  also find patients whose emergency contact has that number.

Animations honour the operating system “reduce motion” setting.

## Laboratory

- **Standard catalogue:** 8 categories, 27 tests and 66 measured parameters (CBC, renal and liver panels, troponin,
  lipids, thyroid, urinalysis, blood gas, CSF, serology and more). Each parameter has a unit, reference range, optional
  female range, critical limits and the body system it belongs to. Add or edit categories and tests (with all their
  parameters on one screen) under Configuration → Lab tests. Restarts add missing standard tests but never overwrite
  your edits. **The ranges are illustrative adult values; validate them for your analysers before clinical use.**
- **Lab requests:** tests ordered together for a patient form **one request** (one card on the lab board, one specimen
  collection, one results sheet, one verification). Set a priority (routine / urgent / STAT) and clinical notes. A single
  test can still be cancelled on its own, and tests that take longer can be submitted later without holding up the rest.
- **Result entry:** one row per parameter, flagged high / low / critical as the technician types, with a critical-value
  call-back prompt. Submission requires every value; drafts can be saved. Each technician has a **My work** list.
- **Lab insights** (patient chart → Lab insights): two views, remembered per clinician.
  *Body map* — an animated figure; organs with results get a marker (red = out of range, pulsing faster when
  critical; teal = in range). Blood droplets flow through the vessels and turn red when blood results are abnormal.
  Click a marker to zoom into the organ and open its values, range bars and trends. *Charts & lists* — summary
  figures, trend charts with shaded reference bands, and every result.
  Out-of-range results must be **marked reviewed**; a progress ring tracks this and the dashboard lists unreviewed
  critical results.

Demo: sign in as `dr.jallow` and open patient **Babucarr Sowe** → Lab insights (an evolving cardiac emergency with
rising troponin and critical potassium).

## Prescriptions

A prescription holds as many medicines as needed. Each line records the medicine, strength, units per dose, route,
how often (once, twice, three or four times daily, every 4/6/8/12 hours, morning, night, weekly, once now, when
required), the number of days and instructions. The total quantity is calculated automatically (1 tablet × three
times daily × 5 days = 15) and can be overridden; "when required" medicines need a quantity entered. Every line gets
its own allergy and stock check. The prescriber signs once; the pharmacy dispenses every line together, drawing the
earliest-expiring stock first, and nothing is dispensed if any line is short.

Port 8000 already in use? Start with `MEDFLOW_PORT=8080 docker compose up -d` (PowerShell: `$env:MEDFLOW_PORT=8080; docker compose up -d`).

## Laboratory management

The **Laboratory** pages share a bar: Work board, **Command centre**, **Specimens**, **Quality control**,
**Analysers**, **Reagents**, **Critical calls** and the test catalogue.
- **Command centre**: samples received, STAT tests open, median turnaround and % within each test's target,
  rejection rate, a work-in-progress pipeline, results per hour, overdue tests, turnaround by section, analyser status
  with today's QC light, reagent alerts and critical calls still to make. Refreshes every minute.
- **Specimens**: scan or type the specimen or LR number to receive a sample; reject with a reason (haemolysed,
  clotted, insufficient, mislabelled…). Rejection sends the tests back for recollection and notifies the requester.
  Print a 50 × 25 mm specimen label with a QR code.
- **Quality control**: Levey-Jennings charts per control material, with Westgard rules (1-2s warns; 1-3s, 2-2s, R-4s,
  4-1s and 10x reject). A rejected run puts the analyser on **QC hold** until a control passes.
- **Analysers** (status, maintenance and fault log) and **Reagents** (lots, expiry, stock, reorder levels).
- **Critical values**: submitting a critical result alerts the requesting clinician (bell and email) and creates a
  call-back task; the call is recorded with who was told and a read-back confirmation.
- The result sheet shows each patient's **previous value** and flags large changes (delta check). Every request has a
  printable **lab report** with reference ranges, flags, verification and a QR code.
- Blood-disease tests: sickling screen, haemoglobin electrophoresis (HbA/S/F/A2 and genotype), reticulocytes,
  ferritin, blood film, G6PD and clotting profile.

## Result guidance: hospital and WHO ranges, sources and AI

When results are reported, the lab request page (and *Lab insights* → any result → **WHO range, sources & AI**) shows a
**Result guidance** panel for doctors, nurses and lab staff. For each abnormal result:

- **Hospital range and WHO reference side by side**, chosen for the patient's group: age, sex, pregnancy and trimester
  (read from the record, e.g. "Pregnancy 20 weeks", or a positive pregnancy test), infection/inflammation (raised CRP or
  white cells) and malaria. WHO severity bands are shown (e.g. *moderate anaemia*), and a note appears when the hospital
  range and WHO disagree. The WHO column also appears in the results table and on the printed report.
- **Next steps**: your hospital protocol first (Admin → Parameter guidance), then the built-in general guidance.
- **What clinicians here did next** after the same kind of result: tests ordered and medicines prescribed within 7 days
  and how those visits ended. Anonymous; groups under 3 patients are hidden. Observational, not evidence.
- **Trusted medical sources**, fetched in the background when the lab submits an abnormal result and cached:
  WHO fact sheets, MedlinePlus (US National Library of Medicine) and recent PubMed guidelines and systematic reviews.
  MedlinePlus and PubMed are read through their official APIs; WHO pages only where robots.txt allows. Only the test
  name and whether it is high or low are sent, never patient data. *Refresh sources* fetches again.
- **AI suggestion** (off by default): *Ask AI for next steps* sends the de-identified visit, these results with both
  ranges, the local-practice counts and the cached sources to Claude (or your own endpoint). The AI may search the web,
  but only on `MEDICAL_TRUSTED_DOMAINS`, and the answer lists every source and search. Answers are kept for audit with
  a SHA-256 of what was sent; *What AI would see* shows it exactly. Doctors can rate answers.

**WHO references** (Laboratory → WHO references). WHO publishes reference values for only a few tests; E-MedFlow
ships haemoglobin anaemia cut-offs (WHO 2024, by age, sex and trimester), ferritin (WHO 2020, with and without
inflammation), fasting glucose and HbA1c diabetes criteria (WHO 2006/2011) and the WHO severe-malaria criteria. They
are marked *not yet lab-verified* until the laboratory verifies them. The laboratory can add other guideline values,
retire values, and a weekly job re-reads the cited WHO pages and puts a reference on *review* when its page changes.
Values are stored in the catalogue's units; a reference in a different unit is shown but never used to classify.
The hospital range still decides every flag.

Settings (`.env`):

| Setting | Default | Purpose |
| --- | --- | --- |
| `MEDICAL_EVIDENCE_FETCH` | `True` (off in tests) | Fetch summaries from trusted sources in the background |
| `MEDICAL_TRUSTED_DOMAINS` | who.int, nih.gov, medlineplus.gov, cdc.gov, nice.org.uk, msf.org, cochranelibrary.com, bmj.com, thelancet.com, nejm.org | Only these sites are fetched or searched |
| `MEDICAL_EVIDENCE_MAX_AGE_DAYS` | `30` | Cached sources older than this are refreshed (weekly job) |
| `NCBI_EMAIL`, `NCBI_API_KEY` | blank | Contact email NCBI asks for; optional key for a higher PubMed rate |
| `CLINICAL_AI_ENABLED` | `False` | Turn AI on |
| `ANTHROPIC_API_KEY`, `CLINICAL_AI_MODEL` | blank, `claude-sonnet-5-5` | Claude API |
| `CLINICAL_AI_WEB_SEARCH` | `True` | Let the AI search trusted sites (set `False` on an offline intranet) |
| `CLINICAL_AI_PROVIDER`, `CLINICAL_AI_ENDPOINT`, `CLINICAL_AI_TOKEN` | | `endpoint` sends `{task, context, instructions}` to your service, which returns `{"text", "sources"}` |

The Celery worker runs with `-B` so the weekly jobs (refresh stale sources, re-check WHO pages) run on schedule.
Without a running worker, *Refresh sources* and *Ask AI* still work; they run in the web process instead.

## Find patients

**Find patients** (menu, or Ctrl+K from anywhere) searches the whole record with one box: name, patient number,
phone, diagnosis, long-term condition, allergy, medicine, lab test, scan finding or town. Every word must match, so
`malaria brikama`, `femoral fracture` or `ebrima touray` narrow the list. Scan findings only match when positive
("no fracture" does not match `fracture`). Each result shows why it matched, the bed or queue number, the latest
diagnosis with its category, allergies and unreviewed abnormal results, with buttons for the record, results,
prescribing and history.

Narrow further with one click:
- **Disease categories** (filed automatically from every diagnosis and condition, loosely following ICD-10
  chapters): Infections & tropical, Bones joints & spine, Injuries & trauma, Brain & nerves, Heart & circulation,
  Lungs & breathing, Kidney & urinary, Stomach liver & gut, Diabetes thyroid & metabolism, Blood & anaemia,
  Pregnancy & women's health, Mental health, Skin, Eyes ears nose & throat, Cancer. Keywords live in
  `hospital/categories.py`.
- **Situations**: admitted now, in the queue, open visit, unreviewed abnormal results, has allergies, my patients.
- **Department, age group, sex, town, seen within, sort.** Every search is a link you can bookmark or share.

## Working from the patient page

On a patient's page, **Order lab tests**, **Prescribe**, **Imaging**, allergies, conditions, referrals and admissions
open in a slide-out panel. Save, and the panel closes and the page refreshes where you were. Every lab request,
prescription and imaging study opens its own detail page.

**Out-of-stock medicines** (prescription detail page): *Order from supplier* raises a supplier order (Pharmacy →
Supplier orders); the line is dispensed once the stock is received, and the rest of the prescription can be dispensed
meanwhile (*partly dispensed*). *Not available · inform patient* records what the patient was told, skips the line
when dispensing and prints a note for the patient.

## Imaging

X-ray, CT, MRI, ultrasound, ECG, echo, mammogram and fluoroscopy requests, with a worklist for the `radiology` role.
Upload JPG/PNG/WEBP images (each is checked to be a real image; export DICOM to JPG/PNG first), view them with zoom,
pan, brightness, contrast and invert, and write a report with measurements. Images are served only to signed-in staff.
Reported studies appear on the body map (camera badge) and under *Charts & lists*. Demo images are synthetic
illustrations, labelled as such.

## Organ illustrations and similar cases

In *Lab insights*, opening an organ shows an animated illustration shaped by the patient's results, for example red
cells drawn from haemoglobin, an irregular heartbeat when potassium is high, or slowed kidney filtering when creatinine
is raised. Tap a part to learn what it does. These are teaching visuals, not diagnostic images.

*What worked for similar cases* (patient and visit pages) compares completed visits with a similar diagnosis by the
medicines prescribed and their recorded outcome. Other patients are anonymous (sex and age band only, no names,
numbers or real dates), and any treatment group with fewer than 3 patients is hidden. The patient's own past visits
are shown as *This patient* and link to the visit. This is observational data, not evidence. Record an outcome when
completing a visit so the comparisons stay meaningful.

## Referral and specialist network

**Specialist network** lists partner hospitals, clinics and diagnostic centres and their specialists. Start from
*Top rated* or search the full list by name, speciality or facility, and sort by rating or soonest availability.
A specialist's page shows two weeks of slots; click a free slot to open the referral with that slot held for the
patient (a slot can only be booked once, and it is released if the referral is declined or cancelled). Add
facilities, specialists and slots under Configuration.

Before a referral is sent to a network facility, the patient's **consent to share records** must be recorded. The
receiving facility then sees a shared record (allergies, conditions, medicines, recent results and imaging reports);
every view is logged.

Each referral has **two-way preparation requests**: the receiving facility can ask the referring hospital for a test
(ordered with one click), a form or a document, and the referring hospital can ask the receiver to book theatre,
reserve a bed and so on. Operation referrals start with a pre-operation checklist (bloods, group and save, consent,
fasting, theatre, anaesthetic review) timed to the planned date.

**Partner facilities** sign in with the `partner` role linked to their facility (Configuration → Staff profiles).
They see only referrals sent to them, never drafts, and the patient record only with consent; nothing else in the
hospital is visible to them. Demo login: `partner.kotu`.

## Referral inbox, outbox and notifications

**Referrals** has two tabs. **Inbox**: referrals coming to you, with Accept / Decline (a reason is required) that
work in place; the inbox refreshes itself every 15 seconds and announces new referrals. **Outbox**: referrals you
sent. "You" depends on who signs in: hospital staff (inbox = referrals from network facilities), a partner facility
(inbox = referrals to it, outbox = referrals it sent to the hospital) or a specialist (requests to them).

**The bell** (top bar) shows notifications for new referrals, acceptance or decline, a record being shared,
preparation requests and closed cases, refreshed every 20 seconds. Staff with an email address also get them by
email (turn off in the bell). Emails contain only a title and a link, never patient details. Configure SMTP in `.env`
(`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`, `SITE_URL`); in
development emails are printed to the web log.

**Patient data on referrals.** Until the receiver accepts *and* the referring doctor presses **Send patient record**
(with the patient's consent), specialists and partner facilities see only the first name and initial, sex and age.
When the case is completed the record **locks** for the receiver; a de-identified version (no name, number, contact
or real dates) stays available under **Learning**.

## Specialist portal

Specialists sign in with the `specialist` role linked to their directory entry (demo: `dr.bojang`, `dr.kceesay`).
They set their **live status** (Available, Busy, In theatre, On call, Away, Off duty) with a note and where they are,
shown in the specialist directory; manage **appointment slots** (a weekly pattern for up to 12 weeks, remove free
slots; booked slots are never changed); handle **requests**; and see closed cases in **Learning**.

## Network record lookup

Partner facilities and specialists can look up a patient's shared record with the **patient number and date of
birth**, choosing a reason. A failed lookup never reveals whether a patient exists; lookups are rate-limited and
logged, and every lookup appears in **Network access** on the patient's record, where the patient's choice to opt
out of network sharing is also set. Partner facilities can refer a looked-up patient to the hospital.

## Beds

Click any bed on the bed board for its page: the current patient with length of stay, vitals, medicines and pending
tests, quick actions (prescribe, order tests, discharge), a ward strip to jump between beds, 30-day occupancy,
average stay, and everyone who has used the bed. Empty beds can be taken out of service with a reason.

## Finance

Prices live in one place: services (consultations, imaging, bed-days, procedures) under *Finance → Price list*,
lab tests and medicines on their own records. *Bill current visit* (patient page) or *Bill* (visit page) opens the
visit's bill and captures every charge: consultation, lab tests, imaging, medicines actually dispensed and bed-days.
Each charge is recorded with its source, so nothing is billed twice. Issue the bill, then take payments by cash,
Wave, Afrimoney, QMoney, card, bank transfer or insurance, including part-payments; mobile money and card need a
transaction reference. Insurance is a percentage split, with the patient's and insurer's balances tracked
separately. Discounts need a reason and finance staff; payments and bills are voided with a reason, never deleted.
The finance dashboard shows collections, payment methods, unpaid balances by age and revenue mix. Roles: `finance`
and `reception` take payments; only `finance` and admins give discounts or void.

## Decision support

While prescribing or ordering tests, a panel shows the patient's allergies, safety checks and suggestions:
allergies are matched by name and by drug class (a penicillin allergy flags amoxicillin; cephalosporins get a
cross-reaction caution); risky combinations with results or conditions (e.g. metformin with raised creatinine,
NSAIDs with kidney disease or hypertension); missing work-up (malaria without a test, chest pain without troponin);
and results that do not fit the diagnosis (negative malaria test, raised troponin without a cardiac diagnosis). The
visit page shows the same *Clinical safety review*. Suggestions show what colleagues here usually ordered or
prescribed for the same diagnosis and how those patients did, with one-click *Add* (needs 3+ past visits).

Click any trend chart or flagged result in *Lab insights* for its meaning, full trend, history, suggested next steps
and buttons to repeat the test or mark it reviewed. *Play history* on the patient page replays the whole record.

**AI.** Off by default. Set `CLINICAL_AI_ENABLED=True`, `CLINICAL_AI_ENDPOINT` and `CLINICAL_AI_TOKEN` to send a
de-identified context (no name, record number, phone, address, date of birth, real dates or free-text notes) from the
server to an approved service; *What AI would see* on the visit page shows exactly that payload. Without AI the
rule-based checks still run. All suggestions are advisory and need clinician review.

## Check-in, queue numbers and QR codes

**Check in** (menu) is for returning patients: type or scan their patient number (or search by name or phone),
confirm the person, choose the department and triage, and print the queue ticket. No re-registration. Queue numbers
(e.g. `OU001`) restart automatically every day, and *Restart numbers* on the Queue page restarts them on demand for
one department or all. Patients already waiting keep their numbers.

Every patient has a QR code (patient page → ⋯ → *Patient QR code & wristband*, the bed page, check-in and the queue
ticket). It contains only a link; opening it requires staff sign-in. Print it on a wristband or card.

**Queue tickets** print on a regular printer or on **thermal receipt printers (80 mm or 58 mm)**, and can be sent
to the patient by **WhatsApp** (to their phone number; local 7-digit numbers get +220) or **email** (add the
patient's email on their record), or the link copied. The message contains the queue number and a live status link
the patient can open on their phone without signing in: it shows only the number, department, people ahead and an
estimated wait, never their name or medical details, and it expires after 24 hours.

## At the bedside (bed page)

Below the patient's details is an animated picture of the patient in bed with everything attached to them. Each part
moves according to the values entered beside it, and the server checks and limits every value before saving:

- **IV**: drops fall in the drip chamber at exactly *rate × drop factor ÷ 60* per minute (125 mL/h with a 20 drops/mL set
  = 41.7 drops/min); the bag level is what is left and goes down in real time; time until empty is shown. On a pump the
  pump shows the rate. Blood and plasma show in their own colours.
- **Monitor**: the ECG and pulse-oximeter waves run at the recorded heart rate, the breathing trace and the chest at the
  breathing rate. Values that score 2 or 3 in NEWS2 turn amber or red and the monitor frame flashes. An optional beep
  sounds with each heartbeat on that screen only.
- **Oxygen**: the flowmeter float sits at the set flow, the humidifier bubbles faster with more flow, and the cannula or
  mask (with a reservoir bag that empties as the patient breathes in) is drawn on the face. Flow is limited to what each
  device allows, and the oxygen percentage is estimated.
- **Urinary catheter, NG tube, BP cuff, neck collar, leg traction, chest drain** (bubbling when there is an air leak),
  **head of bed angle** and **side rails**. Urine output below 0.5 mL/kg/h, a nearly empty bag, a full urine bag or a
  bubbling drain are flagged.
- The patient's colour changes with low oxygen, fever or cold; the wristband is red when allergies are recorded;
  dressings, a splint or a head bandage appear from the injury assessment.

Below the picture, **Record observations** saves heart rate, blood pressure, breathing, SpO₂, temperature and
alertness, scores NEWS2 and shows the expected response. Click any equipment on the picture to open its settings.
Nurses and doctors can change the equipment; others see it read-only.

## Injuries & burns

From a visit (or *More → Injuries & burns* on the patient page): a front and back body map. Click the body to add a
burn or an injury at that spot. The figure is drawn from what is entered:

- **Burns** in four depths (redness, blisters, deep partial, full thickness with charring), covering the entered share
  of each area, with a band for burns that go all the way round. The burned area uses the **Lund–Browder** chart for the
  patient's age (simple redness is not counted). With the weight entered it shows **Parkland** fluids: the 24-hour total,
  the first 8 hours and next 16 hours with rates, and, given the time of the burn and fluids already given, the rate
  needed now. *Set the IV to … mL/h* applies that rate to the bedside IV.
- **Spinal injury** by level (C1 to sacrum) and ASIA grade: a close-up of the spine with nerve signals that stop at the
  injury, or partly get through for incomplete injuries, and the parts of the body below the level shaded. Alerts follow
  the level (breathing, neurogenic shock when the latest blood pressure and pulse are both low, autonomic dysreflexia).
- **Head injury** by GCS and pupils; **fractures (open or closed), dislocations, cuts, grazes, bruises, penetrating
  wounds, crush injuries, amputations and sprains**, with bleeding that drips faster when it is active.

Each save keeps a new version. The numbers are standard starting estimates for documentation and teaching; they do not
replace local protocols or senior review.

## Medication chart (bed page)

For each inpatient, the bed page shows today's doses for every active medicine: given (who and when), due now,
late, not given (refused, held, missed or unavailable, with a reason) and still to come. Tap a dose to record it;
"when required" medicines have a *Give dose* button. Icons show how each medicine is given: tablet, capsule,
injection, infusion, syrup, sachet, cream, drops or inhaler.

## Health intelligence

An interactive dashboard for planning and public-health decisions: disease trends by week (click a diagnosis to
show or hide it, hover for numbers), outbreak signals (this week against the previous four), malaria test
positivity, age and sex of patients seen, where patients come from and their malaria share, outcomes by diagnosis,
antibiotic use, waiting times, admissions and chronic disease control, with plain-language advice generated from
the indicators. Anonymous counts and rates only; choose 30 days to 1 year.

**Real maps.** The health maps are real OpenStreetMap maps built with Folium (bubbles sized by patients, colour by
share, a popup with an *Explore* link, a heat-map layer and a scale bar). Leaflet is served by E-MedFlow itself; only the
map tiles need internet. Map tiles are requested with only the site's address as Referer, as OpenStreetMap's
tile policy requires; the layer box offers Esri street map (default), Esri satellite and OpenStreetMap, none needing a key. Set
`MAPTILER_KEY` (free key from maptiler.com) to make MapTiler the main map, or `MAP_TILE_URL` and
`MAP_TILE_ATTRIBUTION` for your own provider. **Locations** (Health intelligence → Locations) lists the towns and areas used for patient
addresses and maps; about 50 Gambian towns and areas are included. Add one by typing its name, choosing its region
(or the town it is an area of, e.g. Bundung or Westfield), and clicking its place on the map (or dragging the
marker). Patients choose their town or area from a grouped list; existing patients are linked automatically from the
town written at the end of their address.

**Explore** (button on the dashboard, or click a diagnosis, town or outbreak signal) drills into any group: filter
by diagnosis, town, age band and sex, and every chart recomputes — a map of The Gambia with a magnified Greater
Banjul inset (click a town), weekly trend against all visits, a calendar of daily visits, arrival times, outcomes,
treatments used with how often patients improved, tests ordered and malaria positivity. 

## Adding new demo content to an existing database

`docker compose exec web python manage.py seed_demo_extras` adds the newer fictional content (brain cases with
spinal-fluid results, CT, MRI and EEG; imaging for the featured patient; four months of visits for the health
dashboard; inpatient medication charts) without wiping your database. It only runs in demo mode (DEBUG on) and
does nothing the second time. It also adds eight bone, spine and injury cases (femur fracture after a road
accident, disc herniation, osteoporotic spine fracture, whiplash, a child's elbow fracture, spinal cord injury,
knee osteoarthritis, gout) and hand and foot cases (rheumatoid arthritis, boxer's fracture, ankle fracture,
diabetic foot infection) and pregnancy cases (28 weeks, 9 weeks, ectopic) and an enlarged prostate, with synthetic
X-rays, MRI and ultrasound, results, medicines, admissions and referrals.

## Modules included

- Patient MRN, demographics, longitudinal encounters, symptoms, assessments, diagnoses, vitals, conditions, allergies, medications, labs, admissions, referrals, structured forms and chart timeline.
- Multi-department queue tickets with triage priority, call/start/skip/requeue/complete transitions.
- Staff clock-in/out (does not implement shift scheduling, payroll or credential verification).
- Lab catalog and orders/results (verification workflow and reference ranges are placeholders pending validation).
- Medication catalog, expiry-aware stock batches, clinician-signed prescription and atomically dispensed stock movement.
- **Limited medication safety**: lists all documented active allergies; simple case-insensitive text match against a drug's listed name/generic name; blocks matches without override reason. It does NOT understand drug classes, equivalent names, true cross-reactivity, dosing, interactions, disease contraindications, pregnancy or kidney function. Every prescription requires clinician review. Not safe as sole alerting tool.
- Ward/bed availability, active admissions, discharge into 'cleaning' state.
- Referrals linked to clinical encounter, urgency, destination, contact and transfer status.
- Clinical forms with conditions and formulas, published versions, drafts and per-step fields; graph approval flows.
- E-sign envelopes with a SHA-256 hash-chained audit trail and sealed PDFs. This is an audited electronic signature
  workflow, **not** a qualified/PKI digital signature: identity rests on staff logins, private links with optional
  access codes, and the staff host's identity check for in-person signing. Check local law for which documents may be
  signed this way.
- Electronic attestations: user-bound, time-stamped record with SHA-256 content digest and HMAC based on application secret, plus audit record. This is **not** an independently verifiable cryptographic digital signature or legally validated qualified e-sign service; changing the server secret breaks independent reproducibility and the signature record itself should be in append-only storage. No identity re-verification, PDF signing or PKI is included.
- Audit events on major access/actions.

## Forms & approvals

**Form designer** (*Forms & approvals → New form*, admins and managers). Pick from 24 field types: text, numbers,
dates, choices, yes/no, 0–10 score, slider, table with repeating rows, signature, body map, vital signs with NEWS2,
Glasgow Coma Scale, patient details, headings and text, and **calculated** fields. Split long forms into pages. On the
right, each field has:

- *Logic*: show it only when, or make it required when, other answers match (is, contains, more than, between, one of,
  in the past, within N days …, combined with all/any; can compare two fields or a value inside vital signs).
- *Formula* for calculated fields, e.g. `round(bmi(weight, height), 1)` or
  `if(score >= 45, "High", "Low")`, with the result shown as you type. Functions: sum, avg, min, max, round, floor,
  ceil, abs, sqrt, if, coalesce, count, len, today, days_between, age, bmi, concat, upper, lower and `col(table, "column")`.
- *Fill in automatically* from the patient record (name, number, age, allergies …), optionally locked.
- *Filled in at*: a flow step id, so pharmacy, theatre or a second nurse completes their part later.

*Preview* runs the real form. Problems (duplicate keys, formulas that refer to missing fields, calculations that depend
on each other in a loop) are listed and block saving. Ctrl+Z / Ctrl+Shift+Z undo and redo, Ctrl+D duplicates, Ctrl+S
saves. Templates: procedure consent, burns assessment, falls risk (Morse), nursing admission. Changing a form that has
been used makes a new version; earlier answers keep the copy they were made with.

**Filling in** shows a page stepper and progress, checks answers as you go, saves a draft every few seconds (come back
later to the same form for the same patient), and the server repeats every check and recalculates every formula.

**Flow designer.** Drag steps onto the canvas and drag from a step's coloured exit to the next step:

| Step | What happens |
|---|---|
| Fill in | Someone completes the fields assigned to the step |
| Approval | First approval wins, everyone must approve, or *at least N* must approve; can send back for changes |
| Review | Read and acknowledge |
| Signature | The form is turned into a PDF and sent for e-signature (initiator, clinician, a role, the patient in person; as signer, witness or approver; in order) |
| Condition / Route | Yes/No, or several paths with their own rules and *Otherwise* |
| In parallel / Wait for all | Start branches together; continue when all have arrived |
| Notify | Bell and email, without waiting |
| Set a value | Write a calculated value into the answers |
| End | Completed, or rejected |

People can be a role, named staff, the person who started it, or the patient's clinician. Steps can have a deadline;
overdue steps alert the people again and, if set, another role. **Simulate** walks the flow with sample answers and
decisions and animates the path, using the same rule engine as the server. Flows cannot loop; use *send back for
changes* instead. Older flows saved as a list of `{"name", "role"}` steps still work as a chain of approvals.

**Tasks** lists everything waiting for you or your role, with deadlines. Each run has a page with an animated map of
where it is, who has acted, the history, and buttons for your step (approve, reject, send back, fill in, sign). The
person who started a flow can resubmit after changes, cancel it, or pass a step to someone else.

## E-sign

*E-sign → New envelope*: upload a PDF, choose a completed form (rendered as a PDF with signature boxes), or write a
letter here with patient details filled in (`{patient.name}`, `{patient.dob}` …). Add recipients with an order number
(same number = at the same time): staff, outside people by email (with an optional access code shared separately), a
patient or guardian **signing in person** on the device with a staff host, witnesses, approvers and copies. Then place
the fields (signature, initials, date, name, text, tick box, choose one) on the pages and send.

Signers get a guided screen: *Next* takes them field by field, they adopt a signature by drawing, typing (two
handwriting styles) or uploading, and can decline with a reason. You can require that every page is viewed first. For
in-person signing the host records how identity was confirmed. Every event is stored with the SHA-256 of the one
before; when everyone has signed, the signatures are stamped into the PDF and a certificate page is added. The
envelope page shows routing, signing links to share, reminders, cancel, and an integrity check. Anyone can check a
sealed PDF at `/esign/verify/` (no patient details are shown). Staff signatures are remembered for next time.

Run `python manage.py shell -c "from hospital import flows, esign; flows.sweep(); esign.sweep()"` from a scheduler to
send deadline alerts, reminders and expiries; they also run whenever the studio or e-sign page is opened.

## Before live deployment — REQUIRED engineering and governance

1. Implement granular patient/department/team access (current role checks are module-level), medical-record immutability/versioned amendments, and protected break-glass audited access. Add multi-facility tenant isolation if applicable.
2. Run full penetration testing, security review, clinical hazard analysis and staff training; create recovery and downtime procedures. Configure HTTPS, HSTS and proper proxy settings; CSRF/session hardening; encrypted backups, at-rest database encryption and confidential media, key rotation, least-privilege IAM, SSO/MFA, request throttling, central SIEM/append-only logs, retention and consent controls.
3. Add clinical terminologies and interoperability (FHIR R4/R5, HL7, ICD-10/11, LOINC, SNOMED CT, RxNorm depending on licenses/region); validated CDS drug formulary and interaction knowledge base; comprehensive structured vital measurement units; laboratory quality control and signed result-release gates.
4. Replace free-text clinical records and generic form JSON with controlled validated fields where necessary, enforce signature and approval policy, test concurrency, add tamper-evident long-lived signatures and patient identity verification.
5. Add invoicing/insurance, payments, scheduling/roster, specimen barcode scanning, imaging/PACS, consumables procurement, stock reconciliation, finance/revenue cycle, ambulance dispatch, referrals exchange, bedside MAR, discharge letters, patient portal, reporting and capacity forecasting.
6. Create AI integration as an **opt-in, disabled-by-default clinical decision-support adapter**. Enforce scoped clinician authorization, patient consent/legal grounds, minimum necessary disclosure, pseudonymization where possible, vendor contracts and residency policy; treat output as drafts requiring explicit professional signoff. No AI service is called by this app.

### Security note

For HTTPS deployments set `SECURE_SSL_REDIRECT=True`, correct `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, and reverse-proxy `SECURE_PROXY_SSL_HEADER` only for a trusted proxy. Bootstrap uses a local binding (`127.0.0.1:8000`) deliberately. Bootstrap, Bootstrap Icons and the fonts are vendored locally (licences included alongside).

## Development utilities

```bash
USE_SQLITE=True python manage.py test hospital   # 137 tests (Python/JavaScript parity tests need node)
docker compose -f compose.prod.yml logs -f web
docker compose -f compose.prod.yml exec web python manage.py check --deploy
```
