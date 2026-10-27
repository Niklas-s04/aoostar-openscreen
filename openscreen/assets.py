"""Bounded, local media library. Display names never become filesystem paths."""

from collections import OrderedDict
from io import BytesIO
import json
import math
from pathlib import Path
import re
import shutil
from threading import RLock
import uuid
import warnings

from PIL import Image, ImageOps


class AssetStore:
    MAX_INPUT = 10 * 1024 * 1024
    MAX_PIXELS = 8_000_000
    MAX_DECODED_PIXELS = 32_000_000
    MAX_FRAMES = 60
    MAX_ASSETS = 64
    MAX_STORAGE = 100 * 1024 * 1024
    MAX_CACHE = 8 * 1024 * 1024

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._cache = OrderedDict()
        self._cache_bytes = 0

    def _directory(self, asset_id):
        if not isinstance(asset_id, str) or not re.fullmatch(r"[0-9a-f]{32}", asset_id):
            raise ValueError("Invalid asset ID")
        path = self.root / asset_id
        if path.is_symlink():
            raise ValueError("Invalid asset directory")
        return path

    def _metadata(self, asset_id):
        directory = self._directory(asset_id)
        path = directory / "metadata.json"
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16_384:
            raise ValueError("Asset not found")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["id"] != asset_id:
                raise ValueError("Invalid metadata")
            return data
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid asset metadata") from exc

    def list(self):
        with self._lock:
            result = []
            for path in sorted(self.root.iterdir()):
                if not re.fullmatch(r"[0-9a-f]{32}", path.name):
                    continue
                try:
                    data = self._metadata(path.name)
                    self.get_path(path.name)
                    result.append({k: v for k, v in data.items() if k != "durations"})
                except ValueError:
                    continue
            return result

    def get_path(self, asset_id):
        with self._lock:
            path = self._directory(asset_id) / "media.png"
            if path.is_symlink() or not path.is_file():
                raise ValueError("Asset not found")
            return path

    def upload(self, data: bytes, name: str):
        if not isinstance(data, bytes) or not data or len(data) > self.MAX_INPUT:
            raise ValueError("Upload must contain at most 10 MiB")
        if (not isinstance(name, str) or not name.strip() or len(name) > 200
                or any(ord(c) < 32 for c in name) or any(c in name for c in '/\\:')
                or name in {".", ".."}):
            raise ValueError("Invalid display filename")
        with self._lock:
            existing = self.list()
            if len(existing) >= self.MAX_ASSETS:
                raise ValueError("Media library is full")
            frames, durations = [], []
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(BytesIO(data), formats=["PNG", "JPEG", "WEBP", "GIF"]) as source:
                        count = getattr(source, "n_frames", 1)
                        pixels = source.width * source.height
                        if pixels > self.MAX_PIXELS or count > self.MAX_FRAMES:
                            raise ValueError("Image dimensions or frame count exceed limits")
                        if pixels * count > self.MAX_DECODED_PIXELS:
                            raise ValueError("Animation decoded pixel budget exceeded")
                        decoded_pixels = 0
                        canvas_size = source.size
                        for index in range(count):
                            source.seek(index)
                            frame_pixels = source.width * source.height
                            decoded_pixels += frame_pixels
                            if frame_pixels > self.MAX_PIXELS or decoded_pixels > self.MAX_DECODED_PIXELS:
                                raise ValueError('Decoded frame dimensions exceed limits')
                            if source.size != canvas_size:
                                raise ValueError('Animation changes its canvas dimensions')
                            frame = ImageOps.exif_transpose(source).convert("RGBA")
                            # Keep enough detail for network displays, with a fixed decode/storage budget.
                            scale = min(1, 1920/frame.width, 1920/frame.height,
                                        (2_073_600/(frame.width*frame.height))**0.5)
                            frame.thumbnail((max(1,int(frame.width*scale)),max(1,int(frame.height*scale))), Image.Resampling.LANCZOS)
                            # A fresh image deliberately drops EXIF, comments, ICC and other metadata.
                            clean = Image.new("RGBA", frame.size)
                            clean.paste(frame)
                            frames.append(clean)
                            durations.append(max(20, min(10_000, int(source.info.get("duration", 100)))))
                output = BytesIO()
                frames[0].save(output, format="PNG", save_all=len(frames) > 1,
                               append_images=frames[1:], duration=durations, loop=0,
                               disposal=0, blend=0)
                encoded = output.getvalue()
                if sum(item["size"] for item in existing) + len(encoded) > self.MAX_STORAGE:
                    raise ValueError("Media storage quota exceeded")
                # Pillow may coalesce identical animation frames: use the stored representation.
                with Image.open(BytesIO(encoded)) as normalized:
                    durations = []
                    for index in range(getattr(normalized, "n_frames", 1)):
                        normalized.seek(index)
                        durations.append(int(normalized.info.get("duration", 100)))
                asset_id = uuid.uuid4().hex
                metadata = dict(id=asset_id, name=name.strip(), width=frames[0].width,
                                height=frames[0].height, frames=len(durations),
                                duration_ms=sum(durations) if len(durations) > 1 else 0,
                                size=len(encoded), durations=durations)
                staging = self.root / (".upload-" + asset_id)
                staging.mkdir()
                try:
                    (staging / "media.png").write_bytes(encoded)
                    (staging / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
                    staging.rename(self.root / asset_id)
                finally:
                    if staging.exists():
                        shutil.rmtree(staging)
                return {k: v for k, v in metadata.items() if k != "durations"}
            except (OSError, SyntaxError, EOFError, OverflowError, TypeError,
                    Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                raise ValueError("Unsupported or invalid image") from exc
            finally:
                for frame in frames:
                    frame.close()

    def frame(self, asset_id, now, speed=1):
        with self._lock:
            try:
                if not math.isfinite(now) or not math.isfinite(speed) or speed <= 0:
                    return None
                data = self._metadata(asset_id)
                durations = data["durations"]
                position = (now * speed * 1000) % sum(durations)
                index = len(durations) - 1
                for i, duration in enumerate(durations):
                    if position < duration:
                        index = i
                        break
                    position -= duration
                key = (asset_id, index)
                if key in self._cache:
                    self._cache.move_to_end(key)
                    return self._cache[key].copy()
                with Image.open(self.get_path(asset_id)) as image:
                    image.seek(index)
                    result = image.convert("RGBA")
                size = result.width * result.height * 4
                while self._cache and self._cache_bytes + size > self.MAX_CACHE:
                    _, old = self._cache.popitem(last=False)
                    self._cache_bytes -= old.width * old.height * 4
                    old.close()
                if size <= self.MAX_CACHE:
                    self._cache[key] = result.copy()
                    self._cache_bytes += size
                return result
            except (ValueError, OSError, KeyError, TypeError, ZeroDivisionError, EOFError):
                return None

    def delete(self, asset_id):
        with self._lock:
            directory = self._directory(asset_id)
            self.get_path(asset_id)
            try:
                shutil.rmtree(directory)
            except OSError as exc:
                raise ValueError("Could not delete asset") from exc
            for key in list(self._cache):
                if key[0] == asset_id:
                    image = self._cache.pop(key)
                    self._cache_bytes -= image.width * image.height * 4
                    image.close()
