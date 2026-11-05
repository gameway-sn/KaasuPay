"""Phase 3: EMI maths, money formatting and the credit decision, tested on their own."""
from datetime import date

import pytest

from app.services.decision import decide
from app.services.emi import calculate_emi, max_principal, repayment_schedule
from app.services.loans import add_months
from app.services.money import format_inr, parse_rupees

LAKH = 1_00_000 * 100  # ₹1,00,000 in paise


# ---------- EMI (from the CLAUDE.md test plan) ----------

def test_emi_one_lakh_18_percent_12_months_is_9168():
    assert calculate_emi(LAKH, 12, 18) == 916800  # ₹9,168.00


def test_schedule_adds_up_exactly():
    rows = repayment_schedule(LAKH, 12, 18)
    assert len(rows) == 12
    assert sum(r.principal_paise for r in rows) == LAKH          # every paisa of the loan repaid
    assert all(r.amount_paise == r.principal_paise + r.interest_paise for r in rows)
    assert all(r.amount_paise == 916800 for r in rows[:-1])       # 11 normal EMIs
    assert abs(rows[-1].amount_paise - 916800) <= 12              # the last one absorbs rounding


def test_first_month_interest_is_1_5_percent():
    assert repayment_schedule(LAKH, 12, 18)[0].interest_paise == 150000  # ₹1,500 on ₹1,00,000


@pytest.mark.parametrize("amount, months", [(5_000, 3), (73_421, 7), (2_00_000, 24)])
def test_schedule_always_balances(amount, months):
    rows = repayment_schedule(amount * 100, months, 18)
    assert sum(r.principal_paise for r in rows) == amount * 100


def test_max_principal_is_the_largest_that_fits():
    limit = 15_000 * 100
    best = max_principal(limit, 12, 18)
    assert best % 100 == 0                              # whole rupees
    assert calculate_emi(best, 12, 18) <= limit         # fits
    assert calculate_emi(best + 100, 12, 18) > limit    # one rupee more doesn't


def test_add_months_handles_short_months():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


# ---------- Money ----------

@pytest.mark.parametrize("paise, text", [
    (916800, "₹9,168.00"),
    (LAKH, "₹1,00,000.00"),
    (123456789, "₹12,34,567.89"),
    (50, "₹0.50"),
    (500000, "₹5,000.00"),
])
def test_format_inr(paise, text):
    assert format_inr(paise) == text


def test_parse_rupees():
    assert parse_rupees("1,00,000") == 100000
    assert parse_rupees(" ₹50000 ") == 50000
    for bad in ["12.50", "-5", "abc", ""]:
        with pytest.raises(ValueError):
            parse_rupees(bad)


# ---------- Decision rule ----------

def run(amount_rupees, months, income_rupees, existing_rupees=0, kyc=True):
    return decide(kyc_approved=kyc, amount_paise=amount_rupees * 100, months=months,
                  monthly_income_paise=income_rupees * 100, existing_emis_paise=existing_rupees * 100)


def test_decline_without_kyc():
    d = run(50_000, 12, 1_00_000, kyc=False)
    assert not d.offered and "KYC" in d.reason


def test_full_offer_when_within_50_percent():
    d = run(1_00_000, 12, 40_000, 5_000)   # EMI 9,168 + 5,000 <= 20,000
    assert d.offered
    assert d.amount_paise == LAKH
    assert d.emi_paise == 916800


def test_exactly_50_percent_is_allowed():
    # Income chosen so that EMI + existing is exactly half of it.
    d = decide(kyc_approved=True, amount_paise=LAKH, months=12,
               monthly_income_paise=2 * (916800 + 500000), existing_emis_paise=500000)
    assert d.offered and d.amount_paise == LAKH


def test_counter_offer_when_too_much():
    d = run(2_00_000, 12, 40_000, 5_000)   # limit 15,000/month; full EMI would be 18,336
    assert d.offered
    assert d.amount_paise < 2_00_000 * 100
    assert d.amount_paise == max_principal(15_000 * 100, 12, 18)
    assert d.emi_paise <= 15_000 * 100
    assert "Counter-offer" in d.reason


def test_decline_when_even_minimum_does_not_fit():
    d = run(50_000, 3, 3_000)               # limit ₹1,500/month; ₹5,000 over 3 months needs ~₹1,717
    assert not d.offered


def test_decline_when_existing_emis_use_half_the_income():
    d = run(10_000, 12, 30_000, 15_000)
    assert not d.offered and "existing EMIs" in d.reason
