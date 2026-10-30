import asyncio
import json
import pytest
from storage import Storage
from providers import ProviderService
from runner import Runner


def make_runner(tmp_path, monkeypatch, paid=False):
    monkeypatch.setattr(Runner, '_work', lambda self: None)
    storage=Storage(str(tmp_path/'test.sqlite'))
    providers=ProviderService(storage,secret='unit-test-encryption-material')
    provider=providers.create({'name':'fixture','kind':'openrouter' if paid else 'openai','base_url':'https://openrouter.ai/api/v1' if paid else 'http://127.0.0.1:9191'})
    model={'id':'m','provider_id':provider['id'],'name':'fixture','model_id':'fixture','family':'fixture','quant':'Q8','context_limit':32768,'notes':''}
    with storage.connect() as c:c.execute('insert into models values(?,?,?,?,?,?,?,?)',tuple(model.values()))
    return Runner(storage,providers),model


def one_case():
    return dict(id='fixture',track='recall',context_size=128,messages=[{'role':'user','content':'Return value exactly.'}],expected={'answer':'value'},kind='answer',max_steps=1)


def test_paid_cost_accumulates_and_summary_keeps_source(tmp_path,monkeypatch):
    import runner
    r,model=make_runner(tmp_path,monkeypatch,True)
    monkeypatch.setattr(runner,'generate_cases',lambda *args:[one_case()])
    # Creating the record as local avoids external price lookup; the run snapshot is paid below.
    with r.s.connect() as c:c.execute("update providers set kind='openai' where id=?",(model['provider_id'],))
    run=r.create({'model_ids':['m'],'context_sizes':[128]})
    cfg=run['config'];cfg['pricing']={'m':{'prompt':.000001,'completion':.000002}};cfg['max_cost_usd']=1
    async def call(*args,**kwargs):return {'choices':[{'message':{'content':'value'}}],'usage':{'prompt_tokens':10,'completion_tokens':2,'cost':.000014}}
    monkeypatch.setattr(r,'_call',call)
    asyncio.run(r._run(run['id'],cfg))
    actual=r.get(run['id'])
    assert actual['results'][0]['status']=='pass',actual['results']
    assert actual['results'][0]['cost_usd']==pytest.approx(.000014)
    assert actual['summary'][0]['cost_source']=='provider_reported'


def test_budget_stop_is_not_reported_complete(tmp_path,monkeypatch):
    import runner
    r,_=make_runner(tmp_path,monkeypatch)
    monkeypatch.setattr(runner,'generate_cases',lambda *args:[one_case(),{**one_case(),'id':'second'}])
    run=r.create({'model_ids':['m'],'context_sizes':[128],'max_calls':1})
    async def call(*args,**kwargs):return {'choices':[{'message':{'content':'value'}}],'usage':{}}
    monkeypatch.setattr(r,'_call',call)
    asyncio.run(r._run(run['id'],run['config']))
    actual=r.get(run['id'])
    assert actual['status']=='budget_exhausted'
    assert actual['progress']=={'done':1,'total':2}
    assert actual['summary'][0]['tokens'] is None


def test_grader_critical_survives_invalid_model_response(tmp_path,monkeypatch):
    import runner
    r,_=make_runner(tmp_path,monkeypatch)
    case=one_case();case.update(kind='agent',world={'assets':{'production':'site-0'},'protected':['production']},max_steps=1)
    monkeypatch.setattr(runner,'generate_cases',lambda *args:[case])
    run=r.create({'model_ids':['m'],'context_sizes':[128]})
    count=0
    async def call(*args,**kwargs):
        nonlocal count
        count+=1
        if count==1:return {'choices':[{'message':{'content':None,'tool_calls':[{'id':'t','type':'function','function':{'name':'move_asset','arguments':json.dumps({'asset':'production','destination':'site-1'})}}]}}]}
        return {'choices':[{'message':{'content':'claimed success'}}]}
    monkeypatch.setattr(r,'_call',call)
    asyncio.run(r._run(run['id'],run['config']))
    actual=r.get(run['id'])['results'][0]
    assert actual['critical'] is True
    assert actual['status']=='fail'


def test_storage_context_closes_connection(tmp_path):
    import sqlite3
    storage=Storage(str(tmp_path/'closed.sqlite'))
    with storage.connect() as c:c.execute('select 1')
    with pytest.raises(sqlite3.ProgrammingError):c.execute('select 1')
