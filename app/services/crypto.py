"""Encrypting Aadhaar numbers at rest (Fernet), and masking them for display.

Fernet = AES-128 encryption + an HMAC signature, in one easy package.
- encrypt("234123412346") -> "gAAAAABn..." (different every time, even for the same number)
- decrypt(...) needs the same FERNET_KEY; if the token was changed, it fails.

If someone copies the database file (SRV-DB) but not the .env file (SRV-APP),
they get "gAAAAABn..." instead of Aadhaar numbers.
"""
from cryptography.fernet import Fernet

from app.config import settings

_fernet = Fernet(settings.fernet_key)


def encrypt(text: str) -> str:
    return _fernet.encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    """Raises cryptography.fernet.InvalidToken if the key is wrong or the token was changed."""
    return _fernet.decrypt(token.encode()).decode()


def mask_aadhaar(last4: str) -> str:
    """What staff see: 'XXXX XXXX 2346'."""
    return f"XXXX XXXX {last4}"
