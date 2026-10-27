import json
import queue
import threading

import pytest

from openscreen.models import Source
from openscreen.truenas import Session, TrueNASError, host_metrics, collect_session, close_truenas_sessions


class Peer:
    def __init__(self, denied=()):
        self.queue = queue.Queue()
        self.denied = denied
        self.methods = []
        self.closed = False

    def send(self, raw):
        request = json.loads(raw)
        method = request['method']
        self.methods.append(method)
        data = {'auth.login_with_api_key': True, 'system.version': 'TrueNAS-25.10.0',
                'system.info': {'hostname': 'nas'}, 'pool.query': [],
                'app.query': [{'id': 'a', 'state': 'RUNNING'}],
                'virt.instance.query': [{'id': 'c', 'type': 'CONTAINER', 'status': 'STOPPED'},
                                        {'id': 'vm', 'type': 'VM', 'status': 'RUNNING'}],
                'core.subscribe': 'subscription'}
        if method == 'core.subscribe':
            self.queue.put(json.dumps({'method': 'collection_update', 'params': {
                'collection': 'reporting.realtime:{"interval":5}', 'event': 'ADDED',
                'fields': {'cpu': {'cpu': {'usage': 37}}, 'memory': {
                    'physical_memory_total': 100, 'physical_memory_available': 40}}}}))
        self.queue.put(json.dumps({'id': request['id'], **({'error': {'message': 'secret server detail'}}
                                                       if method in self.denied else {'result': data[method]})}))

    def recv(self):
        return self.queue.get(timeout=2)

    def close(self):
        self.closed = True
        self.queue.put('')


SOURCE = Source(id='nas', name='NAS', kind='truenas', url='https://nas')


def test_session_reuses_connection_demultiplexes_event_and_filters_containers():
    peer = Peer()
    connects = []
    session = Session(lambda: connects.append(True) or peer)
    try:
        first = session.snapshot(SOURCE, 'credential')
        second = session.snapshot(SOURCE, 'credential')
        assert len(connects) == 1
        assert peer.methods.count('auth.login_with_api_key') == 1
        assert peer.methods.count('core.subscribe') == 1
        assert first.metrics['cpu'] == second.metrics['cpu'] == 37
        assert first.metrics['memory'] == 60
        assert [(w['kind'], w['state']) for w in first.workloads] == [('truenas', 'running'), ('truenas-container', 'stopped')]
        assert 'credential' not in first.model_dump_json()
    finally:
        session.close()
    assert peer.closed


def test_permissions_degrade_only_affected_features_and_stale_metrics_expire():
    now = [0]
    session = Session(lambda: Peer(denied={'virt.instance.query', 'pool.query'}), clock=lambda: now[0])
    try:
        result = session.snapshot(SOURCE, 'key')
        assert result.ok and result.workloads[0]['name'] == 'a'
        assert result.info['capabilities']['virt.instance.query'] == 'unavailable_or_denied'
        now[0] = 21
        result = session.snapshot(SOURCE, 'key')
        assert result.metrics['cpu'] is None
        assert result.info['capabilities']['reporting.realtime'] == 'waiting_or_stale'
    finally:
        session.close()


def test_reconnect_uses_backoff_and_recovers():
    now, attempts = [0], []
    def connect():
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError('private connection detail')
        return Peer()
    session = Session(connect, clock=lambda: now[0])
    with pytest.raises(OSError):
        session.snapshot(SOURCE, 'key')
    with pytest.raises(TrueNASError, match='wartet'):
        session.snapshot(SOURCE, 'key')
    assert len(attempts) == 1
    now[0] = 5
    try:
        assert session.snapshot(SOURCE, 'key').metrics['cpu'] == 37
        assert len(attempts) == 2
    finally:
        session.close()


def test_partial_metrics_preserve_unknown_and_never_sum_interfaces_or_counters():
    data = {'interfaces': {'eth0': {'received_bytes_rate': 10}, 'br0': {'received_bytes_rate': 10}},
            'disks': {'read_bytes': 123}, 'cpu': {'cpu': {'usage': float('nan')}}}
    assert host_metrics(data)['net_rx_rate'] is None
    assert host_metrics(data, 'eth0')['net_rx_rate'] == 10
    assert host_metrics(data, 'eth0')['net_tx_rate'] is None
    assert host_metrics(data)['disk_read_rate'] == 123
    assert host_metrics(data)['cpu'] is None
    assert host_metrics({'interfaces': {'eth0': {'received_bytes': 100}}})['net_rx_rate'] is None


def test_denied_reporting_preserves_inventory_and_no_server_details():
    session = Session(lambda: Peer(denied={'core.subscribe'}))
    try:
        result = session.snapshot(SOURCE, 'key')
        assert result.ok and len(result.workloads) == 2
        assert result.info['capabilities']['reporting.realtime'] == 'unavailable_or_denied'
        assert 'secret server detail' not in result.model_dump_json()
    finally:
        session.close()


def test_registry_rotates_credentials_and_prunes_sessions():
    peers = []
    def connect():
        peer = Peer()
        peers.append(peer)
        return peer
    try:
        collect_session(SOURCE, 'one', connect)
        collect_session(SOURCE, 'two', connect)
        assert len(peers) == 2 and peers[0].closed
        close_truenas_sessions({'nas'})
        assert not peers[1].closed
        close_truenas_sessions(set())
        assert peers[1].closed
    finally:
        close_truenas_sessions()


def test_pruned_acquired_session_cannot_reconnect(monkeypatch):
    acquired, resume = threading.Event(), threading.Event()
    original = Session.snapshot
    attempts, failures = [], []
    def paused_snapshot(self, source, token):
        acquired.set()
        assert resume.wait(3)
        return original(self, source, token)
    monkeypatch.setattr(Session, 'snapshot', paused_snapshot)
    def collect_in_thread():
        try:
            collect_session(SOURCE, 'key', lambda: attempts.append(True) or Peer())
        except TrueNASError as exc:
            failures.append(exc)
    worker = threading.Thread(target=collect_in_thread)
    try:
        worker.start()
        assert acquired.wait(3)
        close_truenas_sessions(set())
        resume.set()
        worker.join(3)
        assert not worker.is_alive()
        assert not attempts
        assert len(failures) == 1
    finally:
        resume.set()
        worker.join(3)
        close_truenas_sessions()


@pytest.mark.parametrize('late_message', ['', json.dumps({'method': 'collection_update', 'params': {
    'collection': 'reporting.realtime', 'fields': {'cpu': {'cpu': {'usage': 99}}}}})])
def test_old_receiver_cannot_fail_or_update_replacement_connection(late_message):
    session = Session(lambda: None)
    replacement = object()
    class OldPeer:
        def recv(self):
            session.peer = replacement
            return late_message
    old = OldPeer()
    session.peer = old
    session._receive(old)
    assert session.peer is replacement
    assert not session.failure
    assert session.latest is None
