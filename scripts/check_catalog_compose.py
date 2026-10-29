"""Fail closed on privileges outside the browser distribution's resource contract.

Input: docker compose -f rendered/docker-compose.yaml config --format json
Only the caller's explicitly allocated data source may be mounted.
"""
import argparse
import json
from pathlib import Path, PurePosixPath


def validate(compose, data_source):
    services = compose.get('services', {})
    assert set(services) == {'openscreen'}, 'Unexpected helper/service'
    c = services['openscreen']
    assert c.get('user') == '10001:10001', 'Unexpected UID/GID'
    assert c.get('read_only') is True, 'Writable root filesystem'
    assert not c.get('privileged'), 'Privileged container'
    assert set(c.get('cap_drop', [])) == {'ALL'} and not c.get('cap_add'), 'Capabilities'
    assert any(v in ('no-new-privileges:true', 'no-new-privileges=true', 'no-new-privileges') for v in c.get('security_opt', [])), 'Privilege escalation'
    for key in ('pid', 'ipc', 'network_mode', 'devices', 'device_cgroup_rules', 'volumes_from', 'use_api_socket'):
        assert not c.get(key), f'Forbidden resource: {key}'
    mounts = c.get('volumes', [])
    assert len(mounts) == 1, 'Only assigned data storage is allowed'
    assert mounts[0]['target'] == '/data' and mounts[0]['source'] == data_source, 'Unassigned storage'
    assert mounts[0]['type'] in ('volume', 'bind'), 'Unsupported storage'
    assert data_source not in ('/', '/dev', '/sys', '/proc', '/etc', '/var', '/mnt', '/run', '/var/run/docker.sock'), 'Host system path'
    assert '..' not in PurePosixPath(data_source).parts, 'Noncanonical storage path'
    for protected in ('/dev', '/sys', '/proc', '/etc', '/var', '/run', '/usr', '/boot', '/root', '/home', '/conf', '/audit'):
        assert not (data_source == protected or data_source.startswith(protected + '/')), 'Host system subtree'
    assert not data_source.endswith('.sock'), 'Socket mount'
    # The current TrueNAS library adds its standard apps group to every container.
    assert set(map(str, c.get('group_add', []))) <= {'568'}, 'Unexpected extra groups'
    env = c.get('environment', {})
    assert set(env) <= {'OPENSCREEN_DATA', 'OPENSCREEN_ALLOWED_HOSTS', 'OPENSCREEN_ALLOWED_NETWORKS', 'TZ', 'NVIDIA_VISIBLE_DEVICES', 'PUID', 'PGID', 'UMASK', 'UMASK_SET'}, 'Unexpected environment override'
    assert not any('secrets' in key for key in c), 'Secret mount'
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('compose_json', type=Path)
    parser.add_argument('--data-source', required=True)
    args = parser.parse_args()
    validate(json.loads(args.compose_json.read_text()), args.data_source)
    print('Catalog Compose boundaries: PASS')
