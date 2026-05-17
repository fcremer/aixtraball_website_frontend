"""
Calendar (Termine) routes for the intern portal.
"""

from __future__ import annotations

from datetime import datetime, timezone

from flask import (
    Blueprint, Response, flash, g, redirect,
    render_template, request, url_for,
)

from .auth import member_required, generate_csrf_token
from .models import Event, EventAssignment, Member, now_utc
from . import get_db

calendar_bp = Blueprint("calendar", __name__)

EVENT_CATEGORIES = ["Öffnungstag", "Turnier", "Wartung", "Vereinstreffen", "Sonstiges"]


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


@calendar_bp.route("/termine/")
@member_required
def list_events():
    db = get_db()
    now = now_utc()
    events = (
        db.query(Event)
        .filter(Event.is_archived == False, Event.start_dt >= now)
        .order_by(Event.start_dt)
        .all()
    )
    assigned_to_me = {
        a.event_id for e in events for a in e.assignments
        if a.member_id == g.current_member.id
    }
    ical_token = g.current_member.get_or_create_ical_token(db)
    return render_template(
        "intern/calendar_list.html",
        active_tab="termine",
        events=events,
        assigned_to_me=assigned_to_me,
        ical_token=ical_token,
    )


@calendar_bp.route("/termine/archiv")
@member_required
def archive_events():
    db = get_db()
    now = now_utc()
    events = (
        db.query(Event)
        .filter(Event.start_dt < now)
        .order_by(Event.start_dt.desc())
        .all()
    )
    return render_template(
        "intern/calendar_list.html",
        active_tab="termine",
        events=events,
        is_archive=True,
        assigned_to_me=set(),
        ical_token=None,
    )


@calendar_bp.route("/termine/neu", methods=["GET", "POST"])
@member_required
def new_event():
    csrf_token = generate_csrf_token()
    db = get_db()
    members = db.query(Member).filter_by(is_active=True).order_by(Member.email).all()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        start_dt = _parse_dt(request.form.get("start_dt", ""))
        end_dt = _parse_dt(request.form.get("end_dt", ""))
        location = request.form.get("location", "").strip()
        assigned_ids = [int(x) for x in request.form.getlist("assigned_members") if x.isdigit()]
        min_members_raw = request.form.get("min_members", "").strip()
        min_members = int(min_members_raw) if min_members_raw.isdigit() else None

        if not title or not start_dt:
            flash("Titel und Startzeit sind Pflichtfelder.", "error")
        else:
            event = Event(
                title=title,
                description=description or None,
                start_dt=start_dt,
                end_dt=end_dt,
                location=location or None,
                min_members=min_members,
                created_by=g.current_member.id,
            )
            db.add(event)
            db.flush()
            for mid in assigned_ids:
                db.add(EventAssignment(event_id=event.id, member_id=mid))
            db.commit()
            flash("Termin erstellt.", "success")
            return redirect(url_for("intern.calendar.list_events"))

    return render_template(
        "intern/calendar_form.html", active_tab="termine",
        members=members, categories=EVENT_CATEGORIES,
        csrf_token=csrf_token,
    )


@calendar_bp.route("/termine/<int:event_id>")
@member_required
def detail_event(event_id: int):
    db = get_db()
    event = db.get(Event, event_id)
    if not event:
        flash("Termin nicht gefunden.", "error")
        return redirect(url_for("intern.calendar.list_events"))
    is_assigned = any(a.member_id == g.current_member.id for a in event.assignments)
    assigned_members = [a.member for a in event.assignments]
    return render_template(
        "intern/calendar_detail.html", active_tab="termine",
        event=event, is_assigned=is_assigned,
        assigned_members=assigned_members,
        csrf_token=generate_csrf_token(),
    )


