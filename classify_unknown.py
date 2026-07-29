#!/usr/bin/env python3
"""
Scan statement CSVs, auto-classify obvious unclassified bookings, and
optionally prompt for the rest.

Usage:
  python classify_unknown.py              # stats + dry-run auto suggestions
  python classify_unknown.py --apply      # write auto-rules into budget_dict.json
  python classify_unknown.py --ask        # after auto, interactively classify leftovers
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboard"))

import budget_functions as bf
from ingest import classify_dataframe, load_csv

STATEMENTS_DIR = ROOT / "statements"

# Distinctive (alias_keyword, category) pairs for obvious merchants.
# Prefer longer aliases; avoid tiny substrings like "RAN".
AUTO_RULES: list[tuple[str, str]] = [
    # food
    ("BRENNERS", "food"),
    ("Bäckerei Brenner", "food"),
    ("BAECKEREI REISSLER", "food"),
    ("Bäckerei Reißler", "food"),
    ("Stadtcafe Hampp", "food"),
    ("GEORG JOS. KAES", "food"),
    ("HEIss UND KALT", "food"),
    ("HEISS UND KALT", "food"),
    ("Norma,", "food"),
    ("V-MARKT", "food"),
    ("PLATZMETZGER", "food"),
    ("Freeway Diner", "food"),
    ("Ditsch", "food"),
    ("Rothaler Pitac", "food"),
    ("MPREIS", "food"),
    ("FAMILA", "food"),
    ("Danilas Grill", "food"),
    ("Toni  Johns", "food"),
    ("Johns/Molkereiweg", "food"),
    ("MCDONALD S", "food"),
    ("JOESEPPS BRAUHAUS", "food"),
    ("Barrel House", "food"),
    ("OLD WILD WEST", "food"),
    ("LA CREMERIA", "food"),
    ("GELATERIA", "food"),
    ("Aichinger Gastro", "food"),
    # shopping
    ("Hornbach", "shopping"),
    ("HORNBACH", "shopping"),
    ("KiK Fil", "shopping"),
    ("KiK ", "shopping"),
    ("H&M", "shopping"),
    ("HM.COM", "shopping"),
    ("HM IT", "shopping"),
    ("Temu.com", "shopping"),
    ("Temu", "shopping"),
    ("AMZN", "shopping"),
    ("AMAZON", "shopping"),
    ("Amazon", "shopping"),
    ("Prime Video", "shopping"),
    ("C&A", "shopping"),
    ("NEW YORKER", "shopping"),
    ("SOSTRENE GRENE", "shopping"),
    ("JYSK", "shopping"),
    ("NANU NANA", "shopping"),
    ("LIMANGO", "shopping"),
    ("Takko", "shopping"),
    ("Ernsting's family", "shopping"),
    ("Vero Moda", "shopping"),
    ("MEDIA MARKT", "shopping"),
    ("BabyOne", "shopping"),
    ("Dehner", "shopping"),
    ("DEHNER", "shopping"),
    ("MOEBEL INHOFER", "shopping"),
    ("TIGER STORE", "shopping"),
    ("eBay O", "shopping"),
    ("Joybuy", "shopping"),
    ("Douglas", "shopping"),
    ("MGP*Vinted", "shopping"),
    ("BOESNER", "shopping"),
    # fun
    ("LEGOLAND", "fun"),
    ("LEGO ", "fun"),
    ("DIETRICH KINO", "fun"),
    ("Donaubad", "fun"),
    ("Kölle Zoo", "fun"),
    ("Netflix", "fun"),
    ("NETFLIX", "fun"),
    ("APPLE.COM", "fun"),
    ("CURSOR,", "fun"),
    ("Freizeitbad Nautilla", "fun"),
    ("Kikimondo", "fun"),
    ("Hallenfreibad", "fun"),
    ("HALLENFREIBAD", "fun"),
    ("STAEDT FREIBAD", "fun"),
    ("Freibad Kiosk", "fun"),
    ("Musikschule", "fun"),
    ("JUST PLAY", "fun"),
    ("Museumsshop", "fun"),
    ("N.ULM-GLACIS", "fun"),
    ("SV Pfaffenhofen", "fun"),
    ("Cafe Extrablatt", "fun"),
    ("Stadtgefl", "fun"),
    ("ANNO 1460", "fun"),
    ("SumUp *Maccchia", "fun"),
    ("SumUp *Donaugold", "fun"),
    # mobility
    ("Tesla Germany", "mobility"),
    ("Tesla_DE", "mobility"),
    ("PARKSTER", "mobility"),
    ("Autopay Mobility", "mobility"),
    ("TOTAL SERVICE STATION", "mobility"),
    ("SIXT GMBH", "mobility"),
    ("Road B.V.", "mobility"),
    ("Tiefgarage", "mobility"),
    ("Mnchberger Autohof", "mobility"),
    ("CASELLO AUTO", "mobility"),
    # housing / utilities
    ("MONTANA", "housing"),
    ("Naturwerke", "housing"),
    ("AZV ", "housing"),
    ("Abfallwirtschaft", "housing"),
    ("Deutsche Glasfaser", "housing"),
    ("MARKT PFAFFENHOFEN", "housing"),
    ("RAUHER-BERG", "housing"),
    ("POLLUX GRUNDST", "housing"),
    # life
    ("Kindergarten", "life"),
    ("DHL*", "life"),
    ("Universitaetsklinikum", "life"),
    ("4 you Friseure", "life"),
    ("KRYODAT", "life"),
    ("Fotoservice", "life"),
    ("ITZEHOER", "life"),
    ("Deutsche Post", "life"),
    ("Holz Waschparadies", "life"),
    # holidays
    ("PREMIER INN", "holidays"),
    ("CAMPING PARK", "holidays"),
    ("Condor onboard", "holidays"),
    ("Alt Montreal", "holidays"),
    ("MAISONTURENNE", "holidays"),
    ("SCHLOSS ZIETHEN", "holidays"),
    ("LA CHOUAPE", "holidays"),
    ("AGOS MARIO", "holidays"),
    ("GLAM SRL", "holidays"),
    ("CANDY LISA", "holidays"),
    ("GEORGE FISH", "holidays"),
    ("WHITE 10 SRL", "holidays"),
    ("CHENG SUIAN", "holidays"),
    ("TROPICAL/LUNGOLAGO", "holidays"),
    ("FREETIME SRLS", "holidays"),
    ("CAMPAGNARI STEFANO", "holidays"),
    ("BRENNERO/VIA", "holidays"),
    ("AFFI/LOC.", "holidays"),
    # transfers / commitments
    ("SANTANDER", "car_loan"),
    ("OPENBANK", "car_loan"),
    ("Darl.-Le", "house_loan"),
    ("61382287", "house_loan"),
    ("BAUSPAREN", "wuestenrot"),
    ("BAUSPARKREDIT", "wuestenrot"),
    ("WBAGDE61", "wuestenrot"),
    ("Auffüllen", "savings"),
    ("EFG NEU-ULM", "tithe"),
    ("SPENDE", "tithe"),
    ("MOSAIK", "tithe"),
    ("NEBENKOSTEN", "housing"),
    ("NEBENK", "housing"),
    # income
    ("Bundeskasse", "income"),
    ("LANDESOBERKASSE", "income"),
    ("Landesoberkasse", "income"),
    # other / fees
    ("Entgelt Auslandseinsatz", "other"),
    ("Jahresentgelt Ausgabe Karte", "other"),
    ("Finanzamt", "other"),
]


def list_statement_paths(statements_dir: Path = STATEMENTS_DIR) -> list[Path]:
    """Non-recursive CSV paths in statements/ (ignore archive/)."""
    paths = [
        Path(p)
        for p in glob.glob(str(statements_dir / "*.CSV"))
        + glob.glob(str(statements_dir / "*.csv"))
    ]
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


def load_all_transactions(statements_dir: Path = STATEMENTS_DIR) -> list[dict]:
    txs: list[dict] = []
    for path in list_statement_paths(statements_dir):
        df = load_csv(str(path))
        txs.extend(classify_dataframe(df))
    return txs


def normalize_merchant_key(text: str) -> str:
    """Strip card noise, dates, KFN…, autorisiert am… for grouping."""
    t = text
    t = re.sub(r"KFN\s*\d+", " ", t, flags=re.I)
    t = re.sub(r"autorisiert am\s+\d{2}\.\d{2}\.\d{4}", " ", t, flags=re.I)
    t = re.sub(r"Karte Nr\.\s*[\dX\s]+", " ", t, flags=re.I)
    t = re.sub(r"\d{2}\.\d{2}\.\d{4}", " ", t)
    t = re.sub(r"\d{4}-\d{2}-\d{2}T[\d:]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:60].strip()


def suggest_alias(key: str) -> str:
    """Suggest a distinctive alias from a normalized merchant key."""
    # Prefer merchant name before first comma / slash / city marker
    chunk = re.split(r"[,/]", key, maxsplit=1)[0].strip()
    chunk = re.sub(r"\s+DE\s*$", "", chunk, flags=re.I).strip()
    if len(chunk) >= 6:
        return chunk[:40]
    return key[:30].strip()


def group_unclassified(transactions: list[dict]) -> dict[str, dict]:
    groups: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "total": 0.0, "samples": []}
    )
    for tx in transactions:
        if tx["category"] != "unclassified":
            continue
        key = normalize_merchant_key(tx["text"])
        g = groups[key]
        g["count"] += 1
        g["total"] += tx["amount"]
        if len(g["samples"]) < 2:
            g["samples"].append(tx["text"])
    return groups


def missing_auto_rules(budget: bf.budget) -> list[tuple[str, str]]:
    """Return AUTO_RULES aliases not yet present in budget_dict."""
    existing = {
        (alias.lower(), cat)
        for cat, aliases in budget.categories_dict.items()
        for alias in aliases
    }
    missing = []
    for alias, cat in AUTO_RULES:
        if cat not in budget.categories_dict:
            print(f"WARNING: unknown category {cat!r} for alias {alias!r}", file=sys.stderr)
            continue
        if (alias.lower(), cat) not in existing and not any(
            a.lower() == alias.lower() for a in budget.categories_dict[cat]
        ):
            # Also skip if alias already exists under any category
            if any(
                a.lower() == alias.lower()
                for aliases in budget.categories_dict.values()
                for a in aliases
            ):
                continue
            missing.append((alias, cat))
    return missing


def apply_auto_rules(budget: bf.budget, dry_run: bool = True) -> list[tuple[str, str]]:
    missing = missing_auto_rules(budget)
    if not missing:
        print("No new auto-rules to add.")
        return []

    print(f"{'Would add' if dry_run else 'Adding'} {len(missing)} auto-rule alias(es):")
    by_cat: dict[str, list[str]] = defaultdict(list)
    for alias, cat in missing:
        by_cat[cat].append(alias)
    for cat in sorted(by_cat):
        print(f"  [{cat}] {', '.join(by_cat[cat])}")

    if not dry_run:
        for alias, cat in missing:
            budget.categories_dict[cat].append(alias)
        budget.save_categories_dict()
        # Refresh category_names / search order
        budget.category_names = list(budget.categories_dict.keys())
        print(f"Saved {len(missing)} alias(es) to budget_dict.json")
    return missing


def count_unclassified(transactions: list[dict]) -> tuple[int, int]:
    groups = group_unclassified(transactions)
    return len([t for t in transactions if t["category"] == "unclassified"]), len(groups)


def interactive_ask(budget: bf.budget) -> None:
    """Prompt for remaining unique unclassified groups (count desc).

    An "alias" is just a match keyword stored in budget_dict.json: if that
    string appears in a booking text, the booking gets this category.
    You only pick a category — the match text is chosen automatically.
    Override with:  3/Hornbach
    """
    transactions = load_all_transactions()
    groups = group_unclassified(transactions)
    ordered = sorted(groups.items(), key=lambda x: -x[1]["count"])
    cats = budget.category_names
    indexed = [f"({i}){c}" for i, c in enumerate(cats)]

    print(f"\n{len(ordered)} unique unclassified group(s) remaining.")
    print("Pick a category number — match keyword is auto-chosen from the merchant name.")
    print("  3           → food, match auto")
    print("  3/Hornbach  → food, custom match 'Hornbach'")
    print("  skip / q")
    print("Categories:", ", ".join(indexed))

    remaining = list(ordered)
    i = 0
    while i < len(remaining):
        key, g = remaining[i]
        sample = g["samples"][0] if g["samples"] else key
        match = suggest_alias(key)
        print(
            f"\n--- [{i + 1}/{len(remaining)}] ×{g['count']}  "
            f"{g['total']:.2f} EUR ---"
        )
        print(f"  {sample[:120]}")
        print(f"  match → {match!r}")

        choice = input(f"Category {indexed} (or N/match, skip, q): ").strip()
        if choice.lower() == "q":
            print("Stopped.")
            break
        if choice.lower() == "skip" or choice == "":
            i += 1
            continue

        custom = None
        if "/" in choice:
            left, custom = choice.split("/", 1)
            choice = left.strip()
            custom = custom.strip() or None

        try:
            cat_index = int(choice)
        except ValueError:
            print("Invalid input.")
            continue
        if not 0 <= cat_index < len(cats):
            print(f"Index must be 0…{len(cats) - 1}")
            continue

        alias = custom or match
        if len(alias) < 3:
            print("Match text too short; skipped.")
            i += 1
            continue

        budget.add_save_categories_dict(cat_index, alias)
        print(f"✓ {cats[cat_index]}  — bookings containing {alias!r}")

        # Drop later groups that this match already covers
        removed = 0
        new_remaining = remaining[: i + 1]
        for j in range(i + 1, len(remaining)):
            k2, g2 = remaining[j]
            hay = (k2 + " " + " ".join(g2["samples"])).lower()
            if alias.lower() in hay:
                removed += 1
            else:
                new_remaining.append(remaining[j])
        remaining = new_remaining
        if removed:
            print(f"  (also covers {removed} similar group(s))")
        i += 1

    txs = load_all_transactions()
    n_tx, n_grp = count_unclassified(txs)
    print(f"\nDone. Remaining unclassified: {n_tx} txs / {n_grp} unique groups.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-classify unclassified statement bookings.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write missing AUTO_RULES aliases into budget_dict.json",
    )
    parser.add_argument(
        "--ask",
        action="store_true",
        help="After auto-rules, interactively classify remaining unique groups",
    )
    args = parser.parse_args()

    os.chdir(ROOT)
    budget = bf.budget()

    print("Scanning statements/*.CSV and *.csv …")
    before_txs = load_all_transactions()
    before_n, before_g = count_unclassified(before_txs)
    print(f"Before: {before_n} unclassified txs / {before_g} unique groups "
          f"(of {len(before_txs)} total)")

    dry_run = not args.apply and not args.ask
    if dry_run:
        apply_auto_rules(budget, dry_run=True)
        # Simulate impact without writing
        for alias, cat in missing_auto_rules(budget):
            budget.categories_dict[cat].append(alias)
        budget.category_names = list(budget.categories_dict.keys())
        # Re-classify in memory by temporarily saving? Better: search with mutated dict
        sim_n = 0
        sim_groups: set[str] = set()
        for tx in before_txs:
            if tx["category"] != "unclassified":
                continue
            result = budget.search_category(tx["text"])
            if not result:
                sim_n += 1
                sim_groups.add(normalize_merchant_key(tx["text"]))
        print(
            f"After auto-rules (dry-run): ~{sim_n} unclassified txs / "
            f"{len(sim_groups)} unique groups"
        )
        print("Re-run with --apply to write rules, or --ask to classify interactively.")
        return

    if args.apply or args.ask:
        apply_auto_rules(budget, dry_run=False)
        after_txs = load_all_transactions()
        after_n, after_g = count_unclassified(after_txs)
        print(
            f"After auto-apply: {after_n} unclassified txs / {after_g} unique groups "
            f"(classified {before_n - after_n} txs, {before_g - after_g} groups)"
        )

    if args.ask:
        interactive_ask(budget)


if __name__ == "__main__":
    main()
