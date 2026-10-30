"""Full HTTP app lifecycle against a clearly labeled deterministic provider fixture."""
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import httpx
from tasks import generate_cases,known_good_response


def test_full_api_campaign_export_and_restart(tmp_path):
    cases=generate_cases('smoke',42,[256],['recall'])
    expected={json.dumps(c['messages'],sort_keys=True):known_good_response(c) for c in cases}
    class ProviderFixture(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,data):
            raw=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):self.send({'data':[{'id':'fixture-good'},{'id':'fixture-bad'}]})
        def do_POST(self):
            d=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            answer=expected.get(json.dumps(d['messages'],sort_keys=True),'FIXTURE_MISMATCH') if d['model']=='fixture-good' else 'deliberately incorrect fixture answer'
            self.send({'choices':[{'message':{'role':'assistant','content':answer},'finish_reason':'stop'}],'usage':{'prompt_tokens':256,'completion_tokens':8}})
    provider=ThreadingHTTPServer(('127.0.0.1',0),ProviderFixture)
    thread=threading.Thread(target=provider.serve_forever,daemon=True);thread.start()
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    token=secrets.token_urlsafe(24)
    env={**os.environ,'BROODBENCH_DATA':str(tmp_path),'BROODBENCH_ADMIN_TOKEN':token}
    def start():
        process=subprocess.Popen([sys.executable,'-m','uvicorn','app:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=Path(__file__).parents[1],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                if httpx.get(f'http://127.0.0.1:{port}/api/health',timeout=.3).status_code==200:return process
            except httpx.HTTPError:pass
            time.sleep(.05)
        process.terminate();raise AssertionError('HTTP app failed startup')
    process=start()
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',headers={'Authorization':'Bearer '+token},timeout=10) as client:
            assert httpx.get(f'http://127.0.0.1:{port}/api/models').status_code==401
            assert client.get('/static/app.js').status_code==200
            p=client.post('/api/providers',json={'name':'Integration fixture (not a model)','kind':'openwebui','base_url':f'http://127.0.0.1:{provider.server_port}'}).json()
            assert len(client.get('/api/providers/'+p['id']+'/models').json()['models'])==2
            mids=[]
            for suffix in ('good','bad'):
                response=client.post('/api/models',json={'name':'Fixture '+suffix,'provider_id':p['id'],'model_id':'fixture-'+suffix,'quant':'TEST FIXTURE','context_limit':32768})
                assert response.status_code==200,response.text
                mids.append(response.json()['id'])
            response=client.post('/api/runs',json={'name':'Integration fixture; not model results','model_ids':mids,'suite':'smoke','seed':42,'context_sizes':[256],'tracks':['recall'],'max_tokens':32,'max_calls':30})
            assert response.status_code==200,response.text
            rid=response.json()['id']
            for _ in range(150):
                run=client.get('/api/runs/'+rid).json()
                if run['status'] not in ('queued','running'):break
                time.sleep(.05)
            assert run['status']=='done',run
            assert run['progress']=={'done':len(cases)*2,'total':len(cases)*2}
            summary={x['name']:x for x in run['summary']}
            assert summary['Fixture good']['accuracy']==1
            assert summary['Fixture bad']['accuracy']==0
            assert all(x['errors']==0 for x in summary.values())
            assert all(x['by_context'][0]['context_size']==256 for x in summary.values())
            export=client.get('/api/runs/'+rid+'/export?format=json')
            assert 'attachment' in export.headers['content-disposition']
            assert token not in export.text
            assert client.get('/api/runs/'+rid+'/export?format=csv').status_code==200
            process.terminate();process.wait(timeout=5);process=start()
            saved=client.get('/api/runs/'+rid).json()
            assert saved['progress']==run['progress'] and saved['summary']==run['summary']
    finally:
        process.terminate();process.wait(timeout=5)
        provider.shutdown();thread.join()
