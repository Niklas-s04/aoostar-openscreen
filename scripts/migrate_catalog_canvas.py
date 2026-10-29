"""Copy reviewed canvas content to a NEW catalog directory; never edit the source.

Explicit --canvas-only acknowledges loss of collectors, rules, and hardware settings.
Run on an exported data backup, not a running app or a NAS system directory.
"""
import argparse
import json
from pathlib import Path
import shutil

from openscreen_catalog.models import Config
from openscreen_catalog.runtime import Runtime


def migrate(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or destination == source or source in destination.parents:
        raise ValueError('Destination must be a new directory outside source')
    config_path = source / 'config.json'
    if config_path.is_symlink() or config_path.stat().st_size > 1024 * 1024:
        raise ValueError('Invalid source configuration')
    old = json.loads(config_path.read_text(encoding='utf-8'))
    pages = old['pages']
    for page in pages:
        page['source_id'] = ''
        for element in page.get('elements', []):
            element.setdefault('binding', {})['source_id'] = ''
    config = Config.model_validate({
        'pages': pages, 'title': old.get('title', 'OpenScreen Catalog'),
        'rotation': old.get('rotation', 20), 'selected_page': old.get('selected_page', ''),
    })
    referenced = {e.asset_id for p in config.pages for e in p.elements if e.asset_id}
    media = source / 'assets'
    if referenced and (media.is_symlink() or not media.is_dir()):
        raise ValueError('Invalid source media directory')
    for asset in referenced:
        for path in (media / asset, media / asset / 'media.png', media / asset / 'metadata.json'):
            if path.is_symlink():
                raise ValueError('Symlink media is not supported')
        if not (media / asset / 'media.png').is_file():
            raise ValueError('Missing media')
    # Only validated, referenced files are copied. Failure leaves a new partial
    # directory for inspection, never deletes source or destination data.
    destination.mkdir(parents=True, exist_ok=False)
    runtime = Runtime(destination)
    for asset in referenced:
        target = destination / 'assets' / asset
        target.mkdir()
        for name in ('media.png', 'metadata.json'):
            shutil.copyfile(media / asset / name, target / name)
    runtime.save(config)
    return config


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--canvas-only', required=True, action='store_true')
    args = parser.parse_args()
    migrate(args.source, args.destination)
    print('Canvas copied; sources, rules and hardware settings were not migrated.')
