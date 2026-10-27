from types import SimpleNamespace
import pytest
from openscreen import discovery
from openscreen.models import Config, Output, PlayerReport
from tests.test_app import client_for


def port(device='/dev/ttyACM0',vid=0x0416,pid=0x90a1):
    return SimpleNamespace(device=device,vid=vid,pid=pid)


def test_discovery_is_passive_filters_unknown_and_deduplicates_alias(monkeypatch):
    monkeypatch.setattr(discovery,'ports',lambda:[port(),port('/dev/ttyUSB0',vid=123)])
    monkeypatch.setattr(discovery,'accessible',lambda path:True)
    monkeypatch.setattr(discovery,'character_device',lambda path:True)
    monkeypatch.setattr(discovery.os.path,'realpath',lambda path:'/dev/ttyACM0' if path=='/dev/aoostar' else path)
    devices=discovery.serial_displays()
    assert len(devices)==1 and devices[0]['device']=='/dev/aoostar'
    assert devices[0]['size_source']=='adapter-profile'
    assert devices[0]['verified'] is False


def test_manual_devices_need_recognition_or_explicit_allowlist(monkeypatch):
    monkeypatch.setattr(discovery,'ports',lambda:[port()])
    assert discovery.allowed_device('/dev/ttyACM0')
    assert not discovery.allowed_device('/dev/ttyUSB3')
    monkeypatch.setenv('OPENSCREEN_ALLOWED_DEVICES','/dev/ttyUSB3,/dev/sda,/etc/passwd')
    assert discovery.allowed_device('/dev/ttyUSB3')
    assert not discovery.allowed_device('/dev/sda')
    assert not discovery.allowed_device('/etc/passwd')
    assert not discovery.allowed_device('socket://example.org:1234')


def test_ambiguous_auto_never_guesses(monkeypatch):
    monkeypatch.setattr(discovery,'serial_displays',lambda:[{'device':'one'},{'device':'two'}])
    assert not discovery.inspect_output(Config(),discovery.PlayerRegistry())['ok']


def test_browser_registry_expiry_and_auto_size(monkeypatch):
    registry=discovery.PlayerRegistry()
    monkeypatch.setattr(discovery.time,'monotonic',lambda:10)
    registry.report(PlayerReport(id='a'*32,width=1920,height=1080))
    config=Config(output=Output(kind='browser',player_id='a'*32))
    result=discovery.inspect_output(config,registry)
    assert result['output']['width']==1920 and result['size_source']=='player-viewport'
    config.output.auto_size=False
    assert discovery.inspect_output(config,registry)['output']['width']==960
    monkeypatch.setattr(discovery.time,'monotonic',lambda:101)
    assert registry.list()==[]


def test_registry_is_bounded():
    registry=discovery.PlayerRegistry()
    for i in range(16):
        registry.report(PlayerReport(id=f'{i:032x}',width=800,height=480))
    with pytest.raises(ValueError):
        registry.report(PlayerReport(id='f'*32,width=800,height=480))


def test_report_probe_save_and_access_controls(tmp_path):
    with client_for(tmp_path,demo=True) as client:
        body={'id':'b'*32,'width':1280,'height':720}
        assert client.post('/api/displays/report',json=body).status_code==403
        headers={'X-OpenScreen':'1'}
        assert client.post('/api/displays/report',json=body,headers=headers).status_code==200
        assert client.get('/api/displays').json()['players'][0]['id']==body['id']
        config=client.get('/api/config').json()
        config['output'].update(kind='browser',player_id=body['id'])
        probe=client.post('/api/displays/probe',json=config,headers=headers).json()
        assert probe['output']['width']==1280
        assert client.put('/api/config',json=config,headers=headers).status_code==200
        assert client.get('/api/config').json()['output']['height']==720
        config['output'].update(auto_size=False,width=800,height=480)
        assert client.put('/api/config',json=config,headers=headers).status_code==200
        assert client.get('/api/config').json()['output']['width']==800


def test_enable_missing_hardware_does_not_save(tmp_path,monkeypatch):
    monkeypatch.setattr(discovery,'accessible',lambda device:False)
    with client_for(tmp_path,demo=False) as client:
        # Live access requires an explicitly permitted Host.
        headers={'X-OpenScreen':'1','Host':'localhost'}
        config=client.get('/api/config',headers=headers).json()
        config.update(device='/dev/aoostar',hardware_enabled=True)
        assert client.put('/api/config',json=config,headers=headers).status_code==400
        assert client.get('/api/config',headers=headers).json()['hardware_enabled'] is False


def test_saved_device_can_be_temporarily_absent_after_restart(tmp_path,monkeypatch):
    from openscreen.runtime import Runtime
    monkeypatch.setattr(discovery,'ports',lambda:[])
    config=Config(device='/dev/ttyACM7',hardware_enabled=True)
    (tmp_path/'config.json').write_text(config.model_dump_json(),encoding='utf-8')
    runtime=Runtime(tmp_path,tmp_path)
    config.title='Still editable offline'
    runtime.save(config)
    assert runtime.config.title==config.title
    config.hardware_enabled=False
    runtime.save(config)
    assert runtime.config.hardware_enabled is False


def test_api_can_probe_and_disable_saved_unplugged_device(tmp_path,monkeypatch):
    monkeypatch.setattr(discovery,'ports',lambda:[])
    monkeypatch.setattr(discovery,'accessible',lambda path:False)
    config=Config(device='/dev/ttyACM7',hardware_enabled=True)
    (tmp_path/'config.json').write_text(config.model_dump_json(),encoding='utf-8')
    headers={'Host':'localhost','X-OpenScreen':'1'}
    with client_for(tmp_path,demo=False) as client:
        probe=client.post('/api/displays/probe',json=config.model_dump(),headers=headers)
        assert probe.status_code==200 and probe.json()['ok'] is False
        config.title='Offline settings'
        assert client.put('/api/config',json=config.model_dump(),headers=headers).status_code==200
        config.hardware_enabled=False
        assert client.put('/api/config',json=config.model_dump(),headers=headers).status_code==200
