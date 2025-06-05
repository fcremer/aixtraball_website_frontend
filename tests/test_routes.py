"""
Smoke‑Tests: Überprüft, ob alle Haupt­seiten HTTP 200 liefern.
Die YAML‑Dateien werden zur Laufzeit minimal erzeugt, damit die
Flask‑App auch in der CI ohne Volumes funktioniert.
"""
import pathlib, yaml, pytest
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


def test_current_opening_visible(client):
    """Aktueller Öffnungstag wird korrekt angezeigt."""
    t_from = datetime.now().replace(microsecond=0)
    t_to   = t_from + timedelta(hours=4)

    _write(
        "opening_days.yaml",
        [{"from": t_from.strftime("%Y-%m-%d %H:%M"), "to": t_to.strftime("%Y-%m-%d %H:%M")}],
    )

    html = client.get("/").data.decode()

    # Seit der letzten Änderung wird bei einem Termin am heutigen Tag das Wort
    # "Heute" ausgegeben statt des Datums.
    assert "Heute" in html
