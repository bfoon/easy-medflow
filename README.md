# MedFlow HMS — Django / Bootstrap / PostgreSQL / Redis / Docker

An extendable **hospital-management MVP / developer starter**, not a certified electronic health record, medical device, or production-ready clinical decision support system. Treat all data as sensitive; do not process real patient information until a qualified security, privacy, and clinical team signs off.

## Start

```bash
cp .env.example .env
# Set strong DJANGO_SECRET_KEY and POSTGRES_PASSWORD in .env.
docker compose up -d --build
# Generate and run schema migrations on first setup:
docker compose exec web python manage.py createsuperuser
```

Open http://localhost:8000/accounts/login/ . The first boot automatically runs schema generation/migration, static collection and seed setup. Map the web port behind an HTTPS reverse proxy before deploying beyond localhost. Use `python manage.py makemigrations hospital` only while developing the schema; the supplied initial migration is included.

After creating staff users, add a **Staff profile** in `/admin/`, select a role, and optionally a department. Superusers may access everything; other accounts require an active StaffProfile. Clinical modules: doctor/nurse; pharmacy: pharmacy; laboratory: lab/doctor; front desk: reception/nurse. Administrative access to the Django admin is separately controlled by Django `is_staff` and granular model permissions: don't grant broad admin access to clinical workers.

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

For HTTPS deployments set `SECURE_SSL_REDIRECT=True`, correct `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, and reverse-proxy `SECURE_PROXY_SSL_HEADER` only for a trusted proxy. Bootstrap uses a local binding (`127.0.0.1:8000`) deliberately. The Bootstrap stylesheet is a third-party CDN dependency; self-host it before production to control supply chain and availability.

## Development utilities

```bash
docker compose logs -f web
docker compose exec web python manage.py check
docker compose exec web python manage.py test
```
