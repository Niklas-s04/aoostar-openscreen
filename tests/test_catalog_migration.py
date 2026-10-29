import json
import pytest
from scripts.migrate_catalog_canvas import migrate
from openscreen.models import Config as FullConfig


def test_migration_never_rewrites_full_data(tmp_path):
    source = tmp_path / 'full'
    source.mkdir()
    data = FullConfig().model_dump_json()
    (source/'config.json').write_text(data, encoding='utf-8')
    result = migrate(source, tmp_path/'catalog')
    assert result.distribution == 'catalog' and not result.sources
    assert (source/'config.json').read_text(encoding='utf-8') == data
    assert json.loads((tmp_path/'catalog/config.json').read_text(encoding='utf-8'))['distribution'] == 'catalog'
    with pytest.raises(ValueError):
        migrate(source, tmp_path/'catalog')
    with pytest.raises(ValueError):
        migrate(source, source/'nested')
