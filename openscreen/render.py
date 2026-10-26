import io
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BG = '#101012'
FG = '#f5f5f7'
MUTED = '#94949e'
LINE = '#303034'


def font(size):
    candidates = [os.getenv('OPENSCREEN_FONT',''), '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'C:/Windows/Fonts/arial.ttf']
    for path in candidates:
        if path and Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def render(config, snapshots, alerts, page_id, now, demo=False):
    image = Image.new('RGB', (960,376), BG)
    draw = ImageDraw.Draw(image)
    def text(x,y,value,size=20,fill=FG,max_width=880):
        value = str(value)
        f = font(size)
        while value and draw.textlength(value,font=f) > max_width:
            value = value[:-2] + '…' if not value.endswith('…') else value[:-2] + '…'
        draw.text((x,y),value,font=f,fill=fill)
    pages = [p for p in config.pages if p.enabled]
    page = next((p for p in pages if p.id == page_id), pages[0])
    active = [a for a in alerts if a['state'] == 'active']
    full = sorted([a for a in active if a['display'] == 'fullscreen'],key=lambda a:a['severity']!='critical')
    valid = {s.id: snapshots[s.id] for s in config.sources if s.enabled and s.id in snapshots
             and snapshots[s.id].ok and now - snapshots[s.id].observed_at <= s.interval*2}
    selected = [valid[page.source_id]] if page.source_id in valid else [] if page.source_id else list(valid.values())
    metrics = {}
    for s in selected:
        for key,value in s.metrics.items():
            if key not in metrics or metrics[key] is None:
                metrics[key] = value
    title = 'WARNUNG' if full else page.name.upper()
    text(30,24,title,21)
    text(815,26,('!' if active else str(pages.index(page)+1)) + f' / {len(pages)}',18,max_width=120)
    draw.line((30,65,930,65), fill=LINE)
    if full:
        alert = full[int(now//max(10,config.rotation)) % len(full)]
        text(40,120,alert['name'].upper(),46,max_width=870)
        text(40,198,alert.get('target') or alert.get('metric') or 'Bedingung erfüllt',28, MUTED)
        text(40,251,'KRITISCH' if alert['severity']=='critical' else 'WARNUNG',22,'#fca5a5' if alert['severity']=='critical' else '#fcd34d')
    elif page.id == 'system':
        choices = [(k, {'cpu':'CPU','memory':'RAM','temperature':'TEMP'}.get(k,k.upper()), '°C' if k=='temperature' else '%') for k in page.metrics[:3]]
        for index,(key,label,unit) in enumerate(choices):
            x=30+index*310
            value=metrics.get(key)
            text(x,108,label,22,MUTED,max_width=280)
            text(x,155,'—' if value is None else f'{value:.0f}',76,max_width=220)
            text(x+220,205,unit,25,MUTED,max_width=70)
            draw.rectangle((x,274,x+278,279),fill=LINE)
            if value is not None:
                draw.rectangle((x,274,x+max(0,min(100,value))*2.78,279),fill=FG)
    elif page.id == 'storage':
        pools = [p for s in selected for p in s.pools]
        offset = (int(now//config.rotation) % max(1,(len(pools)+1)//2))*2
        for i,pool in enumerate(pools[offset:offset+2]):
            y=99+i*108
            text(30,y,pool['name'].upper(),24,max_width=440)
            pct=pool.get('percent')
            label = '—' if pct is None else f'{pct:.1f}%'
            text(660,y,label,25,max_width=260)
            draw.rectangle((30,y+46,930,y+51),fill=LINE)
            if pct is not None:
                draw.rectangle((30,y+46,30+min(100,max(0,pct))*9,y+51),fill=FG)
            text(30,y+61,pool.get('state','unbekannt').upper(),15,MUTED)
        if not pools:
            text(30,160,'Keine Speicherdaten verfügbar',30,MUTED)
    elif page.id == 'services':
        for i,(kind,label) in enumerate([('docker','DOCKER'),('proxmox','PROXMOX'),('truenas','TRUENAS')]):
            sources = [s for s in config.sources if s.kind == kind and s.id in valid and (not page.source_id or s.id==page.source_id)]
            values = [w for s in sources for w in valid[s.id].workloads if w.get('kind')!='node']
            text(30+i*310,137,str(sum(w.get('state')=='running' for w in values)) if sources else '—',84,max_width=280)
            text(30+i*310,244,label,24,MUTED,max_width=280)
    else:
        for i,(key,label) in enumerate([('download','↓ Download'),('upload','↑ Upload')]):
            value=metrics.get(key)
            text(30+i*470,120,label,27,MUTED,max_width=420)
            text(30+i*470,179,'—' if value is None else f'{value/1_000_000:.1f}',70,max_width=300)
            text(325+i*470,224,'MB/s',22,MUTED,max_width=100)
    draw.line((30,325,930,325),fill=LINE)
    unknown = any(a['state']=='unknown' for a in alerts)
    message = next((a['name'] for a in active if a['display']=='message'), None)
    status = message or ('Warndaten unbekannt' if unknown else 'Keine aktuellen Daten' if not selected else config.title)
    text(30,340,('DEMO · ' if demo else '')+status,15,MUTED,max_width=790)
    text(845,340,f'{config.rotation}s',15,MUTED,max_width=80)
    return image


def png(image):
    buffer = io.BytesIO()
    image.save(buffer,format='PNG')
    return buffer.getvalue()
