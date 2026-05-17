"""
Spare parts (Ersatzteile) routes for the intern portal.
"""

from __future__ import annotations

from flask import (
    Blueprint, flash, g, jsonify, redirect,
    render_template, request, url_for,
)

from .auth import member_required, generate_csrf_token
from .models import Manufacturer, Part, PartManufacturer, PartSynonym
from .search_parts import get_cached_parts, invalidate_cache, search_parts
from . import get_db

parts_bp = Blueprint("parts", __name__)


def _load_parts(db) -> list[dict]:
    """Load all parts with synonyms + manufacturers as plain dicts."""
    parts = db.query(Part).order_by(Part.name).all()
    return [p.to_dict() for p in parts]


def _loader(db):
    return lambda: _load_parts(db)


def _get_or_create_manufacturer(db, name: str) -> Manufacturer:
    m = db.query(Manufacturer).filter_by(name=name).first()
    if not m:
        m = Manufacturer(name=name)
        db.add(m)
        db.flush()
    return m


@parts_bp.route("/ersatzteile/")
@member_required
def list_parts():
    db = get_db()
    q = request.args.get("q", "").strip()
    all_parts = _load_parts(db)

    if q:
        results = search_parts(all_parts, q, limit=60)
    else:
        results = all_parts[:60]

    # If request is AJAX (fetch from search input), return JSON fragment
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(results)

    return render_template(
        "intern/parts_list.html",
        active_tab="ersatzteile",
        parts=results,
        search=q,
        total=len(all_parts),
        csrf_token=generate_csrf_token(),
    )


@parts_bp.route("/ersatzteile/suche")
@member_required
def search():
    """JSON search endpoint for live search."""
    db = get_db()
    q = request.args.get("q", "").strip()
    limit = min(int(request.args.get("limit", 40)), 100)
    all_parts = _load_parts(db)
    results = search_parts(all_parts, q, limit=limit) if q else all_parts[:limit]
    return jsonify(results)


@parts_bp.route("/ersatzteile/<int:part_id>")
@member_required
def part_detail(part_id: int):
    db = get_db()
    part = db.get(Part, part_id)
    if not part:
        flash("Ersatzteil nicht gefunden.", "error")
        return redirect(url_for("intern.parts.list_parts"))
    return render_template(
        "intern/part_detail.html",
        active_tab="ersatzteile",
        part=part,
        csrf_token=generate_csrf_token(),
    )


@parts_bp.route("/ersatzteile/neu", methods=["GET", "POST"])
@member_required
def new_part():
    csrf_token = generate_csrf_token()
    db = get_db()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name ist ein Pflichtfeld.", "error")
        else:
            part = Part(
                name=name,
                article_number=request.form.get("article_number", "").strip() or None,
                supplier=request.form.get("supplier", "").strip() or None,
                stock=int(request.form.get("stock", 0) or 0),
                shelf=request.form.get("shelf", "").strip() or None,
                bin=request.form.get("bin", "").strip() or None,
            )
            db.add(part)
            db.flush()
            _save_synonyms(db, part, request.form.get("synonyms", ""))
            _save_manufacturers(db, part, request.form.get("manufacturers", ""))
            db.commit()
            invalidate_cache()
            flash("Ersatzteil angelegt.", "success")
            return redirect(url_for("intern.parts.part_detail", part_id=part.id))

    return render_template(
        "intern/part_form.html",
        active_tab="ersatzteile",
        part=None,
        csrf_token=csrf_token,
    )


@parts_bp.route("/ersatzteile/<int:part_id>/bearbeiten", methods=["GET", "POST"])
@member_required
def edit_part(part_id: int):
    csrf_token = generate_csrf_token()
    db = get_db()
    part = db.get(Part, part_id)
    if not part:
        flash("Ersatzteil nicht gefunden.", "error")
        return redirect(url_for("intern.parts.list_parts"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name ist ein Pflichtfeld.", "error")
        else:
            part.name = name
            part.article_number = request.form.get("article_number", "").strip() or None
            part.supplier = request.form.get("supplier", "").strip() or None
            part.stock = int(request.form.get("stock", 0) or 0)
            part.shelf = request.form.get("shelf", "").strip() or None
            part.bin = request.form.get("bin", "").strip() or None
            _save_synonyms(db, part, request.form.get("synonyms", ""))
            _save_manufacturers(db, part, request.form.get("manufacturers", ""))
            db.commit()
            invalidate_cache()
            flash("Ersatzteil aktualisiert.", "success")
            return redirect(url_for("intern.parts.part_detail", part_id=part.id))

    return render_template(
        "intern/part_form.html",
        active_tab="ersatzteile",
        part=part,
        csrf_token=csrf_token,
    )


@parts_bp.route("/ersatzteile/<int:part_id>/bestand", methods=["POST"])
@member_required
def adjust_stock(part_id: int):
    db = get_db()
    part = db.get(Part, part_id)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if not part:
        if is_ajax:
            return jsonify({"error": "not_found"}), 404
        flash("Ersatzteil nicht gefunden.", "error")
        return redirect(url_for("intern.parts.list_parts"))
    try:
        delta = int(request.form.get("delta", 0))
    except ValueError:
        if is_ajax:
            return jsonify({"error": "invalid_delta"}), 400
        return redirect(url_for("intern.parts.part_detail", part_id=part_id))
    new_stock = part.stock + delta
    if new_stock < 0:
        if is_ajax:
            return jsonify({"error": "below_zero", "stock": part.stock}), 400
        flash("Bestand kann nicht negativ werden.", "error")
        return redirect(url_for("intern.parts.part_detail", part_id=part_id))
    part.stock = new_stock
    db.commit()
    invalidate_cache()
    if is_ajax:
        return jsonify({"stock": new_stock})
    return redirect(url_for("intern.parts.part_detail", part_id=part_id))


@parts_bp.route("/ersatzteile/<int:part_id>/loeschen", methods=["POST"])
@member_required
def delete_part(part_id: int):
    db = get_db()
    part = db.get(Part, part_id)
    if part:
        db.delete(part)
        db.commit()
        invalidate_cache()
        flash("Ersatzteil gelöscht.", "success")
    return redirect(url_for("intern.parts.list_parts"))


# ── helpers ──────────────────────────────────────────────────────────────────

def _save_synonyms(db, part: Part, raw: str) -> None:
    # Remove old synonyms, set new ones
    for s in list(part.synonyms):
        db.delete(s)
    for val in re.split(r"[;,]", raw):
        val = val.strip()
        if val:
            db.add(PartSynonym(part_id=part.id, synonym=val))


def _save_manufacturers(db, part: Part, raw: str) -> None:
    for pm in list(part.part_manufacturers):
        db.delete(pm)
    for val in re.split(r"[;,]", raw):
        val = val.strip()
        if val:
            m = _get_or_create_manufacturer(db, val)
            db.add(PartManufacturer(part_id=part.id, manufacturer_id=m.id))


import re
