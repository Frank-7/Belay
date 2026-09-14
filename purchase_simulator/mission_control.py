"""General-purpose local payment-mission engine for the investor MVP.

The engine accepts plain-language payment requests, extracts a draft plan,
requires the user to supply or review every money-moving field, and then runs a
durable simulated USDC-to-USD payment. It deliberately makes no external model,
wallet, blockchain, bank, merchant, tax, or insurance call.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from purchase_simulator.engine import DemoError

SCHEMA_VERSION = "belay.mission.v0.1"
USDC_SCALE = 1_000_000
STARTING_USDC_UNITS = 25_000 * USDC_SCALE
MAX_REQUEST_LENGTH = 1_200
MAX_PAYMENT_USD_CENTS = 2_500_000
MONEY_NUMBER_PATTERN = r"[0-9][0-9,]*(?:\.[0-9]+)?"

CATEGORIES = {
    "tax": {
        "label": "Tax payment",
        "keywords": ("tax", "taxes", "irs", "revenue service", "revenue department"),
        "reference_label": "Tax period or notice number",
        "reference_required": True,
        "confirmation": "Tax payment sent",
        "domain_confirmation": "Tax account posting",
        "scope": "Belay records the simulated USD payout. The tax authority must separately confirm account posting. This does not calculate tax or file a return.",
    },
    "insurance": {
        "label": "Insurance premium",
        "keywords": ("insurance", "premium", "policy"),
        "reference_label": "Policy number",
        "reference_required": True,
        "confirmation": "Premium payment sent",
        "domain_confirmation": "Premium applied to policy",
        "scope": "Belay records the simulated USD payout. The insurer must separately confirm that it was applied to the policy. This does not determine coverage or a claim.",
    },
    "invoice": {
        "label": "Invoice",
        "keywords": ("invoice", "invoices", "supplier", "vendor"),
        "reference_label": "Invoice number",
        "reference_required": True,
        "confirmation": "Invoice payment sent",
        "domain_confirmation": "Invoice balance updated",
        "scope": "Belay records the simulated USD payout. The vendor must separately confirm the invoice balance. This does not prove delivery of work or goods.",
    },
    "bill": {
        "label": "Bill",
        "keywords": ("bill", "bills", "utility", "electric", "water", "phone", "rent", "tuition"),
        "reference_label": "Account or bill number",
        "reference_required": True,
        "confirmation": "Bill payment sent",
        "domain_confirmation": "Biller account updated",
        "scope": "Belay records the simulated USD payout. The biller must separately confirm the account balance and service status.",
    },
    "ticket": {
        "label": "Tickets or travel",
        "keywords": ("ticket", "tickets", "concert", "flight", "hotel", "train"),
        "reference_label": "Order note",
        "reference_required": False,
        "confirmation": "Merchant payment sent",
        "domain_confirmation": "Tickets or booking issued",
        "scope": "Belay records the simulated USD payout. The merchant must separately confirm ticket issuance or travel fulfillment.",
    },
    "subscription": {
        "label": "Subscription",
        "keywords": ("subscription", "subscriptions", "subscribe", "membership", "monthly", "annual", "yearly"),
        "reference_label": "Account or plan",
        "reference_required": False,
        "confirmation": "First payment sent",
        "domain_confirmation": "Subscription activated",
        "scope": "Belay records one simulated USD payout. The provider must separately confirm activation. Future charges require a separate recurring mandate.",
    },
    "transfer": {
        "label": "Transfer",
        "keywords": ("send", "transfer", "transfers", "reimburse", "repay"),
        "reference_label": "Payment note",
        "reference_required": False,
        "confirmation": "Transfer sent",
        "domain_confirmation": "Funds available to beneficiary",
        "scope": "Belay records the simulated USD payout under the reviewed identity. Beneficiary account availability remains external.",
    },
    "purchase": {
        "label": "Purchase",
        "keywords": ("buy", "purchase", "order", "pay"),
        "reference_label": "Order or payment note",
        "reference_required": False,
        "confirmation": "Payment sent",
        "domain_confirmation": "Product or service delivered",
        "scope": "Belay records the simulated USD payout. Product or service delivery remains a separate outcome.",
    },
}

EXAMPLES = (
    "Pay my $168 GEICO premium for policy AUTO-2048 by Friday",
    "Pay invoice INV-1042 for $1,250 to Acme Design by September 30",
    "Pay $240 in federal estimated tax to the IRS for Q3-2026 by October 15",
    "Buy two concert tickets for $200 from Northstar Tickets",
)

KNOWN_PAYEES = (
    ("internal revenue service", "Internal Revenue Service", {"tax"}),
    ("irs", "Internal Revenue Service", {"tax"}),
    ("geico", "GEICO", {"insurance"}),
    ("state farm", "State Farm", {"insurance"}),
    ("progressive", "Progressive", {"insurance"}),
    ("allstate", "Allstate", {"insurance"}),
    ("northstar tickets", "Northstar Tickets", {"ticket"}),
)

FIELD_LABELS = {
    "payee": "Who should receive the payment?",
    "amount_usd_cents": "What exact amount should be paid?",
    "reference": "What account, policy, invoice, or tax reference should be attached?",
}

SENSITIVE_KEY_NAMES = (
    "api_key",
    "bank_account",
    "card",
    "credential",
    "password",
    "private_key",
    "routing",
    "secret",
    "security_code",
    "ssn",
    "token",
)

SENSITIVE_PATTERNS = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:[A-Z0-9][A-Z0-9 -]{0,39} )?PRIVATE KEY-----.*?"
            r"(?:-----END (?:[A-Z0-9][A-Z0-9 -]{0,39} )?PRIVATE KEY-----|\Z)",
            re.IGNORECASE | re.DOTALL,
        ),
        lambda _match: "[REDACTED PRIVATE KEY]",
    ),
    (
        "api_key",
        re.compile(
            r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9_-]{8,}\b",
            re.IGNORECASE,
        ),
        lambda _match: "[REDACTED]",
    ),
    (
        "credential",
        re.compile(
            r"\b(?P<label>api[ _-]?key|access[ _-]?token|private[ _-]?key|"
            r"bearer|password|secret)"
            r"(?:\s*[=:]\s*|\s+is\s+|\s+)"
            r'(?:"[^"\r\n]*"|\x27[^\x27\r\n]*\x27|[^\s,;]+)',
            re.IGNORECASE,
        ),
        lambda match: match.group("label") + " [REDACTED]",
    ),
    (
        "ssn",
        re.compile(r"(?<!\d)(\d{3})[- ]?(\d{2})[- ]?(\d{4})(?!\d)"),
        lambda match: "***-**-" + match.group(3),
    ),
    (
        "payment_card",
        re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"),
        lambda match: "card ending " + re.sub(r"\D", "", match.group(0))[-4:],
    ),
    (
        "bank_account",
        re.compile(
            r"\b((?:bank\s+)?account|routing)(\s+(?:number|no\.?|id))?"
            r"\s*(?:is|=|:|#|-)?\s*(\d{5,17})\b",
            re.IGNORECASE,
        ),
        lambda match: f"{match.group(1)} ending {match.group(3)[-4:]}",
    ),
)


@contextmanager
def _connect(path: Path):
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def _encode(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value) -> str:
    return "sha256:" + hashlib.sha256(_encode(value).encode("utf-8")).hexdigest()


def _clean(value: str, limit: int) -> str:
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    return re.sub(r"\s+", " ", value.strip())[:limit]


def _redact_sensitive_text(value: str) -> tuple[str, set[str]]:
    """Remove recognized credentials and identifiers before persistence.

    A private-key opening marker consumes through its closing marker or the end
    of the input. A partially pasted key must not become safe merely because
    its closing marker is missing. Redact before truncating editable fields.
    """

    redacted = value
    categories = set()
    for category, pattern, replacement in SENSITIVE_PATTERNS:
        redacted, count = pattern.subn(replacement, redacted)
        if count:
            categories.add(category)
    return redacted, categories


def _mask_reference(value: str) -> str:
    value = _clean(value, 80)
    if not value:
        return ""
    compact = re.sub(r"\s+", "", value)
    if len(compact) <= 4:
        return "••••"
    return "••••" + compact[-4:]


def _redact_for_audit(value, key: str = ""):
    """Create an audit-safe copy without mutating the user-visible plan."""

    normalized_key = key.lower()
    if any(name in normalized_key for name in SENSITIVE_KEY_NAMES):
        return "[REDACTED]" if value not in (None, "") else value
    if normalized_key == "reference" and isinstance(value, str):
        return _mask_reference(value)
    if isinstance(value, str):
        return _redact_sensitive_text(value)[0]
    if isinstance(value, dict):
        return {child_key: _redact_for_audit(child, child_key) for child_key, child in value.items()}
    if isinstance(value, list):
        return [_redact_for_audit(child, key) for child in value]
    return value


def _money_to_cents(number: str, suffix: str | None = None) -> int | None:
    # A comma immediately after a whole amount is normal prose punctuation.
    # Internal commas still have to use valid thousands grouping.
    number = number[:-1] if number.endswith(",") else number
    integer, dot, fraction = number.partition(".")
    if "," in integer and not re.fullmatch(r"[0-9]{1,3}(?:,[0-9]{3})+", integer):
        raise DemoError("Use a valid dollar amount, such as $1,250.00")
    if dot and not 1 <= len(fraction) <= 2:
        raise DemoError("Use no more than two decimal places for dollar amounts")
    try:
        amount = Decimal(number.replace(",", ""))
        if suffix and suffix.lower() == "k":
            amount *= 1_000
        cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None
    return cents if cents >= 0 else None


def _extract_amounts(text: str) -> list[tuple[int, int, int]]:
    # A sentence-ending full stop is punctuation, not an invalid decimal.
    # Keep rejecting partial matches within malformed amounts such as $5.123.
    amount_end = r"(?![A-Za-z0-9_-]|\.(?!\s|$))"
    patterns = (
        rf"(?<![-+A-Za-z0-9])\$\s*({MONEY_NUMBER_PATTERN})(?:\s*([kK]))?{amount_end}",
        rf"\bUSD\s*({MONEY_NUMBER_PATTERN})(?:\s*([kK]))?{amount_end}",
        rf"(?<![-+])\b({MONEY_NUMBER_PATTERN})(?:\s*([kK]))?\s*(?:US dollars?|dollars?|USD)\b",
    )
    found = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            cents = _money_to_cents(match.group(1), match.group(2))
            if cents is not None:
                found.append((match.start(), match.end(), cents))
    merged = []
    for start, end, cents in sorted(set(found), key=lambda item: (item[0], -item[1])):
        for index, (saved_start, saved_end, saved_cents) in enumerate(merged):
            if start < saved_end and end > saved_start and cents == saved_cents:
                merged[index] = (
                    min(start, saved_start),
                    max(end, saved_end),
                    cents,
                )
                break
        else:
            merged.append((start, end, cents))
    return sorted(merged, key=lambda item: item[0])


def _unsupported_dollar_suffix(text: str) -> str:
    """Return an ambiguous suffix that must not be interpreted as money."""

    pattern = re.compile(
        rf"(?<![A-Za-z0-9])\$\s*({MONEY_NUMBER_PATTERN})(?P<gap>\s*)"
        r"(?P<suffix>[A-Za-z][A-Za-z-]*)?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        suffix = match.group("suffix")
        if not suffix:
            continue
        normalized = suffix.lower()
        separated = bool(match.group("gap"))
        if not separated and normalized not in {"k", "usd", "dollar", "dollars"}:
            return suffix
        if separated and (
            (normalized.startswith("k") and normalized != "k")
            or normalized in {"m", "million", "millions"}
        ):
            return suffix
    return ""


def _category(text: str) -> str:
    lower = text.lower()
    invoice = re.search(r"(?<![a-z0-9])invoices?(?![a-z0-9])", lower)
    if invoice:
        return "invoice"
    matches = []
    priority = ("tax", "insurance", "bill", "ticket", "subscription", "transfer")
    for rank, category in enumerate(priority):
        for keyword in CATEGORIES[category]["keywords"]:
            for match in re.finditer(
                rf"(?<![a-z0-9]){re.escape(keyword.strip())}(?![a-z0-9])",
                lower,
            ):
                if category == "bill" and keyword == "bill":
                    prefix = lower[: match.start()]
                    if re.search(r"\b(?:to|from|with)\s*$", prefix):
                        continue
                matches.append((match.start(), rank, category))
    return min(matches)[2] if matches else "purchase"


def _extract_payee(text: str, category: str) -> str:
    lower = text.lower()
    to_candidate = (
        r"\bto\s+(?!pay\b)([A-Za-z][A-Za-z0-9&.'@+_, -]{1,80}?)"
        r"(?=\s+(?:for|by|before|on|using|from|account|policy|invoice)\b|"
        r"\s+(?:\$|USD\b)|[.!?;](?:\s|$)|$)"
    )
    candidates = (
        r"\bfrom\s+([A-Za-z][A-Za-z0-9&.'@+_, -]{1,80}?)(?=\s+(?:for|by|before|on|using)\b|\s+(?:\$|USD\b)|[.!?;](?:\s|$)|$)",
        r"\bwith\s+([A-Za-z][A-Za-z0-9&.'@+_, -]{1,80}?)(?=\s+(?:for|by|before|on|using|policy|account)\b|\s+(?:\$|USD\b)|[.!?;](?:\s|$)|$)",
    )
    if category != "ticket":
        candidates = (to_candidate, *candidates)
    for pattern in candidates:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            raw_value = _clean(match.group(1), 80)
            value = raw_value.strip(" -,.;")
            if (
                (raw_value.endswith(".") or (
                    match.end(1) < len(text) and text[match.end(1)] == "."
                ))
                and re.search(r"\b(?:co|corp|inc|ltd)$", value, flags=re.IGNORECASE)
            ):
                value += "."
            if re.match(
                r"^(?:(?:bank\s+)?account|routing|card|wallet|policy|invoice)\b",
                value,
                flags=re.IGNORECASE,
            ):
                continue
            if value.lower() not in {"my", "the", "a", "an"}:
                alias_value = re.sub(r"^the\s+", "", value, flags=re.IGNORECASE).lower()
                for needle, payee, _categories in KNOWN_PAYEES:
                    if alias_value == needle:
                        return payee
                return value.title() if value.islower() else value

    # A payee explicitly named after "to", "from", or "with" always wins.
    # Known demo aliases are only a fallback when the request has no explicit
    # grammatical payee span; this prevents a brand token from rewriting a
    # longer user-supplied name such as "Northstar Labs".
    for needle, payee, categories in KNOWN_PAYEES:
        if category in categories and re.search(
            rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", lower
        ):
            return payee

    if category == "tax" and "federal" in lower:
        return "Internal Revenue Service"
    return ""


def _extract_reference(text: str, category: str) -> str:
    token = r"(?=[A-Z0-9./-]*\d)[A-Z0-9](?:[A-Z0-9./-]{1,46}[A-Z0-9])?"
    patterns = (
        rf"\b(?:invoice|policy|account|reference|notice|bill)\b\s+(?:number|no\.?|id)\s*[:#-]?\s*({token})(?![A-Z0-9./-])",
        rf"\b(?:invoice|policy|account|reference|notice|bill)\b\s*[:#]\s*({token})(?![A-Z0-9./-])",
        rf"\b(?:invoice|policy|account|reference|notice|bill)\b\s+({token})(?![A-Z0-9./-])",
        r"\b(Q[1-4][ -]?20\d{2})\b",
        r"\b((?:account|policy) ending\s+[0-9]{3,8})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean(match.group(1).upper(), 48)
    if category == "ticket":
        quantity = re.search(r"\b(one|two|three|four|[1-9])\s+(?:adjacent\s+)?tickets?\b", text, flags=re.IGNORECASE)
        if quantity:
            return _clean(quantity.group(0), 48)
    return ""


def _extract_due_date(text: str) -> str:
    match = re.search(
        r"\b(?:by|before|on)\s+((?:today|tomorrow|next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:,?\s+20\d{2})?|20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/20\d{2})\b",
        text,
        flags=re.IGNORECASE,
    )
    return _clean(match.group(1), 40) if match else "Not specified"


def _resolve_demo_beneficiary(plan: dict) -> None:
    """Expose the deterministic fictional recipient identity before approval."""

    payee = plan.get("payee", "")
    if payee:
        plan["payee_id"] = "beneficiary_demo_" + hashlib.sha256(
            payee.lower().encode("utf-8")
        ).hexdigest()[:16]
        plan["beneficiary_status"] = "fictional_local_fixture"
    else:
        plan["payee_id"] = ""
        plan["beneficiary_status"] = "unresolved"


def _apply_category(plan: dict, category: str) -> None:
    details = CATEGORIES[category]
    plan.update(
        category=category,
        category_label=details["label"],
        reference_label=details["reference_label"],
        reference_required=details["reference_required"],
        confirmation_label=details["confirmation"],
        domain_confirmation_label=details["domain_confirmation"],
        confirmation_scope=details["scope"],
    )


def _amount_role(text: str, start: int, end: int) -> str:
    """Distinguish a spending ceiling or estimate from an exact payment.

    This is deliberately a small deterministic parser. An unsupported range,
    estimate, or minimum must leave the exact amount for the user to supply.
    """

    lead = text[:start].lower()
    tail = text[end:].lower()
    ceiling = (
        r"\b(?:under|up\s+to|at\s+most|no\s+more\s+than|not\s+more\s+than|"
        r"not\s+exceeding|do\s+not\s+exceed|"
        r"(?:maximum|max)(?:\s+amount)?|budget|(?:spending\s+)?(?:cap|limit)|ceiling)"
        r"\s*(?:(?:of|is|at)\s*|[=:]\s*)?$"
    )
    if re.search(ceiling, lead) or re.match(
        r"\s*(?:maximum|max|budget|cap|limit|ceiling|or\s+less|or\s+lower)\b", tail
    ):
        return "maximum"
    if re.search(
        r"\b(?:at\s+least|more\s+than|over|minimum(?:\s+amount)?|"
        r"about|around|approximately|roughly|between|from)"
        r"\s*(?:(?:of|is)\s*|[=:]\s*)?$",
        lead,
    ) or re.match(r"\s*(?:minimum|or\s+more|or\s+higher)\b", tail):
        return "ambiguous"
    return "exact"


def _extract_plan(request_text: str) -> dict:
    category = _category(request_text)
    amounts = _extract_amounts(request_text)
    amount = None
    maximum = None
    exact_amounts = []
    ambiguous = False
    for start, end, cents in amounts:
        role = _amount_role(request_text, start, end)
        if role == "maximum":
            maximum = cents if maximum is None else min(maximum, cents)
        elif role == "ambiguous":
            ambiguous = True
        else:
            exact_amounts.append(cents)
    for (_start, end, _cents), (next_start, _end, _next_cents) in zip(amounts, amounts[1:], strict=False):
        if re.fullmatch(r"\s*(?:to|or|[-–—])\s*", request_text[end:next_start], re.IGNORECASE):
            ambiguous = True
    if not ambiguous and exact_amounts and len(set(exact_amounts)) == 1:
        amount = exact_amounts[0]
    if maximum is None and amount is not None:
        maximum = amount

    details = CATEGORIES[category]
    plan = {
        "category": category,
        "category_label": details["label"],
        "description": _clean(request_text, 180),
        "payee": _extract_payee(request_text, category),
        "payee_id": "",
        "beneficiary_status": "waiting_for_review",
        "amount_usd_cents": amount,
        "maximum_usd_cents": maximum,
        "source_asset": "USDC",
        "destination_asset": "USD",
        "reference": _extract_reference(request_text, category),
        "reference_label": details["reference_label"],
        "reference_required": details["reference_required"],
        "due_date": _extract_due_date(request_text),
        "recurrence": "one_time",
        "confirmation_label": details["confirmation"],
        "domain_confirmation_label": details["domain_confirmation"],
        "confirmation_scope": details["scope"],
        "review_notes": (
            ["An amount range, estimate, or minimum was found. Enter the exact amount to pay."]
            if ambiguous
            else ["More than one payment amount was found. Enter the exact amount to pay."]
            if len(set(exact_amounts)) > 1
            else []
        ),
    }
    _resolve_demo_beneficiary(plan)
    return plan


def _missing(plan: dict) -> list[dict]:
    keys = []
    if not plan.get("payee"):
        keys.append("payee")
    if not isinstance(plan.get("amount_usd_cents"), int):
        keys.append("amount_usd_cents")
    if plan.get("reference_required") and not plan.get("reference"):
        keys.append("reference")
    return [{"field": key, "question": FIELD_LABELS[key]} for key in keys]


def _authorization_payload(state: dict) -> dict:
    """Return every reviewed field that can affect execution or its meaning."""

    plan = state["plan"]
    return {
        "mission_id": state["id"],
        "operation_id": state["operation_id"],
        "request_digest": state["request_digest"],
        "plan_revision": state["plan_revision"],
        "category": plan["category"],
        "payee": plan["payee"],
        "payee_id": plan["payee_id"],
        "amount_usd_cents": plan["amount_usd_cents"],
        "maximum_usd_cents": plan["maximum_usd_cents"],
        "source_asset": plan["source_asset"],
        "destination_asset": plan["destination_asset"],
        "reference": plan["reference"],
        "due_date": plan["due_date"],
        "recurrence": plan["recurrence"],
    }


def _grant_body(grant: dict | None) -> dict:
    if not isinstance(grant, dict):
        return {}
    return {key: value for key, value in grant.items() if key != "signature"}


def _mock_signature(value: dict) -> str:
    return "mocksig:" + _digest(value)[7:31]


def _intent_payload(state: dict) -> dict:
    grant = state["grant"]
    return {
        "operation_id": state["operation_id"],
        "grant_digest": _digest(grant),
        "payee": grant["payee"],
        "payee_id": grant["payee_id"],
        "source_asset": grant["source_asset"],
        "source_usdc_units": grant["amount_usd_cents"] * 10_000,
        "destination_asset": grant["destination_asset"],
        "destination_usd_cents": grant["amount_usd_cents"],
        "reference": grant["reference"],
    }


def _grant_self_integrity_matches(state: dict) -> bool:
    grant = state.get("grant")
    if not isinstance(grant, dict):
        return False
    body = _grant_body(grant)
    return grant.get("signature") == _mock_signature(body)


def _grant_integrity_matches(state: dict) -> bool:
    grant = state.get("grant")
    if not isinstance(grant, dict):
        return False
    authority = _authorization_payload(state)
    expected_body = {
        **authority,
        "plan_digest": _digest(authority),
        "expires_at": grant.get("expires_at"),
    }
    return _grant_body(grant) == expected_body and _grant_self_integrity_matches(state)


def _signed_intent_self_integrity_matches(state: dict) -> bool:
    signed = state.get("signed_intent")
    if not isinstance(signed, dict):
        return False
    body = {
        key: value
        for key, value in signed.items()
        if key not in {"digest", "signature"}
    }
    return (
        signed.get("digest") == _digest(body)
        and signed.get("signature") == _mock_signature(body)
    )


def _signed_intent_matches(state: dict) -> bool:
    signed = state.get("signed_intent")
    if not isinstance(signed, dict):
        return False
    try:
        expected = _intent_payload(state)
    except (KeyError, TypeError):
        return False
    return _signed_intent_self_integrity_matches(state) and {
        key: signed.get(key) for key in expected
    } == expected


class MissionEngine:
    """Persist and execute reviewed payment missions with one local ledger."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "mission-control-v1.sqlite3"
        self.lock = threading.RLock()
        self.closed = False
        with _connect(self.path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS missions (
                    id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mission_ledger (
                    idempotency_key TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    account_from TEXT NOT NULL,
                    account_to TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    units INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(mission_id) REFERENCES missions(id)
                );
                CREATE TABLE IF NOT EXISTS mission_payments (
                    operation_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL UNIQUE,
                    payee_id TEXT NOT NULL,
                    amount_usd_cents INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    provider_reference TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(mission_id) REFERENCES missions(id)
                );
                """
            )
            # Nullable columns preserve old databases without inventing evidence
            # for already dispatched legacy payments.
            columns = {row[1] for row in db.execute("PRAGMA table_info(mission_payments)")}
            for name, kind in (("intent_json", "TEXT"), ("grant_json", "TEXT"),
                               ("source_usdc_units", "INTEGER"), ("source_asset", "TEXT"),
                               ("destination_asset", "TEXT")):
                if name not in columns:
                    db.execute(f"ALTER TABLE mission_payments ADD COLUMN {name} {kind}")

    def close(self) -> None:
        """Stop accepting work; database connections are closed per operation."""

        with self.lock:
            self.closed = True

    def _ensure_open(self) -> None:
        if self.closed:
            raise DemoError("Mission engine is closed", 503)

    def config(self) -> dict:
        self._ensure_open()
        return {
            "schema_version": SCHEMA_VERSION,
            "examples": list(EXAMPLES),
            "demo_outcomes": ["success", "payout_reply_lost"],
            "starting_balance_usdc_units": STARTING_USDC_UNITS,
            "max_payment_usd_cents": MAX_PAYMENT_USD_CENTS,
            "notice": "Local product simulation. No model, wallet, blockchain, bank, biller, government agency, insurer, merchant, coverage, or real money is connected.",
            "agent_api": {
                "analyze": "POST /api/missions/analyze",
                "details": "POST /api/missions/{id}/details",
                "authorize": "POST /api/missions/{id}/authorize",
                "advance": "POST /api/missions/{id}/advance",
                "investigate": "POST /api/missions/{id}/investigate",
                "reconcile": "POST /api/missions/{id}/reconcile",
            },
        }

    @staticmethod
    def _read(db, mission_id: str) -> dict:
        row = db.execute("SELECT state_json FROM missions WHERE id=?", (mission_id,)).fetchone()
        if row is None:
            raise DemoError("Payment mission not found", 404)
        state = json.loads(row["state_json"])
        if state.get("schema_version") != SCHEMA_VERSION:
            raise DemoError("This mission belongs to an older demo. Start a new mission.", 409)
        return state

    @staticmethod
    def _save(db, state: dict) -> None:
        db.execute("UPDATE missions SET state_json=? WHERE id=?", (_encode(state), state["id"]))

    @staticmethod
    def _balances(state: dict) -> dict:
        return deepcopy(state["money"])

    @staticmethod
    def _states(state: dict) -> dict:
        return deepcopy(state["states"])

    def _event(
        self,
        state: dict,
        *,
        stage: str,
        title: str,
        user_message: str,
        actor: str,
        action: str,
        control: str,
        proof: str,
        safe_retry: str,
        method: str,
        route: str,
        request: dict,
        response: dict,
        before_states: dict | None,
        before_money: dict | None,
    ) -> None:
        event = {
            "id": f"{state['id']}:{state['revision']}:{len(state['events'])}",
            "number": len(state["events"]),
            "revision": state["revision"],
            "stage": stage,
            "title": title,
            "user_message": user_message,
            "backend": {
                "actor": actor,
                "action": action,
                "control": control,
                "proof": proof,
                "safe_retry": safe_retry,
                "method": method,
                "route": route,
                "request": _redact_for_audit(request),
                "response": _redact_for_audit(response),
            },
            "states_before": before_states,
            "states_after": self._states(state),
            "money_before": before_money,
            "money_after": self._balances(state),
        }
        state.update(stage=stage, title=title, user_message=user_message)
        state["events"].append(event)

    def _guard_revision(self, state: dict, expected_revision, db) -> None:
        if type(expected_revision) is not int or expected_revision < 0:
            raise DemoError("expected_revision must be a nonnegative integer")
        if expected_revision != state["revision"]:
            raise DemoError(
                "This mission changed in another action. Reload its current state.",
                409,
                self._snapshot(state, db),
            )

    def _snapshot(self, state: dict, db) -> dict:
        result = deepcopy(state)
        result.setdefault("demo_outcome", "success")
        result["can_investigate"] = self._can_investigate(state)
        result["recovery_intent_digest"] = None
        if state.get("signed_intent"):
            from purchase_simulator.mission_recovery import intent_from_state
            try:
                result["recovery_intent_digest"] = intent_from_state(state).view()["intent_digest"]
            except (KeyError, ValueError, TypeError, OverflowError, RecursionError):
                pass
        result["missing_fields"] = _missing(result["plan"])
        result["can_authorize"] = result["status"] in {"needs_details", "ready"} and not result["missing_fields"]
        result["can_advance"] = result["status"] in {"authorized", "checked", "held", "signed", "dispatched", "paid"}
        result["ledger"] = [dict(row) for row in db.execute(
            "SELECT idempotency_key,kind,account_from,account_to,asset,units,created_at FROM mission_ledger WHERE mission_id=? ORDER BY created_at,idempotency_key",
            (state["id"],),
        )]
        payment = db.execute(
            "SELECT operation_id,payee_id,amount_usd_cents,status,attempt_count,provider_reference,created_at FROM mission_payments WHERE mission_id=?",
            (state["id"],),
        ).fetchone()
        result["provider_payment"] = dict(payment) if payment else None
        return result

    def get(self, mission_id: str) -> dict:
        self._ensure_open()
        with self.lock, _connect(self.path) as db:
            return self._snapshot(self._read(db, mission_id), db)

    def analyze(self, request_text, *, demo_outcome="success") -> dict:
        self._ensure_open()
        if not isinstance(demo_outcome, str) or demo_outcome not in {"success", "payout_reply_lost"}:
            raise DemoError("Choose success or payout_reply_lost as the demo outcome")
        if not isinstance(request_text, str):
            raise DemoError("request must be text")
        request_text = _clean(request_text, MAX_REQUEST_LENGTH + 1)
        if not 4 <= len(request_text) <= MAX_REQUEST_LENGTH:
            raise DemoError(f"Describe the payment in 4 to {MAX_REQUEST_LENGTH} characters")
        request_text, redaction_categories = _redact_sensitive_text(request_text)
        unsupported_suffix = _unsupported_dollar_suffix(request_text)
        if unsupported_suffix:
            raise DemoError(
                f"Ambiguous amount suffix {unsupported_suffix!r}; use formats like "
                "$20, $25k, or $20.00 USD"
            )

        plan = _extract_plan(request_text)
        explicit_amounts = _extract_amounts(request_text)
        if any(not 0 < cents <= MAX_PAYMENT_USD_CENTS for _start, _end, cents in explicit_amounts):
            raise DemoError("Payment amounts must be greater than $0 and no more than $25,000")
        mission_id = uuid.uuid4().hex
        operation_id = "pay_" + uuid.uuid4().hex
        missing = _missing(plan)
        state = {
            "schema_version": SCHEMA_VERSION,
            "id": mission_id,
            "operation_id": operation_id,
            "demo_outcome": demo_outcome,
            "revision": 0,
            "plan_revision": 1,
            "status": "needs_details" if missing else "ready",
            "stage": "analyzed",
            "title": "Payment plan prepared",
            "user_message": "I need a few details before you can authorize this." if missing else "I prepared a payment plan for your review.",
            "request_text": request_text,
            "request_digest": _digest(request_text),
            "sensitive_input_redacted": bool(redaction_categories),
            "redaction_categories": sorted(redaction_categories),
            "plan": plan,
            "states": {
                "authority": "draft",
                "policy": "waiting",
                "funding": "available",
                "payout": "not_started",
                "confirmation": "not_started",
                "domain_confirmation": "not_verified",
            },
            "money": {
                "customer_available_usdc_units": STARTING_USDC_UNITS,
                "payment_hold_usdc_units": 0,
                "provider_in_transit_usdc_units": 0,
                "payee_received_usd_cents": 0,
            },
            "grant": None,
            "policy_decision": None,
            "signed_intent": None,
            "receipt": None,
            "events": [],
            "terminal": False,
        }
        self._event(
            state,
            stage="analyzed",
            title="Payment request understood",
            user_message=state["user_message"],
            actor="Intent compiler",
            action="Extract a reviewable plan",
            control="Belay leaves unknown money-moving fields blank instead of guessing.",
            proof="Original request and extracted plan",
            safe_retry="Analysis moves no money and can be repeated safely.",
            method="POST",
            route="/api/missions/analyze",
            request={"request": request_text},
            response={"category": plan["category"], "missing_fields": [item["field"] for item in missing]},
            before_states=None,
            before_money=None,
        )
        with self.lock, _connect(self.path) as db:
            db.execute("INSERT INTO missions(id,state_json) VALUES(?,?)", (mission_id, _encode(state)))
            return self._snapshot(state, db)

    def update_details(self, mission_id: str, expected_revision, fields) -> dict:
        self._ensure_open()
        if not isinstance(fields, dict):
            raise DemoError("fields must be an object")
        allowed = {
            "category",
            "payee",
            "amount_usd_cents",
            "maximum_usd_cents",
            "reference",
            "due_date",
            "description",
        }
        if not fields or not set(fields) <= allowed:
            raise DemoError("Provide one or more supported plan fields")
        with self.lock, _connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            state = self._read(db, mission_id)
            self._guard_revision(state, expected_revision, db)
            if state["status"] not in {"needs_details", "ready"}:
                raise DemoError("Authorized plans cannot be edited; start a new mission", 409)
            before_states = self._states(state)
            before_money = self._balances(state)
            plan = state["plan"]
            plan_before = deepcopy(plan)
            new_redaction_categories = set()
            for key, value in fields.items():
                if key == "category":
                    if not isinstance(value, str) or value not in CATEGORIES:
                        raise DemoError("Choose a supported payment type")
                    _apply_category(plan, value)
                elif key in {"amount_usd_cents", "maximum_usd_cents"}:
                    if value is None or value == "":
                        plan[key] = None
                    elif not isinstance(value, int) or isinstance(value, bool) or not 0 < value <= MAX_PAYMENT_USD_CENTS:
                        raise DemoError("Amounts must be positive whole USD cents within the demo limit")
                    else:
                        plan[key] = value
                else:
                    if not isinstance(value, str):
                        raise DemoError(f"{key} must be text")
                    value, categories = _redact_sensitive_text(value)
                    new_redaction_categories.update(categories)
                    plan[key] = _clean(value, 180 if key == "description" else 80)
            if plan.get("payee") and not re.search(r"[A-Za-z0-9]", plan["payee"]):
                raise DemoError("Payee must include a letter or number")
            if "[REDACTED" in plan.get("payee", "").upper():
                plan["payee"] = ""
            if new_redaction_categories:
                state["sensitive_input_redacted"] = True
                state["redaction_categories"] = sorted(
                    set(state.get("redaction_categories", [])) | new_redaction_categories
                )
            _resolve_demo_beneficiary(plan)
            if plan.get("amount_usd_cents") and plan.get("maximum_usd_cents") is None:
                plan["maximum_usd_cents"] = plan["amount_usd_cents"]
            if plan != plan_before:
                state["plan_revision"] = state.get("plan_revision", 1) + 1
            state["revision"] += 1
            missing = _missing(plan)
            state["status"] = "needs_details" if missing else "ready"
            message = "I still need " + ", ".join(item["question"] for item in missing) if missing else "The exact payee, amount, and reference are ready for your review."
            self._event(
                state,
                stage="plan_ready" if not missing else "needs_details",
                title="Payment plan updated",
                user_message=message,
                actor="Plan editor",
                action="Save reviewed details",
                control="Only the user-reviewed fields can become payment authority.",
                proof="Versioned plan update",
                safe_retry="A stale revision is rejected; no money can move here.",
                method="POST",
                route=f"/api/missions/{mission_id}/details",
                request={"fields": fields, "expected_revision": expected_revision},
                response={"ready": not missing, "missing_fields": [item["field"] for item in missing]},
                before_states=before_states,
                before_money=before_money,
            )
            self._save(db, state)
            return self._snapshot(state, db)

    def authorize(self, mission_id: str, expected_revision) -> dict:
        self._ensure_open()
        with self.lock, _connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            state = self._read(db, mission_id)
            self._guard_revision(state, expected_revision, db)
            if state["status"] not in {"ready", "needs_details"}:
                raise DemoError("This mission is already authorized", 409)
            missing = _missing(state["plan"])
            if missing:
                raise DemoError("Complete the missing payment details before authorization")
            plan = state["plan"]
            amount = plan["amount_usd_cents"]
            maximum = plan["maximum_usd_cents"]
            if maximum is not None and amount > maximum:
                raise DemoError("The exact payment exceeds the reviewed maximum")
            if amount * 10_000 > state["money"]["customer_available_usdc_units"]:
                raise DemoError("The demo wallet does not have enough USDC")
            before_states = self._states(state)
            before_money = self._balances(state)
            _resolve_demo_beneficiary(plan)
            state["revision"] += 1
            state["status"] = "authorized"
            state["states"]["authority"] = "approved"
            authority = _authorization_payload(state)
            grant_body = {
                **authority,
                "plan_digest": _digest(authority),
                "expires_at": int(time.time()) + 1_800,
            }
            state["grant"] = {**grant_body, "signature": _mock_signature(grant_body)}
            self._event(
                state,
                stage="authorized",
                title="You approved one exact payment",
                user_message=f"Authorized one payment of ${amount / 100:,.2f} to {plan['payee']}.",
                actor="Authority service",
                action="Create a bounded payment grant",
                control="The approval fixes the payee, amount, reference, assets, operation ID, and expiry.",
                proof="Signed local authorization record",
                safe_retry="The same mission cannot create a second grant.",
                method="POST",
                route=f"/api/missions/{mission_id}/authorize",
                request={"expected_revision": expected_revision, "reviewed_plan": plan},
                response={"grant_digest": _digest(state["grant"]), "expires_at": grant_body["expires_at"]},
                before_states=before_states,
                before_money=before_money,
            )
            self._save(db, state)
            return self._snapshot(state, db)

    def _policy(self, state: dict) -> dict:
        plan = state["plan"]
        grant = state.get("grant") if isinstance(state.get("grant"), dict) else {}
        amount = plan.get("amount_usd_cents")
        amount_units = amount * 10_000 if type(amount) is int and amount > 0 else -1
        authority = _authorization_payload(state)
        status = state["status"]
        if status in {"authorized", "checked"}:
            funding_matches = amount_units <= state["money"]["customer_available_usdc_units"]
        elif status in {"held", "signed"}:
            funding_matches = state["money"]["payment_hold_usdc_units"] == amount_units
        else:
            funding_matches = True
        signed_matches = status != "signed" or _signed_intent_matches(state)
        expires_at = grant.get("expires_at")
        checks = (
            ("User approved", state["states"]["authority"] == "approved"),
            ("Plan unchanged", grant.get("plan_digest") == _digest(authority)),
            ("Grant signature valid", _grant_integrity_matches(state)),
            ("Payee matches", grant.get("payee_id") == plan.get("payee_id")),
            ("Amount matches", grant.get("amount_usd_cents") == amount),
            ("Within maximum", type(plan.get("maximum_usd_cents")) is int and type(amount) is int and amount <= plan["maximum_usd_cents"]),
            ("Exact funds ready", amount_units > 0 and funding_matches),
            ("Reference ready", not plan["reference_required"] or bool(plan["reference"])),
            ("Payee reviewed", plan["beneficiary_status"] == "fictional_local_fixture"),
            ("USDC source", grant.get("source_asset") == "USDC"),
            ("USD destination", grant.get("destination_asset") == "USD"),
            ("One-time scope", grant.get("recurrence") == "one_time"),
            ("Grant active", type(expires_at) is int and int(time.time()) < expires_at),
            ("Operation fixed", grant.get("operation_id") == state["operation_id"]),
            ("Signed instruction matches", signed_matches),
        )
        items = [{"name": name, "passed": passed} for name, passed in checks]
        return {"allowed": all(passed for _name, passed in checks), "checks": items}

    def _ledger_once(self, db, state, key, kind, source, destination, asset, units) -> None:
        try:
            db.execute(
                "INSERT INTO mission_ledger VALUES(?,?,?,?,?,?,?,?)",
                (key, state["id"], kind, source, destination, asset, units, int(time.time())),
            )
        except sqlite3.IntegrityError as exc:
            raise DemoError("This value movement already exists; Belay refused a duplicate", 409) from exc

    @staticmethod
    def _captured_intent(state):
        from recovery_app.payment import canonical
        return canonical({key: value for key, value in state["signed_intent"].items()
                          if key not in {"digest", "signature"}})

    @staticmethod
    def _captured_grant(state):
        from recovery_app.payment import canonical
        return canonical(state["grant"])

    @staticmethod
    def _can_investigate(state):
        return (state["status"] in {"dispatched", "payout_unknown", "review_required"}
                and state["money"]["provider_in_transit_usdc_units"] > 0)

    def _investigate(self, db, state):
        from purchase_simulator.mission_recovery import investigate

        def lookup(operation_id):
            row = db.execute("SELECT * FROM mission_payments WHERE operation_id=?",
                             (operation_id,)).fetchone()
            return dict(row) if row is not None else None

        return investigate(state, lookup)

    def investigate(self, mission_id: str, expected_revision) -> dict:
        """Return deterministic evidence only, with no state or ledger mutation."""
        self._ensure_open()
        with self.lock, _connect(self.path) as db:
            db.execute("BEGIN")
            state = self._read(db, mission_id)
            self._guard_revision(state, expected_revision, db)
            if not self._can_investigate(state):
                raise DemoError("Only an unresolved dispatched payment can be investigated", 409)
            return self._investigate(db, state)

    def reconcile(self, mission_id: str, expected_revision, evidence_digest) -> dict:
        """Account an already paid original operation after a fresh evidence read."""
        self._ensure_open()
        if not isinstance(evidence_digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", evidence_digest):
            raise DemoError("Provide the evidence_digest from the current investigation")
        with self.lock, _connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            state = self._read(db, mission_id)
            self._guard_revision(state, expected_revision, db)
            if not self._can_investigate(state):
                raise DemoError("This mission has no unresolved payout to reconcile", 409)
            finding = self._investigate(db, state)
            if (finding["evidence_digest"] != evidence_digest
                    or finding["verdict"] != "paid" or not finding["can_reconcile"]):
                raise DemoError("Fresh evidence does not confirm the original payment; investigate again", 409,
                                self._snapshot(state, db))
            before_states, before_money = self._states(state), self._balances(state)
            amount_units = state["signed_intent"]["source_usdc_units"]
            amount_cents = state["signed_intent"]["destination_usd_cents"]
            self._ledger_once(db, state, f"{state['operation_id']}:paid", "usdc_to_usd_payout",
                              "settlement_provider", "payee_received", "USDC_TO_USD_1_TO_1_DEMO", amount_units)
            state["money"]["provider_in_transit_usdc_units"] -= amount_units
            state["money"]["payee_received_usd_cents"] += amount_cents
            state.update(status="paid", terminal=False, revision=state["revision"] + 1)
            state["states"].update(funding="settled", payout="paid", confirmation="payment_recorded")
            self._event(
                state, stage="paid", title="Original payout reconciled",
                user_message="Fresh provider evidence confirmed the original simulated USD payout. Belay recorded it once without sending another payment.",
                actor="Recovery Desk and payment executor", action="Reconcile existing payout evidence",
                control="Read-only findings cannot move money; the executor checks fresh evidence and revision.",
                proof="Cited provider payout record", safe_retry="A unique ledger key prevents double accounting.",
                method="RECONCILE", route=f"/api/missions/{mission_id}/reconcile",
                request={"expected_revision": expected_revision, "evidence_digest": evidence_digest},
                response={"verdict": finding["verdict"], "citations": finding["citations"],
                          "intent_digest": finding["intent_digest"]},
                before_states=before_states, before_money=before_money,
            )
            self._save(db, state)
            return self._snapshot(state, db)

    def advance(self, mission_id: str, expected_revision) -> dict:
        self._ensure_open()
        with self.lock, _connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            state = self._read(db, mission_id)
            self._guard_revision(state, expected_revision, db)
            if state["terminal"]:
                raise DemoError("This mission is already complete", 409)
            if state["status"] not in {"authorized", "checked", "held", "signed", "dispatched", "paid"}:
                raise DemoError("Authorize the reviewed payment before execution", 409)
            before_states = self._states(state)
            before_money = self._balances(state)
            state["revision"] += 1
            status = state["status"]
            if status in {"authorized", "checked", "held", "signed"}:
                amount_cents = state["plan"]["amount_usd_cents"]
                amount_units = amount_cents * 10_000
            else:
                amount_cents = 0
                amount_units = 0

            if status in {"authorized", "checked", "held", "signed"}:
                decision = self._policy(state)
                state["policy_decision"] = decision
                if not decision["allowed"]:
                    failed_checks = {
                        check["name"]
                        for check in decision["checks"]
                        if not check["passed"]
                    }
                    expired = "Grant active" in failed_checks
                    held_units = state["money"]["payment_hold_usdc_units"]
                    if held_units:
                        self._ledger_once(
                            db,
                            state,
                            f"{mission_id}:integrity-return",
                            "integrity_hold_return",
                            "payment_hold",
                            "customer_available",
                            "USDC",
                            held_units,
                        )
                        state["money"]["payment_hold_usdc_units"] = 0
                        state["money"]["customer_available_usdc_units"] += held_units
                    state.update(status="blocked", terminal=True)
                    state["states"]["policy"] = "blocked"
                    if held_units:
                        state["states"]["funding"] = "returned"
                    if expired and held_units:
                        blocked_title = "Authorization expired"
                        blocked_message = (
                            "The authorization expired. Reserved USDC was returned; "
                            "nothing was dispatched."
                        )
                    elif expired:
                        blocked_title = "Authorization expired"
                        blocked_message = (
                            "The authorization expired before any funds were reserved or sent."
                        )
                    elif held_units:
                        blocked_title = "Payment details changed"
                        blocked_message = (
                            "The payment no longer matched your authorization. Reserved USDC "
                            "was returned; nothing was dispatched."
                        )
                    else:
                        blocked_title = "Payment details changed"
                        blocked_message = (
                            "The payment no longer matched your authorization. Belay stopped "
                            "it before any funds were reserved or sent."
                        )
                    self._event(
                        state, stage="blocked", title=blocked_title,
                        user_message=blocked_message,
                        actor="Policy service", action="Compare plan with authority",
                        control="Deterministic checks run outside the AI.", proof="Failed policy record",
                        safe_retry="A corrected plan needs a new authorization.", method="DECIDE",
                        route="belay://policy/check", request={"grant": state["grant"], "plan": state["plan"]},
                        response=decision, before_states=before_states, before_money=before_money,
                    )
                    self._save(db, state)
                    return self._snapshot(state, db)

            if status == "authorized":
                state["status"] = "checked"
                state["states"]["policy"] = "passed"
                self._event(
                    state, stage="checked", title="Every payment limit matched",
                    user_message="Belay checked the payee, amount, reference, wallet, assets, and expiry.",
                    actor="Policy service", action="Match the plan exactly",
                    control="The AI cannot approve its own proposal.", proof=f"{len(decision['checks'])} deterministic checks",
                    safe_retry="Checks move no money.", method="DECIDE", route="belay://policy/check",
                    request={"grant_digest": _digest(state["grant"]), "plan_digest": _digest(state["plan"])},
                    response=decision, before_states=before_states, before_money=before_money,
                )
            elif status == "checked":
                self._ledger_once(db, state, f"{mission_id}:hold", "payment_hold", "customer_available", "payment_hold", "USDC", amount_units)
                state["money"]["customer_available_usdc_units"] -= amount_units
                state["money"]["payment_hold_usdc_units"] += amount_units
                state["status"] = "held"
                state["states"]["funding"] = "held"
                self._event(
                    state, stage="held", title="Exact funds reserved",
                    user_message=f"{amount_cents / 100:,.2f} USDC is reserved for this payment only.",
                    actor="Treasury", action="Reserve the exact amount",
                    control="The hold and ledger record commit together.", proof="Single-use hold entry",
                    safe_retry="The hold key can be written only once.", method="TRANSACT", route="belay://treasury/hold",
                    request={"amount_usdc_units": amount_units}, response={"held": True},
                    before_states=before_states, before_money=before_money,
                )
            elif status == "held":
                intent = _intent_payload(state)
                state["signed_intent"] = {
                    **intent,
                    "digest": _digest(intent),
                    "signature": _mock_signature(intent),
                }
                state["status"] = "signed"
                self._event(
                    state, stage="signed", title="Payment instruction locked",
                    user_message="The payment instruction is now bound to the authorization you reviewed.",
                    actor="Protected signer", action="Bind every payment field",
                    control="Changing the amount, payee, reference, or operation ID invalidates execution.",
                    proof="Transaction-bound intent digest", safe_retry="Signing moves no money.",
                    method="SIGN", route="belay://signer/payment-intent", request=intent,
                    response={"intent_digest": state["signed_intent"]["digest"]},
                    before_states=before_states, before_money=before_money,
                )
            elif status == "signed":
                provider_reference = "pout_demo_" + state["operation_id"][-12:]
                db.execute(
                    """
                    INSERT INTO mission_payments(
                        operation_id,mission_id,payee_id,amount_usd_cents,status,
                        attempt_count,provider_reference,created_at,
                        intent_json,grant_json,source_usdc_units,source_asset,destination_asset
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        state["operation_id"],
                        mission_id,
                        state["signed_intent"]["payee_id"],
                        state["signed_intent"]["destination_usd_cents"],
                        "processing",
                        1,
                        provider_reference,
                        int(time.time()),
                        self._captured_intent(state),
                        self._captured_grant(state),
                        state["signed_intent"]["source_usdc_units"],
                        state["signed_intent"]["source_asset"],
                        state["signed_intent"]["destination_asset"],
                    ),
                )
                self._ledger_once(db, state, state["operation_id"], "provider_dispatch", "payment_hold", "settlement_provider", "USDC", amount_units)
                state["money"]["payment_hold_usdc_units"] -= amount_units
                state["money"]["provider_in_transit_usdc_units"] += amount_units
                state["status"] = "dispatched"
                state["states"]["funding"] = "dispatched"
                state["states"]["payout"] = "processing"
                self._event(
                    state, stage="dispatched", title="USDC sent once",
                    user_message="Belay sent the authorized USDC under one stable payment identity.",
                    actor="Payment executor", action="Dispatch the signed instruction",
                    control="The executor accepts only the saved signed intent.", proof="Stable operation ID",
                    safe_retry="Every retry must reuse the same operation ID.", method="POST",
                    route="https://settlement.belay.invalid/v1/payments",
                    request={"operation_id": state["operation_id"], "intent_digest": state["signed_intent"]["digest"]},
                    response={"accepted": True, "idempotent": True, "provider_reference": provider_reference},
                    before_states=before_states, before_money=before_money,
                )
            elif status == "dispatched":
                payment = db.execute(
                    """
                    SELECT operation_id,mission_id,payee_id,amount_usd_cents,status,
                           attempt_count,provider_reference
                    FROM mission_payments WHERE operation_id=?
                    """,
                    (state["operation_id"],),
                ).fetchone()
                signed_intent = state.get("signed_intent") or {}
                payment_matches = (
                    payment is not None
                    and _grant_self_integrity_matches(state)
                    and _signed_intent_matches(state)
                    and payment["mission_id"] == mission_id
                    and payment["operation_id"] == state["operation_id"]
                    and payment["payee_id"] == signed_intent.get("payee_id")
                    and payment["amount_usd_cents"] == signed_intent.get("destination_usd_cents")
                    and payment["amount_usd_cents"] * 10_000
                    == state["money"]["provider_in_transit_usdc_units"]
                )
                if not payment_matches:
                    state.update(status="review_required", terminal=False)
                    state["states"]["payout"] = "unknown"
                    self._event(
                        state, stage="review_required", title="Settlement needs review",
                        user_message="Belay could not prove the provider accepted this payment. It will not send another.",
                        actor="Settlement reconciler", action="Find the stable operation ID",
                        control="An unknown result never triggers a second payment.", proof="Missing provider record",
                        safe_retry="Reconcile the same operation ID before any retry.", method="GET",
                        route="https://settlement.belay.invalid/v1/payments/{operation_id}",
                        request={"operation_id": state["operation_id"]}, response={"status": "unknown"},
                        before_states=before_states, before_money=before_money,
                    )
                    self._save(db, state)
                    return self._snapshot(state, db)
                amount_cents = payment["amount_usd_cents"]
                amount_units = amount_cents * 10_000
                trusted_payee = signed_intent["payee"]
                provider_reference = payment["provider_reference"]
                if payment["status"] not in {"processing", "paid"}:
                    raise DemoError("The provider payment has an invalid status", 409)
                db.execute(
                    "UPDATE mission_payments SET status='paid' WHERE operation_id=?",
                    (state["operation_id"],),
                )
                finding = self._investigate(db, state)
                if not finding["can_reconcile"]:
                    state.update(status="review_required", terminal=False)
                    state["states"]["payout"] = "unknown"
                    self._event(
                        state, stage="review_required", title="Settlement evidence needs review",
                        user_message=finding["summary"], actor="Recovery Desk",
                        action="Compare original dispatch and provider evidence",
                        control="Incomplete or conflicting evidence cannot release or credit funds.",
                        proof="Deterministic evidence checks", safe_retry="Investigate the same operation; never send again.",
                        method="VERIFY", route="belay://recovery/payment",
                        request={"operation_id": state["operation_id"]},
                        response={"verdict": finding["verdict"]},
                        before_states=before_states, before_money=before_money,
                    )
                    self._save(db, state)
                    return self._snapshot(state, db)
                if state.get("demo_outcome") == "payout_reply_lost":
                    state.update(status="payout_unknown", terminal=False)
                    state["states"]["payout"] = "unknown"
                    self._event(
                        state, stage="payout_unknown", title="Payout reply lost",
                        user_message="The fictional provider completed the payout, but its reply was lost. Investigate the original payment before changing its balance.",
                        actor="Settlement adapter", action="Record an uncertain payout",
                        control="Funds remain in transit; no retry or release is permitted.",
                        proof="Stable operation identity", safe_retry="Read the original provider record; never send again.",
                        method="GET", route="https://settlement.belay.invalid/v1/payments/{operation_id}",
                        request={"operation_id": state["operation_id"]}, response={"status": "unknown"},
                        before_states=before_states, before_money=before_money,
                    )
                    self._save(db, state)
                    return self._snapshot(state, db)
                self._ledger_once(db, state, f"{state['operation_id']}:paid", "usdc_to_usd_payout", "settlement_provider", "payee_received", "USDC_TO_USD_1_TO_1_DEMO", amount_units)
                state["money"]["provider_in_transit_usdc_units"] -= amount_units
                state["money"]["payee_received_usd_cents"] += amount_cents
                state["status"] = "paid"
                state["states"]["funding"] = "settled"
                state["states"]["payout"] = "paid"
                state["states"]["confirmation"] = "payment_recorded"
                self._event(
                    state, stage="paid", title="Simulated USD payout recorded",
                    user_message=f"The settlement adapter recorded one simulated ${amount_cents / 100:,.2f} USD payout to {trusted_payee}.",
                    actor="Settlement adapter", action="Convert USDC and pay USD",
                    control="The beneficiary and amount come from the signed instruction.", proof="Provider payout record",
                    safe_retry="The provider stores one record for the operation ID.", method="WEBHOOK",
                    route="https://settlement.belay.invalid/v1/payments/complete",
                    request={"operation_id": state["operation_id"]},
                    response={"provider_reference": provider_reference, "status": "paid", "attempt_count": 1},
                    before_states=before_states, before_money=before_money,
                )
            else:
                payment = db.execute(
                    """
                    SELECT operation_id,payee_id,amount_usd_cents,status,
                           attempt_count,provider_reference,created_at
                    FROM mission_payments WHERE mission_id=?
                    """,
                    (mission_id,),
                ).fetchone()
                if payment is None or payment["status"] != "paid":
                    raise DemoError("A paid provider record is required for a receipt", 409)
                receipt_sources_match = (
                    _grant_integrity_matches(state)
                    and _signed_intent_matches(state)
                    and payment["operation_id"] == state["operation_id"]
                    and payment["payee_id"] == state["signed_intent"]["payee_id"]
                    and payment["amount_usd_cents"]
                    == state["signed_intent"]["destination_usd_cents"]
                    and state["money"]["payee_received_usd_cents"]
                    == payment["amount_usd_cents"]
                )
                if not receipt_sources_match:
                    state.update(status="review_required", terminal=True)
                    state["states"]["confirmation"] = "integrity_failed"
                    self._event(
                        state, stage="review_required", title="Receipt needs review",
                        user_message="The payout is recorded, but its saved evidence no longer matches. Belay will not create a misleading receipt.",
                        actor="Receipt verifier", action="Compare the authorization, intent, and payout",
                        control="A receipt is created only when every source agrees.", proof="Failed receipt linkage",
                        safe_retry="Review the existing payment; do not send another.", method="VERIFY",
                        route="belay://receipts/verify", request={"operation_id": state["operation_id"]},
                        response={"linked": False}, before_states=before_states, before_money=before_money,
                    )
                    self._save(db, state)
                    return self._snapshot(state, db)
                state["status"] = "complete"
                state["terminal"] = True
                state["states"]["confirmation"] = "receipt_linked"
                state["states"]["domain_confirmation"] = "external_not_verified"
                category_details = CATEGORIES.get(
                    state["grant"]["category"], CATEGORIES["purchase"]
                )
                trusted_payee = state["signed_intent"]["payee"]
                receipt_body = {
                    "mission_id": mission_id,
                    "operation_id": state["operation_id"],
                    "request_digest": state["request_digest"],
                    "authorization_digest": _digest(state["grant"]),
                    "payment_intent_digest": state["signed_intent"]["digest"],
                    "category": state["grant"]["category"],
                    "payee": trusted_payee,
                    "payee_id": payment["payee_id"],
                    "amount_usd_cents": payment["amount_usd_cents"],
                    "reference": state["signed_intent"]["reference"],
                    "confirmation": category_details["confirmation"],
                    "scope": category_details["scope"],
                    "payment": {
                        "status": "simulated_paid",
                        "source_asset": "USDC",
                        "destination_asset": "USD",
                        "amount_usd_cents": payment["amount_usd_cents"],
                        "provider_reference": payment["provider_reference"],
                        "attempt_count": payment["attempt_count"],
                    },
                    "domain_outcome": {
                        "label": category_details["domain_confirmation"],
                        "status": "not_verified",
                        "scope": category_details["scope"],
                    },
                }
                state["receipt"] = {**receipt_body, "receipt_id": "rcpt_" + uuid.uuid4().hex[:20], "digest": _digest(receipt_body)}
                self._event(
                    state, stage="complete", title="Payment receipt ready",
                    user_message=f"Done. The receipt links your request, authorization, and simulated payment to {trusted_payee}. {category_details['domain_confirmation']} remains external.",
                    actor="Receipt service", action="Link the completed facts",
                    control="The receipt says exactly what this payment proves and what remains external.",
                    proof="Linked payment receipt", safe_retry="Creating the receipt cannot move money.",
                    method="WRITE", route="belay://receipts", request={"operation_id": state["operation_id"]},
                    response={"receipt_id": state["receipt"]["receipt_id"], "digest": state["receipt"]["digest"]},
                    before_states=before_states, before_money=before_money,
                )

            self._save(db, state)
            return self._snapshot(state, db)
