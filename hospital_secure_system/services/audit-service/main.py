import os
from typing import Optional

import psycopg2
import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Audit Service")
INTERNAL_API_KEY = os.environ["INTERNAL_API_KEY"]


def db():
    return psycopg2.connect(
        host="postgres",
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def internal(x_internal_api_key: Optional[str] = Header(default=None)):
    if x_internal_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="forbidden")


def auth_admin(authorization: Optional[str] = Header(default=None)):
    """Dashboard/admin access: use the user's JWT, not the internal API key."""
    try:
        res = requests.get(
            "http://auth-service:8000/verify",
            headers={"Authorization": authorization or ""},
            timeout=3,
        )
    except Exception:
        raise HTTPException(status_code=503, detail="auth service unavailable")

    if res.status_code != 200:
        raise HTTPException(status_code=401, detail="unauthorized")

    payload = res.json()
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    return payload


class LogIn(BaseModel):
    user_id: Optional[int] = None
    action: str = Field(min_length=2, max_length=120)
    ip_address: Optional[str] = ""
    status: str = Field(min_length=2, max_length=40)
    details: Optional[str] = ""


@app.get("/health")
def health():
    return {"status": "ok", "service": "audit-service"}


@app.post("/internal/log")
def log(data: LogIn, _: None = Depends(internal)):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO audit_logs(user_id, action, ip_address, status, details)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (data.user_id, data.action, data.ip_address, data.status, data.details),
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"ok": True}


@app.get("/logs")
def logs(_: dict = Depends(auth_admin)):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, user_id, action, ip_address, status, details, created_at
        FROM audit_logs
        ORDER BY id DESC
        LIMIT 250
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {
            "id": r[0],
            "user_id": r[1],
            "action": r[2],
            "ip_address": r[3],
            "status": r[4],
            "details": r[5],
            "created_at": str(r[6]),
        }
        for r in rows
    ]


@app.get("/metrics")
def metrics(_: dict = Depends(auth_admin)):
    queries = {
        "total_users": "SELECT count(*) FROM users",
        "active_users": "SELECT count(*) FROM users WHERE is_active=true",
        "patients": "SELECT count(*) FROM patients",
        "doctors": "SELECT count(*) FROM doctors",
        "appointments": "SELECT count(*) FROM appointments",
        "records": "SELECT count(*) FROM medical_records",
        "failed_logins": "SELECT count(*) FROM audit_logs WHERE action='login' AND status='failed'",
        "unauthorized": "SELECT count(*) FROM audit_logs WHERE status IN ('unauthorized','forbidden')",
        "processed_jobs": "SELECT count(*) FROM background_jobs WHERE status='processed'",
        "queued_jobs": "SELECT count(*) FROM background_jobs WHERE status='queued'",
    }
    conn = db()
    cur = conn.cursor()
    out = {}
    for name, sql in queries.items():
        cur.execute(sql)
        out[name] = cur.fetchone()[0]
    cur.close()
    conn.close()
    return out
