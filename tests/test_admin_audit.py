"""Phase 5: lockouts, OTP limits, the audit log, and IT admin staff management."""
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.db import utcnow
from app.models import AuditEvent, AuditTamperError, KycRecord, KycStatus, Role, User
from app.schemas.loans import LoanApplicationForm
from app.services import otp as otp_service
from app.services.crypto import encrypt
from app.services.loans import accept_offer, apply_for_loan

CUSTOMER = "9876543210"
SUPPORT = "9000000001"
FINANCE = "9000000002"
ADMIN = "9000000003"
AGENT = "9000000004"


def events(db, action=None):
    db.expire_all()
    query = select(AuditEvent).order_by(AuditEvent.id)
    if action:
        query = query.where(AuditEvent.action == action)
    return db.scalars(query).all()


def switch_to(client, login, phone):
    client.cookies.clear()
    return login(phone)


def get_user(db, phone):
    db.expire_all()
    return db.scalars(select(User).where(User.phone == phone)).first()


@pytest.fixture
def staff(make_user):
    return {
        "support": make_user(SUPPORT, Role.SUPPORT, full_name="Sue Support"),
        "finance": make_user(FINANCE, Role.FINANCE, full_name="Fin Finance"),
        "admin": make_user(ADMIN, Role.IT_ADMIN, full_name="Ian Admin"),
        "agent": make_user(AGENT, Role.BRANCH_AGENT, full_name="Bea Agent"),
    }


@pytest.fixture
def customer_with_kyc(db, make_user):
    user = make_user(CUSTOMER, Role.CUSTOMER, full_name="Asha Demo")
    db.add(KycRecord(user_id=user.id, status=KycStatus.SUBMITTED, pan="ABCPE1234F",
                     aadhaar_encrypted=encrypt("234123412346"), aadhaar_last4="2346", submitted_at=utcnow()))
    db.commit()
    return user


# ======================= Login lockout =======================

def test_five_wrong_passwords_lock_the_account(make_user, login, db):
    make_user(CUSTOMER)
    for _ in range(4):
        assert login(CUSTOMER, "wrong-password").status_code == 401
    fifth = login(CUSTOMER, "wrong-password")
    assert fifth.status_code == 423
    assert "locked for 15 minutes" in fifth.text

    # Even the right password is refused while locked.
    assert login(CUSTOMER).status_code == 423
    assert get_user(db, CUSTOMER).is_locked
    assert len(events(db, "auth.locked")) == 1


def test_lock_ends_after_15_minutes(make_user, login, db):
    make_user(CUSTOMER)
    for _ in range(5):
        login(CUSTOMER, "wrong-password")
    user = get_user(db, CUSTOMER)
    user.locked_until = utcnow() - timedelta(seconds=1)  # pretend 15 minutes passed
    db.commit()
    assert login(CUSTOMER).status_code == 303
    assert get_user(db, CUSTOMER).locked_until is None


def test_successful_login_resets_the_counter(make_user, login, db):
    make_user(CUSTOMER)
    for _ in range(4):
        login(CUSTOMER, "wrong-password")
    assert login(CUSTOMER).status_code == 303
    assert get_user(db, CUSTOMER).failed_login_count == 0
    for _ in range(4):                         # 4 more wrong: still not locked
        login(CUSTOMER, "wrong-password")
    assert not get_user(db, CUSTOMER).is_locked


def test_unknown_phone_is_logged_but_cannot_be_locked(login, db):
    for _ in range(6):
        assert login("9999999999", "guess").status_code == 401
    failed = events(db, "auth.login_failed")
    assert len(failed) == 6
    assert "XXXXXX9999" in failed[0].detail     # phone masked even in the log


# ======================= OTP request limit =======================

def test_fourth_otp_request_in_15_minutes_is_refused(client, monkeypatch, db):
    monkeypatch.setattr(otp_service, "generate_code", lambda: "123456")
    data = {"phone": CUSTOMER, "full_name": "Asha Demo"}
    for _ in range(3):
        assert client.post("/register", data=data, follow_redirects=False).status_code == 303
    fourth = client.post("/register", data=data, follow_redirects=False)
    assert fourth.status_code == 429
    assert "Too many codes" in fourth.text


# ======================= Audit log =======================

def test_successful_login_and_logout_are_logged(client, make_user, login, db):
    user = make_user(CUSTOMER)
    login(CUSTOMER)
    client.post("/logout")
    actions = [(e.action, e.actor_id) for e in events(db)]
    assert ("auth.login", user.id) in actions
    assert ("auth.logout", user.id) in actions
    assert events(db, "auth.login")[0].ip == "testclient"   # IP captured by the middleware


