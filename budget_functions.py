import json
import re


# Payment processors whose booking text often embeds the real merchant.
_PROCESSOR_MARKERS = ("paypal", "klarna")


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def extract_payment_merchant(text: str) -> str | None:
    """
    Pull the shop name out of PayPal / Klarna SEPA remittance text.
    Commerzbank wraps lines mid-word, so matching is space-tolerant.
    """
    t = _normalize_spaces(text)
    # "Ihr Einkauf bei <merchant>" (spaces may split "Einkauf")
    m = re.search(
        r"Ihr\s+E\s*i\s*n\s*k\s*a\s*u\s*f\s+bei\s+(.+?)(?=\s+End-to-End|\s+Mandatsref|\s+Gläubiger|\s+PAYPAL\s+Mandats|$)",
        t,
        re.IGNORECASE,
    )
    if m:
        merchant = _normalize_spaces(m.group(1)).strip(" .,")
        if merchant and not merchant.lower().startswith("end-to-end"):
            return merchant
    m = re.search(
        r"Purchase\s+at\s+(.+?)(?=\s+End-to-End|\s+Mandatsref|\s+Gläubiger|$)",
        t,
        re.IGNORECASE,
    )
    if m:
        merchant = _normalize_spaces(m.group(1)).strip(" .,")
        if merchant:
            return merchant
    return None


def _is_processor_merchant(merchant: str) -> bool:
    """True when 'Ihr Einkauf bei' only repeats PayPal/Klarna itself."""
    compact = re.sub(r"[\s.]", "", merchant).lower()
    return compact.startswith("paypal") or compact.startswith("klarna")


def _keyword_in_text(keyword: str, text: str) -> bool:
    """Substring match; also ignore spaces (CSV line-wrap artefacts)."""
    k = keyword.lower().strip()
    t = text.lower()
    if not k:
        return False
    kc = k.replace(" ", "")
    # Short keys must be token-like — "OBI" must not hit "Mobilfunk".
    if len(kc) < 5:
        return (
            re.search(rf"(?<![a-zäöüß0-9]){re.escape(k)}(?![a-zäöüß0-9])", t)
            is not None
        )
    if k in t:
        return True
    if kc in t.replace(" ", ""):
        return True
    return False


class budget():
    def __init__(self):
        with open('budget_dict.json', 'r') as f:
            self.categories_dict = json.load(f)
        self.category_names = list(self.categories_dict.keys())

    def search_category(self, Buchungstext, skip_aliases: set[str] | None = None):
        skip = {a.lower() for a in (skip_aliases or set())}
        text = Buchungstext or ""
        for category_name in self.category_names:
            for value in self.categories_dict[category_name]:
                if value.lower() in skip:
                    continue
                if _keyword_in_text(value, text):
                    return category_name, value
        return False

    def classify_text(self, Buchungstext: str):
        """
        Classify a booking. For PayPal/Klarna, prefer the embedded merchant
        so spend lands in the real category instead of the processor dump.
        """
        text = Buchungstext or ""
        merchant = extract_payment_merchant(text)
        if merchant and not _is_processor_merchant(merchant):
            hit = self.search_category(merchant)
            if hit:
                return hit

        # Ignore processor keywords so other words in the remittance can match.
        hit = self.search_category(text, skip_aliases={"PayPal", "Klarna"})
        if hit:
            return hit

        lower = text.lower()
        if "paypal" in lower:
            return "other", "PayPal"
        if "klarna" in lower:
            return "other", "Klarna"
        return False

    def get_categories_sum(self):
        pass

    def save_categories_dict(self):
        with open('budget_dict.json', 'w', encoding='utf-8') as f:
            json.dump(self.categories_dict, f, indent=2, ensure_ascii=False)
            f.write('\n')

    def add_save_categories_dict(self, index, alias):
        self.categories_dict[self.category_names[index]].append(alias)
        self.save_categories_dict()
