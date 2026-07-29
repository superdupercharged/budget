"""
CSV ingestion layer — parses Commerzbank-format statements and classifies
transactions using the existing budget_functions.budget class.

Expected CSV columns (semicolon-separated, German number format):
  Buchungstag ; Wertstellung ; Umsatzart ; Buchungstext ; Betrag ; Währung ; ...
Column indices used: 0=Buchungstag, 2=Umsatzart, 3=Buchungstext, 4=Betrag
"""

import sys
import os
import glob
import json
from datetime import datetime, date
from pathlib import Path

import pandas as pd

# Allow importing from workspace root (budget_functions.py lives there)
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
import budget_functions as bf


NON_EXPENSE_CATEGORIES = {
    "income",
    "savings",
    "car_loan",
    "house_loan",
    "wuestenrot",
    "tithe",
    "transfers",
}

# Fixed outflows shown separately on the dashboard (not discretionary spend).
COMMITMENT_CATEGORIES = [
    ("savings", "Savings (BNP/Consors)"),
    ("car_loan", "Car loan (Openbank/Santander)"),
    ("house_loan", "House loan"),
    ("wuestenrot", "Wüstenrot"),
    ("tithe", "Tithe (EFG)"),
]


def _parse_amount(raw: str) -> float:
    """Convert German decimal string like '-1.234,56' to float -1234.56"""
    cleaned = raw.strip().replace(".", "").replace(",", ".")
    return float(cleaned)


def load_csv(path: str) -> pd.DataFrame:
    """Load a Commerzbank CSV export robustly."""
    # Try reading; Commerzbank may have a header line before the column row
    raw = pd.read_csv(
        path,
        sep=";",
        encoding="utf-8-sig",  # handles UTF-8 BOM
        header=None,
        dtype=str,
        skip_blank_lines=True,
    )
    # Find the row containing 'Buchungstag' as the header
    header_row = None
    for i, row in raw.iterrows():
        if row.astype(str).str.contains("Buchungstag", case=False).any():
            header_row = i
            break

    if header_row is not None:
        df = pd.read_csv(
            path,
            sep=";",
            encoding="utf-8-sig",
            header=header_row,
            dtype=str,
            skip_blank_lines=True,
        )
    else:
        # Fallback: treat first row as header
        df = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str)

    # Normalize column names
    df.columns = [c.strip() for c in df.columns]
    return df


