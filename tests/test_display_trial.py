import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from openscreen.app import create_app
from openscreen.display_trial import DisplayTrial, test_pattern as pattern
from openscreen.models import Config, Output, Page, PlayerReport
from openscreen.runtime import Runtime


HEADERS = {'X-OpenScreen': '1'}


def browser_config():
    return Config(title='Calibration draft', output=Output(kind='browser', width=640, height=360, auto_size=False))


def test_trial_copies_config_and_pattern_preserves_target_dimensions():
    config = browser_config()
    trial = DisplayTrial(config)
    config.title = 'Later edit'
    assert trial.config.title == 'Calibration draft'
    assert len(trial.id) == 32 and not trial.sent
    for rotation in (0, 90, 180, 270):
        output = config.output.model_copy(update={'rotation': rotation})
        image = pattern(output)
        assert image.size == (640, 360) and image.mode == 'RGB'
        assert len(image.getcolors(640*360)) > 6


def test_cancel_and_timeout_restore_config_without_persistence(tmp_path):
    runtime = Runtime(tmp_path, tmp_path, demo=True)
    original = runtime.config.model_dump_json()
    status = runtime.begin_trial(browser_config())
    assert runtime.effective_config().title == 'Calibration draft'
    assert runtime.config.model_dump_json() == original
    assert not runtime.path.exists()
    with pytest.raises(ValueError):
        runtime.begin_trial(browser_config())
    with pytest.raises(ValueError):
        runtime.save(browser_config())
    runtime.finish_trial(status['id'])
    assert runtime.effective_config().model_dump_json() == original
    runtime.begin_trial(browser_config())
    runtime.trial.deadline = 0
    assert runtime.active_trial() is None
    assert runtime.effective_config().model_dump_json() == original
    assert not runtime.path.exists()


def test_trial_endpoints_require_csrf_correct_id_and_actual_output_request(tmp_path):
    app = create_app(data_dir=tmp_path, demo=True, start_workers=False)
    with TestClient(app, client=('127.0.0.1', 50000)) as client:
        config = browser_config().model_dump()
        assert client.post('/api/displays/trial', json=config).status_code == 403
        assert client.post('/api/displays/trial', json=config, headers={**HEADERS, 'Origin': 'https://evil.test'}).status_code == 403
        trial = client.post('/api/displays/trial', json=config, headers=HEADERS).json()
        endpoint = f"/api/displays/trial/{trial['id']}"
        assert client.post(endpoint+'/confirm', headers=HEADERS).status_code == 400
        assert client.post('/api/displays/trial/wrong/cancel', headers=HEADERS).status_code == 400
        assert client.post(endpoint+'/cancel').status_code == 403
        assert client.get('/api/preview.png').status_code == 200
        assert client.post(endpoint+'/confirm', headers=HEADERS).status_code == 400
        frame = client.get('/api/output.png')
        assert Image.open(io.BytesIO(frame.content)).size == (640, 360)
        assert client.post(endpoint+'/confirm', headers=HEADERS).json() == {'ok': True, 'saved': True}
        assert client.get('/api/config').json()['title'] == 'Calibration draft'
        assert app.state.runtime.path.exists()


def test_physical_rotation_waits_for_visibility_and_does_not_queue_pages(tmp_path):
    runtime = Runtime(tmp_path, tmp_path, demo=True)
    runtime.demo = False
    config = Config(hardware_enabled=True, rotation=10, pages=[Page(id=p, name=p) for p in ('one', 'two', 'three')])
    assert runtime.page(config, 100) == 'one'
    assert runtime.page(config, 500) == 'one'  # No successful output yet.
    runtime.visible_since = 500
    assert runtime.page(config, 509) == 'one'
    assert runtime.page(config, 510) == 'two'
    assert runtime.page(config, 900) == 'two'  # Only latest next page, no catch-up backlog.
    runtime.visible_page, runtime.visible_since = 'two', 905
    assert runtime.page(config, 914) == 'two'
    assert runtime.page(config, 915) == 'three'


def test_failed_confirmation_keeps_trial_available_for_retry(tmp_path, monkeypatch):
    runtime = Runtime(tmp_path, tmp_path, demo=True)
    status = runtime.begin_trial(browser_config())
    trial = runtime.trial
    trial.sent = True
    def failed_save(config, **kwargs):
        raise OSError('disk unavailable')
    monkeypatch.setattr(runtime, 'save', failed_save)
    with pytest.raises(OSError):
        runtime.finish_trial(status['id'], confirm=True)
    assert runtime.active_trial() is trial


