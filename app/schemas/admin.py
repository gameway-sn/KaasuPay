"""Validation for the IT admin's "new staff account" form."""
from pydantic import BaseModel, field_validator

from app.models import STAFF_ROLES
from app.schemas.auth import check_phone


class StaffCreateForm(BaseModel):
    full_name: str
    phone: str
    role: str

    @field_validator("full_name")
    @classmethod
    def name_length(cls, value: str) -> str:
        value = value.strip()
        if not 2 <= len(value) <= 100:
            raise ValueError("Name must be 2 to 100 characters.")
        return value

    @field_validator("phone")
    @classmethod
    def phone_format(cls, value: str) -> str:
        return check_phone(value)

    @field_validator("role")
    @classmethod
    def staff_role_only(cls, value: str) -> str:
        if value not in STAFF_ROLES:
            # Customers register themselves; this screen only makes staff.
            raise ValueError("Choose one of the staff roles.")
        return value
