"""Browser integration against a disposable local demo; no external services."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import pytest
from playwright.sync_api import sync_playwright, expect


@pytest.fixture(scope='module')
def demo_server(tmp_path_factory):
    with socket.socket() as s:
        s.bind(('127.0.0.1',0))
        port=s.getsockname()[1]
    env={**os.environ,'OPENSCREEN_DEMO':'1','OPENSCREEN_DATA':str(tmp_path_factory.mktemp('browser'))}
    process=subprocess.Popen([sys.executable,'-m','uvicorn','openscreen.app:create_app','--factory','--host','127.0.0.1','--port',str(port),'--no-proxy-headers'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    url=f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url+'/healthz',timeout=0.2)
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail('Demo server did not start')
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_navigation_editing_persistence_and_mobile(demo_server, tmp_path):
    errors=[]
    artifacts=tmp_path
    artifacts.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_EXECUTABLE_PATH'))
        page=browser.new_page(viewport={'width':1440,'height':1050},device_scale_factor=1)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
        page.goto(demo_server)
        expect(page.get_by_role('heading',name='Übersicht',exact=True)).to_be_visible()
        expect(page.locator('#preview')).to_be_visible()
        page.screenshot(path=str(artifacts/'ui-overview.png'),full_page=True)
        page.get_by_role('link',name='Display',exact=True).click()
        page.get_by_label('Seitenname',exact=True).fill('Mein System')
        expect(page.get_by_label('Seitenname',exact=True)).to_have_value('Mein System')
        page.get_by_role('button',name='Änderungen speichern').click()
        expect(page.get_by_role('button',name='1. Mein System Aktiv')).to_be_visible()
        page.reload()
        expect(page.get_by_label('Seitenname',exact=True)).to_have_value('Mein System')
        page.screenshot(path=str(artifacts/'ui-display.png'),full_page=True)
        page.get_by_role('link',name='Datenquellen',exact=True).click()
        page.get_by_role('button',name='Datenquelle hinzufügen').click()
        page.get_by_label('Name',exact=True).fill('Docker Test')
        page.get_by_label('Typ',exact=True).select_option('docker')
        page.get_by_label('Endpunkt-URL',exact=True).fill('http://proxy:2375')
        expect(page.get_by_label('Endpunkt-URL',exact=True)).to_have_value('http://proxy:2375')
        page.get_by_role('button',name='Speichern',exact=True).click()
        expect(page.get_by_role('button',name='Docker Test Docker')).to_be_visible()
        page.get_by_role('button',name='Verbindung prüfen').click()
        expect(page.locator('#notice')).to_contain_text('Demo:')
        page.get_by_role('link',name='Warnungen',exact=True).click()
        page.get_by_role('button',name='Warnung hinzufügen').click()
        page.get_by_label('Name der Warnung').fill('CPU Test')
        page.get_by_label('Metrik für Zahlenbedingungen').fill('cpu')
        page.get_by_label('Schwellenwert',exact=True).fill('20')
        page.get_by_label('Verzögerung (Sekunden)').fill('0')
        page.get_by_role('button',name='Speichern',exact=True).click()
        expect(page.locator('.alert-card')).to_contain_text('CPU Test')
        page.get_by_role('button',name='Bedingung testen').click()
        expect(page.locator('#notice')).to_contain_text('Ausgelöst')
        page.screenshot(path=str(artifacts/'ui-alerts.png'),full_page=True)
        page.get_by_role('link',name='Einstellungen',exact=True).click()
        page.get_by_label('Systemname',exact=True).fill('Mein Homelab')
        page.get_by_role('button',name='Einstellungen speichern').click()
        expect(page.locator('#host-name')).to_have_text('Mein Homelab')
        page.set_viewport_size({'width':390,'height':844})
        page.get_by_role('button',name='Navigation öffnen').click()
        page.get_by_role('link',name='Übersicht',exact=True).click()
        expect(page.get_by_role('heading',name='Übersicht',exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(artifacts/'ui-mobile.png'),full_page=True)
        assert not errors, errors
        browser.close()
