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
