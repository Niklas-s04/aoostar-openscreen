from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = str


from .canvas_models import Model, Binding, Element, Page, Rule, PlayerReport, Snapshot


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


class Output(Model):
    kind: Literal['aoostar','browser','broker'] = 'aoostar'
    adapter_id: str = Field(default='', pattern=r'^[a-z0-9_-]{0,64}$')
    mode_id: str = Field(default='', max_length=64)
    pixel_format: str = Field(default='', max_length=32)
    width: int = Field(default=960, ge=64, le=3840)
    height: int = Field(default=376, ge=64, le=3840)
    rotation: Literal[0,90,180,270] = 0
    fit: Literal['contain','cover','stretch'] = 'contain'
    interval: float = Field(default=1, ge=0.5, le=60)
    auto_size: bool = True
    player_id: str = Field(default='', pattern=r'^(|[a-f0-9]{32})$')

    @model_validator(mode='after')
    def capabilities(self):
        if self.width*self.height>8_294_400:
            raise ValueError('Output exceeds 8.3 million pixels')
        if not self.adapter_id:
            self.adapter_id = 'browser' if self.kind=='browser' else 'aoostar'
        if self.kind!='broker':
            from .adapters import ADAPTERS
            if self.adapter_id != self.kind:
                if self.adapter_id not in ('aoostar','browser'):
                    raise ValueError('Adapter does not match output transport')
                # Older API clients change only kind on the returned config.
                self.adapter_id, self.mode_id, self.pixel_format = self.kind, '', ''
            caps = ADAPTERS.get(self.adapter_id).get_capabilities(width=self.width,height=self.height)
            caps.select(self.width,self.height,self.mode_id,self.pixel_format,self.rotation)
        return self


class Config(Model):
    schema_version: Literal[2] = 2
    title: str = Field(default='AOOSTAR WTR MAX', min_length=1, max_length=80)
    rotation: int = Field(default=20, ge=10, le=3600)
    paused: bool = False
    selected_page: str = Field(default='system', max_length=64)
    hardware_enabled: bool = False
    output: Output = Field(default_factory=Output)
    device: str = Field(default='auto', min_length=1, max_length=250)
    sources: list[Source] = Field(default_factory=lambda: [Source(id='local', name='Lokale Laufzeit')], max_length=20)
    pages: list[Page] = Field(default_factory=lambda: [Page(id='system', name='System')], min_length=1, max_length=20)
    rules: list[Rule] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def consistent(self):
        for items in (self.sources, self.pages, self.rules):
            if len({item.id for item in items}) != len(items):
                raise ValueError('IDs must be unique')
        if not any(p.enabled for p in self.pages):
            raise ValueError('Enable at least one display page')
        if sum(e.kind == 'chart' for p in self.pages for e in p.elements)>128:
            raise ValueError('At most 128 charts across all pages')
        ids = {s.id for s in self.sources}
        if any(r.source_id not in ids for r in self.rules) or any(p.source_id and p.source_id not in ids for p in self.pages):
            raise ValueError('Referenced source does not exist')
        if any(e.binding.source_id and e.binding.source_id not in ids for p in self.pages for e in p.elements):
            raise ValueError('Element source does not exist')
        if sum(s.enabled for s in self.sources)>1 and any(
            e.kind=='chart' and e.binding.collection!='metrics' and e.binding.target=='*'
            and not (e.binding.source_id or p.source_id) for p in self.pages for e in p.elements
        ):
            raise ValueError('Select an explicit source for aggregate charts when multiple sources are enabled')
        if self.selected_page not in {p.id for p in self.pages if p.enabled}:
            self.selected_page = next(p.id for p in self.pages if p.enabled)
        return self
