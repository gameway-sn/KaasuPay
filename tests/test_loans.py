"""Phase 3: applying, offers, finance disbursal, and who may do what."""
import pytest
from sqlalchemy import select

from app.models import InstallmentStatus, KycRecord, KycStatus, Loan, LoanStatus, Role
from app.services.crypto import encrypt
from app.services.loans import add_months

CUSTOMER = "9876543210"
OTHER = "9876500000"
FINANCE = "9000000002"


def approve_kyc_for(db, user):
    """Shortcut: give a user an approved KYC directly in the database."""
    db.add(KycRecord(user_id=user.id, status=KycStatus.APPROVED, pan="ABCPE1234F",
                     aadhaar_encrypted=encrypt("234123412346"), aadhaar_last4="2346"))
    db.commit()


def apply(client, amount="100000", months="12", income="40000", existing="5000"):
    return client.post("/loans/apply", data={
        "amount": amount, "tenure_months": months, "monthly_income": income, "existing_emis": existing,
    }, follow_redirects=False)


def latest_loan(db):
    db.expire_all()
    return db.scalars(select(Loan).order_by(Loan.id.desc())).first()


def switch_to(client, make_user, login, phone, role):
    client.cookies.clear()
    make_user(phone, role)
    login(phone)


@pytest.fixture
def customer(db, make_user, login):
    user = make_user(CUSTOMER, Role.CUSTOMER, full_name="Ravi Demo")
    approve_kyc_for(db, user)
    login(CUSTOMER)
    return user


@pytest.fixture
def accepted_loan(client, db, customer):
    apply(client)
    loan = latest_loan(db)
    client.post(f"/loans/{loan.id}/accept")
    return latest_loan(db)


# ---------- Customer applies ----------

def test_apply_gets_full_offer(client, db, customer):
    response = apply(client)
    loan = latest_loan(db)
    assert response.status_code == 303
    assert response.headers["location"] == f"/loans/{loan.id}"
    assert loan.status == LoanStatus.OFFERED
    assert loan.offered_amount_paise == 10000000
    assert loan.emi_paise == 916800

    page = client.get(f"/loans/{loan.id}")
    assert "₹9,168.00" in page.text
    assert "Accept offer" in page.text


def test_apply_gets_counter_offer(client, db, customer):
    apply(client, amount="200000")
    loan = latest_loan(db)
    assert loan.status == LoanStatus.OFFERED
    assert loan.offered_amount_paise < 20000000
    assert "Counter-offer" in client.get(f"/loans/{loan.id}").text


def test_apply_without_approved_kyc_is_declined(client, db, make_user, login):
    make_user(OTHER, Role.CUSTOMER)
    login(OTHER)
    apply(client)
    loan = latest_loan(db)
    assert loan.status == LoanStatus.DECLINED
    assert "KYC" in loan.decision_reason


@pytest.mark.parametrize("field, value, message", [
    ("amount", "4999", "between ₹5,000 and ₹2,00,000"),
    ("amount", "200001", "between ₹5,000 and ₹2,00,000"),
    ("amount", "12.5", "whole number of rupees"),
    ("months", "2", "between 3 and 24"),
    ("months", "25", "between 3 and 24"),
    ("income", "0", "Monthly income"),
])
def test_bad_application_is_rejected(client, db, customer, field, value, message):
    response = apply(client, **{field: value})
    assert response.status_code == 422
    assert message in response.text
    assert latest_loan(db) is None


def test_amount_with_commas_is_accepted(client, db, customer):
    apply(client, amount="1,00,000", income="40,000")
    assert latest_loan(db).requested_amount_paise == 10000000


def test_only_one_open_loan_at_a_time(client, db, customer):
    apply(client)
    response = apply(client)
    assert response.status_code == 409
    assert "already have an open loan" in response.text


def test_decline_offer_then_apply_again(client, db, customer):
    apply(client)
    loan = latest_loan(db)
    client.post(f"/loans/{loan.id}/decline")
    assert latest_loan(db).status == LoanStatus.DECLINED
    assert apply(client).status_code == 303


