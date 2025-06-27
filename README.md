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
python3 finance.py -f bank.xlsx --fx 117.5 --sqlite --debug
