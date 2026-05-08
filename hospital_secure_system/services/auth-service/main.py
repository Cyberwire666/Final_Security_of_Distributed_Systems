import datetime, os, re
from typing import Optional
from urllib.parse import urlencode
import jwt, psycopg2, requests
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field, field_validator

app=FastAPI(title='Auth Service')
pwd=CryptContext(schemes=['bcrypt'], deprecated='auto')
JWT_SECRET=os.environ['JWT_SECRET']; INTERNAL_API_KEY=os.environ['INTERNAL_API_KEY']; JWT_HOURS=int(os.getenv('JWT_EXP_HOURS','2'))
GITHUB_CLIENT_ID=os.getenv('GITHUB_CLIENT_ID',''); GITHUB_CLIENT_SECRET=os.getenv('GITHUB_CLIENT_SECRET','')
OAUTH_REDIRECT_URI=os.getenv('OAUTH_REDIRECT_URI','https://localhost/api/auth/oauth/github/callback'); OAUTH_STATE=os.getenv('OAUTH_STATE','hospital-secure-oauth-state'); OAUTH_DEFAULT_ROLE=os.getenv('OAUTH_DEFAULT_ROLE','user')

def error(code,msg,status=400,fields=None): return JSONResponse(status_code=status, content={'success':False,'error':{'code':code,'message':msg,'fields':fields or []}})
@app.exception_handler(HTTPException)
def http_err(req, exc):
    msgs={400:'The request could not be processed. Please review the submitted data.',401:'The email or password you entered is incorrect.',403:'You do not have permission to perform this action.',404:'The requested resource was not found.',409:'This email address is already registered.',500:'An internal error occurred. Please try again later.',503:'A required service is temporarily unavailable.'}
    code={401:'AUTHENTICATION_FAILED',403:'ACCESS_DENIED',404:'NOT_FOUND',409:'EMAIL_ALREADY_EXISTS',503:'SERVICE_UNAVAILABLE'}.get(exc.status_code,'REQUEST_ERROR')
    return error(code, msgs.get(exc.status_code, str(exc.detail)), exc.status_code)
@app.exception_handler(RequestValidationError)
def val_err(req, exc):
    fields=[]
    for e in exc.errors():
        loc='.'.join(str(x) for x in e.get('loc',[]) if x!='body')
        msg=e.get('msg','Invalid value').replace('Value error, ','')
        if loc=='email': msg='Please enter a valid email address.'
        if loc=='password': msg='Password must be 8-72 characters and include uppercase, lowercase, number, and special character.'
        fields.append({'field':loc or 'request','message':msg})
    return error('VALIDATION_ERROR','Please correct the highlighted fields and try again.',422,fields)
@app.exception_handler(Exception)
def unhandled(req, exc): return error('INTERNAL_ERROR','An unexpected error occurred. Please try again later.',500)

def db(): return psycopg2.connect(host='postgres',dbname=os.environ['POSTGRES_DB'],user=os.environ['POSTGRES_USER'],password=os.environ['POSTGRES_PASSWORD'])
def audit(uid,action,status,details,ip=''):
    try: requests.post('http://audit-service:8000/internal/log',json={'user_id':uid,'action':action,'status':status,'details':details,'ip_address':ip},headers={'x-internal-api-key':INTERNAL_API_KEY},timeout=2)
    except Exception: pass
def create_token(uid:int, role:str): return jwt.encode({'sub':str(uid),'role':role,'exp':datetime.datetime.utcnow()+datetime.timedelta(hours=JWT_HOURS)},JWT_SECRET,algorithm='HS256')

class RegisterIn(BaseModel):
    email: EmailStr; password: str=Field(min_length=8,max_length=72); full_name: str=Field(default='',max_length=150); role: str='user'
    @field_validator('password')
    @classmethod
    def strong(cls,v):
        if not re.search(r'[A-Z]',v) or not re.search(r'[a-z]',v) or not re.search(r'\d',v) or not re.search(r'[^A-Za-z0-9]',v):
            raise ValueError('Password must be 8-72 characters and include uppercase, lowercase, number, and special character.')
        return v
    @field_validator('full_name')
    @classmethod
    def name(cls,v):
        v=(v or '').strip()
        if v and len(v)<2: raise ValueError('Full name must contain at least 2 characters.')
        return v
    @field_validator('role')
    @classmethod
    def role_ok(cls,v):
        if v not in {'user','admin'}: raise ValueError('Role must be either user or admin.')
        return v
