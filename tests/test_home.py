"""Phase 0 tests: the app starts, the home page renders, the banner is there."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

BANNER = "DEMO — KaasuPay is fictional. Do not enter real personal data."


def test_home_page_loads():
    response = client.get("/")
    assert response.status_code == 200
    assert "KaasuPay Loan Portal" in response.text


def test_home_page_shows_demo_banner():
    response = client.get("/")
    assert BANNER in response.text


def test_health():
    response = client.get("/health")
    assert response.json() == {"status": "ok"}
