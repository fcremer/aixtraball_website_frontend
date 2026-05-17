"""
PWA manifest and service worker routes.
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Response, url_for

from . import BUILD_ID

pwa_bp = Blueprint("pwa", __name__)

SW_JS = (Path(__file__).parent.parent / "static" / "intern" / "js" / "service-worker.js").resolve()


@pwa_bp.route("/manifest.json")
def manifest():
    data = {
        "name": "Aixtraball Intern",
        "short_name": "Intern",
        "description": "Mitgliederportal des Flipperverein Aixtraball e.V.",
        "start_url": "/intern/",
        "scope": "/intern/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "theme_color": "#E31E24",
        "background_color": "#0a0a0b",
        "lang": "de",
        "icons": [
            {
                "src": "/static/intern/icons/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "/static/intern/icons/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
    }
    import json
    return Response(json.dumps(data), content_type="application/manifest+json")


@pwa_bp.route("/sw.js")
def service_worker():
    try:
        content = SW_JS.read_text(encoding="utf-8")
    except FileNotFoundError:
        content = "// service worker not yet generated"
    # Inject the per-deploy build ID so the SW invalidates its cache on every restart
    content = content.replace("'intern-v3'", f"'{BUILD_ID}'")
    resp = Response(content, content_type="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/intern/"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp
