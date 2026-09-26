# Budget

Personal budgeting tool for Commerzbank CSV statements. Classifies transactions by merchant keywords and shows monthly spend against category limits.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Screenshot ingest (local OCR)

System packages (Debian/Ubuntu):

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng
```

Python deps (`pytesseract`, `Pillow`) are in `requirements.txt`. OCR is local only — no cloud vision APIs.

## Categories

| Category | Covers |
|----------|--------|
| `income` | Salary, family benefits, gratuities |
| `compensation` | Inflows from own savings to cover spending (not earned income) |
| `housing` | Rent, utilities, municipal fees |
| `renovation` | DIY / builders merchants, materials, craftsmen (Hornbach, Bauhaus, …) |
| `food` | Groceries, restaurants, bakeries |
| `mobility` | Fuel, car, parking, charging |
| `life` | Everyday / household / health / telecom |
| `fun` | Leisure, hobbies, streaming, entertainment |
| `shopping` | Clothes, home goods, online retail |
| `holidays` | Travel and vacation |
| `savings` | Transfers to Consorsbank / BNP savings |
| `car_loan` | Openbank / Santander car loan (~€258) |
| `house_loan` | Sparkasse Neu-Ulm mortgage (`Darl.-Leistung` / ~€1,700) |
| `wuestenrot` | Wüstenrot Bausparen + Bausparkredit |
| `tithe` | EFG Neu-Ulm Spende / MOSAIK (~€500) |
| `transfers` | Other internal moves, credit-card settlement |
| `other` | Fees and uncategorized known merchants |

Keyword mappings live in `budget_dict.json`.

## Classify unknowns

Scan all `statements/*.CSV` / `*.csv` (non-recursive; ignores `archive/`), auto-suggest merchant rules, and optionally prompt for leftovers:

```bash
python3 classify_unknown.py              # stats + dry-run auto suggestions
python3 classify_unknown.py --apply      # write auto-rules into budget_dict.json
python3 classify_unknown.py --ask        # apply auto-rules, then prompt for remaining groups
```

## Dashboard

```bash
python3 run_dashboard.py          # http://localhost:8000
python3 run_dashboard.py --port 8080
```

- Pick a **month** (`YYYY-MM`) — bank + Visa files are merged automatically by filename
  (`2026-07_statement.CSV` + `2026-07_visa_statement.CSV`)
- Bank-side Visa **Abrechnung** (card settlement) is ignored as `transfers`; spend comes from Visa transactions
- Upload a statement CSV in the UI (or place one in `statements/`)
- View income, expenses, commitments, and per-category budget progress
- **Trends** page (`/trends`): line chart of spend per category over months, with checkboxes to show/hide series
- **Stores** page (`/stores`): treemap of Food, Life, Fun & Shopping spend by merchant for a month
- Edit monthly limits in the UI (stored in `dashboard/config.json`)

## CLI

```bash
python3 budget.py <month>   # expects statements/<month>_statement.CSV
```

Interactively classifies unclassified bookings and prints a category summary.

### Screenshot bookings

Second ingest path next to CSV statements. Parses Commerzbank “Buchungen” screenshots with local Tesseract, stores rows in `data/screenshot_bookings.db`, and dedupes by fingerprint (merchant + date + amount) so overlapping daily shots do not double-count.

```bash
# Dry-run (OCR + parse only)
python3 -m dashboard.screenshot_ingest path/to/shot.jpg --dry-run --date 2026-09-26

# Ingest into SQLite (default DB: data/screenshot_bookings.db)
python3 -m dashboard.screenshot_ingest path/to/shot.jpg --date 2026-09-26
python3 -m dashboard.screenshot_ingest path/to/shots/ --db data/screenshot_bookings.db
```

`--date` is the reference day for `Gestern` / `Heute` / missing dates (defaults to today). Re-running the same image inserts zero new bookings. The dashboard merges screenshot rows for a month alongside CSV statements (`source_kind=screenshot`).

## Configuration

| File | Purpose |
|------|---------|
| `budget_dict.json` | Merchant keyword → category mappings |
| `dashboard/config.json` | Monthly budget limits (EUR) per category |

Statements go in `statements/` (gitignored). CSVs are semicolon-separated Commerzbank exports.
