# KaasuPay Loan Portal — FastAPI prototype

## What this project is

A working prototype of the loan app for KaasuPay, the made-up digital-lending company in our
Computer Networks (21CSC302J) team project, "Design and Configuration of a Secure FinTech
Enterprise Network using Cisco Packet Tracer".

- The **network** (VLANs, ACLs, IPsec VPN, port security) is built separately in Cisco Packet Tracer.
- This **app** runs on our laptops. In the project story it is the loan portal on SRV-APP
  (10.10.40.10, VLAN 40), and its database is SRV-DB (10.10.50.10, VLAN 50, the "vault").
- It must work end to end: register → KYC → loan → repayment, plus the staff side.
- It is also a learning project. The team is new to FastAPI.

The app copies the network's security design in code, so the whole project tells one story:
defence in depth, from the network up to the app.

| In the network (Packet Tracer) | Its twin in this app |
| --- | --- |
| VLANs separate departments | Roles: customer, support, finance, it_admin, branch_agent |
| ACLs give each VLAN only what it needs | A role check on every route (`require_role(...)`) |
| Vault VLAN: only SRV-APP and IT reach the DB | Only the API touches the DB; Aadhaar encrypted at rest, shown masked |
| IPsec VPN encrypts branch traffic | HTTPS (stretch phase) |
| SSH only, login blocked after 3 failures | Hashed passwords, short-lived JWT, lockout after failed logins/OTPs |
| Port security, DHCP snooping | Strict validation of uploads and form input |
| `show` commands as evidence | Audit log: who viewed which customer's KYC, who moved money |

## How to work with me (learning mode)

- Work one small step at a time, one feature per step. Never several phases in one go.
- Before writing code, explain in plain language what the step does and why, with a concrete example.
- After each step, tell me exactly how to run it and what I should see, then stop and wait.
- Prefer small files I can read. When I say "explain", go through the code line by line.
- Do not add features, libraries or files outside the current phase without asking first.
- My machine is Windows with PowerShell. Give PowerShell commands
  (e.g. `.venv\Scripts\Activate.ps1`), not bash, unless I say I am on another machine.

## Hard rules

- **Fake data only.** Never real Aadhaar, PAN, bank numbers, or photos of real ID documents.
- **KYC is simulated.** No calls to UIDAI, DigiLocker, NSDL or any real KYC/credit API.
- **Runs locally only** (localhost or our own LAN). Never deployed to a public host.
- Every page shows a banner: "DEMO — KaasuPay is fictional. Do not enter real personal data."
- Secrets (JWT key, Fernet key) live in `.env`, which is gitignored. Commit `.env.example` only.
- Money is stored as integer paise, never floats.
- This is a prototype that demonstrates security controls; never describe it as production-secure.

## Stack

- Python 3.12+, FastAPI, Uvicorn
- Jinja2 server-rendered templates and plain CSS (no React; HTMX only if we decide later)
- SQLAlchemy 2.0 + Alembic; SQLite for phases 0–6, PostgreSQL in Docker in the stretch phase
- Pydantic v2 (+ pydantic-settings for config)
- Passwords: argon2 (`argon2-cffi`); login: JWT in an HttpOnly, SameSite cookie, 30-minute expiry
- Aadhaar encryption: `cryptography` Fernet
- Tests: pytest + FastAPI `TestClient`

## Roles

| Role | Mirrors | Can | Cannot |
| --- | --- | --- | --- |
| customer | — | Register, submit KYC, apply, accept an offer, pay EMIs, see own loans | See anyone else's data |
| support | VLAN 20 | Review KYC (masked Aadhaar), approve/reject with a reason | Any money action |
| finance | VLAN 10 | Approve disbursal, view the loan book and reports | Edit or approve KYC |
| it_admin | VLAN 30 | Manage staff accounts, read the audit log | Approve KYC or loans (separation of duties) |
| branch_agent | VLAN 110 | Find a loan by its ID, record a cash EMI collection | View KYC documents or Aadhaar |

## The end-to-end flow

