import json
import httpx
import pytest
from openscreen.collectors import collect_http, collect_truenas, CollectorError
from openscreen.models import Source


def test_docker_negotiates_version_and_normalizes_health():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.url.path == '/version':
            data = {'ApiVersion':'1.47', 'MinAPIVersion':'1.24'}
        elif request.url.path.endswith('/containers/json'):
            data = [{'Id':'abc', 'Names':['/jellyfin'], 'State':'running', 'Status':'Up 1 hour (healthy)'}]
        elif request.url.path.endswith('/containers/abc/json'):
            data = {'RestartCount':4,'State':{'Health':{'Status':'healthy'}}}
        elif request.url.path.endswith('/containers/abc/stats'):
            data = {'cpu_stats':{'cpu_usage':{'total_usage':200},'system_cpu_usage':1000,'online_cpus':4},'precpu_stats':{'cpu_usage':{'total_usage':100},'system_cpu_usage':500},'memory_stats':{'usage':60,'limit':100,'stats':{'inactive_file':10}}}
        else:
            data = {'Name':'host'}
        return httpx.Response(200, json=data)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = collect_http(Source(id='d', name='Docker', kind='docker', url='http://proxy'), client)
    assert '/v1.47/containers/json' in paths
    assert result.workloads[0]['name'] == 'jellyfin'
    assert result.workloads[0]['health'] == 'healthy'
    assert result.workloads[0]['restarts'] == 4
    assert result.workloads[0]['cpu'] == 80
    assert result.workloads[0]['memory'] == 50


def test_proxmox_resources_and_numeric_ratios():
    def handler(request):
        assert request.url.path == '/api2/json/cluster/resources'
        return httpx.Response(200, json={'data':[{'id':'qemu/101','name':'VM','type':'qemu','status':'running','cpu':0.25,'mem':50,'maxmem':100}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = collect_http(Source(id='p',name='PVE',kind='proxmox',url='https://pve:8006'), client)
    assert result.workloads[0]['cpu'] == 25
    assert result.workloads[0]['memory'] == 50


def test_json_fields_are_paths_not_code_and_null_stays_unknown():
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200,json={'metrics':{'temp':42}}))) as client:
        result = collect_http(Source(id='j',name='JSON',kind='json',url='http://data',fields={'temperature':'metrics.temp','cpu':'missing'}), client)
    assert result.metrics == {'temperature':42, 'cpu':None}


def test_redirect_and_auth_errors_are_not_followed_or_leaked():
    for status in (302, 401, 500):
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status,headers={'Location':'https://elsewhere'},text='sensitive token'))) as client:
            with pytest.raises(CollectorError, match=f'HTTP {status}') as err:
                collect_http(Source(id='j',name='JSON',kind='json',url='http://data'), client)
        assert 'sensitive' not in str(err.value)


def test_truenas_ignores_events_and_rejects_wrong_version():
    class Peer:
        def __init__(self, version):
            self.request = None
            self.version = version
        def send(self, text):
            self.request = json.loads(text)
        def recv(self):
            method = self.request['method']
            data = {'auth.login_with_api_key':True,'system.version':self.version,'system.info':{'hostname':'nas'},'pool.query':[{'id':1,'name':'tank','status':'ONLINE','allocated':25,'size':100}],'app.query':[{'id':'jellyfin','name':'jellyfin','state':'RUNNING'}]}
            return json.dumps({'jsonrpc':'2.0','id':self.request['id'],'result':data[method]})
    source = Source(id='t',name='NAS',kind='truenas',url='https://nas')
    result = collect_truenas(source, Peer('TrueNAS-25.10.1'), 'secret')
    assert result.pools[0]['percent'] == 25
    assert result.workloads[0]['state'] == 'running'
    with pytest.raises(CollectorError, match='25.10'):
        collect_truenas(source, Peer('TrueNAS-24.10'), 'secret')
