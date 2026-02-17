from __future__ import annotations

import json
import os
import sqlite3
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
    poly_realized_pnl: float = 0.0
    blocked: bool = False

    @property
    def agent_id(self) -> str:
        return self.display_name

    @agent_id.setter
    def agent_id(self, value: str) -> None:
        self.display_name = str(value or "").strip()


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
        self.agent_following: Dict[str, list] = {}
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
            poly_positions=dict(payload.get("poly_positions", {})),
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
                "agent_following": self.agent_following,
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


STATE = TradingState()
