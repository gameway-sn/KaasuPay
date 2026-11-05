"""Demo data: one staff account per role, plus fake customers at every stage.

Run (after `alembic upgrade head`):  python -m app.seed
Safe to run more than once: anyone who already exists is skipped.

Everything here is FAKE: names, phones, PANs, Aadhaar numbers (valid checksum,
made up) and the ID "photos" (coloured rectangles generated below).

Customers are built with the real service functions (submit KYC, approve,
apply, disburse, pay), so they obey every rule and the audit log fills in.
For the overdue and closed loans we then move the dates back in time.
"""
import struct
import zlib
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, utcnow
from app.models import DocKind, Loan, PaymentMethod, Role, User
from app.schemas.kyc import KycForm
from app.schemas.loans import LoanApplicationForm
from app.security import hash_password
from app.services import verhoeff
from app.services.audit import record
from app.services.kyc import approve_kyc, reject_kyc, submit_kyc
from app.services.loans import accept_offer, add_months, apply_for_loan, disburse
from app.services.payments import record_payment
from app.services.uploads import CheckedFile

DEMO_STAFF = [
    ("9000000001", "Demo Support Officer", Role.SUPPORT),
    ("9000000002", "Demo Finance Officer", Role.FINANCE),
    ("9000000003", "Demo IT Admin", Role.IT_ADMIN),
    ("9000000004", "Demo Branch Agent", Role.BRANCH_AGENT),
]


# ======================= Staff =======================

def seed_staff(db: Session) -> list[str]:
    """Add any demo staff that don't exist yet. Returns the phones added."""
    added = []
    for phone, name, role in DEMO_STAFF:
        if db.scalars(select(User).where(User.phone == phone)).first():
            continue
        db.add(User(
            phone=phone,
            full_name=name,
            role=role,
            password_hash=hash_password(settings.seed_staff_password),
            phone_verified=True,
        ))
        added.append(phone)
    db.commit()
    return added


# ======================= Helpers =======================

