from __future__ import annotations

import itertools
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from ...state import STATE
from .common import resolve_agent_uuid, valuation_for_account

_ORDER_SEQ = itertools.count(1)
try:
    _POLY_TAKER_FEE = float(os.getenv("CRAB_POLY_TAKER_FEE", "0.001") or 0.001)
except (TypeError, ValueError):
    _POLY_TAKER_FEE = 0.001
_POLY_TAKER_FEE = max(0.0, min(0.05, _POLY_TAKER_FEE))

try:
    _POLY_SLIPPAGE = float(os.getenv("CRAB_POLY_SLIPPAGE", "0.003") or 0.003)
except (TypeError, ValueError):
    _POLY_SLIPPAGE = 0.003
_POLY_SLIPPAGE = max(0.0, min(0.2, _POLY_SLIPPAGE))

try:
    _KALSHI_TAKER_FEE = float(os.getenv("CRAB_KALSHI_TAKER_FEE", "0.001") or 0.001)
except (TypeError, ValueError):
    _KALSHI_TAKER_FEE = 0.001
_KALSHI_TAKER_FEE = max(0.0, min(0.05, _KALSHI_TAKER_FEE))

try:
    _KALSHI_SLIPPAGE = float(os.getenv("CRAB_KALSHI_SLIPPAGE", "0.003") or 0.003)
except (TypeError, ValueError):
    _KALSHI_SLIPPAGE = 0.003
_KALSHI_SLIPPAGE = max(0.0, min(0.2, _KALSHI_SLIPPAGE))


def _synthetic_price(symbol: str) -> float:
    s = str(symbol or "").strip().upper()
    if not s:
        raise HTTPException(status_code=400, detail="invalid_symbol")
    with STATE.lock:
        cached = float(STATE.stock_prices.get(s, 0.0) or 0.0)
        if cached > 0:
            return cached
        seed = sum((idx + 1) * ord(ch) for idx, ch in enumerate(s))
        px = round(5.0 + (seed % 6000) / 20.0, 4)
        STATE.stock_prices[s] = px
        STATE.save_runtime_state()
        return px


