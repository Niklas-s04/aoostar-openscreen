from openscreen.collectors import collect
from openscreen.models import Source


def test_unapproved_target_never_reads_secret_or_opens_network(monkeypatch):
    monkeypatch.delenv('OPENSCREEN_ALLOWED_SOURCE_URLS', raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError('must be blocked before secret or network access')
    monkeypatch.setattr('openscreen.collectors.read_secret', forbidden)
    monkeypatch.setattr('openscreen.collectors.httpx.Client', forbidden)
    source = Source(id='x', name='x', kind='json', url='https://example.test', secret='token')
    result = collect(source, '/run/secrets')
    assert not result.ok
    assert 'nicht in OPENSCREEN_ALLOWED_SOURCE_URLS' in result.error


def test_source_allowlist_matches_exact_url(monkeypatch):
    from openscreen.access import validate_source
    import pytest
    monkeypatch.setenv('OPENSCREEN_ALLOWED_SOURCE_URLS', 'https://nas.example')
    validate_source(Source(id='x',name='x',kind='truenas',url='https://nas.example'))
    for url in ['https://nas.example.evil.test', 'https://nas.example:444', 'https://nas.example/other']:
        with pytest.raises(ValueError):
            validate_source(Source(id='x',name='x',kind='json',url=url))
