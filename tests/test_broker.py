import os
from pathlib import Path
import sys
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from openscreen.broker import (BrokerManager, BusyError, Candidate,
                               FRAME_BYTES, bind_socket, create_app)

KEY = 'a' * 32


def candidate(supported=True, key=KEY):
    return Candidate(key, 'ttyACM0', Path('/sys/devices/usb/ttyACM0'),
                     Path('/sys/devices/usb'), 0, supported)


def manager():
    result = BrokerManager()
    result.enumerate = Mock(return_value={KEY: candidate()})
    result.open_verified = Mock(return_value=Mock())
    return result


def test_unknown_adapter_is_never_opened():
    value = manager()
    value.enumerate.return_value = {KEY: candidate(False)}
    value.scan_once()
    value.open_verified.assert_not_called()
    assert value.snapshot()['devices'] == []
    assert value.snapshot()['candidates'][0]['state'] == 'unsupported'


def test_failure_is_backed_off_and_not_verified():
    value = manager()
    value.open_verified.side_effect = OSError('private path /dev/secret')
    value.scan_once()
    value.scan_once()
    assert value.open_verified.call_count == 1
    assert value.snapshot()['devices'] == []
    assert 'secret' not in str(value.snapshot())


def test_hotplug_closes_revokes_and_changes_generation():
    value = manager()
    value.scan_once()
    generation = value.snapshot()['devices'][0]['generation']
    port = value.open_verified.return_value
    value.enumerate.return_value = {}
    value.scan_once()
    port.close.assert_called_once()
    assert value.snapshot()['devices'] == []
    value.enumerate.return_value = {KEY: candidate()}
    value.scan_once()
    assert value.snapshot()['devices'][0]['generation'] != generation


def test_repeated_scan_retains_exclusive_connection():
    value = manager()
    value.scan_once()
    value.scan_once()
    assert value.open_verified.call_count == 1
    assert len(value.snapshot()['devices']) == 1


def test_scan_bounds_candidates_and_connections():
    value = manager()
    value.enumerate.return_value = {f'{index:032x}': candidate(key=f'{index:032x}') for index in range(100)}
    value.scan_once()
    assert len(value.snapshot()['devices']) == 16


def test_supported_hotplug_not_starved_by_unknown_adapters():
    value = manager()
    unknown = {f'{index:032x}': candidate(False, f'{index:032x}') for index in range(16)}
    value.enumerate.return_value = unknown
    value.scan_once()
    value.enumerate.return_value = {**unknown, KEY: candidate()}
    value.scan_once()
    assert len(value.snapshot()['devices']) == 1
    assert len(value.snapshot()['candidates']) <= 16


def test_same_adapter_new_sysfs_inode_forces_reconnect():
    from dataclasses import replace
    value = manager()
    value.scan_once()
    generation = value.snapshot()['devices'][0]['generation']
    value.enumerate.return_value = {KEY: replace(candidate(), sys_identity=(1, 99))}
    value.scan_once()
    assert value.snapshot()['devices'][0]['generation'] != generation
    assert value.open_verified.call_count == 2


def test_failed_send_revokes_and_closes():
    value = manager()
    value.scan_once()
    value.open_verified.return_value.write.side_effect = OSError('unplugged')
    with pytest.raises(OSError):
        value.send(KEY, bytes(FRAME_BYTES))
    assert value.snapshot()['devices'] == []
    value.open_verified.return_value.close.assert_called_once()


