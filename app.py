import os, secrets, hmac, json, csv, io
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Response, Depends
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from providers import ProviderService, ProviderError
from storage import Storage

DATA=os.environ.get('BROODBENCH_DATA','/data'); Path(DATA).mkdir(parents=True,exist_ok=True)
TOKEN=os.environ.get('BROODBENCH_ADMIN_TOKEN')
if not TOKEN:
    tokenfile=Path(DATA)/'admin.token'
    if tokenfile.exists(): TOKEN=tokenfile.read_text().strip()
    else:
        TOKEN=secrets.token_urlsafe(32); fd=os.open(tokenfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:f.write(TOKEN+'\n')
store=Storage(DATA); providers=ProviderService(store); app=FastAPI()

def authorized(request):
    cookie=request.cookies.get('broodbench_session','')
    bearer=request.headers.get('authorization','')
    return (bool(cookie) and hmac.compare_digest(cookie,TOKEN)) or (bearer.startswith('Bearer ') and hmac.compare_digest(bearer[7:],TOKEN))
async def auth(request:Request):
    if request.url.path!='/api/health' and not authorized(request): raise HTTPException(401,'Authentication required')
@app.middleware('http')
async def security_mw(request, call_next):
    if request.method in ('POST','PUT','PATCH') and request.headers.get('content-length'):
        try:
            if int(request.headers['content-length']) > 1048576: return JSONResponse({'detail':'Request too large'},413)
        except ValueError: return JSONResponse({'detail':'Invalid content length'},400)
    if request.method in ('POST','PUT','PATCH','DELETE'):
        limit=4096 if request.url.path=='/login' else 1048576
        body=bytearray()
        async for chunk in request.stream():
            if len(body)+len(chunk)>limit: return JSONResponse({'detail':'Request too large'},413)
            body.extend(chunk)
        request._body=bytes(body)
    response=await auth_mw(request, call_next)
    response.headers['X-Content-Type-Options']='nosniff'; response.headers['X-Frame-Options']='DENY'; response.headers['Referrer-Policy']='no-referrer'; response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response
async def auth_mw(request,call_next):
    if request.url.path.startswith('/api/') and request.url.path!='/api/health' and not authorized(request): return JSONResponse({'detail':'Authentication required'},401)
    if request.method in ('POST','PUT','PATCH','DELETE'):
        from urllib.parse import urlsplit
        origin=request.headers.get('origin'); host=request.headers.get('host','')
        if origin and (urlsplit(origin).netloc!=host or urlsplit(origin).scheme not in ('http','https')): return JSONResponse({'detail':'Cross-origin mutation denied'},403)
        if request.headers.get('sec-fetch-site') in ('cross-site','none'): return JSONResponse({'detail':'Cross-origin mutation denied'},403)
    return await call_next(request)
@app.get('/api/health')
def health():return {'status':'ok','version':'0.1.0'}
@app.get('/')
def root(request:Request):
    if not authorized(request): return RedirectResponse('/login',303)
    return FileResponse(Path(__file__).parent/'static'/'index.html')
@app.get('/static/{path:path}')
def static_asset(path, request:Request):
    if not authorized(request): raise HTTPException(401,'Authentication required')
    base=(Path(__file__).parent/'static').resolve(); target=(base/path).resolve()
    if base not in target.parents or not target.is_file(): raise HTTPException(404,'Not found')
    return FileResponse(target)
@app.get('/login')
def login_form():
    from fastapi.responses import HTMLResponse
    return HTMLResponse('<!doctype html><meta name="viewport" content="width=device-width"><title>BroodBench login</title><form method="post"><label>Admin token <input name="token" type="password" required autocomplete="current-password"></label><button>Sign in</button></form>')
@app.post('/login')
async def login(request:Request):
    origin=request.headers.get('origin')
    if origin:
        from urllib.parse import urlsplit
        if urlsplit(origin).netloc!=request.headers.get('host') or urlsplit(origin).scheme not in ('http','https'): return JSONResponse({'detail':'Cross-origin mutation denied'},403)
    if int(request.headers.get('content-length','0') or 0)>4096: return JSONResponse({'detail':'Request too large'},413)
    from urllib.parse import parse_qs
    form=parse_qs((await request.body()).decode('utf-8',errors='replace')); value=form.get('token',[''])[0]
    if not hmac.compare_digest(value,TOKEN): return JSONResponse({'detail':'Invalid token'},401)
    r=RedirectResponse('/',303);r.set_cookie('broodbench_session',TOKEN,httponly=True,samesite='strict',secure=request.url.scheme=='https',path='/');return r
@app.get('/api/providers')
def provider_list():return providers.list()
@app.post('/api/providers')
def provider_create(data:dict):
    try:return providers.create(data)
    except ProviderError as e:raise HTTPException(400,str(e))
@app.delete('/api/providers/{pid}')
def provider_delete(pid):
    with store.connect() as c:
        if c.execute('select 1 from models where provider_id=?',(pid,)).fetchone(): raise HTTPException(409,'Remove registered models before removing their provider')
    if not providers.delete(pid):raise HTTPException(404,'Not found')
    return {'ok':True}
@app.get('/api/providers/{pid}/models')
async def provider_models(pid):
    try:return await providers.models(pid)
    except ProviderError as e:raise HTTPException(400,str(e))
    except Exception:raise HTTPException(502,'Provider discovery failed')
@app.post('/api/providers/{pid}/test')
async def provider_test(pid):
    try:m=await providers.models(pid);return {'ok':True,'models_count':len(m['models']),'message':'Discovery succeeded'}
    except Exception:return {'ok':False,'models_count':0,'message':'Discovery failed'}
from tasks import suites,TRACKS
@app.get('/api/suites')
def suite_list():return suites()
@app.get('/api/tracks')
def tracks():return TRACKS
@app.get('/api/models')
def model_list():
    with store.connect() as c:return [dict(x) for x in c.execute('select * from models')]
@app.post('/api/models')
def model_create(d:dict):
    for key in ('provider_id','name','model_id'):
        if not isinstance(d.get(key),str) or not d[key].strip() or len(d[key])>500: raise HTTPException(400,'Invalid '+key)
    for key in ('family','quant','notes'):
        if not isinstance(d.get(key,''),str) or len(d.get(key,''))>4000: raise HTTPException(400,'Invalid '+key)
    try:
        limit=d.get('context_limit',32768)
        if isinstance(limit,bool) or isinstance(limit,float): raise ValueError()
        limit=int(limit)
        if not 128<=limit<=1000000: raise ValueError()
    except (ValueError,TypeError): raise HTTPException(400,'Invalid context_limit')
    if not any(p['id']==d['provider_id'] for p in store.providers()): raise HTTPException(400,'Unknown provider')
    mid=secrets.token_hex(8); vals=(mid,d['provider_id'],d['name'].strip(),d['model_id'].strip(),d.get('family',''),d.get('quant',''),limit,d.get('notes',''))
    with store.connect() as c:c.execute('insert into models values(?,?,?,?,?,?,?,?)',vals)
    return dict(id=mid,provider_id=vals[1],name=vals[2],model_id=vals[3],family=vals[4],quant=vals[5],context_limit=vals[6],notes=vals[7])
@app.delete('/api/models/{mid}')
def model_delete(mid):
    with store.connect() as c:
        for row in c.execute("select config from runs where status in ('queued','running')"):
            if mid in json.loads(row['config']).get('model_ids',[]): raise HTTPException(409,'Model is referenced by an active run')
        n=c.execute('delete from models where id=?',(mid,)).rowcount
    if not n:raise HTTPException(404,'Not found')
    return {'ok':True}
from runner import Runner
runner=Runner(store,providers)
@app.post('/api/runs')
def run_create(d:dict):
    try:return runner.create(d)
    except ValueError as e:raise HTTPException(400,str(e))
@app.get('/api/runs')
def run_list():return runner.list()
@app.get('/api/runs/{rid}')
def run_get(rid):
    x=runner.get(rid)
    if x is None:raise HTTPException(404,'Not found')
    return x
@app.post('/api/runs/{rid}/stop')
def run_stop(rid):
    if not runner.stop(rid):raise HTTPException(404,'Not found')
    return {'ok':True}
@app.get('/api/runs/{rid}/export')
def run_export(rid,format='json'):
    x=runner.get(rid)
    if x is None:raise HTTPException(404,'Not found')
    if format=='json':return JSONResponse(x,headers={'Content-Disposition':f'attachment; filename=run-{rid}.json'})
    if format!='csv':raise HTTPException(400,'format must be json or csv')
    rows=x.get('results',[]); f=io.StringIO();w=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ['id']);w.writeheader()

    for row in rows:
        for k,v in list(row.items()):
            if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')): row[k]="'"+v
    w.writerows(rows)
    return StreamingResponse(iter([f.getvalue()]),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename=run-{rid}.csv'})
