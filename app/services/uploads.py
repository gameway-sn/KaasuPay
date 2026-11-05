"""Checking and storing uploaded KYC files.

Like port security on a switch: don't trust what a file claims to be.
- Only .jpg/.jpeg/.png/.pdf names are accepted.
- Max 2 MB.
- The first bytes ("magic bytes") must really be JPEG/PNG/PDF and match the extension.
- Saved under a random name in uploads/ (outside static/), so files can only
  be reached through a route that checks the user's role.
"""
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.config import settings

MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB

# File name extension -> the type its content must really be.
ALLOWED_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
}

# What each real file type starts with, and the extension we save it under.
SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"%PDF-", "application/pdf", ".pdf"),
)

# Names we generate: 32 hex characters + extension. Anything else is refused.
STORED_NAME_RE = re.compile(r"[0-9a-f]{32}\.(jpg|png|pdf)")


class UploadError(ValueError):
    """A file failed a check. The message is safe to show to the user."""


@dataclass
class CheckedFile:
    data: bytes
    content_type: str
    extension: str


def check_upload(upload: UploadFile | None, label: str) -> CheckedFile:
    """Run every check on one uploaded file. Raises UploadError if any fails."""
    if upload is None or not upload.filename:
        raise UploadError(f"{label}: please choose a file.")

    extension = Path(upload.filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadError(f"{label}: only JPG, PNG or PDF files are allowed.")

    # Read at most 2 MB + 1 byte: enough to know the file is too big, without reading all of it.
    data = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise UploadError(f"{label}: the file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError(f"{label}: the file is larger than 2 MB.")

    for magic, content_type, saved_extension in SIGNATURES:
        if data.startswith(magic):
            if content_type != ALLOWED_EXTENSIONS[extension]:
                raise UploadError(f"{label}: the file's content does not match its name ({extension}).")
            return CheckedFile(data=data, content_type=content_type, extension=saved_extension)

    raise UploadError(f"{label}: this is not a real JPG, PNG or PDF file.")


def save_file(checked: CheckedFile) -> str:
    """Write the file under a new random name. Returns that name."""
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = secrets.token_hex(16) + checked.extension
    (settings.upload_dir / stored_name).write_bytes(checked.data)
    return stored_name


def path_for(stored_name: str) -> Path:
    """Full path of a stored file. Refuses any name we didn't generate (no ../ tricks)."""
    if not STORED_NAME_RE.fullmatch(stored_name):
        raise ValueError(f"Not a stored file name: {stored_name!r}")
    return settings.upload_dir / stored_name


def delete_file(stored_name: str) -> None:
    path_for(stored_name).unlink(missing_ok=True)
