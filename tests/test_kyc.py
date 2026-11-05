"""Phase 2: KYC submission, uploads, support review, and who may see documents."""
import pytest
from sqlalchemy import select

from app.models import KycDocument, KycRecord, KycStatus, Role
from app.services.crypto import decrypt

CUSTOMER = "9876543210"
OTHER_CUSTOMER = "9876500000"
SUPPORT = "9000000001"

AADHAAR = "234123412346"
PAN = "ABCPE1234F"

# Tiny fake files: only the first bytes matter for our checks.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"\x00" * 64


def good_files():
    return {
        "id_front": ("front.png", PNG, "image/png"),
        "id_back": ("back.jpg", JPG, "image/jpeg"),
        "selfie": ("me.pdf", PDF, "application/pdf"),
    }


def submit(client, pan=PAN, aadhaar=AADHAAR, files=None):
    return client.post("/kyc", data={"pan": pan, "aadhaar": aadhaar},
                       files=files or good_files(), follow_redirects=False)


def get_kyc(db):
    db.expire_all()
    return db.scalars(select(KycRecord)).first()


@pytest.fixture
def customer(make_user, login):
    user = make_user(CUSTOMER, Role.CUSTOMER, full_name="Asha Demo")
    login(CUSTOMER)
    return user


@pytest.fixture
def submitted_kyc(client, db, customer):
    assert submit(client).status_code == 303
    return get_kyc(db)


def login_as(client, make_user, login, phone, role):
    client.cookies.clear()
    make_user(phone, role)
    login(phone)


# ---------- Customer submits ----------

def test_customer_submits_kyc(client, db, customer, upload_dir):
    response = submit(client)
    assert response.status_code == 303
    assert response.headers["location"] == "/kyc"

    kyc = get_kyc(db)
    assert kyc.status == KycStatus.SUBMITTED
    assert kyc.pan == PAN
    assert len(kyc.documents) == 3
    # Files are on disk under random names, not "front.png".
    stored = sorted(p.name for p in upload_dir.iterdir())
    assert len(stored) == 3
    assert "front.png" not in stored


def test_aadhaar_is_encrypted_in_the_database(client, db, customer):
    submit(client)
    kyc = get_kyc(db)
    assert AADHAAR not in kyc.aadhaar_encrypted
    assert kyc.aadhaar_encrypted.startswith("gAAAA")  # Fernet token
    assert decrypt(kyc.aadhaar_encrypted) == AADHAAR
    assert kyc.aadhaar_last4 == "2346"


def test_bad_pan_and_aadhaar_show_errors(client, db, customer):
    response = submit(client, pan="ABCDE1234F", aadhaar="234123412345")
    assert response.status_code == 422
    assert "4th letter" in response.text
    assert "checksum" in response.text
    assert get_kyc(db) is None


@pytest.mark.parametrize("name, content, message", [
    ("virus.exe", PNG, "only JPG, PNG or PDF"),
    ("photo.gif", b"GIF89a" + b"\x00" * 10, "only JPG, PNG or PDF"),
    ("fake.png", b"MZ this is really a program", "not a real JPG, PNG or PDF"),
    ("mismatch.png", JPG, "does not match its name"),
    ("empty.png", b"", "empty"),
    ("huge.png", PNG + b"\x00" * (2 * 1024 * 1024), "larger than 2 MB"),
], ids=["exe", "gif", "fake-png", "mismatch", "empty", "too-big"])
def test_bad_uploads_are_rejected(client, db, customer, upload_dir, name, content, message):
    files = good_files()
    files["id_front"] = (name, content, "image/png")
    response = submit(client, files=files)
    assert response.status_code == 422
    assert message in response.text
    assert get_kyc(db) is None
    assert not upload_dir.exists() or not any(upload_dir.iterdir())


def test_cannot_submit_again_while_waiting(client, submitted_kyc):
    assert submit(client).status_code == 409


def test_customer_sees_status_on_dashboard(client, submitted_kyc):
    page = client.get("/dashboard")
    assert "submitted" in page.text


# ---------- Support reviews ----------

def test_support_sees_only_masked_aadhaar(client, db, make_user, login, submitted_kyc):
    login_as(client, make_user, login, SUPPORT, Role.SUPPORT)

    queue = client.get("/staff/kyc")
    assert queue.status_code == 200
    assert "Asha Demo" in queue.text

    page = client.get(f"/staff/kyc/{submitted_kyc.id}")
    assert page.status_code == 200
    assert "XXXX XXXX 2346" in page.text
    assert AADHAAR not in page.text
    assert "2341 2341 2346" not in page.text
    assert AADHAAR not in queue.text


