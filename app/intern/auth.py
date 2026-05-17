"""
Member authentication helpers for the intern portal.
"""

from __future__ import annotations

import secrets
from functools import wraps

from flask import g, redirect, session, url_for

from .models import Member, SessionLocal


def member_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        member_id = session.get("member_id")
        if not member_id:
            return redirect(url_for("intern.auth.login"))
        db = _get_db_for_auth()
        member = db.get(Member, member_id)
        if not member or not member.is_active:
            session.pop("member_id", None)
            session.pop("member_email", None)
            return redirect(url_for("intern.auth.login"))
        g.current_member = member
        return view(*args, **kwargs)
    return wrapped


def get_current_member() -> Member | None:
    return getattr(g, "current_member", None)


def _get_db_for_auth():
    if "db" not in g:
        g.db = SessionLocal()
    return g.db


def generate_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


def check_csrf() -> bool:
    token = session.get("csrf_token")
    return token and request.form.get("csrf_token") == token


# Import here to avoid circular at module load
from flask import request  # noqa: E402
