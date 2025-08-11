"""
app/app.py  –  Haupt-Backend der Vereins‑Website
------------------------------------------------
• Frontend‑Routen (Startseite, Verein, Team, Flipper, News …)
• YAML‑basierte Inhalte werden bei jeder Request live eingelesen
• Hilfsfilter:  asset()   → lokale/remote‑Bilder
                datetimeformat() → Datumsausgabe
"""

from pathlib import Path
from datetime import datetime
from itertools import groupby
from flask import Response

import random
import yaml

from dateutil import parser, tz
from flask import (
    Flask, render_template, redirect,
    url_for, request
)

# --------------------------------------------------
# Grundkonfiguration
# --------------------------------------------------
app = Flask(__name__)

BASE_DIR   = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"

# --------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------
# Einfache Dateicache für YAML-Inhalte. So müssen häufig
# verwendete Dateien nicht bei jeder Anfrage erneut von der
# Festplatte gelesen werden. Ändert sich die Datei, wird sie
# automatisch neu geladen, da das Änderungsdatum geprüft wird.
# Cache-Struktur: Dateiname -> (mtime, geladene Daten)
_yaml_cache: dict[str, tuple[float, object]] = {}

def load_yaml(filename: str):
    """Beliebige YAML‑Datei aus dem config‑Ordner laden."""
    path = CONFIG_DIR / filename
    mtime = path.stat().st_mtime if path.exists() else 0

    cached = _yaml_cache.get(filename)
    if cached and cached[0] == mtime:
        return cached[1]

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []

    _yaml_cache[filename] = (mtime, data)
    return data

def get_next_opening():
    """Nächsten Öffnungstag aus opening_days.yaml ermitteln."""
    openings = load_yaml("opening_days.yaml")
    now = datetime.now(tz=tz.gettz("Europe/Berlin"))
    for o in openings:
        o["from_dt"] = parser.parse(o["from"]).astimezone(tz.gettz("Europe/Berlin"))
        o["to_dt"] = parser.parse(o["to"]).astimezone(tz.gettz("Europe/Berlin"))

    future = [o for o in openings if o["to_dt"] > now]
    future.sort(key=lambda x: x["from_dt"])
    opening = future[0] if future else None
    if opening:
        opening["is_today"] = opening["from_dt"].date() == now.date()
    return opening

# --------------------------------------------------
# Jinja‑Filter
# --------------------------------------------------
@app.template_filter("datetimeformat")
def datetimeformat(value, fmt="%d.%m.%Y %H:%M"):
    if isinstance(value, str):
        value = parser.parse(value)
    return value.strftime(fmt)

@app.template_filter("asset")
def asset(path: str):
    """Gibt für http/https den Original‑Pfad zurück,
       sonst einen /static/‑URL‑Pfad."""
    if path.startswith(("http://", "https://", "//")):
        return path
    return url_for("static", filename=path)

# --------------------------------------------------
# Routen
# --------------------------------------------------
@app.route("/")
def index():
    flippers      = load_yaml("flippers.yaml")
    home_flippers = random.sample(flippers, min(len(flippers), 6))
    news_teaser   = sorted(load_yaml("news.yaml"),
                           key=lambda x: x["date"],
                           reverse=True)[:2]
    now = datetime.now(tz=tz.gettz("Europe/Berlin"))

    return render_template(
        "index.html",
        slides       = load_yaml("slides.yaml"),
        opening      = get_next_opening(),
        home_flippers= home_flippers,
        latest_news  = news_teaser,
        now          = now
    )

@app.route("/preise")
def preise():
    """Preise‑/Besucherinfos anzeigen."""
    return render_template(
        "prices.html",
        opening=get_next_opening()
    )

@app.route("/verein")
def verein():
    # Timeline‑Milestones laden
    timeline = load_yaml("timeline.yaml")
    # chronologisch sortiert – falls im YAML durcheinander
    print(timeline)
    timeline.sort(key=lambda x: parser.parse(x["date"]))
    return render_template(
        "verein.html",
        opening=get_next_opening(),
        timeline=timeline,
        members=load_yaml("members.yaml")  # für Team‑Section auf gleicher Seite
    )

@app.route("/team")
def team():
    return render_template("team.html",
                           members = load_yaml("members.yaml"),
                           opening = get_next_opening())


