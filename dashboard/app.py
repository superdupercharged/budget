"""
Budget Dashboard — FastAPI backend

Endpoints:
  GET  /              → month dashboard
  GET  /trends        → category spend over time
  GET  /stores        → food/life/fun/shopping merchant treemap
  GET  /api/summary   → JSON summary of current month
  GET  /api/trends    → JSON monthly series per category
  GET  /api/stores    → JSON spend by merchant (food, life, fun, shopping)
  GET  /api/transactions → JSON list of all classified transactions
  POST /api/upload    → upload a new CSV statement
  POST /api/upload-screenshot → OCR ingest a Buchungen screenshot
  POST /api/limits    → update budget limits
"""

import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ingest import (
    load_statement_with_meta,
    list_months,
    summarize,
    monthly_trends,
    merchant_breakdown,
    category_budget_total,
)
from screenshot_db import DEFAULT_DB, ingest_screenshot

BASE_DIR    = Path(__file__).parent
ROOT_DIR    = BASE_DIR.parent
STATEMENTS  = ROOT_DIR / "statements"
CONFIG_FILE = BASE_DIR / "config.json"
STATIC_DIR  = BASE_DIR / "static"
SCREENSHOT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}

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
    budget = category_budget_total(limits)
    return {
        "total_income": 0,
        "total_compensation": 0,
        "total_expense": 0,
        "total_commitments": 0,
        "monthly_budget": budget,
        "remaining": budget,
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


@app.get("/trends", response_class=HTMLResponse)
async def trends_page():
    html_path = BASE_DIR / "templates" / "trends.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/stores", response_class=HTMLResponse)
async def stores_page():
    html_path = BASE_DIR / "templates" / "stores.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/api/trends")
async def get_trends():
    STATEMENTS.mkdir(exist_ok=True)
    return JSONResponse(monthly_trends(str(STATEMENTS)))


@app.get("/api/stores")
async def get_stores(month: str | None = None):
    STATEMENTS.mkdir(exist_ok=True)
    return JSONResponse(
        merchant_breakdown(str(STATEMENTS), month, ["food", "life", "fun", "shopping"])
    )


@app.get("/api/statements")
async def get_statements():
    STATEMENTS.mkdir(exist_ok=True)
    return JSONResponse({"months": list_months(str(STATEMENTS))})


@app.get("/api/summary")
async def get_summary(month: str | None = None):
    limits = load_limits()
    STATEMENTS.mkdir(exist_ok=True)
    transactions, source = load_statement_with_meta(str(STATEMENTS), month)
    if not transactions:
        return JSONResponse(empty_summary(
            limits,
            "No statement or screenshot bookings found. Upload a CSV or screenshot.",
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


@app.post("/api/upload-screenshot")
async def upload_screenshot(
    file: UploadFile = File(...),
    ref_date: str | None = Form(None),
):
    """
    Ingest a Buchungen screenshot: OCR → SQLite → classify.
    The uploaded image is deleted after processing (success or failure).
    """
    if not file.filename:
        raise HTTPException(400, "Missing filename.")
    safe_name = Path(file.filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SCREENSHOT_SUFFIXES:
        raise HTTPException(
            400,
            f"Unsupported image type {suffix!r}. Use: {', '.join(sorted(SCREENSHOT_SUFFIXES))}",
        )

    reference: date | None = None
    if ref_date:
        raw = ref_date.strip()
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                reference = datetime.strptime(raw, fmt).date()
                break
            except ValueError:
                continue
        if reference is None:
            raise HTTPException(400, "Invalid ref_date; use YYYY-MM-DD or DD.MM.YYYY")

    tmp_path: Path | None = None
    try:
        content = await file.read()
        if not content:
            raise HTTPException(400, "Empty upload.")
        fd, tmp_name = tempfile.mkstemp(suffix=suffix, prefix="budget-shot-")
        tmp_path = Path(tmp_name)
        try:
            os.write(fd, content)
        finally:
            os.close(fd)

        result = ingest_screenshot(
            tmp_path,
            db_path=DEFAULT_DB,
            reference_date=reference,
            delete_file=True,
        )
    except HTTPException:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Screenshot ingest failed: {exc}") from exc

    month = None
    for b in result.get("bookings") or []:
        d = b.get("date") or ""
        if len(d) >= 7:
            month = d[:7]
            break

    return JSONResponse({
        "status": "ok",
        "filename": safe_name,
        "parsed": result["parsed"],
        "inserted": result["inserted"],
        "skipped_dupes": result["skipped_dupes"],
        "month": month,
        "file_deleted": True,
        "bookings": [
            {
                "date": b["date"],
                "text": b["text"],
                "amount": b["amount"],
                "category": b.get("category"),
                "status": b.get("status"),
            }
            for b in result.get("bookings") or []
        ],
    })


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
        if k.startswith("_"):
            continue  # total budget is derived; meta keys not editable here
        try:
            limits[k] = float(v)
        except (TypeError, ValueError):
            raise HTTPException(400, f"Invalid value for {k}: {v}")
    limits["_total"] = category_budget_total(limits)
    save_limits(limits)
    return JSONResponse({"status": "ok", "limits": limits})
