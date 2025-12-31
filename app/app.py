"""
app/app.py  –  Haupt-Backend der Vereins‑Website
------------------------------------------------
• Frontend‑Routen (Startseite, Verein, Team, Flipper, News …)
• YAML‑basierte Inhalte werden bei jeder Request live eingelesen
• Hilfsfilter:  asset()   → lokale/remote‑Bilder
                datetimeformat() → Datumsausgabe
"""

from pathlib import Path
from datetime import datetime, date as date_cls
import copy
from itertools import groupby
from functools import wraps
from flask import Response, session, flash, jsonify

import random
import yaml
import os
import json
import smtplib
from email.message import EmailMessage
from time import time

from dateutil import parser, tz
from flask import (
    Flask, render_template, redirect,
    url_for, request, g, abort
)
try:
    from flask_compress import Compress
except Exception:
    Compress = None
import hmac
import pyotp
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
# Plaintext password support (preferred if set). Fallback to legacy hash.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")  # e.g. set via docker-compose/.env
ADMIN_PW_HASH = os.environ.get("ADMIN_PASSWORD_HASH")  # legacy support
ADMIN_MFA_SECRET = os.environ.get("ADMIN_MFA_SECRET")


def _env_bool(value, default=False):
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(value, default):
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


BASE_DIR   = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
LOCAL_TZ   = tz.gettz("Europe/Berlin")
STATIC_DIR = BASE_DIR / "static"

SMTP_HOST       = os.environ.get("SMTP_HOST")
SMTP_PORT       = _env_int(os.environ.get("SMTP_PORT"), 587)
SMTP_USERNAME   = os.environ.get("SMTP_USERNAME")
SMTP_PASSWORD   = os.environ.get("SMTP_PASSWORD")
SMTP_SENDER     = os.environ.get("SMTP_SENDER")
SMTP_RECIPIENTS = os.environ.get("SMTP_RECIPIENTS")
SMTP_USE_TLS    = _env_bool(os.environ.get("SMTP_USE_TLS"), True)

NEWS_SETTINGS_FILE = "news_settings.yaml"
DEFAULT_NEWS_SETTINGS = {
    "homepage_limit": 2,
}

# In-memory login attempt tracker: {ip: (count, first_timestamp)}
LOGIN_ATTEMPTS = {}
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60  # 15 minutes
# In-memory contact attempt tracker: {ip: (count, first_timestamp)}
CONTACT_ATTEMPTS = {}
CONTACT_MAX_ATTEMPTS = _env_int(os.environ.get("CONTACT_MAX_ATTEMPTS"), 5)
CONTACT_WINDOW_SECONDS = _env_int(os.environ.get("CONTACT_WINDOW_SECONDS"), 10 * 60)


class SMTPConfigurationError(RuntimeError):
    """Raised when SMTP is not configured properly."""


# --------------------------------------------------
# News/Datetime helpers
# --------------------------------------------------
def _parse_local_datetime(value):
    """Return naive datetime localized to Europe/Berlin or None."""
    if not value:
        return None
    dt = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date_cls):
        dt = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        try:
            dt = parser.parse(value)
        except Exception:
            dt = None
    if not dt:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(LOCAL_TZ).replace(tzinfo=None)
    return dt


def _local_now():
    """Return naive datetime representing current local time."""
    return datetime.now(tz=LOCAL_TZ).replace(tzinfo=None)


def _prepare_news_item(item: dict):
    """Attach helper fields (_dt, _year, visibility window) to a news item."""
    dt = _parse_local_datetime(item.get("date"))
    if dt:
        item["_dt"] = dt
        item["_year"] = dt.year
    else:
        item["_dt"] = datetime.min
        item["_year"] = None
    if "_visible_from" not in item:
        item["_visible_from"] = _parse_local_datetime(item.get("visible_from"))
    if "_visible_until" not in item:
        until_raw = item.get("visible_until") or item.get("visible_to")
        item["_visible_until"] = _parse_local_datetime(until_raw)
    return item


def news_is_visible(item: dict, now=None) -> bool:
    """Check if a news entry should currently be visible."""
    if "_visible_from" not in item or "_visible_until" not in item or "_dt" not in item:
        _prepare_news_item(item)
    now_val = now or _local_now()
    start = item.get("_visible_from")
    end = item.get("_visible_until")
    if start and now_val < start:
        return False
    if end and now_val > end:
        return False
    return True


