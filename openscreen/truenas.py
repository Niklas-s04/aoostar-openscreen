"""Bounded read-only TrueNAS 25.10 API sessions.

Contract verified against middleware tag TS-25.10.0 (virt/instance.py and
api/v25_10_0) and api.truenas.com/v25.10.0 reporting.realtime.
Unknown releases are not assigned these capabilities.
"""
import hashlib
import json
import math
import threading
import time
import websocket

from .models import Snapshot

LIMIT = 4 * 1024 * 1024
API_VERSION = 'v25.10.0'
CAPABILITIES = {API_VERSION: {'containers': 'virt.instance.query', 'realtime': 'reporting.realtime'}}


class TrueNASError(Exception):
    pass


class Denied(TrueNASError):
    pass


def numeric(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def host_metrics(data, interface=None):
    cpu = data.get('cpu', {}).get('cpu', {})
    memory = data.get('memory', {})
    total = numeric(memory.get('physical_memory_total'))
    available = numeric(memory.get('physical_memory_available'))
    used = total - available if total is not None and available is not None and 0 <= available <= total else None
    temps = [numeric(item.get('temp')) for item in data.get('cpu', {}).values() if isinstance(item, dict)]
    temps = [value for value in temps if value is not None]
    interfaces = data.get('interfaces', {})
    # Never sum bridge, bond and physical counters; require selection when ambiguous.
    selected = interface or (next(iter(interfaces)) if len(interfaces) == 1 else None)
    network = interfaces.get(selected, {})
    disks = data.get('disks', {})
    return {'cpu': numeric(cpu.get('usage')), 'temperature': max(temps) if temps else None,
            'memory_total': total, 'memory_used': used, 'memory': used / total * 100 if used is not None and total else None,
            'net_rx_rate': numeric(network.get('received_bytes_rate')), 'net_tx_rate': numeric(network.get('sent_bytes_rate')),
            'download': numeric(network.get('received_bytes_rate')), 'upload': numeric(network.get('sent_bytes_rate')),
            'disk_read_rate': numeric(disks.get('read_bytes')), 'disk_write_rate': numeric(disks.get('write_bytes'))}


class Session:
    def __init__(self, connect, clock=time.monotonic):
        self.connect, self.clock = connect, clock
        self.peer = None
        self.sequence = 0
        self.next_attempt = 0
        self.failures = 0
        self.latest = None
        self.latest_at = 0
        self.lock = threading.RLock()
        self.condition = threading.Condition()
        self.pending = {}
        self.failure = False
        self.reader = None
        self.subscribed = False
        self.retired = False

    def retire(self):
        """Permanently dispose a registry entry, including already acquired references."""
        # Registry operations acquire registry lock then session lock; snapshots
        # never acquire the registry lock, so retirement cannot invert lock order.
        with self.lock:
            self.retired = True
            self.close()

    def close(self):
        peer, self.peer = self.peer, None
        if peer:
            peer.close()
        with self.condition:
            self.failure = True
            self.condition.notify_all()
        if self.reader and self.reader is not threading.current_thread():
            self.reader.join(timeout=1)
        self.latest = None
        self.subscribed = False

    def _receive(self, peer):
        try:
            while self.peer is peer:
                try:
                    raw = peer.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not raw or len(raw) > LIMIT:
                    raise TrueNASError('TrueNAS-Antwortlimit erreicht')
                message = json.loads(raw)
                if not isinstance(message, dict):
                    raise TrueNASError('Ungültige TrueNAS-Antwort')
                with self.condition:
                    if self.peer is not peer:
                        return
                    ident = message.get('id')
                    if ident in self.pending:
                        self.pending[ident] = message
                    elif message.get('method') == 'collection_update':
                        event = message.get('params', {})
                        if isinstance(event, list):
                            event = event[0] if event else {}
                        if isinstance(event, dict) and str(event.get('collection', '')).startswith('reporting.realtime'):
                            fields = event.get('fields')
                            if isinstance(fields, dict):
                                self.latest, self.latest_at = fields, self.clock()
                    self.condition.notify_all()
        except Exception:
            with self.condition:
                if self.peer is peer:
                    self.failure = True
                    self.condition.notify_all()

    def rpc(self, method, params=None):
        with self.condition:
            self.sequence += 1
            ident = self.sequence
            self.pending[ident] = None
        try:
            self.peer.send(json.dumps({'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params or []}))
            with self.condition:
                self.condition.wait_for(lambda: self.pending[ident] is not None or self.failure, timeout=8)
                message = self.pending[ident]
            if message is None:
                raise TrueNASError('TrueNAS-Verbindung unterbrochen oder Zeitlimit erreicht')
            if 'error' in message:
                raise Denied('TrueNAS verweigert ' + method)
            return message.get('result')
        finally:
            with self.condition:
                self.pending.pop(ident, None)

    def snapshot(self, source, token):
        with self.lock:
            if self.retired:
                raise TrueNASError('TrueNAS-Sitzung wurde geschlossen')
            if (self.peer is None or self.failure) and self.clock() < self.next_attempt:
                raise TrueNASError('TrueNAS-Wiederverbindung wartet')
            try:
                if self.peer is None or self.failure:
                    self.close()
                    self.failure = False
                    self.peer = self.connect()
                    self.reader = threading.Thread(target=self._receive, args=(self.peer,), daemon=True)
                    self.reader.start()
                    if self.rpc('auth.login_with_api_key', [token]) is not True:
                        raise TrueNASError('TrueNAS-Anmeldung abgelehnt')
                version = self.rpc('system.version')
                snap = Snapshot(source_id=source.id, observed_at=time.time(), info={
                    'version': version, 'api_version': API_VERSION, 'scope': 'TrueNAS-Host', 'capabilities': {}})
                caps = snap.info['capabilities']
                def optional(method, default):
                    try:
                        value = self.rpc(method)
                        caps[method] = 'available'
                        return value
                    except Denied:
                        caps[method] = 'unavailable_or_denied'
                        return default
                info = optional('system.info', {})
                snap.info['hostname'] = info.get('hostname')
                pools = optional('pool.query', [])
                for item in pools[:2000]:
                    used, total = numeric(item.get('allocated')), numeric(item.get('size'))
                    snap.pools.append({'id': str(item['id']), 'name': item['name'], 'state': str(item.get('status', 'unknown')).lower(),
                                       'used': used, 'total': total, 'percent': used / total * 100 if used is not None and total else None})
                for method, kind in [('app.query', 'truenas'), (CAPABILITIES[API_VERSION]['containers'], 'truenas-container')]:
                    items = optional(method, [])
                    for item in items[:2000]:
                        if kind == 'truenas-container' and item.get('type') != 'CONTAINER':
                            continue
                        snap.workloads.append({'id': str(item['id']), 'name': item.get('name', str(item['id'])), 'kind': kind,
                                               'state': str(item.get('status' if kind == 'truenas-container' else 'state', 'unknown')).lower()})
                if not self.subscribed:
                    try:
                        self.rpc('core.subscribe', ['reporting.realtime:{"interval":5}'])
                        self.subscribed = True
                    except Denied:
                        caps['reporting.realtime'] = 'unavailable_or_denied'
                with self.condition:
                    latest = self.latest if self.latest is not None and self.clock() - self.latest_at <= 20 else {}
                    age = self.clock() - self.latest_at if self.latest is not None else None
                snap.metrics.update(host_metrics(latest, source.fields.get('network_interface')))
                snap.info.update(realtime_age=age, network_interface=source.fields.get('network_interface'))
                caps.setdefault('reporting.realtime', 'available' if latest else 'waiting_or_stale')
                snap.metrics['running'] = (sum(w['state'] == 'running' for w in snap.workloads)
                                           if all(caps.get(method) == 'available' for method in ('app.query', CAPABILITIES[API_VERSION]['containers']))
                                           else None)
                self.failures = 0
                return snap
            except Denied:
                self.close()
                raise
            except Exception:
                self.close()
                self.failures = min(self.failures + 1, 6)
                self.next_attempt = self.clock() + min(60, 2 ** self.failures)
                raise


_sessions = {}
_lock = threading.Lock()


def collect_session(source, token, connect):
    # Rotation of credentials, CA selection, URL or configuration replaces the session.
    fingerprint = hashlib.sha256((source.model_dump_json() + token).encode()).digest()
    with _lock:
        entry = _sessions.get(source.id)
        if entry is None or entry[0] != fingerprint:
            if entry:
                entry[1].retire()
            if len(_sessions) >= 64:
                _, removed = _sessions.pop(next(iter(_sessions)))
                removed.retire()
            entry = (fingerprint, Session(connect))
            _sessions[source.id] = entry
    return entry[1].snapshot(source, token)


def close_truenas_sessions(active_ids=None):
    """Close all sessions, or prune sessions whose source ID is not active."""
    with _lock:
        for ident in list(_sessions):
            if active_ids is None or ident not in active_ids:
                _sessions.pop(ident)[1].retire()
