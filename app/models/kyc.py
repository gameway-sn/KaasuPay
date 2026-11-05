"""KYC: one record per customer, plus the three uploaded documents."""
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow
from app.models.user import User
from app.services.crypto import mask_aadhaar


class KycStatus(StrEnum):
    DRAFT = "draft"          # not submitted yet
    SUBMITTED = "submitted"  # waiting for support
    APPROVED = "approved"
    REJECTED = "rejected"    # customer can fix and resubmit


class DocKind(StrEnum):
    ID_FRONT = "id_front"
    ID_BACK = "id_back"
    SELFIE = "selfie"


DOC_LABELS = {
    DocKind.ID_FRONT: "ID card (front)",
    DocKind.ID_BACK: "ID card (back)",
    DocKind.SELFIE: "Selfie",
}


class KycRecord(Base):
    __tablename__ = "kyc_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)  # one KYC per customer
    status: Mapped[str] = mapped_column(String(20), default=KycStatus.DRAFT, index=True)

    pan: Mapped[str] = mapped_column(String(10))

    # The full Aadhaar exists only as Fernet ciphertext ("gAAAAAB...").
    aadhaar_encrypted: Mapped[str] = mapped_column(String(255))
    # Last 4 digits, kept so screens can show "XXXX XXXX 2346" without decrypting.
    aadhaar_last4: Mapped[str] = mapped_column(String(4))

    rejection_reason: Mapped[str | None] = mapped_column(String(300))
    submitted_at: Mapped[datetime | None]
    reviewed_at: Mapped[datetime | None]
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    # Two links to the users table, so we say which column each one uses.
    user: Mapped[User] = relationship(foreign_keys=[user_id])
    reviewed_by: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_id])
    documents: Mapped[list["KycDocument"]] = relationship(
        back_populates="kyc", cascade="all, delete-orphan", order_by="KycDocument.id"
    )

    @property
    def aadhaar_masked(self) -> str:
        return mask_aadhaar(self.aadhaar_last4)


class KycDocument(Base):
    __tablename__ = "kyc_documents"
    __table_args__ = (UniqueConstraint("kyc_id", "kind", name="uq_kyc_documents_kyc_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kyc_id: Mapped[int] = mapped_column(ForeignKey("kyc_records.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))

    # Random name on disk, e.g. "9f2c41...e1.png". Never the customer's file name.
    stored_name: Mapped[str] = mapped_column(String(64), unique=True)
    content_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int]
    uploaded_at: Mapped[datetime] = mapped_column(default=utcnow)

    kyc: Mapped[KycRecord] = relationship(back_populates="documents")

    @property
    def label(self) -> str:
        return DOC_LABELS[self.kind]

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")
