#!/usr/bin/env python3
"""
planka_export.py — Vollständiger Export einer Planka-Instanz inkl. archivierter Karten.

Verwendung:
    export PLANKA_URL=http://localhost:3000
    export PLANKA_EMAIL=admin@aixtraball.de
    export PLANKA_PASSWORD=geheim
    python scripts/planka_export.py

Oder alles als Argumente:
    python scripts/planka_export.py \
        --url http://localhost:3000 \
        --email admin@aixtraball.de \
        --password geheim \
        --output planka_export_2024.json

Anforderungen:
    pip install requests
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

try:
    import requests
except ImportError:
    print("Fehler: 'requests' ist nicht installiert. Bitte: pip install requests", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# HTTP-Client
# ---------------------------------------------------------------------------

class PlankaClient:
    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })

    def get(self, path: str, **params) -> dict:
        url = f"{self.base}/api/{path.lstrip('/')}"
        for attempt in range(3):
            try:
                resp = self.session.get(url, params=params, timeout=30)
                if resp.status_code == 404:
                    return {}
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.Timeout:
                if attempt == 2:
                    raise
                print(f"  Timeout bei {url}, Versuch {attempt + 2}/3 …", file=sys.stderr)
                time.sleep(2)
        return {}


def authenticate(base_url: str, email: str, password: str) -> str:
    url = f"{base_url.rstrip('/')}/api/access-tokens"
    resp = requests.post(url, json={"emailOrUsername": email, "password": password}, timeout=15)
    if resp.status_code == 401:
        print("Fehler: Authentifizierung fehlgeschlagen. E-Mail oder Passwort falsch.", file=sys.stderr)
        sys.exit(1)
    resp.raise_for_status()
    data = resp.json()
    # Planka gibt {"item": "<token-string>"} zurück – item ist direkt der Token
    item = data.get("item") if isinstance(data, dict) else None
    token = item if isinstance(item, str) else (
        item.get("token") if isinstance(item, dict) else None
    ) or data.get("token") if isinstance(data, dict) else None
    if not token:
        print(f"Fehler: Kein Token in der Antwort: {data}", file=sys.stderr)
        sys.exit(1)
    return token


# ---------------------------------------------------------------------------
# Export-Logik
# ---------------------------------------------------------------------------

def export_card_details(client: PlankaClient, card_id: str) -> dict:
    """Holt Checklisten, Aufgaben und Kommentare zu einer Karte."""
    details: dict[str, Any] = {"checklists": [], "actions": []}

    # Checklisten (inkl. Items)
    checklists_resp = client.get(f"cards/{card_id}/checklists")
    if checklists_resp:
        included = checklists_resp.get("included", {})
        checklists = checklists_resp.get("items", [])
        checklist_items = included.get("checklistItems", [])
        # Items den Checklisten zuordnen
        items_by_list: dict[str, list] = {}
        for item in checklist_items:
            cid = item.get("checklistId")
            items_by_list.setdefault(cid, []).append(item)
        for cl in checklists:
            cl["items"] = sorted(
                items_by_list.get(cl["id"], []),
                key=lambda x: x.get("position", 0),
            )
        details["checklists"] = checklists

    # Kommentare / Aktivitäten
    actions_resp = client.get(f"cards/{card_id}/actions")
    if actions_resp:
        details["actions"] = actions_resp.get("items", [])

    return details


def export_board(client: PlankaClient, board_id: str, board_name: str) -> dict:
    """Exportiert ein einzelnes Board vollständig."""
    print(f"  Board: {board_name} ({board_id})")

    board_resp = client.get(f"boards/{board_id}")
    if not board_resp:
        print(f"    Warnung: Board {board_id} nicht abrufbar.", file=sys.stderr)
        return {}

    board_item = board_resp.get("item", {})
    included = board_resp.get("included", {})

    lists = included.get("lists", [])
    all_cards = included.get("cards", [])
    labels = included.get("labels", [])
    memberships = included.get("memberships", [])
    users = included.get("users", [])

    # Karten nach archivierten und aktiven trennen
    active_cards = [c for c in all_cards if not c.get("isArchived")]
    archived_cards = [c for c in all_cards if c.get("isArchived")]

    # Wenn keine archivierten im Board-Response: explizit abfragen
    if not archived_cards:
        archived_resp = client.get(f"boards/{board_id}/cards", isArchived="true")
        if archived_resp:
            archived_cards = archived_resp.get("items", [])
            # Fallback: Einige Planka-Versionen liefern archived im included
            if not archived_cards:
                archived_cards = archived_resp.get("included", {}).get("cards", [])

    print(f"    {len(lists)} Listen, {len(active_cards)} Karten, {len(archived_cards)} archiviert")

    # Detail-Export aller Karten (aktiv + archiviert)
    def enrich_cards(cards: list[dict]) -> list[dict]:
        enriched = []
        for card in cards:
            cid = card.get("id")
            if not cid:
                continue
            detail = export_card_details(client, cid)
            enriched.append({**card, **detail})
        return enriched

    print(f"    Lade Kartendetails …")
    all_enriched = enrich_cards(active_cards + archived_cards)

    # Listen mit Karten zusammenführen
    cards_by_list: dict[str, list] = {}
    orphan_cards: list[dict] = []
    for card in all_enriched:
        list_id = card.get("listId")
        if list_id:
            cards_by_list.setdefault(list_id, []).append(card)
        else:
            orphan_cards.append(card)

    lists_with_cards = []
    for lst in sorted(lists, key=lambda x: x.get("position", 0)):
        lst_cards = sorted(
            cards_by_list.get(lst["id"], []),
            key=lambda x: x.get("position", 0),
        )
        lists_with_cards.append({**lst, "cards": lst_cards})

    return {
        **board_item,
        "labels": labels,
        "memberships": memberships,
        "users": users,
        "lists": lists_with_cards,
        "orphan_cards": orphan_cards,
    }


def run_export(client: PlankaClient) -> dict:
    """Hauptfunktion: Exportiert alle Projekte und Boards."""
    export: dict[str, Any] = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": 1,
        "projects": [],
    }

    print("Lade Projekte …")
    projects_resp = client.get("projects")
    if not projects_resp:
        print("Fehler: Keine Projekte gefunden oder API nicht erreichbar.", file=sys.stderr)
        sys.exit(1)

    projects = projects_resp.get("items", [])
    # Boards sind oft in included des Projects-Endpoint
    boards_included = projects_resp.get("included", {}).get("boards", [])
    boards_by_project: dict[str, list] = {}
    for board in boards_included:
        pid = board.get("projectId")
        if pid:
            boards_by_project.setdefault(str(pid), []).append(board)

    print(f"  {len(projects)} Projekt(e) gefunden.")

    for project in projects:
        pid = str(project.get("id", ""))
        print(f"\nProjekt: {project.get('name')} ({pid})")

        project_boards = boards_by_project.get(pid, [])

        # Falls Boards nicht im Project-included: separat abrufen
        if not project_boards:
            boards_resp = client.get(f"projects/{pid}/boards")
            if boards_resp:
                project_boards = boards_resp.get("items", []) or \
                                 boards_resp.get("included", {}).get("boards", [])

        print(f"  {len(project_boards)} Board(s)")

        exported_boards = []
        for board in sorted(project_boards, key=lambda x: x.get("position", 0)):
            board_data = export_board(client, str(board["id"]), board.get("name", "?"))
            if board_data:
                exported_boards.append(board_data)

        export["projects"].append({
            **project,
            "boards": exported_boards,
        })

    return export


# ---------------------------------------------------------------------------
# Statistik-Ausgabe
# ---------------------------------------------------------------------------

def print_summary(data: dict) -> None:
    total_boards = total_lists = total_cards = total_archived = total_checklists = total_comments = 0
    for project in data.get("projects", []):
        for board in project.get("boards", []):
            total_boards += 1
            for lst in board.get("lists", []):
                total_lists += 1
                for card in lst.get("cards", []):
                    total_cards += 1
                    if card.get("isArchived"):
                        total_archived += 1
                    total_checklists += len(card.get("checklists", []))
                    total_comments += len([
                        a for a in card.get("actions", [])
                        if a.get("type") == "commentCard"
                    ])
            total_cards += len(board.get("orphan_cards", []))

    print("\n" + "=" * 50)
    print("Export-Zusammenfassung")
    print("=" * 50)
    print(f"  Projekte:    {len(data.get('projects', []))}")
    print(f"  Boards:      {total_boards}")
    print(f"  Listen:      {total_lists}")
    print(f"  Karten:      {total_cards}  (davon archiviert: {total_archived})")
    print(f"  Checklisten: {total_checklists}")
    print(f"  Kommentare:  {total_comments}")
    print("=" * 50)


# ---------------------------------------------------------------------------
# Einstiegspunkt
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exportiert alle Daten einer Planka-Instanz als JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Konfiguration via Umgebungsvariablen:
  PLANKA_URL      URL der Planka-Instanz  (z.B. http://localhost:3000)
  PLANKA_EMAIL    Admin-E-Mail
  PLANKA_PASSWORD Admin-Passwort
        """,
    )
    parser.add_argument("--url", default=os.environ.get("PLANKA_URL", ""),
                        help="Planka-URL (Standard: $PLANKA_URL)")
    parser.add_argument("--email", default=os.environ.get("PLANKA_EMAIL", ""),
                        help="E-Mail-Adresse (Standard: $PLANKA_EMAIL)")
    parser.add_argument("--password", default=os.environ.get("PLANKA_PASSWORD", ""),
                        help="Passwort (Standard: $PLANKA_PASSWORD)")
    parser.add_argument("--output", default="planka_export.json",
                        help="Ausgabedatei (Standard: planka_export.json)")
    args = parser.parse_args()

    if not args.url:
        parser.error("--url oder $PLANKA_URL ist erforderlich.")
    if not args.email:
        parser.error("--email oder $PLANKA_EMAIL ist erforderlich.")
    if not args.password:
        parser.error("--password oder $PLANKA_PASSWORD ist erforderlich.")

    print(f"Verbinde mit {args.url} …")
    token = authenticate(args.url, args.email, args.password)
    print("Authentifizierung erfolgreich.")

    client = PlankaClient(args.url, token)
    export_data = run_export(client)

    print_summary(export_data)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nExport gespeichert: {args.output}")
    print(f"Dateigröße: {os.path.getsize(args.output) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
