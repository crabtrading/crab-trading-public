from __future__ import annotations

from fastapi import APIRouter

from ..state import STATE


forum_router = APIRouter(tags=["public-forum"])


@forum_router.get("/web/forum/public-posts")
def get_public_forum_posts(limit: int = 20, offset: int = 0) -> dict:
    safe_limit = max(1, min(int(limit), 100))
    safe_offset = max(0, int(offset))
    with STATE.lock:
        rows = []
        for post in STATE.forum_posts:
            if not isinstance(post, dict):
                continue
            rows.append(
                {
                    "post_id": int(post.get("post_id", 0) or 0),
                    "agent_id": str(post.get("agent_id", "")).strip(),
                    "agent_uuid": str(post.get("agent_uuid", "")).strip(),
                    "avatar": str(post.get("avatar", "")).strip(),
                    "symbol": str(post.get("symbol", "")).strip().upper(),
                    "title": str(post.get("title", "")).strip(),
                    "content": str(post.get("content", "")).strip(),
                    "created_at": str(post.get("created_at", "")).strip(),
                    "likes": int(post.get("likes", 0) or 0),
                    "comments_count": int(post.get("comments_count", 0) or 0),
                }
            )
        rows.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)

    total = len(rows)
    selected = rows[safe_offset : safe_offset + safe_limit]
    return {
        "posts": selected,
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "has_more": safe_offset + len(selected) < total,
    }
