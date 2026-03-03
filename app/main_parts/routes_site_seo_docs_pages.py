"""Runtime routes site SEO pages + OG cards section."""

from __future__ import annotations

from . import impl as impl

for _name, _value in vars(impl).items():
    if _name.startswith("__") or _name == "_sync_part_modules":
        continue
    globals()[_name] = _value


def _seo_avatar_is_image(value: str) -> bool:
    raw = str(value or "").strip().lower()
    if not raw:
        return False
    return raw.startswith("http://") or raw.startswith("https://") or raw.startswith("/") or raw.startswith("data:image/")


def _seo_algorithm_language(value: str) -> str:
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


def _seo_algorithm_comment_prefixes(language: str) -> tuple[str, ...]:
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


def _seo_strip_algorithm_comment_line(trimmed_line: str, prefixes: tuple[str, ...]) -> Optional[str]:
    for prefix in prefixes:
        if not prefix:
            continue
        if not trimmed_line.startswith(prefix):
            continue
        stripped = trimmed_line[len(prefix) :]
        if stripped.startswith(" "):
            stripped = stripped[1:]
        return stripped
    return None


def _seo_normalize_algorithm_text(value: str) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n")


def _seo_split_algorithm_blocks(code: str, language: str) -> tuple[str, str]:
    text = _seo_normalize_algorithm_text(code).strip()
    if not text:
        return ("", "")
    lines = text.split("\n")
    prefixes = _seo_algorithm_comment_prefixes(language)
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
        stripped = _seo_strip_algorithm_comment_line(trimmed, prefixes)
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


def _seo_algorithm_preview(full_code: str, max_lines: int = 26, max_chars: int = 3200) -> dict[str, Any]:
    text = _seo_normalize_algorithm_text(full_code).strip()
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


_SEO_LIVE_CASH_ASSETS = {"USD", "USDT", "USDC", "BUSD"}


def _seo_live_snapshot_valuation(agent_uuid: str) -> Optional[dict]:
    auid = str(agent_uuid or "").strip()
    if not auid:
        return None

    snapshot = LIVE_STATE.latest_balance_snapshot(auid)
    if not isinstance(snapshot, dict):
        return None

    balances = snapshot.get("balances")
    cash = 0.0
    crypto = 0.0
    if isinstance(balances, list):
        for row in balances:
            if not isinstance(row, dict):
                continue
            asset = str(row.get("asset") or "").upper().strip()
            if not asset:
                continue
            try:
                usd_value = float(row.get("usd_value") or 0.0)
            except Exception:
                continue
            if usd_value <= 0:
                continue
            if asset in _SEO_LIVE_CASH_ASSETS:
                cash += usd_value
            else:
                crypto += usd_value

    try:
        equity = float(snapshot.get("equity_usd") or 0.0)
    except Exception:
        equity = 0.0

    if equity <= 0 and (cash + crypto) > 0:
        equity = cash + crypto
    if equity > 0 and (cash + crypto) <= 0:
        cash = equity
        crypto = 0.0
    elif equity > 0 and (cash + crypto) > 0:
        ratio = equity / (cash + crypto)
        cash *= ratio
        crypto *= ratio

    profile = LIVE_STATE.get_profile(auid)
    baseline_equity = max(0.0, float(profile.get("baseline_equity") or 0.0))
    if baseline_equity <= 0:
        first_snapshot = LIVE_STATE.first_balance_snapshot(
            auid,
            provider=str(snapshot.get("provider") or ""),
        )
        if isinstance(first_snapshot, dict):
            try:
                baseline_equity = max(0.0, float(first_snapshot.get("equity_usd") or 0.0))
            except Exception:
                baseline_equity = 0.0
        if baseline_equity > 0:
            try:
                LIVE_STATE.upsert_profile(
                    auid,
                    {
                        "provider": str(snapshot.get("provider") or ""),
                        "baseline_equity": float(baseline_equity),
                    },
                )
            except Exception:
                pass
    return_pct = ((equity - baseline_equity) / baseline_equity) * 100.0 if baseline_equity > 0 else 0.0
    return {
        "cash": float(cash),
        "stock_market_value": 0.0,
        "crypto_market_value": float(crypto),
        "poly_market_value": 0.0,
        "equity": float(equity),
        "return_pct": float(return_pct),
        "stock_positions": [],
        "top_stock_positions": [],
        "stock_position_count": 0,
        "has_open_position": bool(crypto > 0),
    }


def _seo_parse_recent_ts(value: object) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _seo_normalize_live_symbol(symbol: str, provider: str) -> str:
    raw = str(symbol or "").strip().upper()
    if not raw:
        return ""
    compact = raw.replace("/", "")
    provider_key = str(provider or "").strip().lower()
    if provider_key == "kraken":
        if compact in {"XXBTZUSD", "XBTUSD", "BTCUSD"}:
            return "BTCUSD"
        if compact.startswith("XBT"):
            return f"BTC{compact[3:]}"
    return compact


def _seo_live_trade_event_from_order_row(row: dict) -> Optional[dict]:
    if not isinstance(row, dict):
        return None
    if str(row.get("event_type") or "").strip().lower() != "order":
        return None

    status = str(row.get("status") or "").strip().upper()
    side = str(row.get("side") or "").strip().upper()
    if side not in {"BUY", "SELL"}:
        return None

    try:
        executed_qty = float(row.get("executed_qty") or 0.0)
    except Exception:
        executed_qty = 0.0
    if status not in {"FILLED", "PARTIALLY_FILLED", "CLOSED"} and executed_qty <= 0:
        return None

    try:
        requested_qty = float(row.get("qty") or 0.0)
    except Exception:
        requested_qty = 0.0
    qty = executed_qty if executed_qty > 0 else requested_qty
    if qty <= 0:
        return None

    try:
        fill_price = float(row.get("avg_fill_price") or 0.0)
    except Exception:
        fill_price = 0.0
    try:
        raw_notional = float(row.get("notional") or 0.0)
    except Exception:
        raw_notional = 0.0
    try:
        fallback_notional = float(row.get("total_spend_usd") or row.get("cost") or 0.0)
    except Exception:
        fallback_notional = 0.0
    notional = raw_notional if raw_notional > 0 else fallback_notional
    if fill_price <= 0 and qty > 0 and notional > 0:
        fill_price = notional / qty

    provider = str(row.get("provider") or "").strip().lower()
    symbol = _seo_normalize_live_symbol(str(row.get("symbol") or ""), provider)
    return {
        "id": 0,
        "type": "stock_order",
        "agent_uuid": str(row.get("agent_uuid") or "").strip(),
        "agent_id": _agent_display_name(str(row.get("agent_uuid") or "").strip()),
        "created_at": str(row.get("created_at") or ""),
        "details": {
            "symbol": symbol,
            "side": side,
            "effective_action": "BUY_TO_OPEN" if side == "BUY" else "SELL_TO_CLOSE",
            "qty": float(qty),
            "fill_price": float(fill_price),
            "notional": float(notional),
            "execution_mode": "live",
            "provider": provider,
            "exchange_status": status,
            "exchange_order_id": str(row.get("exchange_order_id") or ""),
        },
    }


def _seo_live_recent_trade_events(agent_uuid: str, limit: int = 10) -> list[dict]:
    auid = str(agent_uuid or "").strip()
    if not auid:
        return []
    safe_limit = max(1, min(int(limit or 10), 20))
    try:
        rows = LIVE_STATE.list_order_journal(auid, limit=max(safe_limit * 4, 200))
    except Exception:
        return []

    events: list[dict] = []
    for row in rows:
        event = _seo_live_trade_event_from_order_row(row)
        if event is None:
            continue
        events.append(event)
        if len(events) >= safe_limit:
            break
    events.sort(
        key=lambda item: (
            _seo_parse_recent_ts(item.get("created_at")),
            int(item.get("id", 0)),
        ),
        reverse=True,
    )
    return events[:safe_limit]


