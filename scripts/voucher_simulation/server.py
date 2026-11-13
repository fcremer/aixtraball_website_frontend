"""Local-only adapters. This directory is never copied into production images."""
import copy
import os
from pathlib import Path
import re
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ['VOUCHER_SIM_DATA']).resolve()
SITE = 'http://127.0.0.1:5087'
POS = 'http://127.0.0.1:5088'
BANNER = '<div style="padding:12px;background:#fff3cd;color:#332700;text-align:center;position:relative;z-index:9999">Lokale Simulation – keine echte Zahlung, kein externer E-Mail-Versand. <a href="http://127.0.0.1:5088/simulation">Teststeuerung und Postfach</a></div>'

if os.environ.get('VOUCHER_LOCAL_SIMULATION') != 'explicit-local-only' or os.environ.get('POS_ENV') == 'production':
    raise RuntimeError('Simulation only runs through the local launcher.')


def decorate(app):
    @app.after_request
    def banner(response):
        if response.mimetype == 'text/html' and not response.direct_passthrough:
            html = response.get_data(as_text=True)
            html = html.replace('<body>', '<body>' + BANNER, 1) if '<body>' in html else BANNER + html
            response.set_data(html)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.before_request
    def local_only():
        from flask import abort, request
        if request.host not in ('127.0.0.1:5087', '127.0.0.1:5088') and not (os.environ.get('VOUCHER_SIM_DOCKER') == 'true' and request.host == 'sim-pos:5088'):
            abort(403)
        if request.method == 'POST' and request.headers.get('Origin') not in (None, SITE, POS):
            abort(403)


def website():
    sys.path.insert(0, str(ROOT / 'app'))
    # Do not initialize or synchronize the unrelated real member database.
    import types
    portal = types.ModuleType('intern')
    portal.create_intern_blueprint = lambda app: None
    sys.modules['intern'] = portal
    import app as website_module
    import online_vouchers
    app = website_module.app
    # Mirror the Docker bind mounts without copying or changing shared assets.
    if (ROOT / 'shared/config').is_dir():
        website_module.CONFIG_DIR = ROOT / 'shared/config'
    original_static = app.view_functions['static']
    def local_static(filename):
        from flask import send_from_directory
        if filename.startswith('images/'):
            return send_from_directory(ROOT / 'shared/images', filename[len('images/'):])
        return original_static(filename=filename)
    app.view_functions['static'] = local_static
    original = online_vouchers.pos

    def local_pos(*args, **kwargs):
        result = original(*args, **kwargs)
        target = result.get('checkout_url') or ''
        if target.startswith('https://checkout.sumup.com/pay/'):
            result['checkout_url'] = POS + '/simulation/pay/' + target.rsplit('/', 1)[1]
        return result

    online_vouchers.pos = local_pos
    online_vouchers.limited = lambda: False  # Repeated local test scenarios, no public listener.
    online_vouchers.payment_redirect_allowed = lambda target: (
        urlsplit(target).netloc == '127.0.0.1:5088'
        and urlsplit(target).scheme == 'http'
        and bool(re.fullmatch(r'/simulation/pay/[a-f0-9]{32}', urlsplit(target).path)))
    # No analytics or unrelated write endpoints in the local voucher playground.
    @app.before_request
    def only_vouchers():
        from flask import abort, request
        if request.method == 'POST' and not request.path.startswith('/gutscheine'):
            abort(403)
    decorate(app)
    return app


