import os, importlib
from fastapi.testclient import TestClient


def test_api_auth_health_and_cookie_bootstrap(tmp_path, monkeypatch):
    monkeypatch.setenv('BROODBENCH_DATA',str(tmp_path));monkeypatch.setenv('BROODBENCH_ADMIN_TOKEN','test-token')
    import app;importlib.reload(app);client=TestClient(app.app)
    assert client.get('/api/health').status_code==200
    assert client.get('/api/providers').status_code==401
    assert client.get('/api/providers',headers={'Authorization':'Bearer test-token'}).status_code==200
    response=client.get('/?token=test-token',follow_redirects=False)
    assert response.status_code==303 and response.headers['location']=='/login'
    assert client.get('/',follow_redirects=False).status_code==303 and client.get('/login').status_code==200


def test_provider_mutations_reject_cross_origin(tmp_path,monkeypatch):
    monkeypatch.setenv('BROODBENCH_DATA',str(tmp_path));monkeypatch.setenv('BROODBENCH_ADMIN_TOKEN','test-token')
    import app;importlib.reload(app);client=TestClient(app.app)
    r=client.post('/api/providers',headers={'Authorization':'Bearer test-token','Origin':'https://evil.test'},json={'name':'x','kind':'openai','base_url':'http://127.0.0.1:8000'})
    assert r.status_code==403
