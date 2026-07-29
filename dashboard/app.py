"""
Budget Dashboard — FastAPI backend

Endpoints:
  GET  /              → serves the dashboard HTML
  GET  /api/summary   → JSON summary of current month
  GET  /api/transactions → JSON list of all classified transactions
  POST /api/upload    → upload a new CSV statement
  POST /api/limits    → update budget limits
"""

import json
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ingest import load_statement_with_meta, list_statement_files, summarize

BASE_DIR    = Path(__file__).parent
ROOT_DIR    = BASE_DIR.parent
STATEMENTS  = ROOT_DIR / "statements"
CONFIG_FILE = BASE_DIR / "config.json"
STATIC_DIR  = BASE_DIR / "static"

app = FastAPI(title="Budget Dashboard")
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def load_limits() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_limits(limits: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(limits, f, indent=2)


def empty_summary(limits: dict, error: str) -> dict:
    return {
        "total_income": 0,
        "total_expense": 0,
        "total_commitments": 0,
        "monthly_budget": limits.get("_total", 3000),
        "remaining": limits.get("_total", 3000),
        "remaining_pct": 100,
        "categories": [],
        "commitments": [],
        "unclassified": [],
        "transaction_count": 0,
        "source": None,
        "error": error,
    }


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = BASE_DIR / "templates" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/api/statements")
async def get_statements():
    STATEMENTS.mkdir(exist_ok=True)
    return JSONResponse({"files": list_statement_files(str(STATEMENTS))})


@app.get("/api/summary")
async def get_summary(month: str | None = None):
    limits = load_limits()
    STATEMENTS.mkdir(exist_ok=True)
    transactions, source = load_statement_with_meta(str(STATEMENTS), month)
    if not transactions:
        return JSONResponse(empty_summary(
            limits, "No statement file found. Upload a CSV to get started."
        ))
    summary = summarize(transactions, limits)
    summary["source"] = source
    return JSONResponse(summary)


@app.get("/api/transactions")
async def get_transactions(month: str | None = None):
    STATEMENTS.mkdir(exist_ok=True)
    transactions, source = load_statement_with_meta(str(STATEMENTS), month)
    return JSONResponse({"transactions": transactions, "source": source})


@app.post("/api/upload")
async def upload_statement(file: UploadFile = File(...)):
    if not file.filename or not (
        file.filename.endswith(".CSV") or file.filename.endswith(".csv")
    ):
        raise HTTPException(400, "Only CSV files are accepted.")
    # Keep uploads in the statements root (never into subdirs)
    safe_name = Path(file.filename).name
    STATEMENTS.mkdir(exist_ok=True)
    dest = STATEMENTS / safe_name
    content = await file.read()
    dest.write_bytes(content)
    return JSONResponse({"status": "ok", "filename": safe_name})


@app.get("/api/config")
async def get_config():
    return JSONResponse(load_limits())


@app.get("/api/limits")
async def get_limits():
    return JSONResponse(load_limits())


@app.post("/api/limits")
async def update_limits(body: dict = Body(...)):
    limits = load_limits()
    for k, v in body.items():
        try:
            limits[k] = float(v)
        except (TypeError, ValueError):
            raise HTTPException(400, f"Invalid value for {k}: {v}")
    save_limits(limits)
    return JSONResponse({"status": "ok", "limits": limits})
