# Secure Hospital Management System

A clean distributed **Non-AI Hospital Management System** built for the Secure Distributed System final project.

It implements a hospital platform with:

- Admin/User roles
- Patient management
- Doctor management
- Appointment booking
- Secure medical record upload
- Encrypted file storage
- SHA-256 integrity verification
- Audit logging
- RabbitMQ background processing
- React dashboard served through Nginx
- Docker Compose deployment

The project follows the assignment focus: **distributed architecture + security practices + clean implementation**.

---

## 1. Architecture

```text
Browser / Postman
      |
      v
Nginx API Gateway HTTPS :443
      |
      |-- /api/auth/*      -> auth-service
      |-- /api/patients/*  -> patient-service
      |-- /api/records/*   -> record-service
      |-- /api/audit/*     -> audit-service
      |
      v
PostgreSQL + RabbitMQ + Worker Service
```

### Containers

| Container | Purpose |
|---|---|
| nginx | API Gateway, HTTPS, rate limit, security headers, dashboard hosting |
| auth-service | Register, login, JWT, BCrypt, RBAC admin endpoints |
| patient-service | Patients, doctors, appointments |
| record-service | Secure upload, encryption, SHA-256, download, verification |
| audit-service | Audit logs and metrics |
| worker-service | RabbitMQ consumer for background record jobs |
| postgres | Database |
| rabbitmq | Message queue and management UI |

---

## 2. Run the Project

### Step 1: Create environment file

```bash
cp .env.example .env
```

### Step 2: Generate Fernet encryption key

```bash
python scripts/generate_keys.py
```

Copy the printed value into `.env`:

```env
FERNET_KEY=paste_generated_key_here
```

### Step 3: Generate HTTPS certificate

Git Bash:

```bash
MSYS_NO_PATHCONV=1 bash scripts/generate_cert.sh
```

PowerShell can also run the script if Git Bash is installed:

```powershell
bash scripts/generate_cert.sh
```

### Step 4: Reset old database volume if you used an older version

```bash
docker compose down -v
```

### Step 5: Start everything

```bash
docker compose up --build
```

Open:

```text
https://localhost
```

The browser will warn about the self-signed certificate. Choose **Advanced** then **Proceed to localhost**.

RabbitMQ dashboard:

```text
http://localhost:15672
```

Use the RabbitMQ user/password from `.env`.

---

## 3. Dashboard Usage

1. Open `https://localhost`.
2. Register an admin:
   - email: `admin@test.com`
   - password: `Admin1234`
   - role: `admin`
3. Login.
4. Paste `INTERNAL_API_KEY` from `.env` into the dashboard key box to load admin metrics/logs.
5. Create patients, doctors, appointments, and upload records.

Note: The dashboard uses React UMD from `unpkg.com`. APIs and backend run locally through Docker.

---

## 4. API Demo Commands

Use Git Bash for these commands.

### Register Admin

```bash
curl -k -X POST https://localhost/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@test.com","password":"Admin1234","full_name":"Admin User","role":"admin"}'
```

### Login

```bash
TOKEN=$(curl -ks -X POST https://localhost/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@test.com","password":"Admin1234"}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo $TOKEN
```

### Create Patient

```bash
curl -k -X POST https://localhost/api/patients/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"full_name":"Ahmed Patient","age":35,"gender":"male","phone":"01000000000","diagnosis":"Routine check"}'
```

### List Patients

```bash
curl -k https://localhost/api/patients/ \
  -H "Authorization: Bearer $TOKEN"
```

### Book Appointment

Use a future date:

```bash
curl -k -X POST https://localhost/api/patients/appointments \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"patient_id":1,"doctor_id":1,"appointment_time":"2027-01-01T10:00:00","reason":"Follow-up"}'
```

### Upload File

```bash
echo "secure test medical record" > test-record.txt

curl -k -X POST https://localhost/api/records/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "patient_id=1" \
  -F "file=@test-record.txt;type=text/plain"
```

### Verify SHA-256 Integrity

