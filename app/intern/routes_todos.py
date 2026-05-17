"""
Todo lists (Todolisten) routes for the intern portal.
"""

from __future__ import annotations

from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for,
)

from .auth import member_required, generate_csrf_token
from .models import TodoItem, TodoList, TodoSection, now_utc
from . import get_db

todos_bp = Blueprint("todos", __name__)


@todos_bp.route("/todolisten/")
@member_required
def list_todos():
    db = get_db()
    lists = db.query(TodoList).order_by(TodoList.sort_order, TodoList.created_at).all()
    return render_template("intern/todos_list.html", active_tab="todolisten", lists=lists,
                           csrf_token=generate_csrf_token())


@todos_bp.route("/todolisten/neu", methods=["POST"])
@member_required
def new_list():
    title = request.form.get("title", "").strip()
    if not title:
        flash("Titel darf nicht leer sein.", "error")
        return redirect(url_for("intern.todos.list_todos"))
    db = get_db()
    todo_list = TodoList(title=title, created_by=g.current_member.id)
    db.add(todo_list)
    db.commit()
    return redirect(url_for("intern.todos.todo_detail", list_id=todo_list.id))


@todos_bp.route("/todolisten/<int:list_id>")
@member_required
def todo_detail(list_id: int):
    db = get_db()
    todo_list = db.get(TodoList, list_id)
    if not todo_list:
        flash("Liste nicht gefunden.", "error")
        return redirect(url_for("intern.todos.list_todos"))
    return render_template(
        "intern/todos_detail.html", active_tab="todolisten",
        todo_list=todo_list, csrf_token=generate_csrf_token(),
    )


@todos_bp.route("/todolisten/<int:list_id>/loeschen", methods=["POST"])
@member_required
def delete_list(list_id: int):
    db = get_db()
    todo_list = db.get(TodoList, list_id)
    if todo_list:
        db.delete(todo_list)
        db.commit()
        flash("Liste gelöscht.", "success")
    return redirect(url_for("intern.todos.list_todos"))


@todos_bp.route("/todolisten/<int:list_id>/abschnitt", methods=["POST"])
@member_required
def add_section(list_id: int):
    title = request.form.get("title", "").strip()
    if not title:
        flash("Abschnittstitel darf nicht leer sein.", "error")
        return redirect(url_for("intern.todos.todo_detail", list_id=list_id))
    db = get_db()
    section = TodoSection(list_id=list_id, title=title)
    db.add(section)
    db.commit()
    return redirect(url_for("intern.todos.todo_detail", list_id=list_id))


@todos_bp.route("/todolisten/abschnitt/<int:section_id>/loeschen", methods=["POST"])
@member_required
def delete_section(section_id: int):
    db = get_db()
    section = db.get(TodoSection, section_id)
    list_id = section.list_id if section else None
    if section:
        db.delete(section)
        db.commit()
    if list_id:
        return redirect(url_for("intern.todos.todo_detail", list_id=list_id))
    return redirect(url_for("intern.todos.list_todos"))


@todos_bp.route("/todolisten/abschnitt/<int:section_id>/item", methods=["POST"])
@member_required
def add_item(section_id: int):
    text = request.form.get("text", "").strip()
    db = get_db()
    section = db.get(TodoSection, section_id)
    list_id = section.list_id if section else None
    if text and section:
        item = TodoItem(section_id=section_id, text=text)
        db.add(item)
        db.commit()
    if list_id:
        return redirect(url_for("intern.todos.todo_detail", list_id=list_id))
    return redirect(url_for("intern.todos.list_todos"))


@todos_bp.route("/todolisten/item/<int:item_id>/toggle", methods=["POST"])
@member_required
def toggle_item(item_id: int):
    db = get_db()
    item = db.get(TodoItem, item_id)
    list_id = None
    if item:
        list_id = item.section.list_id
        item.is_done = not item.is_done
        if item.is_done:
            item.completed_at = now_utc()
            item.completed_by = g.current_member.id
        else:
            item.completed_at = None
            item.completed_by = None
        db.commit()
    if list_id:
        return redirect(url_for("intern.todos.todo_detail", list_id=list_id))
    return redirect(url_for("intern.todos.list_todos"))


@todos_bp.route("/todolisten/item/<int:item_id>/loeschen", methods=["POST"])
@member_required
def delete_item(item_id: int):
    db = get_db()
    item = db.get(TodoItem, item_id)
    list_id = None
    if item:
        list_id = item.section.list_id
        db.delete(item)
        db.commit()
    if list_id:
        return redirect(url_for("intern.todos.todo_detail", list_id=list_id))
    return redirect(url_for("intern.todos.list_todos"))