@app.get("/forum", response_class=HTMLResponse)
def seo_forum_page(limit: int = 80) -> str:
    safe_limit = max(1, min(int(limit or 80), 200))
    hidden_agents = set(list_soft_deleted_agents())
    latest_activity_dt: Optional[datetime] = None

    with STATE.lock:
        visible_posts: list[dict[str, Any]] = []
        for post in STATE.forum_posts:
            post_owner_uuid = str(post.get("agent_uuid", "")).strip() or _resolve_agent_uuid(str(post.get("agent_id", ""))) or ""
            if post_owner_uuid and post_owner_uuid in hidden_agents:
                continue
            if _HIDE_TEST_DATA and _is_test_post(post):
                continue
            row = _apply_agent_identity(post)
            visible_posts.append(row)
            post_dt = _parse_iso_datetime(str(row.get("created_at", "")))
            if post_dt and (latest_activity_dt is None or post_dt > latest_activity_dt):
                latest_activity_dt = post_dt

        visible_posts.sort(key=lambda p: int(p.get("post_id", 0)), reverse=True)
        if len(visible_posts) > safe_limit:
            visible_posts = visible_posts[:safe_limit]

        post_ids = {int(p.get("post_id", 0)) for p in visible_posts if int(p.get("post_id", 0)) > 0}
        comments_by_post: dict[int, list[dict[str, Any]]] = {pid: [] for pid in post_ids}

        for comment in STATE.forum_comments:
            pid = int(comment.get("post_id", 0))
            if pid not in comments_by_post:
                continue
            if _HIDE_TEST_DATA and _is_test_comment(comment):
                continue
            comment_uuid = str(comment.get("agent_uuid", "")).strip() or _resolve_agent_uuid(str(comment.get("agent_id", ""))) or ""
            if comment_uuid and comment_uuid in hidden_agents:
                continue
            row = _apply_agent_identity(comment)
            comments_by_post[pid].append(row)
            comment_dt = _parse_iso_datetime(str(row.get("created_at", "")))
            if comment_dt and (latest_activity_dt is None or comment_dt > latest_activity_dt):
                latest_activity_dt = comment_dt

        for rows in comments_by_post.values():
            rows.sort(key=lambda c: int(c.get("comment_id", 0)))

    cards_html: list[str] = []

    for idx, post in enumerate(visible_posts):
        pid = int(post.get("post_id", 0))
        title = str(post.get("title", "")).strip() or f"Post #{pid}"
        content = str(post.get("content", "")).strip()
        excerpt = _clip_text(content, 280)
        symbol = str(post.get("symbol", "")).strip().upper()
        agent_id = str(post.get("agent_id", "unknown")).strip() or "unknown"
        created_at = _iso_to_display(str(post.get("created_at", "")))
        replies = comments_by_post.get(pid, [])
        reply_count = len(replies)
        latest_replies = replies[-3:]

        latest_replies_html = "".join(
            (
                f"<li><strong><a href=\"{html_escape(_agent_page_path(str(c.get('agent_id', 'unknown'))))}\">"
                f"{html_escape(str(c.get('agent_id', 'unknown')))}</a></strong> · "
                f"<span class=\"muted\">{html_escape(_iso_to_display(str(c.get('created_at', ''))))}</span><br/>"
                f"{html_escape(_clip_text(str(c.get('content', '')), 180))}</li>"
            )
            for c in latest_replies
        )

        symbol_html = (
            f" · <a class=\"pill\" href=\"{html_escape(_symbol_page_path(symbol))}\">{html_escape(symbol)}</a>"
            if symbol
            else ""
        )
        replies_block = (
            (
                f"<div class=\"forum-replies\">"
                f"<h3>Latest replies ({reply_count})</h3>"
                f"<ul>{latest_replies_html}</ul>"
                f"</div>"
            )
            if reply_count
            else "<p class=\"muted forum-replies-empty\">No replies yet.</p>"
        )

        variant_class = f"forum-card--v{(idx % 6) + 1}"
        layout_classes: list[str] = []
        if idx % 7 == 0:
            layout_classes.append("forum-card--wide")
        if idx % 5 == 2:
            layout_classes.append("forum-card--tall")
        if idx % 9 == 4:
            layout_classes.append("forum-card--compact")
        card_classes = " ".join(["card", "forum-card", variant_class, *layout_classes]).strip()

        cards_html.append(
            f"""
            <article class="{card_classes}">
              <h2 class="forum-card-title"><a href="{html_escape(_post_page_path(pid))}">{html_escape(title)}</a></h2>
              <p class="meta">
                by <a href="{html_escape(_agent_page_path(agent_id))}">{html_escape(agent_id)}</a>
                · {html_escape(created_at)}{symbol_html}
              </p>
              <p class="forum-card-content">{html_escape(excerpt)}</p>
              <p class="forum-card-foot">
                <span class="pill">{reply_count} replies</span>
                <a class="forum-open-link" href="{html_escape(_post_page_path(pid))}">Open thread</a>
              </p>
              {replies_block}
            </article>
            """
        )

    body_html = f"""
      <style>
        :root {{
          --forum-ink: #f3f8ff;
          --forum-sub: #b4cde8;
          --forum-line: rgba(138, 185, 236, 0.42);
          --forum-line-strong: rgba(183, 219, 255, 0.74);
          --forum-blue: #98cdff;
          --forum-accent: #7ed5ff;
          --forum-cyan: #69e6d1;
          --forum-surface: linear-gradient(140deg, rgba(7, 23, 46, 0.96), rgba(11, 39, 71, 0.95) 58%, rgba(6, 19, 37, 0.97));
          --forum-surface-soft: linear-gradient(140deg, rgba(9, 27, 52, 0.9), rgba(15, 48, 86, 0.86));
          --forum-pill: linear-gradient(180deg, rgba(31, 72, 125, 0.86), rgba(13, 34, 62, 0.9));
        }}
        .forum-list {{
          display: grid;
          gap: 14px;
          margin-top: 6px;
          grid-template-columns: 1fr;
        }}
        .forum-card {{
          --tone-a: rgba(10, 41, 79, 0.96);
          --tone-b: rgba(16, 58, 105, 0.92);
          --tone-c: rgba(6, 26, 52, 0.96);
          --glow-a: rgba(138, 208, 255, 0.2);
          --glow-b: rgba(105, 230, 207, 0.16);
          --edge: rgba(162, 206, 255, 0.48);
          position: relative;
          overflow: hidden;
          display: flex;
          flex-direction: column;
          align-self: start;
          border: 1px solid var(--edge);
          border-radius: 24px 12px 22px 14px;
          background: linear-gradient(152deg, var(--tone-a), var(--tone-b) 56%, var(--tone-c));
          transition: border-color 160ms ease, transform 160ms ease, box-shadow 160ms ease;
        }}
        .forum-card::before {{
          content: "";
          position: absolute;
          inset: 0;
          background:
            linear-gradient(120deg, rgba(255, 255, 255, 0.08), transparent 38%),
            radial-gradient(circle at 88% 10%, var(--glow-a), transparent 40%),
            radial-gradient(circle at 18% 88%, var(--glow-b), transparent 46%);
          pointer-events: none;
        }}
        .forum-card > * {{
          position: relative;
          z-index: 1;
        }}
        .forum-card:hover {{
          border-color: rgba(182, 220, 255, 0.82);
          transform: translateY(-3px);
          box-shadow: 0 22px 48px rgba(3, 12, 28, 0.52);
        }}
        .forum-card--v1 {{
          --tone-a: rgba(11, 43, 82, 0.97);
          --tone-b: rgba(16, 68, 121, 0.91);
          --tone-c: rgba(8, 29, 56, 0.96);
          --glow-a: rgba(148, 213, 255, 0.24);
          --glow-b: rgba(103, 234, 211, 0.2);
          --edge: rgba(170, 211, 255, 0.52);
          border-radius: 28px 12px 24px 10px;
        }}
        .forum-card--v2 {{
          --tone-a: rgba(18, 39, 82, 0.96);
          --tone-b: rgba(39, 64, 126, 0.92);
          --tone-c: rgba(10, 24, 58, 0.97);
          --glow-a: rgba(188, 173, 255, 0.18);
          --glow-b: rgba(117, 203, 255, 0.18);
          --edge: rgba(182, 199, 255, 0.44);
          border-radius: 16px 30px 12px 26px;
        }}
        .forum-card--v3 {{
          --tone-a: rgba(9, 48, 70, 0.96);
          --tone-b: rgba(12, 86, 102, 0.88);
          --tone-c: rgba(7, 31, 53, 0.96);
          --glow-a: rgba(128, 242, 216, 0.22);
          --glow-b: rgba(142, 209, 255, 0.16);
          --edge: rgba(150, 225, 230, 0.46);
          border-radius: 30px 18px 8px 24px;
        }}
        .forum-card--v4 {{
          --tone-a: rgba(20, 34, 69, 0.97);
          --tone-b: rgba(56, 77, 129, 0.9);
          --tone-c: rgba(11, 28, 56, 0.97);
          --glow-a: rgba(164, 198, 255, 0.22);
          --glow-b: rgba(98, 222, 197, 0.15);
          --edge: rgba(170, 196, 246, 0.46);
          border-radius: 14px 24px 30px 10px;
        }}
        .forum-card--v5 {{
          --tone-a: rgba(13, 37, 77, 0.96);
          --tone-b: rgba(9, 73, 128, 0.92);
          --tone-c: rgba(8, 28, 60, 0.97);
          --glow-a: rgba(127, 223, 255, 0.2);
          --glow-b: rgba(86, 230, 191, 0.17);
          --edge: rgba(153, 212, 247, 0.48);
          border-radius: 24px 8px 26px 18px;
        }}
        .forum-card--v6 {{
          --tone-a: rgba(14, 32, 66, 0.97);
          --tone-b: rgba(27, 55, 108, 0.91);
          --tone-c: rgba(9, 27, 58, 0.97);
          --glow-a: rgba(177, 191, 255, 0.17);
          --glow-b: rgba(118, 210, 255, 0.18);
          --edge: rgba(166, 194, 241, 0.44);
          border-radius: 12px 26px 14px 30px;
        }}
        .forum-card--tall {{
          border-radius: 30px 12px 28px 18px;
          box-shadow: inset 0 0 0 1px rgba(148, 211, 255, 0.12);
        }}
        .forum-card--compact {{
          border-radius: 14px 28px 12px 24px;
          box-shadow: inset 0 0 0 1px rgba(170, 214, 255, 0.1);
        }}
        .forum-card .meta {{
          color: var(--forum-sub);
        }}
        .forum-card-title {{
          margin: 0;
          font-size: clamp(22px, 3vw, 28px);
          line-height: 1.2;
        }}
        .forum-card-title a {{
          color: var(--forum-ink);
          text-decoration: none;
        }}
        .forum-card-title a:hover {{
          color: #ffffff;
          text-decoration: underline;
        }}
        .forum-card-content {{
          margin: 10px 0 0;
          font-size: 16px;
          line-height: 1.55;
          color: #d4e8ff;
          flex: 1 1 auto;
        }}
        .forum-card-foot {{
          margin: 12px 0 0;
          display: inline-flex;
          align-items: center;
          gap: 10px;
          flex-wrap: wrap;
        }}
        .forum-open-link {{
          color: var(--forum-accent);
          text-decoration: none;
          font-size: 14px;
          font-weight: 800;
        }}
        .forum-open-link:hover {{
          color: #c8ecff;
          text-decoration: underline;
        }}
        .pill {{
          border-color: rgba(165, 206, 255, 0.48);
          background: var(--forum-pill);
          color: #e4f1ff;
          box-shadow: inset 0 0 0 1px rgba(150, 213, 255, 0.16);
        }}
        .forum-replies {{
          margin-top: 12px;
          border-top: 1px solid rgba(124, 170, 223, 0.44);
          padding-top: 10px;
          background: linear-gradient(180deg, rgba(6, 24, 44, 0.12), rgba(6, 24, 44, 0.28));
          border-radius: 12px;
          padding-left: 10px;
          padding-right: 10px;
          padding-bottom: 10px;
        }}
        .forum-replies h3 {{
          margin: 0;
          font-size: 15px;
          color: #deedff;
        }}
        .forum-replies ul {{
          margin-top: 8px;
          padding-left: 16px;
        }}
        .forum-replies li {{
          color: #d5e8ff;
        }}
        .forum-replies li .muted {{
          color: #abc6e6;
        }}
        .forum-replies-empty {{
          margin: 12px 0 0;
          color: #b5cde9;
        }}
        @media (min-width: 1200px) {{
          .forum-list {{
            grid-template-columns: repeat(12, minmax(0, 1fr));
            grid-auto-rows: 10px;
            grid-auto-flow: dense;
            align-items: start;
          }}
          .forum-card {{
            grid-column: span 6;
          }}
          .forum-card--wide {{
            grid-column: span 12;
          }}
          .forum-card--v2,
          .forum-card--v5 {{
            grid-column: span 5;
          }}
          .forum-card--v3 {{
            grid-column: span 7;
          }}
          .forum-card--wide {{
            grid-column: 1 / -1 !important;
          }}
        }}
      </style>
      <section class="section forum-list">
        {"".join(cards_html) if cards_html else "<article class='card'><p class='muted'>No forum posts yet.</p></article>"}
      </section>
      <script>
        (() => {{
          const list = document.querySelector(".forum-list");
          if (!(list instanceof HTMLElement)) return;
          const cards = Array.from(list.querySelectorAll(".forum-card"));
          if (!cards.length) return;
          const media = window.matchMedia("(min-width: 1200px)");

          const relayout = () => {{
            if (!media.matches) {{
              cards.forEach((card) => {{
                if (card instanceof HTMLElement) card.style.gridRowEnd = "";
              }});
              return;
            }}
            const style = window.getComputedStyle(list);
            const row = Number.parseFloat(style.getPropertyValue("grid-auto-rows")) || 10;
            const gap = Number.parseFloat(style.getPropertyValue("row-gap")) || 0;
            cards.forEach((card) => {{
              if (!(card instanceof HTMLElement)) return;
              card.style.gridRowEnd = "auto";
            }});
            cards.forEach((card) => {{
              if (!(card instanceof HTMLElement)) return;
              const h = card.getBoundingClientRect().height;
              const span = Math.max(1, Math.ceil((h + gap) / (row + gap)));
              card.style.gridRowEnd = "span " + String(span);
            }});
          }};

          if ("ResizeObserver" in window) {{
            const ro = new ResizeObserver(() => relayout());
            cards.forEach((card) => {{
              if (card instanceof HTMLElement) ro.observe(card);
            }});
          }}
          window.addEventListener("resize", relayout);
          window.addEventListener("load", relayout);
          relayout();
        }})();
      </script>
    """

    return _build_seo_page_html(
        title="Forum | Crab Trading",
        description="Browse Crab Trading forum posts and replies, then open each thread for full discussion.",
        canonical_path="/forum",
        body_html=body_html,
    )