def load_news_items(include_hidden=False, now=None):
    """Load news with helper metadata and optional visibility filtering."""
    items = load_yaml("news.yaml")
    for item in items:
        _prepare_news_item(item)
    if include_hidden:
        return items
    now_val = now or _local_now()
    return [item for item in items if news_is_visible(item, now_val)]


def load_news_settings():
    """Return sanitized news settings with defaults for missing values."""
    raw = load_yaml(NEWS_SETTINGS_FILE)
    settings = DEFAULT_NEWS_SETTINGS.copy()
    if isinstance(raw, dict):
        limit_raw = raw.get("homepage_limit")
        if limit_raw is not None:
            try:
                settings["homepage_limit"] = max(0, int(limit_raw))
            except (ValueError, TypeError):
                pass
    return settings


def _resolve_smtp_recipients():
    raw = SMTP_RECIPIENTS or SMTP_SENDER or SMTP_USERNAME
    if not raw:
        return []
    normalized = raw.replace(";", ",")
    return [addr.strip() for addr in normalized.split(",") if addr.strip()]


def send_contact_email(payload: dict):
    """Send contact form payload via SMTP."""
    if app.config.get("TESTING"):
        return
    if not (SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD):
        raise SMTPConfigurationError("SMTP credentials are incomplete.")
    recipients = _resolve_smtp_recipients()
    if not recipients:
        raise SMTPConfigurationError("No SMTP recipients configured.")
    sender = SMTP_SENDER or SMTP_USERNAME
    msg = EmailMessage()
    msg["Subject"] = f"Neue Kontaktanfrage von {payload.get('name') or 'Unbekannt'}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    reply_to = payload.get("email")
    if reply_to:
        msg["Reply-To"] = reply_to
    body_lines = [
        "Neue Nachricht über das Kontaktformular:",
        "",
        f"Name: {payload.get('name') or '-'}",
        f"E-Mail: {payload.get('email') or '-'}",
        f"Zeit: {payload.get('timestamp') or '-'}",
        f"IP: {payload.get('ip') or '-'}",
        "",
        payload.get("message") or ""
    ]
    msg.set_content("\n".join(body_lines).strip() + "\n")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
        server.ehlo()
        if SMTP_USE_TLS:
            server.starttls()
            server.ehlo()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)


def save_news_settings(new_settings: dict):
    """Persist news settings and invalidate cache."""
    filepath = CONFIG_DIR / NEWS_SETTINGS_FILE
    yaml_content = yaml.safe_dump(new_settings, allow_unicode=True, sort_keys=False)
    filepath.write_text(yaml_content, encoding="utf-8")
    try:
        YAML_CACHE.pop(NEWS_SETTINGS_FILE, None)
    except Exception:
        pass

# --------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------
YAML_CACHE = {}

def load_yaml(filename: str):
    """Beliebige YAML‑Datei aus dem config‑Ordner laden (mtime‑Cache).
    Returns a deep copy to prevent accidental mutation of cached data.
    """
    path = CONFIG_DIR / filename
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return []
    cached = YAML_CACHE.get(filename)
    if cached and cached[0] == mtime:
        return copy.deepcopy(cached[1])
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    YAML_CACHE[filename] = (mtime, data)
    return copy.deepcopy(data)


def load_admin_accounts():
    """Return normalized admin definitions from admins.yaml or env fallback."""
    entries = []
    try:
        raw = load_yaml("admins.yaml")
    except Exception:
        raw = []
    for entry in raw:
        username = (entry or {}).get("username")
        if not username:
            continue
        if entry.get("active", True) is False:
            continue
        entries.append({
            "username": username,
            "password": entry.get("password"),
            "password_hash": entry.get("password_hash"),
            "mfa_secret": entry.get("mfa_secret"),
            "roles": entry.get("roles") or [],
        })
    if not entries:
        if ADMIN_PASSWORD is not None:
            fallback_password = ADMIN_PASSWORD
        elif ADMIN_PW_HASH:
            fallback_password = None
        else:
            fallback_password = "admin"
        entries.append({
            "username": ADMIN_USER,
            "password": fallback_password,
            "password_hash": ADMIN_PW_HASH,
            "mfa_secret": ADMIN_MFA_SECRET,
            "roles": [],
        })
    return entries


