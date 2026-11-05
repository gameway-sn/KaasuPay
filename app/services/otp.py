"""One-time codes: create, "send" (print to console), and check.

Rules (from CLAUDE.md): 6 digits, valid 5 minutes, locked after 3 wrong tries.
Plus (Phase 5): at most 3 codes per phone in 15 minutes, so the "3 tries"
rule can't be dodged by asking for a fresh code again and again.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta
from enum import Enum

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import utcnow
from app.models import OtpCode

OTP_VALID_MINUTES = 5
MAX_ATTEMPTS = 3
MAX_CODES_PER_WINDOW = 3
WINDOW_MINUTES = 15


class OtpRateLimited(Exception):
    """Too many codes asked for this phone recently."""


class OtpResult(Enum):
    OK = "ok"
    WRONG = "wrong"
    EXPIRED = "expired"
    LOCKED = "locked"
    NOT_FOUND = "not_found"


def generate_code() -> str:
    """6 random digits, e.g. '048213'. `secrets` is safe for security codes; `random` is not."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash(code: str) -> str:
    # HMAC with the app's secret key. Without the key, a stolen database
    # can't be used to try all 1,000,000 codes. (A real system would use a
    # separate key just for this.)
    return hmac.new(settings.jwt_secret_key.encode(), code.encode(), hashlib.sha256).hexdigest()


def send_otp(db: Session, phone: str) -> str:
    """Make a new code for this phone, cancel any older ones, and "send" it."""
    recent = db.scalar(
        select(func.count()).select_from(OtpCode).where(
            OtpCode.phone == phone,
            OtpCode.created_at > utcnow() - timedelta(minutes=WINDOW_MINUTES),
        )
    )
    if recent >= MAX_CODES_PER_WINDOW:
        raise OtpRateLimited(
            f"Too many codes asked for this phone. Please wait {WINDOW_MINUTES} minutes and try again."
        )

    db.execute(
        update(OtpCode)
        .where(OtpCode.phone == phone, OtpCode.used.is_(False))
        .values(used=True)
    )
    code = generate_code()
    db.add(
        OtpCode(
            phone=phone,
            code_hash=_hash(code),
            expires_at=utcnow() + timedelta(minutes=OTP_VALID_MINUTES),
        )
    )
    db.commit()

    # Demo "SMS gateway": print to the server console.
    line = "=" * 52
    print(f"\n{line}\n [DEMO SMS] OTP for {phone}: {code}   (valid {OTP_VALID_MINUTES} min)\n{line}\n", flush=True)
    return code


def verify_otp(db: Session, phone: str, code: str) -> tuple[OtpResult, int]:
    """Check a code. Returns (result, tries_left).

    A wrong try is saved straight away. On success the code is marked used,
    and the caller commits that together with its own changes.
    """
    otp = db.scalars(
        select(OtpCode)
        .where(OtpCode.phone == phone, OtpCode.used.is_(False))
        .order_by(OtpCode.id.desc())
    ).first()

    if otp is None:
        return OtpResult.NOT_FOUND, 0
    if otp.attempts >= MAX_ATTEMPTS:
        return OtpResult.LOCKED, 0
    if utcnow() > otp.expires_at:
        return OtpResult.EXPIRED, 0

    # compare_digest takes the same time however many characters match.
    if not hmac.compare_digest(_hash(code), otp.code_hash):
        otp.attempts += 1
        db.commit()
        return OtpResult.WRONG, MAX_ATTEMPTS - otp.attempts

    otp.used = True
    return OtpResult.OK, 0
