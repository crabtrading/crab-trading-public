from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import require_agent
from ..models import AgentRegisterRequest
from ..state import AgentAccount, STATE


sim_router = APIRouter(tags=["public-sim"])

_AGENT_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{3,64}$")
_SIM_STARTING_BALANCE = 2000.0


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


def _valuation_for_account(account: AgentAccount) -> dict:
    stock_value = 0.0
    crypto_value = 0.0
    for symbol, qty in account.positions.items():
        px = float(STATE.stock_prices.get(str(symbol).upper(), 0.0) or 0.0)
        market_value = float(qty or 0.0) * px
        if _is_crypto_symbol(symbol):
            crypto_value += market_value
        else:
            stock_value += market_value

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


def _resolve_agent_uuid(identifier: str) -> str:
    raw = str(identifier or "").strip()
    if not raw:
        return ""
    out = STATE.resolve_agent_uuid(raw)
    return str(out or "").strip()


def _serialize_trade_event(event: dict) -> dict | None:
    if not isinstance(event, dict):
        return None
    etype = str(event.get("type", "")).strip().lower()
    if etype not in {"stock_order", "poly_bet", "poly_resolved"}:
        return None
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    actor_uuid = str(event.get("agent_uuid", "")).strip() or _resolve_agent_uuid(str(event.get("agent_id", "")))
    base = {
        "id": int(event.get("id", 0) or 0),
        "type": etype,
        "agent_uuid": actor_uuid,
        "agent_id": str(event.get("agent_id", "")).strip(),
        "created_at": str(event.get("created_at", "") or ""),
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
    elif etype == "poly_resolved":
        base.update(
            {
                "market_id": str(details.get("market_id", "")),
                "winning_outcome": str(details.get("winning_outcome", "")).upper(),
                "payout": float(details.get("payout", 0.0) or 0.0),
                "cost_basis": float(details.get("cost_basis", 0.0) or 0.0),
                "realized_delta": float(details.get("realized_delta", 0.0) or 0.0),
            }
        )
    return base


@sim_router.post("/api/v1/agents/register")
def register_agent(req: AgentRegisterRequest, request: Request) -> dict:
    name = str(req.name or "").strip()
    if not _AGENT_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=400, detail="invalid_agent_id")

    with STATE.lock:
        if STATE.resolve_agent_uuid(name):
            raise HTTPException(status_code=409, detail="agent_already_exists")

        agent_uuid = str(uuid4())
        while agent_uuid in STATE.accounts:
            agent_uuid = str(uuid4())

        api_key = secrets.token_urlsafe(30)
        while api_key in STATE.key_to_agent:
            api_key = secrets.token_urlsafe(30)

        account = AgentAccount(
            agent_uuid=agent_uuid,
            display_name=name,
            cash=float(_SIM_STARTING_BALANCE),
            description=str(req.description or "").strip(),
            registered_at=datetime.now(timezone.utc).isoformat(),
            registration_ip=str(request.client.host if request.client else ""),
            registration_source="public_api",
        )
        STATE.accounts[agent_uuid] = account
        STATE.agent_name_to_uuid[name] = agent_uuid
        STATE.agent_keys[agent_uuid] = api_key
        STATE.key_to_agent[api_key] = agent_uuid
        STATE.record_operation(
            "agent_registered",
            agent_uuid=agent_uuid,
            details={"source": "public_main"},
            agent_id=name,
        )
        STATE.save_runtime_state()

    return {
        "agent": {
            "name": name,
            "uuid": agent_uuid,
            "api_key": api_key,
            "claim_url": "",
            "verification_code": "",
            "tweet_template": "",
        },
        "important": "SAVE YOUR API KEY",
    }


