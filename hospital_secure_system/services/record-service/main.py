import hashlib, json, mimetypes, os, time, uuid
from pathlib import Path
from typing import Optional
import pika, psycopg2, requests
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

app=FastAPI(title='Medical Records Service')
UPLOAD=Path('/app/uploads'); UPLOAD.mkdir(parents=True,exist_ok=True)
ALLOWED_EXT={'.pdf','.png','.jpg','.jpeg','.txt'}; ALLOWED_MIME={'application/pdf','image/png','image/jpeg','text/plain'}; BLOCKED_EXT={'.exe','.php','.js','.bat','.sh','.cmd','.ps1','.vbs'}
MAX_SIZE=int(os.getenv('MAX_UPLOAD_BYTES',str(5*1024*1024))); INTERNAL_API_KEY=os.environ['INTERNAL_API_KEY']; fernet=Fernet(os.environ['FERNET_KEY'].encode())

def error(code,msg,status=400,fields=None): return JSONResponse(status_code=status,content={'success':False,'error':{'code':code,'message':msg,'fields':fields or []}})
@app.exception_handler(HTTPException)
def http_err(req,exc):
    msgs={400:'The medical file request is invalid. Please review the file and patient selection.',401:'Please sign in to continue.',403:'You do not have permission to access this medical record.',404:'The requested medical record or patient was not found.',413:'The selected file is too large. Please upload a file under 5 MB.',500:'The medical file could not be processed at this time.',503:'A required hospital service is temporarily unavailable.'}
    return error({401:'AUTH_REQUIRED',403:'ACCESS_DENIED',404:'NOT_FOUND',413:'FILE_TOO_LARGE',503:'SERVICE_UNAVAILABLE'}.get(exc.status_code,'REQUEST_ERROR'),msgs.get(exc.status_code,str(exc.detail)),exc.status_code)
@app.exception_handler(RequestValidationError)
def val_err(req,exc): return error('VALIDATION_ERROR','Please provide a valid patient and medical file.',422,[{'field':'.'.join(str(x) for x in e.get('loc',[]) if x!='body'),'message':e.get('msg','Invalid value')} for e in exc.errors()])
@app.exception_handler(Exception)
def unhandled(req,exc): return error('INTERNAL_ERROR','Something went wrong while processing the medical record.',500)

def db(): return psycopg2.connect(host='postgres',dbname=os.environ['POSTGRES_DB'],user=os.environ['POSTGRES_USER'],password=os.environ['POSTGRES_PASSWORD'])
def auth(authorization:Optional[str]):
    try: r=requests.get('http://auth-service:8000/verify',headers={'Authorization':authorization or ''},timeout=3)
    except Exception: raise HTTPException(503,'auth service unavailable')
    if r.status_code!=200: raise HTTPException(401,'unauthorized')
    return r.json()
def audit(uid,action,status,details,ip=''):
    try: requests.post('http://audit-service:8000/internal/log',json={'user_id':uid,'action':action,'status':status,'details':details,'ip_address':ip},headers={'x-internal-api-key':INTERNAL_API_KEY},timeout=2)
    except Exception: pass
def publish(record_id:int):
    creds=pika.PlainCredentials(os.environ['RABBITMQ_DEFAULT_USER'],os.environ['RABBITMQ_DEFAULT_PASS']); last=None
    for _ in range(8):
        try:
            con=pika.BlockingConnection(pika.ConnectionParameters('rabbitmq',5672,'/',creds)); ch=con.channel(); ch.queue_declare(queue='record_jobs',durable=True); ch.basic_publish(exchange='',routing_key='record_jobs',body=json.dumps({'record_id':record_id}),properties=pika.BasicProperties(delivery_mode=2)); con.close(); return
        except Exception as exc: last=exc; time.sleep(1)
    raise RuntimeError(f'Queue publish failed: {last}')
def safe_filename(filename:str):
    raw=Path(filename or 'medical_file').name.strip().replace(' ','_'); cleaned=''.join(c for c in raw if c.isalnum() or c in {'.','_','-'}) or 'medical_file'; return cleaned[:180]
def effective_mime(file:UploadFile,name:str): return mimetypes.guess_type(name)[0] or (file.content_type or '').lower().strip()
def check_patient(patient_id:int,uid:int,role:str):
    if patient_id<1: raise HTTPException(400,'invalid patient')
    conn=db(); cur=conn.cursor(); cur.execute('SELECT owner_user_id FROM patients WHERE id=%s',(patient_id,)); row=cur.fetchone(); cur.close(); conn.close()
    if not row: raise HTTPException(404,'patient not found')
    if role!='admin' and row[0]!=uid: raise HTTPException(403,'forbidden')
    return row[0]
