# Budget

Personal budgeting tool for Commerzbank CSV statements. Classifies transactions by merchant keywords and shows monthly spend against category limits.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Categories

| Category | Covers |
|----------|--------|
| `income` | Salary, family benefits, gratuities |
| `housing` | Rent, utilities, municipal fees |
| `food` | Groceries, restaurants, bakeries |
| `mobility` | Fuel, car, parking, charging |
| `life` | Everyday / household / health / telecom |
| `fun` | Leisure, hobbies, streaming, entertainment |
| `shopping` | Clothes, home goods, online retail |
| `holidays` | Travel and vacation |
| `savings` | Transfers to Consorsbank / BNP savings |
| `car_loan` | Openbank / Santander car loan (~€258) |
| `house_loan` | Mortgage / Darlehen (~€1,700) |
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

- Upload a statement CSV in the UI (or place one in `statements/`)
- View income, expenses, and per-category budget progress
- Edit monthly limits in the UI (stored in `dashboard/config.json`)

## CLI

```bash
python3 budget.py <month>   # expects statements/<month>_statement.CSV
```

Interactively classifies unclassified bookings and prints a category summary.

## Configuration

| File | Purpose |
|------|---------|
| `budget_dict.json` | Merchant keyword → category mappings |
| `dashboard/config.json` | Monthly budget limits (EUR) per category |

Statements go in `statements/` (gitignored). CSVs are semicolon-separated Commerzbank exports.
