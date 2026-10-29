import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from openscreen.canvas_models import Page
from openscreen.network_access import AccessPolicy, same_origin
from openscreen.render import png
from openscreen.templates import FONTS, SYMBOLS, TEMPLATES
import openscreen
from .models import Config
from .runtime import Runtime
from . import __version__

STATIC = Path(__file__).parent / 'static'
SHARED_STATIC = Path(openscreen.__file__).parent / 'static'


def create_app(data_dir=None):
    policy = AccessPolicy()
    runtime = Runtime(data_dir or os.getenv('OPENSCREEN_DATA', '/data'))
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runtime = runtime
    gate = asyncio.Semaphore(4)

    @app.middleware('http')
    async def access(request, call_next):
        peer = request.client.host if request.client else ''
        # Local health probe is independent of the administrator's LAN allowlist.
        if request.url.path == '/healthz' and request.method == 'GET' and peer in ('127.0.0.1', '::1'):
            return JSONResponse({'ok': True})
        if not policy.permits(peer, request.url.hostname):
            return JSONResponse({'detail': 'Host or peer not allowed'}, status_code=403)
        origin = request.headers.get('origin')
        if (request.headers.get('sec-fetch-site') == 'cross-site'
                or (origin and not same_origin(origin, request.url))):
            return JSONResponse({'detail': 'Cross-origin request denied'}, status_code=403)
        if gate.locked():
            return JSONResponse({'detail': 'Busy'}, status_code=429)
        async with gate:
            if request.method not in ('GET', 'HEAD'):
                if request.headers.get('X-OpenScreen') != '1':
                    return JSONResponse({'detail': 'Missing request header'}, status_code=403)
                limit = 10*1024*1024 if request.url.path == '/api/assets' else 1024*1024
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > limit:
                        return JSONResponse({'detail': 'Request too large'}, status_code=413)
                    body.extend(chunk)
                request._body = bytes(body)
            response = await call_next(request)
        response.headers.update({
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'self'; style-src 'self'; img-src 'self' data: blob:; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        })
        return response

    @app.get('/healthz')
    def health():
        return {'ok': True}

    @app.get('/')
    def index():
        return FileResponse(STATIC / 'index.html')

    @app.get('/display')
    def display():
        return FileResponse(STATIC / 'player.html')

    @app.get('/api/config')
    def config_get():
        with runtime.lock:
            return runtime.config.model_dump()

    @app.put('/api/config')
    def config_put(config: Config):
        try:
            runtime.save(config)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except OSError:
            raise HTTPException(500, 'Cannot persist configuration; check assigned storage permissions') from None
        return {'ok': True}

    @app.get('/api/status')
    def status():
        return {'version': __version__, 'distribution': 'catalog', 'sources': [], 'display': {'state': 'browser'}}

    @app.get('/api/editor/catalog')
    def editor_catalog():
        return {'fonts': FONTS, 'symbols': SYMBOLS,
                'templates': [t for t in TEMPLATES if t['id'] in ('blank', 'clock')],
                'outputs': [{'id': 'browser', 'name': 'Browser'}]}

    @app.get('/api/output.png')
    def output():
        return Response(png(runtime.image()), media_type='image/png')

    @app.post('/api/editor/preview')
    def preview(page: Page):
        try:
            return Response(png(runtime.image(draft=page)), media_type='image/png')
        except ValueError:
            raise HTTPException(400, 'Invalid page bindings') from None

    @app.get('/api/assets')
    def assets():
        return runtime.assets.list()

    @app.post('/api/assets')
    async def upload(request: Request, name: str = 'image'):
        from starlette.concurrency import run_in_threadpool
        try:
            return await run_in_threadpool(runtime.assets.upload, await request.body(), name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except OSError:
            raise HTTPException(500, 'Cannot write media') from None

    @app.get('/api/assets/{asset_id}')
    def asset(asset_id: str):
        try:
            return FileResponse(runtime.assets.get_path(asset_id))
        except (ValueError, FileNotFoundError):
            raise HTTPException(404, 'Media not found') from None

    @app.delete('/api/assets/{asset_id}')
    def delete_asset(asset_id: str):
        with runtime.lock:
            if any(e.asset_id == asset_id for p in runtime.config.pages for e in p.elements):
                raise HTTPException(409, 'Media is in use')
            try:
                runtime.assets.delete(asset_id)
            except (ValueError, FileNotFoundError):
                raise HTTPException(404, 'Media not found') from None
        return {'ok': True}

    @app.get('/static/editor.js')
    def editor_script():
        return FileResponse(SHARED_STATIC / 'editor.js')

    @app.get('/static/style.css')
    def editor_styles():
        return FileResponse(SHARED_STATIC / 'style.css')

    app.mount('/static', StaticFiles(directory=STATIC), name='static')
    return app
