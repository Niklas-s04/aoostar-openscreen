"""Restricted Linux USB display owner, reachable only through a Unix socket."""
import argparse
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import threading
import time

from fastapi import FastAPI, HTTPException, Request

from .protocol import SIZE
from .adapters import ADAPTERS
from dataclasses import replace

FRAME_BYTES = SIZE[0] * SIZE[1] * 2
TTY_NAME = re.compile(r'tty(?:ACM|USB)[0-9]+\Z')
DEVICE_ID = re.compile(r'[0-9a-f]{32}\Z')
MAX_DEVICES = 16


@dataclass(frozen=True)
class Candidate:
    id: str
    tty: str
    sys_path: Path
    usb_path: Path
    rdev: int
    supported: bool
    sys_identity: tuple = ()
    adapter_id: str = 'aoostar'


@dataclass
class Connection:
    candidate: Candidate
    port: object
    lock: threading.Lock = field(default_factory=threading.Lock)
    generation: str = field(default_factory=lambda: secrets.token_hex(16))


class BusyError(Exception):
    pass


class BrokerManager:
    def __init__(self, device_root='/host-dev', sys_root='/host-sys', registry=ADAPTERS):
        self.registry = registry
        self.device_root = Path(device_root).resolve()
        self.sys_root = Path(sys_root).resolve()
        self.connections = {}
        self.candidates = {}
        self.failures = {}
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None

    def _read(self, path):
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(self.sys_root):
            raise OSError('Untrusted sysfs path')
        with resolved.open('r', encoding='ascii') as stream:
            value = stream.read(257)
        if len(value) > 256:
            raise OSError('Invalid sysfs value')
        return value.strip()

    def inspect(self, tty):
        if not TTY_NAME.fullmatch(tty):
            raise OSError('Invalid device name')
        path = (self.sys_root / 'class' / 'tty' / tty).resolve(strict=True)
        if not path.is_relative_to(self.sys_root):
            raise OSError('Untrusted sysfs path')
        major, minor = map(int, self._read(path / 'dev').split(':'))
        usb = path
        for _ in range(32):
            if (usb / 'idVendor').exists() and (usb / 'idProduct').exists():
                break
            if usb == self.sys_root:
                raise OSError('No USB parent')
            usb = usb.parent
        else:
            raise OSError('USB parent nesting exceeded')
        vendor = self._read(usb / 'idVendor').lower()
        product = self._read(usb / 'idProduct').lower()
        serial = self._read(usb / 'serial') if (usb / 'serial').exists() else ''
        interface = ''
        for parent in (path,*path.parents):
            if parent==usb:
                break
            if (parent/'bInterfaceNumber').exists():
                interface=self._read(parent/'bInterfaceNumber')
                break
        # Preserve selection across ttyACM/ttyUSB renumbering on the same USB port.
        identity = str(usb.relative_to(self.sys_root)) + '\0' + serial + '\0' + interface
        key = hashlib.sha256(identity.encode()).hexdigest()[:32]
        info = path.stat()
        adapters = [a for a in self.registry.adapters.values()
                    if a.broker_serial and a.matches_usb(vendor,product)]
        adapter_id = adapters[0].id if len(adapters)==1 else ''
        return Candidate(key, tty, path, usb, os.makedev(major, minor),
                         bool(adapter_id), (info.st_dev, info.st_ino),adapter_id)

    def enumerate(self):
        result = {}
        # Bound work even when a malformed or unexpectedly large sysfs is mounted.
        with os.scandir(self.sys_root / 'class' / 'tty') as entries:
            count = 0
            for entry in entries:
                if not TTY_NAME.fullmatch(entry.name):
                    continue
                count += 1
                if count > 128:
                    break
                try:
                    candidate = self.inspect(entry.name)
                except (OSError, ValueError, UnicodeError):
                    continue
                result.setdefault(candidate.id, candidate)
        return result

    def open_verified(self, candidate):
        import serial
        if not candidate.supported or self.inspect(candidate.tty) != candidate:
            raise OSError('Adapter identity changed')
        adapter = self.registry.get(candidate.adapter_id)
        if not adapter.broker_serial:
            raise OSError('Adapter does not support serial broker access')
        if os.major(candidate.rdev) not in (166, 188):
            raise OSError('Unsupported device major')
        path = self.device_root / candidate.tty
        node = path.lstat()
        if not stat.S_ISCHR(node.st_mode) or node.st_rdev != candidate.rdev:
            raise OSError('Device node mismatch')
        fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK | os.O_NOFOLLOW)
        port = None
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino, opened.st_rdev) != (node.st_dev, node.st_ino, node.st_rdev):
                raise OSError('Device node changed')
            if self.inspect(candidate.tty) != candidate:
                raise OSError('Adapter identity changed')
            # pyserial opens the already checked inode; a path replacement cannot redirect it.
            port = serial.Serial(f'/proc/self/fd/{fd}', adapter.baudrate, timeout=1,
                                 write_timeout=1, exclusive=True)
            actual = os.fstat(port.fileno())
            if (actual.st_dev, actual.st_ino, actual.st_rdev) != (opened.st_dev, opened.st_ino, opened.st_rdev):
                raise OSError('Serial identity mismatch')
            if self.inspect(candidate.tty) != candidate:
                raise OSError('Adapter identity changed')
            adapter.probe_connection(port,time.monotonic() + 2)
            return port
        except Exception:
            if port is not None:
                port.close()
            raise
        finally:
            os.close(fd)

    def _failed(self, key):
        attempts = self.failures.get(key, (0, 0))[0] + 1
        self.failures[key] = (min(attempts, 6), time.monotonic() + min(60, 3 * 2 ** min(attempts - 1, 5)))
        self.candidates[key] = {'id': key, 'name': 'AOOSTAR display adapter',
                                'state': 'error', 'reason': 'Display unavailable or handshake failed'}

    def scan_once(self):
        try:
            found = self.enumerate()
        except OSError:
            found = {}
        with self.lock:
            stale = [key for key, item in self.connections.items()
                     if found.get(key) != item.candidate]
            removed = [self.connections.pop(key) for key in stale]
            self.candidates = {key: value for key, value in self.candidates.items() if key in found}
            self.failures = {key: value for key, value in self.failures.items() if key in found}
        for item in removed:
            with item.lock:
                item.port.close()
        selected = sorted(found.values(), key=lambda item: (not item.supported, item.id))[:MAX_DEVICES]
        with self.lock:
            selected_ids = {item.id for item in selected}
            self.candidates = {key: item for key, item in self.candidates.items() if key in selected_ids}
        for candidate in selected:
            if self.stop_event.is_set():
                break
            key = candidate.id
            with self.lock:
                if key in self.connections:
                    continue
                if len(self.connections) >= MAX_DEVICES:
                    continue
                if not candidate.supported:
                    self.candidates[key] = {'id': key, 'name': 'USB serial adapter',
                                            'state': 'unsupported', 'reason': 'Adapter is not supported'}
                    continue
                if self.failures.get(key, (0, 0))[1] > time.monotonic():
                    continue
                self.candidates[key] = {'id': key, 'name': 'AOOSTAR display adapter',
                                        'state': 'probing', 'reason': 'Waiting for display acknowledgement'}
            try:
                port = self.open_verified(candidate)
            except Exception:
                with self.lock:
                    self._failed(key)
                continue
            with self.lock:
                self.connections[key] = Connection(candidate, port)
                self.candidates.pop(key, None)
                self.failures.pop(key, None)

    def snapshot(self):
        with self.lock:
            devices = []
            for key in sorted(self.connections):
                caps = self.capabilities(key)
                mode = caps.modes[0]
                devices.append({'id': key, 'device': 'broker:' + key, 'name': caps.adapter_id,
                        'kind': 'broker', 'width': mode.width, 'height': mode.height,
                        'size_source': 'adapter-profile', 'verified': True,
                        'accessible': True, 'state': 'ready',
                        'generation': self.connections[key].generation,
                        'capabilities': caps.to_dict()})
            return {'version': 1, 'devices': devices,
                    'candidates': [dict(item) for item in self.candidates.values()][:MAX_DEVICES]}

    def capabilities(self, key):
        with self.lock:
            item = self.connections.get(key)
            if item is None:
                raise KeyError(key)
            adapter = self.registry.get(item.candidate.adapter_id)
            return replace(adapter.get_capabilities(key),probe_status='protocol-confirmed')

    def frame_mode(self, key, mode_id='', generation=None):
        """Resolve only from the current trusted connection, never client dimensions."""
        with self.lock:
            caps = self.capabilities(key)
            item = self.connections[key]
            if generation is not None and generation != item.generation:
                raise ValueError('Display generation changed')
            matches = [m for m in caps.modes if m.id==mode_id]
            if not mode_id and caps.adapter_id=='aoostar':
                matches = list(caps.modes)
            if len(matches)!=1:
                raise ValueError('Unsupported display mode')
            return caps, matches[0]

    def send(self, key, frame, mode_id='', generation=None):
        with self.lock:
            caps, mode = self.frame_mode(key,mode_id,generation)
            caps.validate_frame(mode,frame)
            item = self.connections.get(key)
            if item is None:
                raise KeyError(key)
            if not item.lock.acquire(blocking=False):
                raise BusyError()
        try:
            deadline = time.monotonic() + 30
            self.registry.get(item.candidate.adapter_id).send_encoded(item.port,frame,mode,deadline)
        except Exception:
            with self.lock:
                if self.connections.get(key) is item:
                    self.connections.pop(key)
                    self._failed(key)
            item.port.close()
            raise OSError('Display send failed') from None
        finally:
            item.lock.release()

    def start(self):
        def worker():
            while not self.stop_event.is_set():
                self.scan_once()
                self.stop_event.wait(3)
        self.thread = threading.Thread(target=worker, name='display-discovery', daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join()
        with self.lock:
            items = list(self.connections.values())
            self.connections.clear()
        for item in items:
            with item.lock:
                item.port.close()


def create_app(manager=None, start_worker=True):
    manager = manager if manager is not None else BrokerManager()

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            manager.start()
        try:
            yield
        finally:
            await asyncio.to_thread(manager.close)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    active = set()

    @app.get('/healthz')
    async def health():
        if start_worker and (manager.thread is None or not manager.thread.is_alive()):
            raise HTTPException(503,'Discovery worker unavailable')
        return {'status': 'ok', 'version': 1}

    @app.get('/v1/devices')
    async def devices():
        return manager.snapshot()

    @app.post('/v1/devices/{key}/frame')
    async def frame(key: str, request: Request):
        if not DEVICE_ID.fullmatch(key):
            raise HTTPException(404, 'Unknown display')
        mode_id = request.query_params.get('mode','')
        generation = request.query_params.get('generation')
        if len(mode_id)>64 or (generation is not None and not DEVICE_ID.fullmatch(generation)):
            raise HTTPException(400, 'Invalid frame negotiation')
        try:
            caps, mode = manager.frame_mode(key,mode_id,generation)
        except KeyError:
            raise HTTPException(404, 'Unknown display') from None
        except ValueError:
            raise HTTPException(400, 'Unsupported or stale display mode') from None
        bytes_per_pixel = {'rgb565-le':2,'rgb888':3}.get(mode.pixel_format)
        exact_bytes = mode.width*mode.height*bytes_per_pixel if bytes_per_pixel else None
        limit = min(caps.max_frame_bytes,exact_bytes) if exact_bytes else caps.max_frame_bytes
        headers = request.scope['headers']
        lengths = [value for name, value in headers if name.lower() == b'content-length']
        if any(name.lower() == b'transfer-encoding' for name, _ in headers) or len(lengths) != 1:
            raise HTTPException(400, 'A single Content-Length is required')
        try:
            if not lengths[0].isdigit():
                raise ValueError()
            length = int(lengths[0])
        except ValueError:
            raise HTTPException(400, 'Invalid Content-Length') from None
        if length > limit:
            raise HTTPException(413, 'Frame too large')
        if length<=0 or (exact_bytes is not None and length != exact_bytes):
            raise HTTPException(400, 'Wrong frame size')
        if request.headers.get('content-type', '') != 'application/octet-stream':
            raise HTTPException(415, 'Expected application/octet-stream')
        if key in active or len(active) >= 4:
            raise HTTPException(409, 'Display broker busy')
        if key not in {item['id'] for item in manager.snapshot()['devices']}:
            raise HTTPException(404, 'Unknown display')
        active.add(key)
        try:
            body = bytearray()
            try:
                async with asyncio.timeout(10):
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > limit:
                            raise HTTPException(413, 'Frame too large')
                        body.extend(chunk)
            except TimeoutError:
                raise HTTPException(408, 'Frame upload timed out') from None
            if len(body) != length:
                raise HTTPException(400, 'Wrong frame size')
            try:
                caps.validate_frame(mode,body)
                if not mode_id and generation is None:
                    await asyncio.to_thread(manager.send, key, bytes(body))
                else:
                    await asyncio.to_thread(manager.send, key, bytes(body), mode.id, generation)
            except ValueError:
                raise HTTPException(400, 'Invalid frame or changed display mode') from None
            except BusyError:
                raise HTTPException(409, 'Display busy') from None
            except KeyError:
                raise HTTPException(404, 'Unknown display') from None
            except OSError:
                raise HTTPException(503, 'Display unavailable') from None
            return {'ok': True}
        finally:
            active.discard(key)

    return app


def bind_socket(path):
    path = Path(path).absolute()
    parent = path.parent
    # Refuse symlinks throughout the parent path, including an existing final socket.
    if parent.resolve() != parent:
        raise OSError('Socket parent must not contain symlinks')
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = parent.stat()
    if info.st_uid != os.getuid() or not stat.S_ISDIR(info.st_mode):
        raise OSError('Socket directory must be owned by the broker user')
    parent.chmod(0o700)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise OSError('Refusing to replace unsafe socket path')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(1)
            try:
                probe.connect(str(path))
            except ConnectionRefusedError:
                path.unlink()
            else:
                raise OSError('Broker socket already in use')
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(path))
        path.chmod(0o600)
        listener.listen(16)
        return listener
    except Exception:
        listener.close()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device-root', default='/host-dev')
    parser.add_argument('--sys-root', default='/host-sys')
    parser.add_argument('--socket', default='/run/openscreen-broker/broker.sock')
    args = parser.parse_args()
    import uvicorn
    listener = bind_socket(args.socket)
    try:
        app = create_app(BrokerManager(args.device_root, args.sys_root))
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, limit_concurrency=16))
        server.run(sockets=[listener])
    finally:
        listener.close()


if __name__ == '__main__':
    main()
