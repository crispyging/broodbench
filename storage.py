import json, os, sqlite3, threading, time, uuid
from contextlib import contextmanager

class Storage:
    def __init__(self, path=None):
        self.path = path or os.environ.get('BROODBENCH_DATA','/data')
        if self.path.endswith('/') or os.path.isdir(self.path):
            os.makedirs(self.path, exist_ok=True); self.path=os.path.join(self.path,'broodbench.sqlite3')
        else: os.makedirs(os.path.dirname(os.path.abspath(self.path)),exist_ok=True)
        self.lock=threading.RLock()
        with self.connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS providers(id TEXT PRIMARY KEY,name TEXT,kind TEXT,base_url TEXT,secret BLOB); CREATE TABLE IF NOT EXISTS models(id TEXT PRIMARY KEY, provider_id TEXT,name TEXT,model_id TEXT,family TEXT,quant TEXT,context_limit INTEGER,notes TEXT); CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,name TEXT,status TEXT,created_at REAL,config TEXT,progress_done INTEGER DEFAULT 0,progress_total INTEGER DEFAULT 0); CREATE TABLE IF NOT EXISTS results(id TEXT PRIMARY KEY,run_id TEXT,model_id TEXT,case_id TEXT,data TEXT); CREATE TABLE IF NOT EXISTS queue(id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT UNIQUE, config TEXT);''')
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=30)
        c.row_factory=sqlite3.Row
        try:
            c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA foreign_keys=ON')
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()
    def providers(self):
        with self.connect() as c:return [dict(x) for x in c.execute('SELECT id,name,kind,base_url,secret FROM providers')]
    def save_provider(self,p):
        with self.connect() as c:c.execute('INSERT INTO providers VALUES(?,?,?,?,?)',(p['id'],p['name'],p['kind'],p['base_url'],p['secret']))
    def delete_provider(self,id):
        with self.connect() as c:
            if c.execute('SELECT 1 FROM models WHERE provider_id=?',(id,)).fetchone(): return False
            return c.execute('DELETE FROM providers WHERE id=?',(id,)).rowcount>0
