"""Editable starter canvases; return fresh dictionaries for each caller."""
from copy import deepcopy

FONTS = [{'id': key, 'name': name} for key, name in [
    ('sans', 'DejaVu Sans'), ('sans-condensed', 'DejaVu Sans Condensed'),
    ('serif', 'DejaVu Serif'), ('mono', 'DejaVu Mono'),
    ('liberation-sans', 'Liberation Sans'), ('liberation-serif', 'Liberation Serif'),
    ('liberation-mono', 'Liberation Mono')]]
SYMBOLS = [{'id': key, 'name': name} for key, name in [
    ('cpu', 'CPU'), ('memory', 'RAM'), ('storage', 'Speicher'), ('network', 'Netzwerk'),
    ('server', 'Server'), ('clock', 'Uhr'), ('temperature', 'Temperatur'),
    ('warning', 'Warnung'), ('download', 'Download'), ('upload', 'Upload'), ('check', 'Haken')]]


def _metric(id, label, x, width=280, metric=None, unit='%', **extra):
    return dict(id=id, kind='metric', x=x, y=64, width=width, height=248,
                label=label, font_size=96, label_size=30, align='center',
                binding=dict(metric=metric or id, unit=unit), **extra)


def template_page(kind):
    names = dict(system='System', focus='Fokus', network='Netzwerk', storage='Speicher',
                 services='Dienste', clock='Uhr', image='Bild / GIF', blank='Leere Seite')
    kind = kind if kind in names else 'blank'
    elements = []
    if kind == 'system':
        elements = [_metric('cpu', 'CPU', 20), _metric('memory', 'RAM', 340),
                    _metric('temperature', 'TEMPERATUR', 660, unit='°C')]
    elif kind == 'focus':
        elements = [_metric('cpu', 'CPU', 20, width=360),
                    dict(id='history', kind='chart', x=410, y=64, width=520, height=248,
                         binding=dict(metric='cpu'), label='CPU-Verlauf')]
    elif kind == 'network':
        elements = [_metric(key, name, x, width=440, unit='MB/s')
                    for key, name, x in [('download', 'DOWNLOAD', 20), ('upload', 'UPLOAD', 500)]]
        for e in elements:
            e['binding'].update(scale=0.000001, precision=1)
            e['font_size'] = 80
    elif kind in ('storage', 'services'):
        elements = [_metric('value', 'SPEICHER GESAMT BELEGT' if kind == 'storage' else 'LAUFENDE DIENSTE', 40, width=880,
                            metric='percent' if kind == 'storage' else 'running', unit='%' if kind == 'storage' else '')]
        elements[0]['binding']['collection'] = 'pools' if kind == 'storage' else 'workloads'
        elements[0]['binding']['target'] = '*'
    elif kind == 'clock':
        elements = [dict(id='time', kind='clock', x=20, y=40, width=920, height=210,
                         font_size=160, align='center'),
                    dict(id='date', kind='clock', x=20, y=270, width=920, height=70,
                         time_format='date', font_size=48, align='center')]
    elif kind == 'image':
        elements = [dict(id='image', kind='image', x=0, y=0, width=960, height=376)]
    return deepcopy(dict(id=kind, name=names[kind], background='#101012', elements=elements))


TEMPLATES = [dict(id=kind, name=template_page(kind)['name'], page=template_page(kind))
             for kind in ('system', 'focus', 'network', 'storage', 'services', 'clock', 'image', 'blank')]
