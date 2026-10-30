"""Real HTTP transport fixtures verify harness plumbing, not model quality."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from storage import Storage
from providers import ProviderService
from runner import Runner


class FixtureHandler(BaseHTTPRequestHandler):
    seen=[]
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.seen.append(body)
        tools=[m for m in body['messages'] if m['role']=='tool']
        if body.get('tools') and len(tools)<2:
            name='move_asset' if not tools else 'get_asset'
            args={'asset':'asset-001','destination':'site-1'} if not tools else {'asset':'asset-001'}
            message={'content':None,'tool_calls':[{'id':'t'+str(len(tools)),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}
        else:message={'content':'value' if not tools else 'Verified site-1'}
        message['role']='assistant'
        raw=json.dumps({'choices':[{'message':message,'finish_reason':'stop'}],'usage':{'prompt_tokens':11,'completion_tokens':2}}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)


@pytest.fixture
def local_server():
    FixtureHandler.seen=[]
    server=ThreadingHTTPServer(('127.0.0.1',0),FixtureHandler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown();thread.join()


def setup(tmp_path,url):
    s=Storage(str(tmp_path/'db.sqlite'));p=ProviderService(s,secret='fixture-test-encryption-key')
    provider=p.create({'name':'HTTP fixture','kind':'openai','base_url':url})
    with s.connect() as c:c.execute('insert into models values(?,?,?,?,?,?,?,?)',('m',provider['id'],'Fixture','fixture','fixture','Q8',32768,''))
    return s,p


def cases():
    answer=dict(id='answer-fixture',track='recall',context_size=128,messages=[{'role':'user','content':'Return value exactly.'}],expected={'answer':'value'},kind='answer',max_steps=1)
    agent=dict(id='agent-fixture',family='agent-readback',track='agent',context_size=128,messages=[{'role':'user','content':'Move asset-001 from site-0 to site-1 and independently read back.'}],expected={'world':{'asset-001':'site-1'}},kind='agent',max_steps=6,world={'assets':{'asset-001':'site-0'},'protected':['production']})
    return [answer,agent]


def wait_done(r,rid):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        state=r.get(rid)
        if state['status'] not in ('queued','running'):return state
        time.sleep(.03)
    raise AssertionError('runner did not finish')


def test_real_http_runner_executes_tools_and_populates_evidence(tmp_path,local_server,monkeypatch):
    import runner
    monkeypatch.setattr(runner,'generate_cases',lambda *args:cases())
    s,p=setup(tmp_path,local_server);r=Runner(s,p)
    result=wait_done(r,r.create({'model_ids':['m'],'context_sizes':[128],'repeats':2,'max_calls':20,'max_tokens':32})['id'])
    assert result['status']=='done'
    assert result['progress']=={'done':4,'total':4}
    assert all(x['status']=='pass' for x in result['results']),result['results']
    agents=[x for x in result['results'] if x['track']=='agent']
    assert len(agents)==2 and all([e['operation'] for e in a['events']]==['move_asset','get_asset'] for a in agents)
    assert all(x['prompt_tokens'] and x['completion_tokens'] for x in result['results'])
    summary=result['summary'][0]
    assert (summary['passed'],summary['failed'],summary['errors'],summary['total'])==(4,0,0,4)
    assert summary['by_track']['agent']['passed']==2
    assert summary['tokens']>0


def test_call_limit_stops_campaign_and_keeps_results(tmp_path,local_server,monkeypatch):
    import runner
    monkeypatch.setattr(runner,'generate_cases',lambda *args:cases())
    s,p=setup(tmp_path,local_server);r=Runner(s,p)
    result=wait_done(r,r.create({'model_ids':['m'],'context_sizes':[128],'max_calls':1})['id'])
    assert result['status']=='budget_exhausted'
    assert result['progress']=={'done':1,'total':2}


def test_validation_rejects_bad_types_and_context_over_model_limit(tmp_path,local_server):
    s,p=setup(tmp_path,local_server);r=Runner(s,p)
    for config in ({'repeats':True},{'temperature':True},{'max_tokens':0},{'context_sizes':[32769]},{'suite':'extended','context_sizes':[4096,8192,16384,32768],'repeats':10,'max_tokens':1024}):
        with pytest.raises(ValueError):r.create({'model_ids':['m'],**config})


def test_paid_consent_rejected_without_network(tmp_path,monkeypatch):
    s,p=setup(tmp_path,'http://127.0.0.1:9191')
    with s.connect() as c:c.execute("update providers set kind='openrouter',base_url='https://openrouter.ai/api/v1'")
    r=Runner(s,p)
    with pytest.raises(ValueError,match='allow_paid'):r.create({'model_ids':['m']})
