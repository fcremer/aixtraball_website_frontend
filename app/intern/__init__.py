"""
Intern Blueprint — Aixtraball Mitgliederportal
"""

from __future__ import annotations

import time

import yaml
from flask import Blueprint, Flask, Request, g

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
            try:
                existing = db.query(Member).filter_by(email=email).first()
                if existing is None:
                    db.add(Member(email=email, display_name=name, is_active=True))
                    db.flush()
                elif existing.display_name != name:
                    existing.display_name = name
            except Exception:
                db.rollback()
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


class _UnlimitedRequest(Request):
    """Werkzeug limits form-body parsing to 500 KB (max_form_memory_size) by default.
    The intern portal handles large HTML content with embedded media, so we remove that limit."""
    max_form_memory_size = None


def create_intern_blueprint(app: Flask) -> None:
    from datetime import timedelta
    app.request_class = _UnlimitedRequest
    app.config["MAX_CONTENT_LENGTH"] = None
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