ADMIN_SECTIONS = {
    "slides.yaml": {
        "title": "Startseiten-Slider",
        "description": "Hero-Slides mit Headline, Subline und optionalem Logo.",
        "icon": "images",
        "allow_new": True,
        "schema": [
            {"name": "image", "label": "Hintergrundbild", "type": "image", "required": True, "help": "Pfad unter /static/images oder vollständige URL."},
            {"name": "headline", "label": "Überschrift", "type": "text", "preview": True},
            {"name": "subline", "label": "Unterzeile", "type": "text"},
            {"name": "alt", "label": "Alt-Text", "type": "text"},
            {"name": "pinned", "label": "Bevorzugt anzeigen", "type": "bool", "help": "Fixiert den Slide vorne im Karussell."},
            {"name": "logo", "label": "Logo einblenden", "type": "bool"}
        ]
    },
    "opening_days.yaml": {
        "title": "Öffnungstage",
        "description": "Alle öffentlichen Spieltage inkl. Uhrzeit.",
        "icon": "calendar-event",
        "allow_new": True,
        "schema": [
            {"name": "from", "label": "Von", "type": "datetime", "required": True, "help": "ISO-Format, z. B. 2025-07-27T11:00:00+02:00", "preview": True, "picker_format": "Y-m-d H:i:S"},
            {"name": "to", "label": "Bis", "type": "datetime", "required": True, "help": "Selbes Format wie oben.", "picker_format": "Y-m-d H:i:S"}
        ]
    },
    "flippers.yaml": {
        "title": "Flipper-Inventar",
        "description": "Alle Geräte inkl. Bilder, Hersteller, Features.",
        "icon": "joystick",
        "allow_new": True,
        "schema": [
            {"name": "name", "label": "Name", "type": "text", "required": True, "preview": True},
            {"name": "image", "label": "Hauptbild", "type": "image", "required": True},
            {"name": "image_details", "label": "Detailbilder", "type": "image_list"},
            {"name": "link", "label": "Externer Link", "type": "url"},
            {"name": "year", "label": "Baujahr", "type": "text"},
            {"name": "manufacturer", "label": "Hersteller", "type": "text", "preview": True},
            {"name": "system", "label": "System / Plattform", "type": "text"},
            {"name": "designer", "label": "Designer", "type": "text"},
            {"name": "software", "label": "Software", "type": "text"},
            {"name": "artwork", "label": "Artwork", "type": "text"},
            {"name": "sound", "label": "Sound", "type": "text"},
            {"name": "production", "label": "Stückzahl", "type": "text"},
            {"name": "features", "label": "Features", "type": "list", "help": "Eine Zeile pro Bulletpoint."},
            {"name": "notable_facts", "label": "Besonderheiten", "type": "list", "help": "Eine Zeile pro Bulletpoint."}
        ]
    },
    "news.yaml": {
        "title": "News & Berichte",
        "description": "Alle Artikel inkl. Zeitraumsteuerung und Medien.",
        "icon": "newspaper",
        "allow_new": True,
        "schema": [
            {"name": "title", "label": "Titel", "type": "text", "required": True, "preview": True},
            {"name": "slug", "label": "URL-Slug", "type": "text", "required": True, "help": "Kleinbuchstaben, Bindestriche, eindeutig."},
            {"name": "date", "label": "Datum", "type": "datetime", "required": True, "preview": True, "picker_format": "Y-m-d H:i:S"},
            {"name": "visible_from", "label": "Sichtbar ab", "type": "datetime", "picker_format": "Y-m-d H:i:S"},
            {"name": "visible_until", "label": "Sichtbar bis", "type": "datetime", "picker_format": "Y-m-d H:i:S"},
            {"name": "category", "label": "Kategorie", "type": "text", "preview": True},
            {"name": "preview_image", "label": "Teaserbild", "type": "image"},
            {"name": "excerpt", "label": "Kurzbeschreibung", "type": "textarea"},
            {"name": "content", "label": "Artikelinhalt", "type": "html"},
            {"name": "images", "label": "Galeriebilder", "type": "image_list"},
            {"name": "youtube_links", "label": "YouTube-Links", "type": "list", "help": "Komplette URLs; löst Cookie-Hinweis aus."}
        ]
    },
    "members.yaml": {
        "title": "Team & Vorstand",
        "description": "Profile für Verein, Vorstand, Helfer:innen.",
        "icon": "people",
        "allow_new": True,
        "schema": [
            {"name": "name", "label": "Name", "type": "text", "required": True, "preview": True},
            {"name": "role", "label": "Rolle", "type": "text", "preview": True},
            {"name": "image", "label": "Profilbild", "type": "image"},
            {"name": "bio", "label": "Kurzportrait", "type": "textarea", "help": "Einfacher Text, ohne HTML."},
            {"name": "links", "label": "Links (Label | URL)", "type": "list", "help": "Format pro Zeile: Beschriftung | https://example.de"}
        ]
    },
    "timeline.yaml": {
        "title": "Vereinsmeilensteine",
        "description": "Chronik-Ereignisse mit optionalem Bild.",
        "icon": "timeline",
        "allow_new": True,
        "schema": [
            {"name": "date", "label": "Datum (Monat)", "type": "text", "required": True, "help": "Format YYYY-MM, z. B. 2015-07", "preview": True},
            {"name": "title", "label": "Titel", "type": "text", "required": True, "preview": True},
            {"name": "description", "label": "Beschreibung", "type": "html"},
            {"name": "image", "label": "Bild", "type": "image"}
        ]
    },
    "admins.yaml": {
        "title": "Admins & MFA",
        "description": "Logins verwalten, MFA-Secrets hinterlegen.",
        "icon": "shield-lock",
        "allow_new": True,
        "schema": [
            {"name": "username", "label": "Benutzername", "type": "text", "required": True, "preview": True},
            {"name": "password", "label": "Passwort (Klartext)", "type": "password", "help": "Wird im Klartext gespeichert. Alternativ password_hash nutzen."},
            {"name": "password_hash", "label": "Passwort (Hash)", "type": "textarea", "help": "Optionaler Hash aus generate_password_hash."},
            {"name": "mfa_secret", "label": "MFA-Secret (Base32)", "type": "text"},
            {"name": "roles", "label": "Rollen", "type": "list"},
            {"name": "active", "label": "Aktiv", "type": "bool", "default": True, "preview": True}
        ]
    },
    "contact_submissions.yaml": {
        "title": "Kontaktanfragen",
        "description": "Eingehende Nachrichten aus dem Formular.",
        "icon": "envelope-open",
        "allow_new": False,
        "read_only": True
    }
}