def sample_png(rgb: tuple[int, int, int], width: int = 240, height: int = 150) -> bytes:
    """A plain coloured 'card' with a white stripe: obviously not a real ID."""
    row = b"\x00" + bytes(rgb) * width            # \x00 = PNG "no filter" byte at each row start
    stripe = b"\x00" + b"\xff\xff\xff" * width
    raw = b"".join(stripe if 20 <= y < 40 else row for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def fake_identity(phone: str, index: int) -> tuple[str, str]:
    """A made-up PAN (4th letter P) and a made-up Aadhaar with a valid checksum."""
    pan = f"DEMP{chr(ord('A') + index)}{1000 + index}Z"   # e.g. DEMPA1000Z
    digits = "2" + phone                                   # 11 digits, starts with 2
    return pan, digits + verhoeff.check_digit(digits)


def demo_files(rgb) -> dict[str, CheckedFile]:
    files = {}
    for kind, shade in ((DocKind.ID_FRONT, 1.0), (DocKind.ID_BACK, 0.8), (DocKind.SELFIE, 0.6)):
        colour = tuple(int(c * shade) for c in rgb)
        data = sample_png(colour)
        files[kind] = CheckedFile(data=data, content_type="image/png", extension=".png")
    return files


def application(amount, months, income, existing=0) -> LoanApplicationForm:
    return LoanApplicationForm(amount=str(amount), tenure_months=str(months),
                               monthly_income=str(income), existing_emis=str(existing))


def move_loan_back(db: Session, loan: Loan, days: int) -> None:
    """Pretend the loan was disbursed `days` ago, so some EMIs are already due."""
    start = utcnow() - timedelta(days=days)
    loan.accepted_at = start - timedelta(hours=3)
    loan.disbursed_at = start
    for inst in loan.installments:
        inst.due_date = add_months(start.date(), inst.number)
    db.commit()


def pay(db: Session, loan: Loan, method: PaymentMethod, by: User) -> None:
    """Pay the next EMI, and date the payment on its due day."""
    inst = loan.next_installment
    amount = inst.amount_paise if method == PaymentMethod.CASH else None
    payment = record_payment(db, loan, inst.id, method, recorded_by=by, amount_paise=amount)
    payment.paid_at = datetime.combine(inst.due_date, time(11, 30))
    db.commit()


# ======================= Customers =======================
# Each builder takes the new customer and the staff who act on them.

def _kyc(db, c, staff, approve=True):
    pan, aadhaar = staff["identity"]
    kyc = submit_kyc(db, c, KycForm(pan=pan, aadhaar=aadhaar), demo_files(staff["colour"]))
    if approve:
        approve_kyc(db, kyc, staff["support"])
    return kyc


def no_kyc(db, c, staff):
    pass


def kyc_submitted(db, c, staff):
    _kyc(db, c, staff, approve=False)


def kyc_rejected(db, c, staff):
    kyc = _kyc(db, c, staff, approve=False)
    reject_kyc(db, kyc, staff["support"], "Selfie is blurred. Please upload a clear photo.")


def loan_counter_offer(db, c, staff):
    _kyc(db, c, staff)
    apply_for_loan(db, c, application(2_00_000, 12, 40_000, 5_000))    # offered ₹1,63,612


def loan_declined(db, c, staff):
    _kyc(db, c, staff)
    apply_for_loan(db, c, application(50_000, 12, 8_000, 4_000))       # existing EMIs use 50%


def loan_accepted(db, c, staff):
    _kyc(db, c, staff)
    loan = apply_for_loan(db, c, application(1_00_000, 12, 40_000, 5_000))
    accept_offer(db, loan)                                               # waits for finance


def loan_disbursed(db, c, staff):
    _kyc(db, c, staff)
    loan = apply_for_loan(db, c, application(30_000, 3, 40_000))
    accept_offer(db, loan)
    disburse(db, loan, staff["finance"])                                 # first EMI due next month


def loan_overdue(db, c, staff):
    _kyc(db, c, staff)
    loan = apply_for_loan(db, c, application(60_000, 6, 50_000))
    accept_offer(db, loan)
    disburse(db, loan, staff["finance"])
    move_loan_back(db, loan, days=97)                                    # EMIs 1-3 now past due
    pay(db, loan, PaymentMethod.ONLINE, c)
    pay(db, loan, PaymentMethod.CASH, staff["agent"])                    # #3 left unpaid -> overdue


def loan_closed(db, c, staff):
    _kyc(db, c, staff)
    loan = apply_for_loan(db, c, application(15_000, 3, 30_000))
    accept_offer(db, loan)
    disburse(db, loan, staff["finance"])
    move_loan_back(db, loan, days=100)
    pay(db, loan, PaymentMethod.ONLINE, c)
    pay(db, loan, PaymentMethod.CASH, staff["agent"])
    pay(db, loan, PaymentMethod.ONLINE, c)                               # last EMI -> closed


# (phone, name, what to show with them, builder, card colour)
# The story text says "Rs." not "₹": it is printed to the console, and some Windows
# consoles can't print ₹ when the output is redirected.
DEMO_CUSTOMERS = [
    ("9800000001", "Asha Demo", "registered, no KYC yet", no_kyc, (90, 140, 200)),
    ("9800000002", "Bala Demo", "KYC submitted, waiting for support", kyc_submitted, (200, 120, 60)),
    ("9800000003", "Chitra Demo", "KYC rejected (blurred selfie), can resubmit", kyc_rejected, (150, 90, 170)),
    ("9800000004", "Dev Demo", "counter-offer: asked Rs.2,00,000, offered Rs.1,63,612", loan_counter_offer, (60, 150, 120)),
    ("9800000005", "Esha Demo", "loan declined by the 50% rule", loan_declined, (180, 160, 60)),
    ("9800000006", "Farhan Demo", "accepted Rs.1,00,000, waiting for finance to disburse", loan_accepted, (70, 110, 160)),
    ("9800000007", "Gita Demo", "disbursed Rs.30,000, first EMI not due yet", loan_disbursed, (160, 80, 80)),
    ("9800000008", "Hari Demo", "active: EMI 1 online + EMI 2 cash paid, EMI 3 OVERDUE", loan_overdue, (90, 160, 160)),
    ("9800000009", "Isha Demo", "loan fully repaid and closed", loan_closed, (120, 120, 120)),
]


def _staff_member(db: Session, role: Role) -> User:
    user = db.scalars(select(User).where(User.role == role).order_by(User.id)).first()
    if user is None:
        raise RuntimeError(f"No {role} account: run seed_staff first.")
    return user


def seed_customers(db: Session) -> list[str]:
    """Add any demo customers that don't exist yet. Returns the phones added."""
    staff = {
        "support": _staff_member(db, Role.SUPPORT),
        "finance": _staff_member(db, Role.FINANCE),
        "agent": _staff_member(db, Role.BRANCH_AGENT),
    }
    added = []
    for index, (phone, name, _story, build, colour) in enumerate(DEMO_CUSTOMERS):
        if db.scalars(select(User).where(User.phone == phone)).first():
            continue
        customer = User(phone=phone, full_name=name, role=Role.CUSTOMER,
                        password_hash=hash_password(settings.seed_customer_password), phone_verified=True)
        db.add(customer)
        db.commit()
        build(db, customer, {**staff, "identity": fake_identity(phone, index), "colour": colour})
        added.append(phone)
    if added:
        record(db, None, "admin.demo_seed", detail=f"{len(added)} demo customers created by app.seed")
        db.commit()
    return added


def main() -> None:
    with SessionLocal() as db:
        staff_added = seed_staff(db)
        customers_added = seed_customers(db)

    print(f"Added {len(staff_added)} staff and {len(customers_added)} customer account(s).\n")
    print("STAFF  (password: SEED_STAFF_PASSWORD in .env)")
    for phone, name, role in DEMO_STAFF:
        print(f"  {phone}  {role:<13} {name}")
    print("\nCUSTOMERS  (password: SEED_CUSTOMER_PASSWORD in .env)")
    for phone, name, story, _build, _colour in DEMO_CUSTOMERS:
        print(f"  {phone}  {name:<12} {story}")


if __name__ == "__main__":
    main()
