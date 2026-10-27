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


class Binding(Model):
    source_id: str = Field(default='', max_length=64)
    collection: Literal['metrics', 'pools', 'workloads'] = 'metrics'
    metric: str = Field(default='cpu', max_length=100)
    target: str = Field(default='', max_length=160)
    scale: float = Field(default=1, ge=-1e12, le=1e12)
    precision: int = Field(default=0, ge=0, le=4)
    unit: str = Field(default='', max_length=24)


class Element(Model):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    kind: Literal['text','metric','icon','bar','ring','chart','shape','clock','image'] = 'text'
    x: int = Field(default=0, ge=0, le=3839)
    y: int = Field(default=0, ge=0, le=3839)
    width: int = Field(default=240, ge=1, le=3840)
    height: int = Field(default=100, ge=1, le=3840)
    visible: bool = True
    locked: bool = False
    text: str = Field(default='Text', max_length=1000)
    label: str = Field(default='', max_length=100)
    font: Literal['sans','sans-condensed','serif','mono','liberation-sans','liberation-serif','liberation-mono'] = 'sans'
    font_size: int = Field(default=48, ge=8, le=240)
    label_size: int = Field(default=28, ge=8, le=80)
    bold: bool = False
    italic: bool = False
    color: str = Field(default='#ffffff', pattern=r'^#[0-9a-fA-F]{6}$')
    background: str = Field(default='', pattern=r'^(|#[0-9a-fA-F]{6})$')
    align: Literal['left','center','right'] = 'left'
    vertical: Literal['top','center','bottom'] = 'center'
    binding: Binding = Field(default_factory=Binding)
    min_value: float = 0
    max_value: float = 100
    show_value: bool = True
    show_label: bool = True
    stroke_width: int = Field(default=4, ge=1, le=80)
    radius: int = Field(default=12, ge=0, le=200)
    shape: Literal['rect','rounded','ellipse','line'] = 'rounded'
    symbol: str = Field(default='cpu', max_length=40)
    chart_style: Literal['line','bar'] = 'line'
    asset_id: str = Field(default='', pattern=r'^(|[a-f0-9]{32})$')
    fit: Literal['contain','cover','stretch'] = 'contain'
    animation_speed: float = Field(default=1, ge=0.1, le=10)
    time_format: Literal['time','time12','date','datetime'] = 'time'
    timezone: str = Field(default='UTC', max_length=80)

    @model_validator(mode='after')
    def valid_element(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        if self.max_value <= self.min_value:
            raise ValueError('Maximum must exceed minimum')
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Unknown timezone') from None
        return self


class Page(Model):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    name: str = Field(min_length=1, max_length=40)
    enabled: bool = True
    width: int = Field(default=960, ge=64, le=3840)
    height: int = Field(default=376, ge=64, le=3840)
    source_id: str = ''
    metrics: list[Literal['cpu', 'memory', 'temperature', 'download', 'upload']] = Field(default_factory=lambda: ['cpu', 'memory', 'temperature'])
    background: str = Field(default='#101012', pattern=r'^#[0-9a-fA-F]{6}$')
    elements: list[Element] = Field(default_factory=list, max_length=48)

    @model_validator(mode='before')
    @classmethod
    def migrate(cls, value):
        if isinstance(value, dict) and 'elements' not in value:
            from .templates import template_page
            value = dict(value)
            value['elements'] = template_page(value.get('id', 'system'))['elements']
            if value.get('id') == 'system' and 'metrics' in value:
                choices = value['metrics'][:3]
                value['elements'] = value['elements'][:len(choices)]
                for element, metric in zip(value['elements'], choices):
                    element['binding']['metric'] = metric
                    element['binding']['unit'] = '°C' if metric == 'temperature' else 'MB/s' if metric in ('download','upload') else '%'
                    element['binding']['scale'] = 0.000001 if metric in ('download','upload') else 1
                    element['label'] = metric.upper()
            for element in value['elements']:
                if 'binding' in element:
                    element['binding']['source_id'] = value.get('source_id', '')
        return value

    @model_validator(mode='after')
    def valid_elements(self):
        if len({e.id for e in self.elements}) != len(self.elements):
            raise ValueError('Element IDs must be unique within a page')
        if self.width*self.height > 8_294_400:
            raise ValueError('Canvas exceeds 8.3 million pixels')
        if any(e.x + e.width > self.width or e.y + e.height > self.height for e in self.elements):
            raise ValueError('Element exceeds canvas bounds')
        return self


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


class PlayerReport(Model):
    id: str = Field(pattern=r'^[a-f0-9]{32}$')
    width: int = Field(ge=64,le=3840)
    height: int = Field(ge=64,le=3840)

    @model_validator(mode='after')
    def bounded_pixels(self):
        if self.width*self.height>8_294_400:
            raise ValueError('Player resolution exceeds pixel budget')
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


class Snapshot(Model):
    source_id: str
    observed_at: float = 0
    ok: bool = True
    error: str = ''
    metrics: dict[str, float | None] = Field(default_factory=dict)
    pools: list[dict] = Field(default_factory=list)
    workloads: list[dict] = Field(default_factory=list)
    info: dict = Field(default_factory=dict)
