"""Validation for the loan application form."""
from pydantic import BaseModel, field_validator

from app.services.decision import (
    MAX_AMOUNT_RUPEES, MAX_TENURE_MONTHS, MIN_AMOUNT_RUPEES, MIN_TENURE_MONTHS,
)
from app.services.money import parse_rupees

MAX_INCOME_RUPEES = 1_00_00_000  # ₹1 crore a month: anything above is surely a typo


class LoanApplicationForm(BaseModel):
    """All amounts here are whole RUPEES; the service turns them into paise."""

    amount: int
    tenure_months: int
    monthly_income: int
    existing_emis: int

    @field_validator("amount", "monthly_income", "existing_emis", mode="before")
    @classmethod
    def clean_rupees(cls, value) -> int:
        return parse_rupees(value)

    @field_validator("tenure_months", mode="before")
    @classmethod
    def clean_months(cls, value) -> int:
        value = str(value).strip()
        if not value.isascii() or not value.isdigit():
            raise ValueError("Tenure must be a whole number of months.")
        return int(value)

    @field_validator("amount")
    @classmethod
    def amount_range(cls, value: int) -> int:
        if not MIN_AMOUNT_RUPEES <= value <= MAX_AMOUNT_RUPEES:
            raise ValueError("Loan amount must be between ₹5,000 and ₹2,00,000.")
        return value

    @field_validator("tenure_months")
    @classmethod
    def tenure_range(cls, value: int) -> int:
        if not MIN_TENURE_MONTHS <= value <= MAX_TENURE_MONTHS:
            raise ValueError("Tenure must be between 3 and 24 months.")
        return value

    @field_validator("monthly_income")
    @classmethod
    def income_range(cls, value: int) -> int:
        if not 1 <= value <= MAX_INCOME_RUPEES:
            raise ValueError("Monthly income must be between ₹1 and ₹1,00,00,000.")
        return value

    @field_validator("existing_emis")
    @classmethod
    def existing_range(cls, value: int) -> int:
        if value > MAX_INCOME_RUPEES:
            raise ValueError("Existing EMIs look too large. Enter 0 if you have none.")
        return value
