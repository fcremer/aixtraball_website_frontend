"""
Smoke‑Tests: Überprüft, ob alle Haupt­seiten HTTP 200 liefern.
YAML‑Testdaten werden in ein temporäres Verzeichnis geschrieben,
damit Produktions­dateien in app/config/ nicht überschrieben werden.
"""
import pathlib, yaml, pytest, re
from datetime import datetime, timedelta

# ------------------------------------------------------------------
# 1  Import Flask‑App
# ------------------------------------------------------------------
from app.app import app as flask_app, YAML_CACHE, LOGIN_ATTEMPTS  # noqa: E402


# ------------------------------------------------------------------
# 2  Hilfsfunktion: YAMLs in ein beliebiges Verzeichnis schreiben
# ------------------------------------------------------------------
def _write(config_dir: pathlib.Path, name: str, data):
    (config_dir / name).write_text(
        yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
    )


def _populate_config(config_dir: pathlib.Path):
    """Befüllt config_dir mit Minimal‑YAMLs für die Tests."""
    t0 = datetime.now() + timedelta(days=30)
    t1 = t0 + timedelta(hours=4)

    _write(config_dir, "opening_days.yaml", [
        {"from": t0.strftime("%Y-%m-%d %H:%M"),
         "to":   t1.strftime("%Y-%m-%d %H:%M")}
    ])
    _write(config_dir, "flippers.yaml", [
        {"name": "Test Machine",
         "image": "images/test.jpg",
         "link":  "https://example.com"}
    ])
    _write(config_dir, "slides.yaml", [
        {"image": "images/slide.jpg"}
    ])
    _write(config_dir, "news.yaml", [
        {"title": "Dummy-News",
         "date":  datetime.now().strftime("%Y-%m-%d"),
         "slug":  "dummy-news",
         "preview_image": "images/slide.jpg"}
    ])
    _write(config_dir, "members.yaml", [
        {"name": "Jane Doe", "role": "Chairwoman", "image": "images/team.jpg"}
    ])
    _write(config_dir, "timeline.yaml", [
        {"date": "2015-03", "title": "Gründung",          "description": "Vereinsgründung in Würselen."},
        {"date": "2016-07", "title": "Erste Ausstellung",  "description": "Erste öffentliche Präsentation."},
    ])
    _write(config_dir, "news_settings.yaml", {"homepage_limit": 2})


# ------------------------------------------------------------------
# 3  Client‑Fixture – isoliertes tmp‑Verzeichnis, kein Overwrite
# ------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    _populate_config(tmp_path)
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    flask_app.config["CONFIG_DIR"] = tmp_path
    YAML_CACHE.clear()
    with flask_app.test_client() as c:
        yield c


# ------------------------------------------------------------------
# 4  Smoke‑Tests: alle wichtigen Routen
# ------------------------------------------------------------------
@pytest.mark.parametrize(
    "route",
    ["/", "/verein", "/team", "/flipper", "/news", "/preise"]
)
def test_routes_return_200(client, route):
    resp = client.get(route)
    assert resp.status_code == 200


# ------------------------------------------------------------------
# 5  Timeline‑Inhalt erscheint auf /verein
# ------------------------------------------------------------------
def test_timeline_visible_on_verein(client, tmp_path):
    timeline = yaml.safe_load((tmp_path / "timeline.yaml").read_text())
    assert timeline, "timeline.yaml ist leer"

    first_title = timeline[0]["title"]
    html = client.get("/verein").data.decode()

    assert first_title in html, "Timeline‑Titel nicht gefunden"


# ------------------------------------------------------------------
# 6  Aktueller Öffnungstag bleibt sichtbar
# ------------------------------------------------------------------
def test_current_opening_visible(client, tmp_path):
    """Wenn gerade ein Öffnungstag läuft, soll er auf der Startseite erscheinen."""
    now = datetime.now()
    t_from = now - timedelta(hours=1)
    t_to   = now + timedelta(hours=1)
    next_from = now + timedelta(days=1)
    next_to   = next_from + timedelta(hours=4)

    _write(tmp_path, "opening_days.yaml", [
        {"from": t_from.strftime("%Y-%m-%d %H:%M"),
         "to":   t_to.strftime("%Y-%m-%d %H:%M")},
        {"from": next_from.strftime("%Y-%m-%d %H:%M"),
         "to":   next_to.strftime("%Y-%m-%d %H:%M")},
    ])
    YAML_CACHE.clear()

    html = client.get("/").data.decode()

    assert "Heute" in html, "Aktueller Termin fehlt"
    assert next_from.strftime("%d.%m.%Y") not in html, "Falscher Termin angezeigt"


# ------------------------------------------------------------------
# 7  Login schützt vor Brute-Force
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


# ------------------------------------------------------------------
# 8  Admin: neuen Eintrag anlegen
# ------------------------------------------------------------------
def test_admin_add_entry_via_form(client, tmp_path):
    LOGIN_ATTEMPTS.clear()
    html = client.get("/login").data.decode()
    answer = _captcha_answer(html)
    client.post("/login", data={"username": "admin", "password": "admin", "captcha": answer})

    resp = client.get("/admin/manage/flippers.yaml")
    assert resp.status_code == 200

    client.post(
        "/admin/manage/flippers.yaml/new",
        data={"name": "Neu", "image": "images/x.jpg", "link": "https://ex"},
        follow_redirects=True,
    )
    YAML_CACHE.clear()
    data = yaml.safe_load((tmp_path / "flippers.yaml").read_text())
    assert any(f.get("name") == "Neu" for f in data)
