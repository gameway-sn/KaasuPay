"""One-time codes sent by "SMS" during registration."""
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class OtpCode(Base):
    __tablename__ = "otp_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(10), index=True)

    # We store a keyed hash (HMAC) of the code, never the code itself.
    code_hash: Mapped[str] = mapped_column(String(64))

    expires_at: Mapped[datetime]
    attempts: Mapped[int] = mapped_column(default=0)   # wrong tries so far
    used: Mapped[bool] = mapped_column(default=False)  # used, or replaced by a newer code
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
