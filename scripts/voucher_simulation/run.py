#!/usr/bin/env python3
"""Start/stop the isolated, loopback-only voucher playground."""
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
SERVER = Path(__file__).with_name('server.py')
DATA = ROOT / '.local' / 'voucher-simulation'
PIDS = DATA / 'processes.json'


def running(pid):
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'args='], capture_output=True, text=True)
    return str(SERVER) in result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'status'], nargs='?', default='start')
    action = parser.parse_args().action
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    saved = json.loads(PIDS.read_text()) if PIDS.exists() else {}
    active = {role: pid for role, pid in saved.items() if running(pid)}
    if action == 'stop':
        for pid in active.values():
            os.kill(pid, signal.SIGTERM)
        PIDS.write_text('{}')
        print('Simulation gestoppt. Testdaten bleiben erhalten.')
        return
    if action == 'status':
        print('Läuft: ' + ', '.join(active) if active else 'Simulation ist gestoppt.')
        return
    if active:
        if len(active) != 2:
            raise SystemExit('Nur ein Teil läuft. Zuerst stop, anschließend start ausführen.')
        print('Simulation läuft bereits: http://127.0.0.1:5087/gutscheine')
        return
    for port in (5087, 5088):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError as exc:
                raise SystemExit(f'Port {port} nicht verfügbar: {exc}')
    interpreters = {'pos': ROOT.parent / 'POS/.venv/bin/python', 'website': ROOT / '.venv/bin/python'}
    for executable in interpreters.values():
        if not executable.exists():
            raise SystemExit(f'Python-Umgebung fehlt: {executable}. Siehe docs/lokale-gutschein-simulation.md')
    secret_path = DATA / 'secrets.json'
    if not secret_path.exists():
        secret_path.write_text(json.dumps({key: secrets.token_urlsafe(48) for key in ('service','session','voucher')}))
        secret_path.chmod(0o600)
    keys = json.loads(secret_path.read_text())
    env = {k: v for k, v in os.environ.items() if not k.startswith(('POS_', 'SUMUP_', 'SMTP_', 'ONLINE_', 'ADMIN_', 'VOUCHER_', 'FLASK_', 'SECRET_KEY', 'PYTHONPATH', 'INTERN_'))}
    env.update(VOUCHER_LOCAL_SIMULATION='explicit-local-only', VOUCHER_SIM_DATA=str(DATA),
        POS_ENV='development', POS_AUTH_DISABLED='true', POS_DATA_DIR=str(DATA / 'pos'),
        ONLINE_SALES_ENABLED='true', ONLINE_SERVICE_TOKEN=keys['service'],
        ONLINE_PUBLIC_ORIGIN='https://local.invalid', SUMUP_ONLINE_API_KEY='SIMULATION-NOT-A-REAL-KEY',
        SUMUP_ONLINE_MERCHANT_CODE='LOCAL-SIMULATION', SUMUP_SIMULATE='true',
        POS_VOUCHER_SECRET=keys['voucher'], POS_MAIL_MODE='smtp', POS_SMTP_HOST='invalid.local',
        POS_MAIL_FROM='Aixtraball Test <test@example.invalid>', POS_SMTP_VERIFY_TLS='true',
        SECRET_KEY=keys['session'], SESSION_COOKIE_SECURE='false', VOUCHER_SALES_ENABLED='true',
        POS_INTERNAL_URL='http://127.0.0.1:5088', VOUCHER_RATE_DIR=str(DATA / 'limits'))
    processes = {}
    try:
        for role in ('pos','website'):
            with (DATA / (role + '.log')).open('a') as log:
                proc = subprocess.Popen([str(interpreters[role]),str(SERVER),role], cwd=DATA,
                    env=env, stdout=log, stderr=log, start_new_session=True)
                processes[role] = proc
        PIDS.write_text(json.dumps({role: p.pid for role,p in processes.items()}))
        for role, port, path in [('pos',5088,'/simulation'),('website',5087,'/gutscheine')]:
            for _ in range(60):
                if processes[role].poll() is not None:
                    raise RuntimeError(f'{role} konnte nicht starten: {DATA / (role + ".log")}')
                try:
                    with urlopen(f'http://127.0.0.1:{port}{path}', timeout=1) as response:
                        if response.status == 200: break
                except Exception:
                    time.sleep(.25)
            else:
                raise RuntimeError('Start dauerte zu lange; Logs prüfen.')
    except BaseException:
        for proc in processes.values():
            if proc.poll() is None: proc.terminate()
        PIDS.write_text('{}')
        raise
    print('Website: http://127.0.0.1:5087/gutscheine')
    print('Zahlungssteuerung und Testpostfach: http://127.0.0.1:5088/simulation')
    print('Testkasse: http://127.0.0.1:5088/vouchers')
    print('Keine echten Zahlungen oder externen E-Mails. Testdaten: ' + str(DATA))

if __name__ == '__main__':
    main()
