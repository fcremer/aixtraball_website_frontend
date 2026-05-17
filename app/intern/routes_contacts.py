"""
Contacts (Kontakte) routes for the intern portal.
"""

from __future__ import annotations

from flask import (
    Blueprint, Response, flash, g, redirect,
    render_template, request, url_for,
)

from .auth import member_required, generate_csrf_token
from .models import Contact, now_utc
from . import get_db

contacts_bp = Blueprint("contacts", __name__)


@contacts_bp.route("/kontakte/")
@member_required
def list_contacts():
    db = get_db()
    q = request.args.get("q", "").strip()
    query = db.query(Contact).order_by(Contact.name)
    if q:
        query = query.filter(Contact.name.ilike(f"%{q}%"))
    contacts = query.all()
    return render_template(
        "intern/contacts_list.html", active_tab="kontakte",
        contacts=contacts, search=q,
    )


@contacts_bp.route("/kontakte/neu", methods=["GET", "POST"])
@member_required
def new_contact():
    csrf_token = generate_csrf_token()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name ist ein Pflichtfeld.", "error")
        else:
            db = get_db()
            contact = Contact(
                name=name,
                phone=request.form.get("phone", "").strip() or None,
                email=request.form.get("email", "").strip() or None,
                note=request.form.get("note", "").strip() or None,
                created_by=g.current_member.id,
            )
            db.add(contact)
            db.commit()
            flash("Kontakt gespeichert.", "success")
            return redirect(url_for("intern.contacts.list_contacts"))
    return render_template("intern/contact_form.html", active_tab="kontakte", csrf_token=csrf_token)


@contacts_bp.route("/kontakte/<int:contact_id>/bearbeiten", methods=["GET", "POST"])
@member_required
def edit_contact(contact_id: int):
    csrf_token = generate_csrf_token()
    db = get_db()
    contact = db.get(Contact, contact_id)
    if not contact:
        flash("Kontakt nicht gefunden.", "error")
        return redirect(url_for("intern.contacts.list_contacts"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name ist ein Pflichtfeld.", "error")
        else:
            contact.name = name
            contact.phone = request.form.get("phone", "").strip() or None
            contact.email = request.form.get("email", "").strip() or None
            contact.note = request.form.get("note", "").strip() or None
            contact.updated_at = now_utc()
            db.commit()
            flash("Kontakt aktualisiert.", "success")
            return redirect(url_for("intern.contacts.list_contacts"))

    return render_template(
        "intern/contact_form.html", active_tab="kontakte",
        contact=contact, csrf_token=csrf_token,
    )


@contacts_bp.route("/kontakte/<int:contact_id>/loeschen", methods=["POST"])
@member_required
def delete_contact(contact_id: int):
    db = get_db()
    contact = db.get(Contact, contact_id)
    if contact:
        db.delete(contact)
        db.commit()
        flash("Kontakt gelöscht.", "success")
    return redirect(url_for("intern.contacts.list_contacts"))


@contacts_bp.route("/kontakte/<int:contact_id>/vcard")
@member_required
def vcard(contact_id: int):
    db = get_db()
    contact = db.get(Contact, contact_id)
    if not contact:
        flash("Kontakt nicht gefunden.", "error")
        return redirect(url_for("intern.contacts.list_contacts"))
    vc = _build_vcard(contact)
    safe_name = "".join(c for c in contact.name if c.isalnum() or c in " -").strip().replace(" ", "_")
    resp = Response(vc, content_type="text/vcard; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="{safe_name}.vcf"'
    return resp


@contacts_bp.route("/kontakte/export.vcf")
@member_required
def export_all():
    db = get_db()
    contacts = db.query(Contact).order_by(Contact.name).all()
    vc = "\n".join(_build_vcard(c) for c in contacts)
    resp = Response(vc, content_type="text/vcard; charset=utf-8")
    resp.headers["Content-Disposition"] = 'attachment; filename="aixtraball_kontakte.vcf"'
    return resp


def _build_vcard(contact: Contact) -> str:
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{contact.name}"]
    if contact.phone:
        lines.append(f"TEL;TYPE=CELL:{contact.phone}")
    if contact.email:
        lines.append(f"EMAIL:{contact.email}")
    if contact.note:
        note_escaped = contact.note.replace("\n", "\\n")
        lines.append(f"NOTE:{note_escaped}")
    lines.append("END:VCARD")
    return "\n".join(lines)
