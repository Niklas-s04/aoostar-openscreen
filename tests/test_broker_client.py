import pytest
from urllib.parse import urlsplit, parse_qs
from PIL import Image
from openscreen import broker_client
from openscreen.models import Config, Output
from openscreen.discovery import inspect_output, PlayerRegistry


def device(generation='b'*32):
    return {'id':'a'*32,'generation':generation,'verified':True,'width':960,'height':376,'name':'Test'}


def test_verified_inventory_only_and_bounded_paths(monkeypatch):
    monkeypatch.setattr(broker_client,'request',lambda *args:{'version':1,'devices':[device(),{**device(),'verified':False},{**device(),'id':'../etc/passwd'}],'candidates':[]})
    assert len(broker_client.inventory()['devices'])==1
    assert broker_client.selected('auto')['device']=='broker:'+'a'*32
    with pytest.raises(ValueError):
        broker_client.selected('/dev/sda')


def test_only_complete_frames_and_reconnect_resends(monkeypatch):
    generation=['b'*32]
    sent=[]
    def request(method,path,content=None):
        if method=='GET':
            return {'version':1,'devices':[device(generation[0])],'candidates':[]}
        sent.append((path,content))
        return {'ok':True}
    monkeypatch.setattr(broker_client,'request',request)
    transport=broker_client.BrokerTransport('auto')
    assert transport.needs_refresh()
    with pytest.raises(ValueError):
        transport.send(Image.new('RGB',(1,1)))
    transport.send(Image.new('RGB',(960,376),'red'))
    target=urlsplit(sent[0][0])
    assert len(sent[0][1])==721920 and target.path=='/v1/devices/'+'a'*32+'/frame'
    assert parse_qs(target.query)=={'mode':['960x376-rgb565'],'generation':['b'*32]}
    assert sent[0][1][:2]==b'\x00\xf8'
    assert not transport.needs_refresh()
    generation[0]='c'*32
    assert transport.needs_refresh()


def test_broker_preflight_fails_closed_and_does_not_open_host_device(monkeypatch):
    monkeypatch.setattr(broker_client,'request',lambda *args:{'version':1,'devices':[],'candidates':[]})
    config=Config(output=Output(kind='broker'))
    assert not inspect_output(config,PlayerRegistry())['ok']
    monkeypatch.setattr(broker_client,'request',lambda *args:{'version':1,'devices':[device()],'candidates':[]})
    assert inspect_output(config,PlayerRegistry())['ok']


def test_wrong_broker_schema_rejected(monkeypatch):
    monkeypatch.setattr(broker_client,'request',lambda *args:{'version':1,'devices':None,'candidates':[]})
    with pytest.raises(ValueError):
        broker_client.inventory()
