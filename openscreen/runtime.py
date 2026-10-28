from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading
import time
from .alerts import AlertEngine
from .collectors import collect, close_truenas_sessions
from .models import Config, Snapshot
from .render import render, bound_value
from .access import validate_config
from .assets import AssetStore
from .outputs import prepare_frame, open_transport
from .discovery import PlayerRegistry, inspect_output
from .display_trial import DisplayTrial, test_pattern
import copy


class Runtime:
    def __init__(self, data_dir, secret_dir, demo=False):
        self.path = Path(data_dir)/'config.json'
        self.secret_dir = secret_dir
        self.demo = demo
        self.lock = threading.RLock()
        self.players = PlayerRegistry()
        self.config = Config.model_validate_json(self.path.read_text(encoding='utf-8')) if self.path.exists() else Config()
        if not demo:
            validate_config(self.config,existing_device=self.config.device)
        self.snapshots = {}
        self.history = {}
        self.assets = AssetStore(Path(data_dir)/'assets')
        self.render_lock = threading.Lock()
        self.engine = AlertEngine()
        self.stop = threading.Event()
        self.display = {'state':'disabled','last_sent':None,'error':'','frame_seconds':None}
        self.started = time.time()
        self.threads = []
        self.trial = None
        self.visible_page = None
        self.visible_since = None
        self.page_signature = None

    def active_trial(self):
        with self.lock:
            if self.trial and self.trial.expired:
                self.trial = None
            return self.trial

    def effective_config(self):
        with self.lock:
            trial = self.active_trial()
            return (trial.config if trial else self.config).model_copy(deep=True)

    def begin_trial(self, config):
        config = config.model_copy(deep=True)
        with self.lock:
            if self.active_trial():
                raise ValueError('Ein Displaytest läuft bereits')
            if self.demo and config.hardware_enabled:
                raise ValueError('Hardware ist im Demo-Modus deaktiviert')
            if config.output.kind != 'browser' and not config.hardware_enabled:
                raise ValueError('Hardwareausgabe für den Displaytest aktivieren')
            if not self.demo:
                validate_config(config, existing_device=self.config.device)
            result = inspect_output(config, self.players, existing_device=self.config.device)
            if not result['ok']:
                raise ValueError(result['message'])
            config.output = type(config.output).model_validate(result['output'])
            self.trial = DisplayTrial(config)
            return self.trial.status()

    def finish_trial(self, trial_id, confirm=False):
        with self.lock:
            trial = self.active_trial()
            if not trial or trial.id != trial_id:
                raise ValueError('Displaytest ist abgelaufen oder nicht mehr aktiv')
            if confirm and not trial.sent:
                raise ValueError('Testbild wurde noch nicht ausgegeben')
            self.trial = None
            if confirm:
                try:
                    self.save(trial.config, _resolved_output=True)
                except Exception:
                    self.trial = trial
                    raise
            return {'ok': True, 'saved': confirm}

    def save(self, config, *, _resolved_output=False):
        config=config.model_copy(deep=True)
        if not self.demo:
            validate_config(config,existing_device=self.config.device)
        if self.demo and config.hardware_enabled:
            raise ValueError('Hardware ist im Demo-Modus deaktiviert')
        with self.lock:
            if self.active_trial():
                raise ValueError('Displaytest zuerst bestätigen oder abbrechen')
            output_changed=(config.output!=self.config.output or config.device!=self.config.device
                            or config.hardware_enabled!=self.config.hardware_enabled)
            # Confirmation persists the exact output that produced the test image.
            # Resolving auto-size again could silently save a newly resized player.
            if output_changed and not _resolved_output:
                result=inspect_output(config,self.players,existing_device=self.config.device)
                if not self.demo and config.hardware_enabled and config.output.kind in ('aoostar','broker') and not result['ok']:
                    raise ValueError(result['message'])
                config.output=type(config.output).model_validate(result['output'])
            for page in config.pages:
                for element in page.elements:
                    if element.asset_id:
                        self.assets.get_path(element.asset_id)
            self.path.parent.mkdir(parents=True,exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            with temporary.open('w',encoding='utf-8') as handle:
                handle.write(config.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary,self.path)
            changed = {s.id for s in config.sources if next((o for o in self.config.sources if o.id==s.id),None)!=s}
            self.snapshots = {k:v for k,v in self.snapshots.items() if k not in changed and any(s.id==k for s in config.sources)}
            self.history = {k:v for k,v in self.history.items() if k in self.snapshots}
            self.config = config.model_copy(deep=True)
            close_truenas_sessions({s.id for s in config.sources if s.enabled and s.kind=='truenas'})

    def page(self, config, now):
        pages=[p.id for p in config.pages if p.enabled]
        if config.paused and config.selected_page in pages:
            return config.selected_page
        if config.hardware_enabled and config.output.kind != 'browser' and not self.demo:
            with self.lock:
                signature = (tuple(pages), config.rotation, config.device, config.output.model_dump_json())
                if signature != self.page_signature:
                    self.page_signature, self.visible_page, self.visible_since = signature, pages[0], None
                if self.visible_since is not None and now-self.visible_since >= config.rotation:
                    return pages[(pages.index(self.visible_page)+1)%len(pages)]
                return self.visible_page
        return pages[int((now-self.started)//config.rotation)%len(pages)]

    def state(self):
        with self.lock:
            config=self.config.model_copy(deep=True)
            snapshots={k:v.model_copy(deep=True) for k,v in self.snapshots.items()}
            now=time.time()
            if self.demo:
                for s in config.sources:
                    if s.enabled:
                        snapshots[s.id]=Snapshot(source_id=s.id,observed_at=now,
                            metrics={'cpu':28,'memory':64,'temperature':52,'download':184_000_000,'upload':32_000_000},
                            pools=[{'id':'tank','name':'Tank-Data','state':'online','percent':68.1,'used':21.8e12,'total':32e12},
                                   {'id':'nvme','name':'NVME-Fast','state':'online','percent':40.3,'used':742e9,'total':1840e9}],
                            workloads=[{'id':'jellyfin','name':'Jellyfin','state':'running','kind':s.kind,'health':'healthy','restarts':0}],info={'scope':'Demodaten'})
            alerts=self.engine.evaluate(config,snapshots,now)
            return config,snapshots,alerts,now

    def status(self):
        config,snapshots,alerts,now=self.state()
        sources=[]
        for s in config.sources:
            snap=snapshots.get(s.id)
            state='disabled' if not s.enabled else 'waiting' if not snap else 'error' if not snap.ok else 'stale' if now-snap.observed_at>s.interval*2 else 'ok'
            sources.append({'id':s.id,'name':s.name,'kind':s.kind,'state':state,'snapshot':snap.model_dump() if snap else None})
        with self.lock:
            display=dict(self.display)
        if config.output.kind == 'browser':
            display.update(state='player',error='')
        trial = self.active_trial()
        return {'demo':self.demo,'page':self.page(config,now),'sources':sources,'alerts':alerts,'display':display,'trial':trial.status() if trial else None,'uptime':now-self.started,'now':now,'version':'1.0.0'}

    def image(self, page=None, draft=None, output_config=None):
        config,snapshots,alerts,now=self.state()
        trial = self.active_trial()
        if draft is None and trial and (output_config is None or output_config == trial.config):
            return test_pattern(trial.config.output)
        if output_config is not None:
            config = output_config
        if draft is not None:
            draft = draft.model_copy(update={'enabled':True})
            config = Config.model_validate(config.model_copy(update={'pages':[draft], 'selected_page':draft.id}).model_dump())
            alerts = []
            page = draft.id
        with self.lock:
            history = copy.deepcopy(self.history)
        with self.render_lock:
            image = render(config,snapshots,alerts,page or self.page(config,now),now,self.demo,history=history,assets=self.assets)
            return image if draft is not None else prepare_frame(image,config.output)

    def record_history(self, source_id, snapshot, now):
        series = self.history.setdefault(source_id, {})
        values = {key: snapshot.metrics.get(key) for key in list(snapshot.metrics)[:32]}
        for page in self.config.pages:
            for element in page.elements:
                binding = element.binding
                if element.kind != 'chart' or (binding.source_id or page.source_id) not in ('',source_id):
                    continue
                key = binding.metric if binding.collection == 'metrics' else f'{binding.collection}:{binding.target}:{binding.metric}'
                values[key] = bound_value(binding.model_copy(update={'scale':1}), [snapshot])
        for key in list(series):
            if key not in values:
                del series[key]
        interval = next((s.interval for s in self.config.sources if s.id==source_id),15)
        for key, value in values.items():
            points = series.setdefault(key, [])
            if points and now-points[-1][0]>interval*2:
                points.append([now-0.001,None])
            points.append([now, value if snapshot.ok and isinstance(value,(int,float)) else None])
            del points[:-120]

    def poll(self):
        futures={}
        due={}
        with ThreadPoolExecutor(max_workers=20,thread_name_prefix='source') as executor:
            while not self.stop.is_set():
                with self.lock:
                    sources=list(self.config.sources)
                for source in sources:
                    if not source.enabled:
                        continue
                    pair=futures.get(source.id)
                    if pair and pair[0].done():
                        future, original=pair
                        result=future.result()
                        with self.lock:
                            if source==original and source in self.config.sources:
                                previous=self.snapshots.get(source.id)
                                if result.ok and previous and previous.ok:
                                    dt=result.observed_at-previous.observed_at
                                    for key,counter in [('download','net_rx_bytes'),('upload','net_tx_bytes')]:
                                        a,b=result.metrics.get(counter),previous.metrics.get(counter)
                                        if a is not None and b is not None and a>=b and dt>0:
                                            result.metrics[key]=(a-b)/dt
                                if not result.ok and previous:
                                    result=previous.model_copy(update={'ok':False,'error':result.error})
                                self.snapshots[source.id]=result
                                self.record_history(source.id, result, time.time())
                        due[source.id]=time.monotonic()+source.interval
                        del futures[source.id]
                    if source.id not in futures and time.monotonic()>=due.get(source.id,0):
                        futures[source.id]=(executor.submit(collect,source,self.secret_dir),source.model_copy(deep=True))
                self.stop.wait(0.25)

    def output(self):
        transport=None
        transport_kind=None
        transport_output=None
        previous=None
        while not self.stop.is_set():
            config=self.effective_config()
            if not config.hardware_enabled or self.demo or config.output.kind not in ('aoostar','broker'):
                if transport:
                    transport.close()
                    transport=None
                previous=None
                with self.lock:
                    self.display['state']='disabled'
                self.stop.wait(0.5)
                continue
            try:
                if (transport is None or transport.device!=config.device or transport_kind!=config.output.kind
                        or transport_output!=config.output):
                    if transport:
                        transport.close()
                    transport=open_transport(config.output, config.device)
                    transport_kind=config.output.kind
                    transport_output=config.output.model_copy(deep=True)
                    previous=None
                with self.lock:
                    page_id=self.page(config,time.time())
                    trial=self.active_trial()
                    if trial and trial.config != config:
                        trial=None
                    image=self.image(page_id,output_config=config)
                frame=image.tobytes()
                if frame!=previous or (hasattr(transport,'needs_refresh') and transport.needs_refresh()):
                    with self.lock:
                        self.display['state']='sending'
                    start=time.monotonic()
                    transport.send(image)
                    previous=frame
                    with self.lock:
                        self.display.update(state='connected',last_sent=time.time(),error='',frame_seconds=round(time.monotonic()-start,2))
                with self.lock:
                    if trial and self.active_trial() is trial:
                        trial.sent = True
                    if not trial and self.effective_config() == config:
                        if self.visible_page != page_id or self.visible_since is None:
                            self.visible_page, self.visible_since = page_id, time.time()
            except Exception as exc:
                if transport:
                    transport.close()
                    transport=None
                previous=None
                with self.lock:
                    self.display.update(state='error',error='Displayverbindung fehlgeschlagen ('+type(exc).__name__+')')
                self.stop.wait(3)
            self.stop.wait(config.output.interval)
        if transport:
            transport.close()

    def start(self):
        for target in ([self.output] if self.demo else [self.poll,self.output]):
            t=threading.Thread(target=target,daemon=True)
            t.start()
            self.threads.append(t)

    def close(self):
        self.stop.set()
        close_truenas_sessions()
        for t in self.threads:
            t.join(timeout=12)
        close_truenas_sessions()
