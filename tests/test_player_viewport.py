"""Exercise the real player document and viewport observer in Chromium."""
import os
import io
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright


STATIC = Path(__file__).resolve().parents[1] / 'openscreen' / 'static'


@pytest.mark.parametrize('dpr', [1, 1.25, 2])
def test_player_reports_render_area_and_debounces_resizes(dpr):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_EXECUTABLE_PATH'))
        context = browser.new_context(viewport={'width': 800, 'height': 600}, device_scale_factor=dpr,
                                      screen={'width': 1920, 'height': 1080})
        page = context.new_page()
        if dpr != 1:
            # Chromium's emulated DPR leaves native device-pixel boxes at the
            # host scale. Exercise the standards fallback for CSS-only observers.
            page.add_init_script('''
                const NativeObserver = ResizeObserver;
                window.ResizeObserver = class extends NativeObserver {
                    constructor(callback) {
                        super(entries => callback(entries.map(entry => ({
                            contentRect: entry.contentRect
                        }))));
                    }
                };
            ''')
        reports = []
        errors = []
        frame = io.BytesIO()
        Image.new('RGB', (960, 376), 'red').save(frame, format='PNG')
        page.on('pageerror', lambda error: errors.append(str(error)))

        def serve(route):
            path = route.request.url.split('localhost')[1].split('?')[0]
            if path == '/api/displays/report':
                reports.append(route.request.post_data_json)
                route.fulfill(json={'ok': True})
            elif path == '/api/config':
                route.fulfill(json={'output': {'interval': 60}})
            elif path == '/api/output.png':
                route.fulfill(content_type='image/png', body=frame.getvalue())
            else:
                name = 'player.html' if path == '/player' else path.rsplit('/', 1)[-1]
                route.fulfill(path=str(STATIC / name))

        page.route('http://localhost/**', serve)
        page.goto('http://localhost/player')
        page.wait_for_timeout(500)
        assert [(r['width'], r['height']) for r in reports] == [(round(800*dpr), round(600*dpr))]
        assert set(reports[0]) == {'id', 'width', 'height'}
        assert page.locator('#output').evaluate('(image) => image.naturalWidth') == 960
        for width in (810, 820, 830):
            page.set_viewport_size({'width': width, 'height': 600})
            page.wait_for_timeout(30)
        page.wait_for_timeout(500)
        assert len(reports) == 2
        assert (reports[-1]['width'], reports[-1]['height']) == (round(830*dpr), round(600*dpr))
        page.set_viewport_size({'width': 600, 'height': 830})
        page.wait_for_timeout(500)
        assert (reports[-1]['width'], reports[-1]['height']) == (round(600*dpr), round(830*dpr))
        count = len(reports)
        page.set_viewport_size({'width': 4000, 'height': 3000})
        page.wait_for_timeout(500)
        assert len(reports) == count
        page.set_viewport_size({'width': 50, 'height': 20})
        page.wait_for_timeout(500)
        assert len(reports) == count
        assert errors == []
        browser.close()
