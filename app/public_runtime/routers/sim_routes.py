from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...auth import require_agent
from ...state import STATE
from ..schemas.sim import Side, SimOrderCreateRequest, SimPolyBetCreateRequest, SimPolySellCreateRequest
from ..services.common import resolve_agent_uuid, serialize_trade_event, valuation_for_account
from ..services.discovery_rank import leaderboard_rows
from ..services import mock_broker

router = APIRouter(prefix="/api/v1/public", tags=["public-sim"])


@router.get("/sim/account")
def get_sim_account(agent_uuid: str = Depends(require_agent)) -> dict:
    with STATE.lock:
        account = STATE.accounts.get(agent_uuid)
        if not account:
            raise HTTPException(status_code=404, detail="agent_not_found")
        valuation = valuation_for_account(account)
        cash_available = float(valuation["cash"])
        cash_locked = max(0.0, float(getattr(account, "cash_locked", 0.0) or 0.0))
        cash_total = cash_available + cash_locked
        return {
            "status": "ok",
            "execution_mode": "mock",
            "agent_id": account.display_name,
            "agent_uuid": account.agent_uuid,
            "avatar": account.avatar,
            "cash": round(cash_available, 4),
            "cash_available": round(cash_available, 4),
            "cash_locked": round(cash_locked, 4),
            "cash_total": round(cash_total, 4),
            "stock_positions": dict(account.positions),
            "stock_realized_pnl": round(float(account.realized_pnl), 4),
            "stock_market_value": round(float(valuation["stock_market_value"]), 4),
            "crypto_market_value": round(float(valuation["crypto_market_value"]), 4),
            "poly_positions": dict(account.poly_positions),
            "poly_fee_paid": round(float(getattr(account, "poly_fee_paid", 0.0) or 0.0), 4),
            "poly_realized_pnl": round(float(account.poly_realized_pnl), 4),
            "poly_market_value": round(float(valuation["poly_market_value"]), 4),
            "equity_estimate": round(float(valuation["equity"]), 4),
            "return_pct": round(float(valuation["return_pct"]), 6),
        }


@router.get("/sim/quote")
def get_sim_quote(symbol: str, agent_uuid: str = Depends(require_agent)) -> dict:
    payload = mock_broker.get_quote(symbol)
    payload["agent_uuid"] = agent_uuid
    payload["agent_id"] = STATE.display_name_for(agent_uuid)
    return payload


@router.post("/sim/orders")
def create_sim_order(req: SimOrderCreateRequest, agent_uuid: str = Depends(require_agent)) -> dict:
    side = Side(str(req.side.value).upper())
    return mock_broker.place_market_order(
        agent_uuid=agent_uuid,
        symbol=req.symbol,
        side=side.value,
        qty=float(req.qty),
    )


@router.delete("/sim/orders/{order_id}")
def cancel_sim_order(order_id: str, agent_uuid: str = Depends(require_agent)) -> dict:
    return mock_broker.cancel_order(agent_uuid=agent_uuid, order_id=order_id)


@router.get("/sim/open-orders")
def get_open_orders(agent_uuid: str = Depends(require_agent)) -> dict:
    rows = mock_broker.list_open_orders(agent_uuid=agent_uuid)
    return {
        "status": "ok",
        "execution_mode": "mock",
        "agent_uuid": agent_uuid,
        "agent_id": STATE.display_name_for(agent_uuid),
        "orders": rows,
        "total": len(rows),
    }


@router.get("/sim/orders")
def get_orders(limit: int = 50, agent_uuid: str = Depends(require_agent)) -> dict:
    safe_limit = max(1, min(int(limit), 200))
    rows = mock_broker.list_order_history(agent_uuid=agent_uuid, limit=safe_limit)
    return {
        "status": "ok",
        "execution_mode": "mock",
        "agent_uuid": agent_uuid,
        "agent_id": STATE.display_name_for(agent_uuid),
        "orders": rows,
        "total": len(rows),
        "limit": safe_limit,
    }


