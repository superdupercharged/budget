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


EXPENSE_CATEGORIES = {
    "income", "gratuity", "saving", "kredit-card"
}


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
    """
    income_cats = {"income", "gratuity"}
    ignore_cats = {"saving", "kredit-card", "tenth"}

    by_category: dict[str, float] = {}
    total_income = 0.0
    total_expense = 0.0
    unclassified = []

    for tx in transactions:
        cat = tx["category"]
        amt = tx["amount"]

        if cat in income_cats:
            # Income: positive values in Commerzbank CSV mean money IN
            # (amount signs vary by bank — we handle both)
            total_income += abs(amt)
            continue

        if cat in ignore_cats:
            continue

        if cat == "unclassified":
            unclassified.append(tx)
            continue

        # Expenses are debit (negative in our demo, positive in some exports)
        spend = abs(amt)
        by_category[cat] = by_category.get(cat, 0.0) + spend
        total_expense += spend

    # Build per-category breakdown with limits
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

    monthly_budget = limits.get("_total", 3000.0)
    remaining = monthly_budget - total_expense

    return {
        "total_income":   round(total_income, 2),
        "total_expense":  round(total_expense, 2),
        "monthly_budget": monthly_budget,
        "remaining":      round(remaining, 2),
        "remaining_pct":  round(remaining / monthly_budget * 100, 1),
        "categories":     categories,
        "unclassified":   unclassified,
        "transaction_count": len(transactions),
    }


def load_latest_statement(statements_dir: str, month: str | None = None) -> list[dict]:
    """
    Load the most-recently-modified CSV in statements/, or the one matching month.
    """
    pattern = os.path.join(statements_dir, "*.CSV")
    pattern2 = os.path.join(statements_dir, "*.csv")
    files = glob.glob(pattern) + glob.glob(pattern2)
    if not files:
        return []

    if month:
        matches = [f for f in files if month.lower() in os.path.basename(f).lower()]
        if matches:
            files = matches

    latest = max(files, key=os.path.getmtime)
    df = load_csv(latest)
    return classify_dataframe(df)
