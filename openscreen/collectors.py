"""Read-only platform adapters. Credentials never enter normalized snapshots."""
import json
import math
from pathlib import Path
import re
import ssl
import time
from urllib.parse import quote, urlsplit, urlunsplit
import httpx
import psutil
import websocket
from .models import Snapshot
from .access import validate_source
from .truenas import API_VERSION, TrueNASError, collect_session, close_truenas_sessions

LIMIT = 4 * 1024 * 1024


class CollectorError(Exception):
    pass


def number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def ratio(used, total):
    a, b = number(used), number(total)
    return a / b * 100 if a is not None and b and b > 0 else None


def json_get(client, url):
    with client.stream('GET', url, follow_redirects=False) as response:
        if response.status_code != 200:
            raise CollectorError(f'HTTP {response.status_code}')
        body = bytearray()
        deadline = time.monotonic() + 10
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > LIMIT or time.monotonic() > deadline:
                raise CollectorError('Antwort zu groß oder zu langsam')
        try:
            return json.loads(body)
        except (ValueError, UnicodeError):
            raise CollectorError('Ungültige JSON-Antwort') from None


def collect_http(source, client):
    base = source.url.rstrip('/')
    deadline = time.monotonic() + 20
    def get(url):
        if time.monotonic() >= deadline:
            raise CollectorError('Abfragezeitlimit erreicht')
        return json_get(client, url)
    snap = Snapshot(source_id=source.id, observed_at=time.time())
    if source.kind == 'docker':
        version = get(base + '/version')['ApiVersion']
        if not re.fullmatch(r'1\.\d{1,3}', version):
            raise CollectorError('Ungültige Docker-API-Version')
        base += '/v' + version
        containers = get(base + '/containers/json?all=true')
        if not isinstance(containers, list) or len(containers) > 2000:
            raise CollectorError('Ungültige Containerliste')
        for item in containers:
            ident = str(item['Id'])
            work = {'id':ident, 'name':(item.get('Names') or [ident])[0].lstrip('/'),
                    'state':item['State'], 'kind':'docker', 'health':None, 'restarts':None}
            # Bounded details: health/restart rules for larger fleets report unknown.
            if len(snap.workloads) < 50:
                detail = get(base + '/containers/' + quote(ident, safe='') + '/json')
                work.update(health=detail.get('State', {}).get('Health', {}).get('Status'),
                            restarts=number(detail.get('RestartCount')))
            if len(snap.workloads) < 10 and work['state']=='running':
                stats = get(base + '/containers/' + quote(ident,safe='') + '/stats?stream=false&one-shot=true')
                cpu,previous=stats.get('cpu_stats',{}),stats.get('precpu_stats',{})
                current_usage=number(cpu.get('cpu_usage',{}).get('total_usage'))
                old_usage=number(previous.get('cpu_usage',{}).get('total_usage'))
                system=number(cpu.get('system_cpu_usage'))
                old_system=number(previous.get('system_cpu_usage'))
                cores=number(cpu.get('online_cpus')) or len(cpu.get('cpu_usage',{}).get('percpu_usage',[]))
                work['cpu']=(current_usage-old_usage)/(system-old_system)*cores*100 if None not in (current_usage,old_usage,system,old_system) and system>old_system and current_usage>=old_usage and cores else None
                memory=stats.get('memory_stats',{})
                usage=number(memory.get('usage'))
                cache=number(memory.get('stats',{}).get('inactive_file')) or number(memory.get('stats',{}).get('cache')) or 0
                work['memory']=ratio(max(0,usage-cache) if usage is not None else None,memory.get('limit'))
            snap.workloads.append(work)
        snap.metrics['running'] = sum(w['state'] == 'running' for w in snap.workloads)
        snap.info['api_version'] = version
        snap.info['detail_scope'] = 'Health/Neustarts: erste 50 Container; CPU/RAM: erste 10 Container'
    elif source.kind == 'proxmox':
        data = get(base + '/api2/json/cluster/resources')['data']
        if not isinstance(data, list):
            raise CollectorError('Ungültige Proxmox-Ressourcen')
        for item in data:
            if item.get('type') not in ('qemu', 'lxc', 'node'):
                continue
            cpu = number(item.get('cpu'))
            snap.workloads.append({'id':str(item['id']), 'name':item.get('name') or item.get('node') or str(item['id']),
                                   'kind':item['type'], 'state':item.get('status'),
                                   'cpu':cpu * 100 if cpu is not None else None,
                                   'memory':ratio(item.get('mem'), item.get('maxmem'))})
        nodes = [w for w in snap.workloads if w['kind'] == 'node']
        if nodes:
            snap.metrics = {k:sum(w[k] for w in nodes if w[k] is not None) / len([w for w in nodes if w[k] is not None])
                            if any(w[k] is not None for w in nodes) else None for k in ('cpu','memory')}
    else:
        data = get(source.url)
        for metric, path in source.fields.items():
            value = data
            for part in path.split('.'):
                if isinstance(value, dict):
                    value = value.get(part)
                elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
                    value = value[int(part)]
                else:
                    value = None
                    break
            snap.metrics[metric] = number(value)
    return snap


