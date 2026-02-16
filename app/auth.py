import hmac
import ipaddress
import os
from pathlib import Path

from fastapi import Header, HTTPException, Request

from .state import STATE


async def require_agent(
    x_agent_key: str = Header(default=""),
    authorization: str = Header(default=""),
) -> str:
    token = (x_agent_key or "").strip()
    if not token and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing_agent_key_or_bearer_token")

    agent_id = STATE.key_to_agent.get(token)
    if not agent_id:
        raise HTTPException(status_code=403, detail="invalid_agent_key")
    return agent_id


def _client_ip(request: Request) -> str:
    cf_ip = str(request.headers.get("cf-connecting-ip", "")).strip()
    if cf_ip:
        return cf_ip
    xff = str(request.headers.get("x-forwarded-for", "")).strip()
    if xff:
        return xff.split(",", 1)[0].strip()
    client = request.client.host if request.client else ""
    return str(client or "").strip()


def _parse_admin_allowlist() -> list[ipaddress._BaseNetwork]:
    raw = str(os.getenv("CRAB_ADMIN_ALLOWLIST", "")).strip()
    if not raw:
        allowlist_file = Path(
            os.getenv("CRAB_ADMIN_ALLOWLIST_FILE", "~/.config/crab-trading/admin_allowlist")
        ).expanduser()
        try:
            if allowlist_file.exists():
                raw = allowlist_file.read_text(encoding="utf-8").strip()
        except Exception:
            raw = ""
    if not raw:
        return []
    entries = [item.strip() for item in raw.split(",") if item.strip()]
    networks: list[ipaddress._BaseNetwork] = []
    for item in entries:
        try:
            if "/" in item:
                networks.append(ipaddress.ip_network(item, strict=False))
            else:
                # Treat single IPs as /32 or /128.
                ip_obj = ipaddress.ip_address(item)
                suffix = "/32" if ip_obj.version == 4 else "/128"
                networks.append(ipaddress.ip_network(f"{item}{suffix}", strict=False))
        except ValueError:
            continue
    return networks


def _is_ip_allowed(ip_text: str, allowlist: list[ipaddress._BaseNetwork]) -> bool:
    if not allowlist:
        return True
    try:
        ip_obj = ipaddress.ip_address(str(ip_text or "").strip())
    except ValueError:
        return False
    return any(ip_obj in network for network in allowlist)


async def require_admin(
    request: Request,
    x_admin_token: str = Header(default=""),
) -> None:
    admin_token = str(os.getenv("CRAB_ADMIN_TOKEN", "")).strip()
    if not admin_token:
        token_file = Path(
            os.getenv("CRAB_ADMIN_TOKEN_FILE", "~/.config/crab-trading/admin_token")
        ).expanduser()
        try:
            if token_file.exists():
                admin_token = token_file.read_text(encoding="utf-8").strip()
        except Exception:
            admin_token = ""
    if not admin_token:
        raise HTTPException(status_code=503, detail="admin_not_configured")

    token = str(x_admin_token or "").strip()
    if not token or not hmac.compare_digest(token, admin_token):
        raise HTTPException(status_code=403, detail="invalid_admin_token")

    allowlist = _parse_admin_allowlist()
    if not _is_ip_allowed(_client_ip(request), allowlist):
        raise HTTPException(status_code=403, detail="admin_ip_not_allowed")
