(function () {
  "use strict";
  const LS_KEY = "desk_data_path";
  const LS_STAT = "desk_stat_mode";
  const POLL_MS = 60 * 1000;
  const TZ = "Europe/Berlin";

  /* ------------------------------------------------------------ routing */
  function parseHash() {
    const raw = (location.hash || "").replace(/^#/, "");
    const out = { data: null, route: "home", mint: null };
    const parts = raw.split("&").filter(Boolean);
    // support #d=PATH, #d=PATH&/coin/MINT, #/account, #/auditor/MINT
    for (const p of parts) {
      if (p.startsWith("d=")) out.data = decodeURIComponent(p.slice(2));
      else if (p.startsWith("/")) Object.assign(out, routeOf(p));
      else if (p.startsWith("d/")) out.data = decodeURIComponent(p.slice(2));
    }
    if (!out.data && raw.startsWith("d=")) {
      const rest = raw.slice(2);
      const cut = rest.search(/[&/]/);
      out.data = decodeURIComponent(cut === -1 ? rest : rest.slice(0, cut));
      const after = cut === -1 ? "" : rest.slice(cut).replace(/^&/, "");
      if (after.startsWith("/")) Object.assign(out, routeOf(after));
    } else if (raw.startsWith("/")) {
      Object.assign(out, routeOf(raw.split("&")[0]));
    }
    return out;
  }
  function routeOf(path) {
    const s = path.replace(/^\//, "").split("/").filter(Boolean);
    if (!s.length) return { route: "home" };
    if (s[0] === "agents") return { route: "agents" };
    if (s[0] === "stats") return { route: "stats" };
    if (s[0] === "account") return { route: "account" };
    if (s[0] === "auditor") return { route: "auditor", mint: s[1] || null };
    if (s[0] === "coin" && s[1]) return { route: "coin", mint: s[1] };
    return { route: "home" };
  }
  function go(path) {
    const d = localStorage.getItem(LS_KEY);
    const prefix = d ? `#d=${encodeURIComponent(d)}&` : "#";
    location.hash = prefix + path;
  }

  let state = null;
  let error = null;
  let statMode = localStorage.getItem(LS_STAT) || "ALL";
  let tapeAll = false;

  function dataPath() {
    const fromHash = parseHash().data || new URLSearchParams(location.search).get("d");
    if (fromHash) {
      localStorage.setItem(LS_KEY, fromHash);
      return fromHash;
    }
    return localStorage.getItem(LS_KEY);
  }

  function showPathPrompt() {
    const root = document.getElementById("app") || document.body;
    root.innerHTML = `<div class="gate">
      <div class="logo">FOMO<b>DESK</b></div>
      <h1>Zugang einrichten</h1>
      <p>Füge den Zugangscode aus dem Grok-Bot-Chat ein. Das ist nur einmal nötig.</p>
      <input id="dpIn" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Zugangscode">
      <button id="dpBtn">SPEICHERN</button>
    </div>`;
    document.getElementById("dpBtn").onclick = () => {
      let v = (document.getElementById("dpIn").value || "").trim();
      const m = v.match(/[#&?]d=([^&]+)/); if (m) v = decodeURIComponent(m[1]);
      if (v.length < 20) return;
      localStorage.setItem(LS_KEY, v);
      location.reload();
    };
  }

  async function load() {
    const q = new URLSearchParams(location.search);
    if (q.get("fixture") === "empty") { state = emptyState(); error = null; render(); return; }
    if (q.get("fixture") === "error") { state = null; error = "state.json konnte nicht geladen werden."; render(); return; }
    const dp = dataPath();
    if (!dp) { state = null; error = null; showPathPrompt(); return; }
    const url = `d/${encodeURIComponent(dp)}/state.json?ts=${Date.now()}`;
    try {
      const r = await fetch(url, { cache: "no-store" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      state = await r.json();
      error = null;
    } catch (e) {
      error = "state.json konnte nicht geladen werden.";
    }
    render();
  }

  function emptyState() {
    return {
      mode: "PAPER", balance: 50, stack: 50, fomo_handle: "olli81", ts: new Date().toISOString(),
      balances: { PAPER: 50, LIVE: null },
      signup_url: "https://fomo.family/r/olli81",
      profile_url: "https://fomo.family/profile/olli81?source=share_link&r=olli81",
      notifier: "telegram",
      notifier_note: "Web-Push ist in Plan B nicht verfügbar. Meldungen kommen über Telegram.",
      settings: { stop_pct: 6, trail_pct: 12, analyst_mode: "rules", mode: "PAPER" },
      positions: [], activity: [], waiting: [], coins: {}, heartbeats: {},
      stats: null,
      agents: {
        scanner: { name: "Scanner", card: "0 Pools", sub: "0 ok · 0 raus", feed: [] },
        auditor: { name: "Auditor", card: "0 geprüft", sub: "bereit", latest: null },
        analyst: { name: "Analyst", card: "Bewertet", sub: "Regeln · 0 bewertet", min_score: 70, last: null },
        brain: { name: "Brain", card: "Bereit", sub: "$5–$10", decisions: [] },
        executor: { name: "Executor", card: "0 Trades", sub: "Größe vom Brain" },
        risk: { name: "Risk", card: "Bereit", sub: "Noch keine Exits", pills: { stop: "Stop −6%", trail: "Trail 12%" } }
      }
    };
  }

  /* ------------------------------------------------------------ format */
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  const nf2 = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  function num(x) { const n = Number(x); return x == null || x === "" || !Number.isFinite(n) ? null : n; }
  function money(x) { const n = num(x); return n == null ? "—" : (n < 0 ? "−" : "") + nf2.format(Math.abs(n)) + " $"; }
  function smoney(x) { const n = num(x); return n == null ? "—" : (n > 0 ? "+" : n < 0 ? "−" : "±") + nf2.format(Math.abs(n)) + " $"; }
  function spct(x, d) { const n = num(x); return n == null ? "—" : (n > 0 ? "+" : n < 0 ? "−" : "±") + Math.abs(n).toLocaleString("de-DE", { minimumFractionDigits: d == null ? 1 : d, maximumFractionDigits: d == null ? 1 : d }) + "%"; }
  function price(x) {
    const n = num(x); if (n == null) return "—";
    if (n === 0) return "0";
    const a = Math.abs(n);
    const dig = a >= 1 ? 4 : Math.min(10, Math.max(2, 3 - Math.floor(Math.log10(a))));
    return n.toLocaleString("de-DE", { minimumFractionDigits: dig, maximumFractionDigits: dig });
  }
  function cls(x) { const n = num(x); return n == null || n === 0 ? "" : (n > 0 ? "pos-c" : "neg-c"); }
  function toDate(s) { if (!s) return null; const d = new Date(s); return isNaN(d) ? null : d; }
  function hhmm(s, sec) {
    const d = toDate(s); if (!d) return "—";
    return d.toLocaleTimeString("de-DE", { timeZone: TZ, hour: "2-digit", minute: "2-digit", second: sec ? "2-digit" : undefined });
  }
  function ddmm(s) {
    const d = toDate(s.length === 10 ? s + "T12:00:00Z" : s); if (!d) return "—";
    return d.toLocaleDateString("de-DE", { timeZone: TZ, day: "2-digit", month: "2-digit" });
  }
  function ageSec(s) { const d = toDate(s); return d ? Math.max(0, (Date.now() - d.getTime()) / 1000) : null; }
  function ageTxt(sec) {
    if (sec == null) return "—";
    if (sec < 60) return Math.round(sec) + "s";
    if (sec < 3600) return Math.floor(sec / 60) + "m";
    if (sec < 86400) return Math.floor(sec / 3600) + "h " + Math.floor((sec % 3600) / 60) + "m";
    return Math.floor(sec / 86400) + "d";
  }
  function dur(min) { const m = num(min); if (m == null) return "—"; return m < 60 ? Math.round(m) + " min" : (m / 60).toLocaleString("de-DE", { maximumFractionDigits: 1 }) + " h"; }
  function dotCls(sec, ok, warn) { return sec == null ? "" : sec < ok ? "ok" : sec < warn ? "warn" : "bad"; }
  function link(href, text, extra) {
    if (!href) return esc(text);
    return `<a href="${esc(href)}" target="_blank" rel="noopener"${extra || ""}>${esc(text)}</a>`;
  }
  function coinA(c, label) {
    const href = (c && (c.link || c.coin_url)) || (typeof c === "string" ? c : null);
    const text = label || (c && (c.name || c.symbol || c.mint)) || "Coin";
    return link(href, text);
  }

  const AGENTS = [
    ["scanner", "Scanner", "◎"], ["auditor", "Auditor", "⛨"], ["analyst", "Analyst", "◈"],
    ["brain", "Brain", "◆"], ["executor", "Executor", "⇄"], ["risk", "Risk", "⚑"],
  ];
  const SYS = [["telegram", "Telegram"], ["publisher", "Publisher"]];
  const EXIT_DE = { stop: "Stop", tp1: "TP1 (Teilgewinn)", tp2: "TP2 (Teilgewinn)", trail: "Trailing-Stop", timeout: "Timeout", manual: "Manuell", pulled: "Liquidität weg" };
  const EXIT_COL = { stop: "r", tp1: "g", tp2: "g", trail: "o", timeout: "a", manual: "b", pulled: "r" };
  const LAYER_DE = { 1: "Mint-Authority", 2: "Freeze-Authority", 3: "Dev-Wallet", 4: "Top-10-Holder", 5: "Liquidität gesperrt", 6: "Pool-Alter", 7: "Gebündelte Wallets", 8: "Delegationen" };

  function hbAge(agent) {
    const hb = (state && state.heartbeats) || {};
    const ts = toDate(state && state.ts);
    const a = toDate(hb[agent]);
    if (!a) return null;
    // age relative to the snapshot time + how old the snapshot is
    const rel = ts ? Math.max(0, (ts - a) / 1000) : 0;
    return rel + (ageSec(state.ts) || 0);
  }

  /* ------------------------------------------------------------ derived */
  function modeStats(m) {
    const st = state && state.stats && state.stats.modes;
    return st ? st[m] || null : null;
  }
  function openPnl(mode) {
    return (state.positions || []).filter((p) => !mode || (p.mode || "PAPER") === mode)
      .reduce((a, p) => a + (num(p.pnl_usd) || 0) - (num(p.realized_pnl_usd) || 0), 0);
  }
  function realizedOpen(mode) {
    return (state.positions || []).filter((p) => !mode || (p.mode || "PAPER") === mode)
      .reduce((a, p) => a + (num(p.realized_pnl_usd) || 0), 0);
  }
  function todayPnl(mode) {
    const s = modeStats(mode);
    return (s ? num(s.today_pnl) || 0 : 0) + openPnl(mode) + realizedOpen(mode);
  }

  /* ------------------------------------------------------------ shell */
  const ICONS = {
    home: '<svg viewBox="0 0 24 24"><path d="M3 17l5-6 4 4 8-9"/><path d="M3 21h18"/></svg>',
    stats: '<svg viewBox="0 0 24 24"><path d="M5 20V11M12 20V4M19 20v-6"/></svg>',
    agents: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>',
    account: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/></svg>',
  };

  function statusBar() {
    const mode = (state && state.mode) || "PAPER";
    const age = state ? ageSec(state.ts) : null;
    let tick = "";
    if (state) {
      const tp = todayPnl(mode);
      const open = (state.positions || []).length;
      const dots = AGENTS.map(([k, n]) => `<i class="dot ${dotCls(hbAge(k), 180, 900)}" title="${esc(n)}"></i>`).join("");
      tick = `<div class="tick">
        <div><div class="lbl">${mode === "LIVE" ? "Live-Stack" : "Paper-Stack"}</div><div class="v">${money(state.stack)}</div></div>
        <div><div class="lbl">Heute</div><div class="v ${cls(tp)}">${smoney(tp)}</div></div>
        <div><div class="lbl">Offen</div><div class="v">${open}</div></div>
        <div><div class="lbl">Agenten</div><div class="hb">${dots}</div></div>
      </div>`;
    }
    return `<header class="sbar">
      <div class="r1">
        <span class="logo">FOMO<b>DESK</b></span>
        <span class="mode ${esc(mode)}">${esc(mode)}</span>
        <span class="upd"><i class="dot ${dotCls(age, 150, 600)}" id="updDot"></i><span id="updTxt">${state ? hhmm(state.ts, true) + " · vor " + ageTxt(age) : "—"}</span></span>
      </div>${tick}
    </header>`;
  }

  function shell(inner, tab) {
    const t = (id, label) => `<button data-go="/${id}" class="${tab === id ? "on" : ""}">${ICONS[id]}${label}</button>`;
    return `${statusBar()}
      <div class="pad">${inner}</div>
      <div class="tabs"><nav>${t("home", "Desk")}${t("stats", "Statistik")}${t("agents", "Agenten")}${t("account", "Konto")}</nav></div>`;
  }

  /* ------------------------------------------------------------ home */
  function posCard(p) {
    const st = state.settings || {};
    const pct = num(p.pct), pnl = num(p.pnl_usd);
    const entry = num(p.entry_price);
    const stopLine = p.trail_active && num(p.peak_price) != null
      ? num(p.peak_price) * (1 - (num(st.trail_pct) || 12) / 100)
      : (entry != null && num(p.stop_pct) != null ? entry * (1 - num(p.stop_pct) / 100) : null);
    const held = ageSec(p.opened_at);
    const tp1 = num(p.tp1_pct) != null ? p.tp1_pct : st.tp1_pct;
    const tp2 = num(p.tp2_pct) != null ? p.tp2_pct : st.tp2_pct;
    const dir = pct == null ? "" : pct >= 0 ? "up" : "down";
    return `<div class="posc ${dir}">
      <div class="ph">
        <div><div class="nm">${coinA(p)}<span class="tag ${esc(p.mode || "PAPER")}">${esc(p.mode || "PAPER")}</span></div>
          <div class="lbl" style="margin-top:2px">${esc(p.symbol || "")} · seit ${ageTxt(held)}</div></div>
        <div class="pnl">${pct != null
          ? `<div class="a ${cls(pnl)}">${smoney(pnl)}</div><div class="b ${cls(pct)}">${spct(pct)}</div>`
          : `<div class="b mut">kein Kurs</div>`}</div>
      </div>
      <div class="grid4">
        <div><div class="lbl">Einstieg</div><div class="v">${price(p.entry_price)}</div></div>
        <div><div class="lbl">Jetzt</div><div class="v ${cls(pct)}">${price(p.last_price)}</div></div>
        <div><div class="lbl">Hoch</div><div class="v">${price(p.peak_price)}</div></div>
        <div><div class="lbl">${p.trail_active ? "Trail" : "Stop"}</div><div class="v" style="color:var(--orange)">${price(stopLine)}</div></div>
        <div><div class="lbl">Größe</div><div class="v">${money(p.size_usd)}</div></div>
        <div><div class="lbl">Start</div><div class="v">${money(p.original_size_usd)}</div></div>
        <div><div class="lbl">Realisiert</div><div class="v ${cls(p.realized_pnl_usd)}">${smoney(p.realized_pnl_usd)}</div></div>
        <div><div class="lbl">Stop</div><div class="v">−${esc(p.stop_pct)}%</div></div>
      </div>
      <div class="tpbar">
        <span class="stop">${p.trail_active ? "TRAIL AKTIV" : "STOP −" + esc(p.stop_pct) + "%"}</span>
        <span class="${p.tp1_hit ? "hit" : ""}">TP1 +${esc(tp1)}% ${p.tp1_hit ? "✓" : "○"}</span>
        <span class="${p.tp2_hit ? "hit" : ""}">TP2 +${esc(tp2)}% ${p.tp2_hit ? "✓" : "○"}</span>
      </div>
      <canvas class="mini" data-mint="${esc(p.mint)}"></canvas>
      <div class="acts">
        <a class="btn sell" href="${esc(p.link)}" target="_blank" rel="noopener">AUF FOMO VERKAUFEN ↗</a>
        <button class="btn ghost" data-go="/coin/${esc(p.mint)}">CHART</button>
      </div>
    </div>`;
  }

  const KIND = {
    bought: ["KAUF", "buy"], sold: ["VERKAUF", ""], stopped: ["STOP", "bad"], took_profit: ["TP", "good"],
    timeout: ["TIMEOUT", ""], pulled: ["GEZOGEN", "bad"], kill: ["RAUS", "kill"], passed: ["SCAN OK", "good"],
    audited: ["AUDIT", "good"], rejected: ["ABGEL.", "bad"], scored: ["SCORE", ""], sized: ["GRÖSSE", ""],
    skipped: ["SKIP", "kill"], signal: ["SIGNAL", "buy"],
  };
  function tapeRow(a) {
    const k = KIND[a.kind] || [String(a.kind || "").toUpperCase().slice(0, 8), ""];
    let tone = k[1];
    if (a.kind === "sold" || a.kind === "timeout") tone = a.tone === "bad" ? "bad" : "good";
    const name = String(a.title || "").replace(/^(Bought|Sold|Stopped|Took profit|Rejected|Skipped|Sized|Scored|Audited|Passed)\s+/, "");
    const right = String(a.right || "");
    const rc = /^\+/.test(right) ? "pos-c" : /^-/.test(right) ? "neg-c" : "mut";
    return `<div class="tr ${a.kind === "kill" ? "kill" : ""}">
      <div class="t">${hhmm(a.ts)}</div>
      <div class="k ${tone}">${esc(k[0])}</div>
      <div class="m"><div class="n">${a.link ? coinA({ link: a.link }, name) : esc(name)}</div>
        <div class="d">${esc(a.agent || "")}${a.detail ? " · " + esc(a.detail) : ""}</div></div>
      <div class="r ${rc}">${esc(right.replace(/ · [\d.]+% of stack/, ""))}</div>
    </div>`;
  }

  function viewHome() {
    if (!state) return "";
    const mode = state.mode || "PAPER";
    const pos = state.positions || [];
    const act = state.activity || [];
    const bal = state.balances || {};
    const ms = modeStats(mode) || {};
    const other = mode === "LIVE" ? "PAPER" : "LIVE";
    const unreal = openPnl(null);
    const kpis = `<div class="kpis">
      <div class="kpi"><div class="lbl">${mode === "LIVE" ? "Live-Stack" : "Paper-Stack"}</div><div class="v big">${money(state.stack)}</div>
        <div class="s">${ms.start_stack != null ? "Start " + money(ms.start_stack) : esc(state.fomo_handle || "olli81")}</div></div>
      <div class="kpi"><div class="lbl">${other === "LIVE" ? "Live-Stack" : "Paper-Stack"}</div><div class="v big mut">${money(bal[other])}</div>
        <div class="s">nur Info</div></div>
      <div class="kpi"><div class="lbl">Unrealisiert</div><div class="v big ${cls(unreal)}">${smoney(unreal)}</div>
        <div class="s">${pos.length} offen</div></div>
      <div class="kpi"><div class="lbl">PnL gesamt ${esc(mode)}</div><div class="v ${cls(ms.pnl)}">${smoney(ms.pnl || 0)}</div>
        <div class="s">nach Gebühren</div></div>
      <div class="kpi"><div class="lbl">Win-Rate</div><div class="v">${ms.win_rate != null ? esc(String(ms.win_rate).replace(".", ",")) + "%" : "—"}</div>
        <div class="s">${ms.trades || 0} Trades · ${ms.wins || 0}/${ms.losses || 0}</div></div>
      <div class="kpi"><div class="lbl">Risk</div><div class="v">−${esc((state.settings || {}).stop_pct)}%</div>
        <div class="s">TP +${esc((state.settings || {}).tp1_pct)}/+${esc((state.settings || {}).tp2_pct)}%</div></div>
    </div>`;
    const positions = pos.length ? pos.map(posCard).join("")
      : `<div class="empty">Keine offenen Positionen · Scanner sucht weiter</div>`;
    const shown = tapeAll ? act.slice(0, 120) : act.slice(0, 15);
    const feed = act.length ? `<div class="tape">${shown.map(tapeRow).join("")}
      ${act.length > 15 ? `<button class="more" id="tapeMore">${tapeAll ? "WENIGER ZEIGEN" : "ALLE " + Math.min(act.length, 120) + " ZEIGEN"}</button>` : ""}</div>`
      : `<div class="empty">Noch keine Aktivität.</div>`;
    return `
      <div class="sec"><h2>Übersicht</h2><span class="aside">${esc(state.fomo_handle || "olli81")}</span></div>
      ${kpis}
      ${state.ticket_warning ? `<div class="note warnbox">${esc(state.ticket_warning)}</div>` : ""}
      ${mode === "LIVE" ? `<div class="note warnbox">LIVE: Der Desk kauft nicht selbst. Signale kommen per Telegram, du tippst in FOMO auf Buy/Sell.</div>` : ""}
      <div class="sec"><h2>Positionen</h2><span class="aside">${pos.length} offen</span></div>
      ${positions}
      <div class="sec"><h2>Aktivität</h2><span class="aside">Zeiten in Berlin</span></div>
      ${feed}`;
  }

  /* ------------------------------------------------------------ stats */
  function viewStats() {
    const S = state && state.stats;
    if (!S || S.error) {
      return `<h1 class="screen">Statistik</h1><div class="empty">${S && S.error ? "Statistik konnte nicht berechnet werden." : "Noch keine Statistik verfügbar. Sie kommt mit dem nächsten Update."}</div>`;
    }
    const m = S.modes[statMode] ? statMode : "ALL";
    const s = S.modes[m];
    const seg = `<div class="seg">${["ALL", "LIVE", "PAPER"].map((k) =>
      `<button data-stat="${k}" class="${k === m ? "on" : ""}">${k === "ALL" ? "ALLE" : k} <span class="dimc">${S.modes[k] ? S.modes[k].trades : 0}</span></button>`).join("")}</div>`;
    const few = !s.enough ? `<div class="note">Zu wenige Trades für Aussagen: ${s.trades} von mindestens ${S.min_trades || 10} abgeschlossenen Trades. Die Zahlen sind noch nicht aussagekräftig.</div>` : "";
    const pf = s.profit_factor === "inf" ? "∞" : (s.profit_factor != null ? String(s.profit_factor).replace(".", ",") : "—");
    const k = (l, v, sub, c) => `<div class="kpi"><div class="lbl">${l}</div><div class="v ${c || ""}">${v}</div>${sub != null ? `<div class="s">${sub}</div>` : ""}</div>`;
    const bw = (t) => t ? `${coinA(t, t.name)}` : "—";
    const kpis = `<div class="kpis">
      ${k("PnL netto", smoney(s.pnl), "Gebühren " + money(s.fees), cls(s.pnl))}
      ${k("Trades", esc(s.trades), `${s.wins} ▲ · ${s.losses} ▼`)}
      ${k("Win-Rate", s.win_rate != null ? String(s.win_rate).replace(".", ",") + "%" : "—", "TP1 " + s.tp1_hits + "× · TP2 " + s.tp2_hits + "×")}
      ${k("Ø Gewinn", smoney(s.avg_win), null, "pos-c")}
      ${k("Ø Verlust", smoney(s.avg_loss), null, s.avg_loss != null ? "neg-c" : "")}
      ${k("Profit-Faktor", pf, "Gew. ÷ Verl.")}
      ${k("Erwartung", smoney(s.expectancy), "pro Trade", cls(s.expectancy))}
      ${k("Max. Drawdown", s.max_dd ? "−" + money(s.max_dd) : money(0), s.max_dd_pct ? "−" + String(s.max_dd_pct).replace(".", ",") + "% vom Hoch" : "vom Hoch", s.max_dd ? "neg-c" : "")}
      ${k("Ø Haltedauer", dur(s.avg_hold_min), null)}
    </div>
    <div class="kpis two" style="margin-top:8px">
      ${k("Bester Trade", s.best ? `<span class="pos-c">${smoney(s.best.pnl)}</span>` : "—", s.best ? bw(s.best) + " · " + spct(s.best.pct) : null)}
      ${k("Schlechtester Trade", s.worst ? `<span class="${cls(s.worst.pnl)}">${smoney(s.worst.pnl)}</span>` : "—", s.worst ? bw(s.worst) + " · " + spct(s.worst.pct) : null)}
    </div>`;

    const eqLegend = m === "ALL"
      ? `<div class="legend"><span><i style="background:#e6e9ef"></i>Gesamt</span><span><i style="background:var(--red)"></i>LIVE</span><span><i style="background:var(--blue)"></i>PAPER</span></div>`
      : `<div class="legend"><span><i style="background:${m === "LIVE" ? "var(--red)" : "var(--blue)"}"></i>${m} kumuliert nach Gebühren</span></div>`;
    const charts = `
      <div class="sec"><h2>Equity-Kurve</h2><span class="aside">kumulierter PnL</span></div>
      <div class="panel"><div class="chartbox"><canvas class="chart2" id="eqChart"></canvas></div>${eqLegend}</div>
      <div class="sec"><h2>PnL pro Tag</h2><span class="aside">${s.daily.length} Tage</span></div>
      <div class="panel"><div class="chartbox"><canvas class="chart2" id="dayChart" style="height:140px"></canvas></div></div>`;

    const maxE = Math.max(1, ...s.exits.map((e) => e.n));
    const exits = `<div class="sec"><h2>Exit-Gründe</h2><span class="aside">${s.trades} geschlossen</span></div>
      <div class="panel bars">${s.exits.map((e) => `<div class="bar">
        <div class="l">${esc(EXIT_DE[e.reason] || e.reason)}</div>
        <div class="track"><div class="fill ${EXIT_COL[e.reason] || ""}" style="width:${e.n ? (e.n / maxE * 100) : 0}%"></div></div>
        <div class="x">${e.n}× <small class="${cls(e.pnl)}">${e.n ? smoney(e.pnl).replace(" $", "$") : ""}</small></div>
      </div>`).join("")}</div>`;

    const F = S.funnel || [];
    const top = Math.max(1, ...F.map((f) => f.n));
    const funnel = `<div class="sec"><h2>Scanner-Trichter</h2><span class="aside">alle Modi</span></div>
      <div class="panel bars">${F.map((f, i) => {
        const prev = i ? F[i - 1].n : null;
        const conv = prev ? Math.round(f.n / prev * 100) + "%" : "";
        return `<div class="bar"><div class="l">${esc(f.label)}</div>
          <div class="track"><div class="fill a" style="width:${f.n / top * 100}%;opacity:${1 - i * 0.07}"></div></div>
          <div class="x">${f.n} <small>${conv}</small></div></div>`;
      }).join("")}</div>`;

    const R = S.rejections || [];
    const topR = Math.max(1, ...R.map((r) => r.n));
    const rej = `<div class="sec"><h2>Top-Ablehnungsgründe</h2><span class="aside">alle Agenten</span></div>
      ${R.length ? `<div class="panel bars">${R.map((r) => `<div class="bar"><div class="l" title="${esc(r.agent || "")}">${esc(r.label)}</div>
        <div class="track"><div class="fill r" style="width:${r.n / topR * 100}%"></div></div>
        <div class="x">${r.n}× <small>${esc({ Scanner: "SCN", Auditor: "AUD", Analyst: "ANA", Brain: "BRN" }[r.agent] || "")}</small></div></div>`).join("")}</div>`
        : `<div class="empty">Noch keine Ablehnungen.</div>`}`;

    const rec = (S.recent || []).filter((t) => m === "ALL" || t.mode === m);
    const trades = `<div class="sec"><h2>Letzte Trades</h2><span class="aside">${rec.length}</span></div>
      ${rec.length ? `<div class="panel" style="overflow-x:auto"><table class="tb">
        <tr><th>Zeit</th><th>Coin</th><th>Exit</th><th class="rt">PnL</th><th class="rt">%</th></tr>
        ${rec.map((t) => `<tr><td class="mono dimc">${ddmm(t.closed_at)} ${hhmm(t.closed_at)}</td>
          <td class="nm">${coinA(t, t.name)} <span class="tag ${esc(t.mode)}">${esc(t.mode[0])}</span></td>
          <td class="mut">${esc((EXIT_DE[t.reason] || t.reason).replace(" (Teilgewinn)", ""))}</td>
          <td class="rt ${cls(t.pnl)}">${smoney(t.pnl)}</td><td class="rt ${cls(t.pct)}">${spct(t.pct)}</td></tr>`).join("")}
      </table></div>` : `<div class="empty">Noch keine geschlossenen Trades in ${m === "ALL" ? "keinem Modus" : m}.</div>`}`;

    return `<h1 class="screen">Statistik</h1>${seg}${few}${kpis}${charts}${exits}${funnel}${rej}${trades}`;
  }

  /* ------------------------------------------------------------ agents */
  function viewAgents() {
    const A = (state && state.agents) || {};
    const cards = AGENTS.map(([k, label, icon]) => {
      const a = A[k] || { name: label };
      const age = hbAge(k);
      const pills = a.pills ? `<div class="pills">
        ${a.pills.stop ? `<span class="pill stop">${esc(a.pills.stop)}</span>` : ""}
        ${a.pills.trail ? `<span class="pill trail">${esc(a.pills.trail)}</span>` : ""}
        ${a.pills.tp ? `<span class="pill tp">${esc(a.pills.tp)}</span>` : ""}</div>` : "";
      let feed = "";
      if (k === "brain" && a.decisions && a.decisions.length) {
        feed = a.decisions.slice(0, 6).map((d) => `<div class="tr ${d.skipped ? "kill" : ""}">
          <div class="m"><div class="n">${coinA(d, d.name || d.symbol || d.mint)}</div>
          <div class="d">${d.skipped ? esc(d.reason || "übersprungen") : "Score " + esc(d.score) + (d.capHit ? " · Limit " + esc(d.capHit) : "")}</div></div>
          <div class="r">${d.skipped ? "SKIP" : money(d.sizeUsd)}</div></div>`).join("");
      } else if (k === "scanner" && a.feed && a.feed.length) {
        feed = a.feed.slice(0, 6).map((f) => `<div class="tr ${f.verdict === "kill" ? "kill" : ""}">
          <div class="m"><div class="n">${coinA(f, f.name || f.symbol)}</div>
          <div class="d">${hhmm(f.ts)} · ${f.verdict === "pass" ? "→ Auditor" : esc(f.reason || "")}</div></div>
          <div class="r ${f.verdict === "pass" ? "pos-c" : "dimc"}">${f.verdict === "pass" ? "OK" : "RAUS"}</div></div>`).join("");
      }
      let extra = "";
      if (k === "analyst" && a.last) {
        const sc = Math.max(0, Math.min(100, num(a.last.score) || 0));
        const min = num(a.min_score) || 70;
        extra = `<div class="scorebar"><span>${sc}</span><div class="track"><div class="fill" style="width:${sc}%;background:${sc >= min ? "var(--green)" : "var(--red)"}"></div>
          <div class="min" style="left:${min}%"></div></div><span class="dimc">min ${min}</span></div>
          <div class="sub" style="margin-top:4px">Letzter: ${coinA(a.last, (a.last.mint || "").slice(0, 6) + "…")}</div>`;
      }
      if (k === "auditor") extra = `<div class="pills"><button class="pill" data-go="/auditor">LETZTES AUDIT ›</button></div>`;
      return `<div class="ag">
        <div class="h"><span class="ic">${icon}</span><span class="n">${esc(label)}</span>${a.paused ? `<span class="tag">PAUSIERT</span>` : ""}
          <span class="age"><i class="dot ${dotCls(age, 180, 900)}"></i>${age == null ? "kein Signal" : "vor " + ageTxt(age)}</span></div>
        <div class="big">${esc(a.card || "")}</div>
        <div class="sub">${esc(a.sub || "")}</div>
        ${extra}${pills}${feed ? `<div class="rows">${feed}</div>` : ""}
      </div>`;
    }).join("");
    const sys = SYS.map(([k, n]) => { const g = hbAge(k); return `<div class="setrow"><div class="k">${n}</div><div class="v"><i class="dot ${dotCls(g, 180, 900)}"></i> ${g == null ? "—" : "vor " + ageTxt(g)}</div></div>`; }).join("");
    const waiting = (state && state.waiting) || [];
    return `<h1 class="screen">Agenten</h1><div class="agrid">${cards}</div>
      <div class="sec"><h2>Warteschlange</h2><span class="aside">${waiting.length} Pools</span></div>
      ${waiting.length ? `<div class="tape">${waiting.slice(0, 12).map((w) => `<div class="tr" style="grid-template-columns:40px 1fr"><div class="t">${hhmm(w.added_at)}</div><div class="m"><div class="n">${coinA(w, w.name || w.symbol || w.mint)}</div></div></div>`).join("")}</div>` : `<div class="empty">Keine Pools in der Warteschlange.</div>`}
      <div class="sec"><h2>System</h2></div><div class="panel">${sys}</div>`;
  }

  function layersGrid(layers) {
    return `<div class="layers">${layers.map((L) => {
      const c = L.pass === true ? "ok" : (L.pass === false ? "red" : "");
      const v = String(L.value == null ? "" : L.value).replace(/^Revoked$/, "entzogen").replace(/^not checked$/, "nicht geprüft");
      return `<div class="layer ${c}"><div class="n">${esc(L.n)}. ${esc(LAYER_DE[L.n] || L.name)}</div><div class="v">${esc(v)}</div></div>`;
    }).join("")}</div>`;
  }

  function viewAuditor(mint) {
    const latest = (state && (mint && state.coins && state.coins[mint] && state.coins[mint].audit)) || (state && state.latest_audit);
    const layers = (latest && latest.layers) || [];
    let body;
    if (!latest || !layers.length) {
      body = `<div class="empty">Noch kein Audit. Der Auditor prüft Coins, sobald der Scanner sie durchlässt.</div>`;
    } else {
      const ok = layers.filter((L) => L.pass === true).length;
      body = `<div class="panel infop">
        <div class="lbl">${hhmm(latest.ts)} · ${latest.holders != null ? esc(latest.holders) + " Holder" : ""}</div>
        <div class="big" style="font-family:var(--mono);font-size:17px;margin:4px 0">${latest.link ? coinA(latest, latest.name || latest.mint) : esc(latest.mint || "")}</div>
        <div class="${latest.passed ? "pos-c" : "neg-c"} mono">${latest.passed ? "8/8 BESTANDEN → Analyst" : ok + "/8 · ABGELEHNT: " + esc(latest.reason || "")}</div>
      </div><div style="margin-top:8px">${layersGrid(layers)}</div>`;
    }
    return `<button class="back" data-go="/agents">‹ Agenten</button><h1 class="screen">Auditor</h1>${body}`;
  }

  function viewCoin(mint) {
    const c = state && state.coins && state.coins[mint];
    if (!c) {
      return `<button class="back" data-go="/home">‹ Desk</button><h1 class="screen">Coin</h1><div class="empty">Diesen Coin kenne ich noch nicht.</div>`;
    }
    const pos = c.position;
    const prices = (c.prices || []).map((p) => num(p.price)).filter((x) => x != null);
    const last = prices.length ? prices[prices.length - 1] : null;
    const first = prices.length ? prices[0] : null;
    const chg = last != null && first ? (last / first - 1) * 100 : null;
    return `<button class="back" data-go="/home">‹ Desk</button>
      <div class="ph" style="margin:4px 2px 8px"><div><div class="nm" style="font-size:18px;font-weight:700">${esc(c.name || c.symbol || mint)}${pos ? `<span class="tag ${esc(pos.mode || "PAPER")}">${esc(pos.mode || "PAPER")}</span>` : ""}</div>
        <div class="lbl">${esc(c.symbol || "")} · ${esc(String(mint).slice(0, 4))}…${esc(String(mint).slice(-4))}</div></div>
        <div class="pnl"><div class="a">${price(last)}</div><div class="b ${cls(chg)}">${spct(chg)} im Fenster</div></div></div>
      <canvas class="big" id="chart"></canvas>
      <div class="legend" style="padding-top:6px"><span><i style="background:var(--green)"></i>Kurs</span><span><i style="background:var(--muted)"></i>Einstieg</span><span><i style="background:var(--orange)"></i>${pos && pos.trail_active ? "Trail" : "Stop"}</span><span><i style="background:var(--green)"></i>TP1/TP2</span></div>
      ${pos ? posCard(Object.assign({}, pos, { prices: c.prices, pct: pos.pct, last_price: pos.last_price })).replace(/<canvas[^>]*><\/canvas>/, "").replace(/<button class="btn ghost"[^>]*>CHART<\/button>/, "") : `<div class="acts"><a class="btn" href="${esc(c.link)}" target="_blank" rel="noopener">AUF FOMO ÖFFNEN ↗</a></div>`}
      <div class="sec"><h2>Auditor</h2></div>
      ${c.audit && c.audit.layers ? layersGrid(c.audit.layers) : `<div class="empty">Kein Audit.</div>`}`;
  }

  /* ------------------------------------------------------------ account */
  const SET_DE = {
    min_size_usd: "Min. Größe ($)", max_size_usd: "Max. Größe ($)", max_pool_pct: "Max. % vom Pool",
    stop_pct: "Stop (%)", trail_start_pct: "Trail ab (%)", trail_pct: "Trail-Abstand (%)", timeout_h: "Timeout (h)",
    timeout_min_gain_pct: "Timeout min. Gewinn (%)", tp1_pct: "TP1 bei (%)", tp1_fraction: "TP1 Anteil", tp2_pct: "TP2 bei (%)", tp2_fraction: "TP2 Anteil",
    min_ticket_usd: "Min. Ticket ($)", stack_pct: "% vom Stack", below_min: "Unter Minimum", recheck_liq_drop_pct: "Recheck Liq.-Abfall (%)", recheck_price_up_pct: "Recheck Preis-Anstieg (%)",
    min_liquidity_usd: "Min. Liquidität ($)", max_top10_pct: "Max. Top-10 (%)", max_h1_change_pct: "Max. 1h-Anstieg (%)", min_score: "Min. Score",
    analyst_mode: "Analyst-Modus", mode: "Modus", paper_balance: "Paper-Guthaben", paper_start_stack: "Paper-Startstack", fomo_handle: "FOMO-Handle",
  };
  function viewAccount() {
    const s = (state && state.settings) || {};
    const groups = [
      { id: "brain", title: "Brain · Größe", keys: ["min_size_usd", "max_size_usd", "max_pool_pct"] },
      { id: "risk", title: "Risk · Exits", keys: ["stop_pct", "trail_start_pct", "trail_pct", "timeout_h", "timeout_min_gain_pct", "tp1_pct", "tp1_fraction", "tp2_pct", "tp2_fraction"] },
      { id: "executor", title: "Executor", keys: ["min_ticket_usd", "stack_pct", "below_min", "recheck_liq_drop_pct", "recheck_price_up_pct"] },
    ];
    const used = new Set(groups.flatMap((g) => g.keys));
    const rest = Object.keys(s).filter((k) => !used.has(k)).sort();
    const val = (v) => (v != null && typeof v === "object") ? JSON.stringify(v) : (typeof v === "number" ? String(Math.round(v * 1000) / 1000).replace(".", ",") : v);
    const row = (k) => `<div class="setrow"><div class="k">${esc(SET_DE[k] || k)}${SET_DE[k] ? `<small>${esc(k)}</small>` : ""}</div><div class="v">${esc(val(s[k]))}</div></div>`;
    const blocks = groups.map((g) => {
      const rows = g.keys.filter((k) => k in s).map(row).join("");
      return rows ? `<div class="sec"><h2>${esc(g.title)}</h2></div><div class="panel settings-group" data-group="${esc(g.id)}">${rows}</div>` : "";
    }).join("");
    const more = rest.length ? `<div class="sec"><h2>Weitere</h2></div><div class="panel">${rest.map(row).join("")}</div>` : "";
    const bal = (state && state.balances) || {};
    return `<h1 class="screen">Konto</h1>
      <div class="kpis two">
        <div class="kpi"><div class="lbl">Live-Stack</div><div class="v big">${money(bal.LIVE)}</div><div class="s">dein FOMO-Konto</div></div>
        <div class="kpi"><div class="lbl">Paper-Stack</div><div class="v big">${money(bal.PAPER)}</div><div class="s">Simulation</div></div>
      </div>
      <div class="panel infop" style="margin-top:8px">
        <div class="lbl">Benachrichtigung</div>
        <div class="mono" style="font-size:15px;margin-top:2px">Telegram</div>
        <p>${esc((state && state.notifier_note) || "Web-Push ist in Plan B nicht verfügbar. Meldungen kommen über Telegram.")}</p>
        <p>${state && state.profile_url ? link(state.profile_url, "FOMO-Profil " + (state.fomo_handle || "olli81") + " ↗") : ""}
        ${state && state.signup_url ? " · " + link(state.signup_url, "Einladungslink ↗") : ""}</p>
        <p>Einstellungen sind hier nur lesbar. Ändern geht per Telegram, z. B. „set stop to -8%“.</p>
      </div>
      ${blocks}${more}`;
  }

  /* ------------------------------------------------------------ canvas */
  function setup(cnv) {
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(10, cnv.clientWidth), h = Math.max(10, cnv.clientHeight);
    cnv.width = Math.round(w * dpr); cnv.height = Math.round(h * dpr);
    const ctx = cnv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.font = "10px ui-monospace, Menlo, monospace";
    return { ctx, w, h };
  }
  function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim() || "#888"; }
  function noData(ctx, w, h, txt) {
    ctx.fillStyle = "#555e70"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(txt, w / 2, h / 2); ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
  }

  function drawPriceChart(cnv, pts, pos, settings) {
    const { ctx, w, h } = setup(cnv);
    const prices = (pts || []).map((p) => num(p.price)).filter((x) => x != null);
    if (prices.length < 2) { noData(ctx, w, h, "Noch keine Kursdaten"); return; }
    const st = settings || {};
    const entry = pos ? num(pos.entry_price) : null;
    const stopPct = pos ? num(pos.stop_pct) : null;
    const stop = pos && pos.trail_active && num(pos.peak_price) != null
      ? num(pos.peak_price) * (1 - (num(st.trail_pct) || 12) / 100)
      : (entry != null && stopPct != null ? entry * (1 - stopPct / 100) : null);
    const tp1 = entry != null ? entry * (1 + (num(pos.tp1_pct != null ? pos.tp1_pct : st.tp1_pct) || 50) / 100) : null;
    const tp2 = entry != null ? entry * (1 + (num(pos.tp2_pct != null ? pos.tp2_pct : st.tp2_pct) || 100) / 100) : null;
    let lo = Math.min(...prices), hi = Math.max(...prices);
    [stop, entry].forEach((v) => { if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
    // only stretch to TP lines when they're within reach (keeps the chart readable)
    [tp1, tp2].forEach((v) => { if (v != null && v < hi * 1.25) hi = Math.max(hi, v); });
    if (lo === hi) { lo *= 0.99; hi *= 1.01; }
    const padR = 54, padT = 6, padB = 6;
    const xs = (i) => 2 + (i / (prices.length - 1)) * (w - padR - 4);
    const ys = (p) => padT + (1 - (p - lo) / (hi - lo)) * (h - padT - padB);
    // grid
    ctx.strokeStyle = "#141922"; ctx.lineWidth = 1;
    for (let i = 1; i < 4; i++) { const y = Math.round(padT + i * (h - padT - padB) / 4) + 0.5; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w - padR, y); ctx.stroke(); }
    const up = entry != null ? prices[prices.length - 1] >= entry : prices[prices.length - 1] >= prices[0];
    const col = up ? css("--green") : css("--red");
    // area
    const g = ctx.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, up ? "rgba(25,210,122,.28)" : "rgba(255,77,94,.28)"); g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.beginPath(); prices.forEach((p, i) => i ? ctx.lineTo(xs(i), ys(p)) : ctx.moveTo(xs(i), ys(p)));
    ctx.lineTo(xs(prices.length - 1), h); ctx.lineTo(xs(0), h); ctx.closePath(); ctx.fillStyle = g; ctx.fill();
    ctx.beginPath(); prices.forEach((p, i) => i ? ctx.lineTo(xs(i), ys(p)) : ctx.moveTo(xs(i), ys(p)));
    ctx.strokeStyle = col; ctx.lineWidth = 1.6; ctx.stroke();
    const line = (v, c, label) => {
      if (v == null || v < lo || v > hi) return;
      const y = Math.round(ys(v)) + 0.5;
      ctx.strokeStyle = c; ctx.setLineDash([4, 3]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w - padR, y); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = c; ctx.fillText(label, w - padR + 4, Math.min(h - 2, Math.max(9, y + 3)));
    };
    line(entry, "#8a93a6", "EIN");
    line(stop, css("--orange"), pos && pos.trail_active ? "TRAIL" : "STOP");
    line(tp1, css("--green"), "TP1");
    line(tp2, css("--green"), "TP2");
    // last price tag
    const lp = prices[prices.length - 1], ly = ys(lp);
    ctx.fillStyle = col; ctx.fillRect(w - padR + 2, ly - 7, padR - 2, 14);
    ctx.fillStyle = "#000"; ctx.fillText(price(lp).slice(0, 9), w - padR + 4, ly + 3.5);
  }

  function drawEquity() {
    const cnv = document.getElementById("eqChart");
    if (!cnv) return;
    const { ctx, w, h } = setup(cnv);
    const S = state.stats.modes;
    const m = S[statMode] ? statMode : "ALL";
    const series = m === "ALL"
      ? [["ALL", "#e6e9ef", 2], ["LIVE", css("--red"), 1.2], ["PAPER", css("--blue"), 1.2]]
      : [[m, m === "LIVE" ? css("--red") : css("--blue"), 2]];
    const data = series.map(([k, c, lw]) => ({ c, lw, pts: (S[k].equity || []).map((p) => ({ t: toDate(p.ts).getTime(), v: num(p.v) })) }))
      .filter((s) => s.pts.length);
    if (!data.length) { noData(ctx, w, h, "Noch keine geschlossenen Trades"); return; }
    let t0 = Infinity, t1 = -Infinity, lo = 0, hi = 0;
    data.forEach((s) => s.pts.forEach((p) => { t0 = Math.min(t0, p.t); t1 = Math.max(t1, p.t); lo = Math.min(lo, p.v); hi = Math.max(hi, p.v); }));
    // start each curve at 0 slightly before the first trade
    const span = Math.max(t1 - t0, 3600 * 1000);
    t0 = t0 - span * 0.08; t1 = Math.max(t1, Date.now());
    if (hi === lo) { hi += 1; lo -= 1; }
    const pad = (hi - lo) * 0.12; hi += pad; lo -= pad;
    const L = 40, R = 6, T = 6, B = 16;
    const xs = (t) => L + (t - t0) / (t1 - t0) * (w - L - R);
    const ys = (v) => T + (1 - (v - lo) / (hi - lo)) * (h - T - B);
    ctx.strokeStyle = "#141922"; ctx.fillStyle = "#555e70"; ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const v = lo + (hi - lo) * i / 4, y = Math.round(ys(v)) + 0.5;
      ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(w - R, y); ctx.stroke();
      ctx.fillText(nf2.format(v), 2, y + 3);
    }
    ctx.strokeStyle = "#3a4252"; ctx.setLineDash([3, 3]);
    const y0 = Math.round(ys(0)) + 0.5; ctx.beginPath(); ctx.moveTo(L, y0); ctx.lineTo(w - R, y0); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = "#555e70";
    ctx.fillText(ddmm(new Date(t0).toISOString()) + " " + hhmm(new Date(t0).toISOString()), L, h - 3);
    const endLbl = "jetzt"; ctx.fillText(endLbl, w - R - ctx.measureText(endLbl).width, h - 3);
    data.forEach((s) => {
      ctx.beginPath(); ctx.moveTo(xs(t0), ys(0));
      let prev = 0;
      s.pts.forEach((p) => { ctx.lineTo(xs(p.t), ys(prev)); ctx.lineTo(xs(p.t), ys(p.v)); prev = p.v; });
      ctx.lineTo(xs(t1), ys(prev));
      ctx.strokeStyle = s.c; ctx.lineWidth = s.lw; ctx.stroke();
      s.pts.forEach((p) => { ctx.fillStyle = s.c; ctx.beginPath(); ctx.arc(xs(p.t), ys(p.v), 2.2, 0, Math.PI * 2); ctx.fill(); });
    });
  }

  function drawDaily() {
    const cnv = document.getElementById("dayChart");
    if (!cnv) return;
    const { ctx, w, h } = setup(cnv);
    const S = state.stats.modes;
    const m = S[statMode] ? statMode : "ALL";
    const d = (S[m].daily || []).slice(-14);
    if (!d.length) { noData(ctx, w, h, "Noch keine Tageswerte"); return; }
    let hi = Math.max(0, ...d.map((x) => x.pnl)), lo = Math.min(0, ...d.map((x) => x.pnl));
    if (hi === lo) hi = 1;
    const L = 40, R = 6, T = 14, B = 16;
    const ys = (v) => T + (1 - (v - lo) / (hi - lo)) * (h - T - B);
    ctx.strokeStyle = "#141922"; ctx.fillStyle = "#555e70"; ctx.lineWidth = 1;
    [hi, 0, lo].forEach((v) => { const y = Math.round(ys(v)) + 0.5; ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(w - R, y); ctx.stroke(); ctx.fillText(nf2.format(v), 2, y + 3); });
    const slot = (w - L - R) / Math.max(d.length, 7);
    const bw = Math.min(28, slot * 0.6);
    d.forEach((x, i) => {
      const cx = L + slot * i + slot / 2;
      const y1 = ys(Math.max(0, x.pnl)), y2 = ys(Math.min(0, x.pnl));
      ctx.fillStyle = x.pnl >= 0 ? css("--green") : css("--red");
      ctx.fillRect(cx - bw / 2, y1, bw, Math.max(1, y2 - y1));
      ctx.fillStyle = "#8a93a6"; ctx.textAlign = "center";
      ctx.fillText(ddmm(x.day), cx, h - 3);
      ctx.fillStyle = x.pnl >= 0 ? css("--green") : css("--red");
      ctx.fillText((x.pnl >= 0 ? "+" : "") + nf2.format(x.pnl), cx, x.pnl >= 0 ? y1 - 3 : y2 + 10);
      ctx.textAlign = "left";
    });
  }

  function drawAll(route) {
    if (!state) return;
    document.querySelectorAll("canvas.mini").forEach((cnv) => {
      const mint = cnv.getAttribute("data-mint");
      const pos = (state.positions || []).find((p) => p.mint === mint);
      drawPriceChart(cnv, (pos && pos.prices) || [], pos, state.settings);
    });
    if (route === "coin") {
      const cnv = document.getElementById("chart");
      const { mint } = parseHash();
      const c = state.coins && state.coins[mint];
      if (cnv && c) drawPriceChart(cnv, c.prices || [], c.position, state.settings);
    }
    if (route === "stats" && state.stats && state.stats.modes) { drawEquity(); drawDaily(); }
  }

  /* ------------------------------------------------------------ render */
  let lastRoute = null;
  function render() {
    const root = document.getElementById("app");
    const { route, mint } = parseHash();
    if (error && !state) {
      root.innerHTML = shell(`<div class="error" id="error-state">${esc(error)}</div>`, "home");
      bind(root);
      return;
    }
    let inner = "", tab = route;
    if (route === "agents") inner = viewAgents();
    else if (route === "stats") inner = viewStats();
    else if (route === "auditor") { inner = viewAuditor(mint); tab = "agents"; }
    else if (route === "coin") { inner = viewCoin(mint); tab = "home"; }
    else if (route === "account") inner = viewAccount();
    else { inner = viewHome(); tab = "home"; }
    if (error) inner = `<div class="error" style="margin-bottom:8px">${esc(error)} Zeige letzten Stand.</div>` + inner;
    const y = window.scrollY;
    root.innerHTML = shell(inner, tab);
    bind(root);
    if (route === lastRoute) window.scrollTo(0, y);
    lastRoute = route;
    requestAnimationFrame(() => drawAll(route));
  }

  function bind(root) {
    root.querySelectorAll("[data-go]").forEach((b) => {
      b.addEventListener("click", (e) => { e.preventDefault(); go(b.getAttribute("data-go")); });
    });
    root.querySelectorAll("[data-stat]").forEach((b) => {
      b.addEventListener("click", () => { statMode = b.getAttribute("data-stat"); localStorage.setItem(LS_STAT, statMode); render(); });
    });
    const more = root.querySelector("#tapeMore");
    if (more) more.addEventListener("click", () => { tapeAll = !tapeAll; render(); });
  }

  // keep the "updated x ago" label fresh without re-rendering
  setInterval(() => {
    if (!state) return;
    const a = ageSec(state.ts);
    const t = document.getElementById("updTxt"), d = document.getElementById("updDot");
    if (t) t.textContent = hhmm(state.ts, true) + " · vor " + ageTxt(a);
    if (d) d.className = "dot " + dotCls(a, 150, 600);
  }, 5000);

  let rz = null;
  window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => drawAll(parseHash().route), 150); });
  window.addEventListener("hashchange", () => {
    const h = parseHash();
    if (h.data) localStorage.setItem(LS_KEY, h.data);
    window.scrollTo(0, 0);
    render();
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });
  load();
  setInterval(load, POLL_MS);
})();
