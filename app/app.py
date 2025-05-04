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
def load_yaml(filename: str):
    """Beliebige YAML‑Datei aus dem config‑Ordner laden."""
    with open(CONFIG_DIR / filename, encoding="utf-8") as f:
        return yaml.safe_load(f) or []

def get_next_opening():
    """Nächsten Öffnungstag aus opening_days.yaml ermitteln."""
    openings = load_yaml("opening_days.yaml")
    now = datetime.now(tz=tz.gettz("Europe/Berlin"))
    for o in openings:
        o["from_dt"] = parser.parse(o["from"]).astimezone(tz.gettz("Europe/Berlin"))
    future = [o for o in openings if o["from_dt"] > now]
    future.sort(key=lambda x: x["from_dt"])
    return future[0] if future else None

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

    return render_template(
        "index.html",
        slides       = load_yaml("slides.yaml"),
        opening      = get_next_opening(),
        home_flippers= home_flippers,
        latest_news  = news_teaser
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
    flippers = load_yaml("flippers.yaml")
    flippers.sort(key=lambda f: f["name"].lower())

    # alphabetische Gruppen A, B, C …
    groups = []
    for letter, items in groupby(flippers,
                                 key=lambda f: f["name"][0].upper()):
        groups.append({
            "letter":   letter,
            "flippers": list(items)
        })

    return render_template(
        "flipper_all.html",
        groups  = groups,
        opening = get_next_opening()
    )

@app.route("/news")
def news_list():
    news = sorted(load_yaml("news.yaml"),
                  key=lambda x: x["date"],
                  reverse=True)
    return render_template("news_list.html",
                           news    = news,
                           opening = get_next_opening())

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