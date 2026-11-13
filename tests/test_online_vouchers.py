import pytest
from app.app import app
from app import online_vouchers as online

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('VOUCHER_RATE_DIR',str(tmp_path))
    monkeypatch.setenv('VOUCHER_SALES_ENABLED','true')
    monkeypatch.setenv('ONLINE_SERVICE_TOKEN','s'*40)
    monkeypatch.setenv('POS_INTERNAL_URL','http://pos:8000')
    app.config.update(TESTING=True,SECRET_KEY='test-secret',SESSION_COOKIE_SECURE=False)
    return app.test_client()

def csrf(client):
    client.get('/gutscheine')
    with client.session_transaction() as s: return s['voucher_csrf']

def test_validation_and_csrf(client):
    token=csrf(client)
    assert client.post('/gutscheine',data={'amount':'15','email':'test@example.invalid'}).status_code==403
    response=client.post('/gutscheine',data={'csrf':token,'amount':'1','email':'test@example.invalid'})
    assert 'Bitte wähle' in response.text
    assert response.headers['Cache-Control']=='no-store'

def test_purchase_identity_survives_remote_timeout(client,monkeypatch):
    token=csrf(client)
    client.post('/gutscheine',data={'csrf':token,'amount':'30','email':'test@example.invalid'})
    client.post('/gutscheine/bezahlen',data={'csrf':token})
    with client.session_transaction() as s: identity=s['voucher_order']
    def failure(*args,**kwargs): raise TimeoutError
    monkeypatch.setattr(online,'pos',failure)
    assert client.post('/gutscheine/start',data={'csrf':token}).status_code==302
    client.post('/gutscheine/bezahlen',data={'csrf':token})
    with client.session_transaction() as s: assert s['voucher_order']==identity

def test_no_false_delivery_confirmation(client,monkeypatch):
    csrf(client)
    with client.session_transaction() as s: s['voucher_order']='online-'+'a'*32
    monkeypatch.setattr(online,'pos',lambda *a:dict(status='completed',delivery='pending'))
    html=client.get('/gutscheine/status?success=true').text
    assert 'Zahlung erfolgreich' in html and 'Der E-Mail-Versand läuft' in html
    assert 'wurde per E-Mail versendet' not in html

def test_unconfigured_page(client,monkeypatch):
    monkeypatch.setenv('VOUCHER_SALES_ENABLED','false')
    assert 'noch nicht verfügbar' in client.get('/gutscheine').text

def test_status_request_has_no_empty_json_body(client,monkeypatch):
    captured=[]
    class Response:
        status=200
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return b'{}'
    def fake_open(req,**kwargs):
        captured.append(req)
        return Response()
    monkeypatch.setattr(online,'urlopen',fake_open)
    online.pos('GET','/internal/online-orders/test')
    assert not captured[0].has_header('Content-type')
    assert captured[0].data is None


def test_production_redirect_rejects_local_simulator():
    assert not online.payment_redirect_allowed('http://127.0.0.1:5088/simulation/pay/test')
    assert online.payment_redirect_allowed('https://checkout.sumup.com/pay/test')
