## Aixtraball Website

Flask-basierte Vereinswebsite für **Aixtraball e.V.**, den Flipperverein aus Aachen.  
Die Anwendung bündelt Infos zu Verein, Halle, Öffnungstagen, News, Team und Kontakt und greift dabei komplett auf YAML-Dateien als Inhaltsquelle zurück. Dadurch lässt sich der komplette Auftritt ohne Datenbank betreiben – entweder direkt per Git oder über das eingebaute Admin-Interface.

---

### Inhaltsverzeichnis
1. [Technischer Überblick](#technischer-überblick)  
2. [Lokal starten](#lokal-starten)  
3. [Docker Compose Deployment](#docker-compose-deployment)  
4. [Konfiguration per Umgebungsvariablen](#konfiguration-per-umgebungsvariablen)  
5. [Datenhaltung in `shared/config`](#datenhaltung-in-sharedconfig)  
   - [Allgemeine Hinweise](#allgemeine-hinweise)  
   - [`slides.yaml`](#slidesyaml-startseiten-slider)  
   - [`opening_days.yaml`](#opening_daysyaml-öffnungstage)  
   - [`flippers.yaml`](#flippersyaml-flipper-inventar)  
   - [`news.yaml`](#newsyaml-news--berichte)  
   - [`members.yaml`](#membersyaml-team--vorstand)  
   - [`timeline.yaml`](#timelineyaml-vereinsmeilensteine)  
   - [`contact_submissions.yaml`](#contact_submissionsyaml-kontaktanfragen)  
6. [Statische Assets](#statische-assets)  
7. [Admin- und MFA-Login](#admin--und-mfa-login)  
8. [Tests](#tests)

---

### Technischer Überblick
- **Backend:** Flask 3.x (siehe `app/app.py`)
- **Templating & Styling:** Jinja2 mit Bootstrap 5.3, GLightbox und Custom CSS (`app/static/css/custom.css`)
- **Assets & Inhalte:** YAML-Dateien unter `shared/config` + Bilder unter `shared/images`
- **Cookie-/Tracking-Steuerung:** Plausible Analytics nach expliziter Zustimmung (Cookie-Banner erscheint nur auf Seiten mit Cookies bzw. eingebetteten YouTube-Videos)
- **Deployment:** Dockerfile + `docker-compose.yml` (bindet YAML/Bilder als Volumes ein)

---

### Lokal starten
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export FLASK_APP=app.app
export FLASK_ENV=development
# optionale Secrets s. Abschnitt "Konfiguration"
flask run  # läuft per default auf http://127.0.0.1:5000
```

Die App lädt alle Inhalte bei jedem Request neu aus `shared/config`. Änderungen an den YAML-Dateien sind sofort sichtbar; ein Neustart ist nur bei Python-/Template-Anpassungen nötig.

---

### Docker Compose Deployment
```bash
docker compose up --build
```
Der Compose-Stack stellt die App auf Port `8081` bereit (siehe `docker-compose.yml`) und mountet:
- `./shared/config` → `/app/config` (YAML-Inhalte)
- `./shared/images` → `/app/static/images` (Uploads & Bilder)

Dadurch können dieselben Dateien lokal mit Git versioniert und im Container live bearbeitet werden.

---

### Konfiguration per Umgebungsvariablen
| Variable | Beschreibung |
|----------|--------------|
| `SECRET_KEY` | Flask-Session-Key (für Produktion unbedingt setzen). |
| `ADMIN_USER` | Benutzername für den internen Admin-Login. |
| `ADMIN_PASSWORD` | Klartextpasswort (oder `ADMIN_PASSWORD_HASH` für gehashte Variante). |
| `ADMIN_PASSWORD_HASH` | Legacy-Unterstützung für gehashte Passwörter via `werkzeug.security`. |
| `ADMIN_MFA_SECRET` | Base32-Secret für TOTP (z. B. mit `python -c "import pyotp; print(pyotp.random_base32())"` erzeugen). Wenn gesetzt, wird nach erfolgreicher Passworteingabe zusätzlich ein 6-stelliger MFA-Code verlangt. |
| `TZ` | Zeitzone (wird z. B. im Dockerfile auf `Europe/Berlin` gesetzt). |

Weitere Konfiguration (z. B. Öffnungszeiten, Inhalte) erfolgt ausschließlich über die YAML-Dateien.

---

### Datenhaltung in `shared/config`

#### Allgemeine Hinweise
- Die YAML-Dateien werden bei jedem Request neu eingelesen und dienen als Single Source of Truth.
- Strukturänderungen sollten konsistent erfolgen – am besten mit einem YAML-Linter oder über das Admin-Interface (`/admin`), das automatisch passende Formulare generiert.
- Bilder lassen sich via Admin-Oberfläche hochladen (`/static/images/...`). In YAML wird der Pfad relativ zu `static` angegeben, z. B. `images/team/mm.jpg`.

Im Folgenden sind alle Dateien dokumentiert:

#### `slides.yaml` (Startseiten-Slider)
Steuert das Hero-Karussell auf der Startseite.

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `image` | String (Pfad) | Pflicht. Hintergrundbild. |
| `headline` | String | Optionaler Titel-Overlay. |
| `subline` | String | Optionaler Untertitel/Call-to-Action. |
| `alt` | String | Alternativtext für Screenreader. |
| `pinned` | Boolean/String | `"True"` markiert den Slide als bevorzugt (wird nach Slide #1 eingeordnet). |
| `logo` | Boolean/String | `"True"` blendet das Logo im Overlay ein. |

Einträge dürfen auch nur aus `image` bestehen. Die Reihenfolge in der Datei entspricht der Anzeige; nach Eintrag 1 werden `pinned` Slides vor den übrigen rotierenden Slides dargestellt.

#### `opening_days.yaml` (Öffnungstage)
Ein Array aus Zeitintervallen:
```yaml
- from: '2025-07-27T11:00:00+02:00'
  to:   '2025-07-27T15:00:00+02:00'
```
- **Zeitzone:** ISO-8601 mit Offset ist Pflicht (`+01:00`/`+02:00`), damit Sommer-/Winterzeit korrekt dargestellt werden kann.
- Verwendet in den Boxen „Nächster Öffnungstag“ sowie im Kontaktformular.

#### `flippers.yaml` (Flipper-Inventar)
Liste aller Geräte für `/flipper`.

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `name` | String | Anzeige-Name, Format beliebig. |
| `image` | String | Hero-Bild (URL oder Pfad). |
| `image_details` | Liste String | Detailbilder (optional). |
| `link` | URL | Externe Referenz (z. B. IPDB). |
| `year` | String/ISO | Wird auf Jahr heruntergebrochen und zur Sortierung genutzt. |
| `manufacturer`, `system`, `designer`, `artwork`, `sound`, `software` | Strings | Freitext-Metadaten. |
| `production` | String/Number | Produktion (Anzeige 1:1). |
| `features` | Liste String | Bullet-Liste im Detailpanel. |
| `notable_facts` | Liste String | Weitere Highlights. |

Mindestens `name` und `image` sollten gesetzt sein; alle übrigen Felder werden nur angezeigt, wenn vorhanden.

#### `news.yaml` (News & Berichte)
Versorgt `/news` und einzelne Artikel (`/news/<slug>`).  
Wichtige Felder:

| Feld | Typ | Pflicht | Beschreibung |
|------|-----|---------|--------------|
| `title` | String | ✔️ | Headline. |
| `slug` | String | ✔️ | URL-Slug, eindeutig. |
| `date` | Datum/Zeit | ✔️ | Veröffentlichungsdatum (ISO oder `YYYY-MM-DD HH:MM:SS`). |
| `visible_from` / `visible_until` | Datum/Zeit | ✖️ | Steuerung des Veröffentlichungsfensters. |
| `category` | String | ✖️ | Filter in der News-Liste. |
| `preview_image` | Pfad | ✖️ | Teaserbild in der Liste. |
| `excerpt` | String | ✖️ | Kurzbeschreibung. |
| `content` | HTML | ✖️ | Hauptinhalt (HTML wird direkt gerendert). |
| `images` | Liste Pfade | ✖️ | Galerie für GLightbox. |
| `youtube_links` | Liste URLs oder leerer String | ✖️ | Eingebettete Videos; wenn gesetzt, erscheint automatisch der Cookie-Banner wegen externer Einbindung. |

Beim Speichern füllt der Server zusätzliche Felder wie `_dt` und `_year`, die in der YAML belassen werden können, aber beim Erstellen neuer Artikel ignoriert werden.

#### `members.yaml` (Team & Vorstand)
Schema pro Mitglied:
```yaml
- name: "Michael Melder"
  role: "Vorstand"
  image: "images/team/mm.jpg"
  bio: "Langtext ..."
  links:
    - label: "Instagram"
      url: "https://instagram.com/..."
```
`links` ist optional; nicht gesetzte Felder werden ausgeblendet. Die Datei wird sowohl auf `/verein` (Teaser) als auch `/team` vollflächig genutzt.

#### `timeline.yaml` (Vereinsmeilensteine)
Jeder Eintrag beschreibt einen Punkt auf der Timeline des Vereins:
```yaml
- date: "2015-03"        # Monat genau, wird chronologisch sortiert
  title: "Vereinsgründung"
  description: "Kurzer Beschreibungstext."
  image: "images/timeline/gruendung.jpg"  # optional
```

#### `contact_submissions.yaml` (Kontaktanfragen)
Wird ausschließlich vom Kontaktformular geschrieben.  
Schema:
```yaml
- name: ...
  email: ...
  message: ...
  timestamp: ISO-String
  ip: Client-IP
  ua: User-Agent
```
Die Datei dient als einfacher Posteingang. Änderungen sollten nur erfolgen, wenn Einträge archiviert oder gelöscht werden sollen – die Anwendung liest sie sonst nicht.

---

### Statische Assets
- Alle selbst gehosteten Bilder liegen unter `shared/images` und werden im Container nach `/app/static/images` gemountet.
- Globale Styles: `app/static/css/custom.css`.
- Weitere Libraries (Bootstrap, Icons, GLightbox) werden via CDN geladen. Internetzugang ist daher für die Produktivinstanz erforderlich.

---

### Admin- und MFA-Login
- `/login`: Kombination aus Benutzername, Passwort, Captcha und – falls `ADMIN_MFA_SECRET` gesetzt – **zweiter Faktor via TOTP**.  
  Der MFA-Code wird **erst nach erfolgreichem Passwort** abgefragt. Nutzer werden nach dem Passwortschritt auf ein reines OTP-Formular umgeleitet.
- `/admin`: Übersicht über die wichtigsten YAML-Dateien samt Editor/RAW-Ansicht und globalem Bild-Uploader.
- Weitere Unterseiten (`/admin/manage/<file>`, `/admin/edit/<file>`) stellen Formulare für Listeninhalte bereit.

Tipps zur MFA-Einrichtung:
1. Secret generieren, z. B. `python -c "import pyotp; print(pyotp.random_base32())"`.
2. Secret als `ADMIN_MFA_SECRET` in `.env`/Compose exportieren.
3. Secret in einer Authenticator-App (Google Authenticator, Aegis, 1Password etc.) als **TOTP** anlegen (Algorithmus: SHA1, 30 s, 6 Digits – Standardwerte).

---

### Tests
Unit-/Integrationstests liegen unter `tests/` (z. B. `tests/test_routes.py`).  
Ausführen mit:
```bash
pytest
```
Voraussetzung ist, dass ein virtuelles Environment mit den Requirements existiert und – falls Tests Inhalte benötigen – die YAML-Dateien wie im Repo vorhanden sind.

---

Fragen, Feature-Wünsche oder Bugreports bitte direkt im Repo anlegen oder über das Admin-Team kommunizieren. Viel Spaß beim Pflegen der Aixtraball-Webseite! 🎱
