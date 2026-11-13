# Online-Gutscheine: Einrichtung und Abnahme

Website und POS müssen gemeinsam ausgerollt werden. Standardmäßig bleibt der Kauf
abgeschaltet. Keine neuen Gutschein-Geheimnisse in der Website hinterlegen.

## Konfiguration

Einmalig ein dediziertes internes Docker-Netz anlegen:
`docker network create --internal aixtraball-vouchers`.
Beide Projekte mit ihrer jeweiligen `docker-compose.vouchers.yml` zusätzlich starten.
Das normale Netzwerk bleibt für SumUp/SMTP-Verbindungen erhalten. Am öffentlichen
Reverse Proxy `/internal/` sperren; POS-Port 8011 nur über den bestehenden geschützten
Zugangsweg freigeben. Der Service-Token ersetzt keine Netzwerkisolation.

Website `.env`:
- `VOUCHER_SALES_ENABLED=false` bis zur Abnahme
- `POS_INTERNAL_URL=http://pos:8000`
- `ONLINE_SERVICE_TOKEN`: mindestens 32 kryptografisch zufällige Zeichen, eigener Schlüssel
- `VOUCHER_TRUSTED_PROXY_CIDRS`: ausschließlich die IP/CIDR des direkten Reverse-Proxys;
  dieser muss X-Forwarded-For korrekt setzen/anhängen. Ohne Einstellung teilen sich
  alle Besucher hinter diesem Proxy das Limit von 40 Anfragen pro Minute.
- `SECRET_KEY`: eigener zufälliger Session-Schlüssel; HTTPS/Secure-Cookies beibehalten
- Admin-Zugang über `ADMIN_USER`, `ADMIN_PASSWORD_HASH`, `ADMIN_MFA_SECRET` konfigurieren.
  Die bisher im Compose eingebetteten Zugangsdaten vor Freigabe ersetzen.

POS `.env.pos`:
- `ONLINE_SALES_ENABLED=true`
- gleicher `ONLINE_SERVICE_TOKEN`
- `SUMUP_ONLINE_API_KEY` und `SUMUP_ONLINE_MERCHANT_CODE`: Online-Payments-Zugang
- `ONLINE_PUBLIC_ORIGIN=https://www.aixtraball.de` (tatsächlichen kanonischen Host verwenden)
- vorhandenen `POS_VOUCHER_SECRET` unverändert lassen
- `POS_MAIL_MODE=smtp`, `POS_MAIL_FROM`, `POS_SMTP_HOST`, SMTP-Zugangsdaten konfigurieren
- TLS-Zertifikatsprüfung aktiv lassen

Website und POS-Webprozess sowie `online-worker` und `mail-worker` müssen laufen.
`ONLINE_SALES_ENABLED=false` sperrt neue Käufe; der Abgleich bestehender Zahlungen
läuft weiter. Den Worker und die Provider-Zugangsdaten daher nicht vorzeitig entfernen.

## Daten und Sicherheit

Onlinebestellungen sind zusätzliche `operations` in `pos-state.yaml` (Schema 1,
additive Felder). Ausgabe, Buchung und Outbox verwenden den bestehenden gemeinsamen
atomaren Abschluss. Neue Zahlungsart: `sumup_online`, Berichtsfeld: `online_total`.
Vor dem Upgrade alle POS-Schreiber stoppen und Datenverzeichnis plus bestehenden
Voucher-Schlüssel getrennt sichern. Ältere Programmstände verstehen die neue
Zahlungsart nicht: nach Onlineverkäufen kein Code-Rollback ohne passenden
Buchhaltungsadapter. Niemals ein altes Datenbackup über bereits bezahlte Verkäufe
zurückspielen; andernfalls gehen Guthaben und Zahlungszuordnungen verloren.

Der Browser erhält einen zufälligen Bestellschlüssel in seiner signierten
HttpOnly-Session. Keine Bestellschlüssel oder Empfängeradressen in Rücksprung-URLs.
Die Rückkehr muss im gleichen Browser erfolgen; bei verlorener Session wird der
Gutschein dennoch unabhängig per E-Mail versendet. Statusseiten haben `no-store`,
`no-referrer` und kein Analytics. Der interne Status enthält keinen Gutscheincode.

SumUp-Webhooks sind lediglich Hinweise; der dauerhafte Worker prüft alle offenen
Bestellungen alle 30 Sekunden direkt bei SumUp. Eine erfolgreiche Browser-Rückkehr
oder ein gefälschter Webhook kann keine Ausstellung auslösen. Checkout-Erstellung
wird nach unklarem Timeout nicht wiederholt; der Worker sucht anhand der gespeicherten
Referenz nach dem Checkout. Bleibt dieser dauerhaft unauffindbar, muss ein Admin
die Bestellung prüfen. Keine automatische Zweitbelastung als Fehlerbehandlung.

In der Kasse sind offene Onlinevorgänge unter den bestehenden Vorgängen sichtbar;
Versandfehler und Neuversand in der Admin-Gutscheinverwaltung. Worker-Warnungen
überwachen. Fehlgeschlagene Zahlungsversuche bleiben abgleichbar, da ein späterer
Versuch im selben Checkout erfolgreich sein kann. Unaufgelöste Vorgänge werden
absichtlich nicht automatisch gelöscht.

## Abnahme vor Freischaltung

1. Mit SumUp-Sandbox und Test-Mailserver alle vier Beträge testen.
2. Browser direkt nach Bezahlung schließen: genau ein Gutschein muss entstehen.
3. Wiederholte Webhooks und parallele Requests: genau eine Buchung/Outbox.
4. POS/Worker neu starten, SumUp-Timeout und SMTP-Ausfall simulieren; keine erneute
   Belastung. Versandstatus darf erst nach SMTP-Annahme „versendet“ anzeigen.
5. Mobil und per Tastatur prüfen; Angabenprüfung, Rückkehr und Statusaktualisierung.
6. Tagesbericht/PDF: Onlinezuflüsse separat, Gesamtbetrag einschließlich Online.
7. Händlerangaben, Gutscheinbedingungen und Datenschutzhinweise vor Verkauf fachlich
   freigeben; bestehende Bedingungen gelten, keine neuen Gültigkeitsregeln eingeführt.
8. Erst danach produktiven SumUp-Zugang einsetzen und Website-Schalter aktivieren.

Keine automatischen Erstattungen oder Chargeback-Verarbeitung. Ein QR-Code ist ein
Inhabernachweis; Kopien sind möglich, zusätzliche Guthaben entstehen dadurch nicht.
SMTP kann nach unklarer Antwort dieselbe Mail mehrfach zustellen, niemals einen neuen
Gutschein erzeugen.

API-Referenzen: https://developer.sumup.com/online-payments/checkouts/hosted-checkout/
und https://developer.sumup.com/api/checkouts/list/.