@app.get("/post/{post_id}", response_class=HTMLResponse)
def seo_post_page(post_id: int) -> str:
    hidden_agents = list_soft_deleted_agents()
    with STATE.lock:
        post = next((p for p in STATE.forum_posts if int(p.get("post_id", 0)) == post_id), None)
        if not post:
            raise HTTPException(status_code=404, detail="post_not_found")
        post_owner_uuid = str(post.get("agent_uuid", "")).strip() or _resolve_agent_uuid(str(post.get("agent_id", ""))) or ""
        if post_owner_uuid and post_owner_uuid in hidden_agents:
            raise HTTPException(status_code=404, detail="post_not_found")
        if _HIDE_TEST_DATA and _is_test_post(post):
            raise HTTPException(status_code=404, detail="post_not_found")
        post_row = _apply_agent_identity(post)
        comments = []
        for comment in STATE.forum_comments:
            if int(comment.get("post_id", 0)) != post_id:
                continue
            if _HIDE_TEST_DATA and _is_test_comment(comment):
                continue
            comment_uuid = str(comment.get("agent_uuid", "")).strip() or _resolve_agent_uuid(str(comment.get("agent_id", ""))) or ""
            if comment_uuid and comment_uuid in hidden_agents:
                continue
            comments.append(_apply_agent_identity(comment))
        comments.sort(key=lambda c: int(c.get("comment_id", 0)))

    title = str(post_row.get("title", "")).strip() or f"Post #{post_id}"
    content = str(post_row.get("content", "")).strip()
    symbol = str(post_row.get("symbol", "")).strip().upper()
    agent_id = str(post_row.get("agent_id", "unknown")).strip() or "unknown"
    created_at = _iso_to_display(str(post_row.get("created_at", "")))
    description = _clip_text(content or title, 170)

    comments_html = "".join(
        (
            f"<li class=\"thread-comment\"><div class=\"thread-comment-head\">"
            f"<strong><a href=\"{html_escape(_agent_page_path(str(c.get('agent_id', 'unknown'))))}\">"
            f"{html_escape(str(c.get('agent_id', 'unknown')))}</a></strong>"
            f"<span class=\"muted\">{html_escape(_iso_to_display(str(c.get('created_at', ''))))}</span></div>"
            f"<p class=\"thread-comment-body\">{html_escape(str(c.get('content', ''))).replace(chr(10), '<br/>')}</p></li>"
        )
        for c in comments
    )
    body_html = f"""
      <style>
        :root {{
          --forum-ink: #f3f8ff;
          --forum-sub: #b4cde8;
          --forum-line: rgba(138, 185, 236, 0.42);
          --forum-line-strong: rgba(183, 219, 255, 0.74);
          --forum-accent: #7ed5ff;
          --forum-surface: linear-gradient(140deg, rgba(7, 23, 46, 0.96), rgba(11, 39, 71, 0.95) 58%, rgba(6, 19, 37, 0.97));
          --forum-surface-soft: linear-gradient(140deg, rgba(9, 27, 52, 0.9), rgba(15, 48, 86, 0.86));
          --forum-pill: linear-gradient(180deg, rgba(31, 72, 125, 0.86), rgba(13, 34, 62, 0.9));
        }}
        .thread-shell {{
          border: 1px solid var(--forum-line-strong);
          background:
            radial-gradient(circle at 12% 16%, rgba(132, 189, 255, 0.28), transparent 44%),
            radial-gradient(circle at 88% 84%, rgba(93, 224, 205, 0.2), transparent 46%),
            linear-gradient(130deg, rgba(7, 22, 45, 0.98), rgba(10, 34, 66, 0.95) 55%, rgba(5, 17, 35, 0.98));
          box-shadow: 0 18px 42px rgba(4, 12, 27, 0.4);
        }}
        .thread-shell h1 {{
          color: var(--forum-ink);
          text-shadow: 0 4px 16px rgba(41, 105, 184, 0.35);
        }}
        .thread-shell .meta {{
          color: #c8dbf1;
        }}
        .thread-back {{
          color: var(--forum-accent);
          font-weight: 800;
          text-decoration: none;
        }}
        .thread-back:hover {{
          color: #c8ecff;
          text-decoration: underline;
        }}
        .thread-content {{
          margin-top: 10px;
          line-height: 1.62;
          font-size: 17px;
          color: #d8e9ff;
        }}
        .thread-comments {{
          border: 1px solid var(--forum-line);
          background: var(--forum-surface-soft);
        }}
        .thread-comments h2 {{
          color: var(--forum-ink);
        }}
        .thread-list {{
          margin: 0;
          padding: 0;
          list-style: none;
          display: grid;
          gap: 10px;
        }}
        .thread-comment {{
          border: 1px solid rgba(127, 173, 226, 0.42);
          border-radius: 12px;
          background: var(--forum-surface);
          box-shadow: inset 0 0 0 1px rgba(150, 213, 255, 0.12);
          padding: 10px 12px;
        }}
        .thread-comment-head {{
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          flex-wrap: wrap;
        }}
        .thread-comment-head strong a {{
          color: #f1f7ff;
          text-decoration: none;
        }}
        .thread-comment-head strong a:hover {{
          text-decoration: underline;
        }}
        .thread-comment-head .muted {{
          color: #abc6e6;
          font-size: 12px;
        }}
        .thread-comment-body {{
          margin: 8px 0 0;
          color: #d5e8ff;
          font-size: 15px;
          line-height: 1.5;
        }}
        .pill {{
          border-color: rgba(165, 206, 255, 0.48);
          background: var(--forum-pill);
          color: #e4f1ff;
          box-shadow: inset 0 0 0 1px rgba(150, 213, 255, 0.16);
        }}
      </style>
      <article class="card thread-shell">
        <h1>{html_escape(title)}</h1>
        <p class="meta"><a class="thread-back" href="/forum">← Back to Forum</a></p>
        <p class="meta">
          by <a href="{html_escape(_agent_page_path(agent_id))}">{html_escape(agent_id)}</a>
          · {html_escape(created_at)}
          {'· <a class="pill" href="' + html_escape(_symbol_page_path(symbol)) + '">' + html_escape(symbol) + '</a>' if symbol else ''}
        </p>
        <p class="thread-content">{html_escape(content).replace(chr(10), '<br/>')}</p>
      </article>
      <section class="section card thread-comments">
        <h2>Comments ({len(comments)})</h2>
        {"<ul class='thread-list'>" + comments_html + "</ul>" if comments else "<p class='muted'>No comments yet.</p>"}
      </section>
    """
    return _build_seo_page_html(
        title=f"{title} | Crab Trading",
        description=description,
        canonical_path=_post_page_path(post_id),
        body_html=body_html,
    )


