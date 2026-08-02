"""
Intern Blueprint — Aixtraball Mitgliederportal
"""

from __future__ import annotations

import time

import yaml
from flask import Blueprint, Flask, Request, abort, g, request

import re
import unicodedata

from .models import Base, Machine, Member, SessionLocal, engine

BUILD_ID = f"intern-{int(time.time())}"

intern_bp = Blueprint(
    "intern",
    __name__,
    url_prefix="/intern",
    static_folder="../../static/intern",
    static_url_path="/static/intern",
)


def get_db():
    if "db" not in g:
        g.db = SessionLocal()
    return g.db


@intern_bp.teardown_request
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        if exc is not None:
            try:
                db.rollback()
            except Exception:
                pass
        db.close()


@intern_bp.before_request
def _enforce_csrf():
    """Every intern template already renders a csrf_token hidden field
    (see auth.generate_csrf_token), but nothing validated it on submit -
    every mutating POST route in the portal was forgeable cross-site.
    This applies to intern's own routes and all its nested blueprints
    (Flask cascades before_request hooks down the blueprint-name hierarchy)."""
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return
    from .auth import check_csrf
    if not check_csrf():
        abort(400, description="CSRF-Token fehlt oder ist ungültig. Bitte Seite neu laden und erneut versuchen.")


@intern_bp.after_request
def add_noindex(response):
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _name_to_email(name: str) -> str:
    """'Christian Blatzheim' → 'christian.blatzheim@aixtraball.de'"""
    # Normalise umlauts before stripping accents
    replacements = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                    "Ä": "ae", "Ö": "oe", "Ü": "ue"}
    for ch, rep in replacements.items():
        name = name.replace(ch, rep)
    # Strip remaining accents / non-ASCII
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    # Keep only letters, digits, spaces, hyphens
    name = re.sub(r"[^a-zA-Z0-9 \-]", "", name).strip().lower()
    parts = name.split()
    return ".".join(parts) + "@aixtraball.de"


def _sync_members_from_yaml(app: Flask) -> None:
    config_dir = app.root_path + "/config"
    try:
        with open(f"{config_dir}/members.yaml", encoding="utf-8") as f:
            members_data = yaml.safe_load(f) or []
    except FileNotFoundError:
        app.logger.warning("members.yaml not found — skipping member sync")
        return

    db = SessionLocal()
    try:
        for m in members_data:
            name = (m.get("name") or "").strip()
            if not name:
                continue
            email = _name_to_email(name)
            existing = db.query(Member).filter_by(email=email).first()
            if existing is None:
                db.add(Member(email=email, display_name=name, is_active=True))
            elif existing.display_name != name:
                existing.display_name = name
        db.commit()
    except Exception as exc:
        db.rollback()
        app.logger.error("Member sync failed: %s", exc)
    finally:
        db.close()


def _sync_machines_from_yaml(app: Flask) -> None:
    config_dir = app.root_path + "/config"
    try:
        with open(f"{config_dir}/flippers.yaml", encoding="utf-8") as f:
            flippers = yaml.safe_load(f) or []
    except FileNotFoundError:
        app.logger.warning("flippers.yaml not found — skipping machine sync")
        return

    db = SessionLocal()
    try:
        for flipper in flippers:
            name = flipper.get("name", "").strip()
            if not name:
                continue
            existing = db.query(Machine).filter_by(yaml_name=name).first()
            if existing is None:
                machine = Machine(
                    yaml_name=name,
                    display_name=name,
                    manufacturer=flipper.get("manufacturer"),
                    year=str(flipper.get("year", ""))[:20] if flipper.get("year") else None,
                )
                db.add(machine)
        db.commit()
    except Exception as exc:
        db.rollback()
        app.logger.error("Machine sync failed: %s", exc)
    finally:
        db.close()


MAX_FORM_MEMORY_SIZE = 25 * 1024 * 1024  # 25 MB, up from Werkzeug's 500 KB default


class _LargeFormRequest(Request):
    """Werkzeug limits form-body parsing to 500 KB (max_form_memory_size) by
    default. The intern portal handles rich-text content with embedded
    media, so that limit is raised - but NOT removed entirely (max_form_memory_size
    = None previously disabled body-size protection site-wide, letting any
    client, on any route, send an unbounded request body as a trivial DoS)."""
    max_form_memory_size = MAX_FORM_MEMORY_SIZE


def create_intern_blueprint(app: Flask) -> None:
    from datetime import timedelta
    app.request_class = _LargeFormRequest
    app.config["MAX_CONTENT_LENGTH"] = MAX_FORM_MEMORY_SIZE
    app.config.setdefault("PERMANENT_SESSION_LIFETIME", timedelta(days=30))

    # Create all tables (idempotent)
    Base.metadata.create_all(engine)

    # Migrate: add new columns to auth_token if they don't exist yet
    with engine.connect() as conn:
        for col, definition in [
            ("pin_code", "VARCHAR(6)"),
            ("attempt_count", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            try:
                conn.execute(__import__("sqlalchemy").text(
                    f"ALTER TABLE auth_token ADD COLUMN {col} {definition}"
                ))
                conn.commit()
            except Exception:
                pass  # column already exists

    with engine.connect() as conn:
        for col, definition in [
            ("section", "VARCHAR(100)"),
            # event.min_members
        ]:
            try:
                conn.execute(__import__("sqlalchemy").text(
                    f"ALTER TABLE info_page ADD COLUMN {col} {definition}"
                ))
                conn.commit()
            except Exception:
                pass

    with engine.connect() as conn:
        try:
            conn.execute(__import__("sqlalchemy").text(
                "ALTER TABLE event ADD COLUMN min_members INTEGER"
            ))
            conn.commit()
        except Exception:
            pass

    # Sync machines and members from YAML
    _sync_machines_from_yaml(app)
    _sync_members_from_yaml(app)

    # Register route modules
    from .routes_pwa import pwa_bp
    from .routes_auth import auth_bp
    from .routes_dashboard import dashboard_bp
    from .routes_calendar import calendar_bp
    from .routes_repairs import repairs_bp
    from .routes_info import info_bp
    from .routes_contacts import contacts_bp
    from .routes_todos import todos_bp
    from .routes_parts import parts_bp

    intern_bp.register_blueprint(pwa_bp)
    intern_bp.register_blueprint(auth_bp)
    intern_bp.register_blueprint(dashboard_bp)
    intern_bp.register_blueprint(calendar_bp)
    intern_bp.register_blueprint(repairs_bp)
    intern_bp.register_blueprint(info_bp)
    intern_bp.register_blueprint(contacts_bp)
    intern_bp.register_blueprint(todos_bp)
    intern_bp.register_blueprint(parts_bp)

    # Make generate_csrf_token and build_id available in all intern templates
    from .auth import generate_csrf_token
    app.jinja_env.globals["generate_csrf_token"] = generate_csrf_token
    app.jinja_env.globals["intern_build_id"] = BUILD_ID

    app.register_blueprint(intern_bp)
