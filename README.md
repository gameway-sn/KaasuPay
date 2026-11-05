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
- [ ] Phase 3: Loans
- [ ] Phase 4: Repayments
- [ ] Phase 5: Admin and audit
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
- **See the "ACL" working:** log in as a customer and open http://127.0.0.1:8000/staff, and you get **403 Forbidden**.
  Log out and open it again, and you are sent to the login page. As branch agent (`9000000004`),
  a KYC document link gives **403**.

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
  models/        # tables: User, OtpCode, KycRecord, KycDocument
  schemas/       # form validation (phone, OTP, password, PAN, Aadhaar)
  services/      # otp.py, verhoeff.py, crypto.py (Fernet + masking), uploads.py, kyc.py
  routers/       # auth.py, customer.py, kyc.py (customer + support review + documents), staff.py
  templates/     # HTML pages (base.html holds the demo banner)
  static/        # CSS
alembic/         # database migrations
tests/           # pytest tests
uploads/         # KYC files under random names; gitignored, served only via /kyc/documents/{id}
.env.example     # copy to .env; .env is never committed
```