def get_admin_section(filename):
    return ADMIN_SECTIONS.get(filename, {
        "title": filename,
        "description": "",
        "icon": "folder",
        "allow_new": True,
        "schema": None
    })


def get_admin_schema(filename):
    section = get_admin_section(filename)
    return section.get("schema")


def default_for_field(field):
    field_type = field.get("type", "text")
    if "default" in field:
        return field["default"]
    if field_type in {"image_list", "list"}:
        return []
    if field_type == "bool":
        return False
    return ""


def normalize_field_value(field, value):
    field_type = field.get("type", "text")
    if value is None:
        return default_for_field(field)
    if field_type == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"true", "1", "yes", "ja", "on"}
        return bool(value)
    if field_type in {"image_list", "list"}:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [v.strip() for v in value.splitlines() if v.strip()]
        return list(value)
    return value

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


def prepare_slides():
    """Return slides with ordering: first entry, pinned entries, then shuffled rest."""
    slides = load_yaml("slides.yaml")
    if not slides:
        return []

    normalized = []
    for slide in slides:
        if isinstance(slide, dict):
            normalized.append(slide)
        else:
            normalized.append({"image": slide})

    first = normalized[0]
    rest = normalized[1:]
    pinned = [s for s in rest if s.get("pinned")]
    other = [s for s in rest if not s.get("pinned")]
    random.shuffle(other)
    return [first, *pinned, *other]


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def _cookie_banner_required():
    """Return True if the current request depends on cookie-backed session data."""
    if getattr(g, "force_cookie_banner", False):
        return True
    try:
        keys = set(session.keys())
    except RuntimeError:
        return False
    endpoint = request.endpoint
    if endpoint != "login":
        keys.discard("captcha_answer")
    return bool(keys)


