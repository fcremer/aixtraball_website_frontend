import pytest
from app.app import app as flask_app   # Pfad: flipper_site/app/app.py

@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        yield client

@pytest.mark.parametrize("route", ["/", "/verein", "/team", "/flipper", "/news"])
def test_pages_ok(client, route):
    resp = client.get(route)
    assert resp.status_code == 200