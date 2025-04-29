"""
Smoke-Tests: Überprüft, ob alle Haupt­seiten HTTP 200 liefern.
Die YAML-Dateien werden zur Laufzeit minimal erzeugt, damit die
Flask-App auch in der CI ohne Volumes funktioniert.
"""
import pathlib, yaml, pytest
from datetime import datetime, timedelta

# ------------------------------------------------------------------
# 1  Dummy-YAMLs anlegen
# ------------------------------------------------------------------
BASE_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"
CONFIG   = BASE_DIR / "config"
CONFIG.mkdir(parents=True, exist_ok=True)

def _write(name: str, data):
    (CONFIG / name).write_text(yaml.safe_dump(data), encoding="utf-8")

t0 = datetime.now() + timedelta(days=30)
t1 = t0 + timedelta(hours=4)

_write("opening_days.yaml", [
    {"from": t0.strftime("%Y-%m-%d %H:%M"),
     "to"  : t1.strftime("%Y-%m-%d %H:%M")}
])

_write("flippers.yaml", [
    {"name": "Test Machine",
     "image": "images/test.jpg",
     "link": "https://example.com"}
])

_write("slides.yaml", [
    {"image": "images/slide.jpg"}
])

_write("news.yaml", [
    {"title": "Dummy-News",
     "date": datetime.now().strftime("%Y-%m-%d"),
     "slug": "dummy-news",
     "preview_image": "images/slide.jpg"}
])

_write("members.yaml", [
    {"name": "Jane Doe",
     "role": "Chairwoman",
     "image": "images/team.jpg"}
])

# ------------------------------------------------------------------
# 2  Flask importieren & testen
# ------------------------------------------------------------------
from app.app import app as flask_app   # noqa: E402  (Import nach _write)

@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c

@pytest.mark.parametrize("route", ["/", "/verein", "/team", "/flipper", "/news"])
def test_routes_return_200(client, route):
    resp = client.get(route)
    assert resp.status_code == 200