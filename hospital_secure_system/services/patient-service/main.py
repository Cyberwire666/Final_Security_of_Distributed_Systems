import os
from datetime import datetime
from typing import Optional

import psycopg2
import requests
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

app = FastAPI(title="Patient & Appointment Service")
INTERNAL_API_KEY = os.environ["INTERNAL_API_KEY"]


def db():
    return psycopg2.connect(host="postgres", dbname=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"])


def auth(authorization: Optional[str]):
    r = requests.get("http://auth-service:8000/verify", headers={"Authorization": authorization or ""}, timeout=3)
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="unauthorized")
    return r.json()


def audit(uid, action, status, details, ip=""):
    try:
        requests.post("http://audit-service:8000/internal/log", json={"user_id": uid, "action": action, "status": status, "details": details, "ip_address": ip}, headers={"x-internal-api-key": INTERNAL_API_KEY}, timeout=2)
    except Exception:
        pass


def require_admin(payload):
    if payload.get("role") != "admin":
        audit(int(payload["sub"]), "admin_patient_access", "forbidden", "not admin")
        raise HTTPException(status_code=403, detail="admin only")


class PatientIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    age: int = Field(ge=0, le=130)
    gender: str = Field(default="unknown", max_length=20)
    phone: str = Field(default="", max_length=40)
    diagnosis: str = Field(default="", max_length=1000)


class DoctorIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    specialty: str = Field(min_length=2, max_length=120)
    phone: str = Field(default="", max_length=40)


class AppointmentIn(BaseModel):
    patient_id: int
    doctor_id: Optional[int] = None
    appointment_time: datetime
    reason: str = Field(default="", max_length=500)

    @field_validator("appointment_time")
    @classmethod
    def future_time(cls, value):
        if value <= datetime.utcnow():
            raise ValueError("appointment date cannot be in the past")
        return value


