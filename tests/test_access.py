"""Phase 1: require_role(...) acts like the VLAN ACLs.

Mirrors the Packet Tracer test plan: no login -> redirected; wrong role -> 403.
"""
import pytest

from app.models import STAFF_ROLES, Role


def test_staff_page_without_login_redirects_to_login(client):
    response = client.get("/staff", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_customer_page_without_login_redirects_to_login(client):
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_customer_cannot_open_staff_area(client, make_user, login):
    make_user("9876543210", Role.CUSTOMER)
    login("9876543210")
    response = client.get("/staff")
    assert response.status_code == 403
    assert "Forbidden" in response.text


@pytest.mark.parametrize("role", STAFF_ROLES)
def test_each_staff_role_can_open_staff_area(client, make_user, login, role):
    make_user("9000000009", role)
    response = login("9000000009")
    assert response.headers["location"] == "/staff"
    page = client.get("/staff")
    assert page.status_code == 200
    assert role in page.text


@pytest.mark.parametrize("role", STAFF_ROLES)
def test_staff_cannot_open_customer_dashboard(client, make_user, login, role):
    make_user("9000000009", role)
    login("9000000009")
    assert client.get("/dashboard").status_code == 403


def test_deactivated_user_is_logged_out(client, db, make_user, login):
    user = make_user("9876543210")
    login("9876543210")
    user.is_active = False
    db.commit()
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
