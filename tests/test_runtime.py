import time
import threading
from openscreen.models import Config, Source, Snapshot, Rule
from openscreen.runtime import Runtime
from openscreen.render import render


def test_slow_source_does_not_block_other_source(tmp_path,monkeypatch):
    release=threading.Event()
    def collector(source, directory):
        if source.id=='slow':
            release.wait(3)
        return Snapshot(source_id=source.id,observed_at=time.time(),metrics={'cpu':20})
    monkeypatch.setattr('openscreen.runtime.collect',collector)
    runtime=Runtime(tmp_path,tmp_path)
    runtime.save(Config(sources=[Source(id='slow',name='Slow'),Source(id='fast',name='Fast')]))
    runtime.start()
    try:
        for _ in range(30):
            if 'fast' in runtime.snapshots:
                break
            time.sleep(.05)
        assert 'fast' in runtime.snapshots
        assert 'slow' not in runtime.snapshots
    finally:
        release.set()
        runtime.close()


def test_failed_source_retains_values_but_never_reports_fresh(tmp_path):
    runtime=Runtime(tmp_path,tmp_path)
    runtime.snapshots['local']=Snapshot(source_id='local',observed_at=time.time()-100,metrics={'cpu':20})
    assert runtime.status()['sources'][0]['state']=='stale'


def test_every_lcd_page_and_warning_render_with_missing_values():
    config=Config()
    for page in ['system','storage','services','network']:
        assert render(config,{},[],page,time.time()).size==(960,376)
    rule=Rule(id='x',source_id='local',name='A'*80).model_dump()
    rule['state']='active'
    assert render(config,{},[rule],'system',time.time()).size==(960,376)
