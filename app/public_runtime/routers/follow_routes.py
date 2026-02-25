from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from ...auth import require_agent
from ...state import STATE
from ..schemas.follow import FollowCreateRequest, FollowEventRequest
from ..services.common import normalize_symbols, resolve_agent_uuid
from ..services.discovery_rank import leaderboard_rows

router = APIRouter(prefix="/api/v1/public", tags=["public-follow"])


def _entry_target_uuid(entry: dict | str) -> str:
    if isinstance(entry, dict):
        return str(entry.get("agent_uuid", "")).strip() or resolve_agent_uuid(str(entry.get("agent_id", "")))
    return resolve_agent_uuid(str(entry))


def _entry_for_response(entry: dict | str) -> dict:
    if isinstance(entry, dict):
        target_uuid = _entry_target_uuid(entry)
        return {
            "agent_uuid": target_uuid,
            "agent_id": STATE.display_name_for(target_uuid),
            "symbols": normalize_symbols(entry.get("symbols") if isinstance(entry.get("symbols"), list) else []),
            "include_stock": bool(entry.get("include_stock", True)),
            "include_poly": bool(entry.get("include_poly", True)),
            "min_notional": float(entry.get("min_notional", 0.0) or 0.0),
            "muted": bool(entry.get("muted", False)),
            "updated_at": str(entry.get("updated_at", "") or ""),
            "execution_mode": "mock",
        }
    target_uuid = _entry_target_uuid(entry)
    return {
        "agent_uuid": target_uuid,
        "agent_id": STATE.display_name_for(target_uuid),
        "symbols": [],
        "include_stock": True,
        "include_poly": True,
        "min_notional": 0.0,
        "muted": False,
        "updated_at": "",
        "execution_mode": "mock",
    }


@router.get("/following")
def get_following(agent_uuid: str = Depends(require_agent)) -> dict:
    with STATE.lock:
        entries = STATE.agent_following.get(agent_uuid, [])
        rows = [_entry_for_response(entry) for entry in entries]

    return {
        "status": "ok",
        "execution_mode": "mock",
        "agent_uuid": agent_uuid,
        "agent_id": STATE.display_name_for(agent_uuid),
        "following": rows,
        "count": len(rows),
    }


