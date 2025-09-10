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
from functools import wraps
from flask import Response, session, flash, jsonify

import random
import yaml
import os
import json
from time import time

from dateutil import parser, tz
from flask import (
    Flask, render_template, redirect,
    url_for, request
)
try:
    from flask_compress import Compress
except Exception:
    Compress = None
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# --------------------------------------------------
# Grundkonfiguration
# --------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me")

# Performance: cache static files long and enable simple cache-busting
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 60 * 60 * 24 * 365  # 1 year
try:
    static_css_dir = (Path(__file__).resolve().parent / "static" / "css")
    latest_css_mtime = max((p.stat().st_mtime for p in static_css_dir.glob("*.css")), default=time())
    app.config['ASSET_VERSION'] = str(int(latest_css_mtime))
except Exception:
    app.config['ASSET_VERSION'] = str(int(time()))

# Enable gzip compression if available
if Compress is not None:
    Compress(app)

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PW_HASH = os.environ.get(
    "ADMIN_PASSWORD_HASH", generate_password_hash("admin")
)

BASE_DIR   = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"

# In-memory login attempt tracker: {ip: (count, first_timestamp)}
LOGIN_ATTEMPTS = {}
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60  # 15 minutes

# --------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------
YAML_CACHE = {}

def load_yaml(filename: str):
    """Beliebige YAML‑Datei aus dem config‑Ordner laden (mtime‑Cache)."""
    path = CONFIG_DIR / filename
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return []
    cached = YAML_CACHE.get(filename)
    if cached and cached[0] == mtime:
        return cached[1]
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    YAML_CACHE[filename] = (mtime, data)
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


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

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
@app.route("/login", methods=["GET", "POST"])
def login():
    ip = request.remote_addr or "?"

    def _generate_captcha():
        a, b = random.randint(1, 9), random.randint(1, 9)
        session["captcha_answer"] = str(a + b)
        return f"{a} + {b}"

    def _attempt_info():
        info = LOGIN_ATTEMPTS.get(ip)
        if info and time() - info[1] > LOCKOUT_SECONDS:
            LOGIN_ATTEMPTS.pop(ip, None)
            return None
        return info

    def _register_failure():
        info = _attempt_info()
        if info:
            LOGIN_ATTEMPTS[ip] = (info[0] + 1, info[1])
        else:
            LOGIN_ATTEMPTS[ip] = (1, time())

    if request.method == "POST":
        info = _attempt_info()
        if info and info[0] >= MAX_ATTEMPTS:
            flash("Zu viele Fehlversuche. Bitte später erneut versuchen.", "danger")
        else:
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            captcha = request.form.get("captcha", "")

            if captcha != session.get("captcha_answer"):
                flash("Captcha falsch", "danger")
                _register_failure()
            elif username == ADMIN_USER and check_password_hash(ADMIN_PW_HASH, password):
                session["logged_in"] = True
                LOGIN_ATTEMPTS.pop(ip, None)
                return redirect(url_for("admin"))
            else:
                flash("Ungültige Zugangsdaten", "danger")
                _register_failure()
        question = _generate_captcha()
        return render_template("login.html", captcha_question=question)

    # GET
    question = _generate_captcha()
    return render_template("login.html", captcha_question=question)


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("index"))


@app.route("/admin")
@login_required
def admin():
    files = [
        ("flippers.yaml", "Flipper"),
        ("news.yaml", "News"),
        ("opening_days.yaml", "Öffnungstage"),
        ("slides.yaml", "Slides"),
        ("members.yaml", "Mitglieder"),
        ("timeline.yaml", "Timeline"),
    ]
    return render_template("admin.html", files=files)


@app.route("/admin/edit/<path:filename>", methods=["GET", "POST"])
@login_required
def admin_edit(filename):
    filepath = CONFIG_DIR / filename
    if request.method == "POST":
        json_data = request.form.get("content", "")
        try:
            data = json.loads(json_data) if json_data else {}
            yaml_content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
            filepath.write_text(yaml_content, encoding="utf-8")
            flash("Gespeichert", "success")
        except Exception as e:
            flash(f"Fehler beim Speichern: {e}", "danger")
        return redirect(url_for("admin_edit", filename=filename))
    if filepath.exists():
        with open(filepath, encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
    else:
        data = []
    return render_template("admin_edit.html", filename=filename, data=data)


@app.route("/admin/manage/<path:filename>")
@login_required
def admin_manage(filename):
    data = load_yaml(filename)
    return render_template("admin_manage.html", filename=filename, data=data)


@app.route("/admin/manage/<path:filename>/new", methods=["GET", "POST"])
@app.route("/admin/manage/<path:filename>/<int:index>", methods=["GET", "POST"])
@login_required
def admin_item(filename, index=None):
    filepath = CONFIG_DIR / filename
    data = load_yaml(filename)
    template_item = data[0] if data else {}
    if index is not None and index < len(data):
        item = data[index]
    else:
        item = {k: ("" if not isinstance(v, list) else []) for k, v in template_item.items()}
    if request.method == "POST":
        new_item = {}
        for key, value in item.items():
            if isinstance(value, list):
                text = request.form.get(key, "")
                new_list = [l.strip() for l in text.splitlines() if l.strip()]
                if "image" in key:
                    for f in request.files.getlist(f"{key}_upload"):
                        if f and f.filename:
                            upload_dir = BASE_DIR / "static" / "images"
                            upload_dir.mkdir(parents=True, exist_ok=True)
                            fname = secure_filename(f.filename)
                            f.save(upload_dir / fname)
                            new_list.append(f"images/{fname}")
                new_item[key] = new_list
            else:
                file = request.files.get(f"{key}_upload") if "image" in key else None
                if file and file.filename:
                    upload_dir = BASE_DIR / "static" / "images"
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    fname = secure_filename(file.filename)
                    file.save(upload_dir / fname)
                    new_item[key] = f"images/{fname}"
                else:
                    new_item[key] = request.form.get(key, "")
        if index is None or index >= len(data):
            data.append(new_item)
        else:
            data[index] = new_item
        yaml_content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        filepath.write_text(yaml_content, encoding="utf-8")
        flash("Gespeichert", "success")
        return redirect(url_for("admin_manage", filename=filename))
    return render_template("admin_item.html", filename=filename, item=item, index=index)


@app.route("/admin/upload", methods=["POST"])
@login_required
def admin_upload():
    file = request.files.get("image")
    if file and file.filename:
        upload_dir = BASE_DIR / "static" / "images"
        upload_dir.mkdir(parents=True, exist_ok=True)
        filename = secure_filename(file.filename)
        file.save(upload_dir / filename)
        flash("Bild hochgeladen", "success")
    else:
        flash("Keine Datei ausgewählt", "warning")
    return redirect(url_for("admin"))


@app.route("/admin/images.json")
@login_required
def admin_images():
    """List available images under static/images as JSON."""
    images_dir = BASE_DIR / "static" / "images"
    exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
    items = []
    if images_dir.exists():
        for p in images_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                rel = p.relative_to(BASE_DIR / "static").as_posix()
                items.append({
                    "path": rel,  # e.g., images/foo.jpg
                    "url": url_for('static', filename=rel),
                    "name": p.name,
                    "mtime": int(p.stat().st_mtime)
                })
    # newest first
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return jsonify(items)


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
