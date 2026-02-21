from __future__ import annotations

import json
import os
import sqlite3
import secrets
import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from .models import RiskConfig


def _is_uuid_like(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        UUID(text)
        return True
    except Exception:
        return False


@dataclass
class AgentAccount:
    agent_uuid: str
    display_name: str
    cash: float
    registered_at: str = ""
    registration_ip: str = ""
    registration_country: str = ""
    registration_region: str = ""
    registration_city: str = ""
    registration_source: str = ""
    registration_lat: float = 0.0
    registration_lon: float = 0.0
    description: str = ""
    # Daily automation can update this snapshot when the agent traded that day.
    # If the agent does not trade, the previous summary is kept.
    strategy_summary: str = ""
    strategy_summary_day: str = ""
    avatar: str = "🦀"
    is_test: bool = False
    positions: Dict[str, float] = field(default_factory=dict)
    avg_cost: Dict[str, float] = field(default_factory=dict)
    realized_pnl: float = 0.0
    poly_positions: Dict[str, Dict[str, float]] = field(default_factory=dict)
    poly_cost_basis: Dict[str, Dict[str, float]] = field(default_factory=dict)
    poly_realized_pnl: float = 0.0
    blocked: bool = False

    @property
    def agent_id(self) -> str:
        return self.display_name

    @agent_id.setter
    def agent_id(self, value: str) -> None:
        self.display_name = str(value or "").strip()


@dataclass
class QuickHandoverToken:
    token_id: str
    token_hash: str
    owner_id: str
    follower_agent_uuid: str
    target_agent_uuid: str
    created_at: str
    expires_at: str
    consumed_at: str = ""
    consumed_key_id: str = ""
    status: str = "issued"
    telegram_chat_suffix: str = ""
    last_error_code: str = ""
    last_result: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QuickHandoverCallback:
    token_id: str
    owner_id: str
    follower_agent_uuid: str
    target_agent_uuid: str
    telegram_chat_id: str
    webhook_secret: str
    webhook_url: str
    webhook_id: int
    created_at: str
    updated_at: str
    status: str = "configured"
    last_error_code: str = ""


class TradingState:
    def __init__(self) -> None:
        self.lock = RLock()
        self.state_file = Path(
            os.getenv("CRAB_STATE_FILE", "~/.local/share/crab-trading/runtime_state.json")
        ).expanduser()
        self.db_file = Path(
            os.getenv("CRAB_STATE_DB", "~/.local/share/crab-trading/runtime_state.db")
        ).expanduser()
        self.legacy_forum_file = self.state_file.with_name("forum_state.json")

        # Agent identity model:
        # - accounts are keyed by immutable agent_uuid
        # - display_name is mutable and used in UI/API responses as "agent_id"
        self.accounts: Dict[str, AgentAccount] = {}
        self.agent_name_to_uuid: Dict[str, str] = {}
        self.agent_keys: Dict[str, str] = {}
        self.key_to_agent: Dict[str, str] = {}
        self.prices: Dict[str, float] = {"BTCUSDT": 45000.0, "ETHUSDT": 2500.0}
        self.risk_config = RiskConfig()
        self.forum_posts: list[dict] = []
        self.next_forum_post_id: int = 1
        self.forum_comments: list[dict] = []
        self.next_forum_comment_id: int = 1
        self.registration_challenges: Dict[str, dict] = {}
        self.pending_by_agent: Dict[str, str] = {}
        self.registration_by_api_key: Dict[str, str] = {}
        self.temp_follow_api_keys: Dict[str, dict] = {}
        self.agent_following: Dict[str, list] = {}
        self.follow_webhooks: Dict[str, list] = {}
        self.follow_webhook_deliveries: list[dict] = []
        self.next_follow_webhook_id: int = 1
        self.next_follow_webhook_delivery_id: int = 1
        self.quick_handover_tokens: Dict[str, dict] = {}
        self.quick_handover_callbacks: Dict[str, dict] = {}
        self.openclaw_nonces: Dict[str, dict] = {}
        self.stock_prices: Dict[str, float] = {
            "AAPL": 210.0,
            "TSLA": 185.0,
            "NVDA": 125.0,
            "MSFT": 420.0,
            "BTCUSD": 45000.0,
            "ETHUSD": 2500.0,
        }
        self.poly_markets: Dict[str, dict] = {
            "poly-us-recession-2026": {
                "market_id": "poly-us-recession-2026",
                "question": "Will the US enter recession in 2026?",
                "outcomes": {"YES": 0.42, "NO": 0.58},
                "resolved": False,
                "winning_outcome": "",
            },
            "poly-btc-150k-2026": {
                "market_id": "poly-btc-150k-2026",
                "question": "Will BTC touch 150k before 2027?",
                "outcomes": {"YES": 0.35, "NO": 0.65},
                "resolved": False,
                "winning_outcome": "",
            },
        }
        self.activity_log: list[dict] = []
        self.next_activity_id: int = 1
        self.test_agents: set[str] = set()
        self._load_runtime_state()

    def _sqlite_connect_unlocked(self) -> sqlite3.Connection:
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_file), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _sqlite_init_schema_unlocked(self) -> None:
        conn = self._sqlite_connect_unlocked()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state_store (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _sqlite_load_payload_unlocked(self) -> Optional[dict]:
        self._sqlite_init_schema_unlocked()
        conn = self._sqlite_connect_unlocked()
        try:
            row = conn.execute("SELECT payload FROM state_store WHERE id = 1").fetchone()
            if not row:
                return None
            payload = json.loads(str(row[0]))
            if not isinstance(payload, dict):
                return None
            return payload
        finally:
            conn.close()

    def _sqlite_save_payload_unlocked(self, payload: dict) -> None:
        self._sqlite_init_schema_unlocked()
        conn = self._sqlite_connect_unlocked()
        try:
            conn.execute(
                """
                INSERT INTO state_store (id, payload, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (
                    json.dumps(payload, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _account_from_dict(self, payload: dict, fallback_identifier: str = "") -> AgentAccount:
        fallback = str(fallback_identifier or "").strip()
        raw_uuid = str(payload.get("agent_uuid", "")).strip()
        if _is_uuid_like(raw_uuid):
            agent_uuid = raw_uuid
        elif _is_uuid_like(fallback):
            agent_uuid = fallback
        else:
            agent_uuid = str(uuid4())

        display_name = str(
            payload.get("display_name")
            or payload.get("agent_id")
            or fallback
            or f"agent-{agent_uuid[:8]}"
        ).strip()
        avatar = str(payload.get("avatar") or "🦀").strip() or "🦀"
        raw_poly_positions = payload.get("poly_positions", {})
        raw_poly_cost_basis = payload.get("poly_cost_basis", {})

        poly_positions: Dict[str, Dict[str, float]] = {}
        if isinstance(raw_poly_positions, dict):
            for market_id, outcomes in raw_poly_positions.items():
                if not isinstance(outcomes, dict):
                    continue
                normalized_outcomes: Dict[str, float] = {}
                for outcome, shares in outcomes.items():
                    try:
                        normalized_outcomes[str(outcome).upper()] = float(shares or 0.0)
                    except Exception:
                        continue
                if normalized_outcomes:
                    poly_positions[str(market_id)] = normalized_outcomes

        poly_cost_basis: Dict[str, Dict[str, float]] = {}
        if isinstance(raw_poly_cost_basis, dict):
            for market_id, outcomes in raw_poly_cost_basis.items():
                if not isinstance(outcomes, dict):
                    continue
                normalized_costs: Dict[str, float] = {}
                for outcome, amount in outcomes.items():
                    try:
                        normalized_costs[str(outcome).upper()] = float(amount or 0.0)
                    except Exception:
                        continue
                if normalized_costs:
                    poly_cost_basis[str(market_id)] = normalized_costs

        return AgentAccount(
            agent_uuid=agent_uuid,
            display_name=display_name,
            registered_at=str(payload.get("registered_at", "") or "").strip(),
            registration_ip=str(payload.get("registration_ip", "") or "").strip(),
            registration_country=str(payload.get("registration_country", "") or "").strip(),
            registration_region=str(payload.get("registration_region", "") or "").strip(),
            registration_city=str(payload.get("registration_city", "") or "").strip(),
            registration_source=str(payload.get("registration_source", "") or "").strip(),
            registration_lat=float(payload.get("registration_lat", 0.0) or 0.0),
            registration_lon=float(payload.get("registration_lon", 0.0) or 0.0),
            description=str(payload.get("description", "") or payload.get("about", "") or "").strip(),
            strategy_summary=str(payload.get("strategy_summary", "") or "").strip(),
            strategy_summary_day=str(payload.get("strategy_summary_day", "") or "").strip(),
            cash=float(payload.get("cash", 0.0)),
            avatar=avatar,
            is_test=bool(payload.get("is_test", False)),
            positions=dict(payload.get("positions", {})),
            avg_cost=dict(payload.get("avg_cost", {})),
            realized_pnl=float(payload.get("realized_pnl", 0.0)),
            poly_positions=poly_positions,
            poly_cost_basis=poly_cost_basis,
            poly_realized_pnl=float(payload.get("poly_realized_pnl", 0.0)),
            blocked=bool(payload.get("blocked", False)),
        )

    def _derive_next_forum_post_id(self) -> int:
        if not self.forum_posts:
            return 1
        max_id = max(int(p.get("post_id", 0)) for p in self.forum_posts if isinstance(p, dict))
        return max(max_id + 1, 1)

    def _derive_next_forum_comment_id(self) -> int:
        if not self.forum_comments:
            return 1
        max_id = max(int(c.get("comment_id", 0)) for c in self.forum_comments if isinstance(c, dict))
        return max(max_id + 1, 1)

    def _derive_next_activity_id(self) -> int:
        if not self.activity_log:
            return 1
        max_id = max(int(e.get("id", 0)) for e in self.activity_log if isinstance(e, dict))
        return max(max_id + 1, 1)

    def _derive_next_follow_webhook_id(self) -> int:
        max_id = 0
        for configs in self.follow_webhooks.values():
            if not isinstance(configs, list):
                continue
            for item in configs:
                if not isinstance(item, dict):
                    continue
                try:
                    max_id = max(max_id, int(item.get("webhook_id", 0) or 0))
                except Exception:
                    continue
        return max(max_id + 1, 1)

    def _derive_next_follow_webhook_delivery_id(self) -> int:
        if not self.follow_webhook_deliveries:
            return 1
        max_id = 0
        for row in self.follow_webhook_deliveries:
            if not isinstance(row, dict):
                continue
            try:
                max_id = max(max_id, int(row.get("delivery_id", 0) or 0))
            except Exception:
                continue
        return max(max_id + 1, 1)

    def _load_legacy_forum_only(self) -> None:
        if not self.legacy_forum_file.exists():
            return
        raw = json.loads(self.legacy_forum_file.read_text(encoding="utf-8"))
        posts = raw.get("forum_posts", [])
        if isinstance(posts, list):
            self.forum_posts = [p for p in posts if isinstance(p, dict)]
            self.next_forum_post_id = int(raw.get("next_forum_post_id", 0)) or self._derive_next_forum_post_id()

    def _load_runtime_state(self) -> None:
        with self.lock:
            migration_changed = False
            migrated_from_json = False
            try:
                raw = self._sqlite_load_payload_unlocked()
                if raw is None and self.state_file.exists():
                    raw = json.loads(self.state_file.read_text(encoding="utf-8"))
                    migrated_from_json = isinstance(raw, dict)
                if raw is None and not self.state_file.exists():
                    self._load_legacy_forum_only()
                    return
                if not isinstance(raw, dict):
                    return

                accounts_raw = raw.get("accounts", {})
                if isinstance(accounts_raw, dict):
                    loaded_accounts = {}
                    for account_identifier, payload in accounts_raw.items():
                        if isinstance(payload, dict):
                            account = self._account_from_dict(payload, fallback_identifier=str(account_identifier))
                            loaded_accounts[account.agent_uuid] = account
                    self.accounts = loaded_accounts
                else:
                    self.accounts = {}

                # Normalize display name uniqueness and build name index.
                name_to_uuid: Dict[str, str] = {}
                normalized_accounts: Dict[str, AgentAccount] = {}
                for account in self.accounts.values():
                    agent_uuid = account.agent_uuid
                    name = (account.display_name or "").strip() or f"agent-{agent_uuid[:8]}"
                    base = name
                    suffix = 2
                    while name in name_to_uuid and name_to_uuid[name] != agent_uuid:
                        name = f"{base}_{suffix}"
                        suffix += 1
                    if account.display_name != name:
                        account.display_name = name
                        migration_changed = True
                    normalized_accounts[agent_uuid] = account
                    name_to_uuid[name] = agent_uuid
                self.accounts = normalized_accounts
                self.agent_name_to_uuid = name_to_uuid

                def resolve_uuid(identifier: str) -> Optional[str]:
                    ident = str(identifier or "").strip()
                    if not ident:
                        return None
                    if ident in self.accounts:
                        return ident
                    return self.agent_name_to_uuid.get(ident)

                if isinstance(raw.get("agent_keys"), dict):
                    normalized_agent_keys: Dict[str, str] = {}
                    for ident, token in raw["agent_keys"].items():
                        uuid_value = resolve_uuid(str(ident))
                        token_value = str(token or "").strip()
                        if uuid_value and token_value:
                            normalized_agent_keys[uuid_value] = token_value
                    self.agent_keys = normalized_agent_keys
                else:
                    self.agent_keys = {}

                if isinstance(raw.get("key_to_agent"), dict):
                    normalized_key_to_agent: Dict[str, str] = {}
                    for token, ident in raw["key_to_agent"].items():
                        token_value = str(token or "").strip()
                        uuid_value = resolve_uuid(str(ident))
                        if token_value and uuid_value:
                            normalized_key_to_agent[token_value] = uuid_value
                    self.key_to_agent = normalized_key_to_agent
                else:
                    self.key_to_agent = {}

                # Reconcile key maps in case only one side exists.
                for uuid_value, token in self.agent_keys.items():
                    if token and token not in self.key_to_agent:
                        self.key_to_agent[token] = uuid_value
                        migration_changed = True
                for token, uuid_value in list(self.key_to_agent.items()):
                    if uuid_value not in self.agent_keys:
                        self.agent_keys[uuid_value] = token
                        migration_changed = True

                if isinstance(raw.get("registration_challenges"), dict):
                    self.registration_challenges = dict(raw["registration_challenges"])
                if isinstance(raw.get("pending_by_agent"), dict):
                    self.pending_by_agent = dict(raw["pending_by_agent"])
                if isinstance(raw.get("registration_by_api_key"), dict):
                    self.registration_by_api_key = dict(raw["registration_by_api_key"])
                temp_follow_raw = raw.get("temp_follow_api_keys", {})
                if isinstance(temp_follow_raw, dict):
                    normalized_temp_follow: Dict[str, dict] = {}
                    now_ts = int(datetime.now(timezone.utc).timestamp())
                    for token, payload in temp_follow_raw.items():
                        token_value = str(token or "").strip()
                        if not token_value or not isinstance(payload, dict):
                            continue
                        agent_uuid = resolve_uuid(str(payload.get("agent_uuid", "")))
                        if not agent_uuid:
                            continue
                        try:
                            expires_at = int(payload.get("expires_at", 0) or 0)
                        except Exception:
                            expires_at = 0
                        if expires_at <= now_ts:
                            continue
                        normalized_temp_follow[token_value] = {
                            "agent_uuid": agent_uuid,
                            "scope": "follow",
                            "issued_at": int(payload.get("issued_at", now_ts) or now_ts),
                            "expires_at": expires_at,
                        }
                    self.temp_follow_api_keys = normalized_temp_follow
                else:
                    self.temp_follow_api_keys = {}
                following_raw = raw.get("agent_following", {})
                if isinstance(following_raw, dict):
                    normalized_following: Dict[str, list] = {}
                    for follower_identifier, targets in following_raw.items():
                        follower_uuid = resolve_uuid(str(follower_identifier))
                        if not follower_uuid or not isinstance(targets, list):
                            continue
                        deduped: list = []
                        seen = set()
                        for target in targets:
                            if isinstance(target, dict):
                                target_identifier = (
                                    str(target.get("agent_uuid", "")).strip()
                                    or str(target.get("target_agent_uuid", "")).strip()
                                    or str(target.get("agent_id", "")).strip()
                                    or str(target.get("target_agent_id", "")).strip()
                                )
                                target_uuid = resolve_uuid(target_identifier)
                                if not target_uuid or target_uuid in seen:
                                    continue
                                normalized_target = dict(target)
                                normalized_target["agent_uuid"] = target_uuid
                                deduped.append(normalized_target)
                                seen.add(target_uuid)
                                continue

                            target_uuid = resolve_uuid(str(target))
                            if not target_uuid or target_uuid in seen:
                                continue
                            deduped.append(target_uuid)
                            seen.add(target_uuid)
                        normalized_following[follower_uuid] = deduped
                    self.agent_following = normalized_following
                else:
                    self.agent_following = {}

                follow_webhooks_raw = raw.get("follow_webhooks", {})
                if isinstance(follow_webhooks_raw, dict):
                    normalized_follow_webhooks: Dict[str, list] = {}
                    for follower_identifier, configs in follow_webhooks_raw.items():
                        follower_uuid = resolve_uuid(str(follower_identifier))
                        if not follower_uuid or not isinstance(configs, list):
                            continue
                        normalized_configs: list[dict] = []
                        for item in configs:
                            if not isinstance(item, dict):
                                continue
                            try:
                                webhook_id = int(item.get("webhook_id", 0) or 0)
                            except Exception:
                                webhook_id = 0
                            target_identifier = (
                                str(item.get("target_agent_uuid", "")).strip()
                                or str(item.get("target_agent_id", "")).strip()
                                or str(item.get("agent_uuid", "")).strip()
                                or str(item.get("agent_id", "")).strip()
                            )
                            target_uuid = resolve_uuid(target_identifier) or str(item.get("target_agent_uuid", "")).strip()
                            if not target_uuid:
                                continue
                            normalized_configs.append(
                                {
                                    "webhook_id": webhook_id,
                                    "target_agent_uuid": target_uuid,
                                    "url": str(item.get("url", "")).strip(),
                                    "secret_enc": str(item.get("secret_enc", "")).strip(),
                                    "enabled": bool(item.get("enabled", True)),
                                    "events": list(item.get("events", [])) if isinstance(item.get("events", []), list) else [],
                                    "orphaned": bool(item.get("orphaned", False)),
                                    "created_at": str(item.get("created_at", "")).strip(),
                                    "updated_at": str(item.get("updated_at", "")).strip(),
                                }
                            )
                        normalized_follow_webhooks[follower_uuid] = normalized_configs
                    self.follow_webhooks = normalized_follow_webhooks
                else:
                    self.follow_webhooks = {}

                deliveries_raw = raw.get("follow_webhook_deliveries", [])
                if isinstance(deliveries_raw, list):
                    self.follow_webhook_deliveries = [row for row in deliveries_raw if isinstance(row, dict)]
                else:
                    self.follow_webhook_deliveries = []
                next_webhook_id = raw.get("next_follow_webhook_id")
                if isinstance(next_webhook_id, int) and next_webhook_id > 0:
                    self.next_follow_webhook_id = next_webhook_id
                else:
                    self.next_follow_webhook_id = self._derive_next_follow_webhook_id()
                next_delivery_id = raw.get("next_follow_webhook_delivery_id")
                if isinstance(next_delivery_id, int) and next_delivery_id > 0:
                    self.next_follow_webhook_delivery_id = next_delivery_id
                else:
                    self.next_follow_webhook_delivery_id = self._derive_next_follow_webhook_delivery_id()
                quick_tokens_raw = raw.get("quick_handover_tokens", {})
                if isinstance(quick_tokens_raw, dict):
                    normalized_quick_tokens: Dict[str, dict] = {}
                    now_dt = datetime.now(timezone.utc)
                    for token_id, item in quick_tokens_raw.items():
                        token_key = str(token_id or "").strip()
                        if not token_key or not isinstance(item, dict):
                            continue
                        token_hash = str(item.get("token_hash", "")).strip().lower()
                        owner_id = str(item.get("owner_id", "")).strip()
                        follower_uuid = resolve_uuid(str(item.get("follower_agent_uuid", "")))
                        target_uuid = resolve_uuid(str(item.get("target_agent_uuid", "")))
                        if not token_hash or not owner_id or not follower_uuid or not target_uuid:
                            continue
                        created_at = str(item.get("created_at", "")).strip()
                        expires_at = str(item.get("expires_at", "")).strip()
                        try:
                            expires_dt = datetime.fromisoformat(expires_at).astimezone(timezone.utc) if expires_at else None
                        except Exception:
                            expires_dt = None
                        status = str(item.get("status", "issued")).strip().lower() or "issued"
                        if status == "issued" and expires_dt is not None and expires_dt <= now_dt:
                            status = "expired"
                        normalized_quick_tokens[token_key] = asdict(
                            QuickHandoverToken(
                                token_id=token_key,
                                token_hash=token_hash,
                                owner_id=owner_id,
                                follower_agent_uuid=follower_uuid,
                                target_agent_uuid=target_uuid,
                                created_at=created_at,
                                expires_at=expires_at,
                                consumed_at=str(item.get("consumed_at", "")).strip(),
                                consumed_key_id=str(item.get("consumed_key_id", "")).strip(),
                                status=status,
                                telegram_chat_suffix=str(item.get("telegram_chat_suffix", "")).strip(),
                                last_error_code=str(item.get("last_error_code", "")).strip(),
                                last_result=dict(item.get("last_result", {}))
                                if isinstance(item.get("last_result", {}), dict)
                                else {},
                            )
                        )
                    self.quick_handover_tokens = normalized_quick_tokens
                else:
                    self.quick_handover_tokens = {}

                quick_callbacks_raw = raw.get("quick_handover_callbacks", {})
                if isinstance(quick_callbacks_raw, dict):
                    normalized_callbacks: Dict[str, dict] = {}
                    for token_id, item in quick_callbacks_raw.items():
                        token_key = str(token_id or "").strip()
                        if not token_key or not isinstance(item, dict):
                            continue
                        follower_uuid = resolve_uuid(str(item.get("follower_agent_uuid", "")))
                        target_uuid = resolve_uuid(str(item.get("target_agent_uuid", "")))
                        if not follower_uuid or not target_uuid:
                            continue
                        normalized_callbacks[token_key] = asdict(
                            QuickHandoverCallback(
                                token_id=token_key,
                                owner_id=str(item.get("owner_id", "")).strip(),
                                follower_agent_uuid=follower_uuid,
                                target_agent_uuid=target_uuid,
                                telegram_chat_id=str(item.get("telegram_chat_id", "")).strip(),
                                webhook_secret=str(item.get("webhook_secret", "")).strip(),
                                webhook_url=str(item.get("webhook_url", "")).strip(),
                                webhook_id=int(item.get("webhook_id", 0) or 0),
                                created_at=str(item.get("created_at", "")).strip(),
                                updated_at=str(item.get("updated_at", "")).strip(),
                                status=str(item.get("status", "configured")).strip() or "configured",
                                last_error_code=str(item.get("last_error_code", "")).strip(),
                            )
                        )
                    self.quick_handover_callbacks = normalized_callbacks
                else:
                    self.quick_handover_callbacks = {}

                nonces_raw = raw.get("openclaw_nonces", {})
                if isinstance(nonces_raw, dict):
                    normalized_nonces: Dict[str, dict] = {}
                    now_ts = int(datetime.now(timezone.utc).timestamp())
                    for nonce_key, item in nonces_raw.items():
                        key = str(nonce_key or "").strip()
                        if not key or not isinstance(item, dict):
                            continue
                        try:
                            expires_at = int(item.get("expires_at", 0) or 0)
                        except Exception:
                            expires_at = 0
                        if expires_at <= now_ts:
                            continue
                        normalized_nonces[key] = {
                            "created_at": int(item.get("created_at", now_ts) or now_ts),
                            "expires_at": expires_at,
                        }
                    self.openclaw_nonces = normalized_nonces
                else:
                    self.openclaw_nonces = {}
                if isinstance(raw.get("stock_prices"), dict):
                    self.stock_prices = dict(raw["stock_prices"])
                if isinstance(raw.get("poly_markets"), dict):
                    self.poly_markets = dict(raw["poly_markets"])
                if isinstance(raw.get("test_agents"), list):
                    normalized_test_agents = set()
                    for identifier in raw["test_agents"]:
                        if not isinstance(identifier, str):
                            continue
                        agent_uuid = resolve_uuid(identifier)
                        if agent_uuid:
                            normalized_test_agents.add(agent_uuid)
                    self.test_agents = normalized_test_agents
                else:
                    self.test_agents = set()

                posts = raw.get("forum_posts", [])
                if isinstance(posts, list):
                    self.forum_posts = [p for p in posts if isinstance(p, dict)]
                else:
                    self.forum_posts = []
                next_post_id = raw.get("next_forum_post_id")
                if isinstance(next_post_id, int) and next_post_id > 0:
                    self.next_forum_post_id = next_post_id
                else:
                    self.next_forum_post_id = self._derive_next_forum_post_id()

                comments = raw.get("forum_comments", [])
                if isinstance(comments, list):
                    self.forum_comments = [c for c in comments if isinstance(c, dict)]
                else:
                    self.forum_comments = []
                next_comment_id = raw.get("next_forum_comment_id")
                if isinstance(next_comment_id, int) and next_comment_id > 0:
                    self.next_forum_comment_id = next_comment_id
                else:
                    self.next_forum_comment_id = self._derive_next_forum_comment_id()

                events = raw.get("activity_log", [])
                if isinstance(events, list):
                    self.activity_log = [e for e in events if isinstance(e, dict)]
                else:
                    self.activity_log = []
                next_event_id = raw.get("next_activity_id")
                if isinstance(next_event_id, int) and next_event_id > 0:
                    self.next_activity_id = next_event_id
                else:
                    self.next_activity_id = self._derive_next_activity_id()

                # Migrate forum/posts/comments/events to include UUID + latest display names.
                for post in self.forum_posts:
                    agent_uuid = str(post.get("agent_uuid", "")).strip()
                    if not agent_uuid:
                        agent_uuid = resolve_uuid(str(post.get("agent_id", ""))) or ""
                        if agent_uuid:
                            post["agent_uuid"] = agent_uuid
                            migration_changed = True
                    if agent_uuid and agent_uuid in self.accounts:
                        display_name = self.accounts[agent_uuid].display_name
                        if str(post.get("agent_id", "")).strip() != display_name:
                            post["agent_id"] = display_name
                            migration_changed = True

                for comment in self.forum_comments:
                    agent_uuid = str(comment.get("agent_uuid", "")).strip()
                    if not agent_uuid:
                        agent_uuid = resolve_uuid(str(comment.get("agent_id", ""))) or ""
                        if agent_uuid:
                            comment["agent_uuid"] = agent_uuid
                            migration_changed = True
                    if agent_uuid and agent_uuid in self.accounts:
                        display_name = self.accounts[agent_uuid].display_name
                        if str(comment.get("agent_id", "")).strip() != display_name:
                            comment["agent_id"] = display_name
                            migration_changed = True

                for event in self.activity_log:
                    agent_uuid = str(event.get("agent_uuid", "")).strip()
                    if not agent_uuid:
                        agent_uuid = resolve_uuid(str(event.get("agent_id", ""))) or ""
                        if agent_uuid:
                            event["agent_uuid"] = agent_uuid
                            migration_changed = True
                    if agent_uuid and agent_uuid in self.accounts:
                        display_name = self.accounts[agent_uuid].display_name
                        if str(event.get("agent_id", "")).strip() != display_name:
                            event["agent_id"] = display_name
                            migration_changed = True

                for agent_uuid, account in self.accounts.items():
                    if not isinstance(account.poly_cost_basis, dict):
                        account.poly_cost_basis = {}
                        migration_changed = True
                    for market_id, outcomes in account.poly_positions.items():
                        if not isinstance(outcomes, dict):
                            continue
                        market_costs = account.poly_cost_basis.get(market_id)
                        if not isinstance(market_costs, dict):
                            market_costs = {}
                            account.poly_cost_basis[market_id] = market_costs
                            migration_changed = True
                        for outcome, _shares in outcomes.items():
                            if outcome in market_costs:
                                continue
                            # Legacy data may not have explicit Poly cost basis.
                            # Keep as zero and recover from historical poly_bet events at resolve time.
                            market_costs[outcome] = 0.0
                            migration_changed = True
                    if account.is_test:
                        self.test_agents.add(agent_uuid)
                for post in self.forum_posts:
                    if bool(post.get("is_test")):
                        agent_uuid = str(post.get("agent_uuid", "")).strip()
                        if agent_uuid:
                            self.test_agents.add(agent_uuid)
                for comment in self.forum_comments:
                    if bool(comment.get("is_test")):
                        agent_uuid = str(comment.get("agent_uuid", "")).strip()
                        if agent_uuid:
                            self.test_agents.add(agent_uuid)

                if migration_changed:
                    try:
                        self.save_runtime_state()
                    except Exception:
                        pass
                elif migrated_from_json:
                    # One-time migration path: persist legacy JSON state into SQLite.
                    try:
                        self.save_runtime_state()
                    except Exception:
                        pass
            except Exception:
                # Keep service available even if persisted file is corrupted.
                self.accounts = {}
                self.agent_name_to_uuid = {}
                self.agent_keys = {}
                self.key_to_agent = {}
                self.registration_challenges = {}
                self.pending_by_agent = {}
                self.registration_by_api_key = {}
                self.agent_following = {}
                self.follow_webhooks = {}
                self.follow_webhook_deliveries = []
                self.next_follow_webhook_id = 1
                self.next_follow_webhook_delivery_id = 1
                self.quick_handover_tokens = {}
                self.quick_handover_callbacks = {}
                self.openclaw_nonces = {}
                self.forum_posts = []
                self.next_forum_post_id = 1
                self.forum_comments = []
                self.next_forum_comment_id = 1
                self.activity_log = []
                self.next_activity_id = 1
                self.test_agents = set()

    def _resolve_agent_uuid_unlocked(self, identifier: str) -> Optional[str]:
        ident = str(identifier or "").strip()
        if not ident:
            return None
        if ident in self.accounts:
            return ident
        return self.agent_name_to_uuid.get(ident)

    def resolve_agent_uuid(self, identifier: str) -> Optional[str]:
        with self.lock:
            return self._resolve_agent_uuid_unlocked(identifier)

    def display_name_for(self, identifier: str) -> str:
        with self.lock:
            agent_uuid = self._resolve_agent_uuid_unlocked(identifier)
            if not agent_uuid:
                return str(identifier or "").strip()
            account = self.accounts.get(agent_uuid)
            return account.display_name if account else str(identifier or "").strip()

    def record_operation(
        self,
        op_type: str,
        agent_uuid: str = "",
        details: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
    ) -> dict:
        with self.lock:
            display_name = str(agent_id or "").strip()
            normalized_uuid = self._resolve_agent_uuid_unlocked(agent_uuid) or str(agent_uuid or "").strip()
            if not display_name and normalized_uuid:
                account = self.accounts.get(normalized_uuid)
                if account:
                    display_name = account.display_name
            event = {
                "id": self.next_activity_id,
                "type": op_type,
                "agent_uuid": normalized_uuid,
                "agent_id": display_name,
                "details": details or {},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self.next_activity_id += 1
            self.activity_log.append(event)
            if len(self.activity_log) > 5000:
                self.activity_log = self.activity_log[-5000:]
            return event

    def save_runtime_state(self) -> None:
        with self.lock:
            payload = {
                "version": 5,
                "accounts": {agent_uuid: asdict(account) for agent_uuid, account in self.accounts.items()},
                "agent_name_to_uuid": self.agent_name_to_uuid,
                "agent_keys": self.agent_keys,
                "key_to_agent": self.key_to_agent,
                "registration_challenges": self.registration_challenges,
                "pending_by_agent": self.pending_by_agent,
                "registration_by_api_key": self.registration_by_api_key,
                "temp_follow_api_keys": self.temp_follow_api_keys,
                "agent_following": self.agent_following,
                "follow_webhooks": self.follow_webhooks,
                "follow_webhook_deliveries": self.follow_webhook_deliveries,
                "next_follow_webhook_id": self.next_follow_webhook_id,
                "next_follow_webhook_delivery_id": self.next_follow_webhook_delivery_id,
                "quick_handover_tokens": self.quick_handover_tokens,
                "quick_handover_callbacks": self.quick_handover_callbacks,
                "openclaw_nonces": self.openclaw_nonces,
                "forum_posts": self.forum_posts,
                "next_forum_post_id": self.next_forum_post_id,
                "forum_comments": self.forum_comments,
                "next_forum_comment_id": self.next_forum_comment_id,
                "stock_prices": self.stock_prices,
                "poly_markets": self.poly_markets,
                "activity_log": self.activity_log,
                "next_activity_id": self.next_activity_id,
                "test_agents": sorted(self.test_agents),
            }
            self._sqlite_save_payload_unlocked(payload)

    @staticmethod
    def _quick_handover_token_hash(token: str) -> str:
        return hashlib.sha256(str(token or "").strip().encode("utf-8")).hexdigest()

    @staticmethod
    def _quick_handover_chat_suffix(chat_id: str) -> str:
        text = str(chat_id or "").strip()
        if not text:
            return ""
        if len(text) <= 4:
            return text
        return text[-4:]

    def _cleanup_openclaw_nonces_unlocked(self) -> None:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        for key, row in list(self.openclaw_nonces.items()):
            try:
                expires_at = int((row or {}).get("expires_at", 0) or 0)
            except Exception:
                expires_at = 0
            if expires_at <= now_ts:
                self.openclaw_nonces.pop(key, None)

    def _cleanup_quick_handover_expiry_unlocked(self) -> None:
        now_dt = datetime.now(timezone.utc)
        for token_id, row in self.quick_handover_tokens.items():
            if not isinstance(row, dict):
                continue
            status = str(row.get("status", "issued")).strip().lower()
            if status != "issued":
                continue
            expires_at = str(row.get("expires_at", "")).strip()
            if not expires_at:
                continue
            try:
                expires_dt = datetime.fromisoformat(expires_at)
                if expires_dt.tzinfo is None:
                    expires_dt = expires_dt.replace(tzinfo=timezone.utc)
                expires_dt = expires_dt.astimezone(timezone.utc)
            except Exception:
                continue
            if expires_dt <= now_dt:
                row["status"] = "expired"
                row["last_error_code"] = str(row.get("last_error_code", "") or "quick_token_expired")

    def issue_quick_handover_token(
        self,
        *,
        owner_id: str,
        follower_agent_uuid: str,
        target_agent_uuid: str,
        ttl_minutes: int = 5,
    ) -> dict:
        with self.lock:
            follower_uuid = self._resolve_agent_uuid_unlocked(str(follower_agent_uuid or "").strip())
            target_uuid = self._resolve_agent_uuid_unlocked(str(target_agent_uuid or "").strip())
            owner = str(owner_id or "").strip()
            if not owner:
                raise ValueError("owner_not_found")
            if not follower_uuid:
                raise ValueError("follower_agent_not_found")
            if not target_uuid:
                raise ValueError("target_agent_not_found")
            ttl = max(1, min(int(ttl_minutes or 5), 30))
            now_dt = datetime.now(timezone.utc)
            created_at = now_dt.isoformat()
            expires_at = now_dt.replace(microsecond=0).timestamp() + ttl * 60
            expires_iso = datetime.fromtimestamp(int(expires_at), tz=timezone.utc).isoformat()
            token_id = f"qht_{secrets.token_urlsafe(9)}"
            quick_token = f"qhtk_{secrets.token_urlsafe(24)}"
            token_hash = self._quick_handover_token_hash(quick_token)
            while token_id in self.quick_handover_tokens:
                token_id = f"qht_{secrets.token_urlsafe(9)}"
            while any(
                str((row or {}).get("token_hash", "")).strip().lower() == token_hash
                for row in self.quick_handover_tokens.values()
                if isinstance(row, dict)
            ):
                quick_token = f"qhtk_{secrets.token_urlsafe(24)}"
                token_hash = self._quick_handover_token_hash(quick_token)
            row = asdict(
                QuickHandoverToken(
                    token_id=token_id,
                    token_hash=token_hash,
                    owner_id=owner,
                    follower_agent_uuid=follower_uuid,
                    target_agent_uuid=target_uuid,
                    created_at=created_at,
                    expires_at=expires_iso,
                )
            )
            self.quick_handover_tokens[token_id] = row
            self._cleanup_quick_handover_expiry_unlocked()
            self.save_runtime_state()
            out = dict(row)
            out["quick_token"] = quick_token
            return out

    def _find_quick_handover_by_hash_unlocked(self, token_hash: str) -> tuple[str, Optional[dict]]:
        needle = str(token_hash or "").strip().lower()
        if not needle:
            return "", None
        for token_id, row in self.quick_handover_tokens.items():
            if not isinstance(row, dict):
                continue
            if str(row.get("token_hash", "")).strip().lower() == needle:
                return token_id, row
        return "", None

    def get_quick_handover_token(self, token_id: str) -> Optional[dict]:
        with self.lock:
            self._cleanup_quick_handover_expiry_unlocked()
            row = self.quick_handover_tokens.get(str(token_id or "").strip())
            if not isinstance(row, dict):
                return None
            return dict(row)

    def get_quick_handover_by_token(self, quick_token: str) -> Optional[dict]:
        with self.lock:
            self._cleanup_quick_handover_expiry_unlocked()
            token_hash = self._quick_handover_token_hash(str(quick_token or "").strip())
            token_id, row = self._find_quick_handover_by_hash_unlocked(token_hash)
            if not token_id or not isinstance(row, dict):
                return None
            out = dict(row)
            out["token_id"] = token_id
            return out

    def consume_quick_handover_token(
        self,
        *,
        quick_token: str,
        telegram_chat_id: str,
        consumed_key_id: str = "",
    ) -> dict:
        with self.lock:
            self._cleanup_quick_handover_expiry_unlocked()
            token_hash = self._quick_handover_token_hash(str(quick_token or "").strip())
            token_id, row = self._find_quick_handover_by_hash_unlocked(token_hash)
            if not token_id or not isinstance(row, dict):
                raise RuntimeError("quick_token_not_found")

            status = str(row.get("status", "issued")).strip().lower()
            if status == "expired":
                raise RuntimeError("quick_token_expired")
            if str(row.get("consumed_at", "")).strip():
                raise RuntimeError("quick_token_replay")

            expires_at = str(row.get("expires_at", "")).strip()
            expires_dt = None
            if expires_at:
                try:
                    expires_dt = datetime.fromisoformat(expires_at)
                    if expires_dt.tzinfo is None:
                        expires_dt = expires_dt.replace(tzinfo=timezone.utc)
                    expires_dt = expires_dt.astimezone(timezone.utc)
                except Exception:
                    expires_dt = None
            if expires_dt is not None and expires_dt <= datetime.now(timezone.utc):
                row["status"] = "expired"
                row["last_error_code"] = "quick_token_expired"
                self.quick_handover_tokens[token_id] = row
                self.save_runtime_state()
                raise RuntimeError("quick_token_expired")

            row["consumed_at"] = datetime.now(timezone.utc).isoformat()
            row["consumed_key_id"] = str(consumed_key_id or "").strip()
            row["status"] = "consumed_pending"
            row["telegram_chat_suffix"] = self._quick_handover_chat_suffix(telegram_chat_id)
            self.quick_handover_tokens[token_id] = row
            self.save_runtime_state()

            out = dict(row)
            out["token_id"] = token_id
            return out

    def finalize_quick_handover(
        self,
        *,
        token_id: str,
        status: str,
        result: Optional[dict] = None,
        error_code: str = "",
    ) -> Optional[dict]:
        with self.lock:
            key = str(token_id or "").strip()
            row = self.quick_handover_tokens.get(key)
            if not isinstance(row, dict):
                return None
            row["status"] = str(status or "").strip().lower() or "consumed_failed"
            row["last_error_code"] = str(error_code or "").strip()
            row["last_result"] = dict(result or {}) if isinstance(result, dict) else {}
            self.quick_handover_tokens[key] = row
            self.save_runtime_state()
            return dict(row)

    def upsert_quick_handover_callback(
        self,
        *,
        token_id: str,
        owner_id: str,
        follower_agent_uuid: str,
        target_agent_uuid: str,
        telegram_chat_id: str,
        webhook_secret: str,
        webhook_url: str,
        webhook_id: int,
        status: str = "configured",
        error_code: str = "",
    ) -> dict:
        with self.lock:
            token_key = str(token_id or "").strip()
            now_iso = datetime.now(timezone.utc).isoformat()
            existing = self.quick_handover_callbacks.get(token_key)
            created_at = str((existing or {}).get("created_at", "")).strip() if isinstance(existing, dict) else ""
            if not created_at:
                created_at = now_iso
            row = asdict(
                QuickHandoverCallback(
                    token_id=token_key,
                    owner_id=str(owner_id or "").strip(),
                    follower_agent_uuid=str(follower_agent_uuid or "").strip(),
                    target_agent_uuid=str(target_agent_uuid or "").strip(),
                    telegram_chat_id=str(telegram_chat_id or "").strip(),
                    webhook_secret=str(webhook_secret or "").strip(),
                    webhook_url=str(webhook_url or "").strip(),
                    webhook_id=max(0, int(webhook_id or 0)),
                    created_at=created_at,
                    updated_at=now_iso,
                    status=str(status or "configured").strip() or "configured",
                    last_error_code=str(error_code or "").strip(),
                )
            )
            self.quick_handover_callbacks[token_key] = row
            self.save_runtime_state()
            return dict(row)

    def get_quick_handover_callback(self, token_id: str) -> Optional[dict]:
        with self.lock:
            row = self.quick_handover_callbacks.get(str(token_id or "").strip())
            if not isinstance(row, dict):
                return None
            return dict(row)

    def touch_quick_handover_callback(
        self,
        *,
        token_id: str,
        status: str,
        error_code: str = "",
    ) -> Optional[dict]:
        with self.lock:
            key = str(token_id or "").strip()
            row = self.quick_handover_callbacks.get(key)
            if not isinstance(row, dict):
                return None
            row["status"] = str(status or "").strip() or row.get("status", "configured")
            row["last_error_code"] = str(error_code or "").strip()
            row["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.quick_handover_callbacks[key] = row
            self.save_runtime_state()
            return dict(row)

    def consume_openclaw_nonce(self, *, key_id: str, nonce: str, ttl_seconds: int = 600) -> bool:
        with self.lock:
            kid = str(key_id or "").strip()
            nonce_value = str(nonce or "").strip()
            if not kid or not nonce_value:
                return False
            self._cleanup_openclaw_nonces_unlocked()
            map_key = f"{kid}:{nonce_value}"
            if map_key in self.openclaw_nonces:
                return False
            now_ts = int(datetime.now(timezone.utc).timestamp())
            ttl = max(60, min(int(ttl_seconds or 600), 3600))
            self.openclaw_nonces[map_key] = {
                "created_at": now_ts,
                "expires_at": now_ts + ttl,
            }
            self.save_runtime_state()
            return True

    def issue_temp_follow_api_key(self, agent_uuid: str, ttl_seconds: int = 300) -> dict:
        with self.lock:
            normalized_uuid = self._resolve_agent_uuid_unlocked(str(agent_uuid or "").strip())
            if not normalized_uuid:
                raise ValueError("agent_not_found")
            now_ts = int(datetime.now(timezone.utc).timestamp())
            expires_at = now_ts + max(60, min(int(ttl_seconds or 300), 3600))
            token = f"tmp_follow_{secrets.token_urlsafe(18)}"
            self.temp_follow_api_keys[token] = {
                "agent_uuid": normalized_uuid,
                "scope": "follow",
                "issued_at": now_ts,
                "expires_at": expires_at,
            }
            # Opportunistic cleanup of expired temporary follow keys.
            for existing_token, row in list(self.temp_follow_api_keys.items()):
                try:
                    row_expires = int((row or {}).get("expires_at", 0) or 0)
                except Exception:
                    row_expires = 0
                if row_expires <= now_ts:
                    self.temp_follow_api_keys.pop(existing_token, None)
            self.save_runtime_state()
            return {
                "api_key": token,
                "agent_uuid": normalized_uuid,
                "scope": "follow",
                "issued_at": now_ts,
                "expires_at": expires_at,
            }

    def resolve_temp_follow_api_key(self, token: str) -> Optional[dict]:
        with self.lock:
            key = str(token or "").strip()
            if not key:
                return None
            row = self.temp_follow_api_keys.get(key)
            if not isinstance(row, dict):
                return None
            now_ts = int(datetime.now(timezone.utc).timestamp())
            try:
                expires_at = int(row.get("expires_at", 0) or 0)
            except Exception:
                expires_at = 0
            if expires_at <= now_ts:
                self.temp_follow_api_keys.pop(key, None)
                self.save_runtime_state()
                return None
            return dict(row)


STATE = TradingState()
