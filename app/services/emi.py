"""EMI and repayment schedule.

EMI = P · r · (1+r)^n / ((1+r)^n − 1),  r = annual rate / 12 / 100

We calculate with Decimal (exact decimal maths) and round to whole paise
only at the end. Check: ₹1,00,000 at 18% for 12 months = ₹9,168.00.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

ANNUAL_RATE_PERCENT = 18  # flat demo rate


def _monthly_rate(annual_rate_percent: int) -> Decimal:
    return Decimal(annual_rate_percent) / 12 / 100


def _to_paise(amount: Decimal) -> int:
    """Round to the nearest paisa (0.5 rounds up, like a shopkeeper would)."""
    return int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def calculate_emi(principal_paise: int, months: int, annual_rate_percent: int = ANNUAL_RATE_PERCENT) -> int:
    """Monthly EMI in paise."""
    r = _monthly_rate(annual_rate_percent)
    if r == 0:
        return _to_paise(Decimal(principal_paise) / months)
    growth = (1 + r) ** months  # (1+r)^n
    return _to_paise(principal_paise * r * growth / (growth - 1))


def max_principal(emi_limit_paise: int, months: int, annual_rate_percent: int = ANNUAL_RATE_PERCENT) -> int:
    """The largest loan (in whole rupees) whose EMI is at most emi_limit_paise.

    This is the EMI formula turned around: P = EMI · ((1+r)^n − 1) / (r · (1+r)^n).
    """
    if emi_limit_paise <= 0:
        return 0
    r = _monthly_rate(annual_rate_percent)
    if r == 0:
        exact = Decimal(emi_limit_paise * months)
    else:
        growth = (1 + r) ** months
        exact = emi_limit_paise * (growth - 1) / (r * growth)
    principal = int(exact // 100) * 100  # round DOWN to whole rupees
    # Rounding the EMI could push it 1 paisa over the limit; step down if so.
    while principal > 0 and calculate_emi(principal, months, annual_rate_percent) > emi_limit_paise:
        principal -= 100
    return principal


@dataclass(frozen=True)
class ScheduleRow:
    number: int
    amount_paise: int
    principal_paise: int
    interest_paise: int


def repayment_schedule(
    principal_paise: int, months: int, annual_rate_percent: int = ANNUAL_RATE_PERCENT
) -> list[ScheduleRow]:
    """Month-by-month split of each EMI into interest and principal.

    Interest each month = what is still owed × r. The rest of the EMI pays
    down the loan. The LAST installment pays off exactly what is left, so
    rounding never leaves a few paise owing (or overpaid).
    """
    r = _monthly_rate(annual_rate_percent)
    emi = calculate_emi(principal_paise, months, annual_rate_percent)
    balance = principal_paise
    rows = []
    for number in range(1, months + 1):
        interest = _to_paise(balance * r)
        principal_part = balance if number == months else emi - interest
        rows.append(ScheduleRow(number, principal_part + interest, principal_part, interest))
        balance -= principal_part
    return rows