def test_busy_send_has_no_queue():
    value = manager()
    value.scan_once()
    connection = value.connections[KEY]
    with connection.lock:
        with pytest.raises(BusyError):
            value.send(KEY, bytes(FRAME_BYTES))
    connection.port.write.assert_not_called()


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux character-device semantics')
def test_mismatched_character_node_never_opened(tmp_path, monkeypatch):
    value = BrokerManager(device_root=tmp_path)
    item = Candidate(KEY, 'ttyACM0', Path('/sys/a'), Path('/sys/b'), os.makedev(166, 0), True)
    value.inspect = Mock(return_value=item)
    (tmp_path / 'ttyACM0').write_text('not a character node')
    opener = Mock(side_effect=AssertionError('must not open'))
    monkeypatch.setattr(os, 'open', opener)
    with pytest.raises(OSError, match='node mismatch'):
        value.open_verified(item)
    opener.assert_not_called()


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux device numbers and sysfs paths')
def test_sysfs_discovery_metadata_and_escape_rejection(tmp_path):
    root = tmp_path / 'sys'
    tty = root / 'class' / 'tty' / 'ttyACM0'
    tty.mkdir(parents=True)
    (tty / 'dev').write_text('166:0')
    (tty / 'idVendor').write_text('0416')
    (tty / 'idProduct').write_text('90a1')
    (tty / 'serial').write_text('PRIVATE-SERIAL')
    value = BrokerManager(sys_root=root)
    found = value.enumerate()
    assert len(found) == 1
    item = next(iter(found.values()))
    assert item.supported and item.rdev == os.makedev(166, 0)
    assert 'PRIVATE' not in item.id
    outside = tmp_path / 'outside'
    outside.mkdir()
    (root / 'class' / 'tty' / 'ttyUSB0').symlink_to(outside)
    with pytest.raises(OSError, match='Untrusted'):
        value.inspect('ttyUSB0')
    assert len(value.enumerate()) == 1


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux checked FD serial opening')
@pytest.mark.parametrize('ack', [b'A', b'no'], ids=['acknowledged', 'rejected'])
def test_checked_fd_and_handshake(tmp_path, monkeypatch, ack):
    from types import SimpleNamespace
    import stat
    import serial
    value = BrokerManager(device_root=tmp_path)
    item = Candidate(KEY, 'ttyACM0', Path('/sys/a'), Path('/sys/b'), os.makedev(166, 0), True)
    value.inspect = Mock(return_value=item)
    info = SimpleNamespace(st_mode=stat.S_IFCHR | 0o660, st_rdev=item.rdev, st_dev=1, st_ino=42)
    real_lstat = Path.lstat
    monkeypatch.setattr(Path, 'lstat', lambda self: info if self == tmp_path / 'ttyACM0' else real_lstat(self))
    opener = Mock(return_value=90)
    closer = Mock()
    monkeypatch.setattr(os, 'open', opener)
    real_fstat = os.fstat
    monkeypatch.setattr(os, 'fstat', lambda fd: info if fd == 90 else real_fstat(fd))
    monkeypatch.setattr(os, 'close', closer)
    port = Mock()
    port.fileno.return_value = 90
    port.read.return_value = ack
    port.write.side_effect = lambda data: len(data)
    factory = Mock(return_value=port)
    monkeypatch.setattr(serial, 'Serial', factory)
    if ack == b'A':
        assert value.open_verified(item) is port
        port.close.assert_not_called()
    else:
        with pytest.raises(OSError, match='not acknowledged'):
            value.open_verified(item)
        port.close.assert_called_once()
    assert opener.call_args.args[1] & os.O_NOFOLLOW
    assert factory.call_args.args[0] == '/proc/self/fd/90'
    assert factory.call_args.kwargs['exclusive'] is True
    closer.assert_called_once_with(90)


def test_api_exact_raw_frame_and_sanitized_inventory():
    value = manager()
    value.scan_once()
    value.send = Mock()
    with TestClient(create_app(value, start_worker=False)) as client:
        inventory = client.get('/v1/devices').json()
        assert inventory['devices'][0]['device'] == 'broker:' + KEY
        assert 'serial' not in str(inventory)
        response = client.post(f'/v1/devices/{KEY}/frame', content=bytes(FRAME_BYTES),
                               headers={'content-type': 'application/octet-stream'})
        assert response.status_code == 200
        value.send.assert_called_once_with(KEY, bytes(FRAME_BYTES))


@pytest.mark.parametrize('headers,body,status', [
    ({'content-type': 'application/octet-stream'}, b'x', 400),
    ({'content-type': 'application/octet-stream'}, bytes(FRAME_BYTES + 1), 413),
    ({'content-type': 'image/png'}, bytes(FRAME_BYTES), 415),
    ({'content-type': 'application/octet-stream', 'transfer-encoding': 'chunked'}, bytes(FRAME_BYTES), 400),
    ({'content-type': 'application/octet-stream', 'content-length': '-1'}, b'x', 400),
], ids=['short', 'oversized', 'wrong-type', 'chunked', 'bad-length'])
def test_api_rejects_invalid_uploads(headers, body, status):
    value = manager()
    value.scan_once()
    value.send = Mock()
    with TestClient(create_app(value, start_worker=False)) as client:
        response = client.post(f'/v1/devices/{KEY}/frame', content=body, headers=headers)
        assert response.status_code == status
        value.send.assert_not_called()