@calendar_bp.route("/termine/<int:event_id>/bearbeiten", methods=["GET", "POST"])
@member_required
def edit_event(event_id: int):
    csrf_token = generate_csrf_token()
    db = get_db()
    event = db.get(Event, event_id)
    if not event:
        flash("Termin nicht gefunden.", "error")
        return redirect(url_for("intern.calendar.list_events"))
    members = db.query(Member).filter_by(is_active=True).order_by(Member.email).all()
    current_assigned = {a.member_id for a in event.assignments}

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        start_dt = _parse_dt(request.form.get("start_dt", ""))
        if not title or not start_dt:
            flash("Titel und Startzeit sind Pflichtfelder.", "error")
        else:
            event.title = title
            event.description = request.form.get("description", "").strip() or None
            event.start_dt = start_dt
            event.end_dt = _parse_dt(request.form.get("end_dt", ""))
            event.location = request.form.get("location", "").strip() or None
            event.updated_at = now_utc()
            new_ids = {int(x) for x in request.form.getlist("assigned_members") if x.isdigit()}
            min_members_raw = request.form.get("min_members", "").strip()
            event.min_members = int(min_members_raw) if min_members_raw.isdigit() else None
            for a in list(event.assignments):
                if a.member_id not in new_ids:
                    db.delete(a)
            for mid in new_ids - current_assigned:
                db.add(EventAssignment(event_id=event.id, member_id=mid))
            db.commit()
            flash("Termin aktualisiert.", "success")
            return redirect(url_for("intern.calendar.detail_event", event_id=event.id))

    return render_template(
        "intern/calendar_form.html", active_tab="termine",
        event=event, members=members,
        categories=EVENT_CATEGORIES,
        current_assigned=current_assigned,
        csrf_token=csrf_token,
    )


@calendar_bp.route("/termine/<int:event_id>/loeschen", methods=["POST"])
@member_required
def delete_event(event_id: int):
    db = get_db()
    event = db.get(Event, event_id)
    if event:
        db.delete(event)
        db.commit()
        flash("Termin gelöscht.", "success")
    return redirect(url_for("intern.calendar.list_events"))


@calendar_bp.route("/termine/<int:event_id>/zuweisen", methods=["POST"])
@member_required
def assign_self(event_id: int):
    db = get_db()
    existing = db.query(EventAssignment).filter_by(
        event_id=event_id, member_id=g.current_member.id
    ).first()
    if not existing:
        db.add(EventAssignment(event_id=event_id, member_id=g.current_member.id))
        db.commit()
        flash("Du wurdest dem Termin zugewiesen.", "success")
    return redirect(url_for("intern.calendar.detail_event", event_id=event_id))


@calendar_bp.route("/termine/<int:event_id>/abmelden", methods=["POST"])
@member_required
def unassign_self(event_id: int):
    db = get_db()
    a = db.query(EventAssignment).filter_by(
        event_id=event_id, member_id=g.current_member.id
    ).first()
    if a:
        db.delete(a)
        db.commit()
        flash("Du wurdest vom Termin abgemeldet.", "success")
    return redirect(url_for("intern.calendar.detail_event", event_id=event_id))


@calendar_bp.route("/ical")
def ical_feed():
    """iCal feed authenticated via personal token (no session required)."""
    token_str = request.args.get("token", "")
    db = get_db()
    if not token_str:
        return Response("Kein Token.", status=401, content_type="text/plain")
    member = db.query(Member).filter_by(ical_token=token_str, is_active=True).first()
    if not member:
        return Response("Ungültiger Token.", status=401, content_type="text/plain")
    events = (
        db.query(Event)
        .filter(Event.is_archived == False)
        .order_by(Event.start_dt)
        .all()
    )
    ical = _build_ical(events)
    resp = Response(ical, content_type="text/calendar; charset=utf-8")
    resp.headers["Content-Disposition"] = "attachment; filename=aixtraball.ics"
    return resp


def _build_ical(events: list) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Aixtraball//Intern//DE",
        "X-WR-CALNAME:Aixtraball Termine",
        "X-WR-TIMEZONE:Europe/Berlin",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    now_stamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
    for e in events:
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{e.id}@aixtraball.de")
        lines.append(f"DTSTAMP:{now_stamp}")
        lines.append(f"DTSTART;TZID=Europe/Berlin:{e.start_dt.strftime('%Y%m%dT%H%M%S')}")
        if e.end_dt:
            lines.append(f"DTEND;TZID=Europe/Berlin:{e.end_dt.strftime('%Y%m%dT%H%M%S')}")
        lines.append(f"SUMMARY:{_ical_escape(e.title)}")
        if e.description:
            lines.append(f"DESCRIPTION:{_ical_escape(e.description)}")
        if e.location:
            lines.append(f"LOCATION:{_ical_escape(e.location)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _ical_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")
