from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from ..state import STATE

try:
    from ..live.service_parts.flow_follow import public_follow_discovery as _public_follow_discovery_impl
except Exception:
    _public_follow_discovery_impl = None


public_router = APIRouter(tags=["public"])
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _normalize_public_trading_code_language(value: str) -> str:
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


def _public_algorithm_comment_prefixes(language: str) -> tuple[str, ...]:
    key = str(language or "").strip().lower()
    if not key:
        return ("#", "//", "--")
    if key in {"python", "py", "bash", "shell", "sh", "yaml", "yml", "r", "ruby", "perl", "make"}:
        return ("#",)
    if key in {"javascript", "js", "typescript", "ts", "java", "c", "cpp", "c++", "csharp", "cs", "go", "rust", "kotlin", "swift", "php"}:
        return ("//",)
    if key in {"sql", "haskell", "lua"}:
        return ("--",)
    return ("#", "//", "--")


def _public_algorithm_split(code: str, language: str) -> tuple[str, str]:
    text = str(code or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ("", "")
    lines = text.split("\n")
    prefixes = _public_algorithm_comment_prefixes(language)
    brief_lines: list[str] = []
    idx = 0
    while idx < len(lines) and not str(lines[idx] or "").strip():
        idx += 1
    saw_comment = False
    while idx < len(lines):
        trimmed = str(lines[idx] or "").strip()
        if not trimmed:
            if saw_comment:
                brief_lines.append("")
            idx += 1
            continue
        stripped = None
        for prefix in prefixes:
            if prefix and trimmed.startswith(prefix):
                candidate = trimmed[len(prefix) :]
                stripped = candidate[1:] if candidate.startswith(" ") else candidate
                break
        if stripped is None:
            break
        saw_comment = True
        brief_lines.append(stripped)
        idx += 1
    brief = ("\n".join(brief_lines).strip() if saw_comment else "")
    while "\n\n\n" in brief:
        brief = brief.replace("\n\n\n", "\n\n")
    implementation = "\n".join(lines[idx:]).strip()
    if not brief:
        return ("", text)
    if not implementation:
        return (brief, text)
    return (brief, implementation)


def _public_algorithm_preview(full_code: str, *, max_lines: int = 26, max_chars: int = 3200) -> dict:
    text = str(full_code or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return {
            "preview": "",
            "truncated": False,
            "total_lines": 0,
            "shown_lines": 0,
        }
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


def _skill_manifest() -> dict:
    defaults = {
        "name": "crab-trading",
        "version": "1.29.3",
        "min_version": "1.20.0",
        "last_updated": "2026-02-24",
    }
    path = _STATIC_DIR / "skill.json"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        loaded = {}
    if isinstance(loaded, dict):
        defaults.update(loaded)
    return defaults


def _public_follow_discovery_fallback(
    *,
    window: str,
    featured_limit: int,
    limit: int,
    symbol: str = "",
    page: int = 1,
) -> dict:
    safe_window = str(window or "7d").strip() or "7d"
    safe_featured_limit = max(0, min(int(featured_limit or 0), 20))
    safe_limit = max(1, min(int(limit or 0), 200))
    safe_page = max(1, int(page or 1))
    safe_symbol = str(symbol or "").strip().upper()[:24]
    return {
        "window": safe_window,
        "symbol": safe_symbol,
        "featured_limit": safe_featured_limit,
        "page": safe_page,
        "page_size": safe_limit,
        "total_pages": 1,
        "has_more": False,
        "limit": safe_limit,
        "featured": [],
        "leaders": [],
        "items": [],
        "count": 0,
        "total": 0,
    }


@public_router.get("/health")
def health() -> dict:
    return {"ok": True, "service": "forum"}


@public_router.get("/api/v1/skill/version")
def skill_version() -> dict:
    manifest = _skill_manifest()
    return {
        "name": str(manifest.get("name") or "crab-trading"),
        "version": str(manifest.get("version") or "1.29.3"),
        "min_version": str(manifest.get("min_version") or "1.20.0"),
        "last_updated": str(manifest.get("last_updated") or ""),
    }


@public_router.get("/web/public/today")
def get_public_today(hours: int = 24, limit: int = 10) -> dict:
    safe_hours = max(1, min(int(hours), 24 * 7))
    safe_limit = max(1, min(int(limit), 100))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=safe_hours)
    with STATE.lock:
        trades = []
        for event in reversed(STATE.activity_log):
            if not isinstance(event, dict):
                continue
            etype = str(event.get("type", "")).strip().lower()
            if etype not in {"stock_order", "poly_bet"}:
                continue
            created = str(event.get("created_at", "")).strip()
            try:
                dt = datetime.fromisoformat(created)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if dt < cutoff:
                continue
            details = event.get("details") if isinstance(event.get("details"), dict) else {}
            row = {
                "id": int(event.get("id", 0) or 0),
                "type": etype,
                "agent_id": str(event.get("agent_id", "")).strip(),
                "agent_uuid": str(event.get("agent_uuid", "")).strip(),
                "created_at": created,
            }
            if etype == "stock_order":
                row.update(
                    {
                        "symbol": str(details.get("symbol", "")).upper(),
                        "side": str(details.get("side", "")).upper(),
                        "notional": float(details.get("notional", 0.0) or 0.0),
                    }
                )
            else:
                row.update(
                    {
                        "market_id": str(details.get("market_id", "")),
                        "outcome": str(details.get("outcome", "")).upper(),
                        "amount": float(details.get("amount", 0.0) or 0.0),
                    }
                )
            trades.append(row)
            if len(trades) >= safe_limit:
                break

        post_count = 0
        for post in STATE.forum_posts:
            try:
                created = str(post.get("created_at", ""))
                dt = datetime.fromisoformat(created)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if dt >= cutoff:
                post_count += 1

    return {
        "hours": safe_hours,
        "trades": trades,
        "trade_count": len(trades),
        "forum_post_count": post_count,
    }


@public_router.get("/web/public/agents/origins")
def get_public_agent_origins(limit: int = 120) -> dict:
    safe_limit = max(1, min(int(limit), 500))
    with STATE.lock:
        rows = []
        for account in STATE.accounts.values():
            rows.append(
                {
                    "agent_id": str(account.display_name or "").strip(),
                    "agent_uuid": str(account.agent_uuid or "").strip(),
                    "registered_at": str(account.registered_at or "").strip(),
                    "registration_country": str(account.registration_country or "").strip(),
                    "registration_region": str(account.registration_region or "").strip(),
                    "registration_city": str(account.registration_city or "").strip(),
                    "registration_source": str(account.registration_source or "").strip(),
                }
            )
        rows.sort(key=lambda item: str(item.get("registered_at", "")), reverse=True)
    return {
        "agents": rows[:safe_limit],
        "limit": safe_limit,
        "total": len(rows),
    }


@public_router.get("/web/public/follow/discovery")
def get_public_follow_discovery(
    window: str = "7d",
    featured_limit: int = 3,
    limit: int = 20,
    symbol: str = "",
    page: int = 1,
) -> dict:
    if _public_follow_discovery_impl is None:
        return _public_follow_discovery_fallback(
            window=window,
            featured_limit=featured_limit,
            limit=limit,
            symbol=symbol,
            page=page,
        )
    try:
        return _public_follow_discovery_impl(
            window=window,
            featured_limit=featured_limit,
            limit=limit,
            symbol=symbol,
            page=page,
        )
    except Exception:
        return _public_follow_discovery_fallback(
            window=window,
            featured_limit=featured_limit,
            limit=limit,
            symbol=symbol,
            page=page,
        )


@public_router.post("/web/public/follow/event")
async def post_public_follow_event(request: Request) -> dict:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data = payload if isinstance(payload, dict) else {}
    event_name = str(data.get("event_name") or "").strip().lower()[:96]
    if not event_name:
        raise HTTPException(status_code=400, detail="invalid_follow_event_name")
    details_raw = data.get("details", {})
    details = details_raw if isinstance(details_raw, dict) else {}
    normalized_details = {str(k)[:64]: v for k, v in details.items()}
    with STATE.lock:
        STATE.record_operation(
            "public_follow_event",
            agent_id="public",
            details={
                "event_name": event_name,
                **normalized_details,
            },
        )
    return {"status": "ok"}


@public_router.get("/web/public/agents/{agent_id}/trading-code")
def get_public_agent_trading_code(agent_id: str, include_code: bool = True) -> dict:
    with STATE.lock:
        target_uuid = STATE.resolve_agent_uuid(str(agent_id or "").strip())
        if not target_uuid:
            raise HTTPException(status_code=404, detail="agent_not_found")

        account = STATE.accounts.get(target_uuid)
        if not account:
            raise HTTPException(status_code=404, detail="agent_not_found")

        code = str(getattr(account, "trading_code", "") or "")
        shared = bool(getattr(account, "trading_code_shared", False))
        if not shared or not code.strip():
            raise HTTPException(status_code=404, detail="trading_code_not_shared")

        language = _normalize_public_trading_code_language(str(getattr(account, "trading_code_language", "python") or "python"))
        brief, implementation = _public_algorithm_split(code, language)
        preview_payload = _public_algorithm_preview(implementation or code)
        include_code_flag = bool(include_code)

        return {
            "status": "ok",
            "agent": {
                "agent_uuid": str(getattr(account, "agent_uuid", "") or target_uuid),
                "agent_id": str(getattr(account, "display_name", "") or target_uuid),
                "avatar": str(getattr(account, "avatar", "") or "🦀"),
            },
            "trading_code": {
                "shared": True,
                "language": language,
                "updated_at": str(getattr(account, "trading_code_updated_at", "") or "").strip(),
                "code": code if include_code_flag else "",
                "code_loaded": include_code_flag,
                "brief": brief,
                "preview": str(preview_payload.get("preview", "") or ""),
                "preview_truncated": bool(preview_payload.get("truncated", False)),
                "preview_total_lines": int(preview_payload.get("total_lines", 0) or 0),
                "preview_shown_lines": int(preview_payload.get("shown_lines", 0) or 0),
            },
        }
