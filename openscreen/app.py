from contextlib import asynccontextmanager
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from .alerts import AlertEngine
from .collectors import collect
from .models import Config
from .render import png
from .runtime import Runtime
from .access import AccessPolicy, same_origin

STATIC=Path(__file__).parent/'static'


def create_app(data_dir=None, secret_dir=None, demo=None, start_workers=True):
    demo = os.getenv('OPENSCREEN_DEMO','0')=='1' if demo is None else demo
    secret_dir=secret_dir or os.getenv('OPENSCREEN_SECRETS','/run/secrets')
    policy = AccessPolicy()
    runtime=Runtime(data_dir or os.getenv('OPENSCREEN_DATA','data'),secret_dir,demo)
    @asynccontextmanager
    async def lifespan(app):
        if start_workers:
            runtime.start()
        yield
        runtime.close()
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.runtime=runtime

    @app.middleware('http')
    async def access(request, call_next):
        if demo:
            if not request.client or request.client.host not in ('127.0.0.1','::1','localhost'):
                return JSONResponse({'detail':'Demo nur über localhost'},status_code=403)
            if request.url.hostname not in ('127.0.0.1','::1','localhost','testserver'):
                return JSONResponse({'detail':'Unzulässiger Host'},status_code=403)
        else:
            if not request.client or not policy.permits(request.client.host, request.url.hostname):
                return JSONResponse({'detail':'Zugriff nur aus freigegebenem lokalem Netz und Host'},status_code=403)
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail':'Seitenübergreifender Zugriff gesperrt'},status_code=403)
        if request.url.path=='/healthz':
            return JSONResponse({'ok':True})
        if request.method not in ('GET','HEAD'):
            origin=request.headers.get('origin')
            if request.headers.get('X-OpenScreen')!='1' or (origin and not same_origin(origin, request.url)):
                return JSONResponse({'detail':'Ungültige Anfrageherkunft'},status_code=403)
            try:
                length=int(request.headers.get('content-length','0'))
            except ValueError:
                return JSONResponse({'detail':'Ungültige Anfragegröße'},status_code=400)
            if length>262144:
                return JSONResponse({'detail':'Konfiguration zu groß'},status_code=413)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; img-src 'self' data:; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.get('/')
    def index():
        return FileResponse(STATIC/'index.html')

    @app.get('/favicon.ico')
    def favicon():
        return Response(status_code=204)

    @app.get('/api/config')
    def config_get():
        with runtime.lock:
            return runtime.config.model_dump()

    @app.put('/api/config')
    def config_put(config:Config):
        try:
            runtime.save(config)
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from None
        except OSError:
            raise HTTPException(500,'Konfiguration konnte nicht gespeichert werden') from None
        return {'ok':True}

    @app.get('/api/status')
    def status():
        return runtime.status()

    @app.get('/api/preview.png')
    def preview(page:str|None=None):
        return Response(png(runtime.image(page)),media_type='image/png')

    @app.post('/api/sources/{source_id}/test')
    def source_test(source_id:str):
        with runtime.lock:
            source=next((s.model_copy(deep=True) for s in runtime.config.sources if s.id==source_id),None)
        if not source:
            raise HTTPException(404,'Datenquelle fehlt')
        if runtime.demo:
            return {'ok':True,'message':'Demo: keine externe Verbindung ausgeführt'}
        result=collect(source,secret_dir)
        return {'ok':result.ok,'message':'Verbindung erfolgreich' if result.ok else result.error}

    @app.post('/api/rules/{rule_id}/test')
    def rule_test(rule_id:str):
        config,snapshots,_,now=runtime.state()
        rule=next((r for r in config.rules if r.id==rule_id),None)
        if not rule:
            raise HTTPException(404,'Warnregel fehlt')
        rule=rule.model_copy(update={'delay':0})
        trial=config.model_copy(update={'rules':[rule]})
        return AlertEngine().evaluate(trial,snapshots,now)[0]

    app.mount('/static',StaticFiles(directory=STATIC,check_dir=False),name='static')
    return app