@app.route("/flipper")
def flipper_all():
    """
    Reise durch unsere Flipper‑Epochen:
    • lädt flippers.yaml
    • sortiert chronologisch
    • berechnet Jahrzehnt‑Label (70er, 80er …)
    """
    flippers = load_yaml("flippers.yaml")

    # Erwartet: jedes Objekt hat mindestens "name", "image", "year"
    for f in flippers:
        raw_year = f.get("year", "")
        try:
            # Nur die ersten vier Ziffern als Jahr verwenden
            year = int(str(raw_year)[:4])
            f["year"] = year
            f["decade_label"] = f"{(year // 10) * 10}er"
        except (ValueError, TypeError):
            f["year"] = 0
            f["decade_label"] = "Unbekannt"

    # chronologisch (ältestes zuerst)
    flippers.sort(key=lambda f: f["year"] or 9999)

    return render_template(
        "flipper_all.html",
        flippers=flippers,
        opening=get_next_opening()
    )

@app.route("/news")
def news_list():
    """News‑Liste mit Filterung nach Jahr, Kategorie und Suchbegriff."""
    raw_news = load_yaml("news.yaml")

    # -----------------------
    # URL‑Parameter auslesen
    # -----------------------
    year                = request.args.get("year", type=int)
    selected_categories = request.args.getlist("category")
    q                   = request.args.get("q", "").strip()

    # -----------------------
    # Zusatzinfos vorbereiten
    # -----------------------
    from datetime import datetime
    for n in raw_news:
        date_str = n.get("date", "")
        try:
            dt = parser.parse(date_str)
        except Exception:
            # Fallback to minimal date if parsing fails
            dt = datetime.min
        # store datetime for sorting and template compatibility
        n["date"] = dt
        # extract year if valid date
        n["_year"] = dt.year if dt != datetime.min else None

    # -----------------------
    # Filter anwenden
    # -----------------------
    news = raw_news
    if year:
        news = [n for n in news if n.get("_year") == year]
    if selected_categories:
        news = [n for n in news if n.get("category") in selected_categories]
    if q:
        q_lower = q.lower()
        news = [n for n in news if q_lower in n.get("title", "").lower()]

    # -----------------------
    # Sortierung
    # -----------------------
    news.sort(key=lambda x: x["date"], reverse=True)

    # -----------------------
    # Dropdown‑Werte berechnen
    # -----------------------
    years = sorted({n.get("_year") for n in raw_news if n.get("_year")}, reverse=True)
    categories = sorted({n.get("category") for n in raw_news if n.get("category")})

    return render_template(
        "news_list.html",
        news=news,
        years=years,
        categories=categories,
        opening=get_next_opening()
    )

@app.route("/news/<slug>")
def news_detail(slug):
    news = load_yaml("news.yaml")
    article = next((n for n in news if n["slug"] == slug), None)
    if article is None:
        return redirect(url_for("news_list"))
    return render_template("news_detail.html",
                           article = article,
                           opening = get_next_opening())

@app.route("/kontakt", methods=["GET", "POST"])
def kontakt():
    if request.method == "POST":
        # Hier könnte ein echter Mail‑Service angebunden werden.
        return redirect("mailto:info@aixtraball.de")
    return render_template("contact.html",
                           opening=get_next_opening())

@app.route("/impressum")
def impressum():
    return render_template("impressum.html",
                           opening=get_next_opening())


@app.route("/robots.txt")
def robots():
    txt = "User-agent: *\nAllow: /\nSitemap: https://aixtraball.de/sitemap.xml"
    return Response(txt, mimetype="text/plain")

@app.route("/sitemap.xml")
def sitemap():
    pages = [
        {"loc": url_for('index',      _external=True)},
        {"loc": url_for('flipper_all',_external=True)},
        {"loc": url_for('verein',     _external=True)},
        {"loc": url_for('team',       _external=True)},
        {"loc": url_for('news_list',  _external=True)}
    ]
    # alle News‑Artikel
    for n in load_yaml("news.yaml"):
        pages.append({"loc": url_for('news_detail', slug=n["slug"], _external=True),
                      "lastmod": n["date"]})
    xml = render_template("sitemap.xml.j2", pages=pages)
    return Response(xml, mimetype="application/xml")

# --------------------------------------------------
# Local run (Dockerfile startet ebenfalls so)
# --------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)