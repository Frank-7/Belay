"""Read-only bridge from the purchase simulator to Recovery Desk evidence.

One simulation run contains one mission. Its run ID names that mission; the
grant digest binds the exact mission terms. No simulated chain ID is invented.
"""

from recovery_app.purchase import PurchaseIntent, blocked_finding, canonical, digest
from recovery_app.purchase import investigate as investigate_evidence


def intent_from_state(state):
    raw = state["intent"]
    quote = state["fx_quote"]
    expected = {
        "schema": "belay.settlement-intent.v0.3-demo",
        "operation_id": state["operation_id"], "order_id": state["order_id"],
        "grant_digest": digest(state["grant"]), "offer_digest": digest(state["offer"]),
        "quote_digest": digest(quote), "quantity": state["offer"]["quantity"],
        "beneficiary_id": quote["beneficiary_id"],
        "source_asset": "USDC", "destination_asset": "USD",
        "source_usdc_units": quote["source_usdc_units"],
        "net_usd_cents": quote["merchant_net_usd_cents"],
    }
    if (canonical(raw) != canonical(expected) or quote["source_asset"] != "USDC"
            or quote["destination_asset"] != "USD"
            or canonical(quote["merchant_net_usd_cents"]) != canonical(state["offer"]["total_usd_cents"])):
        raise ValueError("Saved intent no longer matches the mission, order and quote")
    return PurchaseIntent(
        run_id=state["id"], revision=state["revision"], mission_id=state["id"],
        order_id=state["order_id"], operation_id=state["operation_id"],
        grant_digest=raw["grant_digest"], beneficiary_id=raw["beneficiary_id"],
        source_usdc_units=raw["source_usdc_units"], net_usd_cents=raw["net_usd_cents"],
        intent_json=canonical(raw),
    )


def investigate(state, lookup):
    """Call only lookup. The returned finding is never an execution token."""
    try:
        intent = intent_from_state(state)
    except (KeyError, ValueError, TypeError, OverflowError, RecursionError):
        return blocked_finding(state.get("id"), state.get("revision"),
                               "The saved purchase intent is incomplete or inconsistent. No payout is authorized.")
    try:
        record = lookup(intent.operation_id)
    except Exception:
        return investigate_evidence(intent, None, unavailable=True)
    return investigate_evidence(intent, record)
