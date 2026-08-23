#!/usr/bin/env python3
"""
Test Commerzbank FinTS connectivity.

Use this to verify HBCI activation and (optionally) DK product registration.

Environment variables:
  FINTS_BLZ          Bank code (default: 20080000 for Commerzbank FinTS)
  FINTS_USER         Online banking user ID (10 digits, leading zeros)
  FINTS_PIN          Online banking PIN
  FINTS_PRODUCT_ID   DK product registration ID (omit for unregistered test)

Examples:
  # Expect "Banking-Programm ist nicht registriert" (9078):
  FINTS_USER=0123456789 FINTS_PIN=secret python scripts/test_fints_connection.py

  # After DK registration:
  FINTS_PRODUCT_ID=YOUR-ID ... python scripts/test_fints_connection.py --fetch
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta

from fints.client import FinTS3PinTanClient
from fints.exceptions import FinTSError

COMMERZBANK_BLZ = "20080000"
COMMERZBANK_URL = "https://fints.commerzbank.de/fints"
UNREGISTERED_PRODUCT_ID = "BUDGET-DIY-NOT-REGISTERED"

KNOWN_ERRORS = {
    "3079": "Contact the banking software vendor (product not recognized).",
    "9078": "Banking program is NOT registered with Deutsche Kreditwirtschaft.",
    "9010": "Initialization failed — order not processed.",
    "9050": "Message contains errors.",
    "9800": "Dialog aborted.",
    "9931": "PIN wrong or authentication failed.",
    "3920": "TAN mechanism selection required (may need photoTAN on phone).",
    "9075": "Strong customer authentication (SCA) required — approve photoTAN.",
}


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"ERROR: Missing environment variable {name}", file=sys.stderr)
        print(
            "\nSet credentials locally (never commit them):\n"
            "  export FINTS_USER='0123456789'\n"
            "  export FINTS_PIN='your-pin'\n",
            file=sys.stderr,
        )
        sys.exit(2)
    return value


def print_result(ok: bool, headline: str, detail: str = "") -> None:
    icon = "✓" if ok else "✗"
    print(f"\n{'=' * 60}")
    print(f" {icon}  {headline}")
    if detail:
        print(f"     {detail}")
    print(f"{'=' * 60}\n")


def explain_error(exc: Exception) -> None:
    text = str(exc)
    print(f"Exception: {type(exc).__name__}")
    print(f"Message:   {text}\n")

    if isinstance(exc, FinTSError) and hasattr(exc, "args") and exc.args:
        for arg in exc.args:
            if isinstance(arg, dict):
                print("Bank error codes:")
                for code, msg in arg.items():
                    hint = KNOWN_ERRORS.get(str(code), "")
                    print(f"  [{code}] {msg}")
                    if hint:
                        print(f"         → {hint}")
                return

    for code, hint in KNOWN_ERRORS.items():
        if code in text or hint.split("—")[0].strip().lower() in text.lower():
            print(f"Likely bank code {code}: {hint}")


def run_test(fetch_transactions: bool, product_id: str | None, verbose: bool) -> int:
    user = require_env("FINTS_USER")
    pin = require_env("FINTS_PIN")
    blz = os.environ.get("FINTS_BLZ", COMMERZBANK_BLZ).strip()
    url = os.environ.get("FINTS_URL", COMMERZBANK_URL).strip()

    if product_id is None:
        product_id = UNREGISTERED_PRODUCT_ID
        mode = "unregistered (expect error 9078)"
    else:
        mode = f"registered product_id={product_id[:8]}…"

    print("Commerzbank FinTS connection test")
    print(f"  BLZ:        {blz}")
    print(f"  URL:        {url}")
    print(f"  User:       {user[:3]}***{user[-2:]}")
    print(f"  Mode:       {mode}")
    print()

    client = FinTS3PinTanClient(
        blz,
        user,
        pin,
        url,
        product_id=product_id,
    )

    try:
        with client:
            print("Step 1: Dialog opened (TLS + FinTS handshake)…")

            if client.init_tan_response:
                print(
                    "Step 2: Bank requests TAN for login.\n"
                    "       Approve photoTAN on your phone, then re-run with --tan support\n"
                    "       (or complete in StarMoney first to assign a system_id)."
                )
                print_result(
                    False,
                    "TAN required before we can continue",
                    "HBCI is likely active; registration status not yet tested.",
                )
                return 3

            info = client.get_information()
            bank_name = info.get("bank", {}).get("name", "unknown")
            accounts = info.get("accounts", [])
            print(f"Step 2: Connected to {bank_name}")
            print(f"Step 3: Found {len(accounts)} account(s)")

            for acc in accounts[:5]:
                iban = acc.get("iban", "?")
                product = acc.get("product_name", "")
                print(f"        - {iban}  ({product})")

            if fetch_transactions and accounts:
                iban = accounts[0]["iban"]
                start = date.today() - timedelta(days=30)
                end = date.today()
                print(f"\nStep 4: Fetching transactions for {iban} ({start} → {end})…")
                txs = client.get_transactions(accounts[0], start, end)
                print(f"        Retrieved {len(txs)} transaction(s)")
                for tx in txs[:3]:
                    print(f"        {tx.data.get('booking_date')}  {tx.data.get('amount')}  "
                          f"{tx.data.get('purpose', '')[:50]}")

            print_result(
                True,
                "FinTS connection successful",
                "HBCI active AND product registration accepted.",
            )
            return 0

    except FinTSError as exc:
        explain_error(exc)

        if product_id == UNREGISTERED_PRODUCT_ID:
            print_result(
                False,
                "Expected outcome for unregistered DIY client",
                "Register your app at https://www.fints.org/de/hersteller/produktregistrierung "
                "then set FINTS_PRODUCT_ID and run again.",
            )
            return 1

        print_result(False, "FinTS connection failed", "Check PIN, HBCI activation, or product ID.")
        return 1

    except Exception as exc:
        print(f"Unexpected error: {type(exc).__name__}: {exc}")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Commerzbank FinTS / HBCI connectivity")
    parser.add_argument(
        "--registered",
        action="store_true",
        help="Use FINTS_PRODUCT_ID env var (after DK registration)",
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Also fetch last 30 days of transactions (requires successful login)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    setup_logging(args.verbose)

    product_id = os.environ.get("FINTS_PRODUCT_ID") if args.registered else None
    if args.registered and not product_id:
        print("ERROR: --registered requires FINTS_PRODUCT_ID", file=sys.stderr)
        sys.exit(2)

    sys.exit(run_test(args.fetch, product_id, args.verbose))


if __name__ == "__main__":
    main()