def test_accept_offer(client, db, accepted_loan):
    assert accepted_loan.status == LoanStatus.ACCEPTED
    assert accepted_loan.accepted_at is not None
    assert client.post(f"/loans/{accepted_loan.id}/accept").status_code == 409  # not twice


# ---------- Finance disburses ----------

def test_finance_disburses_and_schedule_is_created(client, db, make_user, login, accepted_loan):
    switch_to(client, make_user, login, FINANCE, Role.FINANCE)
    assert "Ravi Demo" in client.get("/staff/loans").text

    response = client.post(f"/staff/loans/{accepted_loan.id}/disburse", follow_redirects=False)
    assert response.status_code == 303

    loan = latest_loan(db)
    assert loan.status == LoanStatus.DISBURSED
    assert loan.disbursed_by.phone == FINANCE
    assert len(loan.installments) == 12
    assert all(i.status == InstallmentStatus.DUE for i in loan.installments)
    assert sum(i.principal_paise for i in loan.installments) == 10000000
    start = loan.disbursed_at.date()
    assert [i.due_date for i in loan.installments] == [add_months(start, n) for n in range(1, 13)]

    # Can't disburse twice.
    assert client.post(f"/staff/loans/{loan.id}/disburse").status_code == 409


def test_finance_cannot_disburse_before_customer_accepts(client, db, make_user, login, customer):
    apply(client)
    loan = latest_loan(db)
    switch_to(client, make_user, login, FINANCE, Role.FINANCE)
    assert client.post(f"/staff/loans/{loan.id}/disburse").status_code == 409


def test_loan_book_report_totals(client, db, make_user, login, accepted_loan):
    switch_to(client, make_user, login, FINANCE, Role.FINANCE)
    client.post(f"/staff/loans/{accepted_loan.id}/disburse")
    page = client.get("/staff/loans").text
    assert "₹1,00,000.00" in page          # disbursed
    total = latest_loan(db).total_payable_paise
    assert total > 10000000                # repaying more than borrowed (interest)


# ---------- Who may do what (ACL tests) ----------

def test_support_cannot_disburse(client, db, make_user, login, accepted_loan):
    """CLAUDE.md test plan: support -> finance disbursal route = 403."""
    switch_to(client, make_user, login, "9000000001", Role.SUPPORT)
    assert client.post(f"/staff/loans/{accepted_loan.id}/disburse").status_code == 403
    assert latest_loan(db).status == LoanStatus.ACCEPTED


@pytest.mark.parametrize("role", [Role.SUPPORT, Role.IT_ADMIN, Role.BRANCH_AGENT, Role.CUSTOMER])
def test_only_finance_sees_loan_book(client, db, make_user, login, accepted_loan, role):
    switch_to(client, make_user, login, "9000000009", role)
    assert client.get("/staff/loans").status_code == 403
    assert client.get(f"/staff/loans/{accepted_loan.id}").status_code == 403
    assert client.post(f"/staff/loans/{accepted_loan.id}/disburse").status_code == 403


def test_customer_cannot_see_another_customers_loan(client, db, make_user, login, accepted_loan):
    """CLAUDE.md test plan: customer A -> customer B's loan = 404."""
    switch_to(client, make_user, login, OTHER, Role.CUSTOMER)
    assert client.get(f"/loans/{accepted_loan.id}").status_code == 404
    assert client.post(f"/loans/{accepted_loan.id}/decline").status_code == 404
    assert latest_loan(db).status == LoanStatus.ACCEPTED


def test_missing_loan_is_404(client, customer):
    assert client.get("/loans/999").status_code == 404


def test_staff_cannot_apply(client, make_user, login):
    switch_to(client, make_user, login, FINANCE, Role.FINANCE)
    assert apply(client).status_code == 403


def test_loans_without_login_redirect(client):
    for url in ["/loans/apply", "/loans/1", "/staff/loans"]:
        response = client.get(url, follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/login"
