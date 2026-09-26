"""
Local OCR + layout parse for Commerzbank “Buchungen” screenshots.

Uses Tesseract (deu+eng) via pytesseract + Pillow. No cloud APIs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from PIL import Image
import pytesseract


_IGNORE_EXACT = {
    "buchungen",
    "daueraufträge",
    "dauerauftrage",
    "details",
    "vertragsübersicht",
    "vertragsuebersicht",
    "entdecken",
}

_MONTH_NAMES_DE = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "maerz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}

_AMOUNT_RE = re.compile(
    r"^([+#\-–—−\"“”'‚`]?)(\d{1,3}(?:\.\d{3})*,\d{2})$"
)
_DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{2,4})$")
_MONTH_HEADER_RE = re.compile(
    r"^(januar|februar|märz|maerz|april|mai|juni|juli|august|"
    r"september|oktober|november|dezember)\s+(\d{4})$",
    re.IGNORECASE,
)


@dataclass
class ParsedBooking:
    text: str
    amount: float
    booking_date: date
    date_raw: str | None = None


@dataclass
class _Token:
    text: str
    left: int
    top: int
    width: int
    height: int
    conf: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def cy(self) -> int:
        return self.top + self.height // 2


def ocr_image(
    path: str | Path, lang: str = "deu+eng"
) -> tuple[str, list[_Token], int]:
    """Run Tesseract; return (full text, word tokens, image width used)."""
    img = Image.open(path)
    if max(img.size) < 1600:
        scale = 1600 / max(img.size)
        img = img.resize(
            (int(img.width * scale), int(img.height * scale)),
            Image.Resampling.LANCZOS,
        )

    plain = pytesseract.image_to_string(img, lang=lang)
    data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
    tokens: list[_Token] = []
    for i in range(len(data["text"])):
        t = (data["text"][i] or "").strip()
        if not t:
            continue
        try:
            conf = int(float(data["conf"][i]))
        except (TypeError, ValueError):
            conf = -1
        if conf < 0:
            continue
        tokens.append(
            _Token(
                text=t,
                left=int(data["left"][i]),
                top=int(data["top"][i]),
                width=int(data["width"][i]),
                height=int(data["height"][i]),
                conf=conf,
            )
        )
    return plain, tokens, img.width


def parse_german_amount(raw: str) -> float | None:
    """
    Parse German money like '-1.234,56', '+51,93'.

    OCR quirks: '#' often stands in for '+'; quotes for '-'.
    Unsigned amounts default to debit (negative).
    """
    s = raw.strip().replace(" ", "")
    s = re.sub(r"[^\d+#\-–—−\"“”'‚`.,]+$", "", s)
    m = _AMOUNT_RE.match(s)
    if not m:
        return None
    sign_ch, num = m.group(1), m.group(2)
    value = float(num.replace(".", "").replace(",", "."))
    if sign_ch in ("+", "#"):
        return value
    if sign_ch in ("-", "–", "—", "−", '"', "“", "”", "'", "‚", "`"):
        return -value
    return -value


def _parse_absolute_date(token: str, year_hint: int | None) -> date | None:
    m = _DATE_RE.match(token.strip())
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    if y < 1900 and year_hint:
        y = year_hint
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def resolve_booking_date(
    raw: str | None,
    *,
    reference: date,
    year_hint: int | None = None,
) -> tuple[date, str | None]:
    """Missing → reference; Gestern/Heute relative to reference."""
    if not raw or not raw.strip():
        return reference, None
    t = raw.strip()
    low = t.lower()
    if low == "heute":
        return reference, t
    if low == "gestern":
        return reference - timedelta(days=1), t
    abs_d = _parse_absolute_date(t, year_hint)
    if abs_d:
        return abs_d, t
    return reference, t


def _detect_year(tokens: list[_Token]) -> int | None:
    left = [t for t in tokens if t.left < 500]
    left.sort(key=lambda t: (t.top, t.left))
    lines: list[tuple[int, str]] = []
    for t in left:
        if lines and abs(t.top - lines[-1][0]) < 20:
            lines[-1] = (lines[-1][0], lines[-1][1] + " " + t.text)
        else:
            lines.append((t.top, t.text))
    for _, line in lines:
        m = _MONTH_HEADER_RE.match(line.strip())
        if m:
            return int(m.group(2))
    return None


def _is_amount_token(text: str) -> bool:
    return parse_german_amount(text) is not None


def _is_date_token(text: str) -> bool:
    low = text.strip().lower()
    if low in ("gestern", "heute"):
        return True
    return _DATE_RE.match(text.strip()) is not None


def _is_noise(text: str, *, top: int = 0) -> bool:
    low = text.strip().lower().rstrip(".,:;")
    if low in _IGNORE_EXACT:
        return True
    # Status-bar / nav glyph junk — only near the top of the frame
    if low in ("©", "*", "*)", "nam", "a®", "2@", "7"):
        return True
    if low == "of" and top < 120:
        return True
    if re.fullmatch(r"\d{1,2}:\d{2}", low):
        return True
    return False


def parse_bookings_from_tokens(
    tokens: list[_Token],
    *,
    reference_date: date | None = None,
    image_width: int | None = None,
) -> list[ParsedBooking]:
    """Cluster OCR tokens into booking rows using Y layout (top → bottom)."""
    if not tokens:
        return []

    ref = reference_date or date.today()
    year_hint = _detect_year(tokens) or ref.year

    max_right = max(t.right for t in tokens)
    width = image_width or max_right
    amount_x_min = int(width * 0.72)

    amounts: list[_Token] = []
    left_tokens: list[_Token] = []
    for t in tokens:
        if _is_noise(t.text, top=t.top):
            continue
        if t.left >= amount_x_min and _is_amount_token(t.text):
            amounts.append(t)
            continue
        if t.left >= amount_x_min:
            continue
        if _MONTH_HEADER_RE.match(t.text.strip()) or t.text.strip().lower() in _MONTH_NAMES_DE:
            continue
        if re.fullmatch(r"\d{4}", t.text.strip()):
            continue
        left_tokens.append(t)

    left_tokens.sort(key=lambda t: (t.top, t.left))
    bands: list[dict] = []
    for t in left_tokens:
        if _is_date_token(t.text):
            if bands and abs(t.top - bands[-1]["top"]) < 120:
                bands[-1]["date"] = t.text
            else:
                bands.append({"top": t.top, "parts": [], "date": t.text})
            continue
        if t.text.strip().lower() in ("vertragsübersicht", "entdecken", "©"):
            continue
        if bands and abs(t.top - bands[-1]["top"]) < 35:
            bands[-1]["parts"].append((t.left, t.text))
            bands[-1]["top"] = min(bands[-1]["top"], t.top)
        else:
            bands.append({"top": t.top, "parts": [(t.left, t.text)], "date": None})

    bookings: list[ParsedBooking] = []
    used_bands: set[int] = set()
    amounts.sort(key=lambda t: t.cy)

    for amt_tok in amounts:
        amount = parse_german_amount(amt_tok.text)
        if amount is None:
            continue
        best_i = None
        best_dist = 10**9
        for i, band in enumerate(bands):
            if i in used_bands or not band["parts"]:
                continue
            dist = abs(band["top"] - amt_tok.top)
            if dist < best_dist and dist < 80:
                best_dist = dist
                best_i = i
        if best_i is None:
            continue
        used_bands.add(best_i)
        band = bands[best_i]
        parts_sorted = [txt for _, txt in sorted(band["parts"], key=lambda p: p[0])]
        merchant = re.sub(r"\s+", " ", " ".join(parts_sorted)).strip(" ,")
        if not merchant or len(merchant) < 2:
            continue
        if merchant.lower().startswith("vertrags"):
            continue
        bdate, raw = resolve_booking_date(
            band.get("date"),
            reference=ref,
            year_hint=year_hint,
        )
        bookings.append(
            ParsedBooking(
                text=merchant,
                amount=amount,
                booking_date=bdate,
                date_raw=raw,
            )
        )
    return bookings


def parse_screenshot(
    path: str | Path,
    *,
    reference_date: date | None = None,
) -> tuple[str, list[ParsedBooking]]:
    """OCR a screenshot and return (ocr_text, parsed bookings)."""
    plain, tokens, width = ocr_image(path)
    bookings = parse_bookings_from_tokens(
        tokens,
        reference_date=reference_date,
        image_width=width,
    )
    return plain, bookings


def normalize_merchant(text: str) -> str:
    """Uppercase, collapse whitespace, lightly strip trailing country marker."""
    t = re.sub(r"\s+", " ", (text or "").strip()).upper()
    t = re.sub(r",?\s+DE$", "", t)
    return t


def amount_to_cents(amount: float) -> int:
    return int(round(amount * 100))


def fingerprint(text: str, booking_date: date, amount_cents: int) -> str:
    """Stable dedupe key: normalized merchant + date + amount_cents."""
    return f"{normalize_merchant(text)}|{booking_date.isoformat()}|{amount_cents}"
