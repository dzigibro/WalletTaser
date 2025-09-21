## 🔧 Features

- Auto-detects export header rows from shitty Excel bank statements
- Tags NEEDS vs WANTS using vendor memory (`vendor_tags.csv`)
- Regex-based vendor identification (LIDL, Car:Go, TIDAL, Binance, etc.)
- Category classification: Income, Stocks, Savings, ATM, Spending
- Auto-generates:
  - Totals by category
  - Top vendor spending
  - Daily, hourly, monthly, and rolling spend charts
  - NEEDS vs WANTS pie
  - 12-month net worth projection
- CSV + SQLite export
- Console summary with vampire detection (parasitic vendors)
- Browser dashboard with inline chart previews, text snippets, and one-click
  secure cleanup of generated artefacts

## 🐍 Requirements

- Python 3.10+
- `pandas`, `matplotlib`, `openpyxl`

## 🚀 Usage

```bash
Obtain xls from your bank, put it in dir next to the script. Let it rip.
python3 finance.py -f bank.xlsx --fx 117.5 --sqlite --debug
```

## 🖥️ API Service

An asynchronous, multi-tenant HTTP API is available via FastAPI and Celery.

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the services

Open three terminals (or background the workers):

```bash
# API (http://127.0.0.1:8000/docs)
uvicorn wallettaser.api:app --reload

# Celery worker
CELERY_BROKER_URL=redis://localhost:6379/0 \
CELERY_RESULT_BACKEND=redis://localhost:6379/0 \
celery -A wallettaser.celery_app.celery_app worker --loglevel=info

# Redis (if you do not already have one)
redis-server
```

Set `CELERY_TASK_ALWAYS_EAGER=1` when developing to execute jobs synchronously
without the worker.

### 3. Authenticate

Use the bundled demo tenant (`demo` / `demo`) to obtain a bearer token:

```bash
curl -X POST http://127.0.0.1:8000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"username": "demo", "password": "demo"}'
```

### 4. Upload statements

```bash
curl -X POST http://127.0.0.1:8000/statements/upload \
  -H 'Authorization: Bearer <token>' \
  -F 'file=@statement.xlsx'
```

Use the `/statements/{job_id}` endpoint to poll for completion and
`/statements/{job_id}/result` to download the generated ZIP archive. Each user is
isolated to their tenant: uploads, tags, and reports are stored in
`data/<tenant-id>/`.

### API Reference (JSON)

- `POST /statements/upload`
  - Body: multipart file field `file`, optional query `fx_rate` override.
  - Response: `{ "job_id": "...", "status": "queued", "detail_path": "/statements/<id>" }`
- `GET /statements`
  - Returns the newest jobs for the authenticated tenant. Example payload:
    ```json
    [
      {
        "job_id": "abc123",
        "filename": "statement.xlsx",
        "status": "completed",
        "fx_rate": 117.0,
        "created_at": "2024-05-01T12:00:00",
        "started_at": "2024-05-01T12:00:02",
        "completed_at": "2024-05-01T12:00:15",
        "result_path": "data/<tenant>/archives/abc123.zip",
        "report_directory": "data/<tenant>/reports/abc123",
        "summary": { "average_income": 12345.0, "projected_net": [...], ... }
      }
    ]
    ```
- `GET /statements/{job_id}`
  - Returns the same structure as above for a single job.
- `GET /statements/{job_id}/summary`
  - Convenience endpoint that returns `{ "job_id": "...", "summary": {...} }` once the report is ready.
- `GET /statements/{job_id}/result`
  - Streams the generated ZIP archive for download.

### 🖼️ Web Dashboard

Looking for a friendlier face on top of the API? A static frontend lives in
`frontend/` and can be served by any HTTP server (no build step required).

```bash
cd frontend
python -m http.server 5173
# open http://127.0.0.1:5173 in your browser
```

Log in with the same credentials you use for the API (`demo`/`demo` by default).
Use the dashboard to upload statements, inspect job history, stream the
generated charts/CSV assets inline, and grab the ZIP only if you want the raw
files. Need to scrub a report once you have your insights? Hit the "Delete
Report" button to purge the generated artefacts from disk and the database.

### 🐳 Docker Quickstart

Spin up the whole stack (API + Celery worker + Redis + dashboard) in one shot:

```bash
docker compose up --build -d
```

- API: http://127.0.0.1:8000
- Dashboard: http://127.0.0.1:8080 (configure API URL to `http://api:8000` if you
  access it from another container, otherwise keep `http://127.0.0.1:8000`).
- Persistent artefacts land under the `data/` named volume (`wallettaser.db`,
  generated reports, archives, and vendor tags).

When hosting on a remote server, update the dashboard's "API Base URL" field to
use the public hostname (e.g. `http://your.server.ip:8000`). Cross-origin
requests are enabled server-side so the dashboard can talk to the API from a
different port.

Uploads are restricted to Excel/CSV files (`.xls`, `.xlsx`, `.csv`). Filenames are
sanitized and rewritten per job to keep the storage area clean and mitigate
obvious upload shenanigans.
