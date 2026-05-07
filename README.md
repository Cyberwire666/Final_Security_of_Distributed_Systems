# Secure Distributed Hospital Management System

## Overview

Secure Distributed Hospital Management System is a modern microservices-based healthcare platform designed to demonstrate secure distributed system architecture, API security, containerization, authentication, authorization, encrypted file handling, asynchronous processing, and monitoring.

The project was developed as a final project for the Secure Distributed Systems course.

The system focuses on:

* Distributed architecture
* Secure communication
* JWT authentication
* RBAC authorization
* HTTPS/TLS
* Encrypted medical records
* RabbitMQ asynchronous processing
* Audit logging
* Dockerized deployment
* Secure API Gateway
* React dashboard

---

# Main Features

## Authentication & Security

* User registration
* User login
* JWT authentication
* Password hashing using bcrypt
* Token expiration
* Protected routes
* Role-Based Access Control (RBAC)
* Internal service authentication
* HTTPS/TLS encryption
* Rate limiting
* Secure headers
* Input validation
* Secure environment variables

---

## Hospital Features

* Admin dashboard
* User dashboard
* Patient management
* Appointment management
* Medical record management
* Secure medical file upload
* SHA-256 file integrity verification
* Encrypted file storage
* Audit logging
* Metrics dashboard

---

## Distributed Architecture

The project uses a distributed microservices architecture.

### Services

| Service           | Description                               |
| ----------------- | ----------------------------------------- |
| Nginx API Gateway | HTTPS termination, routing, rate limiting |
| Auth Service      | Authentication, JWT, RBAC                 |
| Patient Service   | Patient operations                        |
| Record Service    | File upload and medical records           |
| Audit Service     | Logs and monitoring                       |
| Worker Service    | Background processing                     |
| PostgreSQL        | Database                                  |
| RabbitMQ          | Message queue                             |
| React Dashboard   | Frontend UI                               |

---

# Architecture Diagram

```text
Client
   ↓
Nginx API Gateway
   ↓
────────────────────────────────
| Auth Service                |
| Patient Service             |
| Record Service              |
| Audit Service               |
| Worker Service              |
────────────────────────────────
   ↓
PostgreSQL Database
   ↓
RabbitMQ Queue
```

---

# Technologies Used

## Backend

* Python 3.12
* FastAPI
* PostgreSQL
* RabbitMQ
* Psycopg2
* bcrypt
* JWT
* cryptography (Fernet)

---

## Frontend

* React
* HTML5
* CSS3
* JavaScript

---

## DevOps & Infrastructure

* Docker
* Docker Compose
* Nginx
* OpenSSL

---

# Security Features

## 1. JWT Authentication

Users authenticate using JWT tokens.

Features:

* Signed tokens
* Expiration handling
* Protected APIs
* Token validation

---

## 2. Password Hashing

Passwords are never stored in plaintext.

Implemented using:

```text
bcrypt
```

---

## 3. RBAC Authorization

Roles:

| Role  | Permissions             |
| ----- | ----------------------- |
| Admin | Full system access      |
| User  | Limited personal access |

---

## 4. HTTPS/TLS

Nginx terminates HTTPS connections using self-signed OpenSSL certificates.

---

## 5. Rate Limiting

Nginx protects APIs against abuse.

Example:

```text
10 requests per minute per IP
```

---

## 6. Secure File Upload

Medical file uploads are validated using:

* Allowed extensions
* MIME type validation
* File size validation
* Safe filenames
* Blocked dangerous extensions

Blocked extensions:

```text
.exe
.php
.js
.bat
.sh
```

---

## 7. File Encryption

Uploaded medical files are encrypted before storage using:

```text
Fernet AES encryption
```

---

## 8. SHA-256 Integrity Verification

Every uploaded file generates:

```text
SHA-256 hash
```

Used to verify integrity.

---

## 9. Service-to-Service Security

Internal APIs use:

```text
INTERNAL_API_KEY
```

to secure communication between services.

---

## 10. Audit Logging

