import os
from typing import Optional
import psycopg2, requests
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
app=FastAPI(title='Audit Service'); INTERNAL_API_KEY=os.environ['INTERNAL_API_KEY']
def error(code,msg,status=400,fields=None): return JSONResponse(status_code=status,content={'success':False,'error':{'code':code,'message':msg,'fields':fields or []}})
@app.exception_handler(HTTPException)
def http_err(req,exc): return error({401:'AUTH_REQUIRED',403:'ACCESS_DENIED',503:'SERVICE_UNAVAILABLE'}.get(exc.status_code,'REQUEST_ERROR'),'You do not have permission to view this information.' if exc.status_code in (401,403) else str(exc.detail),exc.status_code)
@app.exception_handler(RequestValidationError)
def val_err(req,exc): return error('VALIDATION_ERROR','Please review the submitted audit data.',422)
@app.exception_handler(Exception)
def unhandled(req,exc): return error('INTERNAL_ERROR','Audit information is temporarily unavailable.',500)
def db(): return psycopg2.connect(host='postgres',dbname=os.environ['POSTGRES_DB'],user=os.environ['POSTGRES_USER'],password=os.environ['POSTGRES_PASSWORD'])
def internal(x_internal_api_key:Optional[str]=Header(default=None)):
    if x_internal_api_key!=INTERNAL_API_KEY: raise HTTPException(403,'forbidden')
def auth_admin(authorization:Optional[str]=Header(default=None)):
    try: res=requests.get('http://auth-service:8000/verify',headers={'Authorization':authorization or ''},timeout=3)
    except Exception: raise HTTPException(503,'auth unavailable')
    if res.status_code!=200: raise HTTPException(401,'unauthorized')
    p=res.json()
    if p.get('role')!='admin': raise HTTPException(403,'admin only')
    return p
class LogIn(BaseModel): user_id:Optional[int]=None; action:str=Field(min_length=2,max_length=120); ip_address:Optional[str]=''; status:str=Field(min_length=2,max_length=40); details:Optional[str]=''
@app.get('/health')
def health(): return {'status':'ok','service':'audit-service'}
@app.post('/internal/log')
def log(data:LogIn,_:None=Depends(internal)):
    conn=db(); cur=conn.cursor(); cur.execute('INSERT INTO audit_logs(user_id,action,ip_address,status,details) VALUES(%s,%s,%s,%s,%s)',(data.user_id,data.action,data.ip_address,data.status,data.details)); conn.commit(); cur.close(); conn.close(); return {'ok':True}
@app.get('/logs')
def logs(_:dict=Depends(auth_admin)):
    conn=db(); cur=conn.cursor(); cur.execute('SELECT id,user_id,action,ip_address,status,details,created_at FROM audit_logs ORDER BY id DESC LIMIT 250'); rows=cur.fetchall(); cur.close(); conn.close(); return [{'id':r[0],'user_id':r[1],'action':r[2],'ip_address':r[3],'status':r[4],'details':r[5],'created_at':str(r[6])} for r in rows]
@app.get('/metrics')
def metrics(_:dict=Depends(auth_admin)):
    queries={'total_users':'SELECT count(*) FROM users','active_users':'SELECT count(*) FROM users WHERE is_active=true','patients':'SELECT count(*) FROM patients','doctors':'SELECT count(*) FROM doctors','appointments':'SELECT count(*) FROM appointments','records':'SELECT count(*) FROM medical_records','failed_logins':"SELECT count(*) FROM audit_logs WHERE action='login' AND status='failed'",'unauthorized':"SELECT count(*) FROM audit_logs WHERE status IN ('unauthorized','forbidden')",'processed_jobs':"SELECT count(*) FROM background_jobs WHERE status='processed'",'queued_jobs':"SELECT count(*) FROM background_jobs WHERE status='queued'"}
    conn=db(); cur=conn.cursor(); out={}
    for name,sql in queries.items(): cur.execute(sql); out[name]=cur.fetchone()[0]
    cur.close(); conn.close(); return out
