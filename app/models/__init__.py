"""All models, imported in one place so Alembic and the app see every table."""
from app.models.audit import AuditEvent, AuditTamperError
from app.models.kyc import DOC_LABELS, DocKind, KycDocument, KycRecord, KycStatus
from app.models.loan import OPEN_LOAN_STATUSES, Installment, InstallmentStatus, Loan, LoanStatus
from app.models.otp import OtpCode
from app.models.payment import Payment, PaymentMethod
from app.models.user import STAFF_ROLES, Role, User

__all__ = [
    "AuditEvent", "AuditTamperError",
    "DOC_LABELS", "DocKind", "KycDocument", "KycRecord", "KycStatus",
    "OPEN_LOAN_STATUSES", "Installment", "InstallmentStatus", "Loan", "LoanStatus",
    "OtpCode",
    "Payment", "PaymentMethod",
    "Role", "STAFF_ROLES", "User",
]
