from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image
import pytest

from openscreen.assets import AssetStore


def picture(fmt="PNG", size=(100, 50), **kwargs):
    data = BytesIO()
    Image.new("RGB", size, "red").save(data, format=fmt, **kwargs)
    return data.getvalue()


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "GIF"])
def test_formats_resize_restart_and_delete(tmp_path, fmt):
    store = AssetStore(tmp_path)
    meta = store.upload(picture(fmt, (1920, 752)), "display." + fmt.lower())
    assert (meta["width"], meta["height"]) == (1920, 752)
    assert len(meta["id"]) == 32
    restarted = AssetStore(tmp_path)
    assert restarted.list() == [meta]
    frame = restarted.frame(meta["id"], 0)
    assert frame.mode == "RGBA"
    frame.putpixel((0, 0), (0, 0, 0, 0))
    assert restarted.frame(meta["id"], 0).getpixel((0, 0))[3] == 255
    restarted.delete(meta["id"])
    assert restarted.list() == []
    assert restarted.frame(meta["id"], 0) is None


@pytest.mark.parametrize("name", ["../image.png", "a/b.png", "a\\b.png", "C:image.png", "", "\x00.png"])
def test_unsafe_names(tmp_path, name):
    with pytest.raises(ValueError):
        AssetStore(tmp_path).upload(picture(), name)


def test_invalid_media_limits_and_transaction(tmp_path, monkeypatch):
    store = AssetStore(tmp_path)
    for content in [b"<svg></svg>", b"<html></html>", picture("BMP"), b"invalid"]:
        with pytest.raises(ValueError):
            store.upload(content, "image.png")
    with pytest.raises(ValueError):
        store.upload(b"x" * (store.MAX_INPUT + 1), "image.png")
    monkeypatch.setattr(store, "MAX_PIXELS", 100)
    with pytest.raises(ValueError):
        store.upload(picture(), "image.png")
    assert list(tmp_path.iterdir()) == []


def animation(count=3):
    data = BytesIO()
    frames = [Image.new("RGB", (10, 10), (i * 3, 0, 0)) for i in range(count)]
    frames[0].save(data, format="GIF", save_all=True, append_images=frames[1:],
                   duration=100, loop=0)
    return data.getvalue()


def test_animation_timing_and_limits(tmp_path, monkeypatch):
    store = AssetStore(tmp_path)
    meta = store.upload(animation(), "motion.gif")
    assert meta["frames"] == 3 and meta["duration_ms"] == 300
    assert store.frame(meta["id"], .11).getpixel((0, 0))[0] == 3
    assert store.frame(meta["id"], .055, 2).getpixel((0, 0))[0] == 3
    assert store.frame(meta["id"], float("inf")) is None
    with pytest.raises(ValueError):
        store.upload(animation(61), "long.gif")
    monkeypatch.setattr(store, "MAX_DECODED_PIXELS", 200)
    with pytest.raises(ValueError):
        store.upload(animation(), "large.gif")


def test_quotas_and_traversal(tmp_path, monkeypatch):
    store = AssetStore(tmp_path)
    monkeypatch.setattr(store, "MAX_STORAGE", 1)
    with pytest.raises(ValueError):
        store.upload(picture(), "image.png")
    assert store.list() == []
    monkeypatch.setattr(store, "MAX_STORAGE", 100000)
    monkeypatch.setattr(store, "MAX_ASSETS", 1)
    store.upload(picture(), "image.png")
    with pytest.raises(ValueError):
        store.upload(picture(), "image.png")
    for method in [store.get_path, store.delete]:
        with pytest.raises(ValueError):
            method("../outside")


def test_exif_orientation_and_metadata_removed(tmp_path):
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private description"
    store = AssetStore(tmp_path)
    meta = store.upload(picture("JPEG", (100, 50), exif=exif), "camera.jpg")
    assert (meta["width"], meta["height"]) == (50, 100)
    with Image.open(store.get_path(meta["id"])) as image:
        assert not image.getexif()


def test_failed_write_leaves_no_asset(tmp_path, monkeypatch):
    store = AssetStore(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", fail)
    with pytest.raises(ValueError):
        store.upload(picture(), "image.png")
    assert list(tmp_path.iterdir()) == []


def test_concurrent_uploads_obey_quota(tmp_path, monkeypatch):
    store = AssetStore(tmp_path)
    monkeypatch.setattr(store, "MAX_ASSETS", 2)
    data = picture()

    def upload(_):
        try:
            return store.upload(data, "image.png")
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(upload, range(6)))
    assert sum(result is not None for result in results) == 2
    assert len(store.list()) == 2


def test_cache_is_bounded(tmp_path, monkeypatch):
    store = AssetStore(tmp_path)
    monkeypatch.setattr(store, "MAX_CACHE", 400)
    meta = store.upload(animation(), "motion.gif")
    for now in [0, .11, .21]:
        assert store.frame(meta["id"], now) is not None
        assert store._cache_bytes <= 400
    assert len(store._cache) == 1


def test_gif_later_frames_cannot_expand_past_pixel_budget(tmp_path, monkeypatch):
    store = AssetStore(tmp_path)
    monkeypatch.setattr(store, 'MAX_PIXELS', 1000)
    output = BytesIO()
    Image.new('RGB',(80,80),'red').save(output,format='GIF',save_all=True,
        append_images=[Image.new('RGB',(80,80),'blue')],duration=100)
    data=bytearray(output.getvalue())
    palette_end=13+3*(2**((data[10]&7)+1))
    descriptor=data.index(b',',palette_end)
    data[6:10]=b'\x01\x00\x01\x00'
    data[descriptor+5:descriptor+9]=b'\x01\x00\x01\x00'
    with pytest.raises(ValueError):
        store.upload(bytes(data),'expanding.gif')
    assert store.list()==[]
