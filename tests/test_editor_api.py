import io

from PIL import Image
from tests.test_app import client_for


HEADERS = {'X-OpenScreen':'1'}


def test_draft_is_unsaved_and_uses_canonical_renderer(tmp_path):
    with client_for(tmp_path, demo=True) as client:
        catalog = client.get('/api/editor/catalog').json()
        assert catalog['width'] == 960 and len(catalog['templates']) >= 8
        config = client.get('/api/config').json()
        page = config['pages'][0]
        page['elements'] = [{'id':'text','kind':'text','text':'HELLO','font_size':80}]
        preview = client.post('/api/editor/preview', json=page, headers=HEADERS)
        assert preview.status_code == 200
        assert client.get('/api/config').json()['pages'][0] != page
        assert client.put('/api/config',json=config,headers=HEADERS).status_code == 200
        assert preview.content == client.get('/api/preview.png').content


def test_media_lifecycle_and_referenced_asset_protection(tmp_path):
    with client_for(tmp_path, demo=True) as client:
        data=io.BytesIO()
        Image.new('RGB',(40,20),'red').save(data,format='PNG')
        uploaded=client.post('/api/assets?name=sample.png',content=data.getvalue(),headers=HEADERS)
        assert uploaded.status_code == 200
        asset=uploaded.json()
        assert client.get('/api/assets').json()[0]['id']==asset['id']
        assert client.get('/api/assets/'+asset['id']).headers['content-type']=='image/png'
        config=client.get('/api/config').json()
        config['pages'][0]['elements']=[{'id':'photo','kind':'image','asset_id':asset['id']}]
        assert client.put('/api/config',json=config,headers=HEADERS).status_code==200
        assert client.delete('/api/assets/'+asset['id'],headers=HEADERS).status_code==409
        config['pages'][0]['elements']=[]
        assert client.put('/api/config',json=config,headers=HEADERS).status_code==200
        assert client.delete('/api/assets/'+asset['id'],headers=HEADERS).status_code==200
        assert client.get('/api/assets/'+asset['id']).status_code==404


def test_actual_body_limit_and_upload_origin(tmp_path):
    with client_for(tmp_path,demo=True) as client:
        assert client.post('/api/assets',content=b'x').status_code==403
        response=client.put('/api/config',content=iter([b'x'*600000,b'x'*600000]),headers=HEADERS)
        assert response.status_code==413


def test_history_bounded_and_failed_samples_are_gaps(tmp_path):
    from openscreen.runtime import Runtime
    from openscreen.models import Snapshot
    runtime=Runtime(tmp_path,'unused',demo=True)
    for i in range(130):
        runtime.record_history('local',Snapshot(source_id='local',metrics={'cpu':20},ok=i!=129),i)
    assert len(runtime.history['local']['cpu'])==120
    assert runtime.history['local']['cpu'][-1]==[129,None]
