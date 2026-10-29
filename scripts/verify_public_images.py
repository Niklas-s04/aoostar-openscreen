"""Verify full-release registries using anonymous pull tokens, never local credentials."""
import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request

ACCEPT = ', '.join([
    'application/vnd.oci.image.manifest.v1+json',
    'application/vnd.oci.image.index.v1+json',
    'application/vnd.docker.distribution.manifest.v2+json',
    'application/vnd.docker.distribution.manifest.list.v2+json',
])


def get(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError('Oversized registry response')
        return raw, response.headers


def validate_config(config, version):
    assert config['architecture'] == 'amd64' and config['os'] == 'linux'
    assert config['config']['User'] == '10001:10001'
    assert config['config']['Labels']['org.opencontainers.image.version'] == version
    assert config['config']['Healthcheck']['Test']


def inspect(registry, repository, token_url, service, version):
    query = urllib.parse.urlencode({'service': service, 'scope': f'repository:{repository}:pull'})
    token_data, _ = get(token_url + '?' + query)
    token = json.loads(token_data).get('token') or json.loads(token_data)['access_token']
    headers = {'Authorization': 'Bearer ' + token, 'Accept': ACCEPT}

    def manifest(reference):
        raw, response_headers = get(f'https://{registry}/v2/{repository}/manifests/{reference}', headers)
        digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
        assert response_headers.get('Docker-Content-Digest') == digest, 'Manifest integrity mismatch'
        if reference.startswith('sha256:'):
            assert reference == digest
        return json.loads(raw), digest

    data, digest = manifest(version)
    if 'manifests' in data:
        platform = [item for item in data['manifests'] if item.get('platform', {}).get('os') == 'linux'
                    and item['platform'].get('architecture') == 'amd64']
        assert len(platform) == 1, 'Expected one linux/amd64 image'
        data, _ = manifest(platform[0]['digest'])
    config_digest = data['config']['digest']
    raw, _ = get(f'https://{registry}/v2/{repository}/blobs/{config_digest}', headers)
    assert 'sha256:' + hashlib.sha256(raw).hexdigest() == config_digest
    validate_config(json.loads(raw), version)
    return {'repository': repository, 'manifest': digest, 'config': config_digest}


def main(version, attempts=12):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('An exact stable SemVer version is required')
    for attempt in range(attempts):
        try:
            results = [
                inspect('ghcr.io', 'niklas-s04/aoostar-openscreen', 'https://ghcr.io/token', 'ghcr.io', version),
                inspect('registry-1.docker.io', 'niklass2004/aoostar-openscreen',
                        'https://auth.docker.io/token', 'registry.docker.io', version),
            ]
            assert results[0]['config'] == results[1]['config'], 'Registries serve different image configurations'
            print(json.dumps(results, indent=2))
            print('Anonymous public pulls and identical full-release image: PASS')
            return
        except (OSError, ValueError, KeyError, AssertionError):
            if attempt + 1 == attempts:
                raise
            print(f'Registry verification pending ({attempt + 1}/{attempts})')
            time.sleep(5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version')
    parser.add_argument('--attempts', type=int, default=12)
    args = parser.parse_args()
    if args.attempts < 1:
        parser.error('--attempts must be positive')
    main(args.version, args.attempts)
