# KaasuPay Loan Portal (FastAPI prototype)

> **DEMO — KaasuPay is fictional. Do not enter real personal data.**
> This prototype demonstrates security controls. It is **not** production-secure,
> and it must only run on localhost or our own LAN.

This is the loan app for our Computer Networks (21CSC302J) team project,
*"Design and Configuration of a Secure FinTech Enterprise Network using Cisco Packet Tracer"*.
In the project story it runs on SRV-APP (10.10.40.10, VLAN 40). See [CLAUDE.md](CLAUDE.md) for the full design.

## Status

- [x] Phase 0: Setup (hello page, base layout with demo banner)
- [x] Phase 1: Users and login (phone + OTP registration, argon2, JWT cookie, roles, staff seed)
- [x] Phase 2: KYC (PAN/Aadhaar checks, Verhoeff, Fernet encryption, safe uploads, support review)
- [x] Phase 3: Loans (EMI calculator, 50% income rule, offer/accept, finance disbursal, repayment schedule)
- [x] Phase 4: Repayments (fake online gateway, branch cash collection, one payments ledger, active/closed)
- [x] Phase 5: Admin and audit (append-only audit log, login lockout, OTP limit, IT admin staff management)
- [ ] Phase 6: Demo-ready

## Run it (Windows PowerShell)

You need Python 3.12 or newer. (If `pytest` fails with an error from `py.py`, use 3.13 instead:
a file named `py.py` in the Python 3.12 install folder hides a module that pytest needs.)

```powershell
# 1. Create and activate a virtual environment (once)
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
# If PowerShell blocks the script, run this once and try again:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 2. Install the libraries
pip install -r requirements.txt

# 3. Create your local settings file, then fill in the two secrets
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"                              # -> JWT_SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # -> FERNET_KEY

# 4. Create the database tables (run again whenever a new migration is added)
alembic upgrade head

# 5. Create the demo staff accounts (safe to run again)
python -m app.seed

# 6. Start the server
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. You should see the red DEMO banner at the top.

### Try it

- **Register as a customer:** go to *Register*, use any fake 10-digit number starting with 6–9.
  The OTP is printed in the **server console** (the window running uvicorn), in a `[DEMO SMS]` box.
- **Log in as staff:** phone `9000000001` (support), `9000000002` (finance),
  `9000000003` (it_admin), `9000000004` (branch_agent). Password: `SEED_STAFF_PASSWORD` from `.env`.
- **KYC (customer):** from the dashboard, *Start KYC*. Use a fake PAN like `ABCPE1234F`; the page
  offers a made-up Aadhaar number with a valid checksum. Upload three small JPG/PNG/PDF files
  (any sample picture, **never a real ID card**).
- **KYC review (support):** log in as `9000000001`, open *KYC review queue*, approve or reject with a reason.
  Aadhaar only ever shows as `XXXX XXXX 1234` to staff.
- **Loan (customer):** with an approved KYC, *Apply for a loan*. Try ₹1,00,000 / 12 months / income ₹40,000 /
  existing EMIs ₹5,000 → full offer, EMI ₹9,168.00. Try ₹2,00,000 → a counter-offer of ₹1,63,612. Accept it.
- **Disbursal (finance):** log in as `9000000002`, open *Loan book*, *Review* the accepted loan, *Approve disbursal*.
  The customer now sees a 12-month repayment schedule.
- **Pay an EMI (customer):** on a disbursed loan, *Pay EMI #1* opens the DEMO gateway; pay, and the loan
  turns `active`. Pay them all and it turns `closed`.
- **Cash at the branch (branch agent):** log in as `9000000004`, *Collect a cash EMI*, type the loan ID,
  then type the exact amount due. The phone shows masked; no PAN, Aadhaar or KYC documents appear.
  Finance's loan book shows online vs cash totals from the same ledger.
- **Lockout:** type a wrong password 5 times. The account is locked for 15 minutes, even with the right password.
  IT admin can *Unlock* it.
- **IT admin:** log in as `9000000003`. *Staff accounts*: add, deactivate, unlock, reset a password
  (temporary passwords are shown once). *Audit log*: filter by category or customer to see e.g. who viewed
  a customer's KYC, who disbursed and who collected cash, plus every 403.
- **See the "ACL" working:** log in as a customer and open http://127.0.0.1:8000/staff, and you get **403 Forbidden**.
  Log out and open it again, and you are sent to the login page. As branch agent (`9000000004`),
  a KYC document link gives **403**. Another customer opening `/loans/<id>` of someone else's loan gets **404**.

## Run the tests

```powershell
pytest
```

Tests use a fresh in-memory database each time; they never touch `kaasupay.db`.

## Project layout

```
app/
  main.py        # creates the app, plugs in the routers, error pages
  config.py      # settings read from .env
  db.py          # database engine + session (get_db)
  deps.py        # get_current_user, require_role(...)  <- the app's "ACL"
  security.py    # argon2 passwords, JWT login cookie
  seed.py        # demo staff accounts
  templating.py  # Jinja2 setup
  models/        # tables: User, OtpCode, KycRecord, KycDocument, Loan, Installment, Payment, AuditEvent
  schemas/       # form validation (phone, OTP, password, PAN, Aadhaar, loan application)
  services/      # otp, verhoeff, crypto (Fernet + masking), uploads, kyc,
                 # money (paise + ₹ formatting), emi, decision (50% rule), loans, payments,
                 # audit (log + IP middleware), login (lockout), staff (IT admin actions)
  routers/       # auth, customer, kyc (customer + support review + documents),
                 # loans (customer + finance loan book/disbursal),
                 # payments (online gateway + branch cash), staff, admin (staff accounts + audit log)
  templates/     # HTML pages (base.html holds the demo banner)
  static/        # CSS
alembic/         # database migrations
tests/           # pytest tests
uploads/         # KYC files under random names; gitignored, served only via /kyc/documents/{id}
.env.example     # copy to .env; .env is never committed
```
