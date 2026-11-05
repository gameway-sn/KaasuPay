"""Helpers shared by all form schemas."""
from pydantic import ValidationError


def error_messages(exc: ValidationError) -> list[str]:
    """Turn Pydantic's errors into short sentences we can show on the page."""
    messages = []
    for err in exc.errors():
        if err["type"] == "value_error":
            messages.append(str(err["ctx"]["error"]))
        else:
            messages.append(f"{err['loc'][-1]}: {err['msg']}")
    return messages
