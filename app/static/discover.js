(() => {
  const WINDOW_SET = new Set(["24h", "7d", "30d"]);
  const WINDOW_LABEL = {
    "24h": "24H",
    "7d": "This Week",
    "30d": "30 Days",
  };
  const SECTION_DEFAULT_VISIBLE = 6;
  const COLD_START_THRESHOLD = 12;
  const RECENT_TRANSACTION_DEFAULT_VISIBLE = 20;
  const RECENT_TRANSACTION_FETCH_LIMIT = 120;
  const DISCOVERY_ROWS_ENDPOINTS = [
    "/api/v1/public/discovery/agents",
    "/web/public/follow/discovery",
  ];
  const RECENT_TRANSACTIONS_ENDPOINTS = [
    "/api/v1/public/discovery/activity",
    "/web/sim/recent-orders",
  ];
  const TRADING_CODE_ENDPOINT_BUILDERS = [
    (target, queryString) => `/api/v1/public/discovery/agents/${encodeURIComponent(target)}/trading-code?${queryString}`,
    (target, queryString) => `/web/public/agents/${encodeURIComponent(target)}/trading-code?${queryString}`,
  ];
  const AGENT_SUMMARY_ENDPOINT_BUILDERS = [
    (target) => `/web/sim/agents/${encodeURIComponent(target)}/recent-trades?limit=1`,
  ];

  const state = {
    activeWindow: "30d",
    isLoggedIn: false,
    ownerEmail: "",
    searchTicker: "",
    dataSource: "public",
    requestSeq: 0,
    activeRows: [],
    trendingRows: [],
    rowsByWindow: {},
    recentTransactions: [],
    recentTransactionsLoading: false,
    recentTransactionsError: "",
    recentTransactionsExpanded: false,
    sectionVisibleCount: {
      top: SECTION_DEFAULT_VISIBLE,
      trending: SECTION_DEFAULT_VISIBLE,
      newer: SECTION_DEFAULT_VISIBLE,
      all: SECTION_DEFAULT_VISIBLE,
    },
    codeLoadingByAgent: {},
    algorithmPreviewCacheByAgent: {},
    algorithmCodeCacheByAgent: {},
    activeAlgorithmAgent: "",
    activeAlgorithmCode: "",
    activeAlgorithmOverview: {
      asset: "-",
      logic: "-",
      execution: "-",
    },
    activeAlgorithmSections: {
      plain: [],
      rules: [],
      code: "",
      note: "",
    },
    isAlgorithmDrawerOpen: false,
    copyResetTimer: 0,
    lastDrawerTrigger: null,
  };

  const topActionsEl = document.querySelector(".top-actions");
  const accountLinkEl = document.getElementById("discover-account-link");
  const newAgentLinkEl = document.getElementById("discover-new-agent-link");
  const discoverNavLinkEl = document.getElementById("discover-nav-link");

  const discoverSectionsEl = document.getElementById("discover-sections");
  const discoverStatusEl = document.getElementById("discover-status");
  const discoverMetaNoteEl = document.getElementById("discover-meta-note");
  const discoverSortNoteEl = document.getElementById("discover-sort-note");
  const recentTransactionsListEl = document.getElementById("discover-recent-transactions-list");

  const windowButtons = Array.from(document.querySelectorAll(".window-btn[data-window]"));
  const searchFormEl = document.getElementById("discover-search-form");
  const searchInputEl = document.getElementById("discover-search-input");
  const searchSubmitEl = document.getElementById("discover-search-submit");

  const codeLayerEl = document.getElementById("discover-code-layer");
  const codeBgEl = document.getElementById("discover-code-bg");
  const codeCardEl = document.querySelector(".discover-code-card");
  const codeCloseEl = document.getElementById("discover-code-close");
  const codeTitleEl = document.getElementById("discover-code-title");
  const codeMetaEl = document.getElementById("discover-code-meta");
  const codeCopyEl = document.getElementById("discover-code-copy");
  const codeContentEl = document.getElementById("discover-code-content");
  const codeNoteEl = document.getElementById("discover-code-note");
  const codeStrategySectionEl = document.getElementById("discover-code-strategy-section");
  const codeBriefListEl = document.getElementById("discover-code-brief-list");
  const codeRulesSectionEl = document.getElementById("discover-code-rules-section");
  const codeRulesListEl = document.getElementById("discover-code-rules-list");

  const overviewSectionEl = document.getElementById("discover-code-overview-section");
  const overviewAssetItemEl = document.getElementById("discover-overview-item-asset");
  const overviewLogicItemEl = document.getElementById("discover-overview-item-logic");
  const overviewExecutionItemEl = document.getElementById("discover-overview-item-execution");
  const overviewAssetEl = document.getElementById("discover-overview-asset");
  const overviewLogicEl = document.getElementById("discover-overview-logic");
  const overviewExecutionEl = document.getElementById("discover-overview-execution");

  function sanitizeText(value) {
    const raw = String(value || "");
    if (!raw) return "";
    return raw
      .replace(/transparent\s+trading\s+algorithms?/gi, "trading algorithms")
      .replace(/transparent\s+ai\s+trading\s+agents?/gi, "AI trading agents")
      .replace(/transparent\s+algorithms?/gi, "trading algorithms")
      .replace(/view\s+plain-english\s+logic\s*&\s*code/gi, "View Algorithm")
      .replace(/\s+/g, " ")
      .trim();
  }

  function isMeaningfulText(value) {
    const text = sanitizeText(value);
    if (!text) return false;
    if (/^[-=_*#~`|.:+/\\]+$/.test(text)) return false;
    return /[A-Za-z0-9\u4e00-\u9fff]/.test(text);
  }

  function looksLikeCodeToken(value) {
    const text = String(value || "").trim();
    if (!text) return false;
    if (text.length > 40) return false;
    return /^[A-Z0-9_]+$/.test(text);
  }

  function truncateText(value, maxChars) {
    const text = sanitizeText(value);
    if (!text) return "";
    if (text.length <= maxChars) return text;
    return `${text.slice(0, Math.max(1, maxChars - 1)).trimEnd()}…`;
  }

  function normalizeWindow(value) {
    const key = String(value || "").trim().toLowerCase();
    return WINDOW_SET.has(key) ? key : "30d";
  }

  function normalizeSymbolQuery(value) {
    const raw = String(value || "").trim().toUpperCase();
    if (!raw) return "";
    const cleaned = raw.replace(/[^A-Z0-9]/g, "");
    return cleaned.slice(0, 24);
  }

  function normalizePositiveInt(value, fallback = 1) {
    const num = Number(value);
    if (!Number.isFinite(num)) return Math.max(1, Number(fallback) || 1);
    return Math.max(1, Math.floor(num));
  }

  function toneClassForKey(value) {
    const text = String(value || "unknown");
    let hash = 0;
    for (let i = 0; i < text.length; i += 1) {
      hash = ((hash * 31) + text.charCodeAt(i)) >>> 0;
    }
    return `discover-card-tone-${(hash % 6) + 1}`;
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatPct(value) {
    const num = Number(value || 0);
    if (!Number.isFinite(num)) return "+0.00%";
    const prefix = num >= 0 ? "+" : "";
    return `${prefix}${num.toFixed(2)}%`;
  }

  function formatMoney(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) return "";
    const abs = Math.abs(num);
    const sign = num < 0 ? "-" : "";
    return `${sign}$${abs.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  }

  function formatSignedGainMoney(value) {
    const num = toFiniteNumber(value);
    if (num == null) return "";
    const abs = Math.abs(num);
    if (abs < 0.000001) return "$0.00";
    const sign = num > 0 ? "+" : "-";
    return `${sign}$${abs.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function formatQuantity(value) {
    const num = Number(value);
    if (!Number.isFinite(num) || num <= 0) return "";
    if (num >= 1000) {
      return num.toLocaleString(undefined, { maximumFractionDigits: 0 });
    }
    if (num >= 1) {
      return num.toLocaleString(undefined, { maximumFractionDigits: 3 });
    }
    return num.toLocaleString(undefined, { maximumFractionDigits: 6 });
  }

  function formatRelativeTime(value) {
    const date = parseIsoDate(value);
    if (!date) return "";
    const now = Date.now();
    const diffMs = now - date.getTime();
    if (!Number.isFinite(diffMs)) return "";
    if (diffMs < 60 * 1000) return "just now";
    if (diffMs < 60 * 60 * 1000) {
      return `${Math.max(1, Math.floor(diffMs / (60 * 1000)))}m ago`;
    }
    if (diffMs < 24 * 60 * 60 * 1000) {
      return `${Math.max(1, Math.floor(diffMs / (60 * 60 * 1000)))}h ago`;
    }
    if (diffMs < 7 * 24 * 60 * 60 * 1000) {
      return `${Math.max(1, Math.floor(diffMs / (24 * 60 * 60 * 1000)))}d ago`;
    }
    return date.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

  function isSameLocalCalendarDate(left, right) {
    if (!(left instanceof Date) || !(right instanceof Date)) return false;
    return (
      left.getFullYear() === right.getFullYear()
      && left.getMonth() === right.getMonth()
      && left.getDate() === right.getDate()
    );
  }

  function leadingTodayTransactionCount(rows) {
    const list = Array.isArray(rows) ? rows : [];
    if (!list.length) return 0;
    const now = new Date();
    let count = 0;
    for (const row of list) {
      const createdAt = parseIsoDate(row && row.created_at);
      if (!createdAt || !isSameLocalCalendarDate(createdAt, now)) break;
      count += 1;
    }
    return count;
  }

  function collapsedRecentTransactionCount(rows) {
    const list = Array.isArray(rows) ? rows : [];
    if (!list.length) return 0;
    const todayCount = leadingTodayTransactionCount(list);
    if (todayCount > 0) {
      return Math.min(todayCount, RECENT_TRANSACTION_DEFAULT_VISIBLE);
    }
    return Math.min(list.length, RECENT_TRANSACTION_DEFAULT_VISIBLE);
  }

  function normalizeTransactionSide(side, effectiveAction) {
    const primary = String(side || "").trim().toUpperCase();
    if (primary === "BUY" || primary === "SELL") return primary;
    const fallback = String(effectiveAction || "").trim().toUpperCase();
    if (fallback.includes("BUY")) return "BUY";
    if (fallback.includes("SELL")) return "SELL";
    return "TRADE";
  }

  function normalizePredictionProvider(value) {
    const raw = String(value || "").trim().toLowerCase();
    return raw === "kalshi" ? "kalshi" : "poly";
  }

  function predictionProviderTag(value) {
    return normalizePredictionProvider(value) === "kalshi" ? "KAL" : "POLY";
  }

  function predictionVenueLabel(value) {
    return normalizePredictionProvider(value) === "kalshi" ? "Kalshi" : "Polymarket";
  }

  function parseIsoDate(value) {
    const raw = String(value || "").trim();
    if (!raw) return null;
    const direct = new Date(raw);
    if (Number.isFinite(direct.getTime())) return direct;

    const compactOffset = raw.match(/^(.*?)([+-]\d{2})(\d{2})$/);
    if (compactOffset) {
      const normalized = `${compactOffset[1]}${compactOffset[2]}:${compactOffset[3]}`;
      const withOffset = new Date(normalized);
      if (Number.isFinite(withOffset.getTime())) return withOffset;
    }

    const utcLabel = raw.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?\s*UTC$/i);
    if (utcLabel) {
      const date = new Date(Date.UTC(
        Number(utcLabel[1]),
        Number(utcLabel[2]) - 1,
        Number(utcLabel[3]),
        Number(utcLabel[4]),
        Number(utcLabel[5]),
        Number(utcLabel[6] || "0"),
      ));
      if (Number.isFinite(date.getTime())) return date;
    }

    const naiveIso = raw.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?$/);
    if (naiveIso) {
      const millis = String(naiveIso[7] || "").slice(0, 3).padEnd(3, "0");
      const date = new Date(Date.UTC(
        Number(naiveIso[1]),
        Number(naiveIso[2]) - 1,
        Number(naiveIso[3]),
        Number(naiveIso[4]),
        Number(naiveIso[5]),
        Number(naiveIso[6] || "0"),
        Number(millis || "0"),
      ));
      if (Number.isFinite(date.getTime())) return date;
    }

    return null;
  }

  function daysSinceIso(value) {
    const date = parseIsoDate(value);
    if (!date) return null;
    const diff = Date.now() - date.getTime();
    if (!Number.isFinite(diff) || diff < 0) return 1;
    return Math.max(1, Math.floor(diff / (24 * 60 * 60 * 1000)));
  }

  function isImageAvatar(value) {
    const text = String(value || "").trim();
    if (!text) return false;
    return /^(https?:\/\/|\/|data:image\/)/i.test(text);
  }

  function avatarMarkup(avatar, name) {
    const safeAvatar = String(avatar || "").trim();
    if (isImageAvatar(safeAvatar)) {
      return `<img src="${escapeHtml(safeAvatar)}" alt="" loading="lazy" decoding="async" />`;
    }
    const first = String(name || "").trim().charAt(0).toUpperCase() || "C";
    return `<span>${escapeHtml(first)}</span>`;
  }

  function normalizeSymbols(values) {
    if (!Array.isArray(values)) return [];
    const out = [];
    const seen = new Set();
    for (const item of values) {
      const symbol = normalizeSymbolQuery(item);
      if (!symbol || seen.has(symbol)) continue;
      out.push(symbol);
      seen.add(symbol);
      if (out.length >= 8) break;
    }
    return out;
  }

  function normalizeStyleLabel(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/-/g, " ")
      .replace(/\s+/g, " ");
  }

  function shortStyleTag(value) {
    const raw = String(value || "").trim();
    const key = normalizeStyleLabel(raw);
    if (!key) return "Strategy";
    if (key === "large cap swing") return "Swing";
    if (key === "volatility hunter") return "Volatility";
    if (key === "option scalper") return "Scalper";
    if (key === "momentum trader") return "Momentum";
    if (key === "ai macro") return "Macro";
    return raw;
  }

  function isCryptoSymbol(symbol) {
    const text = String(symbol || "").trim().toUpperCase();
    if (!text) return false;
    const baseSet = new Set([
      "BTC",
      "ETH",
      "SOL",
      "BNB",
      "XRP",
      "DOGE",
      "ADA",
      "AVAX",
      "DOT",
      "MATIC",
      "LTC",
      "LINK",
      "UNI",
      "ATOM",
      "ARB",
      "OP",
    ]);
    if (baseSet.has(text)) return true;
    return /(?:USD|USDT|USDC|BUSD)$/.test(text) && baseSet.has(text.replace(/(?:USD|USDT|USDC|BUSD)$/, ""));
  }

  function categoryLabelFromRow(row) {
    const rawCategory = String(row.category || "").trim().toLowerCase();
    if (rawCategory === "stocks") return "US Equity";
    if (rawCategory === "crypto") return "Crypto";
    if (rawCategory === "mixed") return "Multi-Asset";

    const symbols = normalizeSymbols(row.symbols || []);
    if (!symbols.length) return "Multi-Asset";
    const cryptoCount = symbols.filter((sym) => isCryptoSymbol(sym)).length;
    if (cryptoCount === symbols.length) return "Crypto";
    if (cryptoCount === 0) return "US Equity";
    return "Multi-Asset";
  }

  function cleanSummaryText(text, maxChars = 80) {
    const normalized = sanitizeText(text)
      .split(/\s+/)
      .filter(Boolean)
      .join(" ")
      .trim();
    if (!isMeaningfulText(normalized)) return "";
    if (!normalized) return "";
    if (normalized.length <= maxChars) return normalized;
    return `${normalized.slice(0, Math.max(1, maxChars - 3)).trimEnd()}...`;
  }

  function narrativeDedupKey(value) {
    const text = sanitizeText(value).toLowerCase();
    if (!text) return "";
    return text
      .replace(/[^a-z0-9\u4e00-\u9fff\s]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function hasDenseSymbolNoise(value) {
    const text = String(value || "").trim();
    if (!text) return false;
    const symbolCount = (text.match(/[{}[\];=<>`]/g) || []).length;
    return symbolCount >= 4 && symbolCount * 6 >= text.length;
  }

  function looksLikeCodeLine(value) {
    const text = String(value || "").trim();
    if (!text) return false;
    if (/^\s*(if|elif|else|for|while|return|def|class|const|let|var|function|import|from)\b/i.test(text)) {
      return true;
    }
    if (/[{}[\];]/.test(text) || /=>/.test(text)) return true;
    if (/\breturn\s*[{\[]/i.test(text)) return true;
    if (/[<>!=]=/.test(text) && /[_$][a-z0-9_]+/i.test(text)) return true;
    return hasDenseSymbolNoise(text);
  }

  function isLowValueNarrative(value) {
    const text = sanitizeText(value);
    if (!text) return true;
    if (/^plain-english strategy summary\.?$/i.test(text)) return true;
    if (/^strategy summary\.?$/i.test(text)) return true;
    if (/^session-aware automated schedule\.?$/i.test(text)) return true;
    if (/^market:\s*[a-z0-9/_\-.]+(?:\s*\([^)]*\))?\.?$/i.test(text)) return true;
    return false;
  }

  function normalizeNarrativeLine(value, maxChars = 160) {
    let text = sanitizeText(value);
    if (!text) return "";

    if (/cron:/i.test(text)) {
      text = text.replace(/\s*\(?\s*cron:\s*[^)]+\)?/ig, "").trim();
      if (!text) text = "Scheduled during market hours.";
    }

    if (/\([^)]{34,}\)/.test(text)) {
      text = text.replace(/\([^)]{34,}\)/g, "").replace(/\s+/g, " ").trim();
    }

    const cleaned = cleanSummaryText(text, maxChars);
    if (!cleaned) return "";
    if (isLowValueNarrative(cleaned)) return "";
    if (looksLikeCodeLine(cleaned)) return "";
    if (hasDenseSymbolNoise(cleaned)) return "";
    return cleaned;
  }

  function dedupeNarrativeLines(lines, { maxItems = 3, blockedKeys } = {}) {
    const out = [];
    const seen = new Set();
    const blocked = blockedKeys instanceof Set ? blockedKeys : new Set();
    const source = Array.isArray(lines) ? lines : [];

    for (const line of source) {
      const cleaned = normalizeNarrativeLine(line, 160);
      if (!cleaned) continue;
      const key = narrativeDedupKey(cleaned);
      if (!key || seen.has(key) || blocked.has(key)) continue;
      seen.add(key);
      out.push(cleaned);
      if (out.length >= maxItems) break;
    }

    return out;
  }

  function summaryFromRow(row) {
    const strategy = cleanSummaryText(row.strategy_text || "", 80);
    if (strategy) return strategy;
    return "";
  }

  function isMachineAgentId(value) {
    const text = String(value || "").trim();
    if (!text) return false;
    return /^[A-Z]{2,10}\d{1,4}$/.test(text);
  }

  function displayNameForRow(row) {
    const explicit = sanitizeText(String(row.display_name_public || "").trim());
    if (explicit) return explicit;

    const agentId = sanitizeText(String(row.agent_id || "").trim());
    if (!agentId) return "Unknown Agent";
    if (!isMachineAgentId(agentId)) return agentId;

    const symbols = normalizeSymbols(row.symbols || []);
    const primary = symbols[0] || agentId.replace(/\d+$/g, "");
    const style = shortStyleTag(row.style_tag || row.risk_label || "Strategy");
    return `${primary} ${style} Agent`;
  }

  function parseRank(value) {
    const num = Number(value);
    if (!Number.isFinite(num) || num < 1) return 0;
    return Math.floor(num);
  }

  function toLiveDays(data) {
    const direct = Number(data.live_days);
    if (Number.isFinite(direct) && direct > 0) return Math.floor(direct);
    const fromRegistered = daysSinceIso(data.registered_at);
    if (Number.isFinite(fromRegistered) && fromRegistered > 0) return Math.floor(fromRegistered);
    return null;
  }

  function toTradesExecuted(data) {
    const direct = Number(data.trades_executed_total);
    if (Number.isFinite(direct) && direct >= 0) return Math.floor(direct);
    const activity = Number(data.activity_stats && data.activity_stats.activity_events);
    if (Number.isFinite(activity) && activity >= 0) return Math.floor(activity);
    return null;
  }

  function toFiniteNumber(value) {
    if (value == null) return null;
    if (typeof value === "boolean") return null;
    if (typeof value === "string") {
      const text = value.trim();
      if (!text) return null;
      const num = Number(text);
      return Number.isFinite(num) ? num : null;
    }
    const num = Number(value);
    return Number.isFinite(num) ? num : null;
  }

  function toBalanceUsd(data) {
    const candidates = [
      data.capital_allocated_usd,
      data.equity,
      data.balance,
      data.balance_usd,
      data.aum,
    ];
    for (const candidate of candidates) {
      const num = toFiniteNumber(candidate);
      if (num == null) continue;
      return num;
    }
    return null;
  }

  function toRealizedGainUsd(data) {
    const candidates = [
      data.realized_gain_usd,
      data.settled_pnl,
      data.realized_pnl,
      data.total_profit_generated_usd,
    ];
    for (const candidate of candidates) {
      const num = toFiniteNumber(candidate);
      if (num == null) continue;
      return num;
    }
    const stockRealized = toFiniteNumber(data.stock_realized_pnl);
    const polyRealized = toFiniteNumber(data.poly_realized_pnl);
    const kalshiRealized = toFiniteNumber(data.kalshi_realized_pnl);
    if (stockRealized == null && polyRealized == null && kalshiRealized == null) return null;
    return (stockRealized || 0) + (polyRealized || 0) + (kalshiRealized || 0);
  }

  function mapDiscoveryRows(rows, windowName) {
    const list = Array.isArray(rows) ? rows : [];
    return list.map((row) => {
      const data = row && typeof row === "object" ? row : {};
      const agentUuid = String(data.agent_uuid || "").trim();
      const agentId = String(data.agent_id || agentUuid || "unknown").trim() || "unknown";
      const symbols = normalizeSymbols(data.symbols);
      return {
        key: agentUuid || agentId,
        agent_uuid: agentUuid,
        agent_id: agentId,
        display_name_public: String(data.display_name_public || "").trim(),
        avatar: String(data.avatar || "").trim(),
        rank: parseRank(data.rank),
        return_pct: Number(data.return_pct || 0),
        style_tag: String(data.style_tag || "").trim(),
        risk_label: String(data.risk_label || "").trim(),
        strategy_text: String(data.strategy_text || "").trim(),
        symbols,
        category: String(data.category || "").trim().toLowerCase(),
        live_days: toLiveDays(data),
        trades_executed_total: toTradesExecuted(data),
        registered_at: String(data.registered_at || "").trim(),
        activity_events: toFiniteNumber(data.activity_stats && data.activity_stats.activity_events) || 0,
        total_profit_generated_usd: toFiniteNumber(data.total_profit_generated_usd),
        capital_allocated_usd: toFiniteNumber(data.capital_allocated_usd),
        balance_usd: toBalanceUsd(data),
        realized_gain_usd: toRealizedGainUsd(data),
        execution_frequency: String(data.execution_frequency || "").trim(),
        window_label: WINDOW_LABEL[windowName] || "30 Days",
      };
    });
  }

  function mapRecentTransactionRows(rows) {
    const list = Array.isArray(rows) ? rows : [];
    return list.map((row, index) => {
      const data = row && typeof row === "object" ? row : {};
      const type = String(data.type || "stock_order").trim().toLowerCase();
      const createdAt = String(data.created_at || "").trim();
      const idText = String(data.id || "").trim();
      const agentUuid = String(data.agent_uuid || "").trim();
      const agentId = sanitizeText(String(data.agent_id || "").trim()) || "Unknown Agent";
      const provider = normalizePredictionProvider(data.provider);
      const symbol = (type === "poly_bet" || type === "poly_sell" || type === "poly_resolved")
        ? predictionProviderTag(provider)
        : (normalizeSymbolQuery(data.symbol) || "MARKET");
      const side = type === "poly_bet"
        ? "BET"
        : type === "poly_sell"
        ? "SELL"
        : type === "poly_resolved"
        ? "RESOLVE"
        : normalizeTransactionSide(data.side, data.effective_action);
      const marketId = String(data.market_id || "").trim();
      const outcome = String(data.outcome || "").trim().toUpperCase();
      const key = idText
        ? `recent:${idText}`
        : `recent:${type}:${createdAt}:${agentUuid}:${symbol}:${marketId}:${outcome}:${side}:${index}`;

      return {
        key,
        type,
        created_at: createdAt,
        agent_uuid: agentUuid,
        agent_id: agentId,
        avatar: String(data.avatar || "").trim(),
        provider,
        provider_event_type: String(data.provider_event_type || "").trim().toLowerCase(),
        ticker: String(data.ticker || "").trim().toUpperCase(),
        symbol,
        side,
        market_id: marketId,
        market_label: sanitizeText(String(data.market_label || "").trim()),
        outcome,
        amount: Number(data.amount),
        shares: Number(data.shares),
        winning_outcome: String(data.winning_outcome || "").trim().toUpperCase(),
        payout: Number(data.payout),
        cost_basis: Number(data.cost_basis),
        realized_gross: Number(data.realized_gross),
        qty: Number(data.qty),
        fill_price: Number(data.fill_price),
        notional: Number(data.notional),
      };
    });
  }

  function dedupeRows(rows) {
    if (!Array.isArray(rows)) return [];
    const out = [];
    const seen = new Set();
    for (const row of rows) {
      const key = String(row && row.key ? row.key : "").trim();
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push(row);
    }
    return out;
  }

  function setStatus(kind, text) {
    if (!(discoverStatusEl instanceof HTMLElement)) return;
    const isError = kind === "error";
    discoverStatusEl.classList.toggle("error", isError);
    discoverStatusEl.textContent = isError ? String(text || "").trim() : "";
  }

  function setMetaNote(_text) {
    if (!(discoverMetaNoteEl instanceof HTMLElement)) return;
    discoverMetaNoteEl.textContent = "";
  }

  function setSortNote(_windowName) {
    if (!(discoverSortNoteEl instanceof HTMLElement)) return;
    discoverSortNoteEl.textContent = "";
  }

  function renderLoading() {
    if (!(discoverSectionsEl instanceof HTMLElement)) return;
    discoverSectionsEl.innerHTML = '<div class="discover-empty">Loading agents...</div>';
  }

  function lockSectionsHeight() {
    if (!(discoverSectionsEl instanceof HTMLElement)) {
      return () => {};
    }
    const height = discoverSectionsEl.offsetHeight;
    if (!Number.isFinite(height) || height <= 0) {
      return () => {};
    }
    discoverSectionsEl.style.minHeight = `${Math.floor(height)}px`;
    let released = false;
    return () => {
      if (released) return;
      released = true;
      window.requestAnimationFrame(() => {
        if (!(discoverSectionsEl instanceof HTMLElement)) return;
        discoverSectionsEl.style.minHeight = "";
      });
    };
  }

  function renderEmpty(text) {
    if (!(discoverSectionsEl instanceof HTMLElement)) return;
    discoverSectionsEl.innerHTML = `<div class="discover-empty">${escapeHtml(text)}</div>`;
  }

  function sortByReturn(rows) {
    return [...rows].sort((a, b) => {
      const diff = Number(b.return_pct || 0) - Number(a.return_pct || 0);
      if (diff !== 0) return diff;
      return String(a.agent_id || "").localeCompare(String(b.agent_id || ""));
    });
  }

  function sortByTrending(rows) {
    return [...rows].sort((a, b) => {
      const activityDiff = Number(b.activity_events || 0) - Number(a.activity_events || 0);
      if (activityDiff !== 0) return activityDiff;
      const returnDiff = Number(b.return_pct || 0) - Number(a.return_pct || 0);
      if (returnDiff !== 0) return returnDiff;
      return String(a.agent_id || "").localeCompare(String(b.agent_id || ""));
    });
  }

  function sortByNew(rows) {
    return [...rows].sort((a, b) => {
      const dateA = parseIsoDate(a.registered_at);
      const dateB = parseIsoDate(b.registered_at);
      const tsA = dateA ? dateA.getTime() : 0;
      const tsB = dateB ? dateB.getTime() : 0;
      if (tsA !== tsB) return tsB - tsA;
      return Number(b.return_pct || 0) - Number(a.return_pct || 0);
    });
  }

  function rowsForNewSection(rows) {
    return rows.filter((row) => Number.isFinite(row.live_days) && row.live_days > 0 && row.live_days <= 30);
  }

  function takeUniqueRows(rows, usedSet, maxCount = Number.POSITIVE_INFINITY) {
    const out = [];
    for (const row of rows) {
      const key = String(row.key || "").trim();
      if (!key || usedSet.has(key)) continue;
      usedSet.add(key);
      out.push(row);
      if (out.length >= maxCount) break;
    }
    return out;
  }

  function buildSections() {
    const activeRows = dedupeRows(state.activeRows);
    const uniqueCount = activeRows.length;

    if (uniqueCount === 0) {
      return [];
    }

    if (uniqueCount < COLD_START_THRESHOLD) {
      return [
        {
          id: "all",
          title: "All Agents",
          note: `${WINDOW_LABEL[state.activeWindow] || "30 Days"} snapshot`,
          rows: sortByReturn(activeRows),
        },
      ];
    }

    const used = new Set();
    const sectionCap = 12;
    const topPool = sortByReturn(activeRows);
    const trendingPool = sortByTrending(dedupeRows(state.trendingRows));
    const newPool = sortByNew(rowsForNewSection(activeRows));

    // Reserve headroom for Trending/New first, then backfill Top with remaining rows.
    const topSeed = takeUniqueRows(topPool, used, sectionCap);
    const trendingRows = takeUniqueRows(trendingPool, used, sectionCap);
    const newRows = takeUniqueRows(newPool, used, sectionCap);
    const topTail = takeUniqueRows(topPool, used);
    const topRows = [...topSeed, ...topTail];

    const sections = [];
    if (topRows.length) {
      sections.push({
        id: "top",
        title: `Top Performing (${WINDOW_LABEL[state.activeWindow] || "30 Days"})`,
        note: "Highest return in selected timeframe",
        rows: topRows,
      });
    }
    if (trendingRows.length) {
      sections.push({
        id: "trending",
        title: "Trending (This Week)",
        note: "Most active strategies by executed events",
        rows: trendingRows,
      });
    }
    if (newRows.length) {
      sections.push({
        id: "newer",
        title: "New Agents",
        note: "Recently launched agents with live signals",
        rows: newRows,
      });
    }

    if (!sections.length) {
      sections.push({
        id: "all",
        title: "All Agents",
        note: `${WINDOW_LABEL[state.activeWindow] || "30 Days"} snapshot`,
        rows: sortByReturn(activeRows),
      });
    }

    return sections;
  }

  function resetVisibleCounts() {
    state.sectionVisibleCount = {
      top: SECTION_DEFAULT_VISIBLE,
      trending: SECTION_DEFAULT_VISIBLE,
      newer: SECTION_DEFAULT_VISIBLE,
      all: SECTION_DEFAULT_VISIBLE,
    };
  }

  function cardMarkup(row, indexInSection) {
    const key = String(row.key || row.agent_uuid || row.agent_id || "").trim();
    const detailTarget = String(row.agent_id || row.agent_uuid || key || "unknown").trim() || "unknown";
    const detailHref = `/agent/${encodeURIComponent(detailTarget)}`;
    const displayName = displayNameForRow(row);
    const returnPct = Number(row.return_pct || 0);
    const returnClass = returnPct >= 0 ? "up" : "down";
    const rank = parseRank(row.rank) || normalizePositiveInt(indexInSection + 1, 1);
    const category = categoryLabelFromRow(row);
    const symbols = normalizeSymbols(row.symbols || []);
    const primarySymbol = symbols[0] || "Multi-Asset";
    const balanceText = formatMoney(row.balance_usd) || "--";
    const realizedGainValue = toFiniteNumber(row.realized_gain_usd);
    const realizedGainText = formatSignedGainMoney(realizedGainValue) || "--";
    const realizedGainClass = realizedGainValue != null
      ? (realizedGainValue > 0 ? "is-up" : (realizedGainValue < 0 ? "is-down" : "is-flat"))
      : "";
    const isCodeLoading = !!state.codeLoadingByAgent[key];
    const codeButtonLabel = isCodeLoading ? "Loading..." : "View Algorithm";
    const toneClass = toneClassForKey(key || detailTarget || String(indexInSection));

    return `
      <article class="discover-card ${toneClass}" style="--stagger:${indexInSection};" data-card-key="${escapeHtml(key)}">
        <a class="discover-agent-link" href="${escapeHtml(detailHref)}" data-agent-link="observe">
          <div class="discover-agent-head">
            <span class="discover-avatar">${avatarMarkup(row.avatar, displayName)}</span>
            <div class="discover-agent-top">
              <h3 class="discover-agent-name">${escapeHtml(displayName)}</h3>
              <p class="discover-agent-sub">${escapeHtml(primarySymbol)} • ${escapeHtml(category)}</p>
            </div>
            <span class="discover-rank-pill" aria-label="Rank ${rank}">#${escapeHtml(rank)}</span>
          </div>
        </a>

        <div class="discover-metrics">
          <div class="discover-metric metric-primary">
            <span class="discover-metric-k">Return</span>
            <span class="discover-metric-v discover-return ${returnClass}">${escapeHtml(formatPct(returnPct))}</span>
          </div>
          <div class="discover-metric">
            <span class="discover-metric-k">Balance</span>
            <span class="discover-metric-v">${escapeHtml(balanceText)}</span>
            <span class="discover-metric-sub ${escapeHtml(realizedGainClass)}">Realized gain ${escapeHtml(realizedGainText)}</span>
          </div>
        </div>

        <div class="discover-agent-cta-row">
          <a class="discover-view-btn" href="${escapeHtml(detailHref)}" data-agent-link="observe">View Agent</a>
          <button class="discover-code-btn" type="button" data-trading-code-agent="${escapeHtml(key)}" ${isCodeLoading ? "disabled" : ""}>${escapeHtml(codeButtonLabel)}</button>
        </div>
      </article>
    `;
  }

  function sectionMarkup(section) {
    const rows = Array.isArray(section.rows) ? section.rows : [];
    const visible = normalizePositiveInt(state.sectionVisibleCount[section.id] || SECTION_DEFAULT_VISIBLE, SECTION_DEFAULT_VISIBLE);
    const shown = rows.slice(0, visible);
    const canMore = shown.length < rows.length;

    return `
      <section class="discover-section" data-section-id="${escapeHtml(section.id)}">
        <div class="discover-section-head">
          <h2 class="discover-section-title">${escapeHtml(section.title)}</h2>
        </div>
        <div class="discover-grid ct-card-zone">
          ${shown.map((row, index) => cardMarkup(row, index)).join("")}
        </div>
        <div class="discover-section-foot">
          ${canMore ? `<button class="discover-section-more" type="button" data-section-more="${escapeHtml(section.id)}">View more</button>` : ""}
        </div>
      </section>
    `;
  }

  function renderSections() {
    const sections = buildSections();
    if (!sections.length) {
      renderEmpty(state.searchTicker ? `No agents found for ticker ${state.searchTicker}.` : "No agents available for this window.");
      return;
    }
    if (!(discoverSectionsEl instanceof HTMLElement)) return;
    discoverSectionsEl.innerHTML = sections.map((section) => sectionMarkup(section)).join("");
  }

  function recentTransactionMarkup(row) {
    const type = String(row.type || "stock_order").trim().toLowerCase();
    const displayName = sanitizeText(row.agent_id || "") || "Unknown Agent";
    const provider = normalizePredictionProvider(row.provider);
    const providerTag = predictionProviderTag(provider);
    const venueLabel = predictionVenueLabel(provider);
    const side = String(row.side || "").trim().toUpperCase();
    const isBuy = side === "BUY";
    const isSell = side === "SELL";
    const isPolyBet = type === "poly_bet";
    const isPolySell = type === "poly_sell";
    const isPolyResolved = type === "poly_resolved";
    const sideLabel = isBuy ? "BUY" : isSell ? "SELL" : isPolyBet ? "BET" : isPolySell ? "SELL" : isPolyResolved ? "RESOLVE" : "TRADE";
    const sideClass = isBuy ? "buy" : isSell ? "sell" : "trade";
    let symbol = normalizeSymbolQuery(row.symbol) || "MARKET";
    const details = [];
    if (isPolyBet) {
      symbol = providerTag;
      const marketLabel = sanitizeText(row.market_label || row.market_id || venueLabel);
      const outcome = String(row.outcome || "").trim().toUpperCase();
      const amountText = formatMoney(row.amount);
      const sharesText = formatQuantity(row.shares);
      if (marketLabel) details.push(marketLabel);
      if (outcome) details.push(outcome);
      if (amountText) details.push(amountText);
      if (sharesText) details.push(`Shares ${sharesText}`);
    } else if (isPolySell) {
      symbol = providerTag;
      const marketLabel = sanitizeText(row.market_label || row.market_id || venueLabel);
      const outcome = String(row.outcome || "").trim().toUpperCase();
      const amountText = formatMoney(row.amount || row.notional);
      const sharesText = formatQuantity(row.shares || row.qty);
      const pnlValue = Number(row.realized_gross);
      const pnlText = Number.isFinite(pnlValue)
        ? `PnL ${pnlValue >= 0 ? "+" : "-"}$${Math.abs(pnlValue).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
        : "";
      if (marketLabel) details.push(marketLabel);
      if (outcome) details.push(outcome);
      if (amountText) details.push(`Proceeds ${amountText}`);
      if (sharesText) details.push(`Shares ${sharesText}`);
      if (pnlText) details.push(pnlText);
    } else if (isPolyResolved) {
      symbol = providerTag;
      const marketLabel = sanitizeText(row.market_label || row.market_id || venueLabel);
      const winning = String(row.winning_outcome || row.outcome || "").trim().toUpperCase();
      const payoutText = formatMoney(row.payout || row.notional);
      const pnlValue = Number(row.realized_gross);
      const pnlText = Number.isFinite(pnlValue)
        ? `PnL ${pnlValue >= 0 ? "+" : "-"}$${Math.abs(pnlValue).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
        : "";
      if (marketLabel) details.push(marketLabel);
      if (winning) details.push(`WIN ${winning}`);
      if (payoutText) details.push(`Payout ${payoutText}`);
      if (pnlText) details.push(pnlText);
    } else {
      const qtyText = formatQuantity(row.qty);
      const fillPrice = Number(row.fill_price);
      const fillText = Number.isFinite(fillPrice) && fillPrice > 0
        ? `$${fillPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
        : "";
      const notionalText = formatMoney(row.notional);
      if (qtyText) details.push(`Qty ${qtyText}`);
      if (fillText) details.push(`Px ${fillText}`);
      if (notionalText) details.push(notionalText);
    }

    const createdAt = String(row.created_at || "").trim();
    const timeText = formatRelativeTime(createdAt) || createdAt || "--";
    const agentTarget = String(row.agent_uuid || row.agent_id || "").trim() || "unknown";
    const agentHref = `/agent/${encodeURIComponent(agentTarget)}`;

    return `
      <article class="discover-recent-item" data-recent-key="${escapeHtml(row.key)}">
        <a class="discover-recent-agent" href="${escapeHtml(agentHref)}" data-agent-link="observe">
          <span class="discover-avatar discover-avatar-sm">${avatarMarkup(row.avatar, displayName)}</span>
          <span class="discover-recent-agent-name">${escapeHtml(displayName)}</span>
        </a>
        <div class="discover-recent-trade">
          <span class="discover-recent-side ${escapeHtml(sideClass)}">${escapeHtml(sideLabel)}</span>
          <span class="discover-recent-symbol">${escapeHtml(symbol)}</span>
          <span class="discover-recent-meta">${escapeHtml(details.join(" · ") || "Market order")}</span>
        </div>
        <time class="discover-recent-time" datetime="${escapeHtml(createdAt)}">${escapeHtml(timeText)}</time>
      </article>
    `;
  }

  function renderRecentTransactions() {
    if (!(recentTransactionsListEl instanceof HTMLElement)) return;
    if (state.recentTransactionsLoading) {
      recentTransactionsListEl.innerHTML = '<div class="discover-empty">Loading recent transactions...</div>';
      return;
    }
    if (state.recentTransactionsError) {
      recentTransactionsListEl.innerHTML = `<div class="discover-empty">${escapeHtml(state.recentTransactionsError)}</div>`;
      return;
    }
    if (!Array.isArray(state.recentTransactions) || state.recentTransactions.length === 0) {
      recentTransactionsListEl.innerHTML = '<div class="discover-empty">No recent transactions yet.</div>';
      return;
    }
    const rows = state.recentTransactions;
    const collapsedCount = collapsedRecentTransactionCount(rows);
    const hasHiddenRows = rows.length > collapsedCount;
    const shownRows = state.recentTransactionsExpanded ? rows : rows.slice(0, collapsedCount);

    recentTransactionsListEl.innerHTML = `
      <div class="discover-recent-items">
        ${shownRows.map((row) => recentTransactionMarkup(row)).join("")}
      </div>
      ${!state.recentTransactionsExpanded && hasHiddenRows ? '<div class="discover-recent-foot"><button class="discover-section-more" type="button" data-recent-more="1">More</button></div>' : ""}
    `;
  }

  function updateWindowButtons() {
    windowButtons.forEach((button) => {
      if (!(button instanceof HTMLButtonElement)) return;
      const windowName = normalizeWindow(button.getAttribute("data-window") || "30d");
      const active = windowName === state.activeWindow;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
  }

  function setAccountButtonLabel(text) {
    if (!(accountLinkEl instanceof HTMLAnchorElement)) return;
    accountLinkEl.textContent = String(text || "").trim() || "Owner";
  }

  async function fetchJsonWithFallback(urls, errorPrefix) {
    let fallbackErr = null;
    for (const url of urls) {
      const targetUrl = String(url || "").trim();
      if (!targetUrl) continue;
      let response;
      try {
        response = await fetch(targetUrl, { headers: { Accept: "application/json" } });
      } catch (err) {
        fallbackErr = err;
        continue;
      }
      if (response.ok) {
        return response.json();
      }
      if (response.status === 404) {
        fallbackErr = new Error(`${errorPrefix}_${response.status}`);
        continue;
      }
      throw new Error(`${errorPrefix}_${response.status}`);
    }
    if (fallbackErr instanceof Error) {
      throw fallbackErr;
    }
    throw new Error(`${errorPrefix}_no_endpoint`);
  }

  function syncTopbar() {
    if (!(accountLinkEl instanceof HTMLAnchorElement) || !(newAgentLinkEl instanceof HTMLAnchorElement)) return;

    if (state.isLoggedIn) {
      if (topActionsEl instanceof HTMLElement) topActionsEl.classList.remove("guest");
      setAccountButtonLabel(state.ownerEmail || "Owner");
      accountLinkEl.href = "/discover";
      accountLinkEl.title = state.ownerEmail || "Owner";
      newAgentLinkEl.classList.remove("is-hidden");
      newAgentLinkEl.href = "/skill.md";
      if (discoverNavLinkEl instanceof HTMLAnchorElement) discoverNavLinkEl.classList.remove("is-hidden");
      return;
    }

    if (topActionsEl instanceof HTMLElement) topActionsEl.classList.add("guest");
    setAccountButtonLabel("Sign up");
    accountLinkEl.href = "/skill.md";
    accountLinkEl.title = "Sign up";
    newAgentLinkEl.classList.add("is-hidden");
    newAgentLinkEl.href = "/skill.md";
    if (discoverNavLinkEl instanceof HTMLAnchorElement) discoverNavLinkEl.classList.add("is-hidden");
  }

  async function detectOwnerSession() {
    // Public runtime has no owner session surface; always stay in guest mode.
    state.isLoggedIn = false;
    state.ownerEmail = "";
  }

  async function fetchOwnerRows(windowName, ticker) {
    const query = new URLSearchParams();
    query.set("window", windowName);
    query.set("limit", "200");
    query.set("page", "1");
    query.set("tz_offset_minutes", String(-new Date().getTimezoneOffset()));
    if (ticker) {
      query.set("q", ticker);
      query.set("symbol", ticker);
    }

    const queryString = query.toString();
    const urls = DISCOVERY_ROWS_ENDPOINTS.map((basePath) => `${basePath}?${queryString}`);
    const payload = await fetchJsonWithFallback(urls, "public_discover_failed");
    const rows = mapDiscoveryRows(payload && payload.items, windowName);
    return {
      source: "public",
      rows,
    };
  }

  async function fetchPublicRows(windowName, ticker) {
    const query = new URLSearchParams();
    query.set("window", windowName);
    query.set("featured_limit", "3");
    query.set("limit", "200");
    query.set("page", "1");
    if (ticker) query.set("symbol", ticker);
    const queryString = query.toString();
    const urls = DISCOVERY_ROWS_ENDPOINTS.map((basePath) => `${basePath}?${queryString}`);
    const payload = await fetchJsonWithFallback(urls, "public_discover_failed");
    const baseRows = Array.isArray(payload && payload.items)
      ? payload.items
      : Array.isArray(payload && payload.leaders)
      ? payload.leaders
      : [];
    const rows = mapDiscoveryRows(baseRows, windowName);
    return {
      source: "public",
      rows,
    };
  }

  async function fetchRowsForWindow(windowName, ticker) {
    if (state.isLoggedIn) {
      try {
        return await fetchOwnerRows(windowName, ticker);
      } catch (_ownerErr) {
        return fetchPublicRows(windowName, ticker);
      }
    }
    return fetchPublicRows(windowName, ticker);
  }

  async function fetchRecentTransactions(limit = RECENT_TRANSACTION_FETCH_LIMIT) {
    const safeLimit = Math.max(1, Math.min(Number(limit) || RECENT_TRANSACTION_FETCH_LIMIT, 200));
    const query = new URLSearchParams();
    query.set("limit", String(safeLimit));
    const queryString = query.toString();
    const urls = RECENT_TRANSACTIONS_ENDPOINTS.map((basePath) => `${basePath}?${queryString}`);
    const payload = await fetchJsonWithFallback(urls, "recent_orders_failed");
    const rows = Array.isArray(payload && payload.items)
      ? payload.items
      : Array.isArray(payload && payload.orders)
      ? payload.orders
      : [];
    return mapRecentTransactionRows(rows);
  }

  async function loadRecentTransactions() {
    state.recentTransactionsLoading = true;
    state.recentTransactionsError = "";
    state.recentTransactionsExpanded = false;
    renderRecentTransactions();
    try {
      const rows = await fetchRecentTransactions(RECENT_TRANSACTION_FETCH_LIMIT);
      state.recentTransactions = rows;
      state.recentTransactionsError = "";
    } catch (_err) {
      state.recentTransactions = [];
      state.recentTransactionsError = "Failed to load recent transactions.";
    } finally {
      state.recentTransactionsLoading = false;
      renderRecentTransactions();
    }
  }

  async function loadRows(nextWindow, { resetVisible = true } = {}) {
    const windowName = normalizeWindow(nextWindow);
    state.activeWindow = windowName;
    updateWindowButtons();
    setSortNote(windowName);
    const releaseHeightLock = lockSectionsHeight();

    if (resetVisible) {
      resetVisibleCounts();
    }

    const ticker = normalizeSymbolQuery(state.searchTicker);
    state.searchTicker = ticker;
    if (searchInputEl instanceof HTMLInputElement && searchInputEl.value !== ticker) {
      searchInputEl.value = ticker;
    }

    const requestId = state.requestSeq + 1;
    state.requestSeq = requestId;

    setMetaNote("");
    setStatus("hint", "");
    const hasExistingCards = discoverSectionsEl instanceof HTMLElement && discoverSectionsEl.children.length > 0;
    if (!hasExistingCards) {
      renderLoading();
    }

    try {
      const [mainResult, trendingResult] = await Promise.all([
        fetchRowsForWindow(windowName, ticker),
        windowName === "7d"
          ? Promise.resolve(null)
          : fetchRowsForWindow("7d", ticker).catch(() => null),
      ]);

      if (requestId !== state.requestSeq) {
        releaseHeightLock();
        return;
      }

      state.dataSource = String(mainResult && mainResult.source ? mainResult.source : "public");
      state.activeRows = dedupeRows(mainResult && mainResult.rows ? mainResult.rows : []);
      state.trendingRows = dedupeRows(
        windowName === "7d"
          ? state.activeRows
          : trendingResult && trendingResult.rows
          ? trendingResult.rows
          : state.activeRows
      );
      state.rowsByWindow[windowName] = state.activeRows;

      window.requestAnimationFrame(() => {
        if (requestId !== state.requestSeq) {
          releaseHeightLock();
          return;
        }
        renderSections();
        releaseHeightLock();
      });

      setStatus("hint", "");
      setMetaNote("");
    } catch (_err) {
      if (requestId !== state.requestSeq) {
        releaseHeightLock();
        return;
      }
      state.activeRows = [];
      state.trendingRows = [];
      window.requestAnimationFrame(() => {
        renderEmpty("Failed to load discover data.");
        releaseHeightLock();
      });
      setStatus("error", "Failed to load discover data.");
      setMetaNote("");
    }
  }

  function findRowByKey(cardKey) {
    const key = String(cardKey || "").trim();
    if (!key) return null;

    const pools = [
      state.activeRows,
      state.trendingRows,
      ...Object.values(state.rowsByWindow || {}),
    ];
    for (const list of pools) {
      if (!Array.isArray(list)) continue;
      const found = list.find((row) => String(row && row.key ? row.key : "").trim() === key);
      if (found) return found;
    }
    return null;
  }

  function resetCopyButton() {
    if (!(codeCopyEl instanceof HTMLButtonElement)) return;
    if (state.copyResetTimer) {
      window.clearTimeout(state.copyResetTimer);
      state.copyResetTimer = 0;
    }
    const canCopy = String(state.activeAlgorithmAgent || "").trim().length > 0;
    codeCopyEl.textContent = "Copy Code";
    codeCopyEl.disabled = !canCopy;
  }

  function normalizeCodeText(value) {
    return String(value || "").replace(/\r\n/g, "\n");
  }

  function commentPrefixesForLanguage(language) {
    const key = String(language || "").trim().toLowerCase();
    if (!key) return ["#", "//", "--"];
    if (["python", "py", "bash", "shell", "sh", "yaml", "yml", "r", "ruby", "perl", "make"].includes(key)) {
      return ["#"];
    }
    if (["javascript", "js", "typescript", "ts", "java", "c", "cpp", "c++", "csharp", "cs", "go", "rust", "kotlin", "swift", "php"].includes(key)) {
      return ["//"];
    }
    if (["sql", "haskell", "lua"].includes(key)) {
      return ["--"];
    }
    return ["#", "//", "--"];
  }

  function stripCommentLine(trimmed, prefixes) {
    for (const prefix of prefixes) {
      if (!prefix || !trimmed.startsWith(prefix)) continue;
      return trimmed.slice(prefix.length).replace(/^\s?/, "");
    }
    return null;
  }

  function splitAlgorithmBlocks(code, language) {
    const text = normalizeCodeText(code).trim();
    if (!text) {
      return { brief: "", implementation: "" };
    }
    const lines = text.split("\n");
    const prefixes = commentPrefixesForLanguage(language);
    const briefLines = [];
    let idx = 0;
    while (idx < lines.length && !String(lines[idx] || "").trim()) idx += 1;
    let sawComment = false;
    for (; idx < lines.length; idx += 1) {
      const trimmed = String(lines[idx] || "").trim();
      if (!trimmed) {
        if (sawComment) briefLines.push("");
        continue;
      }
      const stripped = stripCommentLine(trimmed, prefixes);
      if (stripped == null) break;
      sawComment = true;
      briefLines.push(stripped);
    }
    const brief = sawComment ? briefLines.join("\n").replace(/\n{3,}/g, "\n\n").trim() : "";
    const implementation = lines.slice(idx).join("\n").trim();
    if (!brief) {
      return { brief: "", implementation: text };
    }
    if (!implementation) {
      return { brief, implementation: text };
    }
    return { brief, implementation };
  }

  function previewAlgorithmCode(fullCode, maxLines = 30, maxChars = 3200) {
    const text = normalizeCodeText(fullCode).trim();
    if (!text) {
      return {
        preview: "",
        truncated: false,
        totalLines: 0,
        shownLines: 0,
      };
    }

    let clipped = text;
    let truncated = false;
    if (clipped.length > maxChars) {
      clipped = clipped.slice(0, maxChars);
      truncated = true;
    }

    let lines = clipped.split("\n");
    if (lines.length > maxLines) {
      lines = lines.slice(0, maxLines);
      truncated = true;
    }

    const totalLines = text.split("\n").length;
    const shownLines = lines.length;
    let preview = lines.join("\n").trimEnd();
    if (truncated) {
      preview = `${preview}\n\n... (preview truncated)`;
    }

    return {
      preview,
      truncated,
      totalLines,
      shownLines,
    };
  }

  function splitToBullets(text, maxItems = 3) {
    const raw = String(text || "").trim();
    if (!raw) return [];

    const lines = raw
      .split(/\n+/)
      .map((line) => line.replace(/^[-*\d.)\s]+/, "").trim())
      .filter((line) => isMeaningfulText(line) && !looksLikeCodeToken(line) && !looksLikeCodeLine(line));

    const sentencePool = lines.length > 1
      ? lines
      : raw
          .split(/[.;!?]\s+/)
          .map((item) => item.trim())
          .filter((item) => isMeaningfulText(item) && !looksLikeCodeToken(item) && !looksLikeCodeLine(item));

    const candidates = [];
    for (const part of sentencePool) {
      const cleaned = normalizeNarrativeLine(part, 160);
      if (!cleaned) continue;
      candidates.push(cleaned);
      if (candidates.length >= maxItems * 2) break;
    }
    return dedupeNarrativeLines(candidates, { maxItems });
  }

  function deriveRules({ briefLines }) {
    const ruleCandidates = [];
    const pushRule = (line) => {
      const clean = normalizeNarrativeLine(line, 140);
      if (!clean) return;
      if (!isMeaningfulText(clean) || looksLikeCodeToken(clean) || looksLikeCodeLine(clean)) return;
      const key = clean.toLowerCase();
      if (ruleCandidates.some((item) => item.toLowerCase() === key)) return;
      ruleCandidates.push(clean);
    };

    for (const line of briefLines) {
      if (/\b(buy|sell|entry|exit|stop|target|risk|rebalance|trigger)\b/i.test(line)) {
        pushRule(line);
      }
      if (ruleCandidates.length >= 3) break;
    }

    return ruleCandidates.slice(0, 3);
  }

  function setListItems(listEl, items, fallbackText) {
    if (!(listEl instanceof HTMLElement)) return 0;
    const values = Array.isArray(items) ? items.filter(Boolean).slice(0, 3) : [];
    listEl.innerHTML = "";

    const fallback = String(fallbackText || "").trim();
    const source = values.length ? values : (fallback ? [fallback] : []);
    for (const line of source) {
      const li = document.createElement("li");
      li.textContent = String(line || "").trim();
      listEl.appendChild(li);
    }
    return source.length;
  }

  function cleanOverviewValue(value) {
    const text = String(value || "").trim();
    if (!text || text === "-" || /^n\/a$/i.test(text)) return "";
    return text;
  }

  function setDrawerOverview(overview) {
    const asset = cleanOverviewValue(overview.asset);
    const logic = cleanOverviewValue(overview.logic);
    const execution = cleanOverviewValue(overview.execution);

    if (overviewAssetEl instanceof HTMLElement) {
      overviewAssetEl.textContent = asset || "-";
    }
    if (overviewAssetItemEl instanceof HTMLElement) {
      overviewAssetItemEl.hidden = !asset;
    }

    if (overviewLogicEl instanceof HTMLElement) {
      overviewLogicEl.textContent = logic || "-";
    }
    if (overviewLogicItemEl instanceof HTMLElement) {
      overviewLogicItemEl.hidden = !logic;
    }

    if (overviewExecutionEl instanceof HTMLElement) {
      overviewExecutionEl.textContent = execution || "-";
    }
    if (overviewExecutionItemEl instanceof HTMLElement) {
      overviewExecutionItemEl.hidden = !execution;
    }
    if (overviewSectionEl instanceof HTMLElement) {
      overviewSectionEl.hidden = !(asset || logic || execution);
    }
  }

  function renderAlgorithmDrawer() {
    if (codeTitleEl instanceof HTMLElement) {
      codeTitleEl.textContent = state.activeAlgorithmOverview.title || "Trading Algorithm";
    }
    if (codeMetaEl instanceof HTMLElement) {
      const metaText = String(state.activeAlgorithmOverview.meta || "").trim();
      codeMetaEl.textContent = metaText;
      codeMetaEl.hidden = !metaText;
    }

    setDrawerOverview(state.activeAlgorithmOverview);

    const strategyCount = setListItems(
      codeBriefListEl,
      state.activeAlgorithmSections.plain,
      ""
    );
    if (codeStrategySectionEl instanceof HTMLElement) {
      codeStrategySectionEl.hidden = strategyCount <= 0;
    }

    const ruleCount = setListItems(
      codeRulesListEl,
      state.activeAlgorithmSections.rules,
      ""
    );
    if (codeRulesSectionEl instanceof HTMLElement) {
      codeRulesSectionEl.hidden = ruleCount <= 0;
    }

    if (codeContentEl instanceof HTMLElement) {
      codeContentEl.textContent = String(state.activeAlgorithmSections.code || "").trim() || "# Preview unavailable.";
    }

    if (codeNoteEl instanceof HTMLElement) {
      const noteText = String(state.activeAlgorithmSections.note || "").trim();
      codeNoteEl.textContent = noteText;
      codeNoteEl.hidden = !noteText;
    }

    resetCopyButton();
  }

  function openAlgorithmDrawer() {
    if (!(codeLayerEl instanceof HTMLElement)) return;
    codeLayerEl.hidden = false;
    codeLayerEl.classList.add("open");
    codeLayerEl.setAttribute("aria-hidden", "false");
    state.isAlgorithmDrawerOpen = true;
    if (codeCloseEl instanceof HTMLButtonElement) {
      window.requestAnimationFrame(() => {
        codeCloseEl.focus();
      });
    }
  }

  function closeAlgorithmDrawer() {
    if (!(codeLayerEl instanceof HTMLElement)) return;
    const wasOpen = !codeLayerEl.hidden;
    codeLayerEl.classList.remove("open");
    codeLayerEl.setAttribute("aria-hidden", "true");
    codeLayerEl.hidden = true;
    state.isAlgorithmDrawerOpen = false;
    if (wasOpen && state.lastDrawerTrigger instanceof HTMLElement && state.lastDrawerTrigger.isConnected) {
      state.lastDrawerTrigger.focus();
    }
  }

  function formatCodeUpdatedTime(isoText) {
    const date = parseIsoDate(isoText);
    if (!date) return "";
    return date.toLocaleString();
  }

  async function fetchTradingCodeByTarget(targetAgent, { includeCode = false } = {}) {
    const target = String(targetAgent || "").trim();
    if (!target) {
      throw new Error("invalid_agent_target");
    }
    const query = new URLSearchParams();
    query.set("include_code", includeCode ? "1" : "0");
    const queryString = query.toString();
    for (const buildPath of TRADING_CODE_ENDPOINT_BUILDERS) {
      const path = String(buildPath(target, queryString) || "").trim();
      if (!path) continue;
      let response;
      try {
        response = await fetch(path, { headers: { Accept: "application/json" } });
      } catch (_err) {
        continue;
      }
      if (response.status === 404) {
        continue;
      }
      if (!response.ok) {
        throw new Error(`trading_code_fetch_failed_${response.status}`);
      }
      return response.json();
    }
    throw new Error("trading_code_not_shared");
  }

  async function fetchPublicSummaryByTarget(targetAgent) {
    const target = String(targetAgent || "").trim();
    if (!target) return "";

    for (const buildPath of AGENT_SUMMARY_ENDPOINT_BUILDERS) {
      const path = String(buildPath(target) || "").trim();
      if (!path) continue;

      let response;
      try {
        response = await fetch(path, { headers: { Accept: "application/json" } });
      } catch (_err) {
        continue;
      }
      if (!response.ok) {
        continue;
      }

      let payload;
      try {
        payload = await response.json();
      } catch (_err) {
        continue;
      }

      const profile = payload && typeof payload.profile === "object" ? payload.profile : {};
      const summaryCandidates = [
        profile.strategy_summary,
        profile.auto_summary,
        profile.description,
      ];
      for (const line of summaryCandidates) {
        const clean = normalizeNarrativeLine(line, 160);
        if (!clean || isLowValueNarrative(clean) || looksLikeCodeLine(clean)) continue;
        return clean;
      }
    }

    return "";
  }

  function buildStrategyOverview(row, viewModel) {
    const symbols = normalizeSymbols(row.symbols || []);
    const asset = symbols.length ? symbols.slice(0, 2).join(" • ") : "Multi-Asset";
    const rawLogic = normalizeNarrativeLine(viewModel.summary || summaryFromRow(row), 120);
    const logic = rawLogic || "-";
    const execution = normalizeNarrativeLine(viewModel.executionFrequency || row.execution_frequency || "", 96)
      || "-";

    return {
      title: `Trading Algorithm · ${viewModel.agentLabel || displayNameForRow(row)}`,
      meta: viewModel.meta,
      asset,
      logic,
      execution,
    };
  }

  function buildTradingCodeViewModel(payload, row) {
    const data = payload && typeof payload === "object" ? payload : {};
    const agent = data.agent && typeof data.agent === "object" ? data.agent : {};
    const tradingCode = data.trading_code && typeof data.trading_code === "object" ? data.trading_code : {};
    const agentLabel = String(agent.agent_id || displayNameForRow(row)).trim() || "Agent";
    const language = String(tradingCode.language || "python").trim() || "python";
    const updatedText = formatCodeUpdatedTime(tradingCode.updated_at);
    const meta = updatedText ? `Updated: ${updatedText}` : "";

    const fullCode = String(tradingCode.code || "");
    const blocks = splitAlgorithmBlocks(fullCode, language);

    let brief = String(tradingCode.brief || "").trim();
    if (!brief && blocks.brief) {
      brief = blocks.brief;
    }

    let preview = String(tradingCode.preview || "").trim();
    let previewTruncated = !!tradingCode.preview_truncated;
    let shownLines = Number(tradingCode.preview_shown_lines || 0);
    let totalLines = Number(tradingCode.preview_total_lines || 0);

    if (!preview && fullCode.trim()) {
      const previewPayload = previewAlgorithmCode(blocks.implementation || fullCode);
      preview = String(previewPayload.preview || "").trim();
      previewTruncated = !!previewPayload.truncated;
      shownLines = Number(previewPayload.shownLines || 0);
      totalLines = Number(previewPayload.totalLines || 0);
    }

    const rawPlainLines = splitToBullets(brief || row.strategy_text || "", 6);
    const summarySeed = rawPlainLines[0] || summaryFromRow(row);
    const summaryLine = normalizeNarrativeLine(summarySeed, 120);
    const usedNarrativeKeys = new Set();
    const summaryKey = narrativeDedupKey(summaryLine);
    if (summaryKey) {
      usedNarrativeKeys.add(summaryKey);
    }

    const basePlainLines = dedupeNarrativeLines(rawPlainLines, { maxItems: 3 });
    let plainLines = basePlainLines;
    if (summaryKey && plainLines.length > 1) {
      plainLines = plainLines.filter((line) => narrativeDedupKey(line) !== summaryKey);
    }
    if (!plainLines.length && basePlainLines.length) {
      plainLines = [basePlainLines[0]];
    }
    if (!plainLines.length) {
      const fallbackPlain = normalizeNarrativeLine(brief || row.strategy_text || "", 160);
      const fallbackKey = narrativeDedupKey(fallbackPlain);
      if (fallbackPlain && fallbackKey) {
        plainLines.push(fallbackPlain);
      }
    }
    if (!plainLines.length && summaryLine) {
      plainLines.push(summaryLine);
    }
    for (const line of plainLines) {
      const key = narrativeDedupKey(line);
      if (key) usedNarrativeKeys.add(key);
    }

    const rules = dedupeNarrativeLines(
      deriveRules({ briefLines: rawPlainLines }),
      {
        maxItems: 3,
        blockedKeys: usedNarrativeKeys,
      }
    );
    const executionFrequency = normalizeNarrativeLine(
      String(tradingCode.execution_frequency || row.execution_frequency || "").trim(),
      96
    ) || "-";

    const note = previewTruncated
      ? `Preview ${Math.max(0, Math.floor(shownLines || 0))}/${Math.max(0, Math.floor(totalLines || 0))} lines.`
      : "Preview is read-only.";

    return {
      agentLabel,
      meta,
      summary: summaryLine,
      plainLines,
      rules,
      preview,
      fullCode,
      note,
      targetAgent: String(agent.agent_uuid || row.agent_uuid || row.agent_id || "").trim(),
      executionFrequency,
    };
  }

  function buildPublicSummaryViewModel(row, externalSummary = "") {
    const sourceText = String(row && row.strategy_text ? row.strategy_text : "").trim();
    const summaryLine = normalizeNarrativeLine(externalSummary || summaryFromRow(row), 120);
    const basePlainLines = splitToBullets(sourceText || summaryLine, 6);

    const usedNarrativeKeys = new Set();
    const plainLines = [];
    const summaryKey = narrativeDedupKey(summaryLine);
    if (summaryLine && summaryKey) {
      plainLines.push(summaryLine);
      usedNarrativeKeys.add(summaryKey);
    }
    for (const line of dedupeNarrativeLines(basePlainLines, { maxItems: 3 })) {
      const key = narrativeDedupKey(line);
      if (!key || usedNarrativeKeys.has(key)) continue;
      plainLines.push(line);
      usedNarrativeKeys.add(key);
      if (plainLines.length >= 3) break;
    }
    const publicLines = plainLines.length ? plainLines : ["Public strategy summary unavailable."];
    const rules = dedupeNarrativeLines(
      deriveRules({ briefLines: basePlainLines }),
      {
        maxItems: 3,
        blockedKeys: usedNarrativeKeys,
      }
    );

    return {
      summary: summaryLine || publicLines[0] || "",
      plainLines: publicLines,
      rules,
      executionFrequency: normalizeNarrativeLine(String(row && row.execution_frequency ? row.execution_frequency : "").trim(), 96) || "-",
    };
  }

  function setAlgorithmLoadingState(row) {
    state.activeAlgorithmAgent = String(row.agent_uuid || row.agent_id || row.key || "").trim();
    state.activeAlgorithmCode = "";
    state.activeAlgorithmOverview = {
      title: `Trading Algorithm · ${displayNameForRow(row)}`,
      meta: "Loading...",
      asset: normalizeSymbols(row.symbols || []).slice(0, 2).join(" • ") || "Multi-Asset",
      logic: "-",
      execution: "-",
    };
    state.activeAlgorithmSections = {
      plain: ["Loading strategy..."],
      rules: [],
      code: "# Loading preview...",
      note: "",
    };
    renderAlgorithmDrawer();
  }

  async function openAlgorithmDrawerByKey(cardKey, triggerEl = null) {
    const row = findRowByKey(cardKey);
    if (!row) return;

    const key = String(row.key || row.agent_uuid || row.agent_id || "").trim();
    if (!key) return;

    state.lastDrawerTrigger = triggerEl instanceof HTMLElement ? triggerEl : null;
    openAlgorithmDrawer();
    setAlgorithmLoadingState(row);

    state.codeLoadingByAgent[key] = true;
    renderSections();

    const targetAgent = String(row.agent_uuid || row.agent_id || key).trim();

    try {
      let viewModel = state.algorithmPreviewCacheByAgent[targetAgent];
      if (!viewModel) {
        const payload = await fetchTradingCodeByTarget(targetAgent, { includeCode: false });
        viewModel = buildTradingCodeViewModel(payload, row);
        state.algorithmPreviewCacheByAgent[targetAgent] = viewModel;
      }

      const cachedFullCode = String(state.algorithmCodeCacheByAgent[targetAgent] || "");
      state.activeAlgorithmAgent = String(viewModel.targetAgent || targetAgent).trim();
      state.activeAlgorithmCode = cachedFullCode;
      state.activeAlgorithmOverview = buildStrategyOverview(row, viewModel);
      state.activeAlgorithmSections = {
        plain: viewModel.plainLines,
        rules: viewModel.rules,
        code: viewModel.preview,
        note: viewModel.note,
      };
      renderAlgorithmDrawer();
    } catch (err) {
      const reason = String(err && err.message ? err.message : "");
      const notShared = reason === "trading_code_not_shared";
      let externalSummary = "";
      if (notShared) {
        externalSummary = await fetchPublicSummaryByTarget(targetAgent);
      }
      const fallback = buildPublicSummaryViewModel(row, externalSummary);
      state.activeAlgorithmOverview = {
        title: `Trading Algorithm · ${displayNameForRow(row)}`,
        meta: notShared ? "Code not shared publicly. Showing public summary." : "Unable to load details.",
        asset: normalizeSymbols(row.symbols || []).slice(0, 2).join(" • ") || "Multi-Asset",
        logic: notShared ? (fallback.summary || "-") : "-",
        execution: fallback.executionFrequency,
      };
      state.activeAlgorithmSections = {
        plain: notShared ? fallback.plainLines : ["Unable to load strategy."],
        rules: notShared ? fallback.rules : [],
        code: notShared ? "# Code is private for this agent." : "# Unable to load preview.",
        note: notShared ? "Public summary only." : "",
      };
      state.activeAlgorithmAgent = notShared ? "" : String(row.agent_uuid || row.agent_id || key).trim();
      state.activeAlgorithmCode = "";
      renderAlgorithmDrawer();
    } finally {
      delete state.codeLoadingByAgent[key];
      renderSections();
    }
  }

  async function ensureFullAlgorithmCode(targetAgent) {
    const target = String(targetAgent || "").trim();
    if (!target) {
      throw new Error("invalid_agent_target");
    }

    const cached = String(state.algorithmCodeCacheByAgent[target] || "");
    if (cached.trim()) {
      return cached;
    }

    const payload = await fetchTradingCodeByTarget(target, { includeCode: true });
    const data = payload && typeof payload === "object" ? payload : {};
    const tradingCode = data.trading_code && typeof data.trading_code === "object" ? data.trading_code : {};
    const code = String(tradingCode.code || "");
    if (!code.trim()) {
      throw new Error("trading_code_missing");
    }

    state.algorithmCodeCacheByAgent[target] = code;
    return code;
  }

  async function copyActiveAlgorithmCode() {
    if (!(codeCopyEl instanceof HTMLButtonElement)) return;
    const target = String(state.activeAlgorithmAgent || "").trim();
    if (!target) return;

    let fullCode = String(state.activeAlgorithmCode || "");
    codeCopyEl.disabled = true;

    try {
      if (!fullCode.trim()) {
        fullCode = await ensureFullAlgorithmCode(target);
        state.activeAlgorithmCode = fullCode;
      }
      await navigator.clipboard.writeText(fullCode);
      codeCopyEl.textContent = "Copied";
    } catch (_err) {
      codeCopyEl.textContent = "Copy Failed";
    }

    if (state.copyResetTimer) {
      window.clearTimeout(state.copyResetTimer);
      state.copyResetTimer = 0;
    }
    state.copyResetTimer = window.setTimeout(() => {
      state.copyResetTimer = 0;
      resetCopyButton();
    }, 1200);
  }

  function applySearchFromInput(forceReload = false) {
    if (!(searchInputEl instanceof HTMLInputElement)) return;
    const ticker = normalizeSymbolQuery(searchInputEl.value);
    searchInputEl.value = ticker;
    if (!forceReload && ticker === state.searchTicker) return;
    state.searchTicker = ticker;
    void loadRows(state.activeWindow, { resetVisible: true });
  }

  function bindSearch() {
    if (searchFormEl instanceof HTMLFormElement) {
      searchFormEl.addEventListener("submit", (event) => {
        event.preventDefault();
        applySearchFromInput(false);
      });
    }

    if (searchSubmitEl instanceof HTMLButtonElement) {
      searchSubmitEl.addEventListener("click", () => {
        applySearchFromInput(false);
      });
    }

    if (searchInputEl instanceof HTMLInputElement) {
      searchInputEl.addEventListener("input", () => {
        const normalized = normalizeSymbolQuery(searchInputEl.value);
        if (searchInputEl.value !== normalized) {
          searchInputEl.value = normalized;
        }
      });

      searchInputEl.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        event.preventDefault();
        if (!state.searchTicker) return;
        state.searchTicker = "";
        searchInputEl.value = "";
        void loadRows(state.activeWindow, { resetVisible: true });
      });
    }
  }

  function bindDrawer() {
    if (codeCloseEl instanceof HTMLButtonElement) {
      codeCloseEl.addEventListener("click", () => {
        closeAlgorithmDrawer();
      });
    }

    if (codeBgEl instanceof HTMLElement) {
      codeBgEl.addEventListener("click", () => {
        closeAlgorithmDrawer();
      });
    }

    if (codeCopyEl instanceof HTMLButtonElement) {
      codeCopyEl.addEventListener("click", () => {
        void copyActiveAlgorithmCode();
      });
    }
  }

  function bindWindowSwitch() {
    windowButtons.forEach((button) => {
      if (!(button instanceof HTMLButtonElement)) return;
      button.addEventListener("click", () => {
        const nextWindow = normalizeWindow(button.getAttribute("data-window") || "30d");
        if (nextWindow === state.activeWindow) return;
        void loadRows(nextWindow, { resetVisible: true });
      });
    });
  }

  function bindSectionEvents() {
    if (!(discoverSectionsEl instanceof HTMLElement)) return;

    discoverSectionsEl.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;

      const observeTrigger = target.closest('a[data-agent-link="observe"]');
      if (observeTrigger instanceof HTMLAnchorElement) {
        event.stopPropagation();
      }

      const moreBtn = target.closest("button[data-section-more]");
      if (moreBtn instanceof HTMLButtonElement) {
        const sectionId = String(moreBtn.getAttribute("data-section-more") || "").trim();
        if (!sectionId) return;
        const current = normalizePositiveInt(state.sectionVisibleCount[sectionId] || SECTION_DEFAULT_VISIBLE, SECTION_DEFAULT_VISIBLE);
        state.sectionVisibleCount[sectionId] = current + SECTION_DEFAULT_VISIBLE;
        renderSections();
        return;
      }

      const algoTrigger = target.closest("[data-trading-code-agent]");
      if (algoTrigger instanceof HTMLElement) {
        event.preventDefault();
        event.stopPropagation();
        const key = String(algoTrigger.getAttribute("data-trading-code-agent") || "").trim();
        if (!key) return;
        void openAlgorithmDrawerByKey(key, algoTrigger);
      }
    });
  }

  function bindGlobalEscAndOutside() {
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (state.isAlgorithmDrawerOpen) {
        closeAlgorithmDrawer();
      }
    });

    document.addEventListener("pointerdown", (event) => {
      const target = event.target;
      if (!(target instanceof Node)) return;

      if (state.isAlgorithmDrawerOpen && codeCardEl instanceof HTMLElement && !codeCardEl.contains(target)) {
        if (codeBgEl instanceof HTMLElement && codeBgEl.contains(target)) {
          closeAlgorithmDrawer();
        }
      }
    });
  }

  function bindRecentTransactionsEvents() {
    if (!(recentTransactionsListEl instanceof HTMLElement)) return;
    recentTransactionsListEl.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const moreBtn = target.closest("button[data-recent-more]");
      if (!(moreBtn instanceof HTMLButtonElement)) return;
      event.preventDefault();
      state.recentTransactionsExpanded = true;
      renderRecentTransactions();
    });
  }

  function bindInteractions() {
    bindWindowSwitch();
    bindSearch();
    bindDrawer();
    bindSectionEvents();
    bindRecentTransactionsEvents();
    bindGlobalEscAndOutside();
  }

  async function init() {
    document.body.classList.add("ready");
    bindInteractions();

    await detectOwnerSession();
    syncTopbar();

    setSortNote(state.activeWindow);
    await Promise.all([
      loadRows(state.activeWindow, { resetVisible: true }),
      loadRecentTransactions(),
    ]);
  }

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      () => {
        void init();
      },
      { once: true }
    );
  } else {
    void init();
  }
})();
