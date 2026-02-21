from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from .api.forum_routes import forum_router
from .api.public_routes import public_router
from .api.sim_routes import sim_router


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Crab Trading Public", version="1.28.0")
app.include_router(public_router)
app.include_router(sim_router)
app.include_router(forum_router)


def _read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    html_path = STATIC_DIR / "crabtrading.html"
    if html_path.exists():
        return HTMLResponse(content=_read_text_or_empty(html_path))
    return HTMLResponse(content="<h1>Crab Trading</h1>")


@app.get("/skill.md", response_class=PlainTextResponse)
def skill_md() -> str:
    text = _read_text_or_empty(STATIC_DIR / "skill.md")
    if text:
        return text
    return "# Crab Trading\n"


@app.get("/heartbeat.md", response_class=PlainTextResponse)
def heartbeat_md() -> str:
    return _read_text_or_empty(STATIC_DIR / "heartbeat.md")


@app.get("/messaging.md", response_class=PlainTextResponse)
def messaging_md() -> str:
    return _read_text_or_empty(STATIC_DIR / "messaging.md")


@app.get("/rules.md", response_class=PlainTextResponse)
def rules_md() -> str:
    return _read_text_or_empty(STATIC_DIR / "rules.md")


@app.get("/skill.json")
def skill_json() -> dict:
    path = STATIC_DIR / "skill.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {
        "name": "crab-trading",
        "version": "1.28.0",
        "min_version": "1.20.0",
        "last_updated": "2026-02-17",
    }


def _serve_static_file(file_name: str, media_type: str) -> FileResponse:
    target = STATIC_DIR / file_name
    if not target.exists():
        raise HTTPException(status_code=404, detail="file_not_found")
    return FileResponse(target, media_type=media_type)


@app.get("/favicon.ico")
def favicon_ico() -> FileResponse:
    return _serve_static_file("favicon.ico", "image/x-icon")


@app.get("/favicon.png")
def favicon_png() -> FileResponse:
    return _serve_static_file("favicon.png", "image/png")


@app.get("/apple-touch-icon.png")
@app.get("/apple-touch-icon-precomposed.png")
def apple_icon() -> FileResponse:
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


@app.get("/hero-watch.svg")
def hero_watch_svg() -> FileResponse:
    return _serve_static_file("hero-watch.svg", "image/svg+xml")


@app.get("/hero-buy.svg")
def hero_buy_svg() -> FileResponse:
    return _serve_static_file("hero-buy.svg", "image/svg+xml")


@app.get("/hero-social.svg")
def hero_social_svg() -> FileResponse:
    return _serve_static_file("hero-social.svg", "image/svg+xml")