@app.context_processor
def inject_cookie_notice_flag():
    return {"cookie_banner_required": _cookie_banner_required}

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
    admin_accounts = load_admin_accounts()
    mfa_available = any(acc.get("mfa_secret") for acc in admin_accounts if acc.get("mfa_secret"))
    if request.args.get("reset_mfa"):
        session.pop("mfa_pending", None)

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

    def _find_admin(username):
        for admin in admin_accounts:
            if admin["username"] == username:
                pwd = admin.get("password")
                pwd_hash = admin.get("password_hash")
                if not (pwd or pwd_hash):
                    continue
                return admin
        return None

    def _get_pending_admin():
        if not mfa_available:
            return None
        pending = session.get("mfa_pending")
        if not pending:
            return None
        if pending.get("ip") and pending["ip"] != ip:
            session.pop("mfa_pending", None)
            return None
        created = pending.get("created", 0)
        if time() - created > 300:
            session.pop("mfa_pending", None)
            return None
        admin = _find_admin(pending.get("username"))
        if not admin or not admin.get("mfa_secret"):
            session.pop("mfa_pending", None)
            return None
        return admin

    def _password_valid(admin, supplied_password):
        if not supplied_password:
            return False
        if admin.get("password") is not None:
            return hmac.compare_digest(supplied_password, admin["password"])
        if admin.get("password_hash"):
            return check_password_hash(admin["password_hash"], supplied_password)
        return False

    if request.method == "POST":
        pending_admin = _get_pending_admin()
        if pending_admin:
            otp_code = request.form.get("otp", "").strip()
            if not otp_code:
                flash("Bitte den MFA-Code aus deiner Authenticator-App eingeben.", "danger")
                _register_failure()
                app.logger.warning(
                    "Login failed (missing mfa): ip=%s ua=%s",
                    ip, request.headers.get("User-Agent", "")
                )
                return render_template("login.html", mfa_stage=True, mfa_enabled=mfa_available, pending_user=pending_admin["username"])
            totp = pyotp.TOTP(pending_admin["mfa_secret"])
            if not totp.verify(otp_code, valid_window=1):
                flash("MFA-Code ungültig oder abgelaufen.", "danger")
                _register_failure()
                app.logger.warning(
                    "Login failed (mfa): ip=%s ua=%s",
                    ip, request.headers.get("User-Agent", "")
                )
                return render_template("login.html", mfa_stage=True, mfa_enabled=mfa_available, pending_user=pending_admin["username"])
            session.pop("mfa_pending", None)
            session["logged_in"] = True
            session["admin_username"] = pending_admin["username"]
            LOGIN_ATTEMPTS.pop(ip, None)
            return redirect(url_for("admin"))

        info = _attempt_info()
        if info and info[0] >= MAX_ATTEMPTS:
            flash("Zu viele Fehlversuche. Bitte später erneut versuchen.", "danger")
            app.logger.warning(
                "Login blocked (rate limit): ip=%s attempts=%s ua=%s",
                ip, info[0], request.headers.get("User-Agent", "")
            )
        else:
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            captcha = request.form.get("captcha", "")

            if captcha != session.get("captcha_answer"):
                flash("Captcha falsch", "danger")
                _register_failure()
                app.logger.warning(
                    "Login failed (captcha): ip=%s user=%s ua=%s",
                    ip, username, request.headers.get("User-Agent", "")
                )
            admin_obj = _find_admin(username)
            if admin_obj:
                valid_pw = _password_valid(admin_obj, password)
            else:
                valid_pw = False

            if admin_obj and valid_pw:
                if admin_obj.get("mfa_secret"):
                    session["mfa_pending"] = {"ip": ip, "created": time(), "username": admin_obj["username"]}
                    session.pop("captcha_answer", None)
                    flash("Passwort korrekt. Bitte gib nun den MFA-Code ein.", "info")
                    return redirect(url_for("login"))
                session["logged_in"] = True
                session["admin_username"] = admin_obj["username"]
                LOGIN_ATTEMPTS.pop(ip, None)
                return redirect(url_for("admin"))
            else:
                flash("Ungültige Zugangsdaten", "danger")
                _register_failure()
                app.logger.warning(
                    "Login failed (credentials): ip=%s user=%s ua=%s",
                    ip, username, request.headers.get("User-Agent", "")
                )
        question = _generate_captcha()
        return render_template("login.html", captcha_question=question, mfa_enabled=mfa_available, mfa_stage=False)

    # GET
    pending_admin = _get_pending_admin()
    if pending_admin:
        return render_template("login.html", mfa_enabled=mfa_available, mfa_stage=True, pending_user=pending_admin["username"])
    question = _generate_captcha()
    return render_template("login.html", captcha_question=question, mfa_enabled=mfa_available, mfa_stage=False)


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("index"))


