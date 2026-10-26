import struct
import pytest
from PIL import Image
from openscreen.protocol import encode_rgb565, frame_packets, write_all


def test_primary_colors_are_little_endian_rgb565():
    image = Image.new('RGB', (3, 1))
    image.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255)])
    assert encode_rgb565(image) == bytes.fromhex('00f8e0071f00')


def test_full_frame_offsets_cover_every_byte_once():
    frame = bytes(i % 256 for i in range(960 * 376 * 2))
    packets = list(frame_packets(frame))
    assert packets[0].hex() == 'aa55aa550500000004000f2f00040b00'
    assert packets[-1].hex() == 'aa55aa5506000000'
    assert len(packets) == 15362
    assert sum(map(len, packets)) == 906264
    assert b''.join(p[12:] for p in packets[1:-1]) == frame
    assert [struct.unpack('<I', p[8:12])[0] for p in packets[1:-1]] == list(range(0, len(frame), 47))
    with pytest.raises(ValueError):
        list(frame_packets(b'bad'))


def test_partial_writes_continue_at_correct_offset():
    class Port:
        result = bytearray()
        def write(self, data):
            self.result.extend(data[:2])
            return min(2, len(data))
    port = Port()
    write_all(port, b'abcdefg')
    assert port.result == b'abcdefg'


def test_zero_write_fails_instead_of_hanging():
    class Port:
        def write(self, data):
            return 0
    with pytest.raises(OSError):
        write_all(Port(), b'a')


def test_frame_deadline_stops_slow_partial_writer():
    class Port:
        def write(self, data):
            raise AssertionError('Expired frame must not write')
    with pytest.raises(OSError,match='deadline'):
        write_all(Port(),b'abc',deadline=0)


def test_failed_handshake_closes_port(monkeypatch):
    from openscreen.protocol import DisplayTransport
    class Port:
        closed=False
        in_waiting=1
        def reset_input_buffer(self): pass
        def write(self,data): return len(data)
        def read(self,size): return b'X'
        def close(self): self.closed=True
    port=Port()
    monkeypatch.setattr('serial.Serial',lambda *a,**k:port)
    monkeypatch.setattr('openscreen.protocol.time.sleep',lambda _:None)
    transport=DisplayTransport('test-device')
    with pytest.raises(OSError,match='acknowledged'):
        transport.connect()
    assert port.closed
    assert transport.port is None