@router.get("/sim/positions")
def get_positions(agent_uuid: str = Depends(require_agent)) -> dict:
    with STATE.lock:
        account = STATE.accounts.get(agent_uuid)
        if not account:
            raise HTTPException(status_code=404, detail="agent_not_found")
        rows = []
        for symbol, qty in account.positions.items():
            px = float(STATE.stock_prices.get(str(symbol).upper(), 0.0) or 0.0)
            rows.append(
                {
                    "symbol": str(symbol).upper(),
                    "qty": float(qty),
                    "last_price": px,
                    "market_value": round(float(qty) * px, 4),
                    "execution_mode": "mock",
                }
            )

    rows.sort(key=lambda item: str(item.get("symbol", "")))
    return {
        "status": "ok",
        "execution_mode": "mock",
        "agent_uuid": agent_uuid,
        "agent_id": STATE.display_name_for(agent_uuid),
        "positions": rows,
        "total": len(rows),
    }


@router.get("/sim/leaderboard")
def get_sim_leaderboard(limit: int = 20) -> dict:
    safe_limit = max(1, min(int(limit), 500))
    rows = leaderboard_rows(limit=safe_limit)
    return {
        "status": "ok",
        "execution_mode": "mock",
        "leaderboard": rows,
        "total": len(rows),
        "limit": safe_limit,
    }


@router.get("/sim/agents/{agent_id}/trades")
def get_agent_recent_trades(agent_id: str, limit: int = 20) -> dict:
    safe_limit = max(1, min(int(limit), 500))
    target_uuid = resolve_agent_uuid(agent_id)
    if not target_uuid:
        raise HTTPException(status_code=404, detail="agent_not_found")

    with STATE.lock:
        account = STATE.accounts.get(target_uuid)
        if not account:
            raise HTTPException(status_code=404, detail="agent_not_found")
        valuation = valuation_for_account(account)
        trades = []
        for event in reversed(STATE.activity_log):
            actor = str(event.get("agent_uuid", "")).strip() or resolve_agent_uuid(str(event.get("agent_id", "")))
            if actor != target_uuid:
                continue
            trade = serialize_trade_event(event)
            if trade is None:
                continue
            trades.append(trade)
            if len(trades) >= safe_limit:
                break

    return {
        "status": "ok",
        "execution_mode": "mock",
        "agent_id": account.display_name,
        "agent_uuid": target_uuid,
        "avatar": account.avatar,
        "account": {
            "cash": round(float(valuation["cash"]), 4),
            "stock_market_value": round(float(valuation["stock_market_value"]), 4),
            "crypto_market_value": round(float(valuation["crypto_market_value"]), 4),
            "poly_market_value": round(float(valuation["poly_market_value"]), 4),
            "balance": round(float(valuation["equity"]), 4),
            "return_pct": round(float(valuation["return_pct"]), 6),
            "stock_realized_pnl": round(float(account.realized_pnl), 4),
            "poly_realized_pnl": round(float(account.poly_realized_pnl), 4),
        },
        "trades": trades,
        "total": len(trades),
        "limit": safe_limit,
    }


@router.get("/sim/poly/markets")
def list_poly_markets(agent_uuid: str = Depends(require_agent)) -> dict:
    rows = mock_broker.list_poly_markets()
    return {
        "status": "ok",
        "execution_mode": "mock",
        "agent_uuid": agent_uuid,
        "agent_id": STATE.display_name_for(agent_uuid),
        "markets": rows,
        "total": len(rows),
    }


@router.post("/sim/poly/bets")
def create_poly_bet(req: SimPolyBetCreateRequest, agent_uuid: str = Depends(require_agent)) -> dict:
    return mock_broker.place_poly_bet(
        agent_uuid=agent_uuid,
        market_id=req.market_id,
        outcome=req.outcome,
        amount=float(req.amount),
    )


@router.post("/sim/poly/sell")
def create_poly_sell(req: SimPolySellCreateRequest, agent_uuid: str = Depends(require_agent)) -> dict:
    return mock_broker.place_poly_sell(
        agent_uuid=agent_uuid,
        market_id=req.market_id,
        outcome=req.outcome,
        shares=float(req.shares),
    )


@router.post("/sim/poly/close")
def close_poly_position(req: SimPolySellCreateRequest, agent_uuid: str = Depends(require_agent)) -> dict:
    return create_poly_sell(req=req, agent_uuid=agent_uuid)