def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Return first matching column name from candidates (case-insensitive)."""
    for c in candidates:
        for col in df.columns:
            if col.lower().strip() == c.lower():
                return col
    return None


def classify_dataframe(df: pd.DataFrame) -> list[dict]:
    """
    Classify each row into a budget category.
    Returns a list of transaction dicts.
    """
    b = bf.budget()

    col_date    = _find_column(df, ["Buchungstag"])
    col_type    = _find_column(df, ["Umsatzart"])
    col_text    = _find_column(df, ["Buchungstext"])
    col_amount  = _find_column(df, ["Betrag"])

    if not col_text or not col_amount:
        raise ValueError(f"Required columns missing. Found: {list(df.columns)}")

    transactions = []
    for _, row in df.iterrows():
        text   = str(row.get(col_text, "")).strip()
        amount_raw = str(row.get(col_amount, "0")).strip()
        tx_type = str(row.get(col_type, "")).strip() if col_type else ""
        tx_date_raw = str(row.get(col_date, "")).strip() if col_date else ""

        # Skip rows with no amount or obviously empty
        if not amount_raw or amount_raw in ("nan", ""):
            continue
        try:
            amount = _parse_amount(amount_raw)
        except ValueError:
            continue

        # Skip bank-fee rows we explicitly don't want (Zinsen/Entgelte not by owner)
        if tx_type == "Zinsen/Entgelte" and "Thilo Bleumer" not in text:
            continue

        result = b.search_category(text)
        category = result[0] if result else "unclassified"
        alias    = result[1] if result else None

        # Parse date
        tx_date = None
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                tx_date = datetime.strptime(tx_date_raw, fmt).date().isoformat()
                break
            except ValueError:
                pass

        transactions.append({
            "date":     tx_date or tx_date_raw,
            "type":     tx_type,
            "text":     text,
            "amount":   amount,
            "category": category,
            "alias":    alias,
        })

    return transactions


def summarize(transactions: list[dict], limits: dict) -> dict:
    """
    Build summary for dashboard:
    - per-category spend (expenses only, summed as positive values)
    - total income
    - total spend
    - remaining budget
    - per-category limit and % used
    - commitments (savings / loans) separate from discretionary spend
    """
    income_cats = {"income"}
    commitment_keys = {k for k, _ in COMMITMENT_CATEGORIES}
    ignore_cats = NON_EXPENSE_CATEGORIES - income_cats - commitment_keys

    by_category: dict[str, float] = {}
    by_commitment: dict[str, float] = {k: 0.0 for k, _ in COMMITMENT_CATEGORIES}
    total_income = 0.0
    total_expense = 0.0
    unclassified = []

    for tx in transactions:
        cat = tx["category"]
        amt = tx["amount"]

        if cat in income_cats:
            # Only money-in counts as income (positive in Commerzbank exports).
            if amt > 0:
                total_income += amt
            continue

        if cat in commitment_keys:
            if amt < 0:
                by_commitment[cat] = by_commitment.get(cat, 0.0) + abs(amt)
            continue

        if cat in ignore_cats:
            continue

        if cat == "unclassified":
            unclassified.append(tx)
            continue

        spend = abs(amt)
        by_category[cat] = by_category.get(cat, 0.0) + spend
        total_expense += spend

    categories = []
    for cat, spent in sorted(by_category.items(), key=lambda x: -x[1]):
        limit = limits.get(cat)
        categories.append({
            "name":    cat,
            "spent":   round(spent, 2),
            "limit":   limit,
            "pct":     round(spent / limit * 100, 1) if limit else None,
            "over":    spent > limit if limit else False,
        })

    planned = limits.get("_commitments") or {}
    commitments = []
    total_commitments = 0.0
    for key, label in COMMITMENT_CATEGORIES:
        paid = round(by_commitment.get(key, 0.0), 2)
        total_commitments += paid
        expect = planned.get(key)
        commitments.append({
            "name": key,
            "label": label,
            "paid": paid,
            "planned": expect,
        })

    monthly_budget = limits.get("_total", 3000.0)
    remaining = monthly_budget - total_expense

    return {
        "total_income":   round(total_income, 2),
        "total_expense":  round(total_expense, 2),
        "total_commitments": round(total_commitments, 2),
        "monthly_budget": monthly_budget,
        "remaining":      round(remaining, 2),
        "remaining_pct":  round(remaining / monthly_budget * 100, 1),
        "categories":     categories,
        "commitments":    commitments,
        "unclassified":   unclassified,
        "transaction_count": len(transactions),
    }



def list_statement_files(statements_dir: str) -> list[str]:
    """Return statement basenames in statements_dir (non-recursive), newest first."""
    pattern = os.path.join(statements_dir, "*.CSV")
    pattern2 = os.path.join(statements_dir, "*.csv")
    files = glob.glob(pattern) + glob.glob(pattern2)
    files = sorted(files, key=os.path.getmtime, reverse=True)
    return [os.path.basename(f) for f in files]


def resolve_statement_path(statements_dir: str, month: str | None = None) -> str | None:
    """
    Pick a CSV in statements_dir.
    If month is given, prefer a filename containing that substring (e.g. '2026-07').
    Otherwise use the most recently modified file.
    """
    pattern = os.path.join(statements_dir, "*.CSV")
    pattern2 = os.path.join(statements_dir, "*.csv")
    files = glob.glob(pattern) + glob.glob(pattern2)
    if not files:
        return None

    if month:
        matches = [f for f in files if month.lower() in os.path.basename(f).lower()]
        if matches:
            files = matches

    return max(files, key=os.path.getmtime)


def load_latest_statement(statements_dir: str, month: str | None = None) -> list[dict]:
    """
    Load the most-recently-modified CSV in statements/, or the one matching month.
    """
    path = resolve_statement_path(statements_dir, month)
    if not path:
        return []
    df = load_csv(path)
    return classify_dataframe(df)


def load_statement_with_meta(statements_dir: str, month: str | None = None) -> tuple[list[dict], str | None]:
    """Like load_latest_statement, but also returns the source basename."""
    path = resolve_statement_path(statements_dir, month)
    if not path:
        return [], None
    df = load_csv(path)
    return classify_dataframe(df), os.path.basename(path)
