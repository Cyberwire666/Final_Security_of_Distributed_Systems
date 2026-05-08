import os, re
from datetime import datetime
from typing import Optional
import psycopg2, requests
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
app=FastAPI(title='Patient Service'); INTERNAL_API_KEY=os.environ['INTERNAL_API_KEY']
def error(code,msg,status=400,fields=None): return JSONResponse(status_code=status,content={'success':False,'error':{'code':code,'message':msg,'fields':fields or []}})
@app.exception_handler(HTTPException)
def http_err(req,exc):
    msgs={401:'Please sign in to continue.',403:'You do not have permission to access this hospital resource.',404:'The requested hospital record was not found.',409:'This record already exists.',503:'A required service is temporarily unavailable.'}
    return error({401:'AUTH_REQUIRED',403:'ACCESS_DENIED',404:'NOT_FOUND',503:'SERVICE_UNAVAILABLE'}.get(exc.status_code,'REQUEST_ERROR'),msgs.get(exc.status_code,str(exc.detail)),exc.status_code)
@app.exception_handler(RequestValidationError)
def val_err(req,exc):
    fields=[]
    for e in exc.errors():
        loc='.'.join(str(x) for x in e.get('loc',[]) if x!='body'); fields.append({'field':loc,'message':e.get('msg','Invalid value').replace('Value error, ','')})
    return error('VALIDATION_ERROR','Please review the highlighted fields and submit again.',422,fields)
@app.exception_handler(Exception)
def unhandled(req,exc): return error('INTERNAL_ERROR','Something went wrong while processing the hospital request.',500)
def db(): return psycopg2.connect(host='postgres',dbname=os.environ['POSTGRES_DB'],user=os.environ['POSTGRES_USER'],password=os.environ['POSTGRES_PASSWORD'])
def auth(authorization:Optional[str]):
    try: r=requests.get('http://auth-service:8000/verify',headers={'Authorization':authorization or ''},timeout=3)
    except Exception: raise HTTPException(503,'auth unavailable')
    if r.status_code!=200: raise HTTPException(401,'unauthorized')
    return r.json()
def audit(uid,action,status,details,ip=''):
    try: requests.post('http://audit-service:8000/internal/log',json={'user_id':uid,'action':action,'status':status,'details':details,'ip_address':ip},headers={'x-internal-api-key':INTERNAL_API_KEY},timeout=2)
    except Exception: pass
def require_admin(p):
    if p.get('role')!='admin': audit(int(p['sub']),'admin_patient_access','forbidden','not admin'); raise HTTPException(403,'admin only')
class PatientIn(BaseModel):
    full_name:str=Field(min_length=2,max_length=150); age:int=Field(ge=0,le=130); gender:str=Field(default='unknown',max_length=20); phone:str=Field(default='',max_length=40); diagnosis:str=Field(default='',max_length=1000)
    @field_validator('full_name','gender','diagnosis')
    @classmethod
    def clean(cls,v): return (v or '').strip()
    @field_validator('phone')
    @classmethod
    def phone_ok(cls,v):
        v=(v or '').strip()
        if v and not re.fullmatch(r'[+0-9\-\s()]{7,25}',v): raise ValueError('Phone number must contain only digits, spaces, +, -, or parentheses.')
        return v
class DoctorIn(BaseModel):
    full_name:str=Field(min_length=2,max_length=150); specialty:str=Field(min_length=2,max_length=120); phone:str=Field(default='',max_length=40)
    @field_validator('phone')
    @classmethod
    def phone_ok(cls,v):
        v=(v or '').strip()
        if v and not re.fullmatch(r'[+0-9\-\s()]{7,25}',v): raise ValueError('Phone number must contain only digits, spaces, +, -, or parentheses.')
        return v
class AppointmentIn(BaseModel):
    patient_id:int=Field(gt=0); doctor_id:Optional[int]=Field(default=None,gt=0); appointment_time:datetime; reason:str=Field(default='',max_length=500)
    @field_validator('appointment_time')
    @classmethod
    def future(cls,v):
        if v<=datetime.utcnow(): raise ValueError('Appointment date and time must be in the future.')
        return v
class AppointmentStatusIn(BaseModel):
    status:str
    @field_validator('status')
    @classmethod
    def ok(cls,v):
        if v not in {'scheduled','completed','cancelled'}: raise ValueError('Status must be scheduled, completed, or cancelled.')
        return v
@app.get('/health')
def health(): return {'status':'ok','service':'patient-service'}
@app.post('/')
def create_patient(data:PatientIn,request:Request,authorization:Optional[str]=Header(default=None)):
    u=auth(authorization); uid=int(u['sub']); conn=db(); cur=conn.cursor(); cur.execute('INSERT INTO patients(owner_user_id,full_name,age,gender,phone,diagnosis) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id',(uid,data.full_name,data.age,data.gender,data.phone,data.diagnosis)); pid=cur.fetchone()[0]; conn.commit(); cur.close(); conn.close(); audit(uid,'create_patient','success',f'patient_id={pid}',request.client.host); return {'success':True,'data':{'id':pid,**data.model_dump()}}
@app.get('/')
def list_patients(authorization:Optional[str]=Header(default=None)):
    u=auth(authorization); uid=int(u['sub']); role=u['role']; conn=db(); cur=conn.cursor();
    cur.execute('SELECT id,owner_user_id,full_name,age,gender,phone,diagnosis,created_at FROM patients '+('ORDER BY id DESC' if role=='admin' else 'WHERE owner_user_id=%s ORDER BY id DESC'), (() if role=='admin' else (uid,)))
    rows=cur.fetchall(); cur.close(); conn.close(); return [{'id':r[0],'owner_user_id':r[1],'full_name':r[2],'age':r[3],'gender':r[4],'phone':r[5],'diagnosis':r[6],'created_at':str(r[7])} for r in rows]
