"""Narrow Unix-socket client: inventory and complete RGB565 frames only."""
import json
import os
import re
import httpx
from .protocol import encode_rgb565, SIZE


IDENTIFIER=re.compile(r'^[a-f0-9]{32}$')


def socket_path():
    path=os.getenv('OPENSCREEN_BROKER_SOCKET','')
    if not path or not os.path.isabs(path):
        raise ValueError('OPENSCREEN_BROKER_SOCKET muss einen absoluten Socket-Pfad enthalten')
    return path


def request(method,path,content=None):
    transport=httpx.HTTPTransport(uds=socket_path(),retries=0)
    with httpx.Client(transport=transport,base_url='http://broker',trust_env=False,
                      follow_redirects=False,timeout=httpx.Timeout(35 if method=='POST' else 3,connect=2)) as client:
        with client.stream(method,path,content=content,headers={'Content-Type':'application/octet-stream'}) as response:
            response.raise_for_status()
            data=bytearray()
            for chunk in response.iter_bytes():
                if len(data)+len(chunk)>65536:
                    raise ValueError('Broker-Antwort zu groß')
                data.extend(chunk)
    return json.loads(data)


def inventory():
    data=request('GET','/v1/devices')
    if not isinstance(data,dict) or data.get('version')!=1:
        raise ValueError('Nicht unterstützte Broker-Version')
    if not isinstance(data.get('devices'),list) or not isinstance(data.get('candidates'),list):
        raise ValueError('Ungültiges Broker-Inventar')
    devices=[]
    for item in data.get('devices',[])[:16]:
        if (isinstance(item,dict) and IDENTIFIER.fullmatch(str(item.get('id','')))
            and IDENTIFIER.fullmatch(str(item.get('generation',''))) and item.get('verified') is True
            and (item.get('width'),item.get('height'))==SIZE):
            devices.append({'id':item['id'],'device':'broker:'+item['id'],'name':str(item.get('name','Display'))[:100],
                            'width':SIZE[0],'height':SIZE[1],'kind':'broker','verified':True,'accessible':True,
                            'state':'ready','generation':item['generation'],'size_source':'adapter-profile'})
    candidates=[]
    for item in data.get('candidates',[])[:128]:
        if isinstance(item,dict):
            candidates.append({'name':str(item.get('name','USB-Gerät'))[:100],
                               'state':str(item.get('state','unknown'))[:32],
                               'reason':str(item.get('reason',''))[:200]})
    return {'devices':devices,'candidates':candidates,'version':1}


def selected(device):
    if device!='auto' and not re.fullmatch(r'broker:[a-f0-9]{32}',device):
        raise ValueError('Broker-Gerät aus der Liste auswählen')
    devices=inventory()['devices']
    matches=devices if device=='auto' else [d for d in devices if d['device']==device]
    if len(matches)!=1:
        raise ValueError('Kein eindeutiges bestätigtes Broker-Display verfügbar')
    return matches[0]


class BrokerTransport:
    def __init__(self,device):
        self.device=device
        self.generation=None
        self.identity=None

    def needs_refresh(self):
        item=selected(self.device)
        return (item['id'],item['generation'])!=(self.identity,self.generation)

    def send(self,image):
        if image.size!=SIZE:
            raise ValueError('Broker frame requires 960 × 376')
        item=selected(self.device)
        response=request('POST','/v1/devices/'+item['id']+'/frame',encode_rgb565(image))
        if not isinstance(response,dict) or response.get('ok') is not True:
            raise OSError('Broker did not acknowledge frame delivery')
        self.identity,self.generation=item['id'],item['generation']

    def close(self):
        self.identity=self.generation=None