def test_output_render_race_does_not_confirm_replacement_trial(tmp_path, monkeypatch):
    app = create_app(data_dir=tmp_path, demo=True, start_workers=False)
    runtime = app.state.runtime
    runtime.begin_trial(browser_config())
    replacement = DisplayTrial(browser_config())
    def interrupted_render(*args, **kwargs):
        runtime.trial = replacement
        return Image.new('RGB', (640, 360))
    monkeypatch.setattr(runtime, 'image', interrupted_render)
    with TestClient(app, client=('127.0.0.1', 50000)) as client:
        assert client.get('/api/output.png').status_code == 200
    assert not replacement.sent


def test_identical_physical_pages_advance_visibility_without_resending(tmp_path, monkeypatch):
    runtime = Runtime(tmp_path, tmp_path, demo=True)
    runtime.demo = False
    runtime.config = Config(hardware_enabled=True, pages=[Page(id=p, name=p) for p in ('one', 'two')])
    class Stop:
        count = 0
        def is_set(self):
            return self.count >= 2
        def wait(self, seconds):
            self.count += 1
    runtime.stop = Stop()
    class Transport:
        device = 'auto'
        sent = 0
        def send(self, image):
            self.sent += 1
        def close(self):
            pass
    transport = Transport()
    monkeypatch.setattr('openscreen.runtime.open_transport', lambda *args: transport)
    monkeypatch.setattr(runtime, 'page', lambda config, now: 'one' if runtime.stop.count == 0 else 'two')
    monkeypatch.setattr(runtime, 'image', lambda *args, **kwargs: Image.new('RGB', (960, 376)))
    runtime.output()
    assert transport.sent == 1
    assert runtime.visible_page == 'two'
    assert runtime.visible_since is not None


def test_confirm_preserves_tested_dimensions_when_player_resizes(tmp_path):
    runtime = Runtime(tmp_path, tmp_path, demo=True)
    player_id = 'a' * 32
    runtime.players.report(PlayerReport(id=player_id, width=640, height=360))
    config = browser_config()
    config.output.auto_size = True
    config.output.player_id = player_id
    trial = runtime.begin_trial(config)
    assert runtime.trial.config.output.width == 640
    runtime.trial.sent = True
    runtime.players.report(PlayerReport(id=player_id, width=1280, height=720))
    runtime.finish_trial(trial['id'], confirm=True)
    persisted = Config.model_validate_json(runtime.path.read_text(encoding='utf-8'))
    assert (persisted.output.width, persisted.output.height) == (640, 360)
    assert persisted.output.auto_size
    # Ordinary saving still resolves the currently selected player's size.
    changed = runtime.config.model_copy(deep=True)
    changed.output.width = 800
    runtime.save(changed)
    assert (runtime.config.output.width, runtime.config.output.height) == (1280, 720)


def test_trial_start_during_transport_open_does_not_acknowledge_old_config(tmp_path, monkeypatch):
    runtime = Runtime(tmp_path, tmp_path, demo=True)
    runtime.demo = False
    runtime.config = Config(hardware_enabled=True)
    changed = runtime.config.model_copy(deep=True)
    changed.title = 'New trial started while opening transport'
    replacement = DisplayTrial(changed)
    class Stop:
        done = False
        def is_set(self):
            return self.done
        def wait(self, seconds):
            self.done = True
    runtime.stop = Stop()
    class Transport:
        device = 'auto'
        def send(self, image):
            pass
        def close(self):
            pass
    def interrupted_open(*args):
        runtime.trial = replacement
        return Transport()
    monkeypatch.setattr('openscreen.runtime.open_transport', interrupted_open)
    monkeypatch.setattr(runtime, 'image', lambda *args, **kwargs: Image.new('RGB', (960, 376)))
    runtime.output()
    assert runtime.active_trial() is replacement
    assert not replacement.sent


def test_transport_reopens_when_same_device_output_changes(tmp_path, monkeypatch):
    runtime = Runtime(tmp_path, tmp_path, demo=True)
    runtime.demo = False
    runtime.config = Config(hardware_enabled=True)
    class Stop:
        count = 0
        def is_set(self):
            return self.count >= 2
        def wait(self, seconds):
            self.count += 1
            runtime.config.output.rotation = 180
    runtime.stop = Stop()
    transports = []
    class Transport:
        device = 'auto'
        closed = False
        def send(self, image):
            pass
        def close(self):
            self.closed = True
    def open_test(output, device):
        transport = Transport()
        transports.append((output.model_copy(deep=True), transport))
        return transport
    monkeypatch.setattr('openscreen.runtime.open_transport', open_test)
    monkeypatch.setattr(runtime, 'image', lambda *args, **kwargs: Image.new('RGB', (960, 376)))
    runtime.output()
    assert [output.rotation for output, _ in transports] == [0, 180]
    assert all(transport.closed for _, transport in transports)
