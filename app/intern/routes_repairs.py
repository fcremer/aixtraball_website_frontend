"""
Repair log (Reparaturen) routes for the intern portal.
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import (
    Blueprint, current_app, flash, g, redirect,
    render_template, request, url_for,
)
from werkzeug.utils import secure_filename

from .auth import member_required, generate_csrf_token
from .models import Machine, Member, Repair, RepairComment, RepairMedia, RepairSubscription, now_utc
from . import get_db

repairs_bp = Blueprint("repairs", __name__)

REPAIR_CATEGORIES = ["Mechanisch", "Elektronisch", "Software", "Optik", "Reinigung", "Sonstiges"]
REPAIR_STATUSES = [
    ("open", "Offen"),
    ("in_progress", "In Bearbeitung"),
    ("resolved", "Behoben"),
    ("wont_fix", "Nicht beheben"),
]
REPAIR_PRIORITIES = [
    ("low", "Niedrig"),
    ("normal", "Normal"),
    ("high", "Hoch"),
    ("critical", "Kritisch"),
]
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif", "video/mp4", "video/quicktime"}
UPLOAD_DIR = Path(__file__).parent.parent / "static" / "intern" / "uploads"


_PRIORITY_ORDER = {"critical": 0, "high": 1, "normal": 2, "low": 3}


@repairs_bp.route("/reparaturen/")
@member_required
def list_repairs():
    db = get_db()
    open_repairs = (
        db.query(Repair)
        .filter(Repair.status.in_(["open", "in_progress"]))
        .all()
    )
    open_repairs.sort(key=lambda r: (
        _PRIORITY_ORDER.get(r.priority, 2),
        r.created_at,
    ))
    return render_template(
        "intern/repairs_overview.html", active_tab="reparaturen",
        repairs=open_repairs,
        statuses=dict(REPAIR_STATUSES),
        priorities=dict(REPAIR_PRIORITIES),
    )


@repairs_bp.route("/reparaturen/maschinen")
@member_required
def list_machines():
    db = get_db()
    machines = db.query(Machine).filter_by(is_active=True).order_by(Machine.display_name).all()
    open_counts = {}
    for m in machines:
        open_counts[m.id] = (
            db.query(Repair)
            .filter_by(machine_id=m.id)
            .filter(Repair.status.in_(["open", "in_progress"]))
            .count()
        )
    machines = sorted(machines, key=lambda m: (0 if open_counts[m.id] > 0 else 1, m.display_name))
    defective_count = sum(1 for m in machines if open_counts[m.id] > 0)
    return render_template(
        "intern/repair_list.html", active_tab="reparaturen",
        machines=machines, open_counts=open_counts,
        defective_count=defective_count,
    )


@repairs_bp.route("/reparaturen/<int:machine_id>")
@member_required
def machine_repairs(machine_id: int):
    db = get_db()
    machine = db.get(Machine, machine_id)
    if not machine:
        flash("Flipper nicht gefunden.", "error")
        return redirect(url_for("intern.repairs.list_repairs"))
    repairs = (
        db.query(Repair)
        .filter_by(machine_id=machine_id)
        .order_by(Repair.created_at.desc())
        .all()
    )
    return render_template(
        "intern/machine_repairs.html", active_tab="reparaturen",
        machine=machine, repairs=repairs,
        statuses=dict(REPAIR_STATUSES),
    )


@repairs_bp.route("/reparaturen/<int:machine_id>/neu", methods=["GET", "POST"])
@member_required
def new_repair(machine_id: int):
    csrf_token = generate_csrf_token()
    db = get_db()
    machine = db.get(Machine, machine_id)
    if not machine:
        flash("Flipper nicht gefunden.", "error")
        return redirect(url_for("intern.repairs.list_repairs"))
    members = db.query(Member).filter_by(is_active=True).order_by(Member.email).all()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "Sonstiges")
        priority = request.form.get("priority", "normal")
        assigned_to = request.form.get("assigned_to") or None

        if not title:
            flash("Titel ist ein Pflichtfeld.", "error")
        else:
            repair = Repair(
                machine_id=machine_id,
                title=title,
                description=description or None,
                category=category,
                priority=priority,
                assigned_to=int(assigned_to) if assigned_to else None,
                created_by=g.current_member.id,
            )
            db.add(repair)
            db.commit()
            flash("Reparatur-Ticket erstellt.", "success")
            return redirect(url_for("intern.repairs.repair_detail", repair_id=repair.id))

    return render_template(
        "intern/repair_form.html", active_tab="reparaturen",
        machine=machine, members=members,
        categories=REPAIR_CATEGORIES,
        priorities=REPAIR_PRIORITIES,
        csrf_token=csrf_token,
    )


@repairs_bp.route("/reparaturen/ticket/<int:repair_id>")
@member_required
def repair_detail(repair_id: int):
    db = get_db()
    repair = db.get(Repair, repair_id)
    if not repair:
        flash("Ticket nicht gefunden.", "error")
        return redirect(url_for("intern.repairs.list_repairs"))
    is_subscribed = db.query(RepairSubscription).filter_by(
        member_id=g.current_member.id, repair_id=repair_id
    ).first() is not None
    return render_template(
        "intern/repair_detail.html", active_tab="reparaturen",
        repair=repair, is_subscribed=is_subscribed,
        statuses=dict(REPAIR_STATUSES),
        csrf_token=generate_csrf_token(),
    )


@repairs_bp.route("/reparaturen/ticket/<int:repair_id>/bearbeiten", methods=["GET", "POST"])
@member_required
def edit_repair(repair_id: int):
    csrf_token = generate_csrf_token()
    db = get_db()
    repair = db.get(Repair, repair_id)
    if not repair:
        flash("Ticket nicht gefunden.", "error")
        return redirect(url_for("intern.repairs.list_repairs"))
    members = db.query(Member).filter_by(is_active=True).order_by(Member.email).all()

    if request.method == "POST":
        repair.title = request.form.get("title", "").strip() or repair.title
        repair.description = request.form.get("description", "").strip() or None
        repair.category = request.form.get("category", repair.category)
        repair.priority = request.form.get("priority", repair.priority)
        repair.status = request.form.get("status", repair.status)
        assigned_to = request.form.get("assigned_to") or None
        repair.assigned_to = int(assigned_to) if assigned_to else None
        repair.updated_at = now_utc()
        db.commit()
        flash("Ticket aktualisiert.", "success")
        return redirect(url_for("intern.repairs.repair_detail", repair_id=repair_id))

    return render_template(
        "intern/repair_form.html", active_tab="reparaturen",
        repair=repair, machine=repair.machine, members=members,
        categories=REPAIR_CATEGORIES, priorities=REPAIR_PRIORITIES,
        statuses=REPAIR_STATUSES,
        csrf_token=csrf_token,
    )


@repairs_bp.route("/reparaturen/ticket/<int:repair_id>/status", methods=["POST"])
@member_required
def update_status(repair_id: int):
    new_status = request.form.get("status", "open")
    valid = {s for s, _ in REPAIR_STATUSES}
    db = get_db()
    repair = db.get(Repair, repair_id)
    if repair and new_status in valid:
        repair.status = new_status
        repair.updated_at = now_utc()
        db.commit()
    return redirect(url_for("intern.repairs.repair_detail", repair_id=repair_id))


@repairs_bp.route("/reparaturen/ticket/<int:repair_id>/kommentar", methods=["POST"])
@member_required
def add_comment(repair_id: int):
    body = request.form.get("body", "").strip()
    if not body:
        flash("Kommentar darf nicht leer sein.", "error")
        return redirect(url_for("intern.repairs.repair_detail", repair_id=repair_id))
    db = get_db()
    db.add(RepairComment(
        repair_id=repair_id,
        member_id=g.current_member.id,
        body=body,
    ))
    repair = db.get(Repair, repair_id)
    if repair:
        repair.updated_at = now_utc()
    db.commit()
    flash("Kommentar hinzugefügt.", "success")
    return redirect(url_for("intern.repairs.repair_detail", repair_id=repair_id))


@repairs_bp.route("/reparaturen/ticket/<int:repair_id>/media", methods=["POST"])
@member_required
def upload_media(repair_id: int):
    file = request.files.get("media_file")
    if not file or not file.filename:
        flash("Keine Datei ausgewählt.", "error")
        return redirect(url_for("intern.repairs.repair_detail", repair_id=repair_id))
    mime = file.content_type or ""
    if mime not in ALLOWED_MIME:
        flash("Dateityp nicht erlaubt (nur Bilder und MP4-Videos).", "error")
        return redirect(url_for("intern.repairs.repair_detail", repair_id=repair_id))
    safe_name = secure_filename(file.filename)
    dest_dir = UPLOAD_DIR / str(repair_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_name
    if dest_path.exists():
        stem, suffix = safe_name.rsplit(".", 1) if "." in safe_name else (safe_name, "")
        import uuid
        safe_name = f"{stem}_{uuid.uuid4().hex[:8]}.{suffix}"
        dest_path = dest_dir / safe_name
    file.save(str(dest_path))
    relative_filename = f"{repair_id}/{safe_name}"
    db = get_db()
    db.add(RepairMedia(
        repair_id=repair_id,
        filename=relative_filename,
        mime_type=mime,
        uploaded_by=g.current_member.id,
    ))
    db.commit()
    flash("Datei hochgeladen.", "success")
    return redirect(url_for("intern.repairs.repair_detail", repair_id=repair_id))


@repairs_bp.route("/reparaturen/ticket/<int:repair_id>/media/<int:media_id>/loeschen", methods=["POST"])
@member_required
def delete_media(repair_id: int, media_id: int):
    db = get_db()
    media = db.get(RepairMedia, media_id)
    if media and media.repair_id == repair_id:
        try:
            (UPLOAD_DIR / media.filename).unlink(missing_ok=True)
        except Exception:
            pass
        db.delete(media)
        db.commit()
        flash("Datei gelöscht.", "success")
    return redirect(url_for("intern.repairs.repair_detail", repair_id=repair_id))


@repairs_bp.route("/reparaturen/ticket/<int:repair_id>/abonnieren", methods=["POST"])
@member_required
def subscribe(repair_id: int):
    db = get_db()
    existing = db.query(RepairSubscription).filter_by(
        member_id=g.current_member.id, repair_id=repair_id
    ).first()
    if not existing:
        db.add(RepairSubscription(member_id=g.current_member.id, repair_id=repair_id))
        db.commit()
        flash("Du bekommst Updates zu dieser Reparatur.", "success")
    return redirect(url_for("intern.repairs.repair_detail", repair_id=repair_id))


@repairs_bp.route("/reparaturen/ticket/<int:repair_id>/abbestellen", methods=["POST"])
@member_required
def unsubscribe(repair_id: int):
    db = get_db()
    sub = db.query(RepairSubscription).filter_by(
        member_id=g.current_member.id, repair_id=repair_id
    ).first()
    if sub:
        db.delete(sub)
        db.commit()
        flash("Abo beendet.", "success")
    return redirect(url_for("intern.repairs.repair_detail", repair_id=repair_id))
