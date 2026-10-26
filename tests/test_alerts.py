import pytest
from pydantic import ValidationError
from openscreen.models import Config, Source, Rule, Snapshot
from openscreen.alerts import AlertEngine


def test_alert_delay_recovery_and_stale_data():
    engine = AlertEngine()
    rule = Rule(id='heat', name='Hitze', source_id='local', metric='temperature', condition='gt', threshold=80, delay=10)
    config = Config(rules=[rule])
    def evaluate(value, now, ok=True):
        snap = Snapshot(source_id='local', observed_at=now, ok=ok, metrics={'temperature': value})
        return engine.evaluate(config, {'local': snap}, now)
    assert evaluate(90, 100)[0]['state'] == 'pending'
    assert evaluate(90, 110)[0]['state'] == 'active'
    assert evaluate(0, 111, False)[0]['state'] == 'unknown'
    assert evaluate(60, 112)[0]['state'] == 'ok'


def test_unknown_time_does_not_satisfy_delay():
    engine = AlertEngine()
    config = Config(rules=[Rule(id='x', name='offline', source_id='local', metric='cpu', condition='gt', threshold=80, delay=10)])
    assert engine.evaluate(config, {'local': Snapshot(source_id='local', observed_at=10, metrics={'cpu': 90})}, 10)[0]['state'] == 'pending'
    engine.evaluate(config, {}, 11)
    assert engine.evaluate(config, {'local': Snapshot(source_id='local', observed_at=100, metrics={'cpu': 90})}, 100)[0]['state'] == 'pending'


def test_restart_rate_uses_counter_delta_not_lifetime_count():
    engine = AlertEngine()
    config = Config(rules=[Rule(id='x', name='Loop', source_id='local', target='jellyfin', condition='restart_loop', threshold=3, delay=0)])
    def check(now, count):
        return engine.evaluate(config, {'local': Snapshot(source_id='local', observed_at=now, workloads=[{'id':'jellyfin','name':'jellyfin','restarts':count,'state':'running'}])}, now)[0]['state']
    assert check(100, 20) == 'ok'
    assert check(110, 24) == 'active'
    assert check(180, 24) == 'ok'


def test_config_rejects_duplicate_ids_secret_paths_and_empty_pages():
    with pytest.raises(ValidationError):
        Config(sources=[Source(id='a', name='A'), Source(id='a', name='B')])
    with pytest.raises(ValidationError):
        Source(id='x', name='X', secret='../../key')
    with pytest.raises(ValidationError):
        Config(pages=[])


def test_unknown_workload_state_is_not_an_offline_alarm():
    config=Config(rules=[Rule(id='x',name='Service',source_id='local',condition='not_running',delay=0)])
    result=AlertEngine().evaluate(config,{'local':Snapshot(source_id='local',observed_at=1,workloads=[{'id':'x','state':'unknown'}])},1)
    assert result[0]['state']=='unknown'
