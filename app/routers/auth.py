"""Registration (phone -> OTP -> password), login and logout."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_optional_user
from app.models import Role, User
from app.schemas.auth import PHONE_RE, RegisterForm, VerifyForm
from app.schemas.common import error_messages
from app.security import clear_login_cookie, hash_password, set_login_cookie
from app.services.audit import record
from app.services.login import LOCK_MINUTES, LoginResult, attempt_login
from app.services.otp import OtpRateLimited, OtpResult, send_otp, verify_otp
from app.templating import render

router = APIRouter()


# ---------- Step 1: phone number + name ----------

@router.get("/register")
def register_page(request: Request, user: User | None = Depends(get_optional_user)):
    return render(request, "auth/register.html", {"user": user, "form": {}, "errors": []})


@router.post("/register")
def register_submit(
    request: Request,
    phone: str = Form(""),
    full_name: str = Form(""),
    db: Session = Depends(get_db),
):
    typed = {"phone": phone, "full_name": full_name}
    try:
        form = RegisterForm(**typed)
    except ValidationError as exc:
        return render(request, "auth/register.html",
                      {"form": typed, "errors": error_messages(exc)}, status_code=422)

    user = db.scalars(select(User).where(User.phone == form.phone)).first()
    if user is not None and user.password_hash is not None:
        return render(request, "auth/register.html",
                      {"form": typed, "errors": ["This phone number is already registered. Please log in."]},
                      status_code=409)

    if user is None:
        # Account exists but can't log in until the OTP step sets a password.
        user = User(phone=form.phone, full_name=form.full_name, role=Role.CUSTOMER)
        db.add(user)
    else:
        user.full_name = form.full_name  # unfinished earlier attempt: start again
    db.commit()

    try:
        send_otp(db, form.phone)
    except OtpRateLimited as exc:
        return render(request, "auth/register.html", {"form": typed, "errors": [str(exc)]}, status_code=429)
    return RedirectResponse(f"/register/verify?phone={form.phone}", status_code=303)


# ---------- Step 2: OTP + choose a password ----------

@router.get("/register/verify")
def verify_page(request: Request, phone: str = ""):
    if not PHONE_RE.fullmatch(phone):
        return RedirectResponse("/register", status_code=303)
    return render(request, "auth/verify.html", {"phone": phone, "errors": []})


OTP_MESSAGES = {
    OtpResult.EXPIRED: "This code has expired. Register again to get a new code.",
    OtpResult.LOCKED: "Too many wrong codes, so this code is locked. Register again to get a new code.",
    OtpResult.NOT_FOUND: "There is no active code for this phone. Register again to get a new code.",
}


@router.post("/register/verify")
def verify_submit(
    request: Request,
    phone: str = Form(""),
    otp: str = Form(""),
    password: str = Form(""),
    confirm_password: str = Form(""),
    db: Session = Depends(get_db),
):
    def show_error(message_list, status_code=400):
        return render(request, "auth/verify.html",
                      {"phone": phone, "errors": message_list}, status_code=status_code)

    # Check the form first, so a typo in the password doesn't use up an OTP try.
    try:
        form = VerifyForm(phone=phone, otp=otp, password=password, confirm_password=confirm_password)
    except ValidationError as exc:
        return show_error(error_messages(exc), status_code=422)

    user = db.scalars(
        select(User).where(User.phone == form.phone, User.password_hash.is_(None))
    ).first()
    if user is None:
        return show_error(["No registration is waiting for this phone. Please register again."])

    result, tries_left = verify_otp(db, form.phone, form.otp)
    if result is not OtpResult.OK:
        record(db, None, "auth.otp_failed", target_type="user", target_id=user.id,
               detail=f"{result.value}, {tries_left} tries left")
        db.commit()
    if result is OtpResult.WRONG:
        if tries_left:
            return show_error([f"Wrong code. {tries_left} tries left."])
        return show_error(["Wrong code. No tries left. Register again to get a new code."])
    if result is not OtpResult.OK:
        return show_error([OTP_MESSAGES[result]])

    user.password_hash = hash_password(form.password)
    user.phone_verified = True
    record(db, user, "auth.register", target_type="user", target_id=user.id, customer_id=user.id)
    db.commit()  # saves the password, marks the OTP used, and logs it, together
    return RedirectResponse("/login?registered=1", status_code=303)


# ---------- Login / logout ----------

@router.get("/login")
def login_page(request: Request, registered: bool = False, user: User | None = Depends(get_optional_user)):
    if user is not None:
        return RedirectResponse(user.home_url, status_code=303)
    return render(request, "auth/login.html", {"registered": registered, "phone": "", "errors": []})


@router.post("/login")
def login_submit(
    request: Request,
    phone: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    result, user = attempt_login(db, phone, password)

    if result is LoginResult.LOCKED:
        # 423 = "Locked". Even the right password is refused until the lock ends.
        return render(request, "auth/login.html", {"phone": phone, "errors": [
            f"Too many wrong passwords. This account is locked for {LOCK_MINUTES} minutes."
        ]}, status_code=423)
    if result is LoginResult.BAD:
        # Same message for "no such phone" and "wrong password":
        # don't tell an attacker which phone numbers are registered.
        return render(request, "auth/login.html",
                      {"phone": phone, "errors": ["Wrong phone number or password."]},
                      status_code=401)

    response = RedirectResponse(user.home_url, status_code=303)
    set_login_cookie(response, user.id)
    return response


@router.post("/logout")
def logout(user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    if user is not None:
        record(db, user, "auth.logout", target_type="user", target_id=user.id)
        db.commit()
    response = RedirectResponse("/", status_code=303)
    clear_login_cookie(response)
    return response