```bash
curl -k https://localhost/api/records/verify/1 \
  -H "Authorization: Bearer $TOKEN"
```

### Admin Metrics

```bash
curl -k https://localhost/api/audit/metrics \
  -H "x-internal-api-key: change_me_internal_service_key"
```

Replace the key with your `.env` value.

---

## 5. Implemented Security Tasks

| Task | Status | Implementation |
|---|---:|---|
| 1 Authentication | Complete | Register, login, JWT, expiration, protected routes |
| 2 Password Hashing | Complete | BCrypt hashes only |
| 3 Authorization/RBAC | Complete | Admin/User role checks, own-data isolation |
| 4 OAuth Login | Partial/Prepared | GitHub OAuth start endpoint + `.env` placeholders; real provider requires client credentials |
| 5 API Gateway | Complete | Nginx routes all services |
| 6 HTTPS | Complete | OpenSSL self-signed certificate and TLS termination |
| 7 Rate Limiting | Complete | Nginx general and login limits |
| 8 Input Validation | Complete | Pydantic validation, password rules, future appointments |
| 9 Secure File Upload | Complete | Extension, MIME, size checks, dangerous extensions blocked |
| 10 File Encryption | Complete | Fernet encryption before storage |
| 11 Integrity Verification | Complete | SHA-256 stored and verified |
| 12 Service-to-Service Security | Complete | Internal API key for audit service |
| 13 Secrets Management | Complete | `.env`, no source-code secrets |
| 14 Database Security | Complete | Roles, permissions, ownership fields, audit logs |
| 15 Message Queue | Complete | RabbitMQ publish/consume flow |
| 16 Queue Security | Complete | Custom RabbitMQ user/password from `.env`; no guest/guest |
| 17 Logging/Audit Trail | Complete | login, upload, download, admin, unauthorized, background job events |
| 18 Monitoring Dashboard | Complete | React dashboard metrics/logs/data |
| 19 Error Handling | Complete | Safe HTTP errors, no stack traces exposed by API responses |
| 20 Docker Compose | Complete | Full multi-container deployment |

---

## 6. Attack Simulation Checklist

Use these during the presentation.

### Missing JWT

```bash
curl -k https://localhost/api/patients/
```

Expected: `401 unauthorized`.

### Invalid JWT

```bash
curl -k https://localhost/api/patients/ -H "Authorization: Bearer badtoken"
```

Expected: `401 invalid token`.

### User Cannot Access Admin Endpoint

Login as a normal user then run:

```bash
curl -k https://localhost/api/auth/admin/users -H "Authorization: Bearer $USER_TOKEN"
```

Expected: `403 admin only`.

### Dangerous File Rejected

```bash
echo "bad" > malware.js
curl -k -X POST https://localhost/api/records/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "patient_id=1" \
  -F "file=@malware.js;type=application/javascript"
```

Expected: rejected.

### Rate Limit

```bash
for i in {1..15}; do curl -k -s -o /dev/null -w "%{http_code}\n" -X POST https://localhost/api/auth/login -H "Content-Type: application/json" -d '{"email":"x@test.com","password":"Wrong1234"}'; done
```

Expected: after several requests, Nginx returns `503` or rate-limit response.

### Tamper Detection

Admin only:

```bash
curl -k -X POST https://localhost/api/records/admin/tamper/1 -H "Authorization: Bearer $TOKEN"
curl -k https://localhost/api/records/verify/1 -H "Authorization: Bearer $TOKEN"
```

Expected: verification fails.

---

## 7. Project Structure

```text
hospital_secure_system/
  dashboard/                 React dashboard page
  db/init/001_schema.sql      PostgreSQL schema and seed data
  nginx/nginx.conf            Gateway, HTTPS, rate limit, headers
  scripts/                    certificate and key generation
  services/
    auth-service/             JWT, BCrypt, RBAC, users
    patient-service/          patients, doctors, appointments
    record-service/           secure file upload, encryption, SHA-256
    audit-service/            logs and metrics
    worker-service/           RabbitMQ consumer
  docker-compose.yml
  .env.example
  README.md
```