def test_support_viewing_kyc_is_logged(client, login, db, staff, customer_with_kyc):
    kyc = db.scalars(select(KycRecord)).first()
    switch_to(client, login, SUPPORT)
    client.get(f"/staff/kyc/{kyc.id}")
    client.get(f"/staff/kyc/{kyc.id}")     # each view is a separate line

    views = events(db, "kyc.view")
    assert len(views) == 2
    assert views[0].actor_id == staff["support"].id
    assert views[0].customer_id == customer_with_kyc.id


def test_kyc_approval_is_logged(client, login, db, staff, customer_with_kyc):
    kyc = db.scalars(select(KycRecord)).first()
    switch_to(client, login, SUPPORT)
    client.post(f"/staff/kyc/{kyc.id}/approve")
    (event,) = events(db, "kyc.approved")
    assert event.actor_id == staff["support"].id and event.customer_id == customer_with_kyc.id


def test_money_actions_are_logged(client, login, db, staff, customer_with_kyc):
    kyc = db.scalars(select(KycRecord)).first()
    kyc.status = KycStatus.APPROVED
    db.commit()
    loan = apply_for_loan(db, customer_with_kyc, LoanApplicationForm(
        amount="30000", tenure_months="3", monthly_income="40000", existing_emis="0"))
    accept_offer(db, loan)

    switch_to(client, login, FINANCE)
    client.post(f"/staff/loans/{loan.id}/disburse")
    switch_to(client, login, AGENT)
    db.expire_all()
    nxt = db.get(type(loan), loan.id).next_installment
    client.post(f"/staff/collect/{loan.id}",
                data={"installment_id": nxt.id, "amount": f"{nxt.amount_paise / 100:.2f}"})

    (disburse,) = events(db, "loan.disburse")
    assert disburse.actor_id == staff["finance"].id
    assert "₹30,000.00" in disburse.detail
    (cash,) = events(db, "payment.cash")
    assert cash.actor_id == staff["agent"].id
    assert cash.customer_id == customer_with_kyc.id
    assert "DEMO-CASH-" in cash.detail
    assert [e.action for e in events(db) if e.action.startswith("loan.")] == [
        "loan.apply", "loan.accept", "loan.disburse"]


def test_access_denied_is_logged(client, login, db, staff):
    switch_to(client, login, SUPPORT)
    assert client.post("/staff/loans/1/disburse").status_code == 403
    (denied,) = events(db, "access.denied")
    assert denied.actor_id == staff["support"].id
    assert denied.detail == "POST /staff/loans/1/disburse"


def test_audit_log_cannot_be_changed_through_the_app(db, staff):
    switch_event = AuditEvent(action="test.event", detail="original")
    db.add(switch_event)
    db.commit()

    switch_event.detail = "edited"
    with pytest.raises(AuditTamperError):
        db.commit()
    db.rollback()

    db.delete(db.get(AuditEvent, switch_event.id))
    with pytest.raises(AuditTamperError):
        db.commit()
    db.rollback()


def test_audit_log_cannot_be_changed_with_raw_sql(db):
    db.add(AuditEvent(action="test.event", detail="original"))
    db.commit()
    for sql in ["UPDATE audit_events SET detail = 'edited'", "DELETE FROM audit_events"]:
        with pytest.raises(DatabaseError, match="append-only"):
            db.execute(text(sql))
        db.rollback()
    assert events(db)[0].detail == "original"


# ======================= IT admin: staff accounts =======================

def test_admin_creates_staff_who_can_log_in(client, login, db, staff):
    switch_to(client, login, ADMIN)
    page = client.post("/staff/admin/staff", data={
        "full_name": "New Support", "phone": "9000000011", "role": "support"})
    assert page.status_code == 200
    assert "shown only once" in page.text
    password = page.text.split('<code class="big">')[1].split("</code>")[0]

    new = get_user(db, "9000000011")
    assert new.role == Role.SUPPORT
    assert password not in new.password_hash      # stored hashed

    client.cookies.clear()
    assert login("9000000011", password).status_code == 303
    assert len(events(db, "admin.staff_create")) == 1


@pytest.mark.parametrize("data, message", [
    ({"full_name": "X Y", "phone": "9000000011", "role": "customer"}, "staff roles"),
    ({"full_name": "X Y", "phone": "12345", "role": "support"}, "start with 6, 7, 8 or 9"),
    ({"full_name": "X Y", "phone": SUPPORT, "role": "support"}, "already has an account"),
])
def test_admin_create_staff_validation(client, login, db, staff, data, message):
    switch_to(client, login, ADMIN)
    response = client.post("/staff/admin/staff", data=data)
    assert response.status_code in (409, 422)
    assert message in response.text


