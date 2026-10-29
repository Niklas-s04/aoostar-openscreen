from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


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


class PlayerReport(Model):
    id: str = Field(pattern=r'^[a-f0-9]{32}$')
    width: int = Field(ge=64,le=3840)
    height: int = Field(ge=64,le=3840)

    @model_validator(mode='after')
    def bounded_pixels(self):
        if self.width*self.height>8_294_400:
            raise ValueError('Player resolution exceeds pixel budget')
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
