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
import re
from datetime import datetime, date
from pathlib import Path

import pandas as pd

# Allow importing from workspace root (budget_functions.py lives there)
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
import budget_functions as bf


NON_EXPENSE_CATEGORIES = {
    "income",
    "compensation",
    "savings",
    "car_loan",
    "house_loan",
    "wuestenrot",
    "tithe",
    "transfers",
}

# Fixed outflows shown separately on the dashboard (not discretionary spend).
COMMITMENT_CATEGORIES = [
    ("house_loan", "House loan (Sparkasse)"),
    ("tithe", "Tithe (EFG)"),
    ("car_loan", "Car loan (Openbank/Santander)"),
    ("savings", "Savings (BNP/Consors)"),
    ("wuestenrot", "Wüstenrot"),
]


def normalize_alias(alias: str | None) -> str | None:
    """Merge merchant spelling variants into one display/aggregate name."""
    if not alias:
        return alias
    compact = re.sub(r"[^a-z0-9]", "", alias.lower())
    if "amzn" in compact or "amazon" in compact:
        return "Amazon"
    return alias


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


def _is_savings_compensation(amount: float, text: str, sender: str) -> bool:
    """
    Money-in from own savings / self to cover spending.
    Outgoing self-transfers (negative) must NOT match.
    """
    if amount <= 0:
        return False
    t = (text or "").strip().lower()
    s = (sender or "").strip().lower()
    if s.startswith("thilo bleumer") or "bleumer-ventures" in s:
        return True
    if t.startswith("thilo bleumer") or t.startswith("bleumer-ventures"):
        return True
    if "kompenstion" in t or "kompensation" in t:
        return True
    return False


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
    col_recv    = _find_column(df, ["Empfänger", "Empfaenger"])
    col_purpose = _find_column(df, ["Verwendungszweck"])
    col_sender  = _find_column(df, ["Sender"])

    if not col_text or not col_amount:
        raise ValueError(f"Required columns missing. Found: {list(df.columns)}")

    transactions = []
    for _, row in df.iterrows():
        text   = str(row.get(col_text, "")).strip()
        amount_raw = str(row.get(col_amount, "0")).strip()
        tx_type = str(row.get(col_type, "")).strip() if col_type else ""
        tx_date_raw = str(row.get(col_date, "")).strip() if col_date else ""
        recv = str(row.get(col_recv, "")).strip() if col_recv else ""
        purpose = str(row.get(col_purpose, "")).strip() if col_purpose else ""
        sender = str(row.get(col_sender, "")).strip() if col_sender else ""
        if recv in ("nan", "None"):
            recv = ""
        if purpose in ("nan", "None"):
            purpose = ""
        if sender in ("nan", "None"):
            sender = ""

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

        # Search across booking text + counterpart + purpose.
        # PayPal/Klarna: prefer embedded merchant (see budget.classify_text).
        search_blob = " | ".join(p for p in (text, recv, purpose) if p)
        result = b.classify_text(search_blob)
        category = result[0] if result else "unclassified"
        alias    = result[1] if result else None

        # Own savings top-ups / spend compensation (income subcategory)
        if _is_savings_compensation(amount, text, sender):
            category = "compensation"
            alias = alias or "self-transfer"

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
            "alias":    normalize_alias(alias),
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
    compensation_cats = {"compensation"}
    commitment_keys = {k for k, _ in COMMITMENT_CATEGORIES}
    ignore_cats = NON_EXPENSE_CATEGORIES - income_cats - compensation_cats - commitment_keys

    by_category: dict[str, float] = {}
    by_commitment: dict[str, float] = {k: 0.0 for k, _ in COMMITMENT_CATEGORIES}
    total_income = 0.0
    total_compensation = 0.0
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

        if cat in compensation_cats:
            # Savings draw / self top-up — income subcategory, tracked separately.
            if amt > 0:
                total_compensation += amt
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

        # Debits add spend; credits/refunds in the same category offset it.
        if amt == 0:
            continue
        by_category[cat] = by_category.get(cat, 0.0) - amt
        total_expense -= amt

    categories = []
    # Don't let refund-heavy months go negative in the UI.
    total_expense = 0.0
    for cat, raw in by_category.items():
        spent = max(0.0, raw)
        by_category[cat] = spent
        total_expense += spent

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

    monthly_budget = category_budget_total(limits)
    remaining = monthly_budget - total_expense

    return {
        "total_income":   round(total_income, 2),
        "total_compensation": round(total_compensation, 2),
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


_MONTH_RE = re.compile(r"^(\d{4}-\d{2})")


def month_key_from_name(name: str) -> str | None:
    """Extract YYYY-MM prefix from a statement filename."""
    m = _MONTH_RE.match(os.path.basename(name))
    return m.group(1) if m else None


def list_months(statements_dir: str) -> list[str]:
    """Unique YYYY-MM keys present in statements/, newest first."""
    months = {
        key
        for name in list_statement_files(statements_dir)
        if (key := month_key_from_name(name))
    }
    return sorted(months, reverse=True)


# Discretionary spend categories shown on the trends chart by default.
TREND_SPEND_CATEGORIES = [
    "housing",
    "renovation",
    "food",
    "life",
    "mobility",
    "shopping",
    "fun",
    "holidays",
    "other",
]


def category_budget_total(limits: dict) -> float:
    """Monthly budget = sum of per-category spend limits (not commitments / meta)."""
    total = 0.0
    for key, val in limits.items():
        if key.startswith("_"):
            continue
        try:
            total += float(val)
        except (TypeError, ValueError):
            continue
    return total


def monthly_trends(statements_dir: str) -> dict:
    """
    Per-month spend by category across all available statements.

    Returns months (oldest→newest), category series, total spend, and income.
    Commitments are included so the UI can toggle them.
    """
    months = sorted(list_months(statements_dir))  # chronological
    commitment_keys = {k for k, _ in COMMITMENT_CATEGORIES}
    track = set(TREND_SPEND_CATEGORIES) | commitment_keys

    # month → category → spend
    grid: dict[str, dict[str, float]] = {m: {} for m in months}
    totals: dict[str, float] = {m: 0.0 for m in months}
    income: dict[str, float] = {m: 0.0 for m in months}
    compensation: dict[str, float] = {m: 0.0 for m in months}

    for month in months:
        txs, _ = load_statement_with_meta(statements_dir, month)
        for tx in txs:
            cat = tx.get("category")
            amt = tx.get("amount", 0.0)
            if cat == "income" and amt > 0:
                income[month] += amt
                continue
            if cat == "compensation" and amt > 0:
                compensation[month] += amt
                continue
            if cat not in track or amt == 0:
                continue
            # Debits increase spend; refunds/credits offset the same category.
            delta = -amt
            grid[month][cat] = grid[month].get(cat, 0.0) + delta
            if cat in TREND_SPEND_CATEGORIES:
                totals[month] += delta

    # Clamp nets at zero for display
    for month in months:
        for cat in list(grid[month]):
            grid[month][cat] = max(0.0, grid[month][cat])
        totals[month] = max(0.0, totals[month])

    # Stable category order: spend first, then commitments
    seen = set()
    categories: list[str] = []
    for cat in list(TREND_SPEND_CATEGORIES) + [k for k, _ in COMMITMENT_CATEGORIES]:
        if cat in seen:
            continue
        if any(grid[m].get(cat, 0) for m in months) or cat in TREND_SPEND_CATEGORIES:
            categories.append(cat)
            seen.add(cat)

    series = {
        cat: [round(grid[m].get(cat, 0.0), 2) for m in months]
        for cat in categories
    }
    series["_total"] = [round(totals[m], 2) for m in months]
    series["income"] = [round(income[m], 2) for m in months]
    series["compensation"] = [round(compensation[m], 2) for m in months]

    defaults = ["income"] + list(TREND_SPEND_CATEGORIES)

    return {
        "months": months,
        "categories": categories,
        "defaults": defaults,
        "commitments": [k for k, _ in COMMITMENT_CATEGORIES],
        "series": series,
    }


def _spend_by_alias(transactions: list[dict], categories: set[str]) -> dict[str, dict[str, float]]:
    """category → alias → net spend (debits minus refunds/credits)."""
    out: dict[str, dict[str, float]] = {c: {} for c in categories}
    for tx in transactions:
        cat = tx.get("category")
        amt = tx.get("amount", 0.0)
        if cat not in categories or amt == 0:
            continue
        alias = normalize_alias((tx.get("alias") or "").strip()) or "Unknown"
        out[cat][alias] = out[cat].get(alias, 0.0) - amt
    return out


def merchant_breakdown(
    statements_dir: str,
    month: str | None = None,
    categories: list[str] | None = None,
) -> dict:
    """
    Per-merchant spend for selected categories in one month, with MoM change.

    Shaped for a nested treemap: groups (categories) → stores (aliases).
    """
    cats = categories or ["food", "life"]
    cat_set = set(cats)
    months = list_months(statements_dir)
    if not months:
        return {
            "month": None,
            "previous_month": None,
            "categories": cats,
            "groups": [],
            "source": None,
        }

    key = None
    if month:
        key = month_key_from_name(month) or (
            month if re.fullmatch(r"\d{4}-\d{2}", month) else None
        )
    if key not in months:
        key = months[0]

    chronological = sorted(months)
    prev = None
    if key in chronological:
        idx = chronological.index(key)
        if idx > 0:
            prev = chronological[idx - 1]

    txs, source = load_statement_with_meta(statements_dir, key)
    cur = _spend_by_alias(txs, cat_set)
    prev_map: dict[str, dict[str, float]] = {c: {} for c in cats}
    if prev:
        prev_txs, _ = load_statement_with_meta(statements_dir, prev)
        prev_map = _spend_by_alias(prev_txs, cat_set)

    groups = []
    for cat in cats:
        items = []
        aliases = set(cur[cat]) | set(prev_map.get(cat, {}))
        for alias in aliases:
            amount = round(cur[cat].get(alias, 0.0), 2)
            prev_amount = round(prev_map.get(cat, {}).get(alias, 0.0), 2)
            if amount <= 0 and prev_amount <= 0:
                continue
            if prev_amount > 0:
                change_pct = round((amount - prev_amount) / prev_amount * 100, 1)
            elif amount > 0:
                change_pct = 100.0  # new this month
            else:
                change_pct = -100.0  # gone this month
            items.append({
                "alias": alias,
                "amount": amount,
                "previous": prev_amount,
                "change_pct": change_pct,
            })
        items.sort(key=lambda x: -x["amount"])
        # Drop zero-amount (only previous) from size, but keep for context? Treemap needs value>0
        visible = [i for i in items if i["amount"] > 0]
        groups.append({
            "name": cat,
            "total": round(sum(i["amount"] for i in visible), 2),
            "items": visible,
        })

    return {
        "month": key,
        "previous_month": prev,
        "categories": cats,
        "groups": groups,
        "source": source,
    }


def resolve_statement_path(statements_dir: str, month: str | None = None) -> str | None:
    """
    Pick a single CSV in statements_dir (legacy helper).
    Prefer an exact month key; otherwise most recently modified.
    """
    files = [
        os.path.join(statements_dir, name)
        for name in list_statement_files(statements_dir)
    ]
    if not files:
        return None

    if month:
        # Accept full filename or YYYY-MM
        key = month_key_from_name(month) or month
        matches = [
            f for f in files
            if key.lower() in os.path.basename(f).lower()
        ]
        if matches:
            files = matches

    return max(files, key=os.path.getmtime)


def files_for_month(statements_dir: str, month: str) -> list[str]:
    """Basenames for a calendar month: bank first, then visa, then others."""
    names = [
        name for name in list_statement_files(statements_dir)
        if month_key_from_name(name) == month
    ]

    def sort_key(name: str) -> tuple[int, str]:
        lower = name.lower()
        if "visa" in lower:
            return (1, name)
        if name.lower().endswith("_statement.csv") or name.lower().endswith("_statement.CSV".lower()):
            return (0, name)
        return (2, name)

    return sorted(names, key=sort_key)


def load_latest_statement(statements_dir: str, month: str | None = None) -> list[dict]:
    """Load merged transactions for a month (bank + visa)."""
    txs, _ = load_statement_with_meta(statements_dir, month)
    return txs


def load_statement_with_meta(statements_dir: str, month: str | None = None) -> tuple[list[dict], str | None]:
    """
    Load and classify all statement CSVs for one calendar month.

    Combines `YYYY-MM_statement.CSV` (bank) + `YYYY-MM_visa_statement.CSV`
    so credit-card purchases count as spend, while the bank-side card
    settlement (Abrechnung) is ignored via the transfers category.
    """
    months = list_months(statements_dir)
    if not months:
        return [], None

    key = None
    if month:
        key = month_key_from_name(month) or (month if re.fullmatch(r"\d{4}-\d{2}", month) else None)
    if key not in months:
        key = months[0]

    names = files_for_month(statements_dir, key)
    if not names:
        return [], None

    all_txs: list[dict] = []
    parts: list[str] = []
    for name in names:
        path = os.path.join(statements_dir, name)
        txs = classify_dataframe(load_csv(path))
        kind = "visa" if "visa" in name.lower() else "bank"
        if kind not in parts:
            parts.append(kind)
        for tx in txs:
            tx["source_file"] = name
            tx["source_kind"] = kind
        all_txs.extend(txs)

    label = f"{key} ({'+'.join(parts)})" if parts else key
    return all_txs, label
