import io
import pytest
from PIL import Image
from pydantic import ValidationError
from openscreen.models import Output, Page, Element, Config
from openscreen.outputs import prepare_frame
from tests.test_app import client_for


def test_target_capabilities_and_canvas_pixel_budget():
    with pytest.raises(ValidationError):
        Output(kind='aoostar',width=1280,height=720)
    with pytest.raises(ValidationError):
        Page(id='large',name='Large',width=3840,height=3840,elements=[])
    page=Page(id='portrait',name='Portrait',width=1080,height=1920,
              elements=[Element(id='clock',kind='clock',y=1000,width=1080,height=400)])
    assert Config(pages=[page]).pages[0].height==1920


def test_rotation_and_fit_are_separate_from_canvas():
    image=Image.new('RGB',(64,128),'red')
    image.putpixel((0,0),(0,255,0))
    turned=prepare_frame(image,Output(kind='browser',width=128,height=64,rotation=90))
    assert turned.size==(128,64) and turned.getpixel((127,0))==(0,255,0)
    contained=prepare_frame(image,Output(kind='browser',width=128,height=128))
    assert contained.getpixel((0,64))==(0,0,0)
    assert contained.getpixel((64,64))==(255,0,0)
    covered=prepare_frame(image,Output(kind='browser',width=128,height=128,fit='cover'))
    assert covered.getpixel((0,64))==(255,0,0)


def test_native_draft_and_network_output_have_independent_dimensions(tmp_path):
    with client_for(tmp_path,demo=True) as client:
        headers={'X-OpenScreen':'1'}
        config=client.get('/api/config').json()
        config['output']={'kind':'browser','width':1280,'height':720}
        config['pages']=[{'id':'custom','name':'Custom','width':800,'height':480,
                          'elements':[{'id':'text','kind':'text','text':'CUSTOM'}]}]
        assert client.put('/api/config',json=config,headers=headers).status_code==200
        draft=client.post('/api/editor/preview',json=config['pages'][0],headers=headers)
        assert Image.open(io.BytesIO(draft.content)).size==(800,480)
        output=client.get('/api/output.png')
        assert Image.open(io.BytesIO(output.content)).size==(1280,720)
        assert client.get('/api/status').json()['display']['state']=='player'


def test_browser_output_never_opens_serial_device(tmp_path,monkeypatch):
    from openscreen.runtime import Runtime
    runtime=Runtime(tmp_path,'unused')
    runtime.config=Config(hardware_enabled=True,output=Output(kind='browser'))
    def forbidden(*args):
        raise AssertionError('Serial device opened by network output')
    monkeypatch.setattr('openscreen.runtime.open_transport',forbidden)
    def stop(_):
        runtime.stop.set()
    monkeypatch.setattr(runtime.stop,'wait',stop)
    runtime.output()
    assert runtime.display['state']=='disabled'
