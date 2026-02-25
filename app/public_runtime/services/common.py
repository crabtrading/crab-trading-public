from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...state import AgentAccount, STATE

_SIM_STARTING_BALANCE = 2000.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_agent_uuid(identifier: str) -> str:
    raw = str(identifier or "").strip()
    if not raw:
        return ""
    out = STATE.resolve_agent_uuid(raw)
    return str(out or "").strip()


def _is_crypto_symbol(symbol: str) -> bool:
    s = str(symbol or "").strip().upper()
    if not s:
        return False
    quote_symbols = ("USDT", "USDC", "USD", "BTC", "ETH")
    base_symbols = {
        "BTC",
        "ETH",
        "SOL",
        "DOGE",
        "LTC",
        "BNB",
        "XRP",
        "ADA",
        "AVAX",
        "DOT",
        "MATIC",
        "LINK",
        "BCH",
        "ETC",
        "UNI",
        "ATOM",
        "TRX",
        "SHIB",
        "PEPE",
        "ARB",
        "OP",
        "NEAR",
    }
    if s in base_symbols:
        return True
    for quote in quote_symbols:
        if s.endswith(quote):
            base = s[: -len(quote)]
            if base in base_symbols:
                return True
    return False


def valuation_for_account(account: AgentAccount) -> dict[str, float]:
    stock_value = 0.0
    crypto_value = 0.0
    for symbol, qty in account.positions.items():
        px = float(STATE.stock_prices.get(str(symbol).upper(), 0.0) or 0.0)
        value = float(qty or 0.0) * px
        if _is_crypto_symbol(symbol):
            crypto_value += value
        else:
            stock_value += value

    poly_value = 0.0
    for market_id, outcomes in account.poly_positions.items():
        market = STATE.poly_markets.get(str(market_id), {})
        if bool(market.get("resolved")):
            continue
        market_outcomes = market.get("outcomes", {})
        if not isinstance(outcomes, dict):
            continue
        for outcome, shares in outcomes.items():
            odds = market_outcomes.get(outcome)
            if isinstance(odds, (int, float)) and float(odds) > 0:
                poly_value += float(shares) * float(odds)

    equity = float(account.cash) + float(stock_value) + float(crypto_value) + float(poly_value)
    return_pct = ((equity - _SIM_STARTING_BALANCE) / _SIM_STARTING_BALANCE) * 100.0 if _SIM_STARTING_BALANCE > 0 else 0.0
    return {
        "cash": float(account.cash),
        "stock_market_value": float(stock_value),
        "crypto_market_value": float(crypto_value),
        "poly_market_value": float(poly_value),
        "equity": float(equity),
        "return_pct": float(return_pct),
    }


def follower_count_for_agent(target_uuid: str) -> int:
    target = str(target_uuid or "").strip()
    if not target:
        return 0
    total = 0
    with STATE.lock:
        for entries in STATE.agent_following.values():
            if not isinstance(entries, list):
                continue
            for item in entries:
                if isinstance(item, dict):
                    item_uuid = str(item.get("agent_uuid", "")).strip()
                else:
                    item_uuid = resolve_agent_uuid(str(item))
                if item_uuid == target:
                    total += 1
                    break
    return total


def risk_label_for_return_pct(return_pct: float) -> str:
    value = float(return_pct or 0.0)
    if value >= 25:
        return "Aggressive"
    if value >= 8:
        return "Moderate"
    return "Conservative"


def ensure_account(agent_uuid: str) -> AgentAccount | None:
    with STATE.lock:
        return STATE.accounts.get(str(agent_uuid or "").strip())


def serialize_trade_event(event: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    etype = str(event.get("type", "")).strip().lower()
    if etype not in {"stock_order", "poly_bet", "poly_resolved"}:
        return None
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    actor_uuid = str(event.get("agent_uuid", "")).strip() or resolve_agent_uuid(str(event.get("agent_id", "")))
    base: dict[str, Any] = {
        "id": int(event.get("id", 0) or 0),
        "type": etype,
        "agent_uuid": actor_uuid,
        "agent_id": str(event.get("agent_id", "")).strip(),
        "created_at": str(event.get("created_at", "") or ""),
        "execution_mode": "mock",
    }
    if etype == "stock_order":
        base.update(
            {
                "symbol": str(details.get("symbol", "")).upper(),
                "side": str(details.get("side", "")).upper(),
                "effective_action": str(details.get("effective_action", "")).upper(),
                "qty": float(details.get("qty", 0.0) or 0.0),
                "fill_price": float(details.get("fill_price", 0.0) or 0.0),
                "notional": float(details.get("notional", 0.0) or 0.0),
                "status": "FILLED",
            }
        )
    elif etype == "poly_bet":
        base.update(
            {
                "market_id": str(details.get("market_id", "")),
                "market_label": str(details.get("market_label", "") or details.get("market_id", "")),
                "outcome": str(details.get("outcome", "")).upper(),
                "amount": float(details.get("amount", 0.0) or 0.0),
                "shares": float(details.get("shares", 0.0) or 0.0),
            }
        )
    else:
        realized_gross = float(details.get("realized_gross", details.get("realized_delta", 0.0)) or 0.0)
        base.update(
            {
                "market_id": str(details.get("market_id", "")),
                "winning_outcome": str(details.get("winning_outcome", "")).upper(),
                "payout": float(details.get("payout", 0.0) or 0.0),
                "cost_basis": float(details.get("cost_basis", 0.0) or 0.0),
                "realized_gross": realized_gross,
                "realized_delta": realized_gross,
                "fee_paid_market": float(details.get("fee_paid_market", 0.0) or 0.0),
            }
        )
    return base


def normalize_symbols(symbols: list[str] | None) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in symbols or []:
        item = str(value or "").strip().upper()
        if not item or item in seen:
            continue
        seen.add(item)
        rows.append(item)
    return rows


def clamp_int(value: int, *, low: int, high: int) -> int:
    return max(low, min(high, int(value)))
