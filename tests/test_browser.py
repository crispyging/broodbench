"""Browser regression tests with explicit API fixtures, not benchmark results."""
import json
import shutil
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from functools import partial
from playwright.sync_api import sync_playwright


def test_dashboard_launch_fields_and_single_point_chart():
    handler = partial(SimpleHTTPRequestHandler, directory=str(Path(__file__).parents[1]))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    captured = []
    model = dict(id='m1', provider_id='p1', name='Fixture model', model_id='fixture', family='test', quant='Q8', context_limit=32768)
    run = dict(id='r1', name='Fixture run', status='done', created_at=1, config={}, progress=dict(done=1,total=1), summary=[dict(model_id='m1',name='Fixture model',quant='Q8',passed=1,failed=0,errors=0,total=1,accuracy=1,avg_latency_s=1,tokens=15,cost_usd=None,critical_failures=0,loops=0,by_track={'recall':dict(passed=1,total=1,accuracy=1)},by_context=[dict(context_size=4096,accuracy=1,total=1)])])
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=shutil.which('google-chrome'), headless=True)
        page = browser.new_page(viewport={'width':1440,'height':1000})
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def api(route):
            path=route.request.url.split('/api/',1)[1]
            if route.request.method=='POST' and path=='runs':
                captured.append(route.request.post_data_json)
                data=run
            else:
                data={'health':{'status':'ok','version':'test'},'providers':[dict(id='p1',name='Fixture endpoint',kind='openai',base_url='http://example.test/v1',key_set=False)],'models':[model],'runs':[run],'suites':[dict(id='smoke',name='Smoke',cases=1,tracks=['recall'])],'tracks':[]}.get(path,{})
            route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
        page.route('**/api/**',api)
        page.goto(f'http://127.0.0.1:{server.server_port}/static/index.html')
        page.wait_for_selector('#launch')
        assert page.locator('main').bounding_box()['y']<150
        assert page.locator('main').bounding_box()['width']>1000
        assert page.locator('#toast').evaluate('(e)=>getComputedStyle(e).position')=='fixed'
        page.click('#launch')
        page.check('#launch-dialog .model-list input')
        page.get_by_role('button',name='Start run',exact=True).click()
        page.wait_for_timeout(300)
        assert captured, page.locator('#launch-dialog').inner_text()
        assert captured[0]['max_tokens']==1024
        assert captured[0]['timeout_s']==120
        assert captured[0]['max_calls']==100
        assert captured[0]['max_cost_usd']==1
        page.click('[data-view="compare"]')
        page.select_option('main select','r1')
        circles=page.locator('svg circle').evaluate_all('(els)=>els.map(e=>[e.getAttribute("cx"),e.getAttribute("cy")])')
        assert circles and all('NaN' not in str(x) and 'Infinity' not in str(x) for x in circles), circles
        page.click('[data-view="models"]')
        page.wait_for_selector('#model-add')
        assert page.locator('main').get_by_text('Fixture model',exact=True).count()==1
        assert not errors, errors
        browser.close()
    server.shutdown()
