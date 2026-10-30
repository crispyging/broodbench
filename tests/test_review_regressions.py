import importlib
import json
import time
from fastapi.testclient import TestClient
from storage import Storage
from providers import ProviderService
from runner import Runner


def test_chunked_body_is_bounded(tmp_path,monkeypatch):
    monkeypatch.setenv('BROODBENCH_DATA',str(tmp_path))
    monkeypatch.setenv('BROODBENCH_ADMIN_TOKEN','fixture-admin-session')
    import app
    importlib.reload(app)
    client=TestClient(app.app,headers={'Authorization':'Bearer fixture-admin-session'})
    def chunks():
        for _ in range(18):yield b'x'*65536
    response=client.post('/api/providers',content=chunks(),headers={'Content-Type':'application/json'})
    assert response.status_code==413


def test_cancelled_queue_cannot_be_claimed(tmp_path,monkeypatch):
    monkeypatch.setattr(Runner,'_work',lambda self:None)
    storage=Storage(str(tmp_path/'db.sqlite'));providers=ProviderService(storage,secret='fixture-encryption-material')
    r=Runner(storage,providers)
    with storage.connect() as c:
        c.execute('insert into runs(id,name,status,created_at,config) values(?,?,?,?,?)',('run','fixture','queued',time.time(),'{}'))
        c.execute('insert into queue(run_id,config) values(?,?)',('run','{}'))
    assert r.stop('run')
    assert r._claim('run') is False
    assert r.get('run')['status']=='cancelled'
