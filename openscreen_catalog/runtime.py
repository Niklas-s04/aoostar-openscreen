"""Local canvas persistence and rendering; deliberately no collectors or transports."""
import os
from pathlib import Path
import tempfile
import threading
import time

from PIL import ImageOps, Image
from openscreen.assets import AssetStore
from openscreen.render import render
from .models import Config


class Runtime:
    def __init__(self, data_dir):
        self.root = Path(data_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'config.json'
        if self.path.is_symlink():
            raise ValueError('Configuration must not be a symlink')
        if self.path.exists() and self.path.stat().st_size > 1024 * 1024:
            raise ValueError('Configuration exceeds 1 MiB')
        try:
            self.config = Config.model_validate_json(self.path.read_bytes()) if self.path.exists() else Config()
        except ValueError:
            raise ValueError('Invalid or incompatible catalog configuration; original file was not changed') from None
        # Fail on startup, without changing existing data or permissions.
        with tempfile.TemporaryFile(dir=self.root) as probe:
            probe.write(b'permission check')
            probe.flush()
            os.fsync(probe.fileno())
        if (self.root / 'assets').is_symlink():
            raise ValueError('Asset root must not be a symlink')
        self.assets = AssetStore(self.root / 'assets')
        self.lock = threading.RLock()
        self.started = time.time()

    def save(self, config):
        config = Config.model_validate(config.model_dump())
        with self.lock:
            for page in config.pages:
                for element in page.elements:
                    if element.asset_id:
                        self.assets.get_path(element.asset_id)
            name = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.root,
                                                 prefix='.config-', delete=False) as handle:
                    name = handle.name
                    handle.write(config.model_dump_json(indent=2))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(name, self.path)
            finally:
                if name and os.path.exists(name):
                    os.unlink(name)
            self.config = config.model_copy(deep=True)

    def image(self, draft=None):
        with self.lock:
            config = self.config.model_copy(deep=True)
            now = time.time()
            if draft is not None:
                config = Config.model_validate(config.model_copy(update={
                    'pages': [draft.model_copy(update={'enabled': True})],
                    'selected_page': draft.id,
                }).model_dump())
            pages = [p.id for p in config.pages if p.enabled]
            page = config.selected_page if config.paused or draft else pages[int((now-self.started)//config.rotation) % len(pages)]
            frame = render(config, {}, [], page, now, False, history={}, assets=self.assets)
            if draft is not None:
                return frame
            return ImageOps.pad(frame, (config.output.width, config.output.height),
                                method=Image.Resampling.LANCZOS, color='#000000')
