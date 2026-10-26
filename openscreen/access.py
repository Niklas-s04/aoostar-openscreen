"""Operator-owned boundaries for the passwordless, local-only service."""
import ipaddress
import os
from urllib.parse import urlsplit


def values(name, default=''):
    return tuple(v.strip() for v in os.getenv(name, default).split(',') if v.strip())


class AccessPolicy:
    def __init__(self):
        self.networks = tuple(ipaddress.ip_network(v) for v in values(
            'OPENSCREEN_ALLOWED_NETWORKS', '127.0.0.0/8,::1/128'))
        private = tuple(ipaddress.ip_network(v) for v in (
            '127.0.0.0/8', '::1/128', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7'))
        if not self.networks or any(not any(n.version == p.version and n.subnet_of(p)
                                            for p in private) for n in self.networks):
            raise ValueError('Only explicit local/private networks may access OpenScreen')
        self.hosts = values('OPENSCREEN_ALLOWED_HOSTS', 'localhost,127.0.0.1,::1')
        if not self.hosts or any('*' in h or '/' in h for h in self.hosts):
            raise ValueError('Explicit allowed hostnames or IPs are required')

    def permits(self, peer, host):
        try:
            address = ipaddress.ip_address(peer)
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
            return host in self.hosts and any(address in network for network in self.networks)
        except ValueError:
            return False


def validate_source(source):
    if source.kind != 'local' and source.url not in values('OPENSCREEN_ALLOWED_SOURCE_URLS'):
        raise ValueError('Datenquellen-URL ist nicht in OPENSCREEN_ALLOWED_SOURCE_URLS freigegeben')


def validate_config(config):
    if config.device not in ('auto', '/dev/aoostar'):
        raise ValueError('Als Gerät sind nur auto und /dev/aoostar erlaubt')
    for source in config.sources:
        validate_source(source)


def same_origin(origin, request_url):
    try:
        a, b = urlsplit(origin), urlsplit(str(request_url))
        def key(u):
            return u.scheme, u.hostname, u.port or (443 if u.scheme == 'https' else 80)
        return a.scheme in ('http', 'https') and not a.username and not a.password and key(a) == key(b)
    except ValueError:
        return False
