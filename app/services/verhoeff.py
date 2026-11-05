"""Verhoeff checksum, used for the last digit of an Aadhaar number.

The last digit is calculated from the other 11. Verhoeff catches every
single-digit typo and every swap of two neighbouring digits. That's why a
random 12-digit number is almost never a "valid" Aadhaar.

It works with three fixed tables:
  _D   multiplication table (of the dihedral group D5, a fancy name for
       "the symmetries of a pentagon")
  _P   permutation table: mixes each digit differently depending on its position
  _INV inverse table: used to pick the check digit
"""
import re

_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)

_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)

_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)

_DIGITS = re.compile(r"[0-9]+")


def is_valid(number: str) -> bool:
    """True if the number's last digit is a correct Verhoeff check digit."""
    if not _DIGITS.fullmatch(number):
        return False
    c = 0
    # Walk the digits from right to left; i is the position from the right.
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def check_digit(digits: str) -> str:
    """The digit to append to `digits` so the result passes is_valid()."""
    if not _DIGITS.fullmatch(digits):
        raise ValueError("digits must contain only 0-9")
    c = 0
    # Same walk, shifted by one position, because the check digit will sit at position 0.
    for i, ch in enumerate(reversed(digits)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])
