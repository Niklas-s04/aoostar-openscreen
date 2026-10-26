import pytest
from fastapi.testclient import TestClient
from openscreen.app import create_app


def app(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENSCREEN_ALLOWED_NETWORKS', '127.0.0.0/8,::1/128,192.168.50.0/24')
    monkeypatch.setenv('OPENSCREEN_ALLOWED_HOSTS', 'localhost,127.0.0.1,192.168.50.250')
    return create_app(data_dir=tmp_path, demo=False, start_workers=False)


def test_passwordless_lan_and_untrusted_sources(tmp_path, monkeypatch):
    application = app(tmp_path, monkeypatch)
    for address, expected in [('192.168.50.50', 200), ('127.0.0.1', 200),
                              ('8.8.8.8', 403), ('192.168.1.4', 403), ('::ffff:8.8.8.8', 403)]:
        with TestClient(application, base_url='http://192.168.50.250:8088', client=(address, 50000)) as client:
            assert client.get('/api/config', headers={'X-Forwarded-For':'192.168.50.50'}).status_code == expected
            assert client.get('/healthz').status_code == expected


def test_rebinding_cross_site_and_mutation_protection(tmp_path, monkeypatch):
    with TestClient(app(tmp_path, monkeypatch), base_url='http://192.168.50.250:8088', client=('192.168.50.50', 1)) as client:
        assert client.get('/api/config', headers={'Host':'attacker.example'}).status_code == 403
        assert client.get('/api/config', headers={'Sec-Fetch-Site':'cross-site'}).status_code == 403
        config = client.get('/api/config').json()
        assert client.put('/api/config', json=config).status_code == 403
        assert client.put('/api/config', json=config, headers={'X-OpenScreen':'1','Origin':'https://192.168.50.250:8088'}).status_code == 403
        assert client.put('/api/config', json=config, headers={'X-OpenScreen':'1','Origin':'http://192.168.50.250:8088'}).status_code == 200


def test_source_and_device_boundaries(tmp_path, monkeypatch):
    with TestClient(app(tmp_path, monkeypatch), base_url='http://127.0.0.1', client=('127.0.0.1',1)) as client:
        config = client.get('/api/config').json()
        config['sources'].append({'id':'bad','name':'bad','kind':'json','url':'http://169.254.169.254/latest/meta-data'})
        assert client.put('/api/config', json=config, headers={'X-OpenScreen':'1'}).status_code == 400
        config['sources'].pop()
        config['device'] = '/dev/sda'
        assert client.put('/api/config', json=config, headers={'X-OpenScreen':'1'}).status_code == 400


def test_public_network_allowlist_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENSCREEN_ALLOWED_NETWORKS','0.0.0.0/0')
    with pytest.raises(ValueError):
        create_app(data_dir=tmp_path, start_workers=False)
