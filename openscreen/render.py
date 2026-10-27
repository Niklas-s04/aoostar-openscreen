"""Bounded Pillow canvas shared by editor preview and physical display."""
import io
import math
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont, ImageOps
from .templates import FONTS, SYMBOLS, TEMPLATES

BG = '#101012'
FG = '#f5f5f7'
MUTED = '#94949e'
LINE = '#303034'


@lru_cache(maxsize=256)
def font(size, family='sans', bold=False, italic=False):
    base = {'sans':'DejaVuSans', 'sans-condensed':'DejaVuSansCondensed',
            'serif':'DejaVuSerif', 'mono':'DejaVuSansMono',
            'liberation-sans':'LiberationSans', 'liberation-serif':'LiberationSerif',
            'liberation-mono':'LiberationMono'}.get(family, 'DejaVuSans')
    liberation = base.startswith('Liberation')
    slant = 'Italic' if 'Serif' in base or liberation else 'Oblique'
    suffix = ('Bold' if bold else '') + (slant if italic else '')
    filename = base + ('-' + suffix if suffix else '-Regular' if liberation else '') + '.ttf'
    windows = {'sans':'arial', 'sans-condensed':'arial', 'serif':'times', 'mono':'cour',
               'liberation-sans':'arial', 'liberation-serif':'times', 'liberation-mono':'cour'}[family]
    windows += 'bi' if bold and italic else 'bd' if bold else 'i' if italic else ''
    for path in [Path('/usr/share/fonts/truetype/dejavu') / filename,
                 Path('/usr/share/fonts/truetype/liberation2') / filename,
                 Path('/usr/share/fonts/truetype/liberation') / filename,
                 Path('C:/Windows/Fonts') / (windows + '.ttf')]:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def draw_text(layer, value, element, box=None, size=None, color=None):
    """Place actual glyph bounds, including italic overhang, inside the box."""
    draw = ImageDraw.Draw(layer)
    f = font(size or element.font_size, element.font, element.bold, element.italic)
    value = str(value)
    x, y, w, h = box or (0, 0, *layer.size)
    bounds = draw.multiline_textbbox((0, 0), value, font=f, spacing=4, align=element.align)
    tw, th = bounds[2] - bounds[0], bounds[3] - bounds[1]
    dx = 0 if element.align == 'left' else (w-tw)/2 if element.align == 'center' else w-tw
    dy = 0 if element.vertical == 'top' else (h-th)/2 if element.vertical == 'center' else h-th
    draw.multiline_text((x+dx-bounds[0], y+dy-bounds[1]), value, font=f,
                        fill=color or element.color, spacing=4, align=element.align)


def bound_value(binding, selected):
    if binding.collection != 'metrics' and binding.target == '*':
        rows = [row for snap in selected for row in getattr(snap,binding.collection)]
        if not rows:
            return None
        if binding.collection == 'workloads' and binding.metric == 'running':
            # Node records describe the host, not a service workload.
            rows = [row for row in rows if row.get('kind') != 'node']
            if any(not row.get('state') or row['state'] == 'unknown' for row in rows):
                return None
            value = sum(str(row['state']).lower() == 'running' for row in rows)
        elif binding.collection == 'pools' and binding.metric == 'percent':
            # Capacity weighted utilization; unknown capacity must not look empty.
            pairs = [(row.get('used'),row.get('total')) for row in rows]
            if any(not isinstance(used,(int,float)) or not isinstance(total,(int,float))
                   or not math.isfinite(used) or not math.isfinite(total)
                   or used < 0 or total <= 0 for used,total in pairs):
                return None
            value = sum(used for used,total in pairs) / sum(total for used,total in pairs) * 100
        else:
            return None
        value *= binding.scale
        return value if math.isfinite(value) else None
    for snap in selected:
        if binding.collection == 'metrics':
            value = snap.metrics.get(binding.metric)
        else:
            # An empty target must never silently select another pool or service.
            row = next((r for r in getattr(snap, binding.collection) if binding.target and
                        binding.target in (str(r.get('id', '')), r.get('name'))), {})
            value = row.get(binding.metric)
        if value is not None:
            if isinstance(value, (float, int)):
                value *= binding.scale
                return value if math.isfinite(value) else None
            return str(value)
    return None


def formatted(value, binding):
    if value is None:
        return '—'
    return (f'{value:.{binding.precision}f}' if isinstance(value, (int, float)) else str(value)) + binding.unit