class LoginIn(BaseModel): email: EmailStr; password: str=Field(min_length=1)
class RoleUpdateIn(BaseModel):
    role:str
    @field_validator('role')
    @classmethod
    def role_ok(cls,v):
        if v not in {'user','admin'}: raise ValueError('Role must be either user or admin.')
        return v

@app.post('/register')
def register(data:RegisterIn, request:Request):
    conn=db(); cur=conn.cursor()
    try:
        cur.execute('INSERT INTO users(email,password_hash,role,full_name) VALUES(%s,%s,%s,%s) RETURNING id',(data.email.lower(),pwd.hash(data.password),data.role,data.full_name.strip()))
        uid=cur.fetchone()[0]; cur.execute('INSERT INTO user_roles(user_id,role_id) SELECT %s,id FROM roles WHERE name=%s ON CONFLICT DO NOTHING',(uid,data.role)); conn.commit(); audit(uid,'register','success',f'new {data.role} user',request.client.host)
        return {'success':True,'data':{'id':uid,'email':data.email.lower(),'full_name':data.full_name.strip(),'role':data.role}}
    except psycopg2.errors.UniqueViolation:
        conn.rollback(); audit(None,'register','failed','email already exists',request.client.host); raise HTTPException(409,'email exists')
    finally: cur.close(); conn.close()
@app.post('/login')
def login(data:LoginIn, request:Request):
    conn=db(); cur=conn.cursor(); cur.execute('SELECT id,password_hash,role,is_active,full_name,email FROM users WHERE email=%s',(data.email.lower(),)); row=cur.fetchone(); cur.close(); conn.close()
    if not row or not pwd.verify(data.password,row[1]): audit(None,'login','failed','invalid credentials',request.client.host); raise HTTPException(401,'invalid credentials')
    if not row[3]: audit(row[0],'login','failed','inactive account',request.client.host); raise HTTPException(403,'account disabled')
    audit(row[0],'login','success','jwt issued',request.client.host)
    return {'success':True,'access_token':create_token(row[0],row[2]),'token_type':'bearer','role':row[2],'user':{'id':row[0],'full_name':row[4],'email':row[5],'role':row[2]}}
@app.get('/verify')
def verify(authorization:Optional[str]=Header(default=None)):
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'missing token')
    try: return jwt.decode(authorization.split()[1],JWT_SECRET,algorithms=['HS256'])
    except jwt.ExpiredSignatureError: raise HTTPException(401,'expired token')
    except Exception: raise HTTPException(401,'invalid token')
@app.get('/me')
def me(authorization:Optional[str]=Header(default=None)):
    p=verify(authorization); conn=db(); cur=conn.cursor(); cur.execute('SELECT id,email,role,full_name,is_active,created_at,oauth_provider FROM users WHERE id=%s',(int(p['sub']),)); r=cur.fetchone(); cur.close(); conn.close()
    if not r: raise HTTPException(404,'user not found')
    return {'success':True,'data':{'id':r[0],'email':r[1],'role':r[2],'full_name':r[3],'is_active':r[4],'created_at':str(r[5]),'oauth_provider':r[6]}}
def require_admin(authz):
    p=verify(authz)
    if p.get('role')!='admin': audit(int(p['sub']),'admin_access','forbidden','admin endpoint rejected'); raise HTTPException(403,'admin only')
    return p
@app.get('/admin/users')
def users(authorization:Optional[str]=Header(default=None)):
    require_admin(authorization); conn=db(); cur=conn.cursor(); cur.execute('SELECT id,email,role,full_name,is_active,created_at,oauth_provider FROM users ORDER BY id DESC'); rows=cur.fetchall(); cur.close(); conn.close()
    return [{'id':r[0],'email':r[1],'role':r[2],'full_name':r[3],'is_active':r[4],'created_at':str(r[5]),'oauth_provider':r[6]} for r in rows]