@app.route("/admin")
@login_required
def admin():
    sections = []
    for filename, meta in ADMIN_SECTIONS.items():
        if meta.get("hide_from_dashboard"):
            continue
        try:
            data = load_yaml(filename)
        except Exception:
            data = []
        count = len(data) if isinstance(data, list) else (len(data.keys()) if isinstance(data, dict) else 0)
        sections.append({
            "filename": filename,
            "title": meta.get("title", filename),
            "description": meta.get("description", ""),
            "icon": meta.get("icon", "folder"),
            "count": count,
            "allow_new": meta.get("allow_new", True) and not meta.get("read_only"),
            "read_only": meta.get("read_only", False)
        })
    sections.sort(key=lambda s: s["title"])
    return render_template("admin.html", sections=sections)


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
    section = get_admin_section(filename)
    schema = section.get("schema")
    data = load_yaml(filename)
    preview_fields = [f for f in (schema or []) if f.get("preview")]
    schema_map = {f["name"]: f for f in (schema or [])}
    news_settings = load_news_settings() if filename == "news.yaml" else None
    return render_template(
        "admin_manage.html",
        filename=filename,
        data=data,
        section=section,
        read_only=section.get("read_only", False),
        schema=schema,
        preview_fields=preview_fields,
        schema_map=schema_map,
        news_settings=news_settings
    )


@app.route("/admin/manage/news/settings", methods=["POST"])
@login_required
def admin_news_settings():
    limit_raw = request.form.get("homepage_limit", "").strip()
    try:
        limit = int(limit_raw)
    except (ValueError, TypeError):
        flash("Bitte eine gültige Zahl angeben.", "warning")
        return redirect(url_for("admin_manage", filename="news.yaml"))
    limit = max(0, limit)
    save_news_settings({"homepage_limit": limit})
    flash("News-Einstellungen gespeichert.", "success")
    return redirect(url_for("admin_manage", filename="news.yaml"))


@app.route("/admin/manage/<path:filename>/new", methods=["GET", "POST"])
@app.route("/admin/manage/<path:filename>/<int:index>", methods=["GET", "POST"])
@login_required
def admin_item(filename, index=None):
    section = get_admin_section(filename)
    if section.get("read_only"):
        abort(403)
    schema = section.get("schema")
    filepath = CONFIG_DIR / filename
    data = load_yaml(filename)
    base_item = {}
    if index is not None and index < len(data):
        base_item = data[index]
    if schema:
        item = {}
        for field in schema:
            name = field["name"]
            if base_item and name in base_item:
                value = base_item.get(name)
            else:
                value = default_for_field(field)
            item[name] = normalize_field_value(field, value)
        extra_fields = {k: v for k, v in base_item.items() if k not in item}
    else:
        if base_item:
            item = base_item
        else:
            item = {}
        extra_fields = {}
    if request.method == "POST":
        # Determine effective index: prefer hidden form value if present
        form_index = request.form.get("__index")
        try:
            effective_index = int(form_index) if form_index not in (None, "") else index
        except ValueError:
            effective_index = index
        if schema:
            new_item = {}
            for field in schema:
                key = field["name"]
                ftype = field.get("type", "text")
                if ftype in {"list", "image_list"}:
                    text = request.form.get(key, "")
                    entries = [l.strip() for l in text.splitlines() if l.strip()]
                    if ftype == "image_list":
                        for f in request.files.getlist(f"{key}_upload"):
                            if f and f.filename:
                                upload_dir = BASE_DIR / "static" / "images"
                                upload_dir.mkdir(parents=True, exist_ok=True)
                                fname = secure_filename(f.filename)
                                f.save(upload_dir / fname)
                                entries.append(f"images/{fname}")
                    new_item[key] = entries
                elif ftype == "image":
                    file = request.files.get(f"{key}_upload")
                    if file and file.filename:
                        upload_dir = BASE_DIR / "static" / "images"
                        upload_dir.mkdir(parents=True, exist_ok=True)
                        fname = secure_filename(file.filename)
                        file.save(upload_dir / fname)
                        new_item[key] = f"images/{fname}"
                    else:
                        new_item[key] = request.form.get(key, "").strip()
                elif ftype == "bool":
                    new_item[key] = request.form.get(key) == "on"
                elif ftype == "password":
                    value = request.form.get(key, "")
                    new_item[key] = value
                else:
                    new_item[key] = request.form.get(key, "").strip()
            if filename == "news.yaml":
                new_item.pop("_date", None)
                new_item.pop("_year", None)
        else:
            new_item = {}
            iter_items = item.items()
            if filename == "news.yaml":
                iter_items = [(k, v) for k, v in item.items() if not k.startswith("_")]
            for key, value in iter_items:
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
        if effective_index is None or effective_index < 0 or effective_index >= len(data):
            data.append(new_item)
        else:
            data[effective_index] = new_item
        yaml_content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        filepath.write_text(yaml_content, encoding="utf-8")
        # Invalidate YAML cache for this file; next read will reload from disk
        try:
            YAML_CACHE.pop(filename, None)
        except Exception:
            pass
        flash("Gespeichert", "success")
        return redirect(url_for("admin_manage", filename=filename))
    return render_template(
        "admin_item.html",
        filename=filename,
        item=item,
        index=index,
        section=section,
        schema=schema,
        extra_fields=extra_fields
    )


