"""Protocol recovered statically from AOOSTAR-X Linux 1.3.6. See analysis/PROTOKOLL.md."""
from array import array
import sys
import time

SIZE = (960, 376)
START = bytes.fromhex('AA55AA550500000004000F2F00040B00')
DATA = bytes.fromhex('AA55AA5508000000')
END = bytes.fromhex('AA55AA5506000000')
ON = bytes.fromhex('AA55AA550B000000')


def encode_rgb565(image):
    rgb = image.convert('RGB')
    pixels = rgb.get_flattened_data() if hasattr(rgb, 'get_flattened_data') else rgb.getdata()
    values = array('H', (((r & 248) << 8) | ((g & 252) << 3) | (b >> 3)
                         for r, g, b in pixels))
    if sys.byteorder != 'little':
        values.byteswap()
    return values.tobytes()


def frame_packets(frame):
    if len(frame) != SIZE[0] * SIZE[1] * 2:
        raise ValueError('Expected a 960 x 376 RGB565 frame')
    yield START
    for offset in range(0, len(frame), 47):
        yield DATA + offset.to_bytes(4, 'little') + frame[offset:offset + 47]
    yield END


def write_all(port, data, deadline=None):
    deadline = time.monotonic() + 30 if deadline is None else deadline
    remaining = memoryview(data)
    while remaining:
        if time.monotonic() >= deadline:
            raise OSError('Serial frame deadline exceeded')
        written = port.write(remaining)
        if not written or written < 0 or written > len(remaining):
            raise OSError('Incomplete serial write')
        remaining = remaining[written:]


class DisplayTransport:
    def __init__(self, device='auto'):
        self.device = device
        self.port = None

    def connect(self):
        import serial
        from serial.tools.list_ports import comports
        device = self.device
        if device == 'auto':
            matches = [p.device for p in comports() if (p.vid, p.pid) == (0x0416, 0x90a1)]
            if len(matches) != 1:
                raise OSError('Select one display device explicitly')
            device = matches[0]
        self.port = serial.Serial(device, 1500000, timeout=1, write_timeout=1,
                                  bytesize=8, parity='N', stopbits=1)
        try:
            self.port.reset_input_buffer()
            write_all(self.port, ON)
            time.sleep(1)
            reply = self.port.read(max(1, self.port.in_waiting))
            if b'A' not in reply:
                raise OSError('Display handshake not acknowledged')
        except Exception:
            self.close()
            raise

    def send(self, image):
        if image.size != SIZE:
            raise ValueError('Wrong display dimensions')
        if self.port is None:
            self.connect()
        try:
            deadline = time.monotonic() + 30
            for packet in frame_packets(encode_rgb565(image)):
                write_all(self.port, packet, deadline)
        except Exception:
            self.close()
            raise

    def close(self):
        if self.port is not None:
            self.port.close()
            self.port = None
