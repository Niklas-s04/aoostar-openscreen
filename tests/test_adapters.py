import pytest
from PIL import Image

from openscreen.adapters import Adapter, AdapterRegistry, ADAPTERS, Capabilities, Mode
from openscreen.models import Output
from openscreen.outputs import validate_output


class Alternate(Adapter):
    id = 'synthetic'
    broker_serial = True

    def get_capabilities(self, device_id=''):
        return Capabilities(self.id,'1',device_id,(Mode('small',128,64,'rgb888'),),24576)

    def send_encoded(self, transport, frame, mode, deadline):
        transport.write(frame)


def test_trusted_extension_has_independent_dimensions_and_encoding():
    adapter=AdapterRegistry((Alternate(),)).get('synthetic')
    caps=adapter.get_capabilities('fixture')
    output=Output(kind='broker',adapter_id='synthetic',width=128,height=64,pixel_format='rgb888')
    mode=validate_output(output,caps)
    frame=adapter.encode(Image.new('RGB',(128,64),'red'),caps,mode)
    assert frame==bytes((255,0,0))*128*64
    with pytest.raises(ValueError):
        caps.validate_frame(mode,frame[:-1])
    with pytest.raises(ValueError):
        caps.select(960,376)
    with pytest.raises(ValueError):
        validate_output(Output(kind='broker',width=128,height=64),caps)
    with pytest.raises(ValueError):
        ADAPTERS.get('synthetic')


def test_legacy_profiles_and_bounded_untrusted_inventory():
    assert Output().adapter_id=='aoostar'
    assert Output(kind='browser').adapter_id=='browser'
    assert Output(kind='broker',width=128,height=64).width==128
    caps=ADAPTERS.get('aoostar').get_capabilities('fixture')
    assert Capabilities.from_dict(caps.to_dict())==caps
    with pytest.raises(ValueError):
        Capabilities.from_dict({**caps.to_dict(),'max_frame_bytes':10**12})
    with pytest.raises(ValueError):
        Mode('huge',3840,3840,'rgb888')


def test_browser_encoding_validates_png_and_rotation():
    adapter=ADAPTERS.get('browser')
    caps=adapter.get_capabilities(width=128,height=64)
    frame=adapter.encode(Image.new('RGB',(128,64)),caps,caps.modes[0])
    caps.validate_frame(caps.modes[0],frame)
    with pytest.raises(ValueError):
        adapter.encode(Image.new('RGB',(64,128)),caps,caps.modes[0])


def test_broker_rejects_forged_capabilities_and_changed_modes(monkeypatch):
    from openscreen import broker_client
    key='a'*32
    caps=ADAPTERS.get('aoostar').get_capabilities(key).to_dict()
    item={'id':key,'generation':'b'*32,'verified':True,'width':960,'height':376,
          'capabilities':caps}
    monkeypatch.setattr(broker_client,'request',lambda *args: {'version':1,'devices':[item],'candidates':[]})
    assert len(broker_client.inventory()['devices'])==1
    item['capabilities']={**caps,'modes':[{'id':'fake','width':128,'height':64,'pixel_format':'rgb888'}]}
    assert broker_client.inventory()['devices']==[]
    item['capabilities']=caps
    transport=broker_client.BrokerTransport('broker:'+key,Output(kind='broker',width=128,height=64))
    with pytest.raises(ValueError):
        transport.send(Image.new('RGB',(128,64)))


def synthetic_broker(monkeypatch):
    from dataclasses import replace
    from unittest.mock import Mock
    from openscreen import broker_client
    from openscreen.broker import BrokerManager, Connection
    from tests.test_broker import candidate, KEY
    registry=AdapterRegistry((ADAPTERS.get('aoostar'),Alternate()))
    manager=BrokerManager(registry=registry)
    port=Mock()
    manager.connections[KEY]=Connection(replace(candidate(),adapter_id='synthetic'),port)
    monkeypatch.setattr(broker_client,'ADAPTERS',registry)
    return manager,port


def exercise_synthetic_broker(monkeypatch, request):
    from openscreen import broker_client
    from tests.test_broker import KEY
    monkeypatch.setattr(broker_client,'request',request)
    device=broker_client.inventory()['devices'][0]
    assert (device['width'],device['height'])==(128,64)
    transport=broker_client.BrokerTransport('broker:'+KEY,
        Output(kind='broker',adapter_id='synthetic',width=128,height=64))
    transport.send(Image.new('RGB',(128,64),'red'))
    assert transport.identity==KEY
    generation=device['generation']
    for suffix,body in [('mode=small&generation='+generation,b'x'),
                        ('mode=wrong&generation='+generation,bytes(24576)),
                        ('mode=small&generation='+'f'*32,bytes(24576))]:
        import httpx
        with pytest.raises(httpx.HTTPStatusError):
            request('POST','/v1/devices/'+KEY+'/frame?'+suffix,body)


def test_alternate_adapter_crosses_broker_data_plane(monkeypatch):
    from fastapi.testclient import TestClient
    from openscreen.broker import create_app
    manager,port=synthetic_broker(monkeypatch)
    with TestClient(create_app(manager,start_worker=False)) as client:
        def request(method,path,content=None):
            response=client.request(method,path,content=content,headers={'content-type':'application/octet-stream'})
            response.raise_for_status()
            return response.json()
        exercise_synthetic_broker(monkeypatch,request)
        port.write.assert_called_once_with(bytes((255,0,0))*128*64)


@pytest.mark.skipif(__import__('sys').platform!='linux',reason='Real Linux Unix socket')
def test_alternate_adapter_real_unix_socket(monkeypatch,tmp_path):
    import threading
    import time
    import uvicorn
    from openscreen import broker_client
    from openscreen.broker import create_app,bind_socket
    manager,port=synthetic_broker(monkeypatch)
    path=tmp_path/'private'/'broker.sock'
    listener=bind_socket(path)
    monkeypatch.setenv('OPENSCREEN_BROKER_SOCKET',str(path))
    real_request=broker_client.request
    server=uvicorn.Server(uvicorn.Config(create_app(manager,start_worker=False),log_level='error'))
    thread=threading.Thread(target=lambda:server.run(sockets=[listener]))
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.01)
        assert server.started
        exercise_synthetic_broker(monkeypatch,real_request)
        port.write.assert_called_once_with(bytes((255,0,0))*128*64)
    finally:
        server.should_exit=True
        thread.join(timeout=10)
        listener.close()
    assert not thread.is_alive()
