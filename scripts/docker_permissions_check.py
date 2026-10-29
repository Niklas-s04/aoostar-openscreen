"""Exercise the production image with a private (0700/0600) source context."""
import argparse
from pathlib import Path
import subprocess
import tarfile
import tempfile
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--expect-denied', action='store_true', help='Reproduce the pre-fix failure')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    tag = 'openscreen-permissions-check:' + uuid.uuid4().hex[:12]
    paths = [root / name for name in ('Dockerfile', 'pyproject.toml', 'uv.lock', 'LICENSE')]
    paths += [root / 'openscreen'] + sorted((root / 'openscreen').rglob('*'))
    try:
        with tempfile.TemporaryFile() as context:
            with tarfile.open(fileobj=context, mode='w', format=tarfile.USTAR_FORMAT) as archive:
                for path in paths:
                    if '__pycache__' in path.parts or path.suffix == '.pyc':
                        continue
                    info = archive.gettarinfo(str(path), str(path.relative_to(root)).replace('\\', '/'))
                    info.uid = info.gid = 0
                    info.mtime = int(info.mtime)
                    info.uname = info.gname = 'root'
                    info.mode = 0o700 if info.isdir() else 0o600
                    if info.isfile():
                        with path.open('rb') as content:
                            archive.addfile(info, content)
                    else:
                        archive.addfile(info)
            context.seek(0)
            built = subprocess.run(['docker', 'build', '-t', tag, '-'], stdin=context,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if built.returncode:
                log = built.stdout.decode(errors='replace')
                raise RuntimeError(log[:6000] + '\n' + log[-1000:])
        probe = '''import os
from pathlib import Path
import openscreen.app, openscreen.broker
assert os.getuid() == 10001
for p in Path('/app/openscreen').rglob('*'):
    assert p.stat().st_uid == 0
    assert not os.access(p, os.W_OK), str(p)
    if p.is_file():
        p.read_bytes()
print('PASS: UID 10001 imports web/broker and reads all code/assets from private build context')
'''
        result = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--read-only',
                                 '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                                 tag, 'python', '-c', probe], capture_output=True, text=True)
        if args.expect_denied:
            assert result.returncode != 0 and 'PermissionError' in result.stderr, result.stderr
            print('REPRODUCED: private build context prevents UID 10001 importing application')
        else:
            assert result.returncode == 0, result.stderr
            print(result.stdout.strip())
    finally:
        subprocess.run(['docker', 'image', 'rm', tag], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
