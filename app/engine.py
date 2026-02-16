from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException

from .models import Order, OrderRequest, Side
from .state import AgentAccount, STATE


def _mark_to_market_loss(account: AgentAccount) -> float:
    # Negative number means loss from open positions.
    total = 0.0
    for sym, qty in account.positions.items():
        if qty == 0:
            continue
        px = STATE.prices.get(sym)
        if px is None:
            continue
        avg = account.avg_cost.get(sym, px)
        total += (px - avg) * qty
    return min(0.0, total)


def _check_risk(account: AgentAccount, req: OrderRequest, fill_price: float) -> None:
    current_pos = account.positions.get(req.symbol, 0.0)
    target_pos = current_pos + req.qty if req.side == Side.BUY else current_pos - req.qty

    if abs(target_pos) > STATE.risk_config.max_abs_position_per_symbol:
        raise HTTPException(status_code=400, detail="risk_reject: max_abs_position_per_symbol")

    if req.side == Side.BUY:
        cost = req.qty * fill_price
        if account.cash < cost:
            raise HTTPException(status_code=400, detail="risk_reject: insufficient_cash")

    if account.realized_pnl + _mark_to_market_loss(account) <= -STATE.risk_config.max_daily_loss:
        account.blocked = True
        raise HTTPException(status_code=400, detail="risk_reject: max_daily_loss_breached")


def _update_position_with_trade(account: AgentAccount, symbol: str, signed_qty: float, fill_price: float) -> None:
    old_qty = account.positions.get(symbol, 0.0)
    old_avg = account.avg_cost.get(symbol, fill_price)
    new_qty = old_qty + signed_qty

    if old_qty == 0 or old_qty * signed_qty > 0:
        total_abs = abs(old_qty) + abs(signed_qty)
        new_avg = ((abs(old_qty) * old_avg) + (abs(signed_qty) * fill_price)) / total_abs
        account.avg_cost[symbol] = new_avg
    else:
        closing = min(abs(old_qty), abs(signed_qty))
        pnl_per_unit = fill_price - old_avg
        if old_qty < 0:
            pnl_per_unit = -pnl_per_unit
        account.realized_pnl += pnl_per_unit * closing
        if new_qty == 0:
            account.avg_cost.pop(symbol, None)
        elif old_qty * new_qty < 0:
            account.avg_cost[symbol] = fill_price

    if new_qty == 0:
        account.positions.pop(symbol, None)
    else:
        account.positions[symbol] = new_qty


def submit_market_order(agent_id: str, req: OrderRequest) -> Order:
    with STATE.lock:
        account = STATE.accounts.get(agent_id)
        if account is None:
            raise HTTPException(status_code=404, detail="agent_not_found")
        if account.blocked:
            raise HTTPException(status_code=403, detail="agent_blocked")

        fill_price = STATE.prices.get(req.symbol)
        if fill_price is None:
            raise HTTPException(status_code=400, detail="symbol_not_supported")

        _check_risk(account, req, fill_price)

        signed_qty = req.qty if req.side == Side.BUY else -req.qty
        notional = req.qty * fill_price

        if req.side == Side.BUY:
            account.cash -= notional
        else:
            account.cash += notional

        _update_position_with_trade(account, req.symbol, signed_qty, fill_price)

        return Order(
            order_id=str(uuid4()),
            agent_id=agent_id,
            symbol=req.symbol,
            side=req.side,
            qty=req.qty,
            fill_price=fill_price,
            notional=notional,
            status="FILLED",
        )
