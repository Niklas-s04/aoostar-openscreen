"""Transient output calibration; never writes a configuration itself."""
import secrets
import time
from PIL import Image, ImageDraw
from .render import font
from .outputs import prepare_frame


class DisplayTrial:
    def __init__(self, config, seconds=60):
        self.id = secrets.token_hex(16)
        self.config = config.model_copy(deep=True)
        self.deadline = time.monotonic() + seconds
        self.sent = False

    @property
    def expired(self):
        return time.monotonic() >= self.deadline

    def status(self):
        return {'id': self.id, 'remaining': max(0, round(self.deadline-time.monotonic())),
                'sent': self.sent, 'output': self.config.output.model_dump()}


def test_pattern(output):
    width, height = output.width, output.height
    if output.rotation in (90, 270):
        width, height = height, width
    image = Image.new('RGB', (width, height), '#101012')
    draw = ImageDraw.Draw(image)
    unit = max(1, min(width, height)//100)
    draw.rectangle((0, 0, width-1, height-1), outline='white', width=unit*2)
    size = max(8, min(width//12, height//10, 64))
    for label, xy, anchor in [('1 TL',(unit*4,unit*4),'lt'),
                              ('2 TR',(width-unit*4,unit*4),'rt'),
                              ('3 BL',(unit*4,height-unit*4),'lb'),
                              ('4 BR',(width-unit*4,height-unit*4),'rb')]:
        draw.text(xy, label, font=font(size, bold=True), fill='white', anchor=anchor)
    radius = min(width, height)//6
    cx, cy = width//2, height//2
    draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius), outline='white', width=unit*2)
    draw.text((cx, height//5), f'{width} x {height}', font=font(size, bold=True), fill='white', anchor='mm')
    if width>=400 and height>=200:
        for index, scale in enumerate((0.65,1,1.35)):
            text_size=max(8,round(size*scale))
            draw.text((width//12,height*(35+index*12)//100), f'{text_size}px',
                      font=font(text_size,bold=True), fill='white', anchor='lm')
    for i, color in enumerate(['#ff0000','#00ff00','#0000ff','#ffffff','#808080','#000000']):
        left = width//5+i*width//10
        draw.rectangle((left,height*3//4,left+width//10-1,height*4//5), fill=color)
    return prepare_frame(image, output)
