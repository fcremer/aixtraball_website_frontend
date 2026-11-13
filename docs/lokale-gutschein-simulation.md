# Gutschein-Simulation mit Docker

Aus dem Website-Projekt starten (eigenständiger Stack, keine Produktionsdateien ergänzen):

```sh
docker compose -f docker-compose.simulation.yml up -d --build --wait
```

- Website: http://127.0.0.1:5087/gutscheine
- Zahlungssteuerung und lokales E-Mail-Postfach: http://127.0.0.1:5088/simulation
- Testkasse: http://127.0.0.1:5088/vouchers

Eine beliebige Testadresse verwenden, etwa `test@example.invalid`. Betrag wählen,
Angaben prüfen und bezahlen. Auf der lokalen Zahlungsseite Erfolg, Fehler, Ablauf
oder einen offenen Vorgang auswählen. Der Worker verarbeitet die Testzahlung und
legt die Gutschein-Mail im lokalen Postfach ab. Die Statusseite aktualisiert sich
alle 15 Sekunden; manuelles Aktualisieren geht sofort. Die Mail lässt sich samt
QR-Code ansehen oder als EML herunterladen.

In der Teststeuerung lässt sich ein Mailausfall einschalten. Nach Wiederherstellung
werden ausstehende Testmails erneut versucht. Wiederholtes Bestätigen derselben
Zahlung erzeugt keinen weiteren Gutschein.

```sh
# Zustand und Logs
docker compose -f docker-compose.simulation.yml ps
docker compose -f docker-compose.simulation.yml logs -f
# Stoppen, Daten behalten
docker compose -f docker-compose.simulation.yml down
# Vollständig zurücksetzen: löscht ausschließlich die Testdaten dieses Stacks
docker compose -f docker-compose.simulation.yml down -v
```

## Trennung vom Produktivbetrieb

Eigener Compose-Projektname und eigenes Volume `simulation-data`. Keine `.env`-
oder `.env.pos`-Datei wird geladen. Alle im Compose gesetzten Schlüssel sind
öffentlich bekannte Testschlüssel und ausschließlich für diese isolierte Simulation.
Ein separates Docker-Netz verbindet die Testdienste; ein zusätzliches Vorschau-Netz
ermöglicht die Portfreigaben unter Docker Desktop. Ports sind nur auf 127.0.0.1
gebunden. Die Zahlungs- und Mailadapter führen keine externen Aufrufe aus. Keine echten Zahlungen, kein SMTP-Versand nach außen. „Versendet“ bedeutet
hier ausschließlich im lokalen Testpostfach abgelegt.

Die echte Gutschein- und Buchungslogik wird verwendet; Zahlungsanbieter und
Mailtransport werden nur im separaten Simulationsskript ersetzt. Die Testkasse ist
bewusst ohne Anmeldung. Die normale Website akzeptiert weiterhin nur HTTPS-SumUp-
Zahlungslinks. Das Rate-Limit ist ausschließlich im lokalen Testadapter deaktiviert.

Quellcode und Website-Inhalte/Bilder aus `shared` werden nur lesend eingebunden.
Das Mitgliederportal wird nicht initialisiert. POS-Produktivdaten werden weder
als Datenverzeichnis verwendet noch verändert. Testadapter unter `scripts/` sind
nicht Bestandteil des Produktionsimages.

Voraussetzungen: Docker Desktop läuft und das POS-Projekt liegt unter `../POS`.
Python-Umgebungen auf dem Host sind für Docker nicht erforderlich.
Immer `127.0.0.1` verwenden; andere Browser-Hostnamen werden abgelehnt.

Optionaler automatischer HTTP-Test vom Host mit vorhandenem Python:
`.venv/bin/python scripts/voucher_simulation/check.py`. Er erzeugt zusätzliche
Testkäufe und prüft alle Beträge, Fehler/Wiederholung, Ablauf, Mailausfall und QR-Mail.
Der frühere Host-Launcher ist alternativ vorhanden; nicht parallel auf denselben
Ports starten.