def test_deactivated_staff_is_thrown_out_at_once(client, login, db, staff):
    # Support is logged in on one "browser"...
    from fastapi.testclient import TestClient
    from app.main import app
    support_browser = TestClient(app)
    support_browser.post("/login", data={"phone": SUPPORT, "password": "Passw0rd!"})
    assert support_browser.get("/staff/kyc").status_code == 200

    # ...IT admin deactivates them on another.
    switch_to(client, login, ADMIN)
    client.post(f"/staff/admin/staff/{staff['support'].id}/deactivate")

    assert support_browser.get("/staff/kyc", follow_redirects=False).status_code == 303   # out
    assert support_browser.post("/login", data={"phone": SUPPORT, "password": "Passw0rd!"},
                                follow_redirects=False).status_code == 401

    client.post(f"/staff/admin/staff/{staff['support'].id}/activate")
    assert get_user(db, SUPPORT).is_active


def test_admin_unlocks_a_locked_staff_member(client, login, db, staff):
    for _ in range(5):
        login(FINANCE, "wrong-password")
    assert get_user(db, FINANCE).is_locked
    switch_to(client, login, ADMIN)
    assert "Unlock" in client.get("/staff/admin/staff").text
    client.post(f"/staff/admin/staff/{staff['finance'].id}/unlock")
    client.cookies.clear()
    assert login(FINANCE).status_code == 303


def test_admin_resets_a_password(client, login, db, staff):
    switch_to(client, login, ADMIN)
    page = client.post(f"/staff/admin/staff/{staff['agent'].id}/reset-password")
    password = page.text.split('<code class="big">')[1].split("</code>")[0]
    client.cookies.clear()
    assert login(AGENT).status_code == 401          # old password no longer works
    assert login(AGENT, password).status_code == 303


def test_admin_cannot_deactivate_themselves(client, login, db, staff):
    switch_to(client, login, ADMIN)
    response = client.post(f"/staff/admin/staff/{staff['admin'].id}/deactivate")
    assert response.status_code == 409
    assert get_user(db, ADMIN).is_active


def test_admin_cannot_manage_customers(client, login, db, staff, customer_with_kyc):
    switch_to(client, login, ADMIN)
    assert client.post(f"/staff/admin/staff/{customer_with_kyc.id}/deactivate").status_code == 404
    assert get_user(db, CUSTOMER).is_active


@pytest.mark.parametrize("phone", [SUPPORT, FINANCE, AGENT])
def test_only_it_admin_can_use_admin_pages(client, login, db, staff, phone):
    switch_to(client, login, phone)
    assert client.get("/staff/admin/staff").status_code == 403
    assert client.get("/staff/admin/audit").status_code == 403
    assert client.post("/staff/admin/staff", data={"full_name": "X", "phone": "9000000099",
                                                   "role": "it_admin"}).status_code == 403


def test_customer_cannot_use_admin_pages(client, login, make_user):
    make_user(CUSTOMER)
    login(CUSTOMER)
    assert client.get("/staff/admin/audit").status_code == 403


def test_admin_pages_without_login_redirect(client):
    for url in ["/staff/admin/staff", "/staff/admin/audit"]:
        response = client.get(url, follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/login"


def test_separation_of_duties_it_admin_cannot_approve_kyc_or_disburse(client, login, db, staff, customer_with_kyc):
    kyc = db.scalars(select(KycRecord)).first()
    switch_to(client, login, ADMIN)
    assert client.get("/staff/kyc").status_code == 403
    assert client.post(f"/staff/kyc/{kyc.id}/approve").status_code == 403
    assert client.post("/staff/loans/1/disburse").status_code == 403
    assert client.get("/staff/collect").status_code == 403


# ======================= Audit viewer =======================

def test_admin_reads_who_viewed_a_customers_kyc(client, login, db, staff, customer_with_kyc):
    kyc = db.scalars(select(KycRecord)).first()
    switch_to(client, login, SUPPORT)
    client.get(f"/staff/kyc/{kyc.id}")

    switch_to(client, login, ADMIN)
    page = client.get(f"/staff/admin/audit?category=kyc.&customer_id={customer_with_kyc.id}")
    assert page.status_code == 200
    assert "Sue Support" in page.text
    assert "kyc.view" in page.text
    assert "auth.login" not in page.text            # filtered out
    assert len(events(db, "admin.audit_view")) == 1  # reading the log is logged too
