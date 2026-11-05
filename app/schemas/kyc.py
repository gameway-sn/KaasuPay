"""Validation for the KYC form and the support reviewer's reject form."""
import re

from pydantic import BaseModel, field_validator

from app.services import verhoeff

PAN_RE = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]")
AADHAAR_RE = re.compile(r"[2-9][0-9]{11}")


def check_pan(value: str) -> str:
    value = value.strip().upper()
    if not PAN_RE.fullmatch(value):
        raise ValueError("PAN must look like ABCPE1234F: 5 letters, 4 digits, 1 letter.")
    if value[3] != "P":
        # The 4th letter says who holds the PAN: P = individual person, C = company, ...
        raise ValueError("The 4th letter of a personal PAN must be P.")
    return value


def check_aadhaar(value: str) -> str:
    # People type Aadhaar in groups of four ("2341 2341 2346"), so drop spaces and dashes.
    value = "".join(value.split()).replace("-", "")
    if not AADHAAR_RE.fullmatch(value):
        raise ValueError("Aadhaar must be 12 digits and cannot start with 0 or 1.")
    if not verhoeff.is_valid(value):
        raise ValueError("This Aadhaar number is not valid (checksum failed). Check for a typo.")
    return value


class KycForm(BaseModel):
    pan: str
    aadhaar: str

    @field_validator("pan")
    @classmethod
    def pan_format(cls, value: str) -> str:
        return check_pan(value)

    @field_validator("aadhaar")
    @classmethod
    def aadhaar_format(cls, value: str) -> str:
        return check_aadhaar(value)


class RejectForm(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def reason_length(cls, value: str) -> str:
        value = value.strip()
        if not 5 <= len(value) <= 300:
            raise ValueError("Please give a reason of 5 to 300 characters, so the customer knows what to fix.")
        return value
