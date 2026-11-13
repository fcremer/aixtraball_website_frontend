"""Public voucher storefront; all financial state belongs to POS."""
import fcntl
import hashlib
import hmac
import json
import ipaddress
import os
import re
import secrets
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from flask import Blueprint, abort, current_app, redirect, render_template, request, session, url_for

bp = Blueprint('online_vouchers', __name__)
AMOUNTS = (15, 30, 50, 100)


def enabled():
    return (os.getenv('VOUCHER_SALES_ENABLED') == 'true'
            and len(os.getenv('ONLINE_SERVICE_TOKEN', '')) >= 32
            and bool(os.getenv('POS_INTERNAL_URL'))
            and current_app.secret_key not in (None, '', 'change-me'))


def payment_redirect_allowed(target):
    parsed = urlsplit(target)
    return parsed.scheme == "https" and parsed.netloc == "checkout.sumup.com"


def pos(method, path, data=None):
    req = Request(os.environ['POS_INTERNAL_URL'].rstrip('/') + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Authorization': 'Bearer ' + os.environ['ONLINE_SERVICE_TOKEN'],
                 **({'Content-Type': 'application/json'} if data is not None else {})}, method=method)
    with urlopen(req, timeout=30) as response:
        return json.load(response) if response.status != 204 else {}


def limited():
    # Shared across gunicorn processes; use a persistent mounted directory.
    directory = Path(os.getenv('VOUCHER_RATE_DIR', '/tmp/aix-voucher-limits'))
    directory.mkdir(parents=True, exist_ok=True)
    source = request.remote_addr or '127.0.0.1'
    trusted = os.getenv('VOUCHER_TRUSTED_PROXY_CIDRS', '').split(',')
    if any(ipaddress.ip_address(source) in ipaddress.ip_network(c.strip())
           for c in trusted if c.strip()):
        forwarded = request.headers.get('X-Forwarded-For', '').split(',')[-1].strip()
        try:
            source = str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    identity = hmac.new(str(current_app.secret_key).encode(),
        source.encode(), hashlib.sha256).hexdigest()
    with (directory / 'requests.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / 'requests.json'
        now = time.time()
        state = json.loads(path.read_text()) if path.exists() else {}
        state = {k: v for k, v in state.items() if v['until'] > now}
        bucket = state.setdefault(identity, {'until': now + 60, 'count': 0})
        bucket['count'] += 1
        temp = directory / 'requests.tmp'
        temp.write_text(json.dumps(state))
        os.chmod(temp, 0o600)
        os.replace(temp, path)
        return bucket['count'] > 40


@bp.before_request
def protect():
    if request.content_length and request.content_length > 4096:
        abort(413)
    if limited():
        abort(429)
    if request.method == 'POST' and request.endpoint != 'online_vouchers.webhook':
        expected = session.get('voucher_csrf', '')
        if not expected or not hmac.compare_digest(expected.encode(), request.form.get('csrf', '').encode()):
            abort(403)


@bp.after_request
def private(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Robots-Tag'] = 'noindex'
    return response


@bp.route('/gutscheine', methods=['GET', 'POST'])
def page():
    session.setdefault('voucher_csrf', secrets.token_urlsafe(32))
    session.setdefault('voucher_draft', 'online-' + secrets.token_hex(16))
    error = None
    review = None
    if request.method == 'POST' and enabled():
        if session.get('voucher_order'):
            return redirect(url_for('.status'))
        try:
            amount = int(request.form.get('amount', ''))
            email = request.form.get('email', '').strip()
            if amount not in AMOUNTS or len(email) > 254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', email):
                raise ValueError
            review = {'amount': amount, 'email': email}
            session['voucher_review'] = dict(review, id=session['voucher_draft'])
        except ValueError:
            error = 'Bitte wähle einen Betrag und gib eine gültige E-Mail-Adresse ein.'
    return render_template('vouchers_online.html', enabled=enabled(), review=review,
                           error=error, amounts=AMOUNTS)


@bp.post('/gutscheine/bezahlen')
def pay():
    if not enabled():
        abort(503)
    if session.get('voucher_order'):
        return redirect(url_for('.status'))
    review = session.get('voucher_review')
    if not review:
        return redirect(url_for('.page'))
    # Persist in the browser session before remote work; separate request prevents
    # a timeout from losing the purchase identity or creating a second charge.
    session['voucher_order'] = review['id']
    session['voucher_pending'] = review
    return redirect(url_for('.start'), code=303)


@bp.route('/gutscheine/start', methods=['GET', 'POST'])
def start():
    if not enabled() or not session.get('voucher_order'):
        return redirect(url_for('.page'))
    if request.method == 'GET':
        return render_template('vouchers_start.html')
    review = session.get('voucher_pending')
    if not review:
        return redirect(url_for('.status'))
    try:
        result = pos('POST', '/internal/online-orders', {
            'id': review['id'], 'amount_cents': review['amount'] * 100, 'email': review['email']})
        target = result.get('checkout_url') or ''
        if payment_redirect_allowed(target):
            session.pop('voucher_pending', None)
            return redirect(target, code=303)
    except (URLError, ValueError, TimeoutError):
        pass
    return redirect(url_for('.status'))


@bp.get('/gutscheine/status')
def status():
    order = session.get('voucher_order')
    result = None
    if order and enabled():
        try:
            result = pos('GET', '/internal/online-orders/' + order)
        except (URLError, ValueError, TimeoutError):
            pass
    return render_template('vouchers_status.html', result=result, order=order)


@bp.post('/gutscheine/neu')
def new():
    order = session.get('voucher_order')
    if order:
        try:
            result = pos('GET', '/internal/online-orders/' + order)
        except (URLError, ValueError, TimeoutError):
            return redirect(url_for('.status'))
        if result.get('status') != 'completed' and result.get('payment_status') != 'EXPIRED':
            return redirect(url_for('.status'))
    for key in ('voucher_order', 'voucher_pending', 'voucher_review', 'voucher_draft'):
        session.pop(key, None)
    return redirect(url_for('.page'))


@bp.post('/gutscheine/webhook')
def webhook():
    # Workers independently reconcile all orders. Never trust event payment data.
    if not enabled():
        abort(503)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get('id'), str) or len(body['id']) > 128:
        abort(400)
    try:
        pos('POST', '/internal/online-webhook', {'id': body['id']})
    except (URLError, ValueError, TimeoutError):
        abort(503)
    return '', 204
