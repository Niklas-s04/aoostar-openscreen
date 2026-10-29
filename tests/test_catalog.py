import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def client_at(path):
    from openscreen_catalog.app import create_app
    return TestClient(create_app(path), base_url='http://localhost', client=('127.0.0.1', 1234))


def test_startup_render_persistence(tmp_path):
    with client_at(tmp_path) as client:
        assert client.get('/healthz').status_code == 200
        config = client.get('/api/config').json()
        config['title'] = 'Persistent title'
        assert client.put('/api/config', json=config, headers={'X-OpenScreen': '1'}).status_code == 200
        assert client.get('/api/output.png').content.startswith(b'\x89PNG')
    with client_at(tmp_path) as client:
        assert client.get('/api/config').json()['title'] == 'Persistent title'


@pytest.mark.parametrize('change', [
    {'sources': [{'id': 'nas', 'kind': kind, 'name': 'NAS'}]}
    for kind in ['truenas', 'docker', 'proxmox', 'json', 'local']
] + [{'hardware_enabled': True}, {'device': '/dev/ttyACM0'},
     {'output': {'kind': 'broker'}}, {'output': {'kind': 'aoostar'}},
     {'secret': 'api-key'}, {'url': 'https://localhost/api/current'}])
def test_forbidden_configuration_rejected_without_rewriting(tmp_path, change):
    with client_at(tmp_path) as client:
        config = client.get('/api/config').json() | change
        assert client.put('/api/config', json=config, headers={'X-OpenScreen': '1'}).status_code == 422
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    original = path.read_bytes()
    with pytest.raises(ValueError):
        client_at(tmp_path)
    assert path.read_bytes() == original


@pytest.mark.parametrize('headers', [
    {}, {'X-OpenScreen': '1', 'Origin': 'https://evil.example'},
    {'X-OpenScreen': '1', 'Sec-Fetch-Site': 'cross-site'},
])
def test_origin_required_for_writes(tmp_path, headers):
    with client_at(tmp_path) as client:
        assert client.put('/api/config', json={}, headers=headers).status_code == 403


def test_no_management_or_device_endpoints(tmp_path):
    with client_at(tmp_path) as client:
        for path in ['/api/sources/nas/test', '/api/displays/probe', '/api/displays/trial']:
            assert client.post(path, json={}, headers={'X-OpenScreen': '1'}).status_code == 404
        assert client.get('/', headers={'host': 'evil.example'}).status_code == 403
        assert client.get('/', headers={'origin': 'https://evil.example'}).status_code == 403


def test_public_network_and_empty_hosts_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENSCREEN_ALLOWED_NETWORKS', '0.0.0.0/0')
    with pytest.raises(ValueError):
        client_at(tmp_path)


def test_peer_and_forwarded_headers_cannot_bypass_policy(tmp_path):
    from openscreen_catalog.app import create_app
    with TestClient(create_app(tmp_path), base_url='http://localhost', client=('203.0.113.1', 123)) as client:
        assert client.get('/api/config', headers={'X-Forwarded-For': '127.0.0.1', 'Forwarded': 'for=127.0.0.1'}).status_code == 403


def test_body_limits_and_unknown_endpoints(tmp_path):
    with client_at(tmp_path) as client:
        assert client.put('/api/config', content=b'x'*(1024*1024+1), headers={'X-OpenScreen': '1'}).status_code == 413
        assert client.get('/static/app.js').status_code == 404
        assert client.get('/static/discovery.js').status_code == 404


def test_failure_preserves_previous_config(tmp_path, monkeypatch):
    from openscreen_catalog.runtime import Runtime
    import os
    runtime = Runtime(tmp_path)
    runtime.save(runtime.config)
    original = runtime.path.read_bytes()
    changed = runtime.config.model_copy(update={'title': 'must not persist'})
    def fail_replace(*args):
        raise PermissionError('denied')
    monkeypatch.setattr(os, 'replace', fail_replace)
    with pytest.raises(PermissionError):
        runtime.save(changed)
    assert runtime.path.read_bytes() == original
    assert runtime.config.title != 'must not persist'
    assert not list(tmp_path.glob('.config-*'))


def test_invalid_startup_config_does_not_echo_sensitive_values(tmp_path):
    from openscreen_catalog.runtime import Runtime
    (tmp_path/'config.json').write_text('{"secret":"do-not-log-this-value"}')
    with pytest.raises(ValueError) as error:
        Runtime(tmp_path)
    assert 'do-not-log-this-value' not in str(error.value)
