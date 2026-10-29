import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect


@pytest.fixture
def catalog_server(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen([
        sys.executable, '-m', 'uvicorn', 'openscreen_catalog.app:create_app',
        '--factory', '--host', '127.0.0.1', '--port', str(port), '--no-proxy-headers',
    ], env={**os.environ, 'OPENSCREEN_DATA': str(tmp_path)},
       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    url = f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url + '/healthz', timeout=.2)
                break
            except OSError:
                time.sleep(.1)
        else:
            pytest.fail('Catalog startup failed')
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_catalog_editor_and_player(catalog_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(catalog_server)
        expect(page.locator('[data-edit-page]')).to_have_count(1)
        page.get_by_role('button', name='OpenScreen Catalog Text', exact=True).click()
        page.get_by_label('Text', exact=True).fill('Catalog persistence')
        page.get_by_role('button', name='Änderungen speichern', exact=True).click()
        expect(page.locator('#editor-dirty')).to_have_text('Gespeichert')
        page.reload()
        expect(page.get_by_role('button', name='Catalog persistence Text', exact=True)).to_be_visible()
        expect(page.locator('#editor-preview')).to_have_js_property('naturalWidth', 960)
        assert 'truenas' not in page.locator('select').all_text_contents()
        if directory := os.getenv('OPENSCREEN_SCREENSHOT_DIR'):
            Path(directory).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(directory)/'editor.png'), full_page=True)
        page.goto(catalog_server + '/display')
        expect(page.locator('#output')).to_have_js_property('naturalWidth', 960)
        expect(page.locator('#player-status')).to_have_text('')
        if directory:
            page.screenshot(path=str(Path(directory)/'player.png'))
        assert not errors
        browser.close()
