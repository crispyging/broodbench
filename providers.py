import base64, hashlib, ipaddress, os, socket, uuid, stat
from urllib.parse import urlsplit
from cryptography.fernet import Fernet

class ProviderError(ValueError): pass

class ProviderService:
    def __init__(self, storage, secret=None, client=None):
        self.storage=storage
        material=(secret or os.environ.get('BROODBENCH_ENCRYPTION_KEY') or self._load_or_create_key(storage)).encode()
        self.fernet=Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest()))
        self.client=client
    @staticmethod
    def _load_or_create_key(storage):
        path=os.path.join(os.path.dirname(os.path.abspath(storage.path)), 'encryption.key')
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f: f.write(Fernet.generate_key())
        except FileExistsError: pass
        return open(path,'rb').read().decode().strip()
    @staticmethod
    def _url(kind,url):
        if kind=='openrouter':
            if url not in ('https://openrouter.ai','https://openrouter.ai/api/v1','https://openrouter.ai/api/v1/'): raise ProviderError('OpenRouter origin is fixed')
            return 'https://openrouter.ai/api/v1'
        try:u=urlsplit(url)
        except Exception as e: raise ProviderError('Invalid URL') from e
        if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment: raise ProviderError('Invalid provider URL')
        if u.hostname.lower() in ('metadata.google.internal','metadata','metadata.azure.internal') or u.hostname.lower().startswith('metadata.'):
            raise ProviderError('Denied provider address')
        try:
            ip=ipaddress.ip_address(u.hostname.split('%')[0])
        except ValueError:
            try:
                records=socket.getaddrinfo(u.hostname,None)
                for record in records:
                    ip=ipaddress.ip_address(record[4][0].split('%')[0])
                    if ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved or str(ip)=='169.254.169.254' or ip in ipaddress.ip_network('192.0.2.0/24'): raise ProviderError('Denied provider address')
            except socket.gaierror: pass
        else:
            if ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved or str(ip)=='169.254.169.254' or ip in ipaddress.ip_network('192.0.2.0/24'): raise ProviderError('Denied provider address')
        path=u.path.rstrip('/')
        suffix='/api' if kind=='openwebui' else '/v1'
        if kind=='openwebui' and not path.endswith('/api'): path += '/api'
        elif kind=='openai' and not path.endswith('/v1'): path += '/v1'
        return f'{u.scheme}://{u.netloc}{path}'
    def create(self,data):
        kind=data.get('kind'); name=data.get('name'); key=data.get('api_key')
        if key is not None and (not isinstance(key,str) or len(key)>8192): raise ProviderError('Invalid API key')
        if not isinstance(data.get('base_url',''),str): raise ProviderError('Invalid provider URL')
        if kind not in ('openai','openwebui','openrouter') or not isinstance(name,str) or not name.strip(): raise ProviderError('Invalid provider')
        url=self._url(kind,data.get('base_url','https://openrouter.ai/api/v1' if kind=='openrouter' else ''))
        p={'id':uuid.uuid4().hex,'name':name.strip(),'kind':kind,'base_url':url,'key_set':bool(key)}
        self.storage.save_provider({**p,'secret':self.fernet.encrypt(key.encode()) if key else None})
        return p
    def list(self):return [{k:p[k] for k in ('id','name','kind','base_url')}|{'key_set':bool(p['secret'])} for p in self.storage.providers()]
    def delete(self,id):return self.storage.delete_provider(id)
    @staticmethod
    def mutation_origin_allowed(origin,host):return not origin or origin==host or origin==f'http://{host}' or origin==f'https://{host}'
    def _provider(self,id):
        return next((p for p in self.storage.providers() if p['id']==id),None)
    async def models(self,id):
        p=self._provider(id)
        if not p:raise ProviderError('Provider not found')
        import httpx
        self._url(p['kind'],p['base_url'])
        headers={'Authorization':'Bearer '+self.fernet.decrypt(p['secret']).decode()} if p['secret'] else {}
        async with httpx.AsyncClient(timeout=15,follow_redirects=False,trust_env=False) as c:
            r=await c.get(p['base_url']+'/models',headers=headers); r.raise_for_status(); j=r.json()
        raw=j.get('data',j.get('models',[])); return {'models':[{'id':m['id'],'name':m.get('name',m['id'])} for m in raw]}