@app.patch('/admin/users/{user_id}/role')
def update_role(user_id:int,data:RoleUpdateIn,authorization:Optional[str]=Header(default=None)):
    admin=require_admin(authorization); conn=db(); cur=conn.cursor(); cur.execute('UPDATE users SET role=%s WHERE id=%s RETURNING id',(data.role,user_id)); row=cur.fetchone()
    if not row: conn.rollback(); cur.close(); conn.close(); raise HTTPException(404,'user not found')
    cur.execute('DELETE FROM user_roles WHERE user_id=%s',(user_id,)); cur.execute('INSERT INTO user_roles(user_id,role_id) SELECT %s,id FROM roles WHERE name=%s',(user_id,data.role)); conn.commit(); cur.close(); conn.close(); audit(int(admin['sub']),'update_role','success',f'user_id={user_id}; role={data.role}'); return {'success':True,'id':user_id,'role':data.role}
@app.patch('/admin/users/{user_id}/disable')
def disable_user(user_id:int,authorization:Optional[str]=Header(default=None)):
    admin=require_admin(authorization); conn=db(); cur=conn.cursor(); cur.execute('UPDATE users SET is_active=false WHERE id=%s RETURNING id',(user_id,)); row=cur.fetchone(); conn.commit(); cur.close(); conn.close()
    if not row: raise HTTPException(404,'user not found')
    audit(int(admin['sub']),'disable_user','success',f'user_id={user_id}'); return {'success':True,'id':user_id,'is_active':False}
def oauth_enabled(): return bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET)
@app.get('/oauth/github/start')
def github_start():
    if not oauth_enabled(): return {'enabled':False,'message':'GitHub sign-in is not configured.','github_callback_url':OAUTH_REDIRECT_URI}
    return {'enabled':True,'authorize_url':'https://github.com/login/oauth/authorize?'+urlencode({'client_id':GITHUB_CLIENT_ID,'redirect_uri':OAUTH_REDIRECT_URI,'scope':'read:user user:email','state':OAUTH_STATE,'allow_signup':'true'}),'callback_url':OAUTH_REDIRECT_URI}
@app.get('/oauth/github/callback')
def github_callback(request:Request, code:str='', state:str=''):
    if not oauth_enabled(): raise HTTPException(503,'OAuth is not configured')
    if not code or state!=OAUTH_STATE: raise HTTPException(400,'Invalid OAuth response')
    token_res=requests.post('https://github.com/login/oauth/access_token',json={'client_id':GITHUB_CLIENT_ID,'client_secret':GITHUB_CLIENT_SECRET,'code':code,'redirect_uri':OAUTH_REDIRECT_URI},headers={'Accept':'application/json'},timeout=10).json()
    access_token=token_res.get('access_token')
    if not access_token: raise HTTPException(400,'OAuth login failed')
    gh={'Authorization':f'Bearer {access_token}','Accept':'application/vnd.github+json'}; profile=requests.get('https://api.github.com/user',headers=gh,timeout=10).json(); emails=requests.get('https://api.github.com/user/emails',headers=gh,timeout=10).json()
    email=next((e['email'] for e in emails if e.get('primary') and e.get('verified')),None) or profile.get('email') or f"github_{profile.get('id')}@users.noreply.github.com"; name=profile.get('name') or profile.get('login') or ''
    conn=db(); cur=conn.cursor(); cur.execute('SELECT id,role FROM users WHERE email=%s',(email,)); row=cur.fetchone()
    if row: uid,role=row
    else:
        cur.execute('INSERT INTO users(email,password_hash,role,full_name,oauth_provider,oauth_subject) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id',(email,pwd.hash(os.urandom(24).hex()),OAUTH_DEFAULT_ROLE,name,'github',str(profile.get('id')))); uid=cur.fetchone()[0]; role=OAUTH_DEFAULT_ROLE; cur.execute('INSERT INTO user_roles(user_id,role_id) SELECT %s,id FROM roles WHERE name=%s ON CONFLICT DO NOTHING',(uid,role)); conn.commit()
    cur.close(); conn.close(); audit(uid,'oauth_github','success','github login',request.client.host); token=create_token(uid,role)
    return RedirectResponse(url=f"/?token={token}&role={role}")
