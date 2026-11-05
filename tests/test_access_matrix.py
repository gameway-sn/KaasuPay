"""Phase 6: the full access matrix — every protected route against every role.

The app's version of testing every ACL in Packet Tracer:
  not logged in        -> redirected to /login
  role not in the list -> 403 Forbidden
  role in the list     -> gets in (200, 303, 409 or 422 — anything but 403/login)

test_matrix_covers_every_route() fails if someone adds a route without adding
it here, the same way a new VLAN shouldn't go live without its ACL.
"""
import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.main import app
from app.models import KycDocument, Role
from app.schemas.kyc import KycForm
from app.schemas.loans import LoanApplicationForm
from app.seed import demo_files
from app.services.kyc import approve_kyc, submit_kyc
from app.services.loans import accept_offer, apply_for_loan, disburse

C, S, F, A, B = Role.CUSTOMER, Role.SUPPORT, Role.FINANCE, Role.IT_ADMIN, Role.BRANCH_AGENT
STAFF = {S, F, A, B}

# (method, path as FastAPI declares it, roles allowed, form data)
MATRIX = [
    ("GET",  "/dashboard",                               {C},   None),
    ("GET",  "/kyc",                                     {C},   None),
    ("POST", "/kyc",                                     {C},   {"pan": "ABCPE1234F", "aadhaar": "234123412346"}),
    ("GET",  "/kyc/documents/{doc_id}",                  {C, S}, None),
    ("GET",  "/loans/apply",                             {C},   None),
    ("POST", "/loans/apply",                             {C},   {"amount": "10000", "tenure_months": "6",
                                                                 "monthly_income": "40000", "existing_emis": "0"}),
    ("GET",  "/loans/{loan_id}",                         {C},   None),
    ("POST", "/loans/{loan_id}/accept",                  {C},   None),
    ("POST", "/loans/{loan_id}/decline",                 {C},   None),
    ("GET",  "/loans/{loan_id}/pay",                     {C},   None),
    ("POST", "/loans/{loan_id}/pay",                     {C},   {"installment_id": "{installment_id}"}),
    ("GET",  "/staff",                                   STAFF, None),
    ("GET",  "/staff/kyc",                               {S},   None),
    ("GET",  "/staff/kyc/{kyc_id}",                      {S},   None),
    ("POST", "/staff/kyc/{kyc_id}/approve",              {S},   None),
    ("POST", "/staff/kyc/{kyc_id}/reject",               {S},   {"reason": "Selfie is blurred"}),
    ("GET",  "/staff/loans",                             {F},   None),
    ("GET",  "/staff/loans/{loan_id}",                   {F},   None),
    ("POST", "/staff/loans/{loan_id}/disburse",          {F},   None),
    ("GET",  "/staff/collect",                           {B},   None),
    ("POST", "/staff/collect/{loan_id}",                 {B},   {"installment_id": "{installment_id}", "amount": "1"}),
    ("GET",  "/staff/admin/staff",                       {A},   None),
    ("POST", "/staff/admin/staff",                       {A},   {"full_name": "New Person", "phone": "9000000077",
                                                                 "role": "support"}),
    ("POST", "/staff/admin/staff/{staff_id}/{action}",   {A},   None),
    ("GET",  "/staff/admin/audit",                       {A},   None),
]

# Open to everyone, on purpose.
PUBLIC = {
    ("GET", "/"), ("GET", "/health"),
    ("GET", "/register"), ("POST", "/register"),
    ("GET", "/register/verify"), ("POST", "/register/verify"),
    ("GET", "/login"), ("POST", "/login"), ("POST", "/logout"),
}

ROLE_PHONES = {C: "9876543210", S: "9000000001", F: "9000000002", A: "9000000003", B: "9000000004"}


@pytest.fixture
def world(db, make_user):
    """One user per role, and a customer who owns a KYC (with documents) and a disbursed loan."""
    users = {role: make_user(phone, role, full_name=f"Matrix {role}") for role, phone in ROLE_PHONES.items()}
    owner = users[C]
    kyc = submit_kyc(db, owner, KycForm(pan="ABCPE1234F", aadhaar="234123412346"), demo_files((100, 100, 200)))
    approve_kyc(db, kyc, users[S])
    loan = apply_for_loan(db, owner, LoanApplicationForm(
        amount="30000", tenure_months="3", monthly_income="40000", existing_emis="0"))
    accept_offer(db, loan)
    disburse(db, loan, users[F])
    return {
        "doc_id": db.scalars(select(KycDocument)).first().id,
        "kyc_id": kyc.id,
        "loan_id": loan.id,
        "installment_id": loan.installments[0].id,
        "staff_id": users[B].id,
        "action": "unlock",
    }


def call(client, method, path, form, ids):
    url = path.format(**ids)
    data = {k: v.format(**ids) for k, v in form.items()} if form else None
    return client.request(method, url, data=data, follow_redirects=False)


def label(entry):
    return f"{entry[0]} {entry[1]}"


@pytest.mark.parametrize("entry", MATRIX, ids=label)
def test_access_matrix(client, login, world, entry):
    method, path, allowed, form = entry

    # 1. Not logged in -> login page.
    client.cookies.clear()
    response = call(client, method, path, form, world)
    assert response.status_code == 303 and response.headers["location"] == "/login", "anonymous"

    # 2. Every role that is NOT allowed -> 403. (Checked first, so nothing has changed yet.)
    for role in [r for r in ROLE_PHONES if r not in allowed]:
        client.cookies.clear()
        login(ROLE_PHONES[role])
        response = call(client, method, path, form, world)
        assert response.status_code == 403, f"{role} should be blocked, got {response.status_code}"

    # 3. Every role that IS allowed gets in.
    for role in allowed:
        client.cookies.clear()
        login(ROLE_PHONES[role])
        response = call(client, method, path, form, world)
        assert response.status_code != 403, f"{role} should be allowed"
        assert response.headers.get("location") != "/login", f"{role} was sent to login"
        assert response.status_code < 500, f"{role} caused a server error"


def test_matrix_covers_every_route():
    declared = {
        (method, route.path)
        for route in app.routes if isinstance(route, APIRoute)
        for method in route.methods
    }
    framework_pages = {(m, p) for m, p in declared if p.startswith(("/docs", "/redoc", "/openapi"))}
    in_matrix = {(m, p) for m, p, *_ in MATRIX}
    missing = declared - in_matrix - PUBLIC - framework_pages
    assert not missing, f"Routes with no access rule in the matrix: {sorted(missing)}"
    stale = in_matrix - declared
    assert not stale, f"Matrix lists routes that no longer exist: {sorted(stale)}"


@pytest.mark.parametrize("path", ["/", "/health", "/login", "/register"])
def test_public_pages_open_to_everyone(client, path):
    assert client.get(path).status_code == 200


def test_every_page_shows_the_demo_banner(client, login, world):
    banner = "DEMO — KaasuPay is fictional. Do not enter real personal data."
    pages = ["/", "/login", "/register"]
    assert all(banner in client.get(p).text for p in pages)
    for role, urls in {C: ["/dashboard", "/kyc", f"/loans/{world['loan_id']}"],
                       S: ["/staff", "/staff/kyc"], F: ["/staff/loans"],
                       A: ["/staff/admin/staff", "/staff/admin/audit"], B: ["/staff/collect"]}.items():
        client.cookies.clear()
        login(ROLE_PHONES[role])
        for url in urls:
            assert banner in client.get(url).text, url
    assert banner in client.get("/no-such-page").text  # error pages too