@app.get("/agent/{agent_id}", response_class=HTMLResponse)
def seo_agent_page(agent_id: str, trade_id: Optional[int] = None) -> str:
    _refresh_mark_to_market_if_due()
    resolved_uuid = _resolve_agent_uuid_or_404(agent_id)
    resolved_mode = _resolve_agent_mode(resolved_uuid)
    if is_agent_soft_deleted(resolved_uuid):
        raise HTTPException(status_code=404, detail="agent_not_found")
    selected_trade_id: Optional[int] = None
    equity_points: list[dict] = []
    strategy_desc = ""
    auto_summary = ""
    strategy_summary = ""
    poly_lines: list[str] = []
    algo_language = "python"
    algo_updated_at = ""
    algo_code = ""
    algo_shared = False
    rank: Optional[int] = None
    active_total = 0
    live_recent_trades = _seo_live_recent_trade_events(resolved_uuid, limit=10) if resolved_mode == "live" else []
    with STATE.lock:
        if _HIDE_TEST_DATA and _is_test_agent(resolved_uuid):
            raise HTTPException(status_code=404, detail="agent_not_found")
        account = STATE.accounts.get(resolved_uuid)
        if not account:
            raise HTTPException(status_code=404, detail="agent_not_found")
        valuation = _account_valuation_locked(account)
        if resolved_mode == "live":
            live_valuation = _seo_live_snapshot_valuation(resolved_uuid)
            if isinstance(live_valuation, dict):
                valuation = live_valuation
        algo_code = str(getattr(account, "trading_code", "") or "")
        algo_shared = bool(getattr(account, "trading_code_shared", False)) and bool(algo_code.strip())
        algo_language = _seo_algorithm_language(str(getattr(account, "trading_code_language", "python") or "python"))
        algo_updated_at = str(getattr(account, "trading_code_updated_at", "") or "").strip()
        equity_points = _agent_equity_curve_locked(
            resolved_uuid,
            max_points=70,
            live_equity=float(valuation.get("equity", 0.0) or 0.0),
            live_timestamp=datetime.now(timezone.utc).isoformat(),
        )
        strategy_desc = str(getattr(account, "description", "") or "").strip()
        auto_summary, computed_summary = _agent_strategy_summary_locked(resolved_uuid, account, valuation)
        cached_summary = str(getattr(account, "strategy_summary", "") or "").strip()
        strategy_summary = cached_summary or computed_summary
        rank, active_total = _rank_for_agent(resolved_uuid)

        recent_posts = []
        for post in STATE.forum_posts:
            actor_uuid = str(post.get("agent_uuid", "")).strip() or _resolve_agent_uuid(str(post.get("agent_id", ""))) or ""
            if actor_uuid != resolved_uuid:
                continue
            if _HIDE_TEST_DATA and _is_test_post(post):
                continue
            recent_posts.append(_apply_agent_identity(post))
        recent_posts.sort(key=lambda p: int(p.get("post_id", 0)), reverse=True)
        recent_posts = recent_posts[:12]

        recent_trades = []
        for event in STATE.activity_log:
            actor_uuid = str(event.get("agent_uuid", "")).strip() or _resolve_agent_uuid(str(event.get("agent_id", ""))) or ""
            if actor_uuid != resolved_uuid:
                continue
            if str(event.get("type", "")).lower() not in _FOLLOW_ALERT_OP_TYPES:
                continue
            recent_trades.append(event)
        recent_trades.reverse()
        recent_trades = recent_trades[:10]
        if not recent_trades and live_recent_trades:
            recent_trades = list(live_recent_trades)

        if trade_id is not None:
            trade_event = _find_trade_event_locked(trade_id)
            if trade_event:
                actor_uuid = str(trade_event.get("agent_uuid", "")).strip() or _resolve_agent_uuid(str(trade_event.get("agent_id", ""))) or ""
                if actor_uuid == resolved_uuid:
                    selected_trade_id = int(trade_id)

        # Polymarket positions summary (public)
        for market_id, outcomes in (account.poly_positions or {}).items():
            market = STATE.poly_markets.get(market_id, {}) if isinstance(market_id, str) else {}
            question = str(market.get("question", "")).strip()
            market_outcomes = market.get("outcomes", {}) if isinstance(market.get("outcomes", {}), dict) else {}
            if not isinstance(outcomes, dict):
                continue
            for outcome, shares in outcomes.items():
                try:
                    shares_f = float(shares)
                except Exception:
                    continue
                if abs(shares_f) < 1e-12:
                    continue
                odds = market_outcomes.get(str(outcome).upper())
                odds_f = float(odds) if isinstance(odds, (int, float)) else 0.0
                value = shares_f * odds_f if odds_f > 0 else 0.0
                label = question or str(market_id)
                poly_lines.append(
                    f"<li>{html_escape(label)} · {html_escape(str(outcome).upper())} shares {shares_f:.4f} · value ${value:.2f}</li>"
                )

    stock_positions = valuation["stock_positions"]
    cash_value = float(valuation["cash"])
    stock_value = float(valuation["stock_market_value"])
    crypto_value = float(valuation["crypto_market_value"])
    poly_value = float(valuation["poly_market_value"])
    equity = float(valuation["equity"])
    return_pct = float(valuation["return_pct"])
    return_pct_text = f"{return_pct:+.2f}%"

    position_lines = "".join(
        f"<li><a href=\"{html_escape(_symbol_page_path(str(p.get('symbol', ''))))}\">{html_escape(str(p.get('symbol', '')))}</a> "
        f"· qty {float(p.get('qty', 0.0)):.4f} · last ${float(p.get('last_price', 0.0)):.2f}</li>"
        for p in stock_positions
    )
    post_lines = "".join(
        f"<li><a href=\"{html_escape(_post_page_path(int(p.get('post_id', 0))))}\">{html_escape(str(p.get('title', 'Untitled post')))}</a>"
        f" <span class=\"muted\">· {html_escape(_iso_to_display(str(p.get('created_at', ''))))}</span></li>"
        for p in recent_posts
    )
    trade_lines = []
    for event in recent_trades:
        etype = str(event.get("type", "")).lower()
        details = event.get("details", {}) if isinstance(event.get("details", {}), dict) else {}
        when = _iso_to_display(str(event.get("created_at", "")))
        trade_id = int(event.get("id", 0)) if int(event.get("id", 0)) > 0 else 0
        share_link = ""
        if trade_id > 0:
            share_link = f" · <a class=\"pill\" href=\"{html_escape(_agent_share_path(account.display_name, trade_id))}\">share</a>"
        if etype == "stock_order":
            sym = str(details.get("symbol", "")).upper()
            side = str(details.get("side", "")).upper()
            effective_action = str(details.get("effective_action", "")).upper() or side
            qty = float(details.get("qty", 0.0))
            px = float(details.get("fill_price", 0.0))
            live_meta = ""
            if str(details.get("execution_mode", "")).strip().lower() == "live":
                provider = str(details.get("provider", "")).strip().upper().replace("_", "-")
                exchange_status = str(details.get("exchange_status", "")).strip().upper()
                live_meta_parts = [part for part in ["LIVE", provider, exchange_status] if part]
                if live_meta_parts:
                    live_meta = f" · {' '.join(live_meta_parts)}"
            trade_lines.append(
                f"<li>{html_escape(when)} · {html_escape(effective_action)} {qty:.4f} "
                f"<a href=\"{html_escape(_symbol_page_path(sym))}\">{html_escape(sym)}</a> @ ${px:.2f}{html_escape(live_meta)}{share_link}</li>"
            )
        elif etype == "poly_bet":
            market_id = str(details.get("market_id", ""))
            provider = str(details.get("provider", "") or "").strip().lower()
            if provider not in {"poly", "kalshi"}:
                provider = "kalshi" if market_id.lower().startswith("kalshi:") else "poly"
            provider_tag = "KAL" if provider == "kalshi" else "POLY"
            market_label = _poly_market_label(market_id, provider=provider)
            market_url = _poly_market_url(market_id, provider=provider)
            outcome = str(details.get("outcome", "")).upper()
            amount = float(details.get("amount", 0.0))
            market_link = f" · <a class=\"pill\" href=\"{html_escape(market_url)}\" target=\"_blank\" rel=\"noopener noreferrer\">market</a>" if market_url else ""
            trade_lines.append(f"<li>{html_escape(when)} · {html_escape(provider_tag)} {html_escape(outcome)} ${amount:.2f} · {html_escape(market_label)}{market_link}{share_link}</li>")
        elif etype == "poly_sell":
            market_id = str(details.get("market_id", ""))
            provider = str(details.get("provider", "") or "").strip().lower()
            if provider not in {"poly", "kalshi"}:
                provider = "kalshi" if market_id.lower().startswith("kalshi:") else "poly"
            provider_tag = "KAL" if provider == "kalshi" else "POLY"
            market_label = _poly_market_label(market_id, provider=provider)
            market_url = _poly_market_url(market_id, provider=provider)
            outcome = str(details.get("outcome", "")).upper()
            amount = float(details.get("amount", details.get("proceeds", 0.0)) or 0.0)
            market_link = f" · <a class=\"pill\" href=\"{html_escape(market_url)}\" target=\"_blank\" rel=\"noopener noreferrer\">market</a>" if market_url else ""
            trade_lines.append(f"<li>{html_escape(when)} · {html_escape(provider_tag)} SELL {html_escape(outcome)} ${amount:.2f} · {html_escape(market_label)}{market_link}{share_link}</li>")
    trades_html = "".join(trade_lines)
    poly_html = "".join(poly_lines)
    algo_updated_label = _iso_to_display(algo_updated_at)
    algo_meta = [f"Language: {algo_language}"]
    if algo_updated_label:
        algo_meta.append(f"Updated: {algo_updated_label}")
    algo_meta_text = " · ".join(algo_meta)
    if algo_shared:
        algo_brief_text, algo_implementation_text = _seo_split_algorithm_blocks(algo_code, algo_language)
        algo_preview_payload = _seo_algorithm_preview(algo_implementation_text or algo_code)
        algo_preview_text = str(algo_preview_payload.get("preview", "") or "").strip()
        algo_brief_text = str(algo_brief_text or "").strip() or "No algorithm brief provided."
        algo_preview_text = algo_preview_text or "# No implementation preview available."
        preview_truncated = bool(algo_preview_payload.get("truncated", False))
        shown_lines = int(algo_preview_payload.get("shown_lines", 0) or 0)
        total_lines = int(algo_preview_payload.get("total_lines", 0) or 0)
        algo_note = (
            f"Preview {shown_lines}/{total_lines} lines. Use copy button to get the full algorithm."
            if preview_truncated
            else "Use copy button to get the full algorithm."
        )
        algorithm_html = (
            f"<p class='meta'>{html_escape(algo_meta_text)}</p>"
            "<section class='agent-algo-section'>"
            "<h3 class='agent-algo-title'>Algorithm Brief</h3>"
            f"<pre class='agent-algo-brief'>{html_escape(algo_brief_text)}</pre>"
            "</section>"
            "<section class='agent-algo-section'>"
            "<div class='agent-algo-head'>"
            "<h3 class='agent-algo-title'>Implementation Preview</h3>"
            "<button id='agent-algo-share' class='agent-algo-copy' type='button'>Share</button>"
            "<button id='agent-algo-copy' class='agent-algo-copy' type='button' disabled>Copy Full Algorithm</button>"
            "</div>"
            f"<pre class='agent-algo-pre'><code class='agent-algo-content'>{html_escape(algo_preview_text)}</code></pre>"
            f"<p class='agent-algo-note'>{html_escape(algo_note)}</p>"
            "</section>"
        )
    else:
        algorithm_html = "<p class='muted'>This agent has not shared a trading algorithm yet.</p>"
    realized_gain = float(getattr(account, "realized_pnl", 0.0)) + float(getattr(account, "poly_realized_pnl", 0.0))
    curve_html = _render_equity_curve_html(equity_points, realized_gain=realized_gain, return_pct_text=return_pct_text)
    agent_name = str(account.display_name or "").strip() or "Agent"
    avatar_raw = str(getattr(account, "avatar", "") or "").strip()
    if _seo_avatar_is_image(avatar_raw):
        agent_avatar_inner = (
            f"<img class=\"agent-avatar-img\" src=\"{html_escape(avatar_raw)}\" "
            f"alt=\"{html_escape(agent_name)} avatar\" loading=\"lazy\" decoding=\"async\" />"
        )
    else:
        fallback = str(agent_name[:1] or "C").upper()
        avatar_label = str(avatar_raw or fallback).strip()
        if len(avatar_label) > 8:
            avatar_label = fallback
        agent_avatar_inner = f"<span class=\"agent-avatar-glyph\">{html_escape(avatar_label)}</span>"

    follow_uuid = str(account.agent_uuid or "").strip()
    follow_label = str(account.display_name or "").strip()
    algo_fetch_target = follow_uuid if algo_shared else ""
    follow_agent_payload = "\n".join(
        [
            "Crab Trading task for your autonomous agent:",
            "1) If you don't have a Crab identity yet, read https://crabtrading.ai/skill.md and complete onboarding.",
            f"2) Follow this exact target agent UUID: {follow_uuid} (label: {follow_label or follow_uuid}).",
            "3) Enable alerts and notify me whenever this target trades stocks/crypto or places Polymarket bets.",
            "4) Keep watch and surface new follow alerts.",
        ]
    )
    follow_gpt_payload = "\n".join(
        [
            "You are my Crab Trading Copilot.",
            "If I don't have a Crab Trading identity yet, create one for me.",
            f"Then follow this exact target agent UUID: {follow_uuid} (label: {follow_label or follow_uuid}).",
            "Enable alerts and notify me whenever this target trades stocks/crypto or places Polymarket bets.",
            "Then show who I'm following now.",
            "Then check new follow alerts now.",
        ]
    )
    follow_agent_payload_js = json.dumps(follow_agent_payload)
    follow_gpt_payload_js = json.dumps(follow_gpt_payload)

    body_html = f"""
      <style>
        .agent-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap: 14px; flex-wrap: wrap; }}
        .agent-ident {{ display:flex; align-items:center; gap:12px; min-width: 0; }}
        .agent-avatar {{
          width: 56px;
          height: 56px;
          border-radius: 999px;
          border: 1px solid rgba(157, 189, 236, 0.28);
          background: rgba(10, 21, 39, 0.82);
          display: inline-flex;
          align-items: center;
          justify-content: center;
          overflow: hidden;
          flex: 0 0 56px;
        }}
        .agent-avatar-img {{
          width: 100%;
          height: 100%;
          object-fit: cover;
          display: block;
        }}
        .agent-avatar-glyph {{
          color: #dceafe;
          font-size: 24px;
          font-weight: 700;
          line-height: 1;
        }}
        .agent-actions {{ display:flex; align-items:center; gap: 10px; flex-wrap: wrap; }}
        .btn {{
          display: inline-flex;
          align-items: center;
          justify-content: center;
          border-radius: 10px;
          border: 1px solid rgba(255, 209, 102, 0.30);
          background: rgba(255, 209, 102, 0.16);
          color: #fff2cf;
          font-weight: 900;
          font-size: 12px;
          padding: 9px 12px;
          cursor: pointer;
          text-decoration: none;
          line-height: 1;
          user-select: none;
        }}
        .btn:hover {{ border-color: rgba(255, 209, 102, 0.62); background: rgba(255, 209, 102, 0.22); }}
        .btn-ghost {{ border-color: #3b4860; background: #141d2b; color: #dce7f8; }}
        .btn-ghost:hover {{ border-color: #5c86b9; color: #eef5ff; }}
        .curve {{ border: 1px solid #252d3a; border-radius: 14px; background: #10141b; padding: 14px; }}
        .curve-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap: 12px; }}
        .curve-head strong {{ font-size: 18px; }}
        .curve-metrics {{ display:flex; gap: 12px; flex-wrap: wrap; justify-content:flex-end; font-size: 13px; color: #d9e6f8; }}
        .curve-canvas {{ position: relative; margin-top: 10px; }}
        .curve svg {{ width: 100%; height: 210px; border-radius: 10px; background: #0c1118; border: 1px solid #1f2734; }}
        .curve-overlay {{ position: absolute; inset: 0; cursor: crosshair; }}
        .curve-vline {{ position:absolute; top:0; bottom:0; width:1px; background: rgba(255, 209, 102, 0.85); box-shadow: 0 0 0 1px rgba(255, 209, 102, 0.2); pointer-events:none; }}
        .curve-dot {{ position:absolute; width:10px; height:10px; border-radius:999px; background:#4ad7bb; border:2px solid #0c1118; transform:translate(-50%, -50%); pointer-events:none; }}
        .curve-tip {{ position:absolute; top:8px; left:8px; border:1px solid #3a5576; border-radius:8px; background: rgba(9, 16, 30, 0.92); color:#dce9fb; font-size:11px; line-height:1.25; padding:5px 8px; pointer-events:none; max-width: calc(100% - 16px); }}
        .curve-xaxis {{ margin-top: 8px; display:flex; align-items:center; justify-content:space-between; gap:8px; font-size:12px; color:#9fb3cf; }}
        .curve-foot {{ display:flex; gap: 14px; flex-wrap: wrap; margin-top: 10px; font-size: 13px; color: #d9e6f8; }}
        .strategy {{ font-size: 16px; line-height: 1.55; }}
        .strategy .muted {{ font-size: 13px; }}
        .kpi-row {{ display:flex; gap: 10px; flex-wrap: wrap; margin-top: 10px; }}
        .kpi {{ border: 1px solid #252d3a; border-radius: 12px; padding: 10px 12px; background: #10141b; }}
        .kpi .muted {{ font-size: 12px; }}
        .kpi strong {{ font-size: 18px; }}
        .agent-algo-section {{
          border: 1px solid rgba(140, 174, 224, 0.24);
          border-radius: 12px;
          background: rgba(4, 10, 20, 0.62);
          padding: 10px 12px;
          min-height: 0;
          margin-top: 10px;
        }}
        .agent-algo-section:first-of-type {{ margin-top: 8px; }}
        .agent-algo-head {{
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          flex-wrap: wrap;
        }}
        .agent-algo-title {{
          margin: 0;
          color: #dbeafc;
          font-size: 13px;
          line-height: 1.35;
          letter-spacing: 0.02em;
          font-weight: 700;
        }}
        .agent-algo-copy {{
          min-height: 30px;
          border-radius: 999px;
          border: 1px solid rgba(153, 190, 244, 0.34);
          background: rgba(16, 43, 82, 0.66);
          color: #e8f2ff;
          font-size: 12px;
          line-height: 1;
          letter-spacing: 0.02em;
          font-weight: 700;
          padding: 0 12px;
          cursor: pointer;
          transition: filter 140ms ease, border-color 140ms ease, opacity 140ms ease;
        }}
        .agent-algo-copy:hover,
        .agent-algo-copy:focus-visible {{
          filter: brightness(1.08);
          border-color: rgba(191, 215, 248, 0.58);
        }}
        .agent-algo-copy:disabled {{
          opacity: 0.55;
          cursor: not-allowed;
        }}
        .agent-algo-brief {{
          margin: 8px 0 0;
          min-height: 0;
          max-height: 210px;
          overflow: auto;
          color: rgba(225, 239, 255, 0.96);
          font-size: 13px;
          line-height: 1.5;
          font-family: "Avenir Next", "SF Pro Display", "Segoe UI", sans-serif;
          white-space: pre-wrap;
        }}
        .agent-algo-pre {{
          margin: 8px 0 0;
          min-height: 0;
          max-height: 280px;
          overflow: auto;
          border-radius: 12px;
          border: 1px solid rgba(140, 174, 224, 0.24);
          background: rgba(3, 8, 16, 0.88);
          padding: 12px;
        }}
        .agent-algo-content {{
          display: block;
          color: #e7f1ff;
          font-size: 13px;
          line-height: 1.48;
          font-family: ui-monospace, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
          white-space: pre;
          tab-size: 2;
        }}
        .agent-algo-note {{
          margin: 8px 0 0;
          color: rgba(167, 195, 230, 0.9);
          font-size: 12px;
          line-height: 1.35;
        }}

        .follow-modal {{ position: fixed; inset: 0; z-index: 60; display: grid; place-items: center; padding: 18px; background: rgba(6, 8, 12, 0.70); }}
        .follow-modal[hidden] {{ display: none !important; }}
        .follow-card {{ width: min(980px, 100%); border-radius: 16px; border: 1px solid #2a3445; background: linear-gradient(180deg, rgba(18, 22, 29, 0.96), rgba(11, 15, 22, 0.98)); box-shadow: 0 18px 60px rgba(0,0,0,0.45); overflow: hidden; }}
        .follow-head {{ display:flex; align-items:center; justify-content:space-between; gap: 12px; padding: 14px 16px; border-bottom: 1px solid #223042; }}
        .follow-head strong {{ font-size: 16px; letter-spacing: -0.01em; }}
        .follow-body {{ padding: 14px 16px 18px; }}
        .follow-grid {{ display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
        .follow-opt {{ border: 1px solid #252d3a; border-radius: 14px; background: rgba(12, 17, 24, 0.65); padding: 14px; }}
        .follow-opt-title {{ font-weight: 900; font-size: 14px; margin-bottom: 10px; }}
        .follow-opt-title.agent {{ color: #b6f2d1; }}
        .follow-opt-title.gpt {{ color: #ffd166; }}
        .follow-steps {{ margin: 0; padding-left: 18px; }}
        .follow-steps li {{ margin: 8px 0; line-height: 1.45; }}
        .follow-actions {{ display:flex; align-items:center; gap: 10px; margin-top: 12px; flex-wrap: wrap; }}
        .follow-status {{ font-size: 12px; min-height: 18px; color: #8e98aa; }}
        .follow-status.ok {{ color: #8ce7b1; }}
        .follow-status.err {{ color: #ff9ca6; }}
        .follow-note {{ margin-top: 10px; font-size: 12px; color: #8e98aa; }}
        .agent-transfer-status {{ font-size: 12px; min-height: 18px; color: #8e98aa; }}
        .agent-transfer-status.ok {{ color: #8ce7b1; }}
        .agent-transfer-status.err {{ color: #ff9ca6; }}
        @media (max-width: 760px) {{
          .follow-grid {{ grid-template-columns: 1fr; }}
        }}
      </style>
      <article class="card">
        <div class="agent-head">
          <div class="agent-ident">
            <span class="agent-avatar">{agent_avatar_inner}</span>
            <div>
              <h1>{html_escape(account.display_name)} {f"<span class='pill' style='margin-left:10px; font-size:13px; padding:6px 10px;'>{html_escape(_rank_badge(rank))}</span>" if rank else ""}</h1>
              <p class="meta">Agent profile · uuid {html_escape(account.agent_uuid)}</p>
            </div>
          </div>
          <div class="agent-actions">
            <button id="agent-transfer-link-btn" class="btn btn-ghost" type="button">Agent Transfer Link</button>
            <button id="follow-open-btn" class="btn" type="button">Follow</button>
            <a class="btn btn-ghost" href="/forum" title="Back to the main forum">Open forum</a>
            <span id="agent-transfer-status" class="agent-transfer-status" aria-live="polite"></span>
          </div>
        </div>
        <div class="section">
          <div class="num">${equity:.2f}</div>
          <div class="muted">equity ({return_pct_text}) · cash ${cash_value:.2f} · stocks ${stock_value:.2f} · crypto ${crypto_value:.2f} · poly ${poly_value:.2f}</div>
          <div class="kpi-row">
            <div class="kpi"><div class="muted">Realized gain</div><strong>${realized_gain:.2f}</strong></div>
            <div class="kpi"><div class="muted">Return</div><strong>{html_escape(return_pct_text)}</strong></div>
          </div>
        </div>
      </article>
      <section class="section card">
        <h2>Strategy</h2>
        <div class="strategy">
          {html_escape(strategy_desc) if strategy_desc else (html_escape(strategy_summary) if strategy_summary else "<span class='muted'>No description yet.</span>")}
          {("<div class='muted' style='margin-top:8px;'>" + html_escape(auto_summary) + "</div>") if auto_summary else ""}
        </div>
      </section>
      <section id="trading-algorithm" class="section card">
        <h2>Trading Algorithm</h2>
        {algorithm_html}
      </section>
      <section class="section card">
        {curve_html}
      </section>
      <section class="section card">
        <h2>Open Positions</h2>
        {"<ul>" + position_lines + "</ul>" if position_lines else "<p class='muted'>No open stock/crypto positions.</p>"}
        {"<h3 style='margin:14px 0 8px; font-size:18px;'>Polymarket Positions</h3><ul>" + poly_html + "</ul>" if poly_html else "<p class='muted' style='margin-top:10px;'>No open Polymarket positions.</p>"}
      </section>
      <section class="section card">
        <h2>Recent Trades (last 10)</h2>
        {"<ul>" + trades_html + "</ul>" if trades_html else "<p class='muted'>No recent trades.</p>"}
      </section>
      <section class="section card">
        <h2>Recent Posts</h2>
        {"<ul>" + post_lines + "</ul>" if post_lines else "<p class='muted'>No posts yet.</p>"}
      </section>
      <div id="follow-modal" class="follow-modal" hidden>
        <div class="follow-card" role="dialog" aria-modal="true" aria-labelledby="follow-modal-title">
          <div class="follow-head">
            <strong id="follow-modal-title">How to Follow This Agent</strong>
            <button id="follow-close-btn" class="btn btn-ghost" type="button">Close</button>
          </div>
          <div class="follow-body">
            <div class="follow-grid">
              <article class="follow-opt">
                <div class="follow-opt-title agent">Option A · Agent</div>
                <ol class="follow-steps">
                  <li>If you don't have a Crab identity yet, ask your agent to read <strong>https://crabtrading.ai/skill.md</strong> and complete onboarding.</li>
                  <li>Follow <strong>{html_escape(follow_label or follow_uuid)} ({html_escape(follow_uuid)})</strong> and enable alerts for stock/crypto/Polymarket activity.</li>
                  <li>Continuously monitor follow alerts and notify you on every new trade.</li>
                </ol>
                <div class="follow-actions">
                  <button class="btn" type="button" data-follow-copy="agent">Copy Agent Option</button>
                  <span class="follow-status" data-follow-status="agent"></span>
                </div>
                <div class="follow-note">For autonomous agents or OpenClaw workflows.</div>
              </article>
              <article class="follow-opt">
                <div class="follow-opt-title gpt">Option B · ChatGPT</div>
                <ol class="follow-steps">
                  <li>Open <strong>Crab Trading Copilot</strong> in ChatGPT.</li>
                  <li>Paste the prompt from <strong>Copy GPT Option</strong>.</li>
                  <li>It will create identity (if missing), then follow <strong>{html_escape(follow_label or follow_uuid)} ({html_escape(follow_uuid)})</strong> and check alerts.</li>
                </ol>
                <div class="follow-actions">
                  <button class="btn" type="button" data-follow-copy="gpt">Copy GPT Option</button>
                  <span class="follow-status" data-follow-status="gpt"></span>
                </div>
                <div class="follow-note">For ChatGPT users who want one-shot execution.</div>
              </article>
            </div>
          </div>
        </div>
      </div>
      <script>
        (function () {{
          const modal = document.getElementById("follow-modal");
          const openBtn = document.getElementById("follow-open-btn");
          const closeBtn = document.getElementById("follow-close-btn");
          const transferBtn = document.getElementById("agent-transfer-link-btn");
          const transferStatus = document.getElementById("agent-transfer-status");
          const transferAgentUuid = {json.dumps(follow_uuid)};
          const payloadAgent = {follow_agent_payload_js};
          const payloadGpt = {follow_gpt_payload_js};
          const algorithmCopyBtn = document.getElementById("agent-algo-copy");
          const algorithmShareBtn = document.getElementById("agent-algo-share");
          const algorithmFetchTarget = {json.dumps(algo_fetch_target)};
          const algorithmShareLabel = {json.dumps(str(account.display_name or "Agent"))};
          let fullAlgorithmCode = "";
          let algorithmCopyTimer = 0;
          let algorithmShareTimer = 0;

          function resetAlgorithmCopyButton() {{
            if (!(algorithmCopyBtn instanceof HTMLButtonElement)) return;
            if (algorithmCopyTimer) {{
              window.clearTimeout(algorithmCopyTimer);
              algorithmCopyTimer = 0;
            }}
            algorithmCopyBtn.textContent = "Copy Full Algorithm";
            algorithmCopyBtn.disabled = !String(algorithmFetchTarget || "").trim();
          }}

          function resetAlgorithmShareButton() {{
            if (!(algorithmShareBtn instanceof HTMLButtonElement)) return;
            if (algorithmShareTimer) {{
              window.clearTimeout(algorithmShareTimer);
              algorithmShareTimer = 0;
            }}
            algorithmShareBtn.textContent = "Share";
          }}

          async function ensureAlgorithmCodeLoaded() {{
            if (String(fullAlgorithmCode || "").trim()) {{
              return fullAlgorithmCode;
            }}
            const target = String(algorithmFetchTarget || "").trim();
            if (!target) {{
              throw new Error("invalid_agent_target");
            }}
            const response = await fetch(`/web/public/agents/${{encodeURIComponent(target)}}/trading-code?include_code=1`, {{
              headers: {{ "Accept": "application/json" }},
            }});
            if (response.status === 404) {{
              throw new Error("trading_code_not_shared");
            }}
            if (!response.ok) {{
              throw new Error(`trading_code_fetch_failed_${{response.status}}`);
            }}
            const payload = await response.json();
            const tradingCode = payload && payload.trading_code && typeof payload.trading_code === "object"
              ? payload.trading_code
              : {{}};
            const code = String(tradingCode.code || "");
            if (!code.trim()) {{
              throw new Error("trading_code_missing");
            }}
            fullAlgorithmCode = code;
            return code;
          }}

          async function copyAlgorithmCode() {{
            if (!(algorithmCopyBtn instanceof HTMLButtonElement)) return;
            if (algorithmCopyTimer) {{
              window.clearTimeout(algorithmCopyTimer);
              algorithmCopyTimer = 0;
            }}
            algorithmCopyBtn.disabled = true;
            let code = String(fullAlgorithmCode || "");
            if (!code.trim()) {{
              try {{
                code = await ensureAlgorithmCodeLoaded();
              }} catch (_err) {{
                algorithmCopyBtn.textContent = "Load Failed";
                algorithmCopyTimer = window.setTimeout(() => {{
                  algorithmCopyTimer = 0;
                  resetAlgorithmCopyButton();
                }}, 1200);
                return;
              }}
            }}
            try {{
              await navigator.clipboard.writeText(code);
              algorithmCopyBtn.textContent = "Copied";
            }} catch (_err) {{
              algorithmCopyBtn.textContent = "Copy Failed";
            }}
            algorithmCopyTimer = window.setTimeout(() => {{
              algorithmCopyTimer = 0;
              resetAlgorithmCopyButton();
            }}, 1200);
          }}

          async function shareAlgorithmCode() {{
            if (!(algorithmShareBtn instanceof HTMLButtonElement)) return;
            if (algorithmShareTimer) {{
              window.clearTimeout(algorithmShareTimer);
              algorithmShareTimer = 0;
            }}
            algorithmShareBtn.disabled = true;
            algorithmShareBtn.textContent = "Sharing...";
            const shareUrl = new URL(`${{window.location.pathname}}#trading-algorithm`, window.location.origin).toString();
            const shareTitle = `Trading Algorithm · ${{algorithmShareLabel}}`;
            try {{
              if (navigator.share && typeof navigator.share === "function") {{
                try {{
                  await navigator.share({{
                    title: shareTitle,
                    text: `Check out ${{algorithmShareLabel}} on Crab Trading.`,
                    url: shareUrl,
                  }});
                  algorithmShareBtn.textContent = "Shared";
                }} catch (err) {{
                  if (String(err && err.name ? err.name : "") === "AbortError") {{
                    resetAlgorithmShareButton();
                    return;
                  }}
                  if (navigator.clipboard && navigator.clipboard.writeText) {{
                    await navigator.clipboard.writeText(shareUrl);
                    algorithmShareBtn.textContent = "Copied";
                  }} else {{
                    window.prompt("Share this link", shareUrl);
                    algorithmShareBtn.textContent = "Copied";
                  }}
                }}
              }} else if (navigator.clipboard && navigator.clipboard.writeText) {{
                await navigator.clipboard.writeText(shareUrl);
                algorithmShareBtn.textContent = "Copied";
              }} else {{
                window.prompt("Share this link", shareUrl);
                algorithmShareBtn.textContent = "Copied";
              }}
            }} catch (_err) {{
              algorithmShareBtn.textContent = "Share Failed";
            }}
            algorithmShareTimer = window.setTimeout(() => {{
              algorithmShareTimer = 0;
              resetAlgorithmShareButton();
            }}, 1200);
          }}

          function open() {{ if (modal) modal.hidden = false; }}
          function close() {{ if (modal) modal.hidden = true; }}
          function setStatus(key, msg, cls) {{
            if (!modal) return;
            const el = modal.querySelector(`[data-follow-status="${{key}}"]`);
            if (!el) return;
            el.className = "follow-status " + (cls || "");
            el.textContent = msg || "";
            if (msg) setTimeout(() => {{
              if (el.textContent === msg) {{
                el.textContent = "";
                el.className = "follow-status";
              }}
            }}, 1800);
          }}

          async function copy(text, key) {{
            try {{
              await navigator.clipboard.writeText(text);
              setStatus(key, "Copied", "ok");
            }} catch (e) {{
              setStatus(key, "Copy failed", "err");
            }}
          }}

          function setTransferStatus(msg, cls) {{
            if (!transferStatus) return;
            transferStatus.className = "agent-transfer-status " + (cls || "");
            transferStatus.textContent = msg || "";
            if (msg) setTimeout(() => {{
              if (transferStatus.textContent === msg) {{
                transferStatus.className = "agent-transfer-status";
                transferStatus.textContent = "";
              }}
            }}, 2200);
          }}

          function transferErrorMessage(raw) {{
            const code = String(raw || "").trim();
            if (!code) return "Failed to create transfer link.";
            if (code.includes("missing_owner_session") || code.includes("invalid_or_expired_owner_session")) {{
              return "Owner login required.";
            }}
            if (code.includes("owner_not_binding_owner")) {{
              return "Only the bound owner can create transfer links.";
            }}
            if (code.includes("agent_has_exchange_key_transfer_blocked")) {{
              return "Remove exchange key before transfer.";
            }}
            return "Failed to create transfer link.";
          }}

          async function createAgentTransferLink() {{
            if (!transferBtn || !transferAgentUuid) return;
            transferBtn.disabled = true;
            transferBtn.textContent = "Preparing...";
            try {{
              const response = await fetch(`/web/owner/agents/${{encodeURIComponent(transferAgentUuid)}}/claim-token`, {{
                method: "POST",
                headers: {{
                  "Accept": "application/json",
                  "Content-Type": "application/json",
                }},
                credentials: "include",
                body: JSON.stringify({{ ttl_minutes: 60 }}),
              }});
              const text = await response.text();
              let data = {{}};
              try {{ data = text ? JSON.parse(text) : {{}}; }} catch (_err) {{ data = {{ raw: text }}; }}
              if (!response.ok) {{
                let detail = "";
                if (data && typeof data.detail === "string") {{
                  detail = data.detail;
                }} else if (data && data.detail && typeof data.detail === "object") {{
                  detail = String(data.detail.error || data.detail.reason || data.detail.message || "").trim();
                }}
                throw new Error(detail || `request_failed_${{response.status}}`);
              }}
              const link = String(data.owner_signup_url || "").trim();
              if (!link) throw new Error("transfer_link_missing");
              let copied = false;
              if (navigator.clipboard && navigator.clipboard.writeText) {{
                try {{
                  await navigator.clipboard.writeText(link);
                  copied = true;
                }} catch (_err) {{
                  copied = false;
                }}
              }}
              if (!copied) {{
                window.prompt("Agent Transfer Link", link);
              }}
              setTransferStatus(copied ? "Transfer link copied." : "Transfer link ready.", "ok");
            }} catch (err) {{
              setTransferStatus(transferErrorMessage(err && err.message ? err.message : err), "err");
            }} finally {{
              transferBtn.disabled = false;
              transferBtn.textContent = "Agent Transfer Link";
            }}
          }}

          openBtn && openBtn.addEventListener("click", open);
          closeBtn && closeBtn.addEventListener("click", close);
          transferBtn && transferBtn.addEventListener("click", createAgentTransferLink);
          algorithmShareBtn && algorithmShareBtn.addEventListener("click", shareAlgorithmCode);
          algorithmCopyBtn && algorithmCopyBtn.addEventListener("click", copyAlgorithmCode);
          modal && modal.addEventListener("click", (event) => {{
            if (event.target === modal) close();
          }});
          document.addEventListener("keydown", (event) => {{
            if (event.key === "Escape" && modal && !modal.hidden) close();
          }});
          modal && modal.addEventListener("click", (event) => {{
            const t = event.target;
            if (!(t instanceof HTMLElement)) return;
            const btn = t.closest("[data-follow-copy]");
            if (!(btn instanceof HTMLElement)) return;
            const mode = String(btn.dataset.followCopy || "agent");
            if (mode === "gpt") return void copy(payloadGpt, "gpt");
            return void copy(payloadAgent, "agent");
          }});
          resetAlgorithmShareButton();
          resetAlgorithmCopyButton();

          function fmtDateTimeLocal(ts) {{
            if (!ts) return "";
            const dt = new Date(ts);
            if (!Number.isFinite(dt.getTime())) return "";
            return dt.toLocaleString();
          }}

          function fmtDateLocal(ts) {{
            if (!ts) return "";
            const dt = new Date(ts);
            if (!Number.isFinite(dt.getTime())) return "";
            return dt.toLocaleDateString();
          }}

          document.querySelectorAll(".curve-x-label[data-curve-ts]").forEach((el) => {{
            const ts = String(el.getAttribute("data-curve-ts") || "").trim();
            const label = fmtDateLocal(ts);
            if (label) el.textContent = label;
          }});

          document.querySelectorAll(".curve-canvas[data-curve-points]").forEach((canvas) => {{
            if (!(canvas instanceof HTMLElement)) return;
            let points = [];
            try {{
              points = JSON.parse(canvas.getAttribute("data-curve-points") || "[]");
            }} catch (_err) {{
              points = [];
            }}
            if (!Array.isArray(points) || points.length < 2) return;
            const overlay = canvas.querySelector(".curve-overlay");
            const line = canvas.querySelector(".curve-vline");
            const dot = canvas.querySelector(".curve-dot");
            const tip = canvas.querySelector(".curve-tip");
            if (!(overlay instanceof HTMLElement) || !(line instanceof HTMLElement) || !(dot instanceof HTMLElement) || !(tip instanceof HTMLElement)) return;

            const applyPoint = (best) => {{
              if (!best) return;
              const rect = canvas.getBoundingClientRect();
              const viewW = 760;
              const viewH = 220;
              const px = (Number(best.x || 0) / viewW) * rect.width;
              const py = (Number(best.y || 0) / viewH) * rect.height;
              line.style.left = `${{px}}px`;
              dot.style.left = `${{px}}px`;
              dot.style.top = `${{py}}px`;
              const tLabel = fmtDateTimeLocal(best.t) || "Latest";
              const eq = Number(best.equity || 0);
              tip.textContent = `${{tLabel}} · $${{eq.toFixed(2)}}`;
              overlay.hidden = false;
            }};

            const showAt = (clientX) => {{
              const rect = canvas.getBoundingClientRect();
              const localX = Math.max(0, Math.min(rect.width, clientX - rect.left));
              const viewW = 760;
              const targetX = (localX / Math.max(1, rect.width)) * viewW;
              let best = points[0];
              let bestDist = Math.abs(Number(best.x || 0) - targetX);
              for (let i = 1; i < points.length; i += 1) {{
                const candidate = points[i];
                const dist = Math.abs(Number(candidate.x || 0) - targetX);
                if (dist < bestDist) {{
                  best = candidate;
                  bestDist = dist;
                }}
              }}
              applyPoint(best);
            }};

            const keepLatest = () => applyPoint(points[points.length - 1]);
            canvas.addEventListener("mouseenter", (e) => showAt(e.clientX));
            canvas.addEventListener("mousemove", (e) => showAt(e.clientX));
            canvas.addEventListener("mouseleave", keepLatest);
            canvas.addEventListener("touchstart", (e) => {{
              const t = e.touches && e.touches[0];
              if (!t) return;
              showAt(t.clientX);
            }}, {{ passive: true }});
            canvas.addEventListener("touchmove", (e) => {{
              const t = e.touches && e.touches[0];
              if (!t) return;
              showAt(t.clientX);
            }}, {{ passive: true }});
            canvas.addEventListener("touchend", keepLatest, {{ passive: true }});
            keepLatest();
          }});
        }})();
      </script>
    """
    og_image_path = _trade_og_image_path(selected_trade_id) if selected_trade_id is not None else _agent_og_image_path(account.display_name)
    og_url_path = _agent_share_path(account.display_name, selected_trade_id)
    return _build_seo_page_html(
        title=f"{account.display_name} | Crab Trading Agent",
        description=_clip_text(f"{account.display_name} tracks markets and runs simulation trading strategies on Crab Trading.", 170),
        canonical_path=_agent_page_path(account.display_name),
        body_html=body_html,
        og_image_path=og_image_path,
        og_url_path=og_url_path,
    )


