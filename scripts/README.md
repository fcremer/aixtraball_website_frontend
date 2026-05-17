# Planka → Aixtraball Intern Portal Migration

## Schritt 1: Export aus Planka

```bash
pip install requests

# Konfiguration (Umgebungsvariablen oder Flags)
export PLANKA_URL=http://deine-planka-instanz.de
export PLANKA_EMAIL=admin@aixtraball.de
export PLANKA_PASSWORD=geheim

python scripts/planka_export.py --output planka_export.json
```

Der Export enthält **alle** Daten:
- Projekte, Boards, Listen, Karten (aktiv + **archiviert**)
- Checklisten mit Items
- Kommentare / Aktivitäten (gespeichert, aber nicht importiert)
- Board-Mitgliedschaften und Labels (gespeichert für spätere Nutzung)

## Schritt 2: Import ins Intern-Portal

```bash
pip install sqlalchemy

# Vorher: App mindestens einmal starten, damit intern.db angelegt wird

python scripts/planka_import.py \
    --input planka_export.json \
    --db app/data/intern.db \
    --owner-email admin@aixtraball.de
```

### Optionen

| Flag | Beschreibung |
|------|-------------|
| `--dry-run` | Zeigt was importiert wird, ohne die DB zu verändern |
| `--board "Reparaturen"` | Importiert nur Boards, deren Name den Text enthält |
| `--owner-email` | E-Mail des Mitglieds, dem die Listen zugeordnet werden |

## Mapping Planka → Intern-Portal

| Planka | Intern-Portal |
|--------|---------------|
| Board | TodoList |
| Liste (Spalte) | TodoSection |
| Karte | TodoItem (Titel + Kurzbeschreibung) |
| Archivierte Karte | TodoItem mit `is_done=True` |
| Checklisten-Item | TodoItem in eigenem Sub-Abschnitt |

## Tipps

- **Zuerst `--dry-run`** ausführen, um das Mapping zu prüfen
- **Nur bestimmte Boards** importieren mit `--board "Name"`
- Der Export läuft idempotent — ein zweiter Import erstellt doppelte Listen
- Kommentare werden in der Export-JSON gespeichert, aber noch nicht importiert
  (die Intern-Portal-Datenbank hat kein generisches Kommentar-Modell für Todo-Items)