def get_quote(symbol: str) -> dict[str, Any]:
    s = str(symbol or "").strip().upper()
    if not s:
        raise HTTPException(status_code=400, detail="invalid_symbol")
    with STATE.lock:
        had_cache = float(STATE.stock_prices.get(s, 0.0) or 0.0) > 0
    price = _synthetic_price(s)
    return {
        "execution_mode": "mock",
        "symbol": s,
        "price": float(price),
        "source": "cache" if had_cache else "synthetic",
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


def _next_order_id() -> str:
    return f"MOCK-{next(_ORDER_SEQ):08d}"


def place_market_order(*, agent_uuid: str, symbol: str, side: str, qty: float) -> dict[str, Any]:
    resolved_uuid = resolve_agent_uuid(agent_uuid)
    if not resolved_uuid:
        raise HTTPException(status_code=404, detail="agent_not_found")
    safe_symbol = str(symbol or "").strip().upper()
    safe_qty = float(qty or 0.0)
    if not safe_symbol or safe_qty <= 0:
        raise HTTPException(status_code=400, detail="invalid_order")

    price = float(_synthetic_price(safe_symbol))
    notional = float(price * safe_qty)
    order_id = _next_order_id()

    side_value = str(side or "").strip().upper()
    if side_value not in {"BUY", "SELL"}:
        raise HTTPException(status_code=400, detail="invalid_side")

    with STATE.lock:
        account = STATE.accounts.get(resolved_uuid)
        if not account:
            raise HTTPException(status_code=404, detail="agent_not_found")

        current_qty = float(account.positions.get(safe_symbol, 0.0) or 0.0)
        avg_cost = float(account.avg_cost.get(safe_symbol, price) or price)

        if side_value == "BUY":
            if float(account.cash) < notional:
                raise HTTPException(status_code=400, detail="insufficient_cash")
            account.cash = float(account.cash) - notional
            new_qty = current_qty + safe_qty
            if new_qty > 0:
                new_avg = ((current_qty * avg_cost) + (safe_qty * price)) / new_qty
                account.avg_cost[safe_symbol] = float(new_avg)
                account.positions[safe_symbol] = float(new_qty)
        else:
            if current_qty < safe_qty:
                raise HTTPException(status_code=400, detail="insufficient_position")
            account.cash = float(account.cash) + notional
            new_qty = current_qty - safe_qty
            realized = (price - avg_cost) * safe_qty
            if abs(realized) > 0:
                account.realized_pnl = float(account.realized_pnl) + float(realized)
            if new_qty <= 0:
                account.positions.pop(safe_symbol, None)
                account.avg_cost.pop(safe_symbol, None)
            else:
                account.positions[safe_symbol] = float(new_qty)

        event = STATE.record_operation(
            "stock_order",
            agent_uuid=resolved_uuid,
            details={
                "order_id": order_id,
                "symbol": safe_symbol,
                "side": side_value,
                "qty": safe_qty,
                "fill_price": price,
                "notional": notional,
                "position_effect": "AUTO",
                "effective_action": "BUY_TO_OPEN" if side_value == "BUY" else "SELL_TO_CLOSE",
                "status": "FILLED",
                "execution_mode": "mock",
            },
        )
        STATE.save_runtime_state()

        valuation = valuation_for_account(account)

    return {
        "execution_mode": "mock",
        "order": {
            "order_id": order_id,
            "status": "FILLED",
            "agent_id": account.display_name,
            "agent_uuid": resolved_uuid,
            "avatar": account.avatar,
            "symbol": safe_symbol,
            "side": side_value,
            "qty": safe_qty,
            "fill_price": price,
            "notional": notional,
            "created_at": str(event.get("created_at", "") or datetime.now(timezone.utc).isoformat()),
        },
        "account": {
            "cash": round(float(valuation["cash"]), 4),
            "equity": round(float(valuation["equity"]), 4),
            "return_pct": round(float(valuation["return_pct"]), 6),
        },
    }


def list_order_history(agent_uuid: str, limit: int = 50) -> list[dict[str, Any]]:
    resolved_uuid = resolve_agent_uuid(agent_uuid)
    if not resolved_uuid:
        return []
    rows: list[dict[str, Any]] = []
    with STATE.lock:
        for event in reversed(STATE.activity_log):
            if str(event.get("type", "")).strip().lower() != "stock_order":
                continue
            actor = str(event.get("agent_uuid", "")).strip() or resolve_agent_uuid(str(event.get("agent_id", "")))
            if actor != resolved_uuid:
                continue
            details = event.get("details") if isinstance(event.get("details"), dict) else {}
            rows.append(
                {
                    "order_id": str(details.get("order_id", "") or f"EVENT-{event.get('id', 0)}"),
                    "id": int(event.get("id", 0) or 0),
                    "created_at": str(event.get("created_at", "") or ""),
                    "symbol": str(details.get("symbol", "")).upper(),
                    "side": str(details.get("side", "")).upper(),
                    "qty": float(details.get("qty", 0.0) or 0.0),
                    "fill_price": float(details.get("fill_price", 0.0) or 0.0),
                    "notional": float(details.get("notional", 0.0) or 0.0),
                    "status": str(details.get("status", "FILLED") or "FILLED"),
                    "effective_action": str(details.get("effective_action", "") or ""),
                    "execution_mode": "mock",
                }
            )
            if len(rows) >= max(1, min(int(limit), 200)):
                break
    return rows


def list_open_orders(agent_uuid: str) -> list[dict[str, Any]]:
    # v1 mock execution is market-fill only; open orders are always empty.
    _ = resolve_agent_uuid(agent_uuid)
    return []


def cancel_order(*, agent_uuid: str, order_id: str) -> dict[str, Any]:
    _ = resolve_agent_uuid(agent_uuid)
    return {
        "execution_mode": "mock",
        "order_id": str(order_id or "").strip(),
        "cancelled": False,
        "message": "mock_market_fill_only",
    }


def list_poly_markets() -> list[dict[str, Any]]:
    with STATE.lock:
        rows = [dict(item) for item in STATE.poly_markets.values() if isinstance(item, dict)]
    for row in rows:
        row.setdefault("resolved", False)
        row.setdefault("winning_outcome", "")
        row.setdefault("closed", False)
        row.setdefault("condition_id", "")
        row.setdefault("resolution_source", "")
        row.setdefault("clob_token_ids", [])
        row.setdefault("last_checked_at", "")
        row.setdefault("resolved_at", "")
        row.setdefault("likely_winner", "")
        row.setdefault("settlement_status", "settled" if bool(row.get("resolved")) else "")
    rows.sort(key=lambda item: str(item.get("market_id", "")))
    return rows


def place_poly_bet(*, agent_uuid: str, market_id: str, outcome: str, amount: float) -> dict[str, Any]:
    resolved_uuid = resolve_agent_uuid(agent_uuid)
    if not resolved_uuid:
        raise HTTPException(status_code=404, detail="agent_not_found")

    safe_market_id = str(market_id or "").strip()
    safe_outcome = str(outcome or "").strip().upper()
    safe_amount = float(amount or 0.0)
    if not safe_market_id or not safe_outcome or safe_amount <= 0:
        raise HTTPException(status_code=400, detail="invalid_poly_bet")

    with STATE.lock:
        account = STATE.accounts.get(resolved_uuid)
        market = STATE.poly_markets.get(safe_market_id)
        if not account:
            raise HTTPException(status_code=404, detail="agent_not_found")
        if not isinstance(market, dict):
            raise HTTPException(status_code=404, detail="market_not_found")
        if bool(market.get("resolved")):
            raise HTTPException(status_code=400, detail="market_already_resolved")
        if bool(market.get("closed")):
            raise HTTPException(status_code=400, detail="market_closed")
        outcomes = market.get("outcomes") if isinstance(market.get("outcomes"), dict) else {}
        odds = None
        for key, value in outcomes.items():
            if str(key or "").strip().upper() != safe_outcome:
                continue
            odds = value
            break
        if not isinstance(odds, (int, float)) or float(odds) <= 0:
            raise HTTPException(status_code=400, detail="invalid_outcome")
        effective_price = float(odds) * (1.0 + float(_POLY_SLIPPAGE))
        if effective_price <= 0.0:
            raise HTTPException(status_code=400, detail="invalid_effective_price")
        fee = float(safe_amount) * float(_POLY_TAKER_FEE)
        required_cash = float(safe_amount) + fee
        if float(account.cash) < required_cash:
            raise HTTPException(status_code=400, detail="insufficient_cash")

        shares = float(safe_amount / effective_price)
        account.cash = float(account.cash) - required_cash
        account.cash_locked = max(0.0, float(getattr(account, "cash_locked", 0.0) or 0.0)) + float(safe_amount)
        account.poly_fee_paid = max(0.0, float(getattr(account, "poly_fee_paid", 0.0) or 0.0)) + fee

        if safe_market_id not in account.poly_positions:
            account.poly_positions[safe_market_id] = {}
        if safe_market_id not in account.poly_cost_basis:
            account.poly_cost_basis[safe_market_id] = {}
        if not isinstance(getattr(account, "poly_fee_by_market", None), dict):
            account.poly_fee_by_market = {}

        account.poly_positions[safe_market_id][safe_outcome] = float(account.poly_positions[safe_market_id].get(safe_outcome, 0.0) or 0.0) + shares
        account.poly_cost_basis[safe_market_id][safe_outcome] = float(account.poly_cost_basis[safe_market_id].get(safe_outcome, 0.0) or 0.0) + safe_amount
        account.poly_fee_by_market[safe_market_id] = float(account.poly_fee_by_market.get(safe_market_id, 0.0) or 0.0) + fee

        event = STATE.record_operation(
            "poly_bet",
            agent_uuid=resolved_uuid,
            details={
                "provider": "poly",
                "provider_event_type": "bet",
                "market_id": safe_market_id,
                "market_label": str(market.get("question", "") or safe_market_id),
                "outcome": safe_outcome,
                "amount": safe_amount,
                "shares": shares,
                "quote_price": float(odds),
                "effective_price": effective_price,
                "slippage": float(_POLY_SLIPPAGE),
                "fee": fee,
                "lock_amount": float(safe_amount),
                "execution_mode": "mock",
            },
        )
        STATE.save_runtime_state()

    return {
        "execution_mode": "mock",
        "provider": "poly",
        "bet": {
            "market_id": safe_market_id,
            "outcome": safe_outcome,
            "amount": safe_amount,
            "shares": shares,
            "quote_price": round(float(odds), 6),
            "effective_price": round(effective_price, 6),
            "slippage": round(float(_POLY_SLIPPAGE), 6),
            "fee": round(fee, 6),
            "lock_amount": round(float(safe_amount), 6),
            "status": "ACCEPTED",
            "created_at": str(event.get("created_at", "") or datetime.now(timezone.utc).isoformat()),
        },
    }


def place_poly_sell(*, agent_uuid: str, market_id: str, outcome: str, shares: float) -> dict[str, Any]:
    resolved_uuid = resolve_agent_uuid(agent_uuid)
    if not resolved_uuid:
        raise HTTPException(status_code=404, detail="agent_not_found")

    safe_market_id = str(market_id or "").strip()
    safe_outcome = str(outcome or "").strip().upper()
    safe_shares = float(shares or 0.0)
    if not safe_market_id or not safe_outcome or safe_shares <= 0:
        raise HTTPException(status_code=400, detail="invalid_poly_sell")

    with STATE.lock:
        account = STATE.accounts.get(resolved_uuid)
        market = STATE.poly_markets.get(safe_market_id)
        if not account:
            raise HTTPException(status_code=404, detail="agent_not_found")
        if not isinstance(market, dict):
            raise HTTPException(status_code=404, detail="market_not_found")
        if bool(market.get("resolved")):
            raise HTTPException(status_code=400, detail="market_already_resolved")
        if bool(market.get("closed")):
            raise HTTPException(status_code=400, detail="market_closed")
        outcomes = market.get("outcomes") if isinstance(market.get("outcomes"), dict) else {}
        odds = None
        for key, value in outcomes.items():
            if str(key or "").strip().upper() != safe_outcome:
                continue
            odds = value
            break
        if not isinstance(odds, (int, float)) or float(odds) <= 0:
            raise HTTPException(status_code=400, detail="invalid_outcome")

        market_positions = account.poly_positions.get(safe_market_id, {})
        held_shares = 0.0
        if isinstance(market_positions, dict):
            held_shares = float(market_positions.get(safe_outcome, 0.0) or 0.0)
        if held_shares <= 0.0:
            raise HTTPException(status_code=400, detail="insufficient_poly_position")
        if safe_shares > held_shares + 1e-12:
            raise HTTPException(status_code=400, detail="insufficient_poly_position")
        safe_shares = min(safe_shares, held_shares)

        market_costs = account.poly_cost_basis.get(safe_market_id, {})
        outcome_cost_basis = 0.0
        if isinstance(market_costs, dict):
            outcome_cost_basis = float(market_costs.get(safe_outcome, 0.0) or 0.0)
        if outcome_cost_basis <= 0.0 and held_shares > 0.0:
            total_cost_basis = 0.0
            if isinstance(market_costs, dict):
                for item in market_costs.values():
                    try:
                        total_cost_basis += max(0.0, float(item or 0.0))
                    except Exception:
                        continue
            total_market_shares = 0.0
            if isinstance(market_positions, dict):
                for item in market_positions.values():
                    try:
                        total_market_shares += max(0.0, float(item or 0.0))
                    except Exception:
                        continue
            if total_cost_basis > 0.0 and total_market_shares > 0.0:
                outcome_cost_basis = total_cost_basis * (held_shares / total_market_shares)

        sell_ratio = safe_shares / held_shares if held_shares > 0.0 else 0.0
        released_cost = max(0.0, outcome_cost_basis * sell_ratio)
        effective_price = float(odds) * (1.0 - float(_POLY_SLIPPAGE))
        if effective_price <= 0.0:
            raise HTTPException(status_code=400, detail="invalid_effective_price")
        proceeds = safe_shares * effective_price
        fee = proceeds * float(_POLY_TAKER_FEE)
        realized_gross = proceeds - released_cost

        account.cash = float(account.cash) + proceeds - fee
        account.cash_locked = max(0.0, float(getattr(account, "cash_locked", 0.0) or 0.0) - released_cost)
        account.poly_fee_paid = max(0.0, float(getattr(account, "poly_fee_paid", 0.0) or 0.0)) + fee
        account.poly_realized_pnl = float(getattr(account, "poly_realized_pnl", 0.0) or 0.0) + realized_gross
        if not isinstance(getattr(account, "poly_fee_by_market", None), dict):
            account.poly_fee_by_market = {}
        account.poly_fee_by_market[safe_market_id] = float(account.poly_fee_by_market.get(safe_market_id, 0.0) or 0.0) + fee

        remaining_shares = max(0.0, held_shares - safe_shares)
        remaining_cost = max(0.0, outcome_cost_basis - released_cost)
        if remaining_shares <= 1e-12:
            if isinstance(market_positions, dict):
                market_positions.pop(safe_outcome, None)
        else:
            if not isinstance(market_positions, dict):
                market_positions = {}
                account.poly_positions[safe_market_id] = market_positions
            market_positions[safe_outcome] = remaining_shares

        if not isinstance(market_costs, dict):
            market_costs = {}
            account.poly_cost_basis[safe_market_id] = market_costs
        if remaining_cost <= 1e-12:
            market_costs.pop(safe_outcome, None)
        else:
            market_costs[safe_outcome] = remaining_cost

        if isinstance(market_positions, dict):
            has_position = any(abs(float(item or 0.0)) > 1e-12 for item in market_positions.values())
            if not has_position:
                account.poly_positions.pop(safe_market_id, None)
        if isinstance(market_costs, dict):
            has_cost = any(abs(float(item or 0.0)) > 1e-12 for item in market_costs.values())
            if not has_cost:
                account.poly_cost_basis.pop(safe_market_id, None)

        event = STATE.record_operation(
            "poly_sell",
            agent_uuid=resolved_uuid,
            details={
                "provider": "poly",
                "provider_event_type": "sell",
                "market_id": safe_market_id,
                "market_label": str(market.get("question", "") or safe_market_id),
                "outcome": safe_outcome,
                "amount": proceeds,
                "shares": safe_shares,
                "quote_price": float(odds),
                "effective_price": effective_price,
                "slippage": float(_POLY_SLIPPAGE),
                "fee": fee,
                "lock_amount": released_cost,
                "released_cost": released_cost,
                "realized_gross": realized_gross,
                "held_shares_before": held_shares,
                "remaining_shares": remaining_shares,
                "execution_mode": "mock",
            },
        )
        STATE.save_runtime_state()

    return {
        "execution_mode": "mock",
        "provider": "poly",
        "sell": {
            "market_id": safe_market_id,
            "outcome": safe_outcome,
            "shares": safe_shares,
            "quote_price": round(float(odds), 6),
            "effective_price": round(effective_price, 6),
            "slippage": round(float(_POLY_SLIPPAGE), 6),
            "proceeds": round(proceeds, 6),
            "fee": round(fee, 6),
            "released_cost": round(released_cost, 6),
            "lock_released": round(released_cost, 6),
            "realized_gross": round(realized_gross, 6),
            "status": "ACCEPTED",
            "created_at": str(event.get("created_at", "") or datetime.now(timezone.utc).isoformat()),
        },
    }


def _kalshi_market_key(raw_market_id: str) -> str:
    raw = str(raw_market_id or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith("kalshi:"):
        return raw
    return f"kalshi:{raw.upper()}"


def _resolve_kalshi_market_unlocked(raw_market_input: str) -> tuple[str, dict[str, Any] | None]:
    raw = str(raw_market_input or "").strip()
    if not raw:
        return "", None
    if raw in STATE.kalshi_markets:
        market = STATE.kalshi_markets.get(raw)
        return raw, dict(market) if isinstance(market, dict) else None
    key = _kalshi_market_key(raw)
    if key in STATE.kalshi_markets:
        market = STATE.kalshi_markets.get(key)
        return key, dict(market) if isinstance(market, dict) else None
    ticker = raw.upper()
    for market_id, market in STATE.kalshi_markets.items():
        if not isinstance(market, dict):
            continue
        if str(market.get("ticker", "")).strip().upper() != ticker:
            continue
        return str(market_id), dict(market)
    return key, None


def list_kalshi_markets() -> list[dict[str, Any]]:
    with STATE.lock:
        rows = [dict(item) for item in STATE.kalshi_markets.values() if isinstance(item, dict)]
    for row in rows:
        row.setdefault("status", "open")
        row.setdefault("resolved", False)
        row.setdefault("winning_outcome", "")
        row.setdefault("closed", False)
        row.setdefault("resolution_source", "")
        row.setdefault("last_checked_at", "")
        row.setdefault("resolved_at", "")
        row.setdefault("settlement_status", "settled" if bool(row.get("resolved")) else "")
    rows.sort(key=lambda item: str(item.get("market_id", "")))
    return rows


def place_kalshi_bet(*, agent_uuid: str, market_id: str, outcome: str, amount: float) -> dict[str, Any]:
    resolved_uuid = resolve_agent_uuid(agent_uuid)
    if not resolved_uuid:
        raise HTTPException(status_code=404, detail="agent_not_found")

    safe_market_input = str(market_id or "").strip()
    safe_outcome = str(outcome or "").strip().upper()
    safe_amount = float(amount or 0.0)
    if not safe_market_input or safe_outcome not in {"YES", "NO"} or safe_amount <= 0:
        raise HTTPException(status_code=400, detail="invalid_kalshi_bet")

    with STATE.lock:
        account = STATE.accounts.get(resolved_uuid)
        safe_market_id, market = _resolve_kalshi_market_unlocked(safe_market_input)
        if not account:
            raise HTTPException(status_code=404, detail="agent_not_found")
        if not isinstance(market, dict):
            raise HTTPException(status_code=404, detail="market_not_found")
        if bool(market.get("resolved")):
            raise HTTPException(status_code=400, detail="market_already_resolved")
        if bool(market.get("closed")) or str(market.get("status", "")).strip().lower() in {"closed", "settled"}:
            raise HTTPException(status_code=400, detail="market_closed")

        outcomes = market.get("outcomes") if isinstance(market.get("outcomes"), dict) else {}
        odds = outcomes.get(safe_outcome)
        if not isinstance(odds, (int, float)) or float(odds) <= 0:
            raise HTTPException(status_code=400, detail="invalid_outcome")
        effective_price = float(odds) * (1.0 + float(_KALSHI_SLIPPAGE))
        if effective_price <= 0.0:
            raise HTTPException(status_code=400, detail="invalid_effective_price")
        fee = float(safe_amount) * float(_KALSHI_TAKER_FEE)
        required_cash = float(safe_amount) + fee
        if float(account.cash) < required_cash:
            raise HTTPException(status_code=400, detail="insufficient_cash")

        shares = float(safe_amount / effective_price)
        account.cash = float(account.cash) - required_cash
        account.cash_locked = max(0.0, float(getattr(account, "cash_locked", 0.0) or 0.0)) + float(safe_amount)
        account.kalshi_fee_paid = max(0.0, float(getattr(account, "kalshi_fee_paid", 0.0) or 0.0)) + fee

        if not isinstance(getattr(account, "kalshi_positions", None), dict):
            account.kalshi_positions = {}
        if not isinstance(getattr(account, "kalshi_cost_basis", None), dict):
            account.kalshi_cost_basis = {}
        if not isinstance(getattr(account, "kalshi_fee_by_market", None), dict):
            account.kalshi_fee_by_market = {}
        if safe_market_id not in account.kalshi_positions:
            account.kalshi_positions[safe_market_id] = {}
        if safe_market_id not in account.kalshi_cost_basis:
            account.kalshi_cost_basis[safe_market_id] = {}

        account.kalshi_positions[safe_market_id][safe_outcome] = float(account.kalshi_positions[safe_market_id].get(safe_outcome, 0.0) or 0.0) + shares
        account.kalshi_cost_basis[safe_market_id][safe_outcome] = float(account.kalshi_cost_basis[safe_market_id].get(safe_outcome, 0.0) or 0.0) + safe_amount
        account.kalshi_fee_by_market[safe_market_id] = float(account.kalshi_fee_by_market.get(safe_market_id, 0.0) or 0.0) + fee

        ticker = str(market.get("ticker", "") or safe_market_id).strip().upper()
        event = STATE.record_operation(
            "poly_bet",
            agent_uuid=resolved_uuid,
            details={
                "provider": "kalshi",
                "provider_event_type": "bet",
                "ticker": ticker,
                "market_id": safe_market_id,
                "market_label": str(market.get("question", "") or safe_market_id),
                "outcome": safe_outcome,
                "amount": safe_amount,
                "shares": shares,
                "quote_price": float(odds),
                "effective_price": effective_price,
                "slippage": float(_KALSHI_SLIPPAGE),
                "fee": fee,
                "lock_amount": float(safe_amount),
                "execution_mode": "mock",
            },
        )
        STATE.save_runtime_state()

    return {
        "execution_mode": "mock",
        "provider": "kalshi",
        "bet": {
            "ticker": ticker,
            "market_id": safe_market_id,
            "outcome": safe_outcome,
            "amount": safe_amount,
            "shares": shares,
            "quote_price": round(float(odds), 6),
            "effective_price": round(effective_price, 6),
            "slippage": round(float(_KALSHI_SLIPPAGE), 6),
            "fee": round(fee, 6),
            "lock_amount": round(float(safe_amount), 6),
            "status": "ACCEPTED",
            "created_at": str(event.get("created_at", "") or datetime.now(timezone.utc).isoformat()),
        },
    }


def place_kalshi_sell(*, agent_uuid: str, market_id: str, outcome: str, shares: float) -> dict[str, Any]:
    resolved_uuid = resolve_agent_uuid(agent_uuid)
    if not resolved_uuid:
        raise HTTPException(status_code=404, detail="agent_not_found")

    safe_market_input = str(market_id or "").strip()
    safe_outcome = str(outcome or "").strip().upper()
    safe_shares = float(shares or 0.0)
    if not safe_market_input or safe_outcome not in {"YES", "NO"} or safe_shares <= 0:
        raise HTTPException(status_code=400, detail="invalid_kalshi_sell")

    with STATE.lock:
        account = STATE.accounts.get(resolved_uuid)
        safe_market_id, market = _resolve_kalshi_market_unlocked(safe_market_input)
        if not account:
            raise HTTPException(status_code=404, detail="agent_not_found")
        if not isinstance(market, dict):
            raise HTTPException(status_code=404, detail="market_not_found")
        if bool(market.get("resolved")):
            raise HTTPException(status_code=400, detail="market_already_resolved")
        if bool(market.get("closed")) or str(market.get("status", "")).strip().lower() in {"closed", "settled"}:
            raise HTTPException(status_code=400, detail="market_closed")

        outcomes = market.get("outcomes") if isinstance(market.get("outcomes"), dict) else {}
        odds = outcomes.get(safe_outcome)
        if not isinstance(odds, (int, float)) or float(odds) <= 0:
            raise HTTPException(status_code=400, detail="invalid_outcome")

        market_positions = account.kalshi_positions.get(safe_market_id, {}) if isinstance(getattr(account, "kalshi_positions", None), dict) else {}
        held_shares = float(market_positions.get(safe_outcome, 0.0) or 0.0) if isinstance(market_positions, dict) else 0.0
        if held_shares <= 0.0:
            raise HTTPException(status_code=400, detail="insufficient_kalshi_position")
        if safe_shares > held_shares + 1e-12:
            raise HTTPException(status_code=400, detail="insufficient_kalshi_position")
        safe_shares = min(safe_shares, held_shares)

        market_costs = account.kalshi_cost_basis.get(safe_market_id, {}) if isinstance(getattr(account, "kalshi_cost_basis", None), dict) else {}
        outcome_cost_basis = float(market_costs.get(safe_outcome, 0.0) or 0.0) if isinstance(market_costs, dict) else 0.0
        if outcome_cost_basis <= 0.0 and held_shares > 0.0:
            total_cost_basis = 0.0
            if isinstance(market_costs, dict):
                for item in market_costs.values():
                    try:
                        total_cost_basis += max(0.0, float(item or 0.0))
                    except Exception:
                        continue
            total_market_shares = 0.0
            if isinstance(market_positions, dict):
                for item in market_positions.values():
                    try:
                        total_market_shares += max(0.0, float(item or 0.0))
                    except Exception:
                        continue
            if total_cost_basis > 0.0 and total_market_shares > 0.0:
                outcome_cost_basis = total_cost_basis * (held_shares / total_market_shares)

        sell_ratio = safe_shares / held_shares if held_shares > 0.0 else 0.0
        released_cost = max(0.0, outcome_cost_basis * sell_ratio)
        effective_price = float(odds) * (1.0 - float(_KALSHI_SLIPPAGE))
        if effective_price <= 0.0:
            raise HTTPException(status_code=400, detail="invalid_effective_price")
        proceeds = safe_shares * effective_price
        fee = proceeds * float(_KALSHI_TAKER_FEE)
        realized_gross = proceeds - released_cost

        account.cash = float(account.cash) + proceeds - fee
        account.cash_locked = max(0.0, float(getattr(account, "cash_locked", 0.0) or 0.0) - released_cost)
        account.kalshi_fee_paid = max(0.0, float(getattr(account, "kalshi_fee_paid", 0.0) or 0.0)) + fee
        account.kalshi_realized_pnl = float(getattr(account, "kalshi_realized_pnl", 0.0) or 0.0) + realized_gross
        if not isinstance(getattr(account, "kalshi_fee_by_market", None), dict):
            account.kalshi_fee_by_market = {}
        account.kalshi_fee_by_market[safe_market_id] = float(account.kalshi_fee_by_market.get(safe_market_id, 0.0) or 0.0) + fee

        remaining_shares = max(0.0, held_shares - safe_shares)
        remaining_cost = max(0.0, outcome_cost_basis - released_cost)
        if remaining_shares <= 1e-12:
            if isinstance(market_positions, dict):
                market_positions.pop(safe_outcome, None)
        else:
            if not isinstance(market_positions, dict):
                market_positions = {}
                account.kalshi_positions[safe_market_id] = market_positions
            market_positions[safe_outcome] = remaining_shares

        if not isinstance(market_costs, dict):
            market_costs = {}
            account.kalshi_cost_basis[safe_market_id] = market_costs
        if remaining_cost <= 1e-12:
            market_costs.pop(safe_outcome, None)
        else:
            market_costs[safe_outcome] = remaining_cost

        if isinstance(market_positions, dict):
            has_position = any(abs(float(item or 0.0)) > 1e-12 for item in market_positions.values())
            if not has_position:
                account.kalshi_positions.pop(safe_market_id, None)
        if isinstance(market_costs, dict):
            has_cost = any(abs(float(item or 0.0)) > 1e-12 for item in market_costs.values())
            if not has_cost:
                account.kalshi_cost_basis.pop(safe_market_id, None)

        ticker = str(market.get("ticker", "") or safe_market_id).strip().upper()
        event = STATE.record_operation(
            "poly_sell",
            agent_uuid=resolved_uuid,
            details={
                "provider": "kalshi",
                "provider_event_type": "sell",
                "ticker": ticker,
                "market_id": safe_market_id,
                "market_label": str(market.get("question", "") or safe_market_id),
                "outcome": safe_outcome,
                "amount": proceeds,
                "shares": safe_shares,
                "quote_price": float(odds),
                "effective_price": effective_price,
                "slippage": float(_KALSHI_SLIPPAGE),
                "fee": fee,
                "lock_amount": released_cost,
                "released_cost": released_cost,
                "realized_gross": realized_gross,
                "held_shares_before": held_shares,
                "remaining_shares": remaining_shares,
                "execution_mode": "mock",
            },
        )
        STATE.save_runtime_state()

    return {
        "execution_mode": "mock",
        "provider": "kalshi",
        "sell": {
            "ticker": ticker,
            "market_id": safe_market_id,
            "outcome": safe_outcome,
            "shares": safe_shares,
            "quote_price": round(float(odds), 6),
            "effective_price": round(effective_price, 6),
            "slippage": round(float(_KALSHI_SLIPPAGE), 6),
            "proceeds": round(proceeds, 6),
            "fee": round(fee, 6),
            "released_cost": round(released_cost, 6),
            "lock_released": round(released_cost, 6),
            "realized_gross": round(realized_gross, 6),
            "status": "ACCEPTED",
            "created_at": str(event.get("created_at", "") or datetime.now(timezone.utc).isoformat()),
        },
    }
