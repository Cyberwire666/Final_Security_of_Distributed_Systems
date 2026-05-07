import hashlib
import json
import mimetypes
import os
import time
import uuid
from pathlib import Path
from typing import Optional

import pika
import psycopg2
import requests
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response

app = FastAPI(title="Secure Medical Record Service")

UPLOAD = Path("/app/uploads")
UPLOAD.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".txt"}
ALLOWED_MIME = {"application/pdf", "image/png", "image/jpeg", "text/plain"}
BLOCKED_EXT = {".exe", ".php", ".js", ".bat", ".sh", ".cmd", ".ps1", ".vbs"}
MAX_SIZE = int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
INTERNAL_API_KEY = os.environ["INTERNAL_API_KEY"]
fernet = Fernet(os.environ["FERNET_KEY"].encode())


def db():
    return psycopg2.connect(
        host="postgres",
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def auth(authorization: Optional[str]):
    try:
        r = requests.get(
            "http://auth-service:8000/verify",
            headers={"Authorization": authorization or ""},
            timeout=3,
        )
    except Exception:
        raise HTTPException(status_code=503, detail="auth service unavailable")
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="unauthorized")
    return r.json()


def audit(uid, action, status, details, ip=""):
    try:
        requests.post(
            "http://audit-service:8000/internal/log",
            json={
                "user_id": uid,
                "action": action,
                "status": status,
                "details": details,
                "ip_address": ip,
            },
            headers={"x-internal-api-key": INTERNAL_API_KEY},
            timeout=2,
        )
    except Exception:
        pass


def publish(record_id: int):
    creds = pika.PlainCredentials(os.environ["RABBITMQ_DEFAULT_USER"], os.environ["RABBITMQ_DEFAULT_PASS"])
    last_error = None
    for _ in range(8):
        try:
            con = pika.BlockingConnection(pika.ConnectionParameters("rabbitmq", 5672, "/", creds))
            ch = con.channel()
            ch.queue_declare(queue="record_jobs", durable=True)
            ch.basic_publish(
                exchange="",
                routing_key="record_jobs",
                body=json.dumps({"record_id": record_id}),
                properties=pika.BasicProperties(delivery_mode=2),
            )
            con.close()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"RabbitMQ publish failed: {last_error}")


def safe_filename(filename: str) -> str:
    raw = Path(filename or "uploaded_file").name.strip().replace(" ", "_")
    keep = []
    for ch in raw:
        if ch.isalnum() or ch in {".", "_", "-"}:
            keep.append(ch)
    cleaned = "".join(keep) or "uploaded_file"
    return cleaned[:180]


def effective_mime(file: UploadFile, original_name: str) -> str:
    guessed = mimetypes.guess_type(original_name)[0]
    provided = (file.content_type or "").lower().strip()
    # Postman/browser can sometimes send text files as octet-stream. Prefer extension-based MIME for allowed types.
    return guessed or provided


def check_patient_access(patient_id: int, uid: int, role: str):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT owner_user_id FROM patients WHERE id=%s", (patient_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="patient not found")
    if role != "admin" and row[0] != uid:
        raise HTTPException(status_code=403, detail="forbidden")
    return row[0]


def get_record(record_id: int, uid: int, role: str):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, patient_id, owner_user_id, original_filename, stored_filename,
               content_type, file_size, sha256_hash, processing_status, created_at
        FROM medical_records
        WHERE id=%s
        """,
        (record_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="record not found")
    if role != "admin" and row[2] != uid:
        raise HTTPException(status_code=403, detail="forbidden")
    return row


@app.get("/health")
def health():
    return {"status": "ok", "service": "record-service"}


@app.post("/upload")
async def upload(
    request: Request,
    patient_id: int = Form(...),
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(default=None),
):
    u = auth(authorization)
    uid = int(u["sub"])
    role = u["role"]
    check_patient_access(patient_id, uid, role)

    original_name = safe_filename(file.filename or "file")
    ext = Path(original_name).suffix.lower()
    content = await file.read()
    mime = effective_mime(file, original_name)

    if not content:
        audit(uid, "file_upload", "rejected", "empty file", request.client.host)
        raise HTTPException(status_code=400, detail="empty file rejected")
    if ext in BLOCKED_EXT or ext not in ALLOWED_EXT:
        audit(uid, "file_upload", "rejected", f"bad extension={ext}", request.client.host)
        raise HTTPException(status_code=400, detail="file type rejected")
    if mime not in ALLOWED_MIME:
        audit(uid, "file_upload", "rejected", f"bad mime={file.content_type}; guessed={mime}", request.client.host)
        raise HTTPException(status_code=400, detail="file MIME type rejected")
    if len(content) > MAX_SIZE:
        audit(uid, "file_upload", "rejected", f"oversized={len(content)}", request.client.host)
        raise HTTPException(status_code=413, detail="file too large")

    sha = hashlib.sha256(content).hexdigest()
    stored = f"{uuid.uuid4().hex}{ext}.enc"
    encrypted_content = fernet.encrypt(content)
    (UPLOAD / stored).write_bytes(encrypted_content)

    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO medical_records(
          patient_id, owner_user_id, original_filename, stored_filename,
          content_type, file_size, sha256_hash
        )
        VALUES(%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
        """,
        (patient_id, uid, original_name, stored, mime, len(content), sha),
    )
    rid = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO background_jobs(record_id, job_type, status, details) VALUES(%s,%s,%s,%s)",
        (rid, "record_scan", "queued", "waiting for worker"),
    )
    conn.commit()
    cur.close()
    conn.close()

    try:
        publish(rid)
    except Exception as exc:
        conn = db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE background_jobs SET status='failed', details=%s, updated_at=CURRENT_TIMESTAMP WHERE record_id=%s",
            (str(exc)[:500], rid),
        )
        conn.commit()
        cur.close()
        conn.close()
        audit(uid, "background_job", "failed", f"record_id={rid}; {exc}", request.client.host)

    audit(uid, "file_upload", "success", f"record_id={rid}; sha256={sha}", request.client.host)
    return {
        "record_id": rid,
        "filename": original_name,
        "content_type": mime,
        "file_size": len(content),
        "sha256": sha,
        "encrypted_at_rest": True,
        "stored_file": stored,
        "status": "queued",
    }


