"""
Magic-link authentication routes for the intern portal.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from time import time

from flask import (
    Blueprint, flash, redirect, render_template,
    request, session, url_for,
)

from .models import AuthToken, Member, now_utc
from .email import send_magic_link_email
from .auth import generate_csrf_token, member_required
from . import get_db

auth_bp = Blueprint("auth", __name__)

_LOGIN_ATTEMPTS: dict[str, tuple[int, float]] = {}
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 15 * 60
_MAX_PIN_ATTEMPTS = 5

VALID_EMAIL_RE = re.compile(r"^[^@\s]+@aixtraball\.de$", re.IGNORECASE)


def _generate_pin() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _check_rate_limit(ip: str) -> bool:
    now = time()
    entry = _LOGIN_ATTEMPTS.get(ip)
    if entry:
        count, first_ts = entry
        if now - first_ts < _LOCKOUT_SECONDS:
            if count >= _MAX_ATTEMPTS:
                return False
        else:
            del _LOGIN_ATTEMPTS[ip]
    return True


def _record_attempt(ip: str) -> None:
    now = time()
    entry = _LOGIN_ATTEMPTS.get(ip)
    if entry:
        count, first_ts = entry
        _LOGIN_ATTEMPTS[ip] = (count + 1, first_ts) if now - first_ts < _LOCKOUT_SECONDS else (1, now)
    else:
        _LOGIN_ATTEMPTS[ip] = (1, now)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("member_id"):
        return redirect(url_for("intern.dashboard.index"))

    csrf_token = generate_csrf_token()

    # ── Step 1: E-Mail eingeben ──────────────────────────────────────────────
    if request.method == "POST":
        ip = request.remote_addr or "unknown"

        if not _check_rate_limit(ip):
            flash("Zu viele Versuche. Bitte warte 15 Minuten.", "error")
            return render_template("intern/login.html", step="email", csrf_token=csrf_token)

        email = (request.form.get("email") or "").strip().lower()

        if not VALID_EMAIL_RE.match(email):
            _record_attempt(ip)
            flash("Nur @aixtraball.de-Adressen sind gültig.", "error")
            return render_template("intern/login.html", step="email", csrf_token=csrf_token)

        db = get_db()
        member = db.query(Member).filter_by(email=email).first()
        if member is None:
            member = Member(email=email, display_name=email.split("@")[0])
            db.add(member)
            db.flush()

        for t in db.query(AuthToken).filter(
            AuthToken.member_id == member.id,
            AuthToken.used_at.is_(None),
        ).all():
            t.used_at = now_utc()

        pin_code = _generate_pin()
        token_str = secrets.token_urlsafe(48)
        expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=15)
        db.add(AuthToken(
            member_id=member.id,
            token=token_str,
            pin_code=pin_code,
            expires_at=expires,
        ))
        db.commit()

        verify_url = url_for("intern.auth.verify", token=token_str, _external=True)
        logo_url = url_for("static", filename="images/logo_Inv.png", _external=True)
        try:
            send_magic_link_email(email, verify_url, pin_code, logo_url)
        except Exception as exc:
            from flask import current_app
            current_app.logger.error("Magic link email failed: %s", exc)
            flash("E-Mail konnte nicht gesendet werden. Bitte SMTP prüfen.", "error")
            return render_template("intern/login.html", step="email", csrf_token=csrf_token)

        # Store email in session so the code step knows who we're waiting for
        session["pending_login_email"] = email
        return redirect(url_for("intern.auth.login_code"))

    # ── GET: show e-mail form ────────────────────────────────────────────────
    session.pop("pending_login_email", None)
    return render_template("intern/login.html", step="email", csrf_token=csrf_token)


@auth_bp.route("/login/code", methods=["GET", "POST"])
def login_code():
    """Step 2: enter the 6-digit PIN received by e-mail."""
    if session.get("member_id"):
        return redirect(url_for("intern.dashboard.index"))

    csrf_token = generate_csrf_token()
    email = session.get("pending_login_email", "")

    if not email:
        # Landed here without going through step 1
        return redirect(url_for("intern.auth.login"))

    if request.method == "POST":
        pin = (request.form.get("pin") or "").strip()

        if not pin:
            flash("Bitte gib deinen 6-stelligen Code ein.", "error")
            return render_template("intern/login.html", step="code", email=email, csrf_token=csrf_token)

        db = get_db()
        now = now_utc()

        member = db.query(Member).filter_by(email=email, is_active=True).first()
        if not member:
            flash("Kein aktives Konto gefunden.", "error")
            return redirect(url_for("intern.auth.login"))

        token = db.query(AuthToken).filter(
            AuthToken.member_id == member.id,
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > now,
        ).order_by(AuthToken.created_at.desc()).first()

        if not token:
            flash("Der Code ist abgelaufen. Bitte neuen Code anfordern.", "error")
            session.pop("pending_login_email", None)
            return redirect(url_for("intern.auth.login"))

        if token.attempt_count >= _MAX_PIN_ATTEMPTS:
            flash("Zu viele Fehlversuche – der Code ist gesperrt. Bitte neuen Code anfordern.", "error")
            session.pop("pending_login_email", None)
            return redirect(url_for("intern.auth.login"))

        if token.pin_code != pin:
            token.attempt_count += 1
            db.commit()
            remaining = _MAX_PIN_ATTEMPTS - token.attempt_count
            if remaining <= 0:
                flash("Falscher Code – maximale Versuche erreicht. Bitte neuen Code anfordern.", "error")
                session.pop("pending_login_email", None)
                return redirect(url_for("intern.auth.login"))
            flash(
                f"Falscher Code. Noch {remaining} Versuch{'e' if remaining != 1 else ''}.",
                "error",
            )
            return render_template("intern/login.html", step="code", email=email, csrf_token=csrf_token)

        token.used_at = now
        member.last_login = now
        db.commit()

        session.pop("pending_login_email", None)
        session.clear()
        session["member_id"] = member.id
        session["member_email"] = member.email
        session.permanent = True
        return redirect(url_for("intern.dashboard.index"))

    return render_template("intern/login.html", step="code", email=email, csrf_token=csrf_token)


@auth_bp.route("/verify")
def verify():
    """Magic link URL token (one-click login from e-mail)."""
    token_str = request.args.get("token", "")
    if not token_str:
        flash("Ungültiger Link.", "error")
        return redirect(url_for("intern.auth.login"))

    db = get_db()
    now = now_utc()
    token = db.query(AuthToken).filter(
        AuthToken.token == token_str,
        AuthToken.used_at.is_(None),
    ).first()

    if not token or token.expires_at < now:
        flash("Der Link ist abgelaufen oder wurde bereits verwendet. Bitte neu anfordern.", "error")
        return redirect(url_for("intern.auth.login"))

    member = db.get(Member, token.member_id)
    if not member or not member.is_active:
        flash("Kein aktives Konto für diese E-Mail-Adresse.", "error")
        return redirect(url_for("intern.auth.login"))

    token.used_at = now
    member.last_login = now
    db.commit()

    session.clear()
    session["member_id"] = member.id
    session["member_email"] = member.email
    session.permanent = True
    return redirect(url_for("intern.dashboard.index"))


@auth_bp.route("/logout")
def logout():
    session.pop("member_id", None)
    session.pop("member_email", None)
    flash("Du wurdest abgemeldet.", "success")
    return redirect(url_for("intern.auth.login"))
