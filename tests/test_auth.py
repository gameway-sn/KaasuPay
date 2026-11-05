"""Phase 1: registration with OTP, passwords, login and logout."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import utcnow
from app.models import OtpCode, User
from app.services import otp as otp_service

PHONE = "9876543210"
CODE = "123456"
PASSWORD = "Passw0rd!"


@pytest.fixture(autouse=True)
def fixed_otp(monkeypatch):
    """In tests the "random" OTP is always 123456, so we know what to type."""
    monkeypatch.setattr(otp_service, "generate_code", lambda: CODE)


def start_registration(client, phone=PHONE, name="Asha Demo"):
    return client.post("/register", data={"phone": phone, "full_name": name}, follow_redirects=False)


def submit_code(client, code, phone=PHONE, password=PASSWORD):
    return client.post(
        "/register/verify",
        data={"phone": phone, "otp": code, "password": password, "confirm_password": password},
        follow_redirects=False,
    )


def get_user(db, phone=PHONE):
    db.expire_all()  # forget cached rows, read fresh from the database
    return db.scalars(select(User).where(User.phone == phone)).first()


def test_full_registration_then_login(client, db, login):
    response = start_registration(client)
    assert response.status_code == 303
    assert response.headers["location"] == f"/register/verify?phone={PHONE}"

    response = submit_code(client, CODE)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?registered=1"

    response = login(PHONE, PASSWORD)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"

    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "Welcome, Asha Demo" in page.text


def test_password_is_stored_hashed_not_plain(client, db):
    start_registration(client)
    submit_code(client, CODE)
    user = get_user(db)
    assert user.password_hash != PASSWORD
    assert user.password_hash.startswith("$argon2")


def test_otp_is_stored_hashed_not_plain(client, db):
    start_registration(client)
    otp = db.scalars(select(OtpCode)).first()
    assert otp.code_hash != CODE
    assert CODE not in otp.code_hash


@pytest.mark.parametrize("bad_phone", ["5876543210", "98765", "98765432101", "98765abcde"])
def test_register_rejects_bad_phone(client, db, bad_phone):
    response = start_registration(client, phone=bad_phone)
    assert response.status_code == 422
    assert "start with 6, 7, 8 or 9" in response.text
    assert db.scalars(select(User)).first() is None


def test_fourth_wrong_otp_is_locked(client, db):
    start_registration(client)

    assert "2 tries left" in submit_code(client, "000000").text
    assert "1 tries left" in submit_code(client, "000001").text
    assert "No tries left" in submit_code(client, "000002").text

    # 4th try is refused even with the RIGHT code: the OTP is locked.
    response = submit_code(client, CODE)
    assert response.status_code == 400
    assert "locked" in response.text
    assert get_user(db).password_hash is None


def test_expired_otp_is_rejected(client, db):
    start_registration(client)
    otp = db.scalars(select(OtpCode)).first()
    otp.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()

    response = submit_code(client, CODE)
    assert "expired" in response.text
    assert get_user(db).password_hash is None


def test_new_code_replaces_old_code(client, db):
    start_registration(client)
    start_registration(client)  # asks for a second code
    active = db.scalars(select(OtpCode).where(OtpCode.used.is_(False))).all()
    assert len(active) == 1


def test_bad_password_does_not_use_an_otp_try(client, db):
    start_registration(client)
    response = submit_code(client, CODE, password="short")
    assert response.status_code == 422
    otp = db.scalars(select(OtpCode)).first()
    assert otp.attempts == 0


def test_cannot_register_same_phone_twice(client, make_user):
    make_user(PHONE)
    response = start_registration(client)
    assert response.status_code == 409
    assert "already registered" in response.text


def test_wrong_password_gives_generic_error(make_user, login):
    make_user(PHONE)
    response = login(PHONE, "wrong-password")
    assert response.status_code == 401
    assert "Wrong phone number or password." in response.text
    assert "access_token" not in response.cookies


def test_unknown_phone_gives_same_generic_error(login):
    response = login("9999999999", "whatever123")
    assert response.status_code == 401
    assert "Wrong phone number or password." in response.text


def test_login_cookie_is_httponly_and_samesite(make_user, login):
    make_user(PHONE)
    response = login(PHONE)
    cookie_header = response.headers["set-cookie"].lower()
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header


def test_logout_ends_the_session(client, make_user, login):
    make_user(PHONE)
    login(PHONE)
    assert client.get("/dashboard").status_code == 200

    client.post("/logout")
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_tampered_cookie_is_treated_as_logged_out(client, make_user, login):
    make_user(PHONE)
    login(PHONE)
    token = client.cookies.get("access_token")
    client.cookies.set("access_token", token[:-3] + "abc")  # change the signature
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
