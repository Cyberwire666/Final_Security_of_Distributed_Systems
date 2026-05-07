# Hospital Secure System PATCH v2

This is a patch only. Copy/replace these folders/files over the existing COMPLETE project:

- `dashboard/index.html`
- `services/audit-service/main.py`
- `services/record-service/main.py`
- `scripts/generate_secrets.py`

## What this patch fixes

1. Dashboard no longer asks for `INTERNAL_API_KEY` in the browser.
2. Audit metrics/logs now use the admin JWT securely.
3. Upload logic is more robust for Postman and frontend.
4. Frontend upload uses real `FormData` and shows proper errors.
5. Frontend design upgraded to a professional admin dashboard.
6. File download from dashboard now works with the JWT Authorization header.
7. Record service now handles MIME detection better and queues jobs more safely.

## Apply patch

From the project root:

```bash
# copy patch files over your existing project, then rebuild only changed services
python scripts/generate_secrets.py
MSYS_NO_PATHCONV=1 bash scripts/generate_cert.sh

docker compose up -d --build audit-service record-service nginx
```

If your database schema is already from the COMPLETE version, you do NOT need `docker compose down -v`.

## Postman upload

Method: POST

URL:

```text
https://localhost/api/records/upload
```

Authorization:

```text
Bearer YOUR_JWT_TOKEN
```

Body: `form-data`

| Key | Type | Value |
|---|---|---|
| patient_id | Text | 1 |
| file | File | any `.pdf`, `.png`, `.jpg`, `.jpeg`, `.txt` |

Disable SSL verification in Postman because this is a local self-signed certificate.