def get_record(record_id:int,uid:int,role:str):
    conn=db(); cur=conn.cursor(); cur.execute('SELECT id,patient_id,owner_user_id,original_filename,stored_filename,content_type,file_size,sha256_hash,processing_status,created_at FROM medical_records WHERE id=%s',(record_id,)); row=cur.fetchone(); cur.close(); conn.close()
    if not row: raise HTTPException(404,'record not found')
    if role!='admin' and row[2]!=uid: raise HTTPException(403,'forbidden')
    return row
@app.get('/health')
def health(): return {'status':'ok','service':'record-service'}
@app.post('/upload')
async def upload(request:Request, patient_id:int=Form(...), file:UploadFile=File(...), authorization:Optional[str]=Header(default=None)):
    u=auth(authorization); uid=int(u['sub']); role=u['role']; check_patient(patient_id,uid,role)
    name=safe_filename(file.filename or 'file'); ext=Path(name).suffix.lower(); content=await file.read(); mime=effective_mime(file,name)
    if not content: audit(uid,'file_upload','rejected','empty file',request.client.host); raise HTTPException(400,'empty file')
    if ext in BLOCKED_EXT or ext not in ALLOWED_EXT: audit(uid,'file_upload','rejected',f'bad extension={ext}',request.client.host); raise HTTPException(400,'unsupported file extension')
    if mime not in ALLOWED_MIME: audit(uid,'file_upload','rejected',f'bad mime={file.content_type}; guessed={mime}',request.client.host); raise HTTPException(400,'unsupported file type')
    if len(content)>MAX_SIZE: audit(uid,'file_upload','rejected',f'oversized={len(content)}',request.client.host); raise HTTPException(413,'file too large')
    sha=hashlib.sha256(content).hexdigest(); stored=f'{uuid.uuid4().hex}{ext}.enc'; (UPLOAD/stored).write_bytes(fernet.encrypt(content))
    conn=db(); cur=conn.cursor(); cur.execute('INSERT INTO medical_records(patient_id,owner_user_id,original_filename,stored_filename,content_type,file_size,sha256_hash) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id',(patient_id,uid,name,stored,mime,len(content),sha)); rid=cur.fetchone()[0]; cur.execute('INSERT INTO background_jobs(record_id,job_type,status,details) VALUES(%s,%s,%s,%s)',(rid,'record_processing','queued','waiting for worker')); conn.commit(); cur.close(); conn.close()
    try: publish(rid)
    except Exception as exc: audit(uid,'background_job','failed',f'record_id={rid}; {exc}',request.client.host)
    audit(uid,'file_upload','success',f'record_id={rid}',request.client.host)
    return {'success':True,'data':{'record_id':rid,'filename':name,'content_type':mime,'file_size':len(content),'sha256':sha,'status':'queued'}}
@app.get('/')
def records(authorization:Optional[str]=Header(default=None)):
    u=auth(authorization); uid=int(u['sub']); role=u['role']; conn=db(); cur=conn.cursor();
    q='SELECT id,patient_id,owner_user_id,original_filename,content_type,file_size,sha256_hash,processing_status,created_at FROM medical_records '
    cur.execute(q+('ORDER BY id DESC' if role=='admin' else 'WHERE owner_user_id=%s ORDER BY id DESC'), (() if role=='admin' else (uid,)))
    rows=cur.fetchall(); cur.close(); conn.close(); return [{'id':r[0],'patient_id':r[1],'owner_user_id':r[2],'filename':r[3],'content_type':r[4],'file_size':r[5],'sha256':r[6],'status':r[7],'created_at':str(r[8])} for r in rows]
@app.get('/verify/{record_id}')
def verify(record_id:int,request:Request,authorization:Optional[str]=Header(default=None)):
    u=auth(authorization); uid=int(u['sub']); row=get_record(record_id,uid,u['role'])
    try: data=fernet.decrypt((UPLOAD/row[4]).read_bytes()); actual=hashlib.sha256(data).hexdigest(); valid=actual==row[7]
    except (FileNotFoundError,InvalidToken): actual=None; valid=False
    audit(uid,'file_verify','success' if valid else 'failed',f'record_id={record_id}; valid={valid}',request.client.host)
    return {'record_id':record_id,'valid':valid,'expected_sha256':row[7],'actual_sha256':actual}
@app.get('/download/{record_id}')
def download(record_id:int,request:Request,authorization:Optional[str]=Header(default=None)):
    u=auth(authorization); uid=int(u['sub']); row=get_record(record_id,uid,u['role'])
    try: data=fernet.decrypt((UPLOAD/row[4]).read_bytes())
    except Exception: audit(uid,'file_download','failed',f'record_id={record_id}',request.client.host); raise HTTPException(500,'file cannot be opened')
    audit(uid,'file_download','success',f'record_id={record_id}',request.client.host)
    return Response(content=data,media_type=row[5],headers={'Content-Disposition':f'attachment; filename="{row[3]}"'})
