## 🔧 Features

- Auto-detects export header rows from shitty Excel bank statements
- Tags NEEDS vs WANTS using vendor memory persisted in SQLite
- Regex-based vendor identification (LIDL, Car:Go, TIDAL, Binance, etc.)
- Category classification: Income, Stocks, Savings, ATM, Spending
- Auto-generates:
  - Totals by category
  - Top vendor spending
  - Daily, hourly, monthly, and rolling spend charts
  - NEEDS vs WANTS pie
  - 12-month net worth projection
- CSV + SQLite export (transactions + vendor tags)
- REST API + web UI for managing vendor tags per user
- Console summary with vampire detection (parasitic vendors)

## 🐍 Requirements

- Python 3.10+
- `pandas`, `matplotlib`, `openpyxl`

## 🚀 Usage

```bash
Obtain xls from your bank, put it in dir next to the script. Let it rip.
python3 finance.py -f bank.xlsx --fx 117.5 --sqlite --user me@example.com
```

### 🗂 Vendor tag service

Launch the Flask app to manage tags (defaults to port 5000):

```bash
pip install -r requirements.txt
flask --app app run
```

Set `X-User-Id` header (or `?user_id=` query) to scope data per user.

API examples:

```bash
curl -H "X-User-Id: me@example.com" http://localhost:5000/api/vendor-tags
curl -X POST -H "Content-Type: application/json" -H "X-User-Id: me@example.com" \
     -d '{"vendor":"LIDL","class":"NEEDS"}' http://localhost:5000/api/vendor-tags
```
