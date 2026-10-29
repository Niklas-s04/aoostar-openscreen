"""Supplemental rendering against upstream library sources, not a substitute for ci.py.

Uses the actual checked-out library without modifying it or generating library
metadata. Execute official ci.py and generate_metadata.py separately on Linux.
"""
import argparse
import importlib
import json
from pathlib import Path
import sys
import types
import yaml
import copy

from jinja2 import Environment, StrictUndefined
from check_catalog_compose import validate


def main(upstream):
    root = Path(__file__).resolve().parents[1]
    app = root / 'catalog/ix-dev/community/aoostar-openscreen'
    meta = yaml.safe_load((app / 'app.yaml').read_text())
    package = types.ModuleType('upstream_library')
    package.__path__ = [str(upstream / 'library' / meta['lib_version'])]
    sys.modules[package.__name__] = package
    render = importlib.import_module('upstream_library.render')
    template = Environment(undefined=StrictUndefined, extensions=['jinja2.ext.do']).from_string(
        (app / 'templates/docker-compose.yaml').read_text())
    result = {}
    for test in sorted((app / 'templates/test_values').glob('*.yaml')):
        values = json.loads((app / 'ix_values.yaml').read_text()) | json.loads(test.read_text())
        data = json.loads(template.render(values=values, ix_lib={'base': {'render': render}}))
        source = data['services']['openscreen']['volumes'][0]['source']
        validate(data, source)
        result[test.name] = data
        invalid = []
        bad_network = copy.deepcopy(values)
        bad_network['network']['host_network'] = True
        invalid.append(bad_network)
        for path in ('/dev', '/sys', '/etc/truenas', '/var/run/docker.sock', '/mnt/.ix-apps', '/mnt/data/../../etc'):
            bad = copy.deepcopy(values)
            bad['storage']['data'] = {'type': 'host_path', 'host_path_config': {'path': path}}
            invalid.append(bad)
        for bad in invalid:
            try:
                template.render(values=bad, ix_lib={'base': {'render': render}})
            except importlib.import_module('upstream_library.error').RenderError:
                pass
            else:
                raise AssertionError('Forbidden configuration rendered successfully')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('upstream', type=Path)
    main(parser.parse_args().upstream)
