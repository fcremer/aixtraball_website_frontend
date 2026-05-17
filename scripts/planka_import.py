#!/usr/bin/env python3
"""
planka_import.py — Importiert Planka-Export-Daten in das Aixtraball-Intern-Portal.

Mapping:
  Planka Board  → TodoList
  Planka Liste  → TodoSection
  Planka Karte  → TodoItem  (Titel + Beschreibung zusammengeführt)
  Archivierte Karten werden ebenfalls importiert (is_done=True wenn archiviert)

  Checklisten-Items innerhalb einer Karte werden als separate TodoItems
  unter einem eigenen Abschnitt "<Kartenname> – Checkliste" importiert.

Verwendung:
    python scripts/planka_import.py --input planka_export.json \
        [--db pfad/zu/intern.db] \
        [--owner-email admin@aixtraball.de] \
        [--dry-run]

Anforderungen:
    pip install sqlalchemy
    (SQLite ist in Python stdlib enthalten)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
except ImportError:
    print("Fehler: 'sqlalchemy' ist nicht installiert. Bitte: pip install sqlalchemy", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Minimale Modell-Definitionen (unabhängig von app/intern/models.py)
# ---------------------------------------------------------------------------

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import mapped_column, Mapped


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Member(Base):
    __tablename__ = "member"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(120), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    ical_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)


class TodoList(Base):
    __tablename__ = "todo_list"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int] = mapped_column(ForeignKey("member.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class TodoSection(Base):
    __tablename__ = "todo_section"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("todo_list.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class TodoItem(Base):
    __tablename__ = "todo_item"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("todo_section.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(String(500))
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("member.id"))


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int = 490) -> str:
    """Kürzt Text auf max_len Zeichen (TodoItem.text ist VARCHAR 500)."""
    if not text:
        return ""
    text = text.strip()
    return text if len(text) <= max_len else text[:max_len - 3] + "…"


def _card_text(card: dict) -> str:
    """Baut den Anzeigetext für eine Karte (Titel + optionale Beschreibung)."""
    title = (card.get("name") or card.get("title") or "").strip()
    desc = (card.get("description") or "").strip()
    if desc:
        # Markdown-Links und übermäßige Leerzeilen entfernen
        desc = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", desc)
        desc = re.sub(r"\n{3,}", "\n\n", desc)
        short_desc = desc[:120].strip()
        if len(desc) > 120:
            short_desc += "…"
        return _truncate(f"{title} — {short_desc}")
    return _truncate(title)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _get_or_create_owner(db, email: str) -> int:
    member = db.query(Member).filter_by(email=email).first()
    if not member:
        member = Member(email=email, display_name="Planka Import", is_active=True)
        db.add(member)
        db.flush()
        print(f"  Neues Mitglied angelegt: {email}")
    return member.id


# ---------------------------------------------------------------------------
# Import-Logik
# ---------------------------------------------------------------------------

def import_board(db, board: dict, owner_id: int, board_index: int, dry_run: bool) -> dict:
    """Importiert ein Planka-Board als TodoList mit Sections und Items."""
    board_name = board.get("name") or board.get("title") or f"Board {board_index + 1}"
    lists = board.get("lists", [])
    orphan_cards = board.get("orphan_cards", [])

    stats = {"sections": 0, "items": 0, "archived": 0, "checklist_items": 0}

    if dry_run:
        print(f"  [DRY-RUN] TodoList: {board_name}")
    else:
        todo_list = TodoList(
            title=board_name,
            sort_order=board_index,
            created_by=owner_id,
            created_at=_parse_dt(board.get("createdAt")) or now_utc(),
        )
        db.add(todo_list)
        db.flush()
        list_id = todo_list.id

    for section_index, lst in enumerate(lists):
        section_name = lst.get("name") or lst.get("title") or f"Liste {section_index + 1}"
        cards = lst.get("cards", [])
        if not cards:
            continue

        stats["sections"] += 1

        if dry_run:
            print(f"    [DRY-RUN] Section: {section_name} ({len(cards)} Karten)")
        else:
            section = TodoSection(
                list_id=list_id,
                title=section_name,
                sort_order=section_index,
            )
            db.add(section)
            db.flush()
            section_id = section.id

        for item_index, card in enumerate(cards):
            is_archived = bool(card.get("isArchived"))
            item_text = _card_text(card)
            if not item_text:
                continue

            stats["items"] += 1
            if is_archived:
                stats["archived"] += 1

            completed_at = _parse_dt(card.get("updatedAt")) if is_archived else None

            if not dry_run:
                todo_item = TodoItem(
                    section_id=section_id,
                    text=item_text,
                    is_done=is_archived,
                    sort_order=item_index,
                    completed_at=completed_at,
                    completed_by=owner_id if is_archived else None,
                )
                db.add(todo_item)

            # Checklisten als Sub-Items
            checklists = card.get("checklists", [])
            for checklist in checklists:
                checklist_items = checklist.get("items", [])
                if not checklist_items:
                    continue

                cl_section_name = f"{(card.get('name') or '')[:60].strip()} – {checklist.get('name', 'Checkliste')}"

                stats["sections"] += 1
                stats["checklist_items"] += len(checklist_items)

                if dry_run:
                    print(f"      [DRY-RUN] Checkliste: {cl_section_name} ({len(checklist_items)} Items)")
                else:
                    cl_section = TodoSection(
                        list_id=list_id,
                        title=_truncate(cl_section_name, 190),
                        sort_order=section_index * 1000 + item_index,
                    )
                    db.add(cl_section)
                    db.flush()
                    for ci_index, ci in enumerate(checklist_items):
                        ci_text = _truncate(ci.get("name") or "")
                        if not ci_text:
                            continue
                        ci_done = bool(ci.get("isCompleted"))
                        db.add(TodoItem(
                            section_id=cl_section.id,
                            text=ci_text,
                            is_done=ci_done,
                            sort_order=ci_index,
                        ))

    # Verwaiste Karten (ohne Liste) in eigenen Abschnitt
    if orphan_cards:
        stats["sections"] += 1
        stats["items"] += len(orphan_cards)
        if not dry_run:
            orphan_section = TodoSection(
                list_id=list_id,
                title="Archiv (ohne Liste)",
                sort_order=9999,
            )
            db.add(orphan_section)
            db.flush()
            for oi, card in enumerate(orphan_cards):
                item_text = _card_text(card)
                if item_text:
                    db.add(TodoItem(
                        section_id=orphan_section.id,
                        text=item_text,
                        is_done=True,
                        sort_order=oi,
                    ))

    return stats


def run_import(db, data: dict, owner_id: int, dry_run: bool, board_filter: str | None) -> None:
    total = {"boards": 0, "sections": 0, "items": 0, "archived": 0, "checklist_items": 0}
    board_index = 0

    for project in data.get("projects", []):
        project_name = project.get("name", "?")
        boards = project.get("boards", [])
        print(f"\nProjekt: {project_name} ({len(boards)} Boards)")

        for board in boards:
            board_name = board.get("name") or board.get("title") or ""
            if board_filter and board_filter.lower() not in board_name.lower():
                print(f"  Übersprungen: {board_name}")
                continue

            print(f"  Importiere Board: {board_name} …")
            stats = import_board(db, board, owner_id, board_index, dry_run)
            board_index += 1
            total["boards"] += 1
            for k, v in stats.items():
                total[k] = total.get(k, 0) + v

            print(
                f"    → {stats['sections']} Abschnitte, "
                f"{stats['items']} Items "
                f"(archiviert: {stats['archived']}, "
                f"Checklisten-Items: {stats['checklist_items']})"
            )

    if not dry_run:
        db.commit()

    print("\n" + "=" * 50)
    print("Import-Zusammenfassung")
    print("=" * 50)
    print(f"  Boards importiert:    {total['boards']}")
    print(f"  Abschnitte erstellt:  {total['sections']}")
    print(f"  Items gesamt:         {total['items']}")
    print(f"    davon archiviert:   {total['archived']}")
    print(f"    Checklisten-Items:  {total['checklist_items']}")
    if dry_run:
        print("\n  [DRY-RUN] Keine Änderungen in der Datenbank gespeichert.")
    print("=" * 50)


# ---------------------------------------------------------------------------
# Einstiegspunkt
# ---------------------------------------------------------------------------

def main() -> None:
    # Standard-DB-Pfad: relativ zum Script-Verzeichnis
    default_db = Path(__file__).resolve().parent.parent / "app" / "data" / "intern.db"

    parser = argparse.ArgumentParser(
        description="Importiert Planka-Export-JSON in das Aixtraball Intern-Portal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", default="planka_export.json",
                        help="Export-Datei von planka_export.py (Standard: planka_export.json)")
    parser.add_argument("--db", default=str(default_db),
                        help=f"Pfad zur intern.db (Standard: {default_db})")
    parser.add_argument("--owner-email", default="admin@aixtraball.de",
                        help="E-Mail des Mitglieds, dem die importierten Listen zugewiesen werden")
    parser.add_argument("--board", default=None,
                        help="Nur Boards importieren, deren Name diesen Text enthält (Groß/Kleinschreibung egal)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Zeigt was importiert werden würde, ohne die DB zu verändern")
    args = parser.parse_args()

    # Export-Datei laden
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Fehler: Datei nicht gefunden: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Lade Export: {input_path} …")
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    exported_at = data.get("exported_at", "unbekannt")
    print(f"Export-Zeitstempel: {exported_at}")
    print(f"Projekte in Export: {len(data.get('projects', []))}")

    # Datenbank verbinden
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Fehler: Datenbank nicht gefunden: {db_path}", file=sys.stderr)
        print("Hinweis: Starte zuerst die Intern-Portal-App, damit intern.db angelegt wird.", file=sys.stderr)
        sys.exit(1)

    print(f"Datenbank: {db_path}")
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()

    try:
        owner_id = _get_or_create_owner(db, args.owner_email)
        if not args.dry_run:
            db.commit()

        run_import(db, data, owner_id, args.dry_run, args.board)

    except Exception as exc:
        db.rollback()
        print(f"\nFehler beim Import: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()

    if not args.dry_run:
        print(f"\nImport abgeschlossen. Datenbank: {db_path}")


if __name__ == "__main__":
    main()
