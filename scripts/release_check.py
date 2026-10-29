"""Fail before publication on inconsistent full-release versions or private files."""
import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(tag):
    from openscreen import __version__
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    version = project['project']['version']
    assert re.fullmatch(r'v\d+\.\d+\.\d+', tag), 'Use an exact stable SemVer tag'
    assert tag == 'v' + version and __version__ == version, 'Release version mismatch'
    lock = tomllib.loads((ROOT / 'uv.lock').read_text(encoding='utf-8'))
    assert next(p['version'] for p in lock['package'] if p['name'] == project['project']['name']) == version
    assert f'image.version="{version}"' in (ROOT / 'Dockerfile').read_text(encoding='utf-8')
    assert f'## {version}' in (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
    assert (ROOT / 'LICENSE').read_text(encoding='utf-8').startswith('MIT License')
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    forbidden_parts = {'.venv', '__pycache__', '.pytest_cache', '.local', '.codex', 'secrets', 'artifacts'}
    for name in filter(None, tracked):
        path = Path(name)
        assert not forbidden_parts.intersection(path.parts), f'Private/generated path tracked: {name}'
        assert not (path.name.startswith('.env') and path.name != '.env.example'), name
        assert path.suffix.lower() not in {'.key', '.pem', '.pfx', '.p12', '.pyc', '.sarif', '.log'}, name
    print(f'Full release {tag}: versions, license, changelog and tracked-file hygiene PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    check(parser.parse_args().tag)
