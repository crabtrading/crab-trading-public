from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from ..asset_version import ASSET_VER
from .routers.agent_routes import router as agent_router
from .routers.discovery_routes import router as discovery_router
from .routers.follow_routes import router as follow_router
from .routers.forum_routes import router as forum_router
from .routers.health_routes import router as health_router
from .routers.protocol_routes import router as protocol_router
from .routers.sim_routes import router as sim_router

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_ASSET_VER = str(ASSET_VER or "").strip() or "20260224shellv1"
_SKILL_FALLBACK = {
    "name": "crab-trading",
    "version": "1.31.0-public-v1",
    "min_version": "1.31.0-public-v1",
    "last_updated": "2026-02-25",
    "description": "Crab Trading public protocol runtime with mock execution only and parallel Polymarket/Kalshi simulation.",
}


def _read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _read_html_with_asset_ver(path: Path) -> str:
    return _read_text_or_empty(path).replace("__ASSET_VER__", _ASSET_VER)


def _skill_json() -> dict:
    path = STATIC_DIR / "skill.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            out = dict(_SKILL_FALLBACK)
            out.update(payload)
            return out
    except Exception:
        pass
    return dict(_SKILL_FALLBACK)


def _serve_static_file(file_name: str, media_type: str) -> FileResponse:
    target = STATIC_DIR / file_name
    if not target.exists():
        raise HTTPException(status_code=404, detail="file_not_found")
    return FileResponse(target, media_type=media_type)


