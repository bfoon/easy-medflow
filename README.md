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
- **Forms & approvals** — visual form builder with live preview and drag-to-reorder; workflow builder showing the
  approval chain; signature ledger.
- **Search** — press `Ctrl K` (or `/`) anywhere to find a patient by name, MRN or phone, or jump to a page.

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
knee osteoarthritis, gout) with synthetic X-rays and MRI, results, medicines, admissions and referrals.

## Modules included

- Patient MRN, demographics, longitudinal encounters, symptoms, assessments, diagnoses, vitals, conditions, allergies, medications, labs, admissions, referrals, structured forms and chart timeline.
- Multi-department queue tickets with triage priority, call/start/skip/requeue/complete transitions.
- Staff clock-in/out (does not implement shift scheduling, payroll or credential verification).
- Lab catalog and orders/results (verification workflow and reference ranges are placeholders pending validation).
- Medication catalog, expiry-aware stock batches, clinician-signed prescription and atomically dispensed stock movement.
- **Limited medication safety**: lists all documented active allergies; simple case-insensitive text match against a drug's listed name/generic name; blocks matches without override reason. It does NOT understand drug classes, equivalent names, true cross-reactivity, dosing, interactions, disease contraindications, pregnancy or kidney function. Every prescription requires clinician review. Not safe as sole alerting tool.
- Ward/bed availability, active admissions, discharge into 'cleaning' state.
- Referrals linked to clinical encounter, urgency, destination, contact and transfer status.
- Schema-configured clinical forms, versioned snapshots of submissions; sequenced role-based approval workflows.
- Electronic attestations: user-bound, time-stamped record with SHA-256 content digest and HMAC based on application secret, plus audit record. This is **not** an independently verifiable cryptographic digital signature or legally validated qualified e-sign service; changing the server secret breaks independent reproducibility and the signature record itself should be in append-only storage. No identity re-verification, PDF signing or PKI is included.
- Audit events on major access/actions.

## Forms Studio example

Form `schema` JSON:
```json
{"fields":[{"key":"chief_complaint","label":"Chief complaint","type":"textarea","required":true},{"key":"consent","label":"Consent received","type":"checkbox"},{"key":"risk","label":"Risk classification","type":"select","options":["low","moderate","high"]}]}
```
Workflow `steps` JSON:
```json
[{"name":"Nurse check","role":"nurse"},{"name":"Physician approval","role":"doctor"}]
```

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
USE_SQLITE=True python manage.py test hospital   # 61 workflow tests
docker compose -f compose.prod.yml logs -f web
docker compose -f compose.prod.yml exec web python manage.py check --deploy
```
