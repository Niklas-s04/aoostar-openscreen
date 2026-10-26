from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading
import time
from .alerts import AlertEngine
from .collectors import collect
from .models import Config, Snapshot
from .protocol import DisplayTransport
from .render import render
from .access import validate_config


class Runtime:
    def __init__(self, data_dir, secret_dir, demo=False):
        self.path = Path(data_dir)/'config.json'
        self.secret_dir = secret_dir
        self.demo = demo
        self.lock = threading.RLock()
        self.config = Config.model_validate_json(self.path.read_text(encoding='utf-8')) if self.path.exists() else Config()
        if not demo:
            validate_config(self.config)
        self.snapshots = {}
        self.engine = AlertEngine()
        self.stop = threading.Event()
        self.display = {'state':'disabled','last_sent':None,'error':'','frame_seconds':None}
        self.started = time.time()
        self.threads = []

    def save(self, config):
        if not self.demo:
            validate_config(config)
        if self.demo and config.hardware_enabled:
            raise ValueError('Hardware ist im Demo-Modus deaktiviert')
        with self.lock:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            with temporary.open('w',encoding='utf-8') as handle:
                handle.write(config.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary,self.path)
            changed = {s.id for s in config.sources if next((o for o in self.config.sources if o.id==s.id),None)!=s}
            self.snapshots = {k:v for k,v in self.snapshots.items() if k not in changed and any(s.id==k for s in config.sources)}
            self.config = config.model_copy(deep=True)

    def page(self, config, now):
        pages=[p.id for p in config.pages if p.enabled]
        if config.paused and config.selected_page in pages:
            return config.selected_page
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
        return {'demo':self.demo,'page':self.page(config,now),'sources':sources,'alerts':alerts,'display':display,'uptime':now-self.started,'now':now,'version':'0.1.0'}

    def image(self, page=None):
        config,snapshots,alerts,now=self.state()
        return render(config,snapshots,alerts,page or self.page(config,now),now,self.demo)

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
                        due[source.id]=time.monotonic()+source.interval
                        del futures[source.id]
                    if source.id not in futures and time.monotonic()>=due.get(source.id,0):
                        futures[source.id]=(executor.submit(collect,source,self.secret_dir),source.model_copy(deep=True))
                self.stop.wait(0.25)

    def output(self):
        transport=None
        previous=None
        while not self.stop.is_set():
            with self.lock:
                config=self.config.model_copy(deep=True)
            if not config.hardware_enabled or self.demo:
                if transport:
                    transport.close()
                    transport=None
                previous=None
                with self.lock:
                    self.display['state']='disabled'
                self.stop.wait(0.5)
                continue
            try:
                if transport is None or transport.device!=config.device:
                    if transport:
                        transport.close()
                    transport=DisplayTransport(config.device)
                    previous=None
                image=self.image()
                frame=image.tobytes()
                if frame!=previous:
                    with self.lock:
                        self.display['state']='sending'
                    start=time.monotonic()
                    transport.send(image)
                    previous=frame
                    with self.lock:
                        self.display.update(state='connected',last_sent=time.time(),error='',frame_seconds=round(time.monotonic()-start,2))
            except Exception as exc:
                if transport:
                    transport.close()
                    transport=None
                previous=None
                with self.lock:
                    self.display.update(state='error',error='Displayverbindung fehlgeschlagen ('+type(exc).__name__+')')
                self.stop.wait(3)
            self.stop.wait(0.5)
        if transport:
            transport.close()

    def start(self):
        for target in ([self.output] if self.demo else [self.poll,self.output]):
            t=threading.Thread(target=target,daemon=True)
            t.start()
            self.threads.append(t)

    def close(self):
        self.stop.set()
        for t in self.threads:
            t.join(timeout=12)
