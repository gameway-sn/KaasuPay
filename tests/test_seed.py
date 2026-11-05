"""Phase 6: the demo seed puts every customer in the state its story says."""
import pytest
from sqlalchemy import select

from app.config import settings
from app.models import InstallmentStatus, KycStatus, Loan, LoanStatus, Payment, User
from app.seed import DEMO_CUSTOMERS, seed_customers, seed_staff
from app.services.crypto import decrypt
from app.services.kyc import get_kyc
from app.services.money import format_inr
from app.services import verhoeff


@pytest.fixture
def seeded(db):
    seed_staff(db)
    seed_customers(db)
    db.expire_all()
    return db


def customer(db, phone):
    return db.scalars(select(User).where(User.phone == phone)).first()


def loan_of(db, phone):
    return db.scalars(select(Loan).where(Loan.user_id == customer(db, phone).id)).first()


def test_all_customers_created(seeded):
    phones = {phone for phone, *_ in DEMO_CUSTOMERS}
    found = {u.phone for u in seeded.scalars(select(User).where(User.phone.in_(phones)))}
    assert found == phones


def test_kyc_states(seeded):
    assert get_kyc(seeded, customer(seeded, "9800000001").id) is None
    assert get_kyc(seeded, customer(seeded, "9800000002").id).status == KycStatus.SUBMITTED
    rejected = get_kyc(seeded, customer(seeded, "9800000003").id)
    assert rejected.status == KycStatus.REJECTED and "blurred" in rejected.rejection_reason
    assert get_kyc(seeded, customer(seeded, "9800000004").id).status == KycStatus.APPROVED


def test_fake_identities_are_valid_and_encrypted(seeded):
    kyc = get_kyc(seeded, customer(seeded, "9800000002").id)
    assert kyc.pan[3] == "P"
    aadhaar = decrypt(kyc.aadhaar_encrypted)
    assert verhoeff.is_valid(aadhaar) and aadhaar[0] in "23456789"
    assert len(kyc.documents) == 3
    for doc in kyc.documents:
        assert (settings.upload_dir / doc.stored_name).exists()


def test_loan_states(seeded):
    offer = loan_of(seeded, "9800000004")
    assert offer.status == LoanStatus.OFFERED
    assert format_inr(offer.offered_amount_paise) == "₹1,63,612.00"
    assert loan_of(seeded, "9800000005").status == LoanStatus.DECLINED
    assert loan_of(seeded, "9800000006").status == LoanStatus.ACCEPTED
    fresh = loan_of(seeded, "9800000007")
    assert fresh.status == LoanStatus.DISBURSED and not fresh.next_installment.is_overdue


def test_overdue_loan(seeded):
    loan = loan_of(seeded, "9800000008")
    assert loan.status == LoanStatus.ACTIVE
    assert [p.method for p in loan.payments] == ["online", "cash"]
    third = loan.installments[2]
    assert third.status == InstallmentStatus.DUE and third.is_overdue
    assert not loan.installments[3].is_overdue


def test_closed_loan(seeded):
    loan = loan_of(seeded, "9800000009")
    assert loan.status == LoanStatus.CLOSED
    assert loan.outstanding_paise == 0
    assert sum(p.amount_paise for p in loan.payments) == loan.total_payable_paise


def test_seed_twice_adds_nothing(seeded):
    payments_before = len(seeded.scalars(select(Payment)).all())
    assert seed_staff(seeded) == []
    assert seed_customers(seeded) == []
    assert len(seeded.scalars(select(Payment)).all()) == payments_before


def test_demo_customers_can_log_in(client, seeded, login):
    response = login("9800000008", settings.seed_customer_password)
    assert response.headers["location"] == "/dashboard"
    assert "overdue" in client.get("/dashboard").text
