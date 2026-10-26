import io
from PIL import Image
from fastapi.testclient import TestClient
from openscreen.app import create_app


def client_for(path, **kwargs):
    return TestClient(create_app(data_dir=path, start_workers=False, **kwargs), client=('127.0.0.1', 50000))


def test_demo_config_persists_and_invalid_write_preserves_file(tmp_path):
    with client_for(tmp_path, demo=True) as client:
        config = client.get('/api/config').json()
        config['title'] = 'Mein NAS'
        assert client.put('/api/config',json=config,headers={'X-OpenScreen':'1'}).status_code == 200
        config['pages'] = []
        assert client.put('/api/config',json=config,headers={'X-OpenScreen':'1'}).status_code == 422
        assert client.get('/api/config').json()['title'] == 'Mein NAS'
    with client_for(tmp_path, demo=True) as client:
        assert client.get('/api/config').json()['title'] == 'Mein NAS'


def test_mutations_require_custom_header_and_same_origin(tmp_path):
    with client_for(tmp_path, demo=True) as client:
        config = client.get('/api/config').json()
        assert client.put('/api/config',json=config).status_code == 403
        assert client.put('/api/config',json=config,headers={'X-OpenScreen':'1','Origin':'https://evil.test'}).status_code == 403


def test_live_is_passwordless_and_health_is_minimal(tmp_path):
    with TestClient(create_app(data_dir=tmp_path,start_workers=False),base_url='http://localhost',client=('127.0.0.1',1)) as client:
        assert client.get('/api/config').status_code == 200
        assert client.get('/healthz').json() == {'ok':True}


def test_preview_is_physical_size_and_demo_cannot_enable_hardware(tmp_path):
    with client_for(tmp_path, demo=True) as client:
        image = Image.open(io.BytesIO(client.get('/api/preview.png?page=storage').content))
        assert image.size == (960,376)
        config = client.get('/api/config').json()
        config['hardware_enabled'] = True
        assert client.put('/api/config',json=config,headers={'X-OpenScreen':'1'}).status_code == 400
        assert client.get('/api/status').json()['demo'] is True


def test_demo_rejects_nonlocal_clients(tmp_path):
    with TestClient(create_app(data_dir=tmp_path,demo=True,start_workers=False),client=('10.0.0.1',50000)) as client:
        assert client.get('/api/config').status_code == 403


def test_default_live_rejects_arbitrary_hosts(tmp_path):
    with client_for(tmp_path) as client:
        assert client.get('/api/config').status_code==403
