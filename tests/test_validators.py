"""Phase 2: Verhoeff, PAN, Aadhaar and encryption, tested on their own."""
import pytest

from app.schemas.kyc import check_aadhaar, check_pan
from app.services import verhoeff
from app.services.crypto import decrypt, encrypt, mask_aadhaar
from app.services.kyc import make_fake_aadhaar

VALID_SAMPLE = "234123412346"  # fake; its last digit is the correct Verhoeff check digit


# ---------- Verhoeff (from the CLAUDE.md test plan) ----------

def test_verhoeff_textbook_example():
    assert verhoeff.check_digit("236") == "3"
    assert verhoeff.is_valid("2363")


def test_verhoeff_valid_sample_passes():
    assert verhoeff.is_valid(VALID_SAMPLE)


def test_verhoeff_changing_any_one_digit_fails():
    # Try every position and every other digit: 12 x 9 = 108 typos, all caught.
    for position in range(len(VALID_SAMPLE)):
        for digit in "0123456789":
            if digit == VALID_SAMPLE[position]:
                continue
            typo = VALID_SAMPLE[:position] + digit + VALID_SAMPLE[position + 1:]
            assert not verhoeff.is_valid(typo), typo


def test_verhoeff_swapping_neighbours_fails():
    swapped = VALID_SAMPLE[:4] + VALID_SAMPLE[5] + VALID_SAMPLE[4] + VALID_SAMPLE[6:]
    assert swapped != VALID_SAMPLE
    assert not verhoeff.is_valid(swapped)


def test_verhoeff_rejects_non_digits():
    assert not verhoeff.is_valid("23412341234a")
    assert not verhoeff.is_valid("")


def test_fake_aadhaar_generator_makes_valid_numbers():
    for _ in range(50):
        assert check_aadhaar(make_fake_aadhaar())


# ---------- PAN ----------

def test_pan_valid_and_uppercased():
    assert check_pan(" abcpe1234f ") == "ABCPE1234F"


@pytest.mark.parametrize("bad", ["ABCDE1234F", "ABCPE12345", "ABCP1234F", "1BCPE1234F", ""])
def test_pan_invalid(bad):
    with pytest.raises(ValueError):
        check_pan(bad)


def test_pan_fourth_letter_must_be_p():
    with pytest.raises(ValueError, match="4th letter"):
        check_pan("ABCCE1234F")  # C = company


# ---------- Aadhaar ----------

def test_aadhaar_spaces_and_dashes_allowed():
    assert check_aadhaar("2341 2341 2346") == VALID_SAMPLE
    assert check_aadhaar("2341-2341-2346") == VALID_SAMPLE


@pytest.mark.parametrize("bad", ["034123412346", "134123412346", "23412341234", "2341234123467"])
def test_aadhaar_wrong_shape(bad):
    with pytest.raises(ValueError, match="12 digits"):
        check_aadhaar(bad)


def test_aadhaar_bad_checksum():
    with pytest.raises(ValueError, match="checksum"):
        check_aadhaar("234123412345")


# ---------- Encryption ----------

def test_encrypt_hides_the_number_and_decrypts_back():
    token = encrypt(VALID_SAMPLE)
    assert VALID_SAMPLE not in token
    assert decrypt(token) == VALID_SAMPLE


def test_encrypting_twice_gives_different_ciphertext():
    assert encrypt(VALID_SAMPLE) != encrypt(VALID_SAMPLE)


def test_mask():
    assert mask_aadhaar("2346") == "XXXX XXXX 2346"