The system logs:

* Successful logins
* Failed logins
* Unauthorized access
* File uploads
* File downloads
* Background jobs
* Admin actions

---

# Project Structure

```text
hospital_secure_system/
│
├── dashboard/
├── db/
├── nginx/
├── scripts/
├── services/
│   ├── auth-service/
│   ├── patient-service/
│   ├── record-service/
│   ├── audit-service/
│   └── worker-service/
│
├── uploads/
├── docker-compose.yml
├── .env
└── README.md
```

---

# Installation & Setup

## 1. Clone Repository

```bash
git clone https://github.com/Cyberwire666/Final_Security_of_Distributed_Systems.git
cd Final_Security_of_Distributed_Systems
```

---

## 2. Generate Secrets

```bash
python scripts/generate_secrets.py
```

Copy generated values into:

```text
.env
```

---

## 3. Generate HTTPS Certificates

### Git Bash

```bash
MSYS_NO_PATHCONV=1 bash scripts/generate_cert.sh
```

---

## 4. Start System

```bash
docker compose up --build
```

---

# Access URLs

| Service            | URL                                              |
| ------------------ | ------------------------------------------------ |
| Frontend Dashboard | [https://localhost](https://localhost)           |
| RabbitMQ Dashboard | [http://localhost:15672](http://localhost:15672) |
| PostgreSQL         | localhost:5432                                   |

---

# Default Environment Variables

```env
POSTGRES_DB=hospitaldb
POSTGRES_USER=hospital_user
POSTGRES_PASSWORD=123

JWT_SECRET=your_secret
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60

INTERNAL_API_KEY=your_internal_key
```

---

# API Examples

## Register

```http
POST /api/auth/register
```

```json
{
  "email": "admin@test.com",
  "password": "Admin123!",
  "role": "admin"
}
```

---

## Login

```http
POST /api/auth/login
```

```json
{
  "email": "admin@test.com",
  "password": "Admin123!"
}
```

---

## Create Patient

```http
POST /api/patients
```

---

## Upload Medical Record

```http
POST /api/records/upload
```

---

# PostgreSQL Access

## pgAdmin Connection

| Field    | Value         |
| -------- | ------------- |
| Host     | 127.0.0.1     |
| Port     | 5432          |
| Database | hospitaldb    |
| Username | hospital_user |
| Password | 123           |

---

# RabbitMQ Access

```text
http://localhost:15672
```

Credentials are configured inside:

```text
.env
```

---

# Demonstration Scenarios

## Successful Login

* User logs in successfully
* JWT token generated
* Dashboard access granted

---

## Unauthorized Access

* Missing token
* Invalid token
* Access denied

---

## Rate Limiting Demo

* Multiple rapid requests
* Nginx blocks excessive traffic

---

## File Integrity Verification

* Original file passes verification
* Modified file fails verification

---

# Monitoring & Metrics

Dashboard displays:

* Total users
* Total patients
* Uploaded files
* Failed logins
* Unauthorized attempts
* Background jobs

---

# Docker Containers

The system runs using Docker Compose.

Containers:

* nginx
* auth-service
* patient-service
* record-service
* audit-service
* worker-service
* postgres
* rabbitmq

---

# Educational Objectives

This project demonstrates:

* Secure distributed architecture
* Microservices communication
* Authentication & authorization
* API Gateway design
* HTTPS deployment
* Secure file handling
* Asynchronous systems
* Monitoring and audit logging
* Dockerized infrastructure

---

# Contributors

| Name          | 
| ------------- | 
| Yehia Tarek   | 
| Sara Atalla   | 
| Amr Khaled    | 
| Mariam Waleed | 
| Marwan Farouk |
| Rewan El Wardani |

---

# Future Improvements

* Full OAuth integration
* Grafana monitoring
* Kubernetes deployment
* Multi-factor authentication
* Email notifications
* Cloud deployment
* CI/CD pipeline

---

# License

This project was developed for educational purposes as part of the Secure Distributed Systems course.