def test_support_approves(client, db, make_user, login, submitted_kyc):
    login_as(client, make_user, login, SUPPORT, Role.SUPPORT)
    response = client.post(f"/staff/kyc/{submitted_kyc.id}/approve", follow_redirects=False)
    assert response.status_code == 303
    kyc = get_kyc(db)
    assert kyc.status == KycStatus.APPROVED
    assert kyc.reviewed_by.phone == SUPPORT

    # Can't approve twice.
    assert client.post(f"/staff/kyc/{submitted_kyc.id}/approve").status_code == 409


def test_reject_needs_a_reason(client, db, make_user, login, submitted_kyc):
    login_as(client, make_user, login, SUPPORT, Role.SUPPORT)
    response = client.post(f"/staff/kyc/{submitted_kyc.id}/reject", data={"reason": ""})
    assert response.status_code == 422
    assert get_kyc(db).status == KycStatus.SUBMITTED


def test_rejected_kyc_can_be_resubmitted(client, db, make_user, login, submitted_kyc, upload_dir):
    old_files = {d.stored_name for d in submitted_kyc.documents}

    login_as(client, make_user, login, SUPPORT, Role.SUPPORT)
    client.post(f"/staff/kyc/{submitted_kyc.id}/reject", data={"reason": "Selfie is blurred"})
    assert get_kyc(db).status == KycStatus.REJECTED

    client.cookies.clear()
    login(CUSTOMER)
    assert "Selfie is blurred" in client.get("/kyc").text
    assert submit(client).status_code == 303

    kyc = get_kyc(db)
    assert kyc.status == KycStatus.SUBMITTED
    assert kyc.rejection_reason is None
    new_files = {d.stored_name for d in kyc.documents}
    assert len(new_files) == 3 and not (old_files & new_files)
    # Old files were deleted from disk; only the 3 new ones remain.
    assert {p.name for p in upload_dir.iterdir()} == new_files


# ---------- Who may see what (ACL tests) ----------

def first_doc_id(db):
    return db.scalars(select(KycDocument)).first().id


def test_branch_agent_cannot_open_kyc_document(client, db, make_user, login, submitted_kyc):
    login_as(client, make_user, login, "9000000004", Role.BRANCH_AGENT)
    assert client.get(f"/kyc/documents/{first_doc_id(db)}").status_code == 403


@pytest.mark.parametrize("role", [Role.FINANCE, Role.IT_ADMIN, Role.BRANCH_AGENT])
def test_other_staff_cannot_use_kyc_queue_or_documents(client, db, make_user, login, submitted_kyc, role):
    login_as(client, make_user, login, "9000000009", role)
    assert client.get("/staff/kyc").status_code == 403
    assert client.get(f"/staff/kyc/{submitted_kyc.id}").status_code == 403
    assert client.post(f"/staff/kyc/{submitted_kyc.id}/approve").status_code == 403
    assert client.get(f"/kyc/documents/{first_doc_id(db)}").status_code == 403


def test_support_can_open_documents(client, db, make_user, login, submitted_kyc):
    login_as(client, make_user, login, SUPPORT, Role.SUPPORT)
    response = client.get(f"/kyc/documents/{first_doc_id(db)}")
    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_customer_can_open_own_document(client, db, submitted_kyc):
    assert client.get(f"/kyc/documents/{first_doc_id(db)}").status_code == 200


def test_customer_cannot_open_another_customers_document(client, db, make_user, login, submitted_kyc):
    login_as(client, make_user, login, OTHER_CUSTOMER, Role.CUSTOMER)
    assert client.get(f"/kyc/documents/{first_doc_id(db)}").status_code == 404


def test_document_without_login_redirects(client, db, submitted_kyc):
    client.cookies.clear()
    response = client.get(f"/kyc/documents/{first_doc_id(db)}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_staff_cannot_submit_kyc(client, make_user, login):
    login_as(client, make_user, login, SUPPORT, Role.SUPPORT)
    assert submit(client).status_code == 403


def test_uploads_are_not_reachable_through_static(client, submitted_kyc, upload_dir):
    name = next(upload_dir.iterdir()).name
    assert client.get(f"/static/{name}").status_code == 404
    assert client.get(f"/uploads/{name}").status_code == 404
