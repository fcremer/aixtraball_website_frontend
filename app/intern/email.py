"""
Email utilities for the intern portal (magic link + PIN delivery).
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


def _html_email(verify_url: str, pin_code: str, logo_url: str = "") -> str:
    if logo_url:
        logo_tag = (
            f'<img src="{logo_url}" alt="Aixtraball" height="40" '
            f'style="display:block;margin:0 auto 4px;height:40px;width:auto;">'
        )
    else:
        logo_tag = (
            '<span style="font-family:\'Space Grotesk\',Arial,sans-serif;'
            'font-size:22px;font-weight:700;color:#ffffff;letter-spacing:-0.5px;">'
            'AIXTRABALL</span>'
        )
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dein Login-Code</title>
</head>
<body style="margin:0;padding:0;background:#0a0a0b;font-family:'Inter',Arial,sans-serif;color:#f0ede8;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#0a0a0b;padding:40px 16px;">
    <tr>
      <td align="center">
        <table width="560" cellpadding="0" cellspacing="0" border="0"
               style="max-width:560px;width:100%;background:#111114;border-radius:16px;overflow:hidden;border:1px solid rgba(255,255,255,0.07);">

          <!-- Header -->
          <tr>
            <td style="background:#E31E24;padding:24px 36px;text-align:center;">
              {logo_tag}
              <p style="margin:6px 0 0;font-size:13px;color:rgba(255,255,255,0.8);letter-spacing:1px;text-transform:uppercase;">
                Mitgliederportal
              </p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:36px 36px 28px;">
              <h1 style="margin:0 0 12px;font-family:'Space Grotesk',Arial,sans-serif;font-size:24px;font-weight:700;color:#f0ede8;letter-spacing:-0.5px;">
                Dein Login
              </h1>
              <p style="margin:0 0 28px;font-size:15px;line-height:1.6;color:rgba(240,237,232,0.65);">
                Du hast einen Login für das Aixtraball-Mitgliederportal angefordert.
                Wähle eine der beiden Methoden:
              </p>

              <!-- Magic Link Button -->
              <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:28px;">
                <tr>
                  <td align="center">
                    <a href="{verify_url}"
                       style="display:inline-block;background:#E31E24;color:#ffffff;text-decoration:none;
                              font-family:'Space Grotesk',Arial,sans-serif;font-size:15px;font-weight:700;
                              padding:14px 36px;border-radius:10px;letter-spacing:0.2px;">
                      &#8594;&nbsp; Direkt einloggen
                    </a>
                  </td>
                </tr>
              </table>

              <!-- Divider -->
              <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:28px;">
                <tr>
                  <td style="border-top:1px solid rgba(255,255,255,0.07);font-size:1px;line-height:1px;">&nbsp;</td>
                  <td style="padding:0 14px;white-space:nowrap;font-size:12px;color:rgba(240,237,232,0.35);text-transform:uppercase;letter-spacing:1px;">
                    oder Code eingeben
                  </td>
                  <td style="border-top:1px solid rgba(255,255,255,0.07);font-size:1px;line-height:1px;">&nbsp;</td>
                </tr>
              </table>

              <!-- PIN Code -->
              <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:28px;">
                <tr>
                  <td align="center">
                    <p style="margin:0 0 10px;font-size:12px;color:rgba(240,237,232,0.45);text-transform:uppercase;letter-spacing:1px;">
                      Dein 6-stelliger Code
                    </p>
                    <div style="display:inline-block;background:#1a1a1f;border:1px solid rgba(255,255,255,0.10);
                                border-radius:12px;padding:18px 36px;">
                      <span style="font-family:'Space Grotesk','Courier New',monospace;font-size:36px;font-weight:700;
                                   color:#ffffff;letter-spacing:12px;word-spacing:0;">
                        {pin_code}
                      </span>
                    </div>
                    <p style="margin:10px 0 0;font-size:12px;color:rgba(240,237,232,0.35);">
                      Auf <strong style="color:rgba(240,237,232,0.55);">aixtraball.de/intern/login</strong> eingeben &bull; max. 5 Versuche
                    </p>
                  </td>
                </tr>
              </table>

              <!-- Expiry note -->
              <p style="margin:0;font-size:13px;color:rgba(240,237,232,0.35);text-align:center;line-height:1.5;">
                Link und Code sind <strong style="color:rgba(240,237,232,0.5);">15 Minuten</strong> gültig.<br>
                Falls du keinen Login angefordert hast, ignoriere diese E-Mail einfach.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:20px 36px;border-top:1px solid rgba(255,255,255,0.07);text-align:center;">
              <p style="margin:0;font-size:12px;color:rgba(240,237,232,0.25);">
                Aixtraball e.V. &mdash; Mitgliederportal
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _text_fallback(verify_url: str, pin_code: str) -> str:
    return f"""Hallo,

du hast den Login für das Aixtraball-Mitgliederportal angefordert.

METHODE 1 – Direkt einloggen:
{verify_url}

METHODE 2 – Code eingeben:
Gehe zu https://aixtraball.de/intern/login und gib diesen Code ein:

  {pin_code}

(max. 5 Versuche, gültig 15 Minuten)

Falls du keinen Login angefordert hast, ignoriere diese E-Mail.

– Dein Aixtraball-Team
"""


def send_magic_link_email(to_email: str, verify_url: str, pin_code: str, logo_url: str = "") -> None:
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USERNAME")
    smtp_pass = os.environ.get("SMTP_PASSWORD")
    smtp_sender = os.environ.get("SMTP_SENDER") or smtp_user
    use_tls = str(os.environ.get("SMTP_USE_TLS", "true")).lower() in {"1", "true", "yes"}

    if not smtp_host or not smtp_sender:
        raise RuntimeError("SMTP nicht konfiguriert (SMTP_HOST, SMTP_SENDER fehlen).")

    msg = EmailMessage()
    msg["Subject"] = f"Dein Login-Code: {pin_code}"
    msg["From"] = smtp_sender
    msg["To"] = to_email
    msg.set_content(_text_fallback(verify_url, pin_code))
    msg.add_alternative(_html_email(verify_url, pin_code, logo_url), subtype="html")

    if use_tls:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
