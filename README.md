# MedFlow HMS — Django / Bootstrap / PostgreSQL / Redis / Docker

An extendable **hospital-management MVP / developer starter**, not a certified electronic health record, medical device, or production-ready clinical decision support system. Treat all data as sensitive; do not process real patient information until a qualified security, privacy, and clinical team signs off.

## Quick start with Docker

```bash
docker compose up -d --build
docker compose ps          # db, redis, web and worker should all be running
docker compose logs -f web # wait for "MedFlow is starting at http://localhost:8000"
```

Open http://localhost:8000 and sign in as `admin` / `medflow-admin-2026`. No `.env` file is needed.

| Service | What it is | Reach it from your machine |
| --- | --- | --- |
| `db` | PostgreSQL 16 (database `medflow`, user `medflow`, password `medflow-dev-password`) | `localhost:5433` |
| `redis` | Redis 7, message broker for background jobs | internal only |
| `web` | MedFlow (Django dev server, auto-reloads when you edit code) | http://localhost:8000 |
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
USE_SQLITE=True python manage.py test hospital   # 20 workflow tests
docker compose -f compose.prod.yml logs -f web
docker compose -f compose.prod.yml exec web python manage.py check --deploy
```
