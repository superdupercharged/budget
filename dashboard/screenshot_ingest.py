"""
CLI: ingest Commerzbank Buchungen screenshots via local OCR → SQLite.

Usage:
    python -m dashboard.screenshot_ingest path/to.png [--db data/screenshot_bookings.db]
    python -m dashboard.screenshot_ingest path/to/dir --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from dashboard.screenshot_db import DEFAULT_DB, ingest_screenshot
from dashboard.screenshot_ocr import parse_screenshot


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def _parse_ref_date(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise SystemExit(f"Invalid --date {raw!r}; use YYYY-MM-DD or DD.MM.YYYY")


def _collect_images(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.suffix.lower() in IMAGE_SUFFIXES:
                    out.append(child)
        elif path.is_file():
            out.append(path)
        else:
            raise SystemExit(f"Not found: {p}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest banking screenshots (local Tesseract OCR → SQLite)."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Image file(s) or directory of screenshots",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help=f"SQLite path (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--date",
        dest="ref_date",
        default=None,
        help="Reference day for Gestern/Heute/missing dates (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="OCR + parse only; do not write SQLite",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON summary",
    )
    args = parser.parse_args(argv)

    ref = _parse_ref_date(args.ref_date)
    images = _collect_images(args.paths)
    if not images:
        print("No images found.", file=sys.stderr)
        return 1

    summaries = []
    for img in images:
        if args.dry_run:
            ocr_text, bookings = parse_screenshot(img, reference_date=ref)
            rows = [
                {
                    "text": b.text,
                    "amount": b.amount,
                    "date": b.booking_date.isoformat(),
                    "date_raw": b.date_raw,
                    "status": "dry-run",
                }
                for b in bookings
            ]
            summary = {
                "file": str(img),
                "parsed": len(bookings),
                "inserted": 0,
                "skipped_dupes": 0,
                "bookings": rows,
            }
        else:
            result = ingest_screenshot(
                img, db_path=args.db, reference_date=ref
            )
            summary = {
                "file": str(img),
                "screenshot_id": result["screenshot_id"],
                "parsed": result["parsed"],
                "inserted": result["inserted"],
                "skipped_dupes": result["skipped_dupes"],
                "bookings": result["bookings"],
            }
        summaries.append(summary)

        if not args.json:
            print(f"\n=== {img.name} ===")
            print(
                f"parsed={summary['parsed']}  "
                f"inserted={summary['inserted']}  "
                f"dupes={summary['skipped_dupes']}"
            )
            for b in summary["bookings"]:
                raw = f" ({b['date_raw']})" if b.get("date_raw") else ""
                cat = b.get("category") or ""
                print(
                    f"  {b['date']}{raw:12}  {b['amount']:>8.2f}  "
                    f"{b['text'][:50]:50}  {cat}  [{b.get('status', '')}]"
                )

    if args.json:
        print(json.dumps(summaries, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