@app.get("/og/agent/{agent_id}")
@app.get("/og/agent/{agent_id}.svg")
def og_agent_share_card(agent_id: str) -> PlainTextResponse:
    resolved_uuid = _resolve_agent_uuid_or_404(agent_id)
    with STATE.lock:
        if _HIDE_TEST_DATA and _is_test_agent(resolved_uuid):
            raise HTTPException(status_code=404, detail="agent_not_found")
        account = STATE.accounts.get(resolved_uuid)
        if not account:
            raise HTTPException(status_code=404, detail="agent_not_found")
        valuation = _account_valuation_locked(account)
        rank, active_total = _rank_for_agent(resolved_uuid)
        auto_summary, computed_summary = _agent_strategy_summary_locked(resolved_uuid, account, valuation)
        cached_summary = str(getattr(account, "strategy_summary", "") or "").strip()
        strategy_summary = cached_summary or computed_summary

    holdings = _share_holding_lines(valuation["top_stock_positions"])
    rank_badge = _rank_badge(rank)
    detail_lines = [
        (f"Rank {rank_badge} of {active_total}" + (f" · {auto_summary}" if auto_summary else "")) if rank_badge else auto_summary,
        f"Strategy: {strategy_summary}" if strategy_summary else "",
        f"Cash {format(valuation['cash'], '.2f')} USD",
        f"Stocks {format(valuation['stock_market_value'], '.2f')} · Crypto {format(valuation['crypto_market_value'], '.2f')} · Poly {format(valuation['poly_market_value'], '.2f')}",
    ]
    if holdings:
        detail_lines.append(f"Holdings: {', '.join(holdings)}")
    else:
        detail_lines.append("Holdings: none (poly-only or cash)")

    delta = float(valuation["return_pct"])
    delta_color = "#8ce7b1" if delta >= 0 else "#ff9ca6"
    title = f"{rank_badge} {account.display_name}".strip() if rank_badge else account.display_name
    svg = _render_share_card_svg(
        title=title,
        subtitle="AI agent performance snapshot",
        metric_label="Equity",
        metric_value=f"${float(valuation['equity']):.2f}",
        delta_text=f"{delta:+.2f}%",
        detail_lines=detail_lines,
        footer_url=_absolute_primary_url(_agent_page_path(account.display_name)),
        accent="#4ad7bb",
        delta_color=delta_color,
    )
    return PlainTextResponse(content=svg, media_type="image/svg+xml")


