"""
SQLite storage for screenshot OCR bookings with fingerprint dedupe.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import budget_functions as bf

from dashboard.screenshot_ocr import (
    amount_to_cents,
    fingerprint,
    parse_screenshot,
)

DEFAULT_DB = ROOT / "data" / "screenshot_bookings.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS screenshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_hash TEXT NOT NULL UNIQUE,
    original_filename TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    ocr_text TEXT,
    status TEXT NOT NULL DEFAULT 'ok'
);

CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(id),
    booking_date TEXT NOT NULL,
    text TEXT NOT NULL,
    amount REAL NOT NULL,
    amount_cents INTEGER NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    category TEXT,
    alias TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(booking_date);
"""


def _normalize_alias(alias: str | None) -> str | None:
    """Match dashboard.ingest.normalize_alias without importing ingest."""
    if not alias:
        return alias
    compact = re.sub(r"[^a-z0-9]", "", alias.lower())
    if "amzn" in compact or "amazon" in compact:
        return "Amazon"
    return alias


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_booking(text: str) -> tuple[str, str | None]:
    b = bf.budget()
    result = b.classify_text(text)
    if result:
        return result[0], _normalize_alias(result[1])
    return "unclassified", None


def ingest_screenshot(
    image_path: str | Path,
    *,
    db_path: str | Path | None = None,
    reference_date: date | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """
    OCR + parse + store. Fingerprint collisions are skipped (dedupe).

    Returns counts: inserted, skipped_dupes, parsed, screenshot_id, bookings.
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    own_conn = conn is None
    conn = conn or connect(db_path)
    try:
        fhash = file_sha256(path)
        now = datetime.now().isoformat(timespec="seconds")

        existing = conn.execute(
            "SELECT id, status FROM screenshots WHERE file_hash = ?", (fhash,)
        ).fetchone()

        ocr_text, parsed = parse_screenshot(path, reference_date=reference_date)

        if existing:
            screenshot_id = existing["id"]
        else:
            cur = conn.execute(
                "INSERT INTO screenshots"
                " (file_hash, original_filename, ingested_at, ocr_text, status)"
                " VALUES (?, ?, ?, ?, ?)",
                (fhash, path.name, now, ocr_text, "ok"),
            )
            screenshot_id = cur.lastrowid

        inserted = 0
        skipped = 0
        rows_out: list[dict] = []
        for pb in parsed:
            cents = amount_to_cents(pb.amount)
            fp = fingerprint(pb.text, pb.booking_date, cents)
            category, alias = classify_booking(pb.text)
            try:
                conn.execute(
                    "INSERT INTO bookings "
                    "(screenshot_id, booking_date, text, amount, amount_cents, "
                    " fingerprint, category, alias, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        screenshot_id,
                        pb.booking_date.isoformat(),
                        pb.text,
                        pb.amount,
                        cents,
                        fp,
                        category,
                        alias,
                        now,
                    ),
                )
                inserted += 1
                status = "inserted"
            except sqlite3.IntegrityError:
                skipped += 1
                status = "duplicate"
            rows_out.append(
                {
                    "text": pb.text,
                    "amount": pb.amount,
                    "date": pb.booking_date.isoformat(),
                    "date_raw": pb.date_raw,
                    "category": category,
                    "alias": alias,
                    "fingerprint": fp,
                    "status": status,
                }
            )

        conn.commit()
        return {
            "screenshot_id": screenshot_id,
            "file_hash": fhash,
            "parsed": len(parsed),
            "inserted": inserted,
            "skipped_dupes": skipped,
            "bookings": rows_out,
            "ocr_text": ocr_text,
        }
    finally:
        if own_conn:
            conn.close()


def list_booking_months(db_path: str | Path | None = None) -> list[str]:
    """YYYY-MM keys that have at least one screenshot booking."""
    path = Path(db_path) if db_path else DEFAULT_DB
    if not path.exists():
        return []
    conn = connect(path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT substr(booking_date, 1, 7) AS m FROM bookings ORDER BY m DESC"
        ).fetchall()
        return [r["m"] for r in rows]
    finally:
        conn.close()


def load_bookings_for_month(
    month: str,
    db_path: str | Path | None = None,
) -> list[dict]:
    """
    Load screenshot bookings for YYYY-MM as txn dicts matching CSV shape
    (+ source_kind='screenshot').
    """
    if not re.fullmatch(r"\d{4}-\d{2}", month or ""):
        return []
    path = Path(db_path) if db_path else DEFAULT_DB
    if not path.exists():
        return []
    conn = connect(path)
    try:
        rows = conn.execute(
            "SELECT booking_date, text, amount, category, alias FROM bookings"
            " WHERE booking_date LIKE ?"
            " ORDER BY booking_date, id",
            (f"{month}%",),
        ).fetchall()
        return [
            {
                "date": r["booking_date"],
                "type": "Screenshot",
                "text": r["text"],
                "amount": float(r["amount"]),
                "category": r["category"] or "unclassified",
                "alias": r["alias"],
                "source_file": None,
                "source_kind": "screenshot",
            }
            for r in rows
        ]
    finally:
        conn.close()
