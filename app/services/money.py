"""Money helpers.

All money in this app is an integer number of PAISE (₹1 = 100 paise).
Never floats: in floating point, 0.1 + 0.2 = 0.30000000000000004.
"""
import re

_WHOLE_RUPEES = re.compile(r"[0-9]{1,12}")


def rupees_to_paise(rupees: int) -> int:
    return rupees * 100


def parse_rupees(text: str) -> int:
    """'1,00,000' or '₹ 50000' -> 100000 / 50000 (whole rupees). Raises ValueError."""
    cleaned = str(text).replace("₹", "").replace(",", "").strip()
    if not _WHOLE_RUPEES.fullmatch(cleaned):
        raise ValueError("Enter a whole number of rupees, like 50000 or 1,00,000.")
    return int(cleaned)


def format_inr(paise: int | None) -> str:
    """916800 -> '₹9,168.00';  10000000 -> '₹1,00,000.00' (Indian digit grouping)."""
    if paise is None:
        return "—"
    sign = "-" if paise < 0 else ""
    rupees, rest = divmod(abs(paise), 100)
    digits = str(rupees)
    if len(digits) > 3:
        # Last 3 digits together, then groups of 2: 1,00,000 / 12,34,567
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"{sign}₹{digits}.{rest:02d}"
