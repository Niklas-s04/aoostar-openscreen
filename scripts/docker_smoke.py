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

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keep', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    project = 'openscreen-check-' + uuid.uuid4().hex[:8]
    env = dict(os.environ, DOCKER_SOCKET_GID='0', OPENSCREEN_ALLOWED_SOURCE_URLS='http://docker-proxy:2375')
    compose = ['docker', 'compose', '-p', project, '-f', 'compose.yaml', '-f', 'compose.docker.yaml']

    def run(*command, capture=True):
        return subprocess.run(command, cwd=root, env=env, check=True, text=True,
                              stdout=subprocess.PIPE if capture else None).stdout

    success = False
    try:
        run(*compose, 'up', '-d', '--build', '--wait', '--wait-timeout', '120', capture=False)
        base = 'http://127.0.0.1:8080'
        with httpx.Client(base_url=base, timeout=30) as client:
            assert httpx.get(base + '/healthz').status_code == 200
            assert httpx.get(base + '/api/config').status_code == 200
            assert client.get('/api/config', headers={'Host':'attacker.example'}).status_code == 403
            assert client.get('/api/config', headers={'Sec-Fetch-Site':'cross-site'}).status_code == 403
            assert client.get('/').status_code == 200
            assert client.get('/static/app.js').status_code == 200
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
        print('PASS: build/start, passwordless local access, Host/CSRF protection, config persistence, PNG 960x376, live Docker collector and proxy allow/deny checks.')
        success = True
    except Exception:
        print(run(*compose, 'logs', '--tail', '30'))
        raise
    finally:
        if args.keep and success:
            print('URL: http://127.0.0.1:8080 | No login, local access only')
            print('Compose project: ' + project)
        else:
            run(*compose, 'down', '--volumes', capture=False)


if __name__ == '__main__':
    main()
