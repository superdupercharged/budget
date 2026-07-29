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
import os
import shutil
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ingest import load_latest_statement, summarize

BASE_DIR    = Path(__file__).parent
ROOT_DIR    = BASE_DIR.parent
STATEMENTS  = ROOT_DIR / "statements"
CONFIG_FILE = BASE_DIR / "config.json"
STATIC_DIR  = BASE_DIR / "static"

app = FastAPI(title="Budget Dashboard")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def load_limits() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_limits(limits: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(limits, f, indent=2)


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = BASE_DIR / "templates" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/api/summary")
async def get_summary():
    limits = load_limits()
    STATEMENTS.mkdir(exist_ok=True)
    transactions = load_latest_statement(str(STATEMENTS))
    if not transactions:
        # Return empty state so the UI still renders
        return JSONResponse({
            "total_income": 0,
            "total_expense": 0,
            "monthly_budget": limits.get("_total", 3000),
            "remaining": limits.get("_total", 3000),
            "remaining_pct": 100,
            "categories": [],
            "unclassified": [],
            "transaction_count": 0,
            "error": "No statement file found. Upload a CSV to get started."
        })
    summary = summarize(transactions, limits)
    return JSONResponse(summary)


@app.get("/api/transactions")
async def get_transactions():
    STATEMENTS.mkdir(exist_ok=True)
    transactions = load_latest_statement(str(STATEMENTS))
    return JSONResponse({"transactions": transactions})


@app.post("/api/upload")
async def upload_statement(file: UploadFile = File(...)):
    if not (file.filename.endswith(".CSV") or file.filename.endswith(".csv")):
        raise HTTPException(400, "Only CSV files are accepted.")
    STATEMENTS.mkdir(exist_ok=True)
    dest = STATEMENTS / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return JSONResponse({"status": "ok", "filename": file.filename})


@app.get("/api/config")
async def get_config():
    return JSONResponse(load_limits())


@app.get("/api/limits")
async def get_limits():
    return JSONResponse(load_limits())


@app.post("/api/limits")
async def update_limits(body: dict):
    limits = load_limits()
    for k, v in body.items():
        try:
            limits[k] = float(v)
        except (TypeError, ValueError):
            raise HTTPException(400, f"Invalid value for {k}: {v}")
    save_limits(limits)
    return JSONResponse({"status": "ok", "limits": limits})
