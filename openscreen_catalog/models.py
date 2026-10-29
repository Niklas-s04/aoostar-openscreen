from typing import Literal
from pydantic import Field, model_validator
from openscreen.canvas_models import Model, Page


class Output(Model):
    kind: Literal['browser'] = 'browser'
    width: int = Field(default=960, ge=64, le=3840)
    height: int = Field(default=376, ge=64, le=3840)
    interval: float = Field(default=1, ge=0.5, le=60)

    @model_validator(mode='after')
    def pixels(self):
        if self.width * self.height > 8_294_400:
            raise ValueError('Output exceeds pixel budget')
        return self


def initial_pages():
    return [Page(id='welcome', name='Welcome', elements=[
        {'id': 'title', 'kind': 'text', 'text': 'OpenScreen Catalog',
         'x': 40, 'y': 30, 'width': 880, 'height': 100, 'font_size': 64},
        {'id': 'clock', 'kind': 'clock', 'text': '', 'x': 40, 'y': 150,
         'width': 880, 'height': 160, 'font_size': 96},
    ])]


class Config(Model):
    schema_version: Literal[1] = 1
    distribution: Literal['catalog'] = 'catalog'
    title: str = Field(default='OpenScreen Catalog', min_length=1, max_length=80)
    rotation: int = Field(default=20, ge=10, le=3600)
    paused: bool = False
    selected_page: str = Field(default='welcome', max_length=64)
    output: Output = Field(default_factory=Output)
    sources: list[dict] = Field(default_factory=list, max_length=0)
    rules: list[dict] = Field(default_factory=list, max_length=0)
    pages: list[Page] = Field(default_factory=initial_pages, min_length=1, max_length=20)

    @model_validator(mode='after')
    def consistent(self):
        if len({p.id for p in self.pages}) != len(self.pages):
            raise ValueError('Page IDs must be unique')
        enabled = [p.id for p in self.pages if p.enabled]
        if not enabled:
            raise ValueError('Enable at least one page')
        if any(p.source_id or any(e.binding.source_id for e in p.elements) for p in self.pages):
            raise ValueError('This distribution has no telemetry sources')
        if self.selected_page not in enabled:
            self.selected_page = enabled[0]
        return self
