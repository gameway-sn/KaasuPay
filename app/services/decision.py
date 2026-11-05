"""The demo credit decision.

1. KYC not approved                          -> declined
2. new EMI + existing EMIs <= 50% of income  -> offered (full amount)
3. otherwise                                 -> offered (the largest amount that fits),
                                                or declined if even ₹5,000 doesn't fit
"""
from dataclasses import dataclass

from app.services.emi import ANNUAL_RATE_PERCENT, calculate_emi, max_principal
from app.services.money import format_inr

MIN_AMOUNT_RUPEES = 5_000
MAX_AMOUNT_RUPEES = 2_00_000
MIN_TENURE_MONTHS = 3
MAX_TENURE_MONTHS = 24
MIN_AMOUNT_PAISE = MIN_AMOUNT_RUPEES * 100


@dataclass(frozen=True)
class Decision:
    offered: bool
    amount_paise: int | None
    emi_paise: int | None
    reason: str


def decide(
    *,
    kyc_approved: bool,
    amount_paise: int,
    months: int,
    monthly_income_paise: int,
    existing_emis_paise: int,
    annual_rate_percent: int = ANNUAL_RATE_PERCENT,
) -> Decision:
    if not kyc_approved:
        return Decision(False, None, None, "Declined: your KYC is not approved yet.")

    # All EMIs together may use at most half the income. (Whole paise, so rounding down is exact.)
    limit = monthly_income_paise // 2 - existing_emis_paise
    if limit <= 0:
        return Decision(False, None, None,
                        "Declined: your existing EMIs already use 50% or more of your monthly income.")

    emi = calculate_emi(amount_paise, months, annual_rate_percent)
    if emi <= limit:
        return Decision(True, amount_paise, emi,
                        f"Approved: the new EMI of {format_inr(emi)} plus existing EMIs of "
                        f"{format_inr(existing_emis_paise)} stays within 50% of your income "
                        f"({format_inr(monthly_income_paise // 2)}).")

    best = max_principal(limit, months, annual_rate_percent)
    if best >= MIN_AMOUNT_PAISE:
        best_emi = calculate_emi(best, months, annual_rate_percent)
        return Decision(True, best, best_emi,
                        f"Counter-offer: {format_inr(amount_paise)} would need an EMI of {format_inr(emi)}, "
                        f"but you can afford at most {format_inr(limit)} a month. "
                        f"The largest loan that fits is {format_inr(best)}.")

    return Decision(False, None, None,
                    f"Declined: you can afford at most {format_inr(limit)} a month in new EMIs, "
                    f"which is not enough for even the smallest loan ({format_inr(MIN_AMOUNT_PAISE)}).")
