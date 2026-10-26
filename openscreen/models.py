from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = str


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Source(Model):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    name: str = Field(min_length=1, max_length=80)
    kind: Literal['local', 'truenas', 'docker', 'proxmox', 'json'] = 'local'
    enabled: bool = True
    url: str = Field(default='', max_length=500)
    secret: str = Field(default='', pattern=r'^[a-zA-Z0-9_.-]{0,100}$')
    ca_file: str = Field(default='', pattern=r'^[a-zA-Z0-9_.-]{0,100}$')
    interval: int = Field(default=15, ge=5, le=3600)
    fields: dict[str, str] = Field(default_factory=dict, max_length=20)

    @field_validator('secret', 'ca_file')
    @classmethod
    def secret_name(cls, value):
        if value in ('.', '..'):
            raise ValueError('Use a secret filename')
        return value

    @model_validator(mode='after')
    def validate_url(self):
        if self.kind != 'local':
            parsed = urlsplit(self.url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValueError('Use an HTTP(S) URL without credentials or fragment')
            if self.secret and parsed.scheme != 'https':
                raise ValueError('Authentication requires HTTPS')
        return self


class Page(Model):
    id: Literal['system', 'storage', 'services', 'network']
    name: str = Field(min_length=1, max_length=40)
    enabled: bool = True
    source_id: str = ''
    metrics: list[Literal['cpu', 'memory', 'temperature', 'download', 'upload']] = Field(default_factory=lambda: ['cpu', 'memory', 'temperature'])


class Rule(Model):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    name: str = Field(min_length=1, max_length=80)
    source_id: str
    enabled: bool = True
    target: str = Field(default='', max_length=160)
    metric: str = Field(default='temperature', max_length=100)
    condition: Literal['gt', 'lt', 'not_running', 'unhealthy', 'restart_loop', 'pool_not_online'] = 'gt'
    threshold: float = 80
    delay: int = Field(default=60, ge=0, le=86400)
    severity: Literal['warning', 'critical'] = 'warning'
    display: Literal['fullscreen', 'icon', 'message'] = 'fullscreen'


class Config(Model):
    title: str = Field(default='AOOSTAR WTR MAX', min_length=1, max_length=80)
    rotation: int = Field(default=20, ge=10, le=3600)
    paused: bool = False
    selected_page: Literal['system', 'storage', 'services', 'network'] = 'system'
    hardware_enabled: bool = False
    device: str = Field(default='auto', min_length=1, max_length=250)
    sources: list[Source] = Field(default_factory=lambda: [Source(id='local', name='Lokale Laufzeit')], max_length=20)
    pages: list[Page] = Field(default_factory=lambda: [Page(id=i, name=n) for i, n in [('system','System'),('storage','Speicher'),('services','Dienste'),('network','Netzwerk')]], min_length=1, max_length=4)
    rules: list[Rule] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def consistent(self):
        for items in (self.sources, self.pages, self.rules):
            if len({item.id for item in items}) != len(items):
                raise ValueError('IDs must be unique')
        if not any(p.enabled for p in self.pages):
            raise ValueError('Enable at least one display page')
        ids = {s.id for s in self.sources}
        if any(r.source_id not in ids for r in self.rules) or any(p.source_id and p.source_id not in ids for p in self.pages):
            raise ValueError('Referenced source does not exist')
        return self


class Snapshot(Model):
    source_id: str
    observed_at: float = 0
    ok: bool = True
    error: str = ''
    metrics: dict[str, float | None] = Field(default_factory=dict)
    pools: list[dict] = Field(default_factory=list)
    workloads: list[dict] = Field(default_factory=list)
    info: dict = Field(default_factory=dict)
