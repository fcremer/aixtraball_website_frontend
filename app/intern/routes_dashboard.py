"""
Dashboard route for the intern portal.
"""

from __future__ import annotations

from flask import Blueprint, g, render_template

from .auth import member_required
from .models import Event, EventAssignment, Machine, Repair, RepairComment, RepairMedia, RepairSubscription, now_utc
from . import get_db

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@member_required
def index():
    db = get_db()
    member = g.current_member
    now = now_utc()

    next_event = (
        db.query(Event)
        .filter(Event.is_archived == False, Event.start_dt >= now)
        .order_by(Event.start_dt)
        .first()
    )

    my_assignments = (
        db.query(EventAssignment)
        .join(Event)
        .filter(
            EventAssignment.member_id == member.id,
            Event.is_archived == False,
            Event.start_dt >= now,
        )
        .order_by(Event.start_dt)
        .all()
    )

    subscriptions = (
        db.query(RepairSubscription)
        .filter_by(member_id=member.id)
        .all()
    )
    unseen_repairs = []
    for sub in subscriptions:
        new_comments = (
            db.query(RepairComment)
            .filter(
                RepairComment.repair_id == sub.repair_id,
                RepairComment.created_at > sub.last_seen,
            )
            .count()
        )
        new_media = (
            db.query(RepairMedia)
            .filter(
                RepairMedia.repair_id == sub.repair_id,
                RepairMedia.uploaded_at > sub.last_seen,
            )
            .count()
        )
        if new_comments + new_media > 0:
            unseen_repairs.append({
                "subscription": sub,
                "repair": sub.repair,
                "count": new_comments + new_media,
            })

    defective_count = (
        db.query(Machine)
        .filter(Machine.is_active == True)
        .join(Repair, (Repair.machine_id == Machine.id) & Repair.status.in_(["open", "in_progress"]))
        .distinct()
        .count()
    )

    return render_template(
        "intern/dashboard.html",
        active_tab="dashboard",
        next_event=next_event,
        my_assignments=my_assignments,
        unseen_repairs=unseen_repairs,
        member=member,
        defective_count=defective_count,
    )