def collect_truenas(source, peer, token):
    sequence = 0
    def rpc(method, params=None):
        nonlocal sequence
        sequence += 1
        peer.send(json.dumps({'jsonrpc':'2.0','id':sequence,'method':method,'params':params or []}))
        deadline = time.monotonic() + 10
        for _ in range(100):
            raw = peer.recv()
            if len(raw) > LIMIT or time.monotonic() > deadline:
                raise CollectorError('TrueNAS-Antwortlimit erreicht')
            data = json.loads(raw)
            if data.get('id') != sequence:
                continue
            if 'error' in data:
                raise CollectorError('TrueNAS verweigert ' + method)
            return data.get('result')
        raise CollectorError('TrueNAS-Antwort fehlt')
    if rpc('auth.login_with_api_key', [token]) is not True:
        raise CollectorError('TrueNAS-Anmeldung abgelehnt')
    version = rpc('system.version')
    if not re.search(r'(?:^|-)25\.10(?:\.|$)', str(version)):
        raise CollectorError('Dieser Adapter unterstützt TrueNAS SCALE 25.10')
    info = rpc('system.info')
    pools = rpc('pool.query')
    apps = rpc('app.query')
    snap = Snapshot(source_id=source.id, observed_at=time.time(), info={'version':version,'hostname':info.get('hostname')})
    for p in pools:
        snap.pools.append({'id':str(p['id']), 'name':p['name'], 'state':str(p.get('status','unknown')).lower(),
                           'used':number(p.get('allocated')), 'total':number(p.get('size')),
                           'percent':ratio(p.get('allocated'), p.get('size'))})
    for app in apps:
        snap.workloads.append({'id':str(app['id']), 'name':app.get('name', str(app['id'])),
                               'state':str(app.get('state','unknown')).lower(), 'kind':'truenas'})
    snap.metrics['running'] = sum(w['state'] == 'running' for w in snap.workloads)
    return snap


def local_snapshot(source):
    memory = psutil.virtual_memory()
    net = psutil.net_io_counters()
    temperatures = getattr(psutil, 'sensors_temperatures', lambda: {})()
    cpu_temps = [t.current for name, values in temperatures.items()
                 if any(k in name.lower() for k in ('coretemp','k10temp','cpu')) for t in values]
    return Snapshot(source_id=source.id, observed_at=time.time(), metrics={
        'cpu':psutil.cpu_percent(interval=0.2), 'memory':memory.percent,
        'temperature':max(cpu_temps) if cpu_temps else None,
        'memory_used':memory.used, 'memory_total':memory.total,
        'net_rx_bytes':net.bytes_recv, 'net_tx_bytes':net.bytes_sent,
        'uptime':time.time() - psutil.boot_time()}, info={'scope':'Laufzeitumgebung (im Container nicht automatisch der Host)'})


def read_secret(directory, name):
    if not name:
        return ''
    root = Path(directory).resolve()
    path = (root / name).resolve()
    if path.parent != root or not path.is_file() or path.stat().st_size > 16384:
        raise CollectorError('Secret-Datei fehlt oder ist unzulässig')
    return path.read_text(encoding='utf-8').strip()


def collect(source, secret_dir):
    try:
        try:
            validate_source(source)
        except ValueError as exc:
            raise CollectorError(str(exc)) from None
        if source.kind == 'local':
            return local_snapshot(source)
        token = read_secret(secret_dir, source.secret)
        context = ssl.create_default_context()
        if source.ca_file:
            root = Path(secret_dir).resolve()
            ca = (root / source.ca_file).resolve()
            if ca.parent != root:
                raise CollectorError('Ungültige CA-Datei')
            context.load_verify_locations(cafile=str(ca))
        if source.kind == 'truenas':
            u = urlsplit(source.url)
            endpoint = urlunsplit(('wss' if u.scheme == 'https' else 'ws', u.netloc, '/api/' + API_VERSION, '', ''))
            return collect_session(source, token, lambda: websocket.create_connection(
                endpoint, timeout=8, sslopt={'context':context}, redirect_limit=0))
        headers = {}
        if token:
            headers['Authorization'] = ('PVEAPIToken=' if source.kind == 'proxmox' else 'Bearer ') + token
        with httpx.Client(timeout=8, verify=context, headers=headers, trust_env=False) as client:
            return collect_http(source, client)
    except (CollectorError, TrueNASError) as exc:
        return Snapshot(source_id=source.id, ok=False, error=str(exc))
    except Exception as exc:
        # Exception messages can contain URLs, credentials, server bodies or headers.
        return Snapshot(source_id=source.id, ok=False, error='Abfrage fehlgeschlagen (' + type(exc).__name__ + ')')
