"""Shared static asset version for cache busting."""

from __future__ import annotations

import os
from pathlib import Path


def _resolve_fallback_asset_ver() -> str:
    app_dir = Path(__file__).resolve().parent
    project_root = app_dir.parent
    candidates = [
        app_dir / "static" / "crab-shell.css",
        app_dir / "static" / "crabtrading.css",
        app_dir / "static" / "crabtrading.js",
        app_dir / "static" / "discover.css",
        app_dir / "static" / "discover-surface.css",
        app_dir / "static" / "discover.js",
        app_dir / "static" / "crabtrading.html",
        app_dir / "static" / "discover.html",
        app_dir / "static" / "claim.html",
        project_root / "internal_beta" / "owner-console.html",
        project_root / "internal_beta" / "owner-start.html",
        project_root / "internal_beta" / "beta-ui.html",
    ]
    latest_mtime = 0
    for path in candidates:
        try:
            latest_mtime = max(latest_mtime, int(path.stat().st_mtime))
        except OSError:
            continue
    if latest_mtime > 0:
        return f"m{latest_mtime}"
    return "20260224shellv2"


def _resolve_asset_ver() -> str:
    value = str(os.getenv("CRAB_ASSET_VER", "")).strip()
    if value:
        return value
    return _resolve_fallback_asset_ver()


ASSET_VER = _resolve_asset_ver()
