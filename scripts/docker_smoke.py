"""Exercise the real Compose stack locally; --keep leaves it available on port 8080.

Uses a unique project and local-only networking, never an existing stack.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import ipaddress
import socket
import tempfile

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keep', action='store_true')
    parser.add_argument('--broker', action='store_true', help='Also exercise the isolated display broker')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    project = 'openscreen-check-' + uuid.uuid4().hex[:8]
    env = dict(os.environ, DOCKER_SOCKET_GID='0', OPENSCREEN_ALLOWED_SOURCE_URLS='http://docker-proxy:2375')
    compose = ['docker', 'compose', '-p', project, '-f', 'compose.yaml', '-f', 'compose.docker.yaml']
    if args.broker:
        env['OPENSCREEN_DEVICE_GID']=os.getenv('OPENSCREEN_DEVICE_GID','0')
        compose.extend(['-f','compose.broker.yaml'])

    def run(*command, capture=True):
        return subprocess.run(command, cwd=root, env=env, check=True, text=True,
                              stdout=subprocess.PIPE if capture else None).stdout

    # Resolve paths before writing a disposable configuration outside the checkout.
    resolved = json.loads(run(*compose, 'config', '--format', 'json'))
    networks = run('docker', 'network', 'ls', '-q').split()
    occupied = []
    if networks:
        for network in json.loads(run('docker', 'network', 'inspect', *networks)):
            occupied.extend(ipaddress.ip_network(item['Subnet']) for item in (network.get('IPAM',{}).get('Config') or []) if item.get('Subnet'))
    subnet = next((ipaddress.ip_network(f'172.29.{i}.0/24') for i in range(256)
                   if not any(ipaddress.ip_network(f'172.29.{i}.0/24').overlaps(n) for n in occupied if n.version==4)), None)
    if subnet is None:
        raise RuntimeError('No isolated test subnet available')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0))
        port = listener.getsockname()[1]
    resolved['networks']['default']['ipam']={'config':[{'subnet':str(subnet)}]}
    resolved['services']['openscreen']['environment']['OPENSCREEN_ALLOWED_NETWORKS']=f'127.0.0.0/8,::1/128,{subnet.network_address+1}/32'
    resolved['services']['openscreen']['ports']=[{'target':8080,'published':str(port),'host_ip':'127.0.0.1','protocol':'tcp'}]
    temporary = tempfile.TemporaryDirectory(prefix='openscreen-docker-')
    config_path = Path(temporary.name)/'compose.json'
    config_path.write_text(json.dumps(resolved),encoding='utf-8')
    compose = ['docker','compose','-p',project,'-f',str(config_path)]

    success = False
    try:
        run(*compose, 'up', '-d', '--build', '--wait', '--wait-timeout', '120', capture=False)
        base = f'http://127.0.0.1:{port}'
        with httpx.Client(base_url=base, timeout=30) as client:
            assert httpx.get(base + '/healthz').status_code == 200
            assert httpx.get(base + '/api/config').status_code == 200
            assert client.get('/api/config', headers={'Host':'attacker.example'}).status_code == 403
            assert client.get('/api/config', headers={'Sec-Fetch-Site':'cross-site'}).status_code == 403
            assert client.get('/').status_code == 200
            assert client.get('/static/app.js').status_code == 200
            assert client.get('/api/editor/catalog').status_code == 200
            config = client.get('/api/config').raise_for_status().json()
            assert client.put('/api/config', json=config).status_code == 403
            config['sources'].append(dict(id='docker-local', name='Docker lokal', kind='docker',
                                         url='http://docker-proxy:2375', interval=5))
            config['title'] = 'OpenScreen Docker lokal'
            headers = {'X-OpenScreen': '1'}
            client.put('/api/config', json=config, headers=headers).raise_for_status()
            result = client.post('/api/sources/docker-local/test', headers=headers).raise_for_status().json()
            assert result['ok'], result
            preview = client.get('/api/preview.png').raise_for_status().content
            assert preview[:8] == b'\x89PNG\r\n\x1a\n'
            assert int.from_bytes(preview[16:20], 'big') == 960
            assert int.from_bytes(preview[20:24], 'big') == 376
            draft=client.post('/api/editor/preview',json=config['pages'][0],headers=headers).raise_for_status().content
            assert int.from_bytes(draft[16:20],'big')==960
            assert 'serial' in client.get('/api/displays').raise_for_status().json()
            if args.broker:
                inventory=client.get('/api/displays').raise_for_status().json()
                assert inventory['broker']['available'],inventory['broker']['error']
                boundary='''import os,stat,socket
from pathlib import Path
assert os.getuid()==10001
assert Path('/run/openscreen-broker/broker.sock').stat().st_mode & 0o777 == 0o600
assert Path('/run/openscreen-broker').stat().st_mode & 0o777 == 0o700
assert 'CapEff:\\t0000000000000000' in Path('/proc/self/status').read_text()
with open('/host-dev/null','wb',buffering=0) as f: f.write(b'char-device-readonly-mount-check')
assert len(socket.if_nameindex())==1
print('Broker: UID, socket permissions, zero capabilities, isolated network, readonly char-device mount passed')
'''
                print(run(*compose,'exec','-T','display-broker','python','-c',boundary).strip())
                web_boundary='''from pathlib import Path
assert not Path('/host-dev').exists()
assert not Path('/var/run/docker.sock').exists()
try:
    Path('/run/openscreen-broker/write-test').write_text('must fail')
except OSError:
    pass
else:
    raise AssertionError('Web broker mount is writable')
'''
                run(*compose,'exec','-T','openscreen','python','-c',web_boundary)
                run(*compose,'restart','display-broker',capture=False)
                for _ in range(30):
                    if client.get('/api/displays').raise_for_status().json()['broker']['available']:
                        break
                    time.sleep(1)
                else:
                    raise AssertionError('Broker did not recover its socket after restart')
            client.post('/api/displays/report',json={'id':'a'*32,'width':1280,'height':720},headers=headers).raise_for_status()
            config['output']={'kind':'browser','width':960,'height':376,'player_id':'a'*32,'auto_size':True}
            client.put('/api/config',json=config,headers=headers).raise_for_status()
            network_frame=client.get('/api/output.png').raise_for_status().content
            assert int.from_bytes(network_frame[16:20],'big')==1280
            assert int.from_bytes(network_frame[20:24],'big')==720
            assert client.get('/display').status_code==200
            run(*compose, 'restart', 'openscreen', capture=False)
            for _ in range(60):
                try:
                    restored = client.get('/api/config').raise_for_status().json()
                    break
                except httpx.HTTPError:
                    time.sleep(1)
            else:
                raise AssertionError('App did not restart')
            assert restored['title'] == config['title']
            assert restored['sources'][-1]['id'] == 'docker-local'
        # Run through the same internal network as the application, without exposing the socket.
        probe = '''import httpx,json,os
from openscreen.collectors import collect
from openscreen.models import Source
with httpx.Client(base_url="http://docker-proxy:2375", timeout=30) as c:
    version=c.get("/version").raise_for_status().json()["ApiVersion"]
    prefix="/v"+version
    containers=c.get(prefix+"/containers/json?all=1").raise_for_status().json()
    assert containers
    ident=containers[0]["Id"]
    assert c.get(prefix+"/containers/"+ident+"/json").status_code==200
    assert c.get(prefix+"/containers/"+ident+"/stats?stream=false").status_code==200
    for method,path in [("POST",prefix+"/containers/"+ident+"/stop"),("DELETE",prefix+"/containers/"+ident),("POST","/version"),("GET",prefix+"/info"),("GET",prefix+"/containers/"+ident+"/logs")]:
        assert c.request(method,path).status_code==403, (method,path)
snapshot=collect(Source(id="check",name="check",kind="docker",url="http://docker-proxy:2375"),"/run/secrets")
assert snapshot.ok and snapshot.workloads, snapshot.error
assert os.getuid()==10001
print(json.dumps({"uid":os.getuid(),"docker_api":version,"workloads":len(snapshot.workloads),"proxy_filters":"passed"}))
'''
        print(run(*compose, 'exec', '-T', 'openscreen', 'python', '-c', probe).strip())
        print('PASS: build/start, local access, Host/CSRF protection, persistence, editor preview, 960x376 and 1280x720 outputs, browser player, live Docker collector and proxy filters.')
        success = True
    except Exception:
        print(run(*compose, 'logs', '--tail', '30'))
        raise
    finally:
        if args.keep and success:
            print(f'URL: http://127.0.0.1:{port} | No login, local access only')
            print('Compose project: ' + project)
        else:
            run(*compose, 'down', '--volumes', capture=False)
        temporary.cleanup()


if __name__ == '__main__':
    main()
