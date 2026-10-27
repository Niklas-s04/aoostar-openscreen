import pytest
from pydantic import ValidationError
from openscreen.models import Config, Page, Element


def test_one_readable_start_page_and_legacy_migration():
    config = Config()
    assert len(config.pages) == 1
    assert config.schema_version == 2
    assert any(e.kind == 'metric' and e.font_size >= 96 for e in config.pages[0].elements)
    old = {'hardware_enabled':True, 'device':'/dev/aoostar', 'pages':[
        {'id':i,'name':i,'metrics':['cpu','memory'],'source_id':'local'}
        for i in ['system','storage','services','network']]}
    migrated = Config.model_validate(old)
    assert len(migrated.pages) == 4 and all(p.elements for p in migrated.pages)
    assert migrated.hardware_enabled and migrated.device == '/dev/aoostar'
    assert Config.model_validate_json(migrated.model_dump_json()) == migrated
    assert [e.binding.metric for e in migrated.pages[0].elements]==['cpu','memory']


def test_custom_pages_bounds_and_bindings():
    p = Page(id='my_page', name='Custom', elements=[])
    assert Config(pages=[p]).pages[0].id == 'my_page'
    with pytest.raises(ValidationError):
        Page(id='x',name='X',elements=[Element(id='a',x=950,width=100)])
    with pytest.raises(ValidationError):
        Page(id='x',name='X',elements=[Element(id='a'),Element(id='a')])
    with pytest.raises(ValidationError):
        Config(pages=[Page(id='x',name='X',elements=[Element(id='a',binding={'source_id':'absent'})])])
    with pytest.raises(ValidationError):
        Element(id='a',kind='bar',min_value=10,max_value=5)
    with pytest.raises(ValidationError):
        Element(id='a',asset_id='../secret')


def test_aggregate_chart_requires_unambiguous_source():
    from openscreen.models import Source
    page=Page(id='p',name='P',elements=[Element(id='chart',kind='chart',
        binding={'collection':'pools','target':'*','metric':'percent'})])
    sources=[Source(id='one',name='One'),Source(id='two',name='Two')]
    with pytest.raises(ValidationError,match='explicit source'):
        Config(pages=[page],sources=sources)
    page.elements[0].binding.source_id='one'
    assert Config(pages=[page],sources=sources)
