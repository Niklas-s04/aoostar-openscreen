from PIL import Image, ImageChops
from openscreen.models import Config, Page, Element, Binding, Snapshot
from openscreen.render import render, bound_value, draw_text, font
from openscreen.templates import TEMPLATES, template_page, FONTS, SYMBOLS


def canvas(elements, snapshots=None, **kwargs):
    config = Config(pages=[Page(id='test',name='Test',background='#000000',elements=elements)])
    return render(config,snapshots or {},[],'test',100,**kwargs)


def test_templates_valid_independent_and_readable():
    for t in TEMPLATES:
        Page.model_validate(t['page'])
    a = template_page('system')
    a['elements'][0]['binding']['metric'] = 'changed'
    assert template_page('system')['elements'][0]['binding']['metric'] == 'cpu'
    assert min(e['font_size'] for e in a['elements']) >= 96
    assert min(e['label_size'] for e in a['elements']) >= 28
    assert template_page('unknown')['elements'] == []
    assert template_page('system')['elements'][2]['binding']['unit'] == '°C'


def test_glyph_bounds_alignment_and_all_fonts():
    for family in FONTS:
        for bold,italic in [(False,False),(True,True)]:
            e = Element(id='t',text='Ag',font=family['id'],font_size=40,bold=bold,italic=italic,
                        align='right',vertical='bottom',width=200,height=100)
            layer = Image.new('RGBA',(200,100))
            draw_text(layer,e.text,e)
            bbox = layer.getbbox()
            assert bbox and bbox[2] >= 195 and bbox[3] >= 97


def test_text_clips_at_own_bounds_and_layer_order():
    e = Element(id='t',text='M'*100,x=30,y=20,width=40,height=40,font_size=80,color='#ffffff')
    image = canvas([e])
    bbox = image.getbbox()
    assert bbox and bbox[0] >= 30 and bbox[1] >= 20 and bbox[2] <= 70 and bbox[3] <= 60
    shape = Element(id='s',kind='shape',shape='rect',x=30,y=20,width=40,height=40,color='#ff0000')
    assert canvas([e,shape]).getpixel((40,30)) == (255,0,0)


def test_bindings_scaling_target_and_unknown():
    snap = Snapshot(source_id='local',observed_at=100,metrics={'cpu':12.5},
                    pools=[{'id':'1','name':'tank','percent':30}],
                    workloads=[{'id':'svc','state':'running'}])
    assert bound_value(Binding(metric='cpu',scale=2),[snap]) == 25
    assert bound_value(Binding(collection='pools',metric='percent',target='tank'),[snap]) == 30
    assert bound_value(Binding(collection='pools',metric='percent'),[snap]) is None
    assert bound_value(Binding(collection='workloads',metric='state',target='svc'),[snap]) == 'running'
    e = Element(id='m',kind='metric')
    missing = canvas([e])
    stale = snap.model_copy(update={'observed_at':0})
    assert canvas([e],{'local':stale}).tobytes() == missing.tobytes()
    zero = snap.model_copy(update={'metrics':{'cpu':0}})
    assert canvas([e],{'local':zero}).tobytes() != missing.tobytes()


def test_chart_gap_does_not_connect_or_draw_zero():
    snap = Snapshot(source_id='local',observed_at=100,metrics={'cpu':50})
    e = Element(id='c',kind='chart',width=101,height=101,stroke_width=2)
    image = canvas([e],{'local':snap},history={'local':{'cpu':[[1,50],[2,None],[3,50]]}})
    assert image.getpixel((50,50)) == (0,0,0)
    continuous = canvas([e],{'local':snap},history={'local':{'cpu':[[1,50],[2,50],[3,50]]}})
    assert continuous.getpixel((50,50)) == (255,255,255)
    assert image.getpixel((50,100)) == (0,0,0)


def test_image_frame_speed_and_fit():
    class Assets:
        def frame(self,id,now,speed=1):
            assert id == 'a'*32 and now == 100 and speed == 2
            return Image.new('RGBA',(20,10),'red')
    e = Element(id='i',kind='image',asset_id='a'*32,width=100,height=100,animation_speed=2)
    image = canvas([e],assets=Assets())
    assert image.getpixel((50,5)) == (0,0,0)
    assert image.getpixel((50,50)) == (255,0,0)


def test_all_element_kinds_symbols_and_alarm_precedence():
    for kind in ('text','metric','icon','bar','ring','chart','shape','clock','image'):
        assert canvas([Element(id='e',kind=kind)]).mode == 'RGB'
    for item in SYMBOLS:
        assert canvas([Element(id='e',kind='icon',symbol=item['id'])]).getbbox()
    config = Config()
    warning = dict(state='active',display='fullscreen',severity='warning',name='warning')
    critical = dict(state='active',display='fullscreen',severity='critical',name='critical')
    for now in (100,120,140):
        a = render(config,{},[warning,critical],'system',now)
        b = render(config,{},[critical],'system',now)
        assert a.tobytes() == b.tobytes()


def test_minimum_geometry_for_every_kind():
    for kind in ('text','metric','icon','bar','ring','chart','shape','clock','image'):
        e = Element(id='e',kind=kind,width=1,height=1,x=959,y=375,label='Tiny',show_label=True)
        assert canvas([e]).size == (960,376)
    for shape in ('rect','rounded','ellipse','line'):
        assert canvas([Element(id='e',kind='shape',shape=shape,width=1,height=1)]).size == (960,376)


def test_gauge_labels_change_output():
    for kind in ('bar','ring'):
        e = Element(id='g',kind=kind,label='CPU',width=240,height=200,show_label=False)
        unlabeled = canvas([e])
        labeled = canvas([e.model_copy(update={'show_label':True})])
        assert labeled.tobytes() != unlabeled.tobytes()


def test_aggregate_collection_bindings_preserve_available_legacy_data():
    first = Snapshot(source_id='a',pools=[{'used':25,'total':100}],
                     workloads=[{'state':'running'},{'state':'stopped'},{'state':'running','kind':'node'}])
    second = Snapshot(source_id='b',pools=[{'used':225,'total':900}],
                      workloads=[{'state':'RUNNING'}])
    pools = Binding(collection='pools',target='*',metric='percent')
    running = Binding(collection='workloads',target='*',metric='running')
    assert bound_value(pools,[first,second]) == 25
    assert bound_value(running,[first,second]) == 2
    assert bound_value(running.model_copy(update={'scale':2}),[first,second]) == 4
    invalid = Snapshot(source_id='bad',pools=[{'percent':0}],workloads=[{'state':'unknown'}])
    assert bound_value(pools,[first,invalid]) is None
    assert bound_value(running,[first,invalid]) is None
    assert bound_value(pools,[]) is None
    assert bound_value(running,[Snapshot(source_id='empty')]) is None
    assert template_page('storage')['elements'][0]['binding']['target'] == '*'
    assert template_page('services')['elements'][0]['binding']['metric'] == 'running'


def test_collection_chart_history_key_scale_and_gaps():
    snap = Snapshot(source_id='local',observed_at=100,pools=[{'id':'tank','percent':25}])
    e = Element(id='c',kind='chart',width=101,height=101,stroke_width=2,
                binding=Binding(collection='pools',target='tank',metric='percent',scale=2))
    history = {'local':{'pools:tank:percent':[[1,25],[2,25],[3,25]]}}
    image = canvas([e],{'local':snap},history=history)
    assert image.getpixel((50,50)) == (255,255,255)
    history['local']['pools:tank:percent'][1][1] = None
    image = canvas([e],{'local':snap},history=history)
    assert image.getpixel((50,50)) == (0,0,0)
