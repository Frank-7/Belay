"""Deterministic purchase admission for the Belay investor simulator.

The shopping agent may propose an order. This module decides whether that
proposal matches the customer's signed grant. It contains no model call and
cannot move money.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    checks: tuple[dict, ...]
    reason: str


def _seats_are_adjacent(seats: list[str], quantity: int) -> bool:
    if len(seats) != quantity or len(set(seats)) != quantity:
        return False
    try:
        parsed = [seat.rsplit("-", 1) for seat in seats]
        section_rows = {prefix for prefix, _number in parsed}
        numbers = sorted(int(number) for _prefix, number in parsed)
    except (AttributeError, TypeError, ValueError):
        return False
    return len(section_rows) == 1 and numbers == list(
        range(numbers[0], numbers[0] + quantity)
    )


def evaluate(grant: dict, offer: dict, quote: dict, now: int) -> PolicyDecision:
    """Compare an exact offer and payout quote with a bounded customer grant."""

    checks = (
        {"name": "customer_approved", "expected": True, "observed": grant["approved"], "passed": grant["approved"] is True},
        {"name": "demo_grant_marker", "expected": "mocksig:customer-grant:approved", "observed": grant["signature"], "passed": grant["signature"] == "mocksig:customer-grant:approved"},
        {"name": "grant_not_before", "expected": f">={grant['issued_at']}", "observed": now, "passed": now >= grant["issued_at"]},
        {"name": "grant_expiry", "expected": f"<{grant['expires_at']}", "observed": now, "passed": now < grant["expires_at"]},
        {"name": "quantity", "expected": grant["quantity"], "observed": offer["quantity"], "passed": offer["quantity"] == grant["quantity"]},
        {"name": "maximum_total", "expected": grant["max_total_usd_cents"], "observed": offer["total_usd_cents"], "passed": offer["total_usd_cents"] <= grant["max_total_usd_cents"]},
        {"name": "grant_unit_consistency", "expected": grant["max_total_usd_cents"] * 10_000, "observed": grant["max_total_usdc_units"], "passed": grant["max_total_usdc_units"] == grant["max_total_usd_cents"] * 10_000},
        {"name": "event", "expected": grant["event"], "observed": offer["event"], "passed": offer["event"] == grant["event"]},
        {"name": "date", "expected": grant["date"], "observed": offer["date"], "passed": offer["date"] == grant["date"]},
        {"name": "venue", "expected": grant["venue"], "observed": offer["venue"], "passed": offer["venue"] == grant["venue"]},
        {"name": "offer_arithmetic", "expected": offer["unit_price_usd_cents"] * offer["quantity"], "observed": offer["total_usd_cents"], "passed": offer["total_usd_cents"] == offer["unit_price_usd_cents"] * offer["quantity"]},
        {"name": "seat_count", "expected": offer["quantity"], "observed": len(offer["seats"]), "passed": len(offer["seats"]) == offer["quantity"]},
        {"name": "adjacent_seats", "expected": grant["adjacent"], "observed": offer["seats"], "passed": (not grant["adjacent"] and offer["adjacent"] is False) or (grant["adjacent"] is True and offer["adjacent"] is True and _seats_are_adjacent(offer["seats"], offer["quantity"]))},
        {"name": "seller", "expected": grant["seller_id"], "observed": offer["seller_id"], "passed": offer["seller_id"] == grant["seller_id"]},
        {"name": "payout_beneficiary", "expected": grant["seller_id"], "observed": quote["beneficiary_id"], "passed": quote["beneficiary_id"] == grant["seller_id"]},
        {"name": "source_asset", "expected": "USDC", "observed": quote["source_asset"], "passed": quote["source_asset"] == "USDC"},
        {"name": "source_amount", "expected": offer["total_usd_cents"] * 10_000, "observed": quote["source_usdc_units"], "passed": quote["source_usdc_units"] == offer["total_usd_cents"] * 10_000},
        {"name": "source_within_grant", "expected": f"<={grant['max_total_usdc_units']}", "observed": quote["source_usdc_units"], "passed": quote["source_usdc_units"] <= grant["max_total_usdc_units"]},
        {"name": "merchant_net", "expected": offer["total_usd_cents"], "observed": quote["merchant_net_usd_cents"], "passed": quote["merchant_net_usd_cents"] == offer["total_usd_cents"]},
        {"name": "destination_asset", "expected": "USD", "observed": quote["destination_asset"], "passed": quote["destination_asset"] == "USD"},
        {"name": "demo_fee", "expected": 0, "observed": quote["fee_usdc_units"], "passed": quote["fee_usdc_units"] == 0},
        {"name": "quote_not_before", "expected": f">={quote['issued_at']}", "observed": now, "passed": now >= quote["issued_at"]},
        {"name": "quote_expiry", "expected": f"<{quote['expires_at']}", "observed": now, "passed": now < quote["expires_at"]},
    )
    failed = [check["name"] for check in checks if not check["passed"]]
    if failed:
        return PolicyDecision(False, checks, "Blocked: " + ", ".join(failed) + " did not match the grant.")
    return PolicyDecision(True, checks, "All configured grant, offer, and quote checks passed.")
