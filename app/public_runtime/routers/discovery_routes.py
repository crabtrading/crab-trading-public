from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from ...state import STATE
from ..services.common import resolve_agent_uuid
from ..services.discovery_rank import discovery_cards

router = APIRouter(prefix="/api/v1/public", tags=["public-discovery"])


def _normalize_language(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return "python"
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in {"+", ".", "_", "#", "-"})
    cleaned = cleaned[:32]
    if not cleaned:
        return "python"
    if not cleaned[0].isalnum():
        cleaned = f"lang{cleaned}"[:32]
    return cleaned


def _algorithm_preview(full_code: str, *, max_lines: int = 26, max_chars: int = 3200) -> dict:
    text = str(full_code or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return {"preview": "", "truncated": False, "total_lines": 0, "shown_lines": 0}
    clipped = text
    truncated = False
    if len(clipped) > max_chars:
        clipped = clipped[:max_chars]
        truncated = True
    lines = clipped.split("\n")
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True
    preview = "\n".join(lines).rstrip()
    if truncated:
        preview = f"{preview}\n\n... (preview truncated)"
    return {
        "preview": preview,
        "truncated": truncated,
        "total_lines": len(text.split("\n")),
        "shown_lines": len(lines),
    }


def _comment_prefix(language: str) -> str:
    key = str(language or "").strip().lower()
    if key in {"javascript", "js", "typescript", "ts", "java", "c", "cpp", "c++", "csharp", "cs", "go", "rust", "kotlin", "swift", "php"}:
        return "//"
    if key in {"sql", "haskell", "lua"}:
        return "--"
    return "#"


def _public_trading_code_payload(account, language: str) -> tuple[str, bool]:
    raw_code = str(getattr(account, "trading_code", "") or "").strip()
    if raw_code:
        return raw_code, True

    summary_candidates = (
        str(getattr(account, "strategy_summary", "") or "").strip(),
        str(getattr(account, "strategy_summary_day", "") or "").strip(),
        str(getattr(account, "description", "") or "").strip(),
    )
    summary = ""
    for item in summary_candidates:
        text = " ".join(item.split()).strip()
        if len(text) >= 8 and not text.isdigit():
            summary = text
            break

    prefix = _comment_prefix(language)
    if summary:
        fallback = (
            f"{prefix} Public strategy summary\n"
            f"{prefix} {summary}\n\n"
            f"{prefix} No executable trading code provided."
        )
    else:
        fallback = (
            f"{prefix} Public strategy summary unavailable.\n"
            f"{prefix} No executable trading code provided."
        )
    return fallback, False


@router.get("/discovery/agents")
def get_discovery_agents(
    window: str = "7d",
    limit: int = 20,
    page: int = 1,
    symbol: str = "",
    risk: str = "",
    tag: str = "",
) -> dict:
    safe_limit = max(1, min(int(limit), 500))
    safe_page = max(1, int(page))
    cards = discovery_cards(limit=max(safe_limit * safe_page, safe_limit), symbol=symbol, risk=risk, tag=tag)
    start = (safe_page - 1) * safe_limit
    selected = cards[start : start + safe_limit]
    return {
        "status": "ok",
        "execution_mode": "mock",
        "window": str(window or "7d"),
        "page": safe_page,
        "page_size": safe_limit,
        "has_more": start + len(selected) < len(cards),
        "total": len(cards),
        "items": selected,
    }


@router.get("/discovery/tags")
def get_discovery_tags(limit: int = 60) -> dict:
    safe_limit = max(1, min(int(limit), 200))
    cards = discovery_cards(limit=500)
    counts: dict[str, int] = {}
    for row in cards:
        for tag in row.get("tags", []):
            text = str(tag or "").strip().lower()
            if not text:
                continue
            counts[text] = counts.get(text, 0) + 1
    tags = [{"tag": key, "count": value} for key, value in counts.items()]
    tags.sort(key=lambda item: (-int(item.get("count", 0)), str(item.get("tag", ""))))
    return {
        "status": "ok",
        "execution_mode": "mock",
        "tags": tags[:safe_limit],
        "total": len(tags),
        "limit": safe_limit,
    }


@router.get("/discovery/activity")
def get_discovery_activity(limit: int = 40) -> dict:
    safe_limit = max(1, min(int(limit), 500))
    rows: list[dict] = []
    with STATE.lock:
        for event in reversed(STATE.activity_log):
            etype = str(event.get("type", "")).strip().lower()
            if etype not in {"stock_order", "poly_bet", "poly_sell", "poly_resolved"}:
                continue
            details = event.get("details") if isinstance(event.get("details"), dict) else {}
            agent_uuid = str(event.get("agent_uuid", "")).strip() or resolve_agent_uuid(str(event.get("agent_id", "")))
            account = STATE.accounts.get(agent_uuid) if agent_uuid else None
            item = {
                "id": int(event.get("id", 0) or 0),
                "type": etype,
                "created_at": str(event.get("created_at", "") or ""),
                "agent_uuid": agent_uuid,
                "agent_id": str(account.display_name if account else STATE.display_name_for(agent_uuid) or ""),
                "avatar": str((account.avatar if account else "") or ""),
                "execution_mode": "mock",
            }
            if etype == "stock_order":
                item.update(
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
                market_id = str(details.get("market_id", "")).strip()
                market = STATE.poly_markets.get(market_id) if market_id else {}
                market_label = str(details.get("market_label", "")).strip() or str(market.get("question", "") if isinstance(market, dict) else "").strip() or market_id
                amount = float(details.get("amount", 0.0) or 0.0)
                shares = float(details.get("shares", 0.0) or 0.0)
                item.update(
                    {
                        "symbol": "POLY",
                        "side": "POLY",
                        "effective_action": "POLY_BET",
                        "qty": shares,
                        "notional": amount,
                        "market_id": market_id,
                        "market_label": market_label,
                        "outcome": str(details.get("outcome", "")).upper(),
                        "amount": amount,
                        "shares": shares,
                    }
                )
            elif etype == "poly_sell":
                market_id = str(details.get("market_id", "")).strip()
                market = STATE.poly_markets.get(market_id) if market_id else {}
                market_label = str(details.get("market_label", "")).strip() or str(market.get("question", "") if isinstance(market, dict) else "").strip() or market_id
                amount = float(details.get("amount", details.get("proceeds", 0.0)) or 0.0)
                shares = float(details.get("shares", 0.0) or 0.0)
                realized = float(details.get("realized_gross", details.get("realized_delta", 0.0)) or 0.0)
                item.update(
                    {
                        "symbol": "POLY",
                        "side": "POLY",
                        "effective_action": "POLY_SELL",
                        "qty": shares,
                        "notional": amount,
                        "market_id": market_id,
                        "market_label": market_label,
                        "outcome": str(details.get("outcome", "")).upper(),
                        "amount": amount,
                        "shares": shares,
                        "realized_gross": realized,
                    }
                )
            else:
                market_id = str(details.get("market_id", "")).strip()
                market = STATE.poly_markets.get(market_id) if market_id else {}
                market_label = str(details.get("market_label", "")).strip() or str(market.get("question", "") if isinstance(market, dict) else "").strip() or market_id
                payout = float(details.get("payout", 0.0) or 0.0)
                cost_basis = float(details.get("cost_basis", 0.0) or 0.0)
                realized = float(details.get("realized_gross", details.get("realized_delta", 0.0)) or 0.0)
                item.update(
                    {
                        "symbol": "POLY",
                        "side": "POLY",
                        "effective_action": "POLY_RESOLVED",
                        "qty": 0.0,
                        "notional": payout,
                        "market_id": market_id,
                        "market_label": market_label,
                        "winning_outcome": str(details.get("winning_outcome", "")).upper(),
                        "payout": payout,
                        "cost_basis": cost_basis,
                        "realized_gross": realized,
                    }
                )
            rows.append(item)
            if len(rows) >= safe_limit:
                break

    return {
        "status": "ok",
        "execution_mode": "mock",
        "items": rows,
        "limit": safe_limit,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/discovery/agents/{agent_id}/trading-code")
def get_public_trading_code(agent_id: str, include_code: bool = Query(default=True)) -> dict:
    target_uuid = resolve_agent_uuid(agent_id)
    if not target_uuid:
        raise HTTPException(status_code=404, detail="agent_not_found")
    with STATE.lock:
        account = STATE.accounts.get(target_uuid)
        if not account:
            raise HTTPException(status_code=404, detail="agent_not_found")
        language = _normalize_language(str(getattr(account, "trading_code_language", "python") or "python"))
        code, has_user_code = _public_trading_code_payload(account, language)
        preview = _algorithm_preview(code)

    return {
        "status": "ok",
        "execution_mode": "mock",
        "agent": {
            "agent_uuid": target_uuid,
            "agent_id": account.display_name,
            "avatar": account.avatar,
        },
        "trading_code": {
            "shared": True,
            "language": language,
            "updated_at": str(getattr(account, "trading_code_updated_at", "") or ""),
            "code": code if bool(include_code) else "",
            "code_loaded": bool(include_code),
            "brief": "",
            "preview": str(preview.get("preview", "") or ""),
            "preview_truncated": bool(preview.get("truncated", False)),
            "preview_total_lines": int(preview.get("total_lines", 0) or 0),
            "preview_shown_lines": int(preview.get("shown_lines", 0) or 0),
            "has_user_code": bool(has_user_code),
        },
    }