@app.route("/admin/manage/<path:filename>/<int:index>/delete", methods=["POST"])
@login_required
def admin_delete(filename, index):
    section = get_admin_section(filename)
    if section.get("read_only"):
        abort(403)
    data = load_yaml(filename)
    if not isinstance(data, list) or index < 0 or index >= len(data):
        abort(404)
    removed = data.pop(index)
    schema = section.get("schema")
    cleanup_entry_media(removed, schema)
    filepath = CONFIG_DIR / filename
    yaml_content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    filepath.write_text(yaml_content, encoding="utf-8")
    try:
        YAML_CACHE.pop(filename, None)
    except Exception:
        pass
    flash("Eintrag gelöscht.", "success")
    return redirect(url_for("admin_manage", filename=filename))


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
    news_items    = load_news_items()
    news_settings = load_news_settings()
    news_limit    = news_settings.get("homepage_limit", DEFAULT_NEWS_SETTINGS["homepage_limit"])
    sorted_news   = sorted(news_items,
                           key=lambda n: n.get("_dt", datetime.min),
                           reverse=True)
    news_teaser   = sorted_news[:news_limit] if news_limit else []
    now = datetime.now(tz=tz.gettz("Europe/Berlin"))

    return render_template(
        "index.html",
        slides       = prepare_slides(),
        opening      = get_next_opening(),
        home_flippers= home_flippers,
        latest_news  = news_teaser,
        now          = now,
        stack_news_cards=len(news_teaser) > 2
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
    visible_news = load_news_items()

    # -----------------------
    # URL‑Parameter auslesen
    # -----------------------
    years_param         = request.args.getlist("year")
    selected_categories = request.args.getlist("category")
    q                   = request.args.get("q", "").strip()

    # -----------------------
    # Zusatzinfos vorbereiten
    # -----------------------
    news = list(visible_news)

    # -----------------------
    # Filter anwenden
    # -----------------------
    # Filter by one or multiple years chosen via checkboxes
    if years_param:
        try:
            years_sel = {int(y) for y in years_param if str(y).strip()}
        except ValueError:
            years_sel = set()
        if years_sel:
            news = [n for n in news if n.get("_year") in years_sel]
    if selected_categories:
        news = [n for n in news if n.get("category") in selected_categories]
    if q:
        q_lower = q.lower()
        news = [n for n in news if q_lower in n.get("title", "").lower()]

    # -----------------------
    # Sortierung
    # -----------------------
    news.sort(key=lambda x: x.get("_dt", datetime.min), reverse=True)

    # -----------------------
    # Dropdown‑Werte berechnen
    # -----------------------
    years = sorted({n.get("_year") for n in visible_news if n.get("_year")}, reverse=True)
    categories = sorted({n.get("category") for n in visible_news if n.get("category")})

    return render_template(
        "news_list.html",
        news=news,
        years=years,
        categories=categories,
        opening=get_next_opening()
    )

@app.route("/news/<slug>")
def news_detail(slug):
    news = load_news_items(include_hidden=True)
    article = next((n for n in news if n["slug"] == slug), None)
    if article is None or not news_is_visible(article):
        return redirect(url_for("news_list"))
    if article.get("youtube_links"):
        g.force_cookie_banner = True
    return render_template("news_detail.html",
                           article = article,
                           opening = get_next_opening())

@app.route("/kontakt", methods=["GET", "POST"])
def kontakt():
    ip = request.remote_addr or "?"

    def _save_submission(payload: dict):
        path = CONFIG_DIR / "contact_submissions.yaml"
        try:
            existing = []
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or []
            existing.append(payload)
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(existing, f, allow_unicode=True, sort_keys=False)
        except Exception as e:
            raise e

    def _generate_captcha():
        a, b = random.randint(1, 9), random.randint(1, 9)
        session["captcha_answer"] = str(a + b)
        return f"{a} + {b}"

    def _attempt_info():
        info = CONTACT_ATTEMPTS.get(ip)
        if info and time() - info[1] > CONTACT_WINDOW_SECONDS:
            CONTACT_ATTEMPTS.pop(ip, None)
            return None
        return info

    def _register_attempt():
        info = _attempt_info()
        if info:
            CONTACT_ATTEMPTS[ip] = (info[0] + 1, info[1])
        else:
            CONTACT_ATTEMPTS[ip] = (1, time())

    def _is_rate_limited():
        info = _attempt_info()
        return info and info[0] >= CONTACT_MAX_ATTEMPTS

    if request.method == "POST":
        # Honeypot
        if request.form.get("website"):
            # silently ignore as success
            flash("Nachricht gesendet.", "success")
            return redirect(url_for("kontakt"))

        if _is_rate_limited():
            flash("Zu viele Anfragen. Bitte später erneut versuchen.", "danger")
            app.logger.warning(
                "Kontaktformular: Rate limit ausgelöst: ip=%s ua=%s",
                ip, request.headers.get("User-Agent", "")
            )
            return redirect(url_for("kontakt"))
        _register_attempt()

        name    = request.form.get("name", "").strip()
        email   = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()
        consent = request.form.get("consent") == "on"
        captcha = request.form.get("captcha", "").strip()

        if not (name and email and message and consent and captcha):
            flash("Bitte alle Pflichtfelder ausfüllen und zustimmen.", "warning")
            return redirect(url_for("kontakt"))
        if captcha != session.get("captcha_answer"):
            flash("Captcha falsch", "warning")
            app.logger.warning(
                "Kontaktformular: Captcha falsch: ip=%s ua=%s",
                ip, request.headers.get("User-Agent", "")
            )
            return redirect(url_for("kontakt"))

        payload = {
            "name": name,
            "email": email,
            "message": message,
            "timestamp": datetime.now(tz=tz.gettz("Europe/Berlin")).isoformat(),
            "ip": request.remote_addr,
            "ua": request.headers.get("User-Agent", "")
        }
        try:
            send_contact_email(payload)
        except SMTPConfigurationError as exc:
            app.logger.error("Kontaktformular: SMTP-Konfiguration fehlt: %s", exc)
            flash("Der Mail-Versand ist derzeit nicht konfiguriert. Bitte versuchen Sie es später erneut.", "danger")
            return redirect(url_for("kontakt"))
        except Exception as exc:
            app.logger.exception("Kontaktformular: Versand fehlgeschlagen")
            flash("Nachricht konnte nicht gesendet werden. Bitte versuchen Sie es später erneut.", "danger")
            return redirect(url_for("kontakt"))
        session.pop("captcha_answer", None)
        try:
            _save_submission(payload)
        except Exception as e:
            app.logger.exception("Kontaktformular: Speicherung fehlgeschlagen")
            flash(f"Nachricht gesendet, aber Archivierung fehlgeschlagen: {e}", "warning")
        else:
            flash("Danke! Wir melden uns zeitnah bei dir.", "success")
        return redirect(url_for("kontakt"))

    question = _generate_captcha()
    return render_template("contact.html", opening=get_next_opening(), captcha_question=question)

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
    for n in load_news_items():
        dt = n.get("_dt")
        lastmod = dt.date().isoformat() if dt and dt != datetime.min else None
        entry = {"loc": url_for('news_detail', slug=n["slug"], _external=True)}
        if lastmod:
            entry["lastmod"] = lastmod
        pages.append(entry)
    xml = render_template("sitemap.xml.j2", pages=pages)
    return Response(xml, mimetype="application/xml")

# --------------------------------------------------
# Local run (Dockerfile startet ebenfalls so)
# --------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
def _remove_static_file(path_value):
    if not path_value or not isinstance(path_value, str):
        return
    if path_value.startswith(("http://", "https://", "//")):
        return
    rel = path_value.lstrip("/")
    target = STATIC_DIR / rel
    try:
        if target.is_file():
            target.unlink()
    except Exception as exc:
        app.logger.warning("Could not delete media %s: %s", target, exc)


def cleanup_entry_media(entry, schema):
    if not schema or not isinstance(entry, dict):
        return
    for field in schema:
        name = field.get("name")
        ftype = field.get("type")
        if not name or name not in entry:
            continue
        value = entry.get(name)
        if ftype == "image" and isinstance(value, str):
            _remove_static_file(value)
        elif ftype == "image_list":
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        _remove_static_file(item)
        elif ftype == "list" and field.get("cleanup") == "image":
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        _remove_static_file(item)
