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
- Structured storage layer (local filesystem or S3) with manifest + metadata
- JSON chart specs + CSV export for streaming front-ends
- Console summary with vampire detection (parasitic vendors)

## 🐍 Requirements

- Python 3.10+
- `pandas`, `matplotlib`, `openpyxl`
- `boto3` (only when using the S3 backend)

## 🚀 Usage

```bash
Obtain xls from your bank, put it in dir next to the script. Let it rip.
python3 finance.py -f bank.xlsx --fx 117.5 --sqlite --debug --user alice

# Storage configuration

Artifacts for each run are now stored via a pluggable backend. The default is a
local filesystem store rooted at `./storage/` with metadata in `metadata.db`.

Environment variables:

- `WALLETTASER_STORAGE_BACKEND` – `local` (default) or `s3`
- `WALLETTASER_STORAGE_PATH` – base directory for local storage
- `WALLETTASER_METADATA_PATH` – override metadata SQLite path
- `WALLETTASER_S3_BUCKET` / `WALLETTASER_S3_PREFIX` – destination for S3 backend
- `WALLETTASER_USER_ID` – default user id when `--user` is omitted
- `WALLETTASER_MAX_RESULTS`, `WALLETTASER_MAX_AGE_DAYS`,
  `WALLETTASER_MAX_STORAGE_MB` – retention policy knobs per user

Every chart generates both a PNG and a JSON spec, and a `manifest.json`
summarises the run for streaming to a frontend. Retention jobs run after each
execution to keep per-user storage usage in check.
