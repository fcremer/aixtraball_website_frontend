"""Exercise the running LOCAL simulator, without external payments or mail."""
import http.cookiejar
import re
import time
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPCookieProcessor

SITE='http://127.0.0.1:5087'
POS='http://127.0.0.1:5088'

def browser():
    return build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

def get(client,url,data=None):
    with client.open(url, data=urlencode(data).encode() if data is not None else None, timeout=10) as response:
        return response.read().decode(), response.geturl()

def checkout(amount):
    client=browser()
    html,_=get(client,SITE+'/gutscheine')
    assert 'Lokale Simulation' in html
    csrf=re.search(r'name="csrf" value="([^"]+)"',html).group(1)
    get(client,SITE+'/gutscheine',{'csrf':csrf,'amount':amount,'email':'simulation@example.invalid'})
    get(client,SITE+'/gutscheine/bezahlen',{'csrf':csrf})
    html,url=get(client,SITE+'/gutscheine/start',{'csrf':csrf})
    assert url.startswith(POS+'/simulation/pay/'), url
    return client,url

def wait(client,text):
    for _ in range(30):
        html,_=get(client,SITE+'/gutscheine/status')
        if text in html: return
        time.sleep(.5)
    raise AssertionError('Expected status not reached: '+text)

def main():
    for amount in (15,30,50,100):
        client,url=checkout(amount)
        get(client,url,{'outcome':'PAID'})
        wait(client,'wurde per E-Mail versendet')
        # A duplicate successful provider notification must reuse the order.
        get(client,url,{'outcome':'PAID'})
    client,url=checkout(15)
    get(client,url,{'outcome':'FAILED'})
    wait(client,'Zahlung nicht abgeschlossen')
    get(client,url,{'outcome':'PAID'})
    wait(client,'wurde per E-Mail versendet')
    client,url=checkout(30)
    get(client,url,{'outcome':'EXPIRED'})
    wait(client,'Zahlung abgelaufen')
    control=browser()
    html,_=get(control,POS+'/simulation')
    assert 'Lokaler Mailversand: bereit' in html
    get(control,POS+'/simulation',{})
    try:
        client,url=checkout(50)
        get(client,url,{'outcome':'PAID'})
        wait(client,'Der E-Mail-Versand läuft')
    finally:
        get(control,POS+'/simulation',{})
    wait(client,'wurde per E-Mail versendet')
    html,_=get(control,POS+'/simulation')
    link=re.search(r'href="(/simulation/mail/[^"]+)"',html).group(1)
    mail,_=get(control,POS+link)
    assert 'data:image/png;base64,' in mail
    print('OK: four amounts, failure/retry, expiry, duplicate notification, mail outage/recovery and QR email preview.')

if __name__=='__main__': main()
