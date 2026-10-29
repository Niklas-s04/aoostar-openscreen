import copy
import json
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml
from scripts.check_catalog_compose import validate

ROOT = Path(__file__).resolve().parents[1]


def safe_compose():
    return {'services': {'openscreen': {
        'user': '10001:10001', 'read_only': True, 'cap_drop': ['ALL'],
        'security_opt': ['no-new-privileges:true'],
        'volumes': [{'type': 'volume', 'source': 'assigned', 'target': '/data'}],
    }}}


@pytest.mark.parametrize('mutation', [
    {'privileged': True}, {'pid': 'host'}, {'network_mode': 'host'},
    {'cap_add': ['SYS_ADMIN']}, {'read_only': False}, {'user': '0:0'},
    {'devices': ['/dev/ttyACM0']}, {'device_cgroup_rules': ['c 166:* rwm']},
    {'volumes': [{'type': 'bind', 'source': '/var/run/docker.sock', 'target': '/data'}]},
    {'volumes': [{'type': 'bind', 'source': '/dev', 'target': '/dev'}]},
    {'environment': {'OPENSCREEN_BROKER_SOCKET': '/run/broker.sock'}},
])
def test_compose_mutations_fail(mutation):
    config = safe_compose()
    config['services']['openscreen'].update(mutation)
    with pytest.raises(AssertionError):
        validate(config, 'assigned')


def test_valid_compose_and_version():
    assert validate(safe_compose(), 'assigned')
    from openscreen_catalog import __version__
    assert tomllib.loads((ROOT/'catalog/pyproject.toml').read_text())['project']['version'] == __version__
    app = yaml.safe_load((ROOT/'catalog/ix-dev/community/aoostar-openscreen/app.yaml').read_text())
    assert app['app_version'] == __version__
    assert f'image.version="{__version__}"' in (ROOT/'Dockerfile.catalog').read_text()
    values = yaml.safe_load((ROOT/'catalog/ix-dev/community/aoostar-openscreen/ix_values.yaml').read_text())
    assert values['images']['image']['tag'] == __version__
    assert yaml.safe_load((ROOT/'compose.catalog.yaml').read_text())['services']['openscreen']['image'].endswith(':' + __version__)


@pytest.mark.parametrize('source', ['/etc/truenas', '/var/run/docker.sock', '/proc/1/root', '/mnt', '/mnt/data/../../etc'])
def test_system_paths_rejected_even_if_selected(source):
    config = safe_compose()
    config['services']['openscreen']['volumes'][0].update(type='bind', source=source)
    with pytest.raises(AssertionError):
        validate(config, source)


def test_safe_modules_have_no_forbidden_imports():
    import ast
    files = list((ROOT/'openscreen_catalog').glob('*.py')) + [ROOT/'openscreen'/p for p in
            ['__init__.py', 'canvas_models.py', 'network_access.py', 'render.py', 'templates.py', 'assets.py']]
    forbidden = {'truenas', 'collectors', 'runtime', 'outputs', 'protocol', 'broker', 'broker_client',
                 'discovery', 'serial', 'psutil', 'websocket', 'httpx', 'subprocess'}
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Import):
                names = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or '']
            else:
                continue
            for name in names:
                # Own browser-only runtime is explicitly allowed.
                if path.parent.name == 'openscreen_catalog' and name == 'runtime':
                    continue
                assert not forbidden.intersection(name.split('.')), (path, name)
