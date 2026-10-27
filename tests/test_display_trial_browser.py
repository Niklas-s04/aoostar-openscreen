"""Exercise temporary display trials through the settings UI and real player."""
import os

from playwright.sync_api import expect, sync_playwright
from test_browser import demo_server


def test_display_trial_cancel_and_confirm_with_active_player(demo_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_EXECUTABLE_PATH'))
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()
        baseline = context.request.get(demo_server + '/api/config').json()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            page.goto(demo_server + '/#settings')
            page.get_by_label('Ausgabetyp', exact=True).select_option('browser')
            page.get_by_label('Gemeldete Größe beim Speichern übernehmen', exact=True).uncheck()
            page.get_by_label('Ausgabebreite', exact=True).fill('800')
            page.get_by_label('Ausgabehöhe', exact=True).fill('480')
            page.get_by_role('button', name='Einstellungen speichern', exact=True).click()
            expect(page.locator('#notice')).to_have_text('Änderungen gespeichert')
            saved = context.request.get(demo_server + '/api/config').json()
            player = context.new_page()
            player.on('pageerror', lambda error: errors.append(str(error)))
            player.goto(demo_server + '/display')
            expect(player.locator('#output')).to_have_js_property('naturalWidth', 800)

            for confirm in (False, True):
                page.get_by_label('Ausgabebreite', exact=True).fill('900')
                page.get_by_label('Ausgabehöhe', exact=True).fill('500')
                page.get_by_role('button', name='Testbild anzeigen', exact=True).click()
                expect(page.locator('#display-trial')).to_be_visible()
                expect(page.locator('#display-trial')).to_contain_text('Testbild aktiv')
                expect(page.get_by_role('button', name='Einstellungen speichern', exact=True)).to_be_disabled()
                assert context.request.get(demo_server + '/api/config').json() == saved
                expect(player.locator('#output')).to_have_js_property('naturalWidth', 900)
                expect(page.locator('#confirm-display-trial')).to_be_enabled(timeout=10000)
                # Cross both countdown redraws and status polling before clicking.
                page.wait_for_timeout(3500)
                expect(page.locator('#display-trial')).to_be_visible()
                assert context.request.get(demo_server + '/api/config').json() == saved
                if confirm:
                    page.locator('#confirm-display-trial').click()
                else:
                    page.locator('#cancel-display-trial').click()
                expect(page.locator('#display-trial')).to_be_hidden()
                expect(page.get_by_role('button', name='Einstellungen speichern', exact=True)).to_be_enabled()
                current = context.request.get(demo_server + '/api/config').json()
                if confirm:
                    assert (current['output']['width'], current['output']['height']) == (900, 500)
                else:
                    assert current == saved
                    expect(player.locator('#output')).to_have_js_property('naturalWidth', 800)
            assert errors == []
        finally:
            trial = context.request.get(demo_server + '/api/status').json().get('trial')
            if trial:
                context.request.post(demo_server + '/api/displays/trial/' + trial['id'] + '/cancel',
                                     data={}, headers={'X-OpenScreen': '1'})
            response = context.request.put(demo_server + '/api/config', data=baseline,
                                            headers={'X-OpenScreen': '1'})
            assert response.ok
            browser.close()