def symbol(layer, name, color, stroke):
    """Small offline vector vocabulary in a normalized 100-unit square."""
    side = min(layer.size)
    icon = Image.new('RGBA', (100, 100))
    d = ImageDraw.Draw(icon)
    width = max(2, min(12, round(stroke * 100 / max(1, side))))
    def line(points):
        d.line(points, fill=color, width=width, joint='curve')
    if name in ('cpu', 'memory'):
        d.rectangle((25,25,75,75), outline=color, width=width)
        for p in (35,50,65):
            line([(p,12),(p,25)]); line([(p,75),(p,88)])
            line([(12,p),(25,p)]); line([(75,p),(88,p)])
        d.rectangle((38,38,62,62), outline=color, width=width)
    elif name in ('storage', 'server'):
        for y in (16,42,68):
            d.rounded_rectangle((14,y,86,y+19), radius=4, outline=color, width=width)
            d.ellipse((24,y+6,30,y+12), fill=color)
    elif name == 'clock':
        d.ellipse((10,10,90,90), outline=color, width=width)
        line([(50,25),(50,50),(70,60)])
    elif name == 'temperature':
        d.rounded_rectangle((40,10,60,72), radius=10, outline=color, width=width)
        d.ellipse((32,58,68,94), fill=color)
        line([(50,32),(50,72)])
    elif name == 'warning':
        line([(50,8),(94,88),(6,88),(50,8)])
        line([(50,32),(50,60)])
        d.ellipse((46,70,54,78), fill=color)
    elif name == 'check':
        line([(15,52),(40,78),(87,22)])
    elif name in ('upload', 'download'):
        top, bottom = (78,22) if name == 'upload' else (22,78)
        line([(50,top),(50,bottom)])
        line([(25,50),(50,bottom),(75,50)])
    elif name == 'network':
        line([(50,30),(50,55),(20,55),(20,72)])
        line([(50,55),(80,55),(80,72)])
        for x,y in ((38,8),(8,72),(68,72)):
            d.rectangle((x,y,x+24,y+20), outline=color, width=width)
    else:
        d.ellipse((15,15,85,85), outline=color, width=width)
    icon = icon.resize((side,side), Image.Resampling.LANCZOS)
    layer.alpha_composite(icon, ((layer.width-side)//2,(layer.height-side)//2))


def render(config, snapshots, alerts, page_id, now, demo=False, history=None, assets=None):
    pages = [p for p in config.pages if p.enabled]
    page = next((p for p in pages if p.id == page_id), pages[0])
    image = Image.new('RGB', (page.width,page.height), page.background)
    valid = {s.id: snapshots[s.id] for s in config.sources if s.enabled and s.id in snapshots
             and snapshots[s.id].ok and now-snapshots[s.id].observed_at <= s.interval*2}
    for e in page.elements:
        if not e.visible:
            continue
        layer = Image.new('RGBA', (e.width,e.height), e.background or (0,0,0,0))
        d = ImageDraw.Draw(layer)
        sid = e.binding.source_id or page.source_id
        selected = [valid[sid]] if sid in valid else [] if sid else list(valid.values())
        value = bound_value(e.binding, selected)
        number = value if isinstance(value,(int,float)) else None
        ratio = None if number is None else max(0,min(1,(number-e.min_value)/(e.max_value-e.min_value)))
        if e.kind == 'text':
            draw_text(layer,e.text,e)
        elif e.kind == 'metric':
            label_height = e.label_size+16 if e.show_label and e.label else 0
            if label_height:
                draw_text(layer,e.label,e,(0,0,e.width,label_height),e.label_size)
            if e.show_value:
                draw_text(layer,formatted(value,e.binding),e,(0,label_height,e.width,e.height-label_height))
        elif e.kind == 'icon':
            symbol(layer,e.symbol,e.color,e.stroke_width)
        elif e.kind in ('bar','ring'):
            if e.kind == 'bar':
                h = max(6,min(e.height, e.stroke_width*3))
                y = e.height-h
                d.rectangle((0,y,e.width-1,e.height-1), fill=e.background or LINE)
                if ratio is not None and ratio > 0:
                    d.rectangle((0,y,max(0,round((e.width-1)*ratio)),e.height-1), fill=e.color)
                box = (0,0,e.width,max(1,e.height-h-4))
            else:
                side = max(0,min(e.width,e.height)-2)
                x,y = (e.width-side)//2,(e.height-side)//2
                box = (x,y,max(1,side),max(1,side))
                rect = (x,y,x+side,y+side)
                d.arc(rect,0,360,fill=e.background or LINE,width=min(e.stroke_width,max(1,side//2)))
                if ratio is not None and ratio > 0:
                    d.arc(rect,-90,-90+ratio*360,fill=e.color,width=min(e.stroke_width,max(1,side//2)))
            if e.show_label and e.label:
                label_h = min(e.label_size+8, max(1,box[3]//3))
                draw_text(layer,e.label,e,(box[0],box[1],box[2],label_h),e.label_size)
                box = (box[0],box[1]+label_h,box[2],max(1,box[3]-label_h))
            if e.show_value:
                draw_text(layer,formatted(value,e.binding),e,box)
        elif e.kind == 'chart':
            points = []
            if selected:
                key = e.binding.metric if e.binding.collection == 'metrics' else f'{e.binding.collection}:{e.binding.target}:{e.binding.metric}'
                source = next((s for s in selected if bound_value(e.binding,[s]) is not None),selected[0])
                points = (history or {}).get(source.source_id,{}).get(key,[])[-120:]
            previous = None
            for index, (_, sample) in enumerate(points):
                if sample is None or not isinstance(sample,(int,float)) or not math.isfinite(sample):
                    previous = None
                    continue
                x = index*(e.width-1)/max(1,len(points)-1)
                y = (1-max(0,min(1,(sample*e.binding.scale-e.min_value)/(e.max_value-e.min_value))))*(e.height-1)
                if e.chart_style == 'bar':
                    d.line((x,e.height-1,x,y),fill=e.color,width=max(1,min(e.stroke_width,e.width//max(1,len(points)))))
                elif previous is not None:
                    d.line((*previous,x,y),fill=e.color,width=e.stroke_width)
                else:
                    d.ellipse((x-1,y-1,x+1,y+1),fill=e.color)
                previous = (x,y)
            if not points or not any(p[1] is not None for p in points):
                draw_text(layer,'—',e)
            if e.height >= 48 and (e.show_value or (e.show_label and e.label)):
                header_h = min(e.label_size+8,e.height//3)
                d.rectangle((0,0,e.width-1,header_h),fill=e.background or page.background)
                label_width = e.width//2 if e.show_value else e.width
                if e.show_label and e.label:
                    draw_text(layer,e.label,e.model_copy(update={'align':'left'}),
                              (0,0,label_width,header_h),e.label_size)
                if e.show_value:
                    draw_text(layer,formatted(value,e.binding),e.model_copy(update={'align':'right'}),
                              (0,0,e.width,header_h),e.label_size)
        elif e.kind == 'shape':
            rect = (0,0,e.width-1,e.height-1)
            if e.shape == 'line':
                d.line(rect,fill=e.color,width=e.stroke_width)
            else:
                method = {'rect':d.rectangle,'rounded':d.rounded_rectangle,'ellipse':d.ellipse}[e.shape]
                options = {'radius':e.radius} if e.shape == 'rounded' else {}
                method(rect,fill=e.background or e.color,outline=e.color,width=e.stroke_width,**options)
        elif e.kind == 'clock':
            pattern = {'time':'%H:%M','time12':'%I:%M %p','date':'%d.%m.%Y','datetime':'%d.%m.%Y\n%H:%M'}[e.time_format]
            draw_text(layer,datetime.fromtimestamp(now,ZoneInfo(e.timezone)).strftime(pattern),e)
        elif e.kind == 'image':
            frame = assets.frame(e.asset_id,now,speed=e.animation_speed) if assets and e.asset_id else None
            if frame is not None:
                frame = frame.convert('RGBA')
                if e.fit == 'stretch':
                    frame = frame.resize(layer.size,Image.Resampling.LANCZOS)
                elif e.fit == 'cover':
                    frame = ImageOps.fit(frame,layer.size,method=Image.Resampling.LANCZOS)
                else:
                    frame = ImageOps.contain(frame,layer.size,method=Image.Resampling.LANCZOS)
                layer.alpha_composite(frame,((e.width-frame.width)//2,(e.height-frame.height)//2))
            else:
                draw_text(layer,'Bild wählen',e,size=min(28,e.font_size),color=MUTED)
        image.paste(layer,(e.x,e.y),layer)
    active = [a for a in alerts if a['state']=='active']
    full = [a for a in active if a['display']=='fullscreen']
    if full:
        critical = [a for a in full if a['severity']=='critical']
        candidates = critical or full
        alert = candidates[int(now//max(10,config.rotation)) % len(candidates)]
        image.paste(BG,(0,0,page.width,page.height))
        d = ImageDraw.Draw(image)
        scale = min(page.width/960,page.height/376)
        d.text((30*scale,25*scale),'KRITISCH' if critical else 'WARNUNG',font=font(max(8,round(32*scale)),bold=True),fill='#fca5a5' if critical else '#fcd34d')
        d.text((30*scale,120*scale),alert['name'][:80],font=font(max(8,round(52*scale)),bold=True),fill=FG)
        d.text((30*scale,260*scale),str(alert.get('target') or alert.get('metric') or 'Bedingung erfüllt')[:80],font=font(max(8,round(28*scale))),fill=MUTED)
    else:
        message = next((a['name'] for a in active if a['display']=='message'),None)
        if message:
            d = ImageDraw.Draw(image)
            d.rectangle((0,max(0,page.height-54),page.width-1,page.height-1),fill=BG)
            d.text((16,max(0,page.height-48)),message[:100],font=font(28),fill='#fcd34d')
        if any(a['display']=='icon' for a in active):
            badge = Image.new('RGBA',(64,64),BG)
            symbol(badge,'warning','#fcd34d',4)
            image.paste(badge,(max(0,page.width-64),0),badge)
    if demo:
        ImageDraw.Draw(image).text((8,4),'DEMO',font=font(18,bold=True),fill=MUTED)
    return image


def png(image):
    buffer = io.BytesIO()
    image.save(buffer,format='PNG')
    return buffer.getvalue()