@app.get("/")
def records(authorization: Optional[str] = Header(default=None)):
    u = auth(authorization)
    uid = int(u["sub"])
    role = u["role"]
    conn = db()
    cur = conn.cursor()
    if role == "admin":
        cur.execute(
            """
            SELECT id, patient_id, owner_user_id, original_filename, content_type,
                   file_size, sha256_hash, processing_status, created_at
            FROM medical_records
            ORDER BY id DESC
            """
        )
    else:
        cur.execute(
            """
            SELECT id, patient_id, owner_user_id, original_filename, content_type,
                   file_size, sha256_hash, processing_status, created_at
            FROM medical_records
            WHERE owner_user_id=%s
            ORDER BY id DESC
            """,
            (uid,),
        )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {
            "id": r[0],
            "patient_id": r[1],
            "owner_user_id": r[2],
            "filename": r[3],
            "content_type": r[4],
            "file_size": r[5],
            "sha256": r[6],
            "status": r[7],
            "created_at": str(r[8]),
        }
        for r in rows
    ]


@app.get("/verify/{record_id}")
def verify(record_id: int, request: Request, authorization: Optional[str] = Header(default=None)):
    u = auth(authorization)
    uid = int(u["sub"])
    role = u["role"]
    row = get_record(record_id, uid, role)
    try:
        encrypted = (UPLOAD / row[4]).read_bytes()
        data = fernet.decrypt(encrypted)
        actual = hashlib.sha256(data).hexdigest()
        valid = actual == row[7]
    except (FileNotFoundError, InvalidToken):
        actual = None
        valid = False
    audit(uid, "file_verify", "success" if valid else "failed", f"record_id={record_id}; valid={valid}", request.client.host)
    return {"record_id": record_id, "valid": valid, "expected_sha256": row[7], "actual_sha256": actual}


@app.get("/download/{record_id}")
def download(record_id: int, request: Request, authorization: Optional[str] = Header(default=None)):
    u = auth(authorization)
    uid = int(u["sub"])
    role = u["role"]
    row = get_record(record_id, uid, role)
    try:
        data = fernet.decrypt((UPLOAD / row[4]).read_bytes())
    except Exception:
        audit(uid, "file_download", "failed", f"record_id={record_id}", request.client.host)
        raise HTTPException(status_code=500, detail="file cannot be decrypted")
    audit(uid, "file_download", "success", f"record_id={record_id}", request.client.host)
    return Response(
        content=data,
        media_type=row[5],
        headers={"Content-Disposition": f'attachment; filename="{row[3]}"'},
    )


@app.post("/admin/tamper/{record_id}")
def tamper(record_id: int, request: Request, authorization: Optional[str] = Header(default=None)):
    u = auth(authorization)
    uid = int(u["sub"])
    if u.get("role") != "admin":
        audit(uid, "tamper_file", "forbidden", f"record_id={record_id}", request.client.host)
        raise HTTPException(status_code=403, detail="admin only")
    row = get_record(record_id, uid, "admin")
    with open(UPLOAD / row[4], "ab") as fh:
        fh.write(b"tampered")
    audit(uid, "tamper_file", "success", f"record_id={record_id}", request.client.host)
    return {"record_id": record_id, "tampered": True, "next_verify_should_fail": True}
