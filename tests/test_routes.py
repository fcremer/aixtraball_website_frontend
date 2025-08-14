"""
Smoke‑Tests: Überprüft, ob alle Haupt­seiten HTTP 200 liefern.
Die YAML‑Dateien werden zur Laufzeit minimal erzeugt, damit die
Flask‑App auch in der CI ohne Volumes funktioniert.
"""
import pathlib, yaml, pytest, re
from datetime import datetime, timedelta

# ------------------------------------------------------------------
# 1  Dummy‑YAMLs anlegen
# ------------------------------------------------------------------
BASE_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"
CONFIG   = BASE_DIR / "config"
CONFIG.mkdir(parents=True, exist_ok=True)

def _write(name: str, data):
    (CONFIG / name).write_text(yaml.safe_dump(data, allow_unicode=True),
                               encoding="utf-8")

# Öffnungstag in ~30 Tagen
t0 = datetime.now() + timedelta(days=30)
t1 = t0 + timedelta(hours=4)

_write("opening_days.yaml", [
    {"from": t0.strftime("%Y-%m-%d %H:%M"),
     "to"  : t1.strftime("%Y-%m-%d %H:%M")}
])

_write("flippers.yaml", [
    {"name": "Test Machine",
     "image": "images/test.jpg",
     "link" : "https://example.com"}
])

_write("slides.yaml", [
    {"image": "images/slide.jpg"}
])

_write("news.yaml", [
    {"title": "Dummy-News",
     "date" : datetime.now().strftime("%Y-%m-%d"),
     "slug" : "dummy-news",
     "preview_image": "images/slide.jpg"}
])

_write("members.yaml", [
    {"name" : "Jane Doe",
     "role" : "Chairwoman",
     "image": "images/team.jpg"}
])

_write("timeline.yaml", [
    {"date": "2015-03",
     "title": "Gründung",
     "description": "Vereinsgründung in Würselen."},
    {"date": "2016-07",
     "title": "Erste Ausstellung",
     "description": "Erste öffentliche Präsentation."}
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

# ------------------------------------------------------------------
# 3  Smoke‑Tests: alle wichtigen Routen
# ------------------------------------------------------------------
@pytest.mark.parametrize(
    "route",
    ["/", "/verein", "/team", "/flipper", "/news",
     "/preise"]                     # ← neu
)
def test_routes_return_200(client, route):
    resp = client.get(route)
    assert resp.status_code == 200

# ------------------------------------------------------------------
# 4  Timeline‑Inhalt erscheint auf /verein
# ------------------------------------------------------------------
def test_timeline_visible_on_verein(client):
    """
    Erstes Timeline‑Element aus timeline.yaml muss im
    gerendeten HTML der Vereins‑Seite vorkommen.
    """
    timeline = yaml.safe_load((CONFIG / "timeline.yaml").read_text())
    assert timeline, "timeline.yaml ist leer"

    first_title = timeline[0]["title"]
    html = client.get("/verein").data.decode()

    assert first_title in html, "Timeline‑Titel nicht gefunden"

# ------------------------------------------------------------------
# 5  Aktueller Öffnungstag bleibt sichtbar
# ------------------------------------------------------------------
def test_current_opening_visible(client):
    """Wenn gerade ein Öffnungstag läuft, soll er auf der Startseite erscheinen."""
    now = datetime.now()
    t_from = now - timedelta(hours=1)
    t_to = now + timedelta(hours=1)
    next_from = now + timedelta(days=1)
    next_to = next_from + timedelta(hours=4)

    _write("opening_days.yaml", [
        {"from": t_from.strftime("%Y-%m-%d %H:%M"),
         "to": t_to.strftime("%Y-%m-%d %H:%M")},
        {"from": next_from.strftime("%Y-%m-%d %H:%M"),
         "to": next_to.strftime("%Y-%m-%d %H:%M")},
    ])

    html = client.get("/").data.decode()

    assert "Heute" in html, "Aktueller Termin fehlt"
    assert next_from.strftime("%d.%m.%Y") not in html, "Falscher Termin angezeigt"


# ------------------------------------------------------------------
# 6  Login schützt vor Brute-Force durch Limitierung
# ------------------------------------------------------------------
def _captcha_answer(html: str) -> str:
    m = re.search(r"(\d+) \+ (\d+)", html)
    assert m, "Captcha-Frage nicht gefunden"
    return str(int(m.group(1)) + int(m.group(2)))


def test_login_rate_limit(client):
    """Nach 5 falschen Logins wird die weitere Anmeldung blockiert."""
    for _ in range(5):
        answer = _captcha_answer(client.get("/login").data.decode())
        resp = client.post(
            "/login",
            data={"username": "admin", "password": "wrong", "captcha": answer},
        )
        assert b"Zugangsdaten" in resp.data

    # sechster Versuch → blockiert
    answer = _captcha_answer(client.get("/login").data.decode())
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "wrong", "captcha": answer},
    )
    assert b"Zu viele Fehlversuche" in resp.data
