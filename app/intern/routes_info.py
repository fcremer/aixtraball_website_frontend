"""
Information pages (Informationen) routes for the intern portal.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from flask import (
    Blueprint, flash, g, jsonify, redirect, render_template, request, url_for,
)
from werkzeug.utils import secure_filename

from .auth import member_required, generate_csrf_token
from .models import InfoPage, now_utc
from . import get_db

INFO_UPLOAD_DIR = Path(__file__).parent.parent / "static" / "intern" / "uploads" / "info"
INFO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "avif"}

info_bp = Blueprint("info", __name__)


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[äÄ]", "ae", text)
    text = re.sub(r"[öÖ]", "oe", text)
    text = re.sub(r"[üÜ]", "ue", text)
    text = re.sub(r"ß", "ss", text)
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def _unique_slug(db, title: str, exclude_id: int | None = None) -> str:
    base = _slugify(title) or "seite"
    slug = base
    i = 1
    while True:
        q = db.query(InfoPage).filter_by(slug=slug)
        if exclude_id:
            q = q.filter(InfoPage.id != exclude_id)
        if not q.first():
            return slug
        slug = f"{base}-{i}"
        i += 1


@info_bp.route("/informationen/")
@member_required
def list_pages():
    db = get_db()
    q = request.args.get("q", "").strip()
    query = db.query(InfoPage).filter_by(is_published=True)
    if q:
        query = query.filter(InfoPage.title.ilike(f"%{q}%"))
    pages = query.order_by(InfoPage.section.nulls_last(), InfoPage.updated_at.desc()).all()
    # Group by section
    sections: dict[str, list] = {}
    for page in pages:
        key = page.section or ""
        sections.setdefault(key, []).append(page)
    return render_template(
        "intern/info_list.html", active_tab="informationen",
        sections=sections, search=q,
    )


@info_bp.route("/informationen/bild-upload", methods=["POST"])
@member_required
def upload_image():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Keine Datei"}), 400
    ext = secure_filename(f.filename).rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({"error": "Dateityp nicht erlaubt"}), 400
    filename = f"{uuid.uuid4().hex}.{ext}"
    f.save(INFO_UPLOAD_DIR / filename)
    return jsonify({"url": url_for("static", filename=f"intern/uploads/info/{filename}")})


@info_bp.route("/informationen/neu", methods=["GET", "POST"])
@member_required
def new_page():
    csrf_token = generate_csrf_token()
    db = get_db()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content_html = request.form.get("content_html", "").strip()
        section = request.form.get("section", "").strip() or None
        if not title:
            flash("Titel ist ein Pflichtfeld.", "error")
        else:
            slug = _unique_slug(db, title)
            page = InfoPage(
                title=title,
                slug=slug,
                section=section,
                content_html=content_html,
                created_by=g.current_member.id,
            )
            db.add(page)
            db.commit()
            flash("Seite erstellt.", "success")
            return redirect(url_for("intern.info.view_page", slug=slug))
    existing_sections = [
        s for (s,) in db.query(InfoPage.section).filter(InfoPage.section.isnot(None)).distinct().all()
    ]
    return render_template("intern/info_form.html", active_tab="informationen", csrf_token=csrf_token,
                           existing_sections=existing_sections)


@info_bp.route("/informationen/<slug>")
@member_required
def view_page(slug: str):
    db = get_db()
    page = db.query(InfoPage).filter_by(slug=slug, is_published=True).first()
    if not page:
        flash("Seite nicht gefunden.", "error")
        return redirect(url_for("intern.info.list_pages"))
    return render_template("intern/info_detail.html", active_tab="informationen", page=page)


@info_bp.route("/informationen/<slug>/bearbeiten", methods=["GET", "POST"])
@member_required
def edit_page(slug: str):
    csrf_token = generate_csrf_token()
    db = get_db()
    page = db.query(InfoPage).filter_by(slug=slug).first()
    if not page:
        flash("Seite nicht gefunden.", "error")
        return redirect(url_for("intern.info.list_pages"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content_html = request.form.get("content_html", "").strip()
        if not title:
            flash("Titel ist ein Pflichtfeld.", "error")
        else:
            new_slug = _unique_slug(db, title, exclude_id=page.id)
            page.title = title
            page.slug = new_slug
            page.section = request.form.get("section", "").strip() or None
            page.content_html = content_html
            page.updated_by = g.current_member.id
            page.updated_at = now_utc()
            db.commit()
            flash("Seite aktualisiert.", "success")
            return redirect(url_for("intern.info.view_page", slug=page.slug))

    existing_sections = [
        s for (s,) in db.query(InfoPage.section).filter(InfoPage.section.isnot(None)).distinct().all()
    ]
    return render_template(
        "intern/info_form.html", active_tab="informationen",
        page=page, csrf_token=csrf_token,
        existing_sections=existing_sections,
    )


@info_bp.route("/informationen/<slug>/loeschen", methods=["POST"])
@member_required
def delete_page(slug: str):
    db = get_db()
    page = db.query(InfoPage).filter_by(slug=slug).first()
    if page:
        db.delete(page)
        db.commit()
        flash("Seite gelöscht.", "success")
    return redirect(url_for("intern.info.list_pages"))
