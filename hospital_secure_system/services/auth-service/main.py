import datetime
import html
import os
from typing import Optional
from urllib.parse import urlencode

import jwt
import psycopg2
import requests
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field, field_validator

app = FastAPI(title="Auth Service")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
JWT_SECRET = os.environ["JWT_SECRET"]
INTERNAL_API_KEY = os.environ["INTERNAL_API_KEY"]
JWT_HOURS = int(os.getenv("JWT_EXP_HOURS", "2"))
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "https://localhost/api/auth/oauth/github/callback")
OAUTH_STATE = os.getenv("OAUTH_STATE", "hospital-secure-oauth-state")
OAUTH_DEFAULT_ROLE = os.getenv("OAUTH_DEFAULT_ROLE", "user")


def db():
    return psycopg2.connect(
        host="postgres",
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def audit(user_id, action, status, details, ip=""):
    try:
        requests.post(
            "http://audit-service:8000/internal/log",
            json={"user_id": user_id, "action": action, "status": status, "details": details, "ip_address": ip},
            headers={"x-internal-api-key": INTERNAL_API_KEY},
            timeout=2,
        )
    except Exception:
        pass


def create_token(user_id: int, role: str):
    payload = {"sub": str(user_id), "role": role, "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=JWT_HOURS)}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(default="", max_length=150)
    role: str = "user"

    @field_validator("password")
    @classmethod
    def strong_password(cls, value):
        if not any(c.isupper() for c in value) or not any(c.islower() for c in value) or not any(c.isdigit() for c in value):
            raise ValueError("password must include uppercase, lowercase, and digit")
        return value

    @field_validator("role")
    @classmethod
    def valid_role(cls, value):
        if value not in {"user", "admin"}:
            raise ValueError("invalid role")
        return value


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RoleUpdateIn(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def valid_role(cls, value):
        if value not in {"user", "admin"}:
            raise ValueError("invalid role")
        return value


@app.post("/register")
def register(data: RegisterIn, request: Request):
    conn = db(); cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users(email,password_hash,role,full_name) VALUES(%s,%s,%s,%s) RETURNING id",
            (data.email, pwd.hash(data.password), data.role, data.full_name),
        )
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO user_roles(user_id, role_id) SELECT %s, id FROM roles WHERE name=%s ON CONFLICT DO NOTHING", (uid, data.role))
        conn.commit(); audit(uid, "register", "success", f"new {data.role} user", request.client.host)
        return {"id": uid, "email": data.email, "full_name": data.full_name, "role": data.role}
    except psycopg2.errors.UniqueViolation:
        conn.rollback(); audit(None, "register", "failed", "email already exists", request.client.host); raise HTTPException(status_code=409, detail="email already exists")
    finally:
        cur.close(); conn.close()


@app.post("/login")
def login(data: LoginIn, request: Request):
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT id,password_hash,role,is_active FROM users WHERE email=%s", (data.email,))
    row = cur.fetchone(); cur.close(); conn.close()
    if not row or not pwd.verify(data.password, row[1]):
        audit(None, "login", "failed", "invalid credentials", request.client.host)
        raise HTTPException(status_code=401, detail="invalid credentials")
    if not row[3]:
        audit(row[0], "login", "failed", "inactive account", request.client.host)
        raise HTTPException(status_code=403, detail="account disabled")
    token = create_token(row[0], row[2])
    audit(row[0], "login", "success", "jwt issued", request.client.host)
    return {"access_token": token, "token_type": "bearer", "role": row[2]}


@app.get("/verify")
def verify(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing token")
    try:
        payload = jwt.decode(authorization.split()[1], JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    return payload


@app.get("/me")
def me(authorization: Optional[str] = Header(default=None)):
    payload = verify(authorization)
    uid = int(payload["sub"])
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT id,email,role,full_name,is_active,created_at,oauth_provider FROM users WHERE id=%s", (uid,))
    r = cur.fetchone(); cur.close(); conn.close()
    if not r:
        raise HTTPException(status_code=404, detail="user not found")
    return {"id": r[0], "email": r[1], "role": r[2], "full_name": r[3], "is_active": r[4], "created_at": str(r[5]), "oauth_provider": r[6]}


def require_admin(authorization: Optional[str]):
    payload = verify(authorization)
    if payload.get("role") != "admin":
        audit(int(payload["sub"]), "admin_access", "forbidden", "admin endpoint rejected")
        raise HTTPException(status_code=403, detail="admin only")
    return payload


@app.get("/admin/users")
def users(authorization: Optional[str] = Header(default=None)):
    require_admin(authorization)
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT id,email,role,full_name,is_active,created_at,oauth_provider FROM users ORDER BY id DESC")
    rows = cur.fetchall(); cur.close(); conn.close()
    return [{"id": r[0], "email": r[1], "role": r[2], "full_name": r[3], "is_active": r[4], "created_at": str(r[5]), "oauth_provider": r[6]} for r in rows]


@app.patch("/admin/users/{user_id}/role")
def update_role(user_id: int, data: RoleUpdateIn, authorization: Optional[str] = Header(default=None)):
    admin = require_admin(authorization)
    conn = db(); cur = conn.cursor()
    cur.execute("UPDATE users SET role=%s WHERE id=%s RETURNING id", (data.role, user_id))
    row = cur.fetchone()
    if not row:
        conn.rollback(); cur.close(); conn.close(); raise HTTPException(status_code=404, detail="user not found")
    cur.execute("DELETE FROM user_roles WHERE user_id=%s", (user_id,))
    cur.execute("INSERT INTO user_roles(user_id, role_id) SELECT %s, id FROM roles WHERE name=%s", (user_id, data.role))
    conn.commit(); cur.close(); conn.close(); audit(int(admin["sub"]), "update_role", "success", f"user_id={user_id}; role={data.role}")
    return {"id": user_id, "role": data.role}


@app.patch("/admin/users/{user_id}/disable")
def disable_user(user_id: int, authorization: Optional[str] = Header(default=None)):
    admin = require_admin(authorization)
    conn = db(); cur = conn.cursor(); cur.execute("UPDATE users SET is_active=false WHERE id=%s RETURNING id", (user_id,)); row = cur.fetchone(); conn.commit(); cur.close(); conn.close()
    if not row: raise HTTPException(status_code=404, detail="user not found")
    audit(int(admin["sub"]), "disable_user", "success", f"user_id={user_id}")
    return {"id": user_id, "is_active": False}


def oauth_enabled():
    return bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET)


@app.get("/oauth/github/start")
def github_start():
    if not oauth_enabled():
        return {
            "enabled": False,
            "message": "Set GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, OAUTH_REDIRECT_URI, and OAUTH_STATE in .env, then rebuild auth-service.",
            "github_callback_url": OAUTH_REDIRECT_URI,
        }
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "scope": "read:user user:email",
        "state": OAUTH_STATE,
        "allow_signup": "true",
    }
    return {"enabled": True, "authorize_url": "https://github.com/login/oauth/authorize?" + urlencode(params), "callback_url": OAUTH_REDIRECT_URI}


@app.get("/oauth/github/callback")
def github_callback(request: Request, code: str = "", state: str = "") :
    if not oauth_enabled():
        raise HTTPException(status_code=503, detail="GitHub OAuth is not configured")
    if not code:
        raise HTTPException(status_code=400, detail="missing OAuth code")
    if state != OAUTH_STATE:
        audit(None, "oauth_github", "failed", "invalid state", request.client.host)
        raise HTTPException(status_code=400, detail="invalid OAuth state")

    token_res = requests.post(
        "https://github.com/login/oauth/access_token",
        json={"client_id": GITHUB_CLIENT_ID, "client_secret": GITHUB_CLIENT_SECRET, "code": code, "redirect_uri": OAUTH_REDIRECT_URI},
        headers={"Accept": "application/json"},
        timeout=10,
    )
    token_data = token_res.json()
    access_token = token_data.get("access_token")
    if not access_token:
        audit(None, "oauth_github", "failed", "token exchange failed", request.client.host)
        raise HTTPException(status_code=400, detail="OAuth token exchange failed")

    gh_headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
    profile = requests.get("https://api.github.com/user", headers=gh_headers, timeout=10).json()
    emails = requests.get("https://api.github.com/user/emails", headers=gh_headers, timeout=10).json()

    primary_email = profile.get("email")
    if isinstance(emails, list):
        verified = [e for e in emails if e.get("primary") and e.get("verified")]
        fallback = [e for e in emails if e.get("verified")]
        chosen = (verified or fallback or emails[:1])
        if chosen:
            primary_email = chosen[0].get("email")
    if not primary_email:
        primary_email = f"github-{profile.get('id')}@oauth.local"

    subject = str(profile.get("id"))
    full_name = profile.get("name") or profile.get("login") or "GitHub User"
    role = OAUTH_DEFAULT_ROLE if OAUTH_DEFAULT_ROLE in {"user", "admin"} else "user"

    conn = db(); cur = conn.cursor()
    cur.execute("SELECT id,role,is_active FROM users WHERE oauth_provider='github' AND oauth_subject=%s", (subject,))
    row = cur.fetchone()
    if not row:
        cur.execute("SELECT id,role,is_active FROM users WHERE email=%s", (primary_email,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE users SET oauth_provider='github', oauth_subject=%s, full_name=COALESCE(NULLIF(full_name,''),%s) WHERE id=%s", (subject, full_name, row[0]))
        else:
            cur.execute(
                "INSERT INTO users(email,password_hash,role,full_name,oauth_provider,oauth_subject) VALUES(%s,%s,%s,%s,'github',%s) RETURNING id,role,is_active",
                (primary_email, pwd.hash(secrets_placeholder_password(subject)), role, full_name, subject),
            )
            row = cur.fetchone()
            cur.execute("INSERT INTO user_roles(user_id, role_id) SELECT %s, id FROM roles WHERE name=%s ON CONFLICT DO NOTHING", (row[0], row[1]))
    conn.commit(); cur.close(); conn.close()

    if not row[2]:
        audit(row[0], "oauth_github", "failed", "inactive account", request.client.host)
        raise HTTPException(status_code=403, detail="account disabled")

    token = create_token(row[0], row[1])
    audit(row[0], "oauth_github", "success", "jwt issued via GitHub", request.client.host)
    safe_token = html.escape(token, quote=True)
    safe_role = html.escape(row[1], quote=True)
    return HTMLResponse(f"""
<!doctype html><html><head><meta charset='utf-8'><title>OAuth Success</title></head>
<body style="font-family:Arial;background:#fff5f6;color:#17202a;display:grid;place-items:center;height:100vh;margin:0">
  <div style="background:white;border:1px solid #ffd5da;border-radius:24px;padding:28px;box-shadow:0 20px 60px rgba(215,25,32,.12);text-align:center">
    <h2 style="color:#d71920;margin-top:0">GitHub OAuth login successful</h2>
    <p>Redirecting to dashboard...</p>
  </div>
  <script>
    localStorage.setItem('token', '{safe_token}');
    localStorage.setItem('role', '{safe_role}');
    window.location.href = '/';
  </script>
</body></html>
""")


def secrets_placeholder_password(subject: str) -> str:
    return f"oauth-github-{subject}-{JWT_SECRET[:16]}"


@app.get("/health")
def health():
    return {"status": "ok", "service": "auth-service", "github_oauth_enabled": oauth_enabled()}
