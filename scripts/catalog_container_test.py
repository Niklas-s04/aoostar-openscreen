"""Real local Docker tests. Creates/removes only its own disposable Docker volume.

No NAS access. No hardware simulation is claimed as hardware validation.
"""
import argparse
import json
import subprocess
import uuid


def docker(*args, check=True):
    result = subprocess.run(['docker', *args], text=True, encoding='utf-8', capture_output=True)
    if check and result.returncode:
        raise RuntimeError(f'Docker check failed ({result.returncode}):\n{result.stdout}\n{result.stderr}')
    return result


def main(image):
    metadata = json.loads(docker('image', 'inspect', image).stdout)[0]
    assert metadata['Architecture'] == 'amd64' and metadata['Os'] == 'linux'
    assert metadata['Config']['User'] == '10001:10001'
    assert metadata['Config']['Healthcheck']['Test'], 'Missing image healthcheck'
    name = 'openscreen-catalog-test-' + uuid.uuid4().hex[:12]
    docker('volume', 'create', name)
    base = ['run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--pids-limit', '128',
            '--memory', '512m', '--cpus', '2', '--tmpfs', '/tmp:size=67108864,noexec,nosuid,nodev',
            '-v', name + ':/data', '--entrypoint', 'python', image, '-c']
    try:
        code = '''
import importlib.util, os, pathlib
import zlib
from openscreen_catalog.runtime import Runtime
assert os.getuid() == os.getgid() == 10001
assert __import__('PIL').__version__ == '13.0.0'
assert pathlib.Path('/etc/alpine-release').read_text().strip() == '3.24.3'
packages = pathlib.Path('/lib/apk/db/installed').read_text()
records = [dict(line.split(':', 1) for line in record.splitlines() if ':' in line)
           for record in packages.split('\\n\\n') if record.strip()]
versions = {record['P']: record['V'] for record in records}
assert versions['zlib'] == '1.3.2-r1', versions.get('zlib')
assert zlib.ZLIB_RUNTIME_VERSION == '1.3.2'
assert 'perl' not in versions and 'perl-base' not in versions
assert not pathlib.Path('/usr/bin/perl').exists()
assert {p.name for p in pathlib.Path('/app/openscreen').glob('*.py')} == {
    '__init__.py', 'canvas_models.py', 'network_access.py', 'render.py', 'templates.py', 'assets.py'}
for module in ('openscreen.truenas','openscreen.collectors','openscreen.models',
               'openscreen.access','openscreen.protocol','openscreen.broker',
               'openscreen.discovery','serial','websocket','psutil','httpx','pip','setuptools'):
    assert importlib.util.find_spec(module) is None, module
for target in ('/app/probe','/etc/probe','/probe'):
    try:
        pathlib.Path(target).write_text('must fail')
    except OSError:
        pass
    else:
        raise AssertionError(target)
r = Runtime('/data')
r.config.title = 'survives replacement'
r.save(r.config)
assert r.image().size == (960, 376)
print('UID, excluded modules, read-only root, save, rendering: PASS')
'''
        print(docker(*base, code).stdout.strip())
        print(docker(*base, '''
import ctypes
import resource
# Exercise musl itself, not Python's different regular-expression engine.
# Bound hostile expansion locally so a regression cannot exhaust the runner.
resource.setrlimit(resource.RLIMIT_AS, (128 * 1024 * 1024, 128 * 1024 * 1024))
resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
libc = ctypes.CDLL(None)
libc.regcomp.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
libc.regcomp.restype = ctypes.c_int
libc.regexec.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_int]
libc.regexec.restype = ctypes.c_int
libc.regfree.argtypes = [ctypes.c_void_p]
libc.regfree.restype = None
# Oversized aligned opaque storage for musl's regex_t; no layout assumptions.
regex = (ctypes.c_uint64 * 512)()
assert libc.regcomp(regex, b'^OpenScreen[0-9]+$', 1) == 0
try:
    assert libc.regexec(regex, b'OpenScreen13', 0, None, 0) == 0
    assert libc.regexec(regex, b'wrong', 0, None, 0) == 1
finally:
    libc.regfree(regex)
for pattern in (b'a' * 1_024_000, b'(((a{255}){255}){255}){255}', b'((a|b*){255,}){255,}'):
    result = libc.regcomp(regex, pattern, 1)
    if result == 0:
        libc.regfree(regex)
    assert result == 12, ('Expected musl REG_ESPACE', result)
print('musl regex: normal match/non-match and bounded hostile-input rejection: PASS')
''').stdout.strip())
        print(docker(*base, '''
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
from PIL import Image, features
from openscreen.render import font
from openscreen.assets import AssetStore
# Assert real font files, not Pillow's silent default-font fallback.
for family, stem in {'sans':'DejaVuSans', 'sans-condensed':'DejaVuSansCondensed',
                     'serif':'DejaVuSerif', 'mono':'DejaVuSansMono',
                     'liberation-sans':'LiberationSans', 'liberation-serif':'LiberationSerif',
                     'liberation-mono':'LiberationMono'}.items():
    for bold in (False, True):
        for italic in (False, True):
            f = font(32, family, bold, italic)
            slant = 'Italic' if 'Serif' in stem or stem.startswith('Liberation') else 'Oblique'
            suffix = ('Bold' if bold else '') + (slant if italic else '')
            expected = stem + ('-' + suffix if suffix else '-Regular' if stem.startswith('Liberation') else '') + '.ttf'
            assert isinstance(f.path, str), (family, bold, italic, 'default-font fallback')
            assert Path(f.path).is_file() and Path(f.path).name == expected, (family, bold, italic)
            assert f.getbbox('ÄÖÜ ß — 123')[2] > 0
store = AssetStore('/data/codec-test')
for codec in ('PNG', 'JPEG', 'WEBP', 'GIF'):
    encoded = BytesIO()
    Image.new('RGB', (40, 20), 'red').save(encoded, format=codec)
    asset = store.upload(encoded.getvalue(), codec + '.image')
    assert asset['frames'] == 1 and store.frame(asset['id'], 0).size == (40, 20)
for codec in ('GIF', 'PNG'):
    encoded = BytesIO()
    Image.new('RGB', (40, 20), 'red').save(encoded, format=codec, save_all=True,
        append_images=[Image.new('RGB', (40, 20), 'blue')], duration=[100, 200], loop=0)
    asset = store.upload(encoded.getvalue(), codec + '.animation')
    assert asset['frames'] == 2 and asset['duration_ms'] == 300
    assert store.frame(asset['id'], 0).getpixel((0, 0))[:3] == (255, 0, 0)
    assert store.frame(asset['id'], .15).getpixel((0, 0))[:3] == (0, 0, 255)
assert datetime(2026, 1, 1, tzinfo=ZoneInfo('Europe/Berlin')).utcoffset() == timedelta(hours=1)
assert datetime(2026, 7, 1, tzinfo=ZoneInfo('Europe/Berlin')).utcoffset() == timedelta(hours=2)
print('28 real font styles, image codecs, GIF/APNG timing, timezone: PASS')
assert features.version('zlib') == '1.3.2'
loaded = {line.split()[-1] for line in Path('/proc/self/maps').read_text().splitlines() if '/libz' in line}
assert '/usr/lib/libz.so.1.3.2' in loaded, loaded
assert not any('pillow.libs/libz-' in path or 'pillow.libs/libz.so' in path for path in loaded), loaded
print('CPython/Pillow use the patched system zlib: PASS')
''').stdout.strip())
        print(docker(*base, "from openscreen_catalog.runtime import Runtime; assert Runtime('/data').config.title == 'survives replacement'; print('Container replacement persistence: PASS')").stdout.strip())
        denied = docker('run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                        '--entrypoint', 'python', image, '-c',
                        "from openscreen_catalog.runtime import Runtime; Runtime('/data')", check=False)
        assert denied.returncode != 0 and ('Read-only file system' in denied.stderr or 'Permission denied' in denied.stderr)
        print('Missing writable storage fails startup: PASS')
        health = docker(*base, '''
import subprocess, sys, time, urllib.request
p = subprocess.Popen([sys.executable,'-m','uvicorn','openscreen_catalog.app:create_app','--factory','--host','127.0.0.1','--port','8080','--no-proxy-headers'])
try:
    for _ in range(100):
        try:
            assert urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=1).status == 200
            print('Real HTTP startup and healthcheck: PASS')
            break
        except OSError:
            time.sleep(.1)
    else:
        raise AssertionError('health timeout')
    from io import BytesIO
    from PIL import Image
    from openscreen_catalog.models import Config
    preview = urllib.request.Request('http://127.0.0.1:8080/api/editor/preview',
        data=Config().pages[0].model_dump_json().encode(),
        headers={'Content-Type': 'application/json', 'X-OpenScreen': '1'}, method='POST')
    for request in ('http://127.0.0.1:8080/api/output.png', preview):
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
            with Image.open(BytesIO(response.read())) as frame:
                assert frame.size == (960, 376)
                frame.load()
    print('Real HTTP PNG output and preview: PASS')
finally:
    p.terminate(); p.wait(timeout=10)
''')
        print(health.stdout.strip())
    finally:
        docker('volume', 'rm', name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', default='ghcr.io/niklas-s04/aoostar-openscreen-catalog:1.0.2')
    main(parser.parse_args().image)
