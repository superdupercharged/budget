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
python3 run_dashboard.py          # http://localhost:8000 (binds 0.0.0.0)
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

### Docker (LAN / phone test)

Runs the same dashboard on port **8000**, listening on `0.0.0.0`, with `data/` and `statements/` persisted via volumes. No sample screenshots are baked into the image.

```bash
# Build & start
docker compose up --build -d

# Or without compose:
docker build -t budget-dashboard:local .
mkdir -p data statements
docker run --rm -p 8000:8000 \
  -v "$PWD/data:/app/data" \
  -v "$PWD/statements:/app/statements" \
  -v "$PWD/dashboard/config.json:/app/dashboard/config.json" \
  -v "$PWD/budget_dict.json:/app/budget_dict.json" \
  budget-dashboard:local
```

On this machine: [http://localhost:8000/](http://localhost:8000/)  
On a phone (same Wi‑Fi): `http://<host-lan-ip>:8000/` — find the host IP with `ip addr` / `hostname -I` (Linux) or System Settings → Network (macOS/Windows).

If the phone cannot connect, allow inbound TCP **8000** on the host firewall (e.g. `ufw allow 8000/tcp`). Screenshot upload is on the home page (**Screenshot** → **Ingest shot**); temp images are deleted after OCR.

```bash
docker compose down
```

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

**Web UI:** on the home page (`/`), use **Screenshot** + **Ingest shot** next to the CSV upload. The server writes a temp file, runs the same OCR→SQLite path, then **deletes the image** (OCR text + bookings remain in the DB; no image blobs stored).

## Configuration

| File | Purpose |
|------|---------|
| `budget_dict.json` | Merchant keyword → category mappings |
| `dashboard/config.json` | Monthly budget limits (EUR) per category |

Statements go in `statements/` (gitignored). CSVs are semicolon-separated Commerzbank exports.