def point_of_sale():
    sys.path.insert(0, str(ROOT.parent / 'POS'))
    from app import create_app, online, storage, vouchers, mailer
    from flask import request, redirect, render_template_string, abort, send_file
    from email import policy
    from email.parser import BytesParser
    app = create_app()
    app.secret_key = os.environ['SECRET_KEY']
    provider_path = DATA / 'provider.yaml'

    def fake_api(method, path='', **kwargs):
        with vouchers.lock():
            import yaml
            state = yaml.safe_load(provider_path.read_text()) if provider_path.exists() else {'checkouts': {}, 'mail_failure': False}
            if method == 'POST':
                body = kwargs['json']
                identity = uuid.uuid4().hex
                result = dict(body, id=identity, status='PENDING',
                              hosted_checkout_url='https://checkout.sumup.com/pay/' + identity)
                state['checkouts'][identity] = result
                storage.atomic_yaml(provider_path, state)
            elif path:
                result = state['checkouts'][path.lstrip('/')]
            else:
                result = [c for c in state['checkouts'].values()
                          if c['checkout_reference'] == kwargs['params']['checkout_reference']]
            return copy.deepcopy(result)

    online.api = fake_api

    def deliver(mail, job_id):
        import yaml
        with vouchers.lock():
            state = yaml.safe_load(provider_path.read_text())
            if state.get('mail_failure'):
                raise OSError('Simulated mail outage')
        directory = DATA / 'mailbox'
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / (job_id + '.eml')
        path.write_bytes(mail.as_bytes())
        path.chmod(0o600)
        return 'sent'  # Accepted by this local test mailbox only.

    mailer.deliver = deliver

    def provider_state():
        import yaml
        return yaml.safe_load(provider_path.read_text()) if provider_path.exists() else {'checkouts': {}, 'mail_failure': False}

    @app.route('/simulation/pay/<identity>', methods=['GET', 'POST'])
    def payment(identity):
        with vouchers.lock():
            state = provider_state()
            checkout = state['checkouts'].get(identity)
            if not checkout:
                abort(404)
            if request.method == 'POST':
                outcome = request.form.get('outcome')
                if outcome not in ('PAID', 'FAILED', 'EXPIRED', 'PENDING'):
                    abort(400)
                if checkout['status'] != 'PAID':
                    checkout['status'] = outcome
                    if outcome == 'PAID':
                        checkout['transactions'] = [{'id': uuid.uuid4().hex, 'status': 'SUCCESSFUL', 'timestamp': storage._now().isoformat()}]
                    storage.atomic_yaml(provider_path, state)
        if request.method == 'POST':
            return redirect(SITE + '/gutscheine/status')
        return render_template_string('''<!doctype html><html lang="de"><head><title>Zahlung simulieren</title></head><body>
        <main style="max-width:640px;margin:40px auto;font:18px system-ui"><h1>Zahlung simulieren</h1>
        <p>Testgutschein: {{ checkout.amount }} Euro</p><p>Status: {{ checkout.status }}</p>
        <p>Keine Karten- oder Bankdaten eingeben. Es findet keine Abbuchung statt.</p>
        <form method="post">{% for value,label in outcomes %}<p><button style="padding:12px" name="outcome" value="{{ value }}">{{ label }}</button></p>{% endfor %}</form>
        <a href="{{ site }}/gutscheine/status">Zur Website zurück, ohne zu bezahlen</a></main></body></html>''', checkout=checkout, site=SITE,
        outcomes=[('PAID','Zahlung erfolgreich'),('FAILED','Zahlung fehlgeschlagen'),('EXPIRED','Zahlung abbrechen / ablaufen lassen'),('PENDING','Zahlung bleibt offen')])

    @app.route('/simulation', methods=['GET', 'POST'])
    def dashboard():
        with vouchers.lock():
            state = provider_state()
            if request.method == 'POST':
                state['mail_failure'] = not state.get('mail_failure')
                storage.atomic_yaml(provider_path, state)
                if not state['mail_failure']:
                    book = storage.load_state()
                    for job in book['outbox'].values():
                        if job['status'] in ('failed','pending'):
                            job.update(status='pending', attempts=0, next_attempt=0)
                    storage.save_state(book)
            checkouts = list(state['checkouts'].values())
            book = storage.load_state()
        mails = sorted((DATA / 'mailbox').glob('*.eml'))
        return render_template_string('''<!doctype html><html lang="de"><head><title>Gutschein-Teststeuerung</title></head><body>
        <main style="max-width:900px;margin:40px auto;font:17px system-ui"><h1>Gutschein-Teststeuerung</h1>
        <p><a href="{{ site }}/gutscheine">Website öffnen</a> · <a href="/vouchers">Gutscheine in der Testkasse</a> · <a href="/simulation">Aktualisieren</a></p>
        <h2>Lokaler Mailversand: {{ 'gestört' if failed else 'bereit' }}</h2>
        <form method="post"><button style="padding:10px">{{ 'Versand wiederherstellen und erneut versuchen' if failed else 'Versandfehler simulieren' }}</button></form>
        <h2>Testzahlungen</h2><ul>{% for c in checkouts %}<li><a href="/simulation/pay/{{ c.id }}">{{ c.amount }} Euro</a> — {{ c.status }}</li>{% else %}<li>Noch keine Zahlung.</li>{% endfor %}</ul>
        <h2>Lokales E-Mail-Postfach</h2><p>Alle Empfängeradressen landen nur hier; es wird keine E-Mail nach außen versendet.</p>
        <ul>{% for name in mails %}<li><a href="/simulation/mail/{{ name }}">Gutschein-Mail anzeigen</a> · <a href="/simulation/mail/{{ name }}?download=1">EML herunterladen</a></li>{% else %}<li>Noch keine E-Mail.</li>{% endfor %}</ul>
        <p>{{ vouchers }} ausgestellte Gutscheine · {{ jobs }} Versandaufträge</p></main></body></html>''', site=SITE, failed=state.get('mail_failure'), checkouts=checkouts, mails=[p.name for p in mails], vouchers=len(book['vouchers']), jobs=len(book['outbox']))

    @app.get('/simulation/mail/<name>')
    def mail_view(name):
        import base64
        if not re.fullmatch(r'online-[a-f0-9]{32}\.eml', name):
            abort(404)
        path = DATA / 'mailbox' / name
        if not path.is_file():
            abort(404)
        if request.args.get('download'):
            return send_file(path, as_attachment=True)
        msg = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        body = msg.get_body(preferencelist=('html',)).get_content()
        for part in msg.walk():
            cid = part.get('Content-ID')
            if cid and part.get_content_maintype() == 'image':
                body = body.replace('cid:' + cid.strip('<>'), 'data:' + part.get_content_type() + ';base64,' + base64.b64encode(part.get_payload(decode=True)).decode())
        response = app.make_response(body)
        response.headers['Content-Security-Policy'] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
        return response

    def background():
        while True:
            with app.app_context():
                try:
                    with vouchers.lock():
                        ids = [o['id'] for o in storage.load_state()['operations'].values()
                               if o['payment_method'] == 'sumup_online' and o['status'] != 'completed']
                    for identity in ids:
                        online.reconcile(identity)
                    mailer.process_one()
                except Exception:
                    app.logger.exception('Local simulation worker failed')
            time.sleep(1)

    threading.Thread(target=background, daemon=True).start()
    decorate(app)
    return app

if __name__ == '__main__':
    from werkzeug.serving import run_simple
    role = sys.argv[1]
    application = website() if role == 'website' else point_of_sale()
    bind = '0.0.0.0' if os.environ.get('VOUCHER_SIM_DOCKER') == 'true' else '127.0.0.1'
    run_simple(bind, 5087 if role == 'website' else 5088, application, threaded=True, use_reloader=False)
