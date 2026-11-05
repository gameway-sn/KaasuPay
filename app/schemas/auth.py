"""Validation for the registration forms (Pydantic).

The browser also checks some fields, but anyone can bypass the browser,
so these server-side checks are the ones that count.
"""
import re

from pydantic import BaseModel, ValidationError, field_validator, model_validator

PHONE_RE = re.compile(r"[6-9][0-9]{9}")
OTP_RE = re.compile(r"[0-9]{6}")


def check_phone(value: str) -> str:
    value = value.strip()
    if not PHONE_RE.fullmatch(value):
        raise ValueError("Phone must be 10 digits and start with 6, 7, 8 or 9.")
    return value


class RegisterForm(BaseModel):
    phone: str
    full_name: str

    @field_validator("phone")
    @classmethod
    def phone_format(cls, value: str) -> str:
        return check_phone(value)

    @field_validator("full_name")
    @classmethod
    def name_length(cls, value: str) -> str:
        value = value.strip()
        if not 2 <= len(value) <= 100:
            raise ValueError("Name must be 2 to 100 characters.")
        return value


class VerifyForm(BaseModel):
    phone: str
    otp: str
    password: str
    confirm_password: str

    @field_validator("phone")
    @classmethod
    def phone_format(cls, value: str) -> str:
        return check_phone(value)

    @field_validator("otp")
    @classmethod
    def otp_format(cls, value: str) -> str:
        value = value.strip()
        if not OTP_RE.fullmatch(value):
            raise ValueError("The code must be exactly 6 digits.")
        return value

    @field_validator("password")
    @classmethod
    def password_length(cls, value: str) -> str:
        if not 8 <= len(value) <= 128:
            raise ValueError("Password must be 8 to 128 characters.")
        return value

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("The two passwords do not match.")
        return self


def error_messages(exc: ValidationError) -> list[str]:
    """Turn Pydantic's errors into short sentences we can show on the page."""
    messages = []
    for err in exc.errors():
        if err["type"] == "value_error":
            messages.append(str(err["ctx"]["error"]))
        else:
            messages.append(f"{err['loc'][-1]}: {err['msg']}")
    return messages