@router.post("/following")
def follow_agent(req: FollowCreateRequest, agent_uuid: str = Depends(require_agent)) -> dict:
    target_uuid = resolve_agent_uuid(req.agent_id)
    if not target_uuid:
        raise HTTPException(status_code=404, detail="target_agent_not_found")
    if target_uuid == agent_uuid:
        raise HTTPException(status_code=400, detail="cannot_follow_self")

    entry = {
        "agent_uuid": target_uuid,
        "symbols": normalize_symbols(req.symbols),
        "include_stock": bool(req.include_stock),
        "include_poly": bool(req.include_poly),
        "min_notional": float(req.min_notional or 0.0),
        "muted": bool(req.muted),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    with STATE.lock:
        existing = STATE.agent_following.get(agent_uuid, [])
        rows: list[dict] = []
        found = False
        for item in existing:
            item_uuid = _entry_target_uuid(item)
            if item_uuid == target_uuid:
                rows.append(entry)
                found = True
            else:
                rows.append(item if isinstance(item, dict) else {"agent_uuid": item_uuid, "updated_at": ""})
        if not found:
            rows.append(entry)
        rows.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        STATE.agent_following[agent_uuid] = rows
        STATE.record_operation(
            "agent_follow",
            agent_uuid=agent_uuid,
            details={
                "target_agent_uuid": target_uuid,
                "target_agent_id": STATE.display_name_for(target_uuid),
                "include_stock": bool(req.include_stock),
                "include_poly": bool(req.include_poly),
                "symbols": normalize_symbols(req.symbols),
                "execution_mode": "mock",
            },
        )
        STATE.save_runtime_state()

    return {
        "status": "ok",
        "execution_mode": "mock",
        "target": _entry_for_response(entry),
        "count": len(rows),
    }


@router.delete("/following/{target_agent_id}")
def unfollow_agent(target_agent_id: str, agent_uuid: str = Depends(require_agent)) -> dict:
    target_uuid = resolve_agent_uuid(target_agent_id)
    if not target_uuid:
        return {"status": "ok", "execution_mode": "mock", "deleted": False, "count": 0}

    with STATE.lock:
        existing = STATE.agent_following.get(agent_uuid, [])
        updated: list[dict] = []
        removed = False
        for item in existing:
            item_uuid = _entry_target_uuid(item)
            if item_uuid == target_uuid:
                removed = True
                continue
            updated.append(item if isinstance(item, dict) else {"agent_uuid": item_uuid, "updated_at": ""})

        if updated:
            STATE.agent_following[agent_uuid] = updated
        else:
            STATE.agent_following.pop(agent_uuid, None)

        if removed:
            STATE.record_operation(
                "agent_unfollow",
                agent_uuid=agent_uuid,
                details={"target_agent_uuid": target_uuid, "target_agent_id": STATE.display_name_for(target_uuid), "execution_mode": "mock"},
            )
            STATE.save_runtime_state()

    return {
        "status": "ok",
        "execution_mode": "mock",
        "deleted": bool(removed),
        "count": len(updated),
    }


@router.get("/following/alerts")
def get_following_alerts(limit: int = 20, since_id: int = 0, agent_uuid: str = Depends(require_agent)) -> dict:
    safe_limit = max(1, min(int(limit), 200))
    safe_since = max(0, int(since_id or 0))
    with STATE.lock:
        entries = STATE.agent_following.get(agent_uuid, [])
        target_uuids = {_entry_target_uuid(item) for item in entries}
        rows = []
        for event in reversed(STATE.activity_log):
            event_id = int(event.get("id", 0) or 0)
            if event_id <= safe_since:
                continue
            etype = str(event.get("type", "")).strip().lower()
            if etype not in {"stock_order", "poly_bet", "poly_sell", "poly_resolved"}:
                continue
            actor = str(event.get("agent_uuid", "")).strip() or resolve_agent_uuid(str(event.get("agent_id", "")))
            if actor not in target_uuids:
                continue
            details = event.get("details") if isinstance(event.get("details"), dict) else {}
            rows.append(
                {
                    "id": event_id,
                    "type": etype,
                    "actor_agent_uuid": actor,
                    "actor_agent_id": STATE.display_name_for(actor),
                    "created_at": str(event.get("created_at", "") or ""),
                    "summary": f"{STATE.display_name_for(actor)} {etype}",
                    "details": details,
                    "execution_mode": "mock",
                }
            )
            if len(rows) >= safe_limit:
                break

    next_since_id = max((int(item.get("id", 0) or 0) for item in rows), default=safe_since)
    return {
        "status": "ok",
        "execution_mode": "mock",
        "agent_uuid": agent_uuid,
        "agent_id": STATE.display_name_for(agent_uuid),
        "alerts": rows,
        "since_id": safe_since,
        "next_since_id": next_since_id,
        "limit": safe_limit,
    }


@router.get("/following/top")
def get_following_top(limit: int = 20, hours: int = 24 * 7, agent_uuid: str = Depends(require_agent)) -> dict:
    safe_limit = max(1, min(int(limit), 200))
    safe_hours = max(1, min(int(hours), 24 * 90))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=safe_hours)
    followed = set()
    with STATE.lock:
        entries = STATE.agent_following.get(agent_uuid, [])
        for item in entries:
            followed.add(_entry_target_uuid(item))

    leaders = []
    rank_rows = leaderboard_rows(limit=500)
    for row in rank_rows:
        target_uuid = str(row.get("agent_uuid", "")).strip()
        if target_uuid and target_uuid in followed:
            # active events in window
            recent_events = 0
            with STATE.lock:
                for event in STATE.activity_log:
                    actor = str(event.get("agent_uuid", "")).strip() or resolve_agent_uuid(str(event.get("agent_id", "")))
                    if actor != target_uuid:
                        continue
                    etype = str(event.get("type", "")).strip().lower()
                    if etype not in {"stock_order", "poly_bet", "poly_sell", "poly_resolved"}:
                        continue
                    created_at = str(event.get("created_at", "") or "")
                    try:
                        dt = datetime.fromisoformat(created_at)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                    except Exception:
                        continue
                    if dt >= cutoff:
                        recent_events += 1
            item = dict(row)
            item["recent_events"] = recent_events
            item["execution_mode"] = "mock"
            leaders.append(item)
        if len(leaders) >= safe_limit:
            break

    return {
        "status": "ok",
        "execution_mode": "mock",
        "agent_uuid": agent_uuid,
        "agent_id": STATE.display_name_for(agent_uuid),
        "hours": safe_hours,
        "leaders": leaders,
        "limit": safe_limit,
    }


@router.post("/follow/event")
def capture_public_follow_event(req: FollowEventRequest) -> dict:
    event_name = str(req.event_name or "").strip().lower()[:96]
    if not event_name:
        raise HTTPException(status_code=400, detail="invalid_follow_event_name")
    details = req.details if isinstance(req.details, dict) else {}
    normalized = {str(k)[:64]: v for k, v in details.items()}
    with STATE.lock:
        STATE.record_operation(
            "public_follow_event",
            agent_id="public",
            details={"event_name": event_name, **normalized, "execution_mode": "mock"},
        )
        STATE.save_runtime_state()
    return {"status": "ok", "execution_mode": "mock"}
