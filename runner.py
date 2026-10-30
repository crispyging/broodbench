import asyncio, copy, json, os, threading, time, uuid
import httpx
from tasks import generate_cases, evaluate, tool_definitions, execute_tool, SUITE_VERSION


class Runner:
    def __init__(self, storage, providers):
        self.s, self.p = storage, providers
        self.cancel = set(); self.active = {}; self.lock = threading.RLock()
        with self.s.connect() as c:
            c.execute("UPDATE runs SET status='interrupted' WHERE status='running'")
        self.worker = threading.Thread(target=self._work, daemon=True); self.worker.start()

    def create(self, d):
        if not isinstance(d, dict): raise ValueError('Run config must be an object')
        allowed={'name','model_ids','suite','seed','repeats','context_sizes','temperature','max_tokens','timeout_s','tracks','allow_paid','max_calls','max_cost_usd'}
        if set(d)-allowed: raise ValueError('Unknown run fields')
        cfg={'name':'Run','model_ids':None,'suite':'smoke','seed':42,'repeats':1,'context_sizes':[4096],'temperature':0.0,'max_tokens':1024,'timeout_s':120,'tracks':None,'allow_paid':False,'max_calls':100,'max_cost_usd':1.0}
        cfg.update(d)
        integer=lambda v,lo,hi: isinstance(v,int) and not isinstance(v,bool) and lo<=v<=hi
        number=lambda v,lo,hi: isinstance(v,(int,float)) and not isinstance(v,bool) and lo<=v<=hi
        if not isinstance(cfg['model_ids'],list) or not cfg['model_ids'] or len(cfg['model_ids'])>32 or any(not isinstance(x,str) or not x for x in cfg['model_ids']) or len(set(cfg['model_ids']))!=len(cfg['model_ids']): raise ValueError('Invalid model_ids')
        if cfg['suite'] not in ('smoke','core','extended') or not integer(cfg['seed'],-2147483648,2147483647) or not integer(cfg['repeats'],1,10): raise ValueError('Invalid suite, seed, or repeats')
        if not isinstance(cfg['context_sizes'],list) or not 1<=len(cfg['context_sizes'])<=8 or any(not integer(x,1,1000000) for x in cfg['context_sizes']): raise ValueError('Invalid context sizes')
        if not number(cfg['temperature'],0,2) or not integer(cfg['max_tokens'],1,32768) or not integer(cfg['timeout_s'],1,600) or not integer(cfg['max_calls'],1,10000) or not number(cfg['max_cost_usd'],0,100000): raise ValueError('Invalid numeric limits')
        if not isinstance(cfg['allow_paid'],bool) or (cfg['tracks'] is not None and (not isinstance(cfg['tracks'],list) or any(not isinstance(x,str) for x in cfg['tracks']))): raise ValueError('Invalid tracks or consent')
        with self.s.connect() as c:
            models=[dict(x) for x in c.execute('select * from models where id in (%s)'%','.join('?'*len(cfg['model_ids'])),cfg['model_ids'])]
            if len(models)!=len(cfg['model_ids']): raise ValueError('Unknown model')
        if any(any(size>m['context_limit'] for size in cfg['context_sizes']) for m in models): raise ValueError('Context exceeds model limit')
        prov={p['id']:p for p in self.s.providers()}
        paid=[m for m in models if prov.get(m['provider_id'],{}).get('kind')=='openrouter']
        if paid and not cfg['allow_paid']: raise ValueError('Paid provider requires allow_paid')
        prices={}
        for m in paid:
            try:
                with httpx.Client(timeout=8,follow_redirects=False) as client:
                    res=client.get('https://openrouter.ai/api/v1/models');res.raise_for_status()
                    entry=next(x for x in res.json()['data'] if x['id']==m['model_id'])
                    prices[m['id']]={'prompt':float(entry['pricing']['prompt']),'completion':float(entry['pricing']['completion']),'source':'openrouter_catalog','captured_at':time.time()}
                    import math
                    if not all(math.isfinite(prices[m['id']][k]) for k in ('prompt','completion')) or entry.get('pricing',{}).get('overrides'): raise ValueError()
                    if any(float(v or 0)>0 for k,v in entry['pricing'].items() if k not in ('prompt','completion','input_cache_read','input_cache_write')): raise ValueError()
                    if min(prices[m['id']]['prompt'],prices[m['id']]['completion'])<0: raise ValueError()
            except Exception as e: raise ValueError('Unable to establish paid model pricing; refusing run') from e
        small_cases=generate_cases(cfg['suite'],cfg['seed'],[128],cfg['tracks'])
        projected_bytes=sum(cfg['context_sizes'])*4*len(small_cases)*cfg['repeats']*len(models)
        if projected_bytes>128*1024*1024: raise ValueError('Campaign exceeds 128 MiB planned prompt budget; reduce tracks, contexts, repeats or models')
        if len(set(cfg['context_sizes']))!=len(cfg['context_sizes']): raise ValueError('Duplicate context sizes')
        if not isinstance(cfg['name'],str) or not cfg['name'].strip() or len(cfg['name'])>120: raise ValueError('Invalid run name')
        if not small_cases: raise ValueError('No cases selected')
        cases=generate_cases(cfg['suite'],cfg['seed'],cfg['context_sizes'],cfg['tracks'])
        cfg.update(models=models,providers=[{k:p[k] for k in ('id','name','kind','base_url')} for p in prov.values() if p['id'] in {m['provider_id'] for m in models}],suite_version=SUITE_VERSION,pricing=prices,spend_usd=0.0,spend_source='usage_or_catalog_estimate')
        rid=uuid.uuid4().hex;total=len(cases)*cfg['repeats']*len(models)
        with self.s.connect() as c:
            c.execute('insert into runs(id,name,status,created_at,config,progress_total) values(?,?,?,?,?,?)',(rid,cfg['name'],'queued',time.time(),json.dumps(cfg),total))
            c.execute('insert into queue(run_id,config) values(?,?)',(rid,json.dumps(cfg)))
        return self.get(rid)

    def _claim(self,rid):
        with self.s.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            claimed=c.execute("update runs set status='running' where id=? and status='queued'",(rid,)).rowcount==1
            c.execute('delete from queue where run_id=?',(rid,))
            return claimed

    def _work(self):
        while True:
            with self.s.connect() as c: row=c.execute('select * from queue order by id limit 1').fetchone()
            if not row: time.sleep(.1); continue
            rid=row['run_id']; cfg=json.loads(row['config'])
            if not self._claim(rid): continue
            try:
                loop=asyncio.new_event_loop();asyncio.set_event_loop(loop)
                task=loop.create_task(self._run(rid,cfg))
                with self.lock:self.active[rid]=(loop,task)
                loop.run_until_complete(task)
            except Exception:
                with self.s.connect() as c:c.execute("update runs set status='error' where id=? and status='running'",(rid,))
            finally:
                with self.lock:self.active.pop(rid,None)
                try:loop.close()
                except Exception:pass

    async def _call(self,p,model,messages,cfg,tools=None):
        self.p._url(p['kind'],p['base_url'])
        key=self.p.fernet.decrypt(p['secret']).decode() if p['secret'] else ''
        payload={'model':model['model_id'],'messages':messages,'temperature':cfg['temperature'],'max_tokens':cfg['max_tokens']}
        if tools: payload.update(tools=tools,tool_choice='auto')
        async with httpx.AsyncClient(timeout=cfg['timeout_s'],follow_redirects=False,trust_env=False) as client:
            response=await client.post(p['base_url']+'/chat/completions',headers={'Authorization':'Bearer '+key} if key else {},json=payload);response.raise_for_status();return response.json()

    async def _run(self,rid,cfg):
        cases=generate_cases(cfg['suite'],cfg['seed'],cfg['context_sizes'],cfg['tracks']);calls=0;stopped=False
        for model in cfg['models']:
            p=next((x for x in self.s.providers() if x['id']==model['provider_id']),None)
            if not p: raise RuntimeError('Configured provider missing')
            for repeat in range(cfg['repeats']):
                for case0 in cases:
                    if rid in self.cancel: stopped=True;break
                    cost_source='unknown'
                    case=copy.deepcopy(case0); start=time.monotonic();response='';events=[];usage_prompt=usage_completion=0;actual_cost=None;err=None;status='error';attempted=False;ev={'passed':False,'score':0,'critical':False,'loop':False,'details':{}}
                    try:
                        msgs=copy.deepcopy(case['messages']);world=copy.deepcopy(case.get('world',{}));steps=0
                        while True:
                            if rid in self.cancel: raise asyncio.CancelledError()
                            if calls>=cfg['max_calls']: stopped=True;break
                            price=cfg['pricing'].get(model['id']); reserve=0
                            if price:
                                # Byte count bounds UTF-8 prompt tokens; include tool/schema overhead and a safety factor.
                                prompt_bytes=len(json.dumps({'messages':msgs,'tools':tool_definitions(case)},ensure_ascii=False).encode('utf-8'))+4096
                                reserve=(prompt_bytes*price['prompt']+cfg['max_tokens']*price['completion'])*2
                                if cfg['spend_usd']+reserve>cfg['max_cost_usd']: stopped=True;break
                            if price:
                                cfg['spend_usd']+=reserve
                                actual_cost=(actual_cost or 0)+reserve
                                cost_source='conservative_reserve'
                            calls+=1; attempted=True; data=await self._call(p,model,msgs,cfg,tool_definitions(case) if case.get('kind')=='agent' else None)
                            choice=data['choices'][0]['message'];response=choice.get('content') or '';use=data.get('usage') or {};usage_prompt+=use.get('prompt_tokens',0) or 0;usage_completion+=use.get('completion_tokens',0) or 0
                            if price:
                                billed=use.get('cost')
                                if billed is not None:
                                    billed=float(billed)
                                    if not __import__('math').isfinite(billed) or billed<0: raise RuntimeError('Invalid provider cost')
                                    cost_source='provider_reported'
                                else:
                                    billed=reserve
                                    cost_source='conservative_reserve'
                                actual_cost=(actual_cost or 0)+billed-reserve
                                cfg['spend_usd']+=billed-reserve
                                if cfg['spend_usd']>cfg['max_cost_usd']: raise RuntimeError('Provider-reported spend exceeded budget')
                            tcalls=choice.get('tool_calls') or []
                            if not tcalls: break
                            if not isinstance(tcalls,list) or len(tcalls)>16: raise ValueError('Invalid or excessive tool calls')
                            steps+=1
                            if steps>case.get('max_steps',1): raise RuntimeError('Step limit reached')
                            msgs.append(choice)
                            for tc in tcalls:
                                if len(events)>=case.get('max_steps',6): raise ValueError('Tool action limit reached')
                                fn=tc['function'];args=json.loads(fn['arguments'])
                                if not isinstance(args,dict): raise ValueError('Tool arguments must be object')
                                result=execute_tool(case,world,fn['name'],args);events.append({'operation':fn['name'],'args':args,'result':result});msgs.append({'role':'tool','tool_call_id':tc['id'],'content':json.dumps(result)})
                        if stopped and calls>=cfg['max_calls']: err='Hard call limit reached'
                        if not err:
                            ev=evaluate(case,response,events,world);status='pass' if ev['passed'] else 'fail'
                    except asyncio.CancelledError:
                        status='cancelled';err='Cancelled';stopped=True
                    except Exception as e:
                        err=type(e).__name__
                        if isinstance(e,httpx.HTTPStatusError): err+=' HTTP '+str(e.response.status_code)
                        ev=evaluate(case,response,events,world)
                        if isinstance(e,(ValueError,KeyError,TypeError,IndexError)):
                            status='fail';ev['score']=0
                        if isinstance(e,RuntimeError) and str(e)=='Step limit reached':
                            status='fail';ev['loop']=True;ev['score']=0
                    if not attempted:
                        if stopped: break
                        continue
                    result={'id':uuid.uuid4().hex,'model_id':model['id'],'case_id':case['id'],'track':case['track'],'context_size':case['context_size'],'family':case.get('family'),'variant':case.get('variant'),'context_estimate':case.get('context_estimate'),'repeat':repeat,'status':status,'score':ev.get('score',0),'critical':ev.get('critical',False),'loop':ev.get('loop',False),'latency_s':time.monotonic()-start,'prompt_tokens':usage_prompt or None,'completion_tokens':usage_completion or None,'cost_usd':actual_cost,'cost_source':cost_source,'error':err,'prompt':case['messages'],'response':response,'expected':case['expected'],'details':ev.get('details',{}),'events':events}
                    with self.s.connect() as c:
                        c.execute('insert into results values(?,?,?,?,?)',(result['id'],rid,model['id'],case['id'],json.dumps(result)))
                        c.execute('update runs set progress_done=progress_done+1,config=? where id=?',(json.dumps(cfg),rid))
                    if stopped: break
                if stopped: break
            if stopped: break
        with self.s.connect() as c:c.execute('update runs set status=?,config=? where id=?',('cancelled' if rid in self.cancel else 'budget_exhausted' if stopped else 'done',json.dumps(cfg),rid))
        self.cancel.discard(rid)

    def stop(self,rid):
        with self.s.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('select status from runs where id=?',(rid,)).fetchone()
            if not row:return False
            if row['status']=='queued':
                c.execute('delete from queue where run_id=?',(rid,));c.execute("update runs set status='cancelled' where id=?",(rid,));return True
            if row['status']=='running':
                self.cancel.add(rid)
                with self.lock:
                    active=self.active.get(rid)
                    if active: active[0].call_soon_threadsafe(active[1].cancel)
            return True

    def list(self):
        with self.s.connect() as c: rows=c.execute('select * from runs order by created_at desc').fetchall()
        return [self._summary(dict(r)) for r in rows]

    def get(self,rid):
        with self.s.connect() as c:
            row=c.execute('select * from runs where id=?',(rid,)).fetchone()
            if not row:return None
            results=[json.loads(x['data']) for x in c.execute('select data from results where run_id=?',(rid,))]
        v=self._summary(dict(row));v['results']=results;return v

    def _summary(self,r):
        cfg=json.loads(r['config']);results=[]
        with self.s.connect() as c: results=[json.loads(x['data']) for x in c.execute('select data from results where run_id=?',(r['id'],))]
        models={m['id']:m for m in cfg.get('models',[])};summary=[]
        for mid,m in models.items():
            items=[x for x in results if x['model_id']==mid];passed=sum(x['status']=='pass' for x in items);failed=sum(x['status']=='fail' for x in items);errors=sum(x['status']=='error' for x in items);total=len(items)
            tracks={}
            for track in sorted({x['track'] for x in items}):
                xs=[x for x in items if x['track']==track];ok=sum(x['status']=='pass' for x in xs);tracks[track]={'passed':ok,'total':len(xs),'accuracy':ok/len(xs) if xs else 0}
            contexts=[]
            for size in sorted({x['context_size'] for x in items}):
                xs=[x for x in items if x['context_size']==size];contexts.append({'context_size':size,'accuracy':sum(x['status']=='pass' for x in xs)/len(xs),'total':len(xs)})
            costs=[x['cost_usd'] for x in items if x['cost_usd'] is not None]
            summary.append({'model_id':mid,'name':m['name'],'quant':m['quant'],'passed':passed,'failed':failed,'errors':errors,'total':total,'accuracy':passed/total if total else 0,'avg_latency_s':sum(x['latency_s'] for x in items)/total if total else 0,'tokens':sum((x['prompt_tokens'] or 0)+(x['completion_tokens'] or 0) for x in items) if items and all(x['prompt_tokens'] is not None and x['completion_tokens'] is not None for x in items) else None,'cost_usd':sum(costs) if len(costs)==total and costs else None,'cost_source':next(iter({x.get('cost_source','unknown') for x in items})) if len({x.get('cost_source','unknown') for x in items})==1 else 'mixed','critical_failures':sum(bool(x['critical']) for x in items),'loops':sum(bool(x['loop']) for x in items),'by_track':tracks,'by_context':contexts})
        return {'id':r['id'],'name':r['name'],'status':r['status'],'created_at':r['created_at'],'config':cfg,'progress':{'done':r['progress_done'],'total':r['progress_total']},'summary':summary}
