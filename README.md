# MedFlow HMS — Django / Bootstrap / PostgreSQL / Redis / Docker

An extendable **hospital-management MVP / developer starter**, not a certified electronic health record, medical device, or production-ready clinical decision support system. Treat all data as sensitive; do not process real patient information until a qualified security, privacy, and clinical team signs off.

## Quick start with Docker (demo / development)

```bash
docker compose up -d --build
```

Open http://localhost:8000 and sign in as `admin` / `medflow-admin-2026`. On first start the container migrates,
loads fictional demo data and creates the admin account; restarts keep your data and skip both steps. Your code is
mounted into the container, so edits reload the server automatically.

| Task | Command |
| --- | --- |
| Run in the foreground (see logs live) | `docker compose up --build` |
| Follow logs | `docker compose logs -f web` |
| Run tests | `docker compose exec web python manage.py test hospital` |
| Django shell | `docker compose exec web python manage.py shell` |
| Stop | `docker compose down` |
| Reset to fresh demo data | `docker compose down -v` then `up` again |

Change the admin credentials in `compose.yml` before the first start if you like. This stack uses SQLite and
`DEBUG=True`; it is for demos and development only. For real deployments use the PostgreSQL stack below.

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
USE_SQLITE=True python manage.py test hospital   # 13 workflow tests
docker compose -f compose.prod.yml logs -f web
docker compose -f compose.prod.yml exec web python manage.py check --deploy
```