def test_api_arbitrary_path_is_not_device():
    value = manager()
    value.send = Mock()
    with TestClient(create_app(value, start_worker=False)) as client:
        for key in ('ttyACM0', 'dev%2FttyACM0', 'http:example', 'b' * 32):
            response = client.post(f'/v1/devices/{key}/frame', content=bytes(FRAME_BYTES),
                                   headers={'content-type': 'application/octet-stream'})
            assert response.status_code == 404
        value.send.assert_not_called()


def test_api_busy_and_send_failure():
    value = manager()
    value.scan_once()
    value.send = Mock(side_effect=BusyError())
    with TestClient(create_app(value, start_worker=False)) as client:
        response = client.post(f'/v1/devices/{KEY}/frame', content=bytes(FRAME_BYTES),
                               headers={'content-type': 'application/octet-stream'})
        assert response.status_code == 409
        value.send.side_effect = OSError('private detail')
        response = client.post(f'/v1/devices/{KEY}/frame', content=bytes(FRAME_BYTES),
                               headers={'content-type': 'application/octet-stream'})
        assert response.status_code == 503
        assert 'private' not in response.text


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux Unix socket permissions')
def test_real_unix_socket_http_and_permissions(tmp_path):
    import threading
    import time
    import uvicorn
    path = tmp_path / 'private' / 'broker.sock'
    listener = bind_socket(path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    value = manager()
    server = uvicorn.Server(uvicorn.Config(create_app(value, start_worker=False), log_level='error'))
    value.scan_once()
    value.send=Mock()
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]))
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.01)
        with httpx.Client(transport=httpx.HTTPTransport(uds=str(path)), base_url='http://broker') as client:
            assert client.get('/healthz').json()['status'] == 'ok'
            response=client.post(f'/v1/devices/{KEY}/frame',content=bytes(FRAME_BYTES),headers={'content-type':'application/octet-stream'})
            assert response.status_code==200
            value.send.assert_called_once_with(KEY,bytes(FRAME_BYTES))
        with pytest.raises(OSError, match='already in use'):
            bind_socket(path)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
    assert not thread.is_alive()


@pytest.mark.skipif(sys.platform!='linux',reason='Real Linux pseudo-terminal descriptor')
def test_real_serial_reopens_checked_fd_exclusively(monkeypatch):
    import pty
    import select
    import threading
    from openscreen.protocol import ON
    master,slave=pty.openpty()
    path=Path(os.ttyname(slave))
    info=path.stat()
    value=BrokerManager(device_root=path.parent)
    item=Candidate(KEY,path.name,Path('/sys/test'),Path('/sys/test'),info.st_rdev,True)
    monkeypatch.setattr(value,'inspect',lambda tty:item)
    # The production major check is covered separately; the emulator is a PTY.
    monkeypatch.setattr(os,'major',lambda rdev:166)
    received=[]
    def acknowledge():
        if select.select([master],[],[],3)[0]:
            received.append(os.read(master,1024))
            os.write(master,b'A')
    thread=threading.Thread(target=acknowledge)
    thread.start()
    port=None
    try:
        port=value.open_verified(item)
        thread.join(timeout=4)
        assert received==[ON]
        assert port.exclusive is True
    finally:
        if port:port.close()
        os.close(master)
        os.close(slave)
        thread.join(timeout=4)


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux Unix socket permissions')
def test_socket_refuses_symlink_and_regular_file(tmp_path):
    path = tmp_path / 'broker.sock'
    path.write_text('keep')
    with pytest.raises(OSError):
        bind_socket(path)
    assert path.read_text() == 'keep'
    alias = tmp_path / 'alias.sock'
    alias.symlink_to(path)
    with pytest.raises(OSError):
        bind_socket(alias)