@sim_router.get("/web/sim/account")
def get_sim_account(agent_uuid: str = Depends(require_agent)) -> dict:
    with STATE.lock:
        account = STATE.accounts.get(agent_uuid)
        if not account:
            raise HTTPException(status_code=404, detail="agent_not_found")
        valuation = _valuation_for_account(account)
        return {
            "agent_id": account.display_name,
            "agent_uuid": agent_uuid,
            "avatar": account.avatar,
            "cash": round(float(valuation["cash"]), 4),
            "stock_positions": account.positions,
            "stock_realized_pnl": round(float(account.realized_pnl), 4),
            "stock_market_value": round(float(valuation["stock_market_value"]), 4),
            "crypto_market_value": round(float(valuation["crypto_market_value"]), 4),
            "poly_positions": account.poly_positions,
            "poly_realized_pnl": round(float(account.poly_realized_pnl), 4),
            "poly_market_value": round(float(valuation["poly_market_value"]), 4),
            "equity_estimate": round(float(valuation["equity"]), 4),
        }


@sim_router.get("/web/sim/leaderboard")
def get_sim_leaderboard(limit: int = 20) -> dict:
    safe_limit = max(1, min(int(limit), 200))
    with STATE.lock:
        rows = []
        for account in STATE.accounts.values():
            valuation = _valuation_for_account(account)
            rows.append(
                {
                    "agent_id": account.display_name,
                    "agent_uuid": account.agent_uuid,
                    "avatar": account.avatar,
                    "cash": round(float(valuation["cash"]), 4),
                    "stock_market_value": round(float(valuation["stock_market_value"]), 4),
                    "crypto_market_value": round(float(valuation["crypto_market_value"]), 4),
                    "poly_market_value": round(float(valuation["poly_market_value"]), 4),
                    "balance": round(float(valuation["equity"]), 4),
                    "return_pct": round(float(valuation["return_pct"]), 6),
                }
            )
        rows.sort(key=lambda item: float(item.get("balance", 0.0)), reverse=True)
        for idx, row in enumerate(rows, start=1):
            row["rank"] = idx
            row["rank_badge"] = "TOP 3" if idx <= 3 else ""
    return {
        "leaderboard": rows[:safe_limit],
        "total": len(rows),
        "active_total": len(rows),
        "limit": safe_limit,
        "max_limit": 200,
    }


@sim_router.get("/web/sim/agents/{agent_id}/recent-trades")
def get_recent_trades(agent_id: str, limit: int = 10) -> dict:
    safe_limit = max(1, min(int(limit), 200))
    target = _resolve_agent_uuid(agent_id)
    if not target:
        raise HTTPException(status_code=404, detail="agent_not_found")

    with STATE.lock:
        account = STATE.accounts.get(target)
        if not account:
            raise HTTPException(status_code=404, detail="agent_not_found")
        valuation = _valuation_for_account(account)
        rows = []
        for event in reversed(STATE.activity_log):
            actor = str(event.get("agent_uuid", "")).strip() or _resolve_agent_uuid(str(event.get("agent_id", "")))
            if actor != target:
                continue
            trade = _serialize_trade_event(event)
            if trade is None:
                continue
            rows.append(trade)
            if len(rows) >= safe_limit:
                break

    return {
        "agent_id": account.display_name,
        "agent_uuid": target,
        "avatar": account.avatar,
        "profile": {
            "agent_id": account.display_name,
            "agent_uuid": target,
            "avatar": account.avatar,
            "description": str(account.description or ""),
        },
        "account": {
            "cash": round(float(valuation["cash"]), 4),
            "stock_market_value": round(float(valuation["stock_market_value"]), 4),
            "crypto_market_value": round(float(valuation["crypto_market_value"]), 4),
            "poly_market_value": round(float(valuation["poly_market_value"]), 4),
            "balance": round(float(valuation["equity"]), 4),
            "return_pct": round(float(valuation["return_pct"]), 6),
            "realized_gain": round(float(account.realized_pnl) + float(account.poly_realized_pnl), 4),
            "stock_realized_pnl": round(float(account.realized_pnl), 4),
            "poly_realized_pnl": round(float(account.poly_realized_pnl), 4),
        },
        "trades": rows,
        "total": len(rows),
        "limit": safe_limit,
        "max_limit": 200,
    }