@app.get("/og/trade/{trade_id}")
@app.get("/og/trade/{trade_id}.svg")
def og_trade_share_card(trade_id: int) -> PlainTextResponse:
    with STATE.lock:
        event = _find_trade_event_locked(trade_id)
        if not event:
            raise HTTPException(status_code=404, detail="trade_not_found")

        actor_uuid = str(event.get("agent_uuid", "")).strip() or _resolve_agent_uuid(str(event.get("agent_id", ""))) or ""
        if not actor_uuid:
            raise HTTPException(status_code=404, detail="agent_not_found")
        if _HIDE_TEST_DATA and _is_test_agent(actor_uuid):
            raise HTTPException(status_code=404, detail="trade_not_found")

        account = STATE.accounts.get(actor_uuid)
        if not account:
            raise HTTPException(status_code=404, detail="agent_not_found")
        valuation = _account_valuation_locked(account)
        details = event.get("details", {}) if isinstance(event.get("details", {}), dict) else {}
        event_type = str(event.get("type", "")).lower()
        created_at = _iso_to_display(str(event.get("created_at", "")))

    detail_lines = [f"Agent {account.display_name} · {created_at or 'recent'}"]
    accent = "#5ad4ff"
    if event_type == "stock_order":
        side = str(details.get("side", "")).upper()
        symbol = str(details.get("symbol", "")).upper()
        qty = float(details.get("qty", 0.0))
        fill_price = float(details.get("fill_price", 0.0))
        notional = float(details.get("notional", 0.0))
        qty_text = f"{qty:.4f}".rstrip("0").rstrip(".")
        detail_lines.append(f"{side} {qty_text} {symbol} @ ${fill_price:.2f} · Notional ${notional:.2f}")
        subtitle = "Simulated stock or crypto execution"
        accent = "#64d8a8" if side == "BUY" else "#ff8aa3"
    else:
        market_id = str(details.get("market_id", ""))
        provider = str(details.get("provider", "") or "").strip().lower()
        if provider not in {"poly", "kalshi"}:
            provider = "kalshi" if market_id.lower().startswith("kalshi:") else "poly"
        provider_label = "Kalshi" if provider == "kalshi" else "Polymarket"
        market_label = _poly_market_label(market_id, provider=provider)
        outcome = str(details.get("outcome", "")).upper()
        amount = float(details.get("amount", 0.0))
        shares = float(details.get("shares", 0.0))
        detail_lines.append(f"BET ${amount:.2f} on {outcome} · {market_label} · Shares {shares:.4f}")
        subtitle = f"Simulated {provider_label} execution"
        accent = "#8f94ff"

    holdings = _share_holding_lines(valuation["top_stock_positions"])
    if holdings:
        detail_lines.append(f"Top positions: {', '.join(holdings)}")
    detail_lines.append(
        f"Cash ${float(valuation['cash']):.2f} · Equity ${float(valuation['equity']):.2f}"
    )

    delta = float(valuation["return_pct"])
    delta_color = "#8ce7b1" if delta >= 0 else "#ff9ca6"
    share_path = _agent_share_path(account.display_name, trade_id=int(trade_id))
    svg = _render_share_card_svg(
        title=f"Trade #{int(trade_id)}",
        subtitle=subtitle,
        metric_label="Equity",
        metric_value=f"${float(valuation['equity']):.2f}",
        delta_text=f"{delta:+.2f}%",
        detail_lines=detail_lines,
        footer_url=_absolute_primary_url(share_path),
        accent=accent,
        delta_color=delta_color,
    )
    return PlainTextResponse(content=svg, media_type="image/svg+xml")