1. Customer registers with a phone number → 6-digit OTP printed to the server console → sets a password.
2. KYC: enters PAN + Aadhaar, uploads front/back ID images and a selfie → validated → `submitted`.
3. Support reviews KYC (masked Aadhaar, documents) → `approved` or `rejected` with a reason.
4. Customer applies: amount, tenure, monthly income, existing EMIs → app computes EMI and decides.
5. Customer accepts the offer → finance approves disbursal → repayment schedule created.
6. Customer pays an EMI (fake payment button) → installment `paid`.
7. Branch agent records a cash EMI collection → same ledger, marked `cash`.
8. IT admin manages staff accounts and reads the audit log.

### Status workflows

- KYC: `draft → submitted → approved | rejected`; a rejected KYC can be resubmitted.
- Loan: `applied → offered | declined → accepted → disbursed → active → closed`
- Installment: `due → paid` (method `online` or `cash`); `overdue` if unpaid after its due date.

## Business rules

- Phone: 10 digits, first digit 6–9.
- OTP: 6 digits, expires in 5 minutes, locked after 3 wrong tries.
- Login: account locked for 15 minutes after 5 failed attempts.
- PAN: `^[A-Z]{5}[0-9]{4}[A-Z]$`; 4th character must be `P` (individual).
- Aadhaar: 12 digits, first digit 2–9, valid Verhoeff checksum. Stored Fernet-encrypted;
  shown as `XXXX XXXX 1234` to everyone except the customer at entry time.
- Uploads: jpg/png/pdf only, max 2 MB, saved outside `static/` under random filenames,
  served only through a route that checks the role.
- Loan amount ₹5,000–₹2,00,000; tenure 3–24 months; flat demo rate 18% a year.
- EMI = P·r·(1+r)^n / ((1+r)^n − 1), with r = annual rate / 12 / 100.
  Check: ₹1,00,000 at 18% for 12 months = ₹9,168.00. The last installment absorbs rounding.
- Decision (demo rule): decline if KYC is not approved; approve if new EMI + existing EMIs
  ≤ 50% of monthly income; otherwise offer the largest amount that meets the 50% rule, or decline.

## Build phases

Each phase ends with something runnable and its tests passing. Stop after each phase.

0. **Setup** — venv, FastAPI hello page, Jinja base layout with the demo banner, git, `.env.example`, README.
1. **Users and login** — User model with role, phone + OTP registration, login/logout, argon2,
   JWT cookie, `require_role(...)` dependency, seed script for one staff user per role.
2. **KYC** — KYC form and uploads, PAN/Aadhaar validators (Verhoeff in `services/verhoeff.py`),
   Fernet encryption, masked display, support review queue, approve/reject.
3. **Loans** — application form, EMI calculator, decision rule, offer/accept, finance disbursal,
   repayment schedule.
4. **Repayments** — pay EMI (fake gateway), branch agent cash collection, customer loan page.
5. **Admin and audit** — staff management, audit log (KYC views, approvals, money actions),
   lockouts.
6. **Demo-ready** — seed fake customers in each state, full access-matrix tests, README with run steps.

Stretch (only if phases 0–6 are done): HTTPS with a local certificate; PostgreSQL + Docker Compose
with separate networks copying the VLANs (DB only on a "vault" network, plus a "guest" container that
fails to reach it); Razorpay test mode for EMI payments; PDF loan agreement.

## Suggested layout

```
app/
  main.py  config.py  db.py  deps.py        # deps.py holds get_current_user, require_role
  models/  schemas/
  routers/   auth.py kyc.py loans.py payments.py staff.py admin.py
  services/  emi.py decision.py verhoeff.py crypto.py audit.py otp.py
  templates/ static/
alembic/
tests/
uploads/        # gitignored
.env.example  README.md
```

## Tests that mirror the Packet Tracer test plan

- support sees only the masked Aadhaar on a KYC page
- support → finance disbursal route = 403
- branch_agent → KYC document route = 403
- customer A → customer B's loan = 404
- 4th wrong OTP = locked
- any `/staff/...` route without login = redirect to login
- EMI: ₹1,00,000, 18%, 12 months = ₹9,168.00
- Verhoeff: a valid sample passes; changing one digit fails
