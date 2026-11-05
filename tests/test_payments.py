"""Phase 4: paying EMIs online (customer) and in cash (branch agent)."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import utcnow
from app.models import (
    InstallmentStatus, KycRecord, KycStatus, Loan, LoanStatus, Payment, PaymentMethod, Role,
)
from app.schemas.loans import LoanApplicationForm
from app.services.crypto import encrypt
from app.services.loans import accept_offer, apply_for_loan, disburse
from app.services.money import parse_amount_paise

CUSTOMER = "9876543210"
OTHER = "9876500000"
AGENT = "9000000004"


@pytest.fixture
def customer(db, make_user, login):
    user = make_user(CUSTOMER, Role.CUSTOMER, full_name="Ravi Demo")
    db.add(KycRecord(user_id=user.id, status=KycStatus.APPROVED, pan="ABCPE1234F",
                     aadhaar_encrypted=encrypt("234123412346"), aadhaar_last4="2346"))
    db.commit()
    login(CUSTOMER)
    return user


@pytest.fixture
def loan(db, make_user, customer):
    """A disbursed 3-month loan of ₹30,000 (made directly with the services, for speed)."""
    finance = make_user("9000000002", Role.FINANCE)
    form = LoanApplicationForm(amount="30000", tenure_months="3", monthly_income="40000", existing_emis="0")
    new_loan = apply_for_loan(db, customer, form)
    accept_offer(db, new_loan)
    disburse(db, new_loan, finance)
    return new_loan


def reload(db, loan_id):
    db.expire_all()
    return db.get(Loan, loan_id)


def pay_online(client, loan, installment_id=None):
    if installment_id is None:
        installment_id = loan.next_installment.id
    return client.post(f"/loans/{loan.id}/pay", data={"installment_id": installment_id}, follow_redirects=False)


def as_agent(client, make_user, login):
    client.cookies.clear()
    make_user(AGENT, Role.BRANCH_AGENT, full_name="Demo Branch Agent")
    login(AGENT)


def pay_cash(client, loan, amount=None, installment_id=None):
    nxt = loan.next_installment
    if amount is None:
        amount = f"{nxt.amount_paise / 100:.2f}"
    return client.post(f"/staff/collect/{loan.id}", data={
        "installment_id": installment_id or nxt.id, "amount": amount,
    }, follow_redirects=False)


# ---------- Online ----------

def test_gateway_page_shows_demo_warning_and_amount(client, loan):
    page = client.get(f"/loans/{loan.id}/pay")
    assert page.status_code == 200
    assert "DEMO payment gateway" in page.text
    assert "Pay EMI #1" in page.text


def test_customer_pays_first_emi(client, db, loan):
    response = pay_online(client, loan)
    assert response.status_code == 303
    assert response.headers["location"] == f"/loans/{loan.id}?paid=1"

    loan = reload(db, loan.id)
    assert loan.status == LoanStatus.ACTIVE            # disbursed -> active
    assert loan.installments[0].status == InstallmentStatus.PAID
    payment = loan.installments[0].payment
    assert payment.method == PaymentMethod.ONLINE
    assert payment.reference.startswith("DEMO-ONLINE-")
    assert payment.amount_paise == loan.installments[0].amount_paise
    assert payment.recorded_by.phone == CUSTOMER
    assert "Payment received" in client.get(f"/loans/{loan.id}?paid=1").text


def test_double_click_does_not_pay_twice(client, db, loan):
    first_id = loan.next_installment.id
    assert pay_online(client, loan, first_id).status_code == 303
    second = pay_online(client, loan, first_id)    # same installment again
    assert second.status_code == 409
    assert len(db.scalars(select(Payment)).all()) == 1
    assert reload(db, loan.id).installments[1].status == InstallmentStatus.DUE


def test_cannot_pay_out_of_order(client, db, loan):
    third = loan.installments[2].id
    assert pay_online(client, loan, third).status_code == 409
    assert db.scalars(select(Payment)).first() is None


def test_paying_every_emi_closes_the_loan(client, db, loan):
    for _ in range(3):
        assert pay_online(client, reload(db, loan.id)).status_code == 303
    loan = reload(db, loan.id)
    assert loan.status == LoanStatus.CLOSED
    assert loan.closed_at is not None
    assert loan.outstanding_paise == 0
    assert sum(p.amount_paise for p in loan.payments) == loan.total_payable_paise
    # Nothing left: the gateway sends you back, and a POST is refused.
    assert client.get(f"/loans/{loan.id}/pay", follow_redirects=False).status_code == 303
    assert pay_online(client, loan, loan.installments[0].id).status_code == 409


def test_cannot_pay_a_loan_that_is_not_disbursed(client, db, customer):
    form = LoanApplicationForm(amount="30000", tenure_months="3", monthly_income="40000", existing_emis="0")
    offered = apply_for_loan(db, customer, form)
    assert client.post(f"/loans/{offered.id}/pay", data={"installment_id": 1}).status_code == 409


def test_other_customer_cannot_pay_or_see_gateway(client, db, make_user, login, loan):
    client.cookies.clear()
    make_user(OTHER, Role.CUSTOMER)
    login(OTHER)
    assert client.get(f"/loans/{loan.id}/pay").status_code == 404
    assert pay_online(client, loan).status_code == 404
    assert db.scalars(select(Payment)).first() is None


def test_overdue_installment_is_shown(client, db, loan):
    loan.installments[0].due_date = utcnow().date() - timedelta(days=3)
    db.commit()
    assert "overdue" in client.get(f"/loans/{loan.id}").text
    assert "overdue" in client.get("/dashboard").text


# ---------- Cash at the branch ----------

def test_agent_finds_loan_by_id(client, make_user, login, loan):
    as_agent(client, make_user, login)
    page = client.get(f"/staff/collect?loan_id={loan.id}")
    assert page.status_code == 200
    assert "Ravi Demo" in page.text
    assert "XXXXXX3210" in page.text


def test_agent_sees_no_kyc_data(client, make_user, login, loan):
    as_agent(client, make_user, login)
    page = client.get(f"/staff/collect?loan_id={loan.id}").text
    for secret in ["ABCPE1234F", "2346", "234123412346", CUSTOMER, "/kyc/documents"]:
        assert secret not in page


def test_agent_records_cash_into_the_same_ledger(client, db, make_user, login, loan):
    pay_online(client, loan)                       # EMI #1 online by the customer
    as_agent(client, make_user, login)
    response = pay_cash(client, reload(db, loan.id))   # EMI #2 in cash at the branch
    assert response.status_code == 303

    loan = reload(db, loan.id)
    methods = [(p.installment.number, p.method, p.recorded_by.phone) for p in loan.payments]
    assert methods == [(1, "online", CUSTOMER), (2, "cash", AGENT)]
    assert loan.payments[1].reference.startswith("DEMO-CASH-")


def test_cash_amount_must_match_exactly(client, db, make_user, login, loan):
    as_agent(client, make_user, login)
    response = pay_cash(client, loan, amount="100")
    assert response.status_code == 422
    assert "does not match" in response.text
    assert db.scalars(select(Payment)).first() is None


def test_cash_amount_must_be_a_number(client, db, make_user, login, loan):
    as_agent(client, make_user, login)
    response = pay_cash(client, loan, amount="ten thousand")
    assert response.status_code == 422
    assert db.scalars(select(Payment)).first() is None


def test_agent_unknown_or_bad_loan_id(client, make_user, login):
    as_agent(client, make_user, login)
    assert client.get("/staff/collect?loan_id=999").status_code == 404
    assert client.get("/staff/collect?loan_id=abc").status_code == 422
    assert client.get("/staff/collect").status_code == 200


@pytest.mark.parametrize("role", [Role.SUPPORT, Role.FINANCE, Role.IT_ADMIN, Role.CUSTOMER])
def test_only_branch_agents_collect_cash(client, db, make_user, login, loan, role):
    client.cookies.clear()
    make_user("9000000009", role)
    login("9000000009")
    assert client.get(f"/staff/collect?loan_id={loan.id}").status_code == 403
    assert pay_cash(client, loan).status_code == 403
    assert db.scalars(select(Payment)).first() is None


def test_finance_sees_collected_totals(client, db, make_user, login, loan):
    pay_online(client, loan)
    client.cookies.clear()
    login("9000000002")  # finance user made by the `loan` fixture
    book = client.get("/staff/loans").text
    first_emi = reload(db, loan.id).installments[0].amount_paise
    from app.services.money import format_inr
    assert format_inr(first_emi) in book
    assert "Payments ledger" in client.get(f"/staff/loans/{loan.id}").text


# ---------- Amount parsing ----------

@pytest.mark.parametrize("text, paise", [
    ("9168", 916800), ("9,167.99", 916799), ("₹9168.5", 916850), (" 0.05 ", 5),
])
def test_parse_amount_paise(text, paise):
    assert parse_amount_paise(text) == paise


@pytest.mark.parametrize("bad", ["", "abc", "12.345", "-5", "1e3"])
def test_parse_amount_paise_rejects(bad):
    with pytest.raises(ValueError):
        parse_amount_paise(bad)