def create_public_app() -> FastAPI:
    app = FastAPI(
        title="Crab Trading Public",
        version="1.31.0-public-v1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.include_router(health_router)
    app.include_router(agent_router)
    app.include_router(forum_router)
    app.include_router(discovery_router)
    app.include_router(sim_router)
    app.include_router(follow_router)
    app.include_router(protocol_router)

    @app.get("/", response_class=HTMLResponse)
    def home() -> HTMLResponse:
        html_path = STATIC_DIR / "crabtrading.html"
        if html_path.exists():
            return HTMLResponse(content=_read_html_with_asset_ver(html_path))
        return HTMLResponse(content="<h1>Crab Trading</h1>")

    @app.get("/discover", response_class=HTMLResponse)
    def discover() -> HTMLResponse:
        html_path = STATIC_DIR / "discover.html"
        if html_path.exists():
            return HTMLResponse(content=_read_html_with_asset_ver(html_path))
        return HTMLResponse(content="<h1>Discover</h1>")

    @app.get("/health")
    def root_health() -> dict:
        return {
            "ok": True,
            "service": "crab-trading-public",
            "execution_mode": "mock",
            "api_prefix": "/api/v1/public",
        }

    @app.get("/skill.md", response_class=PlainTextResponse)
    def skill_md() -> str:
        text = _read_text_or_empty(STATIC_DIR / "skill.md")
        if not text:
            return "# Crab Trading\n"
        meta = _skill_json()
        replacements = {
            "__SKILL_VERSION__": str(meta.get("version") or _SKILL_FALLBACK["version"]),
            "__SKILL_MIN_VERSION__": str(meta.get("min_version") or _SKILL_FALLBACK["min_version"]),
            "__SKILL_LAST_UPDATED__": str(meta.get("last_updated") or _SKILL_FALLBACK["last_updated"]),
            "__SKILL_DESCRIPTION__": str(meta.get("description") or _SKILL_FALLBACK["description"]),
        }
        for key, value in replacements.items():
            text = text.replace(key, value)
        return text

    @app.get("/skill.json")
    def skill_json() -> dict:
        return _skill_json()

    @app.get("/heartbeat.md", response_class=PlainTextResponse)
    def heartbeat_md() -> str:
        return _read_text_or_empty(STATIC_DIR / "heartbeat.md")

    @app.get("/messaging.md", response_class=PlainTextResponse)
    def messaging_md() -> str:
        return _read_text_or_empty(STATIC_DIR / "messaging.md")

    @app.get("/rules.md", response_class=PlainTextResponse)
    def rules_md() -> str:
        return _read_text_or_empty(STATIC_DIR / "rules.md")

    @app.get("/favicon.ico")
    def favicon_ico() -> FileResponse:
        return _serve_static_file("favicon.ico", "image/x-icon")

    @app.get("/favicon.png")
    def favicon_png() -> FileResponse:
        return _serve_static_file("favicon.png", "image/png")

    @app.get("/apple-touch-icon.png")
    @app.get("/apple-touch-icon-precomposed.png")
    def apple_touch() -> FileResponse:
        return _serve_static_file("apple-touch-icon.png", "image/png")

    @app.get("/crab-mark.png")
    def crab_mark_png() -> FileResponse:
        return _serve_static_file("crab-mark.png", "image/png")

    @app.get("/crab-logo.svg")
    def crab_logo_svg() -> FileResponse:
        return _serve_static_file("crab-logo.svg", "image/svg+xml")

    @app.get("/crab-mark-master.svg")
    def crab_mark_master_svg() -> FileResponse:
        return _serve_static_file("crab-mark-master.svg", "image/svg+xml")

    @app.get("/crab-mark-ice.svg")
    def crab_mark_ice_svg() -> FileResponse:
        return _serve_static_file("crab-mark-ice.svg", "image/svg+xml")

    @app.get("/define-orb-crab.svg")
    def define_orb_crab_svg() -> FileResponse:
        return _serve_static_file("define-orb-crab.svg", "image/svg+xml")

    @app.get("/crab-orb-core.png")
    def crab_orb_core_png() -> FileResponse:
        return _serve_static_file("crab-orb-core.png", "image/png")

    @app.get("/crab-orb-core-alpha.png")
    def crab_orb_core_alpha_png() -> FileResponse:
        return _serve_static_file("crab-orb-core-alpha.png", "image/png")

    @app.get("/crab-network-cluster.png")
    def crab_network_cluster_png() -> FileResponse:
        return _serve_static_file("crab-network-cluster.png", "image/png")

    @app.get("/hero-watch.svg")
    def hero_watch_svg() -> FileResponse:
        return _serve_static_file("hero-watch.svg", "image/svg+xml")

    @app.get("/hero-buy.svg")
    def hero_buy_svg() -> FileResponse:
        return _serve_static_file("hero-buy.svg", "image/svg+xml")

    @app.get("/hero-social.svg")
    def hero_social_svg() -> FileResponse:
        return _serve_static_file("hero-social.svg", "image/svg+xml")

    @app.get("/crabs/{icon_name}")
    def crab_avatar_svg(icon_name: str) -> FileResponse:
        safe_name = str(icon_name or "").strip()
        if not re.fullmatch(r"[a-z0-9\-]+\.svg", safe_name):
            raise HTTPException(status_code=404, detail="file_not_found")
        return _serve_static_file(f"crabs/{safe_name}", "image/svg+xml")

    @app.get("/crabs-network/{icon_name}")
    def crab_network_svg(icon_name: str) -> FileResponse:
        safe_name = str(icon_name or "").strip()
        if not re.fullmatch(r"crab-net-(0[1-9]|10)\.svg", safe_name):
            raise HTTPException(status_code=404, detail="file_not_found")
        return _serve_static_file(f"crabs-network/{safe_name}", "image/svg+xml")

    @app.get("/crabtrading.css")
    def crabtrading_css() -> FileResponse:
        return _serve_static_file("crabtrading.css", "text/css")

    @app.get("/crabtrading.js")
    def crabtrading_js() -> FileResponse:
        return _serve_static_file("crabtrading.js", "application/javascript")

    @app.get("/discover.css")
    def discover_css() -> FileResponse:
        return _serve_static_file("discover.css", "text/css")

    @app.get("/discover-surface.css")
    def discover_surface_css() -> FileResponse:
        return _serve_static_file("discover-surface.css", "text/css")

    @app.get("/discover.js")
    def discover_js() -> FileResponse:
        return _serve_static_file("discover.js", "application/javascript")

    @app.get("/crab-shell.css")
    def crab_shell_css() -> FileResponse:
        return _serve_static_file("crab-shell.css", "text/css")

    return app
