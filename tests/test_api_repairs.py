import importlib
import json
from fastapi.testclient import TestClient


def client_for(tmp_path,monkeypatch):
    monkeypatch.setenv('BROODBENCH_DATA',str(tmp_path))
    monkeypatch.setenv('BROODBENCH_ADMIN_TOKEN','test-dashboard-session')
    import app
    importlib.reload(app)
    return TestClient(app.app,headers={'Authorization':'Bearer test-dashboard-session'}),app


def test_model_validation_and_referenced_delete(tmp_path,monkeypatch):
    client,app=client_for(tmp_path,monkeypatch)
    assert client.post('/api/models',json={'name':'X','provider_id':'missing','model_id':'x'}).status_code==400
    p=client.post('/api/providers',json={'name':'Fixture','kind':'openai','base_url':'http://127.0.0.1:19999'}).json()
    assert client.post('/api/models',json={'name':'X','provider_id':p['id'],'model_id':'x','context_limit':'nonsense'}).status_code==400
    m=client.post('/api/models',json={'name':'X','provider_id':p['id'],'model_id':'x'}).json()
    with app.store.connect() as c:
        c.execute('insert into runs(id,name,status,created_at,config) values(?,?,?,?,?)',('r','fixture','queued',0,json.dumps({'model_ids':[m['id']]})))
    assert client.delete('/api/models/'+m['id']).status_code==409


def test_authenticated_assets_and_csv_formula(tmp_path,monkeypatch):
    client,app=client_for(tmp_path,monkeypatch)
    assert client.get('/').status_code==200
    assert client.get('/static/app.js').status_code==200
    assert "style-src 'self' 'unsafe-inline'" in client.get('/').headers['content-security-policy']
    with app.store.connect() as c:
        c.execute('insert into runs(id,name,status,created_at,config) values(?,?,?,?,?)',('r','fixture','done',0,'{}'))
        c.execute('insert into results values(?,?,?,?,?)',('x','r','m','c',json.dumps({'response':'=HYPERLINK("bad")','model_id':'m','case_id':'c'})))
    res=client.get('/api/runs/r/export?format=csv')
    assert "'=HYPERLINK" in res.text
