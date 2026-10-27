"""Trusted, bundled display adapters. Discovery never loads executable plugins."""
from dataclasses import asdict, dataclass
from io import BytesIO
from types import MappingProxyType

from .protocol import DisplayTransport, encode_rgb565, frame_packets, write_all, ON

MAX_PIXELS = 8_294_400


@dataclass(frozen=True)
class Mode:
    id: str
    width: int
    height: int
    pixel_format: str

    def __post_init__(self):
        if (not self.id or len(self.id) > 64 or type(self.width) is not int
                or type(self.height) is not int or not 64 <= self.width <= 3840
                or not 64 <= self.height <= 3840 or self.width*self.height > MAX_PIXELS
                or self.pixel_format not in ('rgb565-le', 'rgb888', 'png-rgb')):
            raise ValueError('Invalid display mode')


@dataclass(frozen=True)
class Capabilities:
    adapter_id: str
    version: str
    device_id: str
    modes: tuple[Mode, ...]
    max_frame_bytes: int
    size_source: str = 'adapter-profile'
    probe_status: str = 'unverified'
    rotations: tuple[int, ...] = (0, 90, 180, 270)
    partial_frames: bool | None = None
    brightness: bool | None = None

    def __post_init__(self):
        if (not self.adapter_id or len(self.adapter_id) > 64 or not self.version
                or len(self.version) > 32 or len(self.device_id) > 250
                or not 1 <= len(self.modes) <= 32
                or len({m.id for m in self.modes}) != len(self.modes)
                or type(self.max_frame_bytes) is not int
                or not 1 <= self.max_frame_bytes <= MAX_PIXELS*4+65536
                or self.size_source not in ('device-report','kernel-mode','adapter-profile','player-viewport','manual')
                or self.probe_status not in ('unverified','protocol-confirmed','physically-confirmed')
                or not self.rotations or len(self.rotations)>4
                or any(type(r) is not int or r not in (0,90,180,270) for r in self.rotations)):
            raise ValueError('Invalid display capabilities')

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError('Missing display capabilities')
        data = dict(data)
        modes = data.get('modes')
        if not isinstance(modes, (list, tuple)) or len(modes) > 32:
            raise ValueError('Invalid display modes')
        try:
            data['modes'] = tuple(Mode(**m) for m in modes)
            data['rotations'] = tuple(data.get('rotations',(0,90,180,270)))
            return cls(**data)
        except (TypeError, KeyError) as exc:
            raise ValueError('Invalid display capabilities') from exc

    def select(self, width, height, mode_id='', pixel_format='', rotation=0):
        matches = [m for m in self.modes if (m.width,m.height)==(width,height)
                   and (not mode_id or m.id==mode_id)
                   and (not pixel_format or m.pixel_format==pixel_format)]
        if len(matches)!=1 or rotation not in self.rotations:
            raise ValueError('Output mode is not supported by the selected adapter')
        return matches[0]

    def validate_frame(self, mode, frame):
        if mode not in self.modes or len(frame)>self.max_frame_bytes:
            raise ValueError('Unsupported or oversized frame')
        sizes = {'rgb565-le':2, 'rgb888':3}
        if mode.pixel_format in sizes:
            if len(frame)!=mode.width*mode.height*sizes[mode.pixel_format]:
                raise ValueError('Wrong frame size')
        else:
            from PIL import Image
            try:
                with Image.open(BytesIO(frame)) as image:
                    if image.format!='PNG' or image.mode!='RGB' or image.size!=(mode.width,mode.height):
                        raise ValueError('Invalid PNG frame')
                    image.verify()
            except (OSError,SyntaxError) as exc:
                raise ValueError('Invalid PNG frame') from exc


class Adapter:
    id = ''
    version = '1'
    broker_serial = False
    baudrate = 1500000

    def matches_usb(self, vendor, product):
        return False

    def probe_connection(self, transport, deadline):
        raise ValueError('Adapter does not support serial probing')

    def discover(self):
        return []

    def probe(self, device_id=''):
        # Passive capabilities are deliberately not a physical acceptance test.
        return self.get_capabilities(device_id)

    def encode(self, image, capabilities, mode):
        if image.size!=(mode.width,mode.height):
            raise ValueError('Image does not match negotiated mode')
        image = image.convert('RGB')
        if mode.pixel_format=='rgb565-le':
            frame = encode_rgb565(image)
        elif mode.pixel_format=='rgb888':
            frame = image.tobytes()
        else:
            stream = BytesIO()
            image.save(stream, format='PNG')
            frame = stream.getvalue()
        capabilities.validate_frame(mode, frame)
        return frame

    def send_frame(self, transport, image):
        transport.send(image)

    def send_encoded(self, transport, frame, mode, deadline):
        """Broker-owned connection; only a bundled adapter defines its wire protocol."""
        raise ValueError('Adapter does not support broker transport')

    def close(self, transport):
        transport.close()


class AoostarAdapter(Adapter):
    id = 'aoostar'
    broker_serial = True

    def matches_usb(self, vendor, product):
        return (vendor,product)==('0416','90a1')

    def probe_connection(self, transport, deadline):
        transport.reset_input_buffer()
        write_all(transport, ON, deadline)
        if b'A' not in transport.read(64):
            raise OSError('Display handshake not acknowledged')

    def discover(self):
        from .discovery import serial_displays
        return serial_displays()

    def get_capabilities(self, device_id='', **_):
        return Capabilities(self.id,self.version,device_id,
                            (Mode('960x376-rgb565',960,376,'rgb565-le'),),721920)

    def open(self, device):
        return DisplayTransport(device)

    def send_encoded(self, transport, frame, mode, deadline):
        for packet in frame_packets(frame):
            write_all(transport, packet, deadline)


class BrowserAdapter(Adapter):
    id = 'browser'

    def get_capabilities(self, device_id='', width=960, height=376, size_source='manual'):
        return Capabilities(self.id,self.version,device_id,
                            (Mode(f'{width}x{height}-png',width,height,'png-rgb'),),
                            MAX_PIXELS*4+65536,size_source)

    def open(self, device):
        raise ValueError('Browser frames are delivered by the network player')


class AdapterRegistry:
    def __init__(self, adapters):
        items = tuple(adapters)
        if len({a.id for a in items}) != len(items) or any(not a.id for a in items):
            raise ValueError('Duplicate or invalid adapter ID')
        self.adapters = MappingProxyType({a.id:a for a in items})

    def get(self, adapter_id):
        try:
            return self.adapters[adapter_id]
        except KeyError:
            raise ValueError('Unknown trusted output adapter') from None


ADAPTERS = AdapterRegistry((AoostarAdapter(),BrowserAdapter()))