@app.get('/{patient_id}')
def get_patient(patient_id:int,authorization:Optional[str]=Header(default=None)):
    u=auth(authorization); uid=int(u['sub']); role=u['role']; conn=db(); cur=conn.cursor(); cur.execute('SELECT id,owner_user_id,full_name,age,gender,phone,diagnosis,created_at FROM patients WHERE id=%s',(patient_id,)); r=cur.fetchone(); cur.close(); conn.close()
    if not r: raise HTTPException(404,'patient not found')
    if role!='admin' and r[1]!=uid: raise HTTPException(403,'forbidden')
    return {'id':r[0],'owner_user_id':r[1],'full_name':r[2],'age':r[3],'gender':r[4],'phone':r[5],'diagnosis':r[6],'created_at':str(r[7])}
@app.delete('/{patient_id}')
def delete_patient(patient_id:int,request:Request,authorization:Optional[str]=Header(default=None)):
    u=auth(authorization); require_admin(u); conn=db(); cur=conn.cursor(); cur.execute('DELETE FROM patients WHERE id=%s RETURNING id',(patient_id,)); row=cur.fetchone(); conn.commit(); cur.close(); conn.close();
    if not row: raise HTTPException(404,'patient not found')
    audit(int(u['sub']),'delete_patient','success',f'patient_id={patient_id}',request.client.host); return {'success':True,'deleted':patient_id}
@app.post('/doctors')
def create_doctor(data:DoctorIn,request:Request,authorization:Optional[str]=Header(default=None)):
    u=auth(authorization); require_admin(u); conn=db(); cur=conn.cursor(); cur.execute('INSERT INTO doctors(full_name,specialty,phone) VALUES(%s,%s,%s) RETURNING id',(data.full_name,data.specialty,data.phone)); did=cur.fetchone()[0]; conn.commit(); cur.close(); conn.close(); audit(int(u['sub']),'create_doctor','success',f'doctor_id={did}',request.client.host); return {'success':True,'data':{'id':did,**data.model_dump()}}
@app.get('/doctors/list')
def list_doctors(authorization:Optional[str]=Header(default=None)):
    auth(authorization); conn=db(); cur=conn.cursor(); cur.execute('SELECT id,full_name,specialty,phone,created_at FROM doctors ORDER BY id DESC'); rows=cur.fetchall(); cur.close(); conn.close(); return [{'id':r[0],'full_name':r[1],'specialty':r[2],'phone':r[3],'created_at':str(r[4])} for r in rows]
@app.post('/appointments')
def create_appointment(data:AppointmentIn,request:Request,authorization:Optional[str]=Header(default=None)):
    u=auth(authorization); uid=int(u['sub']); role=u['role']; conn=db(); cur=conn.cursor(); cur.execute('SELECT owner_user_id FROM patients WHERE id=%s',(data.patient_id,)); owner=cur.fetchone()
    if not owner: cur.close(); conn.close(); raise HTTPException(404,'patient not found')
    if role!='admin' and owner[0]!=uid: cur.close(); conn.close(); raise HTTPException(403,'forbidden')
    if data.doctor_id: cur.execute('SELECT id FROM doctors WHERE id=%s',(data.doctor_id,));
    if data.doctor_id and not cur.fetchone(): cur.close(); conn.close(); raise HTTPException(404,'doctor not found')
    cur.execute('INSERT INTO appointments(owner_user_id,patient_id,doctor_id,appointment_time,reason) VALUES(%s,%s,%s,%s,%s) RETURNING id',(owner[0],data.patient_id,data.doctor_id,data.appointment_time,data.reason)); aid=cur.fetchone()[0]; conn.commit(); cur.close(); conn.close(); audit(uid,'create_appointment','success',f'appointment_id={aid}',request.client.host); return {'success':True,'data':{'id':aid,**data.model_dump(mode='json'),'status':'scheduled'}}
@app.get('/appointments/list')
def list_appointments(authorization:Optional[str]=Header(default=None)):
    u=auth(authorization); uid=int(u['sub']); role=u['role']; base='SELECT a.id,a.owner_user_id,a.patient_id,p.full_name,d.full_name,a.appointment_time,a.reason,a.status FROM appointments a JOIN patients p ON p.id=a.patient_id LEFT JOIN doctors d ON d.id=a.doctor_id'; conn=db(); cur=conn.cursor(); cur.execute(base+(' ORDER BY a.appointment_time DESC' if role=='admin' else ' WHERE a.owner_user_id=%s ORDER BY a.appointment_time DESC'), (() if role=='admin' else (uid,))); rows=cur.fetchall(); cur.close(); conn.close(); return [{'id':r[0],'owner_user_id':r[1],'patient_id':r[2],'patient_name':r[3],'doctor_name':r[4],'appointment_time':str(r[5]),'reason':r[6],'status':r[7]} for r in rows]
@app.patch('/appointments/{appointment_id}/status')
def update_status(appointment_id:int,data:AppointmentStatusIn,request:Request,authorization:Optional[str]=Header(default=None)):
    u=auth(authorization); require_admin(u); conn=db(); cur=conn.cursor(); cur.execute('UPDATE appointments SET status=%s WHERE id=%s RETURNING id',(data.status,appointment_id)); row=cur.fetchone(); conn.commit(); cur.close(); conn.close();
    if not row: raise HTTPException(404,'appointment not found')
    audit(int(u['sub']),'update_appointment','success',f'appointment_id={appointment_id}; status={data.status}',request.client.host); return {'success':True,'id':appointment_id,'status':data.status}
