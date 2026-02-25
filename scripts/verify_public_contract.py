#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.routing import APIRoute

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.public_main import app  # noqa: E402

API_PREFIX = "/api/v1/public"
REQUIRED_API_PATHS = {
    "/api/v1/public/health",
    "/api/v1/public/agents/register",
    "/api/v1/public/agents/me",
    "/api/v1/public/forum/posts",
    "/api/v1/public/discovery/agents",
    "/api/v1/public/discovery/agents/{agent_id}/trading-code",
    "/api/v1/public/discovery/tags",
    "/api/v1/public/discovery/activity",
    "/api/v1/public/sim/account",
    "/api/v1/public/sim/quote",
    "/api/v1/public/sim/orders",
    "/api/v1/public/sim/open-orders",
    "/api/v1/public/sim/positions",
    "/api/v1/public/sim/leaderboard",
    "/api/v1/public/sim/agents/{agent_id}/trades",
    "/api/v1/public/sim/poly/markets",
    "/api/v1/public/sim/poly/bets",
    "/api/v1/public/following",
    "/api/v1/public/following/alerts",
    "/api/v1/public/following/top",
    "/api/v1/public/follow/event",
    "/api/v1/public/protocol/openapi.json",
    "/api/v1/public/protocol/event-schema",
}

ALLOWED_NON_API_PATHS = {
    "/",
    "/discover",
    "/health",
    "/skill.md",
    "/skill.json",
    "/heartbeat.md",
    "/messaging.md",
    "/rules.md",
    "/favicon.ico",
    "/favicon.png",
    "/apple-touch-icon.png",
    "/apple-touch-icon-precomposed.png",
    "/crab-mark.png",
    "/crab-logo.svg",
    "/crab-mark-master.svg",
    "/crab-mark-ice.svg",
    "/define-orb-crab.svg",
    "/crab-orb-core.png",
    "/crab-orb-core-alpha.png",
    "/crab-network-cluster.png",
    "/hero-watch.svg",
    "/hero-buy.svg",
    "/hero-social.svg",
    "/crabtrading.css",
    "/crabtrading.js",
    "/discover.css",
    "/discover-surface.css",
    "/discover.js",
    "/crab-shell.css",
    "/crabs/{icon_name}",
    "/crabs-network/{icon_name}",
}

BLOCKED_ROUTE_PREFIXES = (
    "/web/live/",
    "/web/owner/",
    "/internal/",
    "/api/agent/live/",
)

BLOCKED_ROUTE_EXACT = {
    "/web/live/account",
    "/web/live/order",
    "/web/owner/session/me",
}

SCAN_PATHS = [
    REPO_ROOT / "app" / "public_main.py",
    REPO_ROOT / "app" / "public_runtime",
    REPO_ROOT / "app" / "static",
]

BLOCKED_MARKERS = (
    "from ..live",
    "from ...live",
    "app.live",
    "/web/live/",
    "/web/owner/",
    "/internal/",
    "CRAB_LIVE_",
)


def collect_route_paths() -> list[str]:
    paths: list[str] = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            paths.append(str(route.path))
    return sorted(set(paths))


def scan_markers() -> list[str]:
    findings: list[str] = []
    for base in SCAN_PATHS:
        if not base.exists():
            continue
        targets = [base]
        if base.is_dir():
            targets = sorted([item for item in base.rglob("*") if item.is_file()])
        for path in targets:
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            for marker in BLOCKED_MARKERS:
                if marker in text:
                    findings.append(f"blocked_marker:{marker}:{path.relative_to(REPO_ROOT)}")
    return findings


def main() -> int:
    errors: list[str] = []
    paths = collect_route_paths()
    path_set = set(paths)

    missing = sorted(REQUIRED_API_PATHS - path_set)
    if missing:
        errors.append("missing_required_api_paths")
        errors.extend(f"  - {item}" for item in missing)

    for path in paths:
        if path.startswith(API_PREFIX):
            continue
        if path in ALLOWED_NON_API_PATHS:
            continue
        errors.append(f"unexpected_non_api_route:{path}")

    for path in paths:
        if path in BLOCKED_ROUTE_EXACT:
            errors.append(f"blocked_route:{path}")
        for prefix in BLOCKED_ROUTE_PREFIXES:
            if path.startswith(prefix):
                errors.append(f"blocked_prefix_route:{path}")

    if "/api/v1/public/discovery/leaderboard" in path_set:
        errors.append("discovery_leaderboard_must_not_exist")

    marker_findings = scan_markers()
    errors.extend(marker_findings)

    if errors:
        print("PUBLIC CONTRACT VERIFY FAILED")
        for item in errors:
            print(item)
        return 1

    print("PUBLIC CONTRACT VERIFY OK")
    print(f"public_route_count={len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
