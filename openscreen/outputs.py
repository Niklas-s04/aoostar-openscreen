"""Output capabilities and the boundary between canvas pixels and transport.

Serial protocols belong in device adapters, never in the canvas renderer.
Browser clients pull the current PNG; they do not require host display access.
"""
from PIL import Image, ImageOps
from .protocol import DisplayTransport


OUTPUTS = [
    {'id':'aoostar','name':'AOOSTAR USB / Serial','transport':'serial',
     'width':960,'height':376,'pixel_format':'RGB565 LE','push':True},
    {'id':'browser','name':'Browser / Network player','transport':'http-pull',
     'max_width':3840,'max_height':3840,'max_pixels':8_294_400,
     'pixel_format':'PNG RGB','push':False},
]


def prepare_frame(image, output):
    """Rotate clockwise, then fit into the target's physical pixel dimensions."""
    if output.rotation:
        image = image.rotate(-output.rotation,expand=True)
    size = (output.width,output.height)
    if image.size == size:
        return image.convert('RGB')
    if output.fit == 'cover':
        return ImageOps.fit(image,size,method=Image.Resampling.LANCZOS).convert('RGB')
    if output.fit == 'stretch':
        return image.resize(size,Image.Resampling.LANCZOS).convert('RGB')
    fitted = ImageOps.contain(image,size,method=Image.Resampling.LANCZOS)
    result = Image.new('RGB',size,'black')
    result.paste(fitted,((size[0]-fitted.width)//2,(size[1]-fitted.height)//2))
    return result


def open_transport(output, device):
    if output.kind == 'aoostar':
        return DisplayTransport(device)
    raise ValueError('This output is served through the network player')