class AppointmentStatusIn(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def status_ok(cls, value):
        if value not in {"scheduled", "completed", "cancelled"}:
            raise ValueError("invalid status")
        return value


@app.get("/health")
def health():
    return {"status": "ok", "service": "patient-service"}


@app.post("/")
def create_patient(data: PatientIn, request: Request, authorization: Optional[str] = Header(default=None)):
    u = auth(authorization); uid = int(u["sub"])
    conn = db(); cur = conn.cursor()
    cur.execute("INSERT INTO patients(owner_user_id,full_name,age,gender,phone,diagnosis) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id", (uid, data.full_name, data.age, data.gender, data.phone, data.diagnosis))
    pid = cur.fetchone()[0]; conn.commit(); cur.close(); conn.close()
    audit(uid, "create_patient", "success", f"patient_id={pid}", request.client.host)
    return {"id": pid, **data.model_dump()}


@app.get("/")
def list_patients(authorization: Optional[str] = Header(default=None)):
    u = auth(authorization); uid = int(u["sub"]); role = u["role"]
    conn = db(); cur = conn.cursor()
    if role == "admin":
        cur.execute("SELECT id,owner_user_id,full_name,age,gender,phone,diagnosis,created_at FROM patients ORDER BY id DESC")
    else:
        cur.execute("SELECT id,owner_user_id,full_name,age,gender,phone,diagnosis,created_at FROM patients WHERE owner_user_id=%s ORDER BY id DESC", (uid,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [{"id": r[0], "owner_user_id": r[1], "full_name": r[2], "age": r[3], "gender": r[4], "phone": r[5], "diagnosis": r[6], "created_at": str(r[7])} for r in rows]


@app.get("/{patient_id}")
def get_patient(patient_id: int, authorization: Optional[str] = Header(default=None)):
    u = auth(authorization); uid = int(u["sub"]); role = u["role"]
    conn = db(); cur = conn.cursor(); cur.execute("SELECT id,owner_user_id,full_name,age,gender,phone,diagnosis,created_at FROM patients WHERE id=%s", (patient_id,)); r = cur.fetchone(); cur.close(); conn.close()
    if not r: raise HTTPException(status_code=404, detail="patient not found")
    if role != "admin" and r[1] != uid:
        audit(uid, "read_patient", "forbidden", f"patient_id={patient_id}")
        raise HTTPException(status_code=403, detail="forbidden")
    return {"id": r[0], "owner_user_id": r[1], "full_name": r[2], "age": r[3], "gender": r[4], "phone": r[5], "diagnosis": r[6], "created_at": str(r[7])}


@app.delete("/{patient_id}")
def delete_patient(patient_id: int, request: Request, authorization: Optional[str] = Header(default=None)):
    u = auth(authorization); require_admin(u)
    conn = db(); cur = conn.cursor(); cur.execute("DELETE FROM patients WHERE id=%s RETURNING id", (patient_id,)); row = cur.fetchone(); conn.commit(); cur.close(); conn.close()
    if not row: raise HTTPException(status_code=404, detail="patient not found")
    audit(int(u["sub"]), "delete_patient", "success", f"patient_id={patient_id}", request.client.host)
    return {"deleted": patient_id}


@app.post("/doctors")
def create_doctor(data: DoctorIn, request: Request, authorization: Optional[str] = Header(default=None)):
    u = auth(authorization); require_admin(u)
    conn = db(); cur = conn.cursor(); cur.execute("INSERT INTO doctors(full_name,specialty,phone) VALUES(%s,%s,%s) RETURNING id", (data.full_name, data.specialty, data.phone)); did = cur.fetchone()[0]; conn.commit(); cur.close(); conn.close()
    audit(int(u["sub"]), "create_doctor", "success", f"doctor_id={did}", request.client.host)
    return {"id": did, **data.model_dump()}


@app.get("/doctors/list")
def list_doctors(authorization: Optional[str] = Header(default=None)):
    auth(authorization)
    conn = db(); cur = conn.cursor(); cur.execute("SELECT id,full_name,specialty,phone,created_at FROM doctors ORDER BY id DESC"); rows = cur.fetchall(); cur.close(); conn.close()
    return [{"id": r[0], "full_name": r[1], "specialty": r[2], "phone": r[3], "created_at": str(r[4])} for r in rows]


@app.post("/appointments")
def create_appointment(data: AppointmentIn, request: Request, authorization: Optional[str] = Header(default=None)):
    u = auth(authorization); uid = int(u["sub"]); role = u["role"]
    conn = db(); cur = conn.cursor(); cur.execute("SELECT owner_user_id FROM patients WHERE id=%s", (data.patient_id,)); owner = cur.fetchone()
    if not owner:
        cur.close(); conn.close(); raise HTTPException(status_code=404, detail="patient not found")
    if role != "admin" and owner[0] != uid:
        cur.close(); conn.close(); audit(uid, "create_appointment", "forbidden", f"patient_id={data.patient_id}"); raise HTTPException(status_code=403, detail="forbidden")
    cur.execute("INSERT INTO appointments(owner_user_id,patient_id,doctor_id,appointment_time,reason) VALUES(%s,%s,%s,%s,%s) RETURNING id", (owner[0], data.patient_id, data.doctor_id, data.appointment_time, data.reason))
    aid = cur.fetchone()[0]; conn.commit(); cur.close(); conn.close()
    audit(uid, "create_appointment", "success", f"appointment_id={aid}", request.client.host)
    return {"id": aid, **data.model_dump(mode="json"), "status": "scheduled"}


@app.get("/appointments/list")
def list_appointments(authorization: Optional[str] = Header(default=None)):
    u = auth(authorization); uid = int(u["sub"]); role = u["role"]
    base = "SELECT a.id,a.owner_user_id,a.patient_id,p.full_name,d.full_name,a.appointment_time,a.reason,a.status FROM appointments a JOIN patients p ON p.id=a.patient_id LEFT JOIN doctors d ON d.id=a.doctor_id"
    conn = db(); cur = conn.cursor()
    if role == "admin":
        cur.execute(base + " ORDER BY a.appointment_time DESC")
    else:
        cur.execute(base + " WHERE a.owner_user_id=%s ORDER BY a.appointment_time DESC", (uid,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [{"id": r[0], "owner_user_id": r[1], "patient_id": r[2], "patient_name": r[3], "doctor_name": r[4], "appointment_time": str(r[5]), "reason": r[6], "status": r[7]} for r in rows]


@app.patch("/appointments/{appointment_id}/status")
def update_appointment_status(appointment_id: int, data: AppointmentStatusIn, request: Request, authorization: Optional[str] = Header(default=None)):
    u = auth(authorization); require_admin(u)
    conn = db(); cur = conn.cursor(); cur.execute("UPDATE appointments SET status=%s WHERE id=%s RETURNING id", (data.status, appointment_id)); row = cur.fetchone(); conn.commit(); cur.close(); conn.close()
    if not row: raise HTTPException(status_code=404, detail="appointment not found")
    audit(int(u["sub"]), "update_appointment", "success", f"appointment_id={appointment_id}; status={data.status}", request.client.host)
    return {"id": appointment_id, "status": data.status}
