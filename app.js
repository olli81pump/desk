(function () {
  "use strict";
  const LS_KEY = "desk_data_path";
  const LIVE_JSON = "live.json";
  const TZ = "Europe/Berlin";
  const AGENTS = ["gmgn-skills", "tradingview-mcp", "timesfm", "ai-hedge-fund", "TradingAgents"];
  const ICONS = {
    "gmgn-skills": "✦",
    "tradingview-mcp": "▲",
    "timesfm": "▦",
    "ai-hedge-fund": "⛽",
    "TradingAgents": "◈",
  };

  let state = null;
  let error = null;
  let liveOrigin = localStorage.getItem("desk_live_origin") || null;
  let liveOk = false;
  let liveLast = 0;
  let lastTick = null;
  let desk = null;
  let lastGoodChart = null;
  let stateFreshAt = 0;
  let pollBusy = false;
  let liveFails = 0;
  let liveBackoffUntil = 0;
  let chartInFlight = false;
  let lastChartPullKey = "";
  let lastChartPullAt = 0;
  let lastChartKey = "";
  let selectedTf = (function () {
    const v = localStorage.getItem("desk_tf") || "1m";
    return (v === "1m" || v === "5m" || v === "15m") ? v : "1m";
  })();
  let tradesTab = localStorage.getItem("desk_trades_tab") || "closed";
  let uiBound = false;

  function fetchTimeout(url, ms, opts) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), ms || 10000);
    return fetch(url, Object.assign({ cache: "no-store", signal: ctrl.signal }, opts || {}))
      .finally(() => clearTimeout(t));
  }

  function dataPath() {
    const q = new URLSearchParams(location.search).get("d");
    const hash = (location.hash || "").replace(/^#/, "");
    let fromHash = null;
    if (hash.startsWith("d=")) {
      const cut = hash.search(/[&/]/);
      fromHash = decodeURIComponent(cut === -1 ? hash.slice(2) : hash.slice(2, cut));
    }
    const v = fromHash || q;
    if (v && v.length >= 20) {
      localStorage.setItem(LS_KEY, v);
      return v;
    }
    return localStorage.getItem(LS_KEY);
  }

  function showPathPrompt() {
    const root = document.getElementById("app") || document.body;
    root.innerHTML = `<div class="gate">
      <div class="brand" style="justify-content:center;margin-bottom:8px">olli81</div>
      <h1>Zugang einrichten</h1>
      <p>Füge den Zugangscode aus dem Chat ein. Das ist nur einmal nötig.</p>
      <input id="dpIn" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Zugangscode">
      <button id="dpBtn">SPEICHERN</button>
    </div>`;
    document.getElementById("dpBtn").onclick = () => {
      let v = (document.getElementById("dpIn").value || "").trim();
      const m = v.match(/[#&?]d=([^&]+)/); if (m) v = decodeURIComponent(m[1]);
      if (v.length < 20) return;
      localStorage.setItem(LS_KEY, v);
      location.href = location.pathname + location.search.replace(/[?&]d=[^&]*/g, "");
      location.reload();
    };
  }

  async function load() {
    if (window.__DESK_PREVIEW__) return;
    const dp = dataPath();
    if (!dp) { showPathPrompt(); return; }
    const url = `d/${encodeURIComponent(dp)}/state.json?ts=${Date.now()}`;
    try {
      const r = await fetchTimeout(url, 12000);
      if (!r.ok) throw new Error("HTTP " + r.status);
      state = await r.json();
      error = null;
      desk = keepChart((state && state.desk) || desk);
      if (lastTick) applyTick(lastTick);
      stateFreshAt = Date.now();
    } catch (e) {
      if (!desk) error = "state.json konnte nicht geladen werden.";
    }
    render();
  }

  function liveFresh() { return liveOk && liveLast && (Date.now() - liveLast) < 15000; }

  async function discoverLiveOrigin() {
    try {
      const r = await fetchTimeout(LIVE_JSON + "?ts=" + Date.now(), 8000);
      if (r.ok) {
        const j = await r.json();
        const origin = j && j.origin ? String(j.origin).replace(/\/$/, "") : "";
        if (/^https:\/\/[a-z0-9.-]+$/i.test(origin)) {
          liveOrigin = origin;
          localStorage.setItem("desk_live_origin", origin);
          return origin;
        }
      }
    } catch (e) { /* keep last */ }
    return liveOrigin;
  }


  function keepChart(d) {
    if (!d) return d;
    if (!hasOpen(d)) {
      d.candles = [];
      return d;
    }
    if (d.candles && d.candles.length >= 2 && d.coin) {
      lastGoodChart = { candles: d.candles, coin: d.coin, tf: d.tf, chart_status: d.chart_status || (d.coin && d.coin.status) };
      return d;
    }
    if (lastGoodChart) {
      d.candles = lastGoodChart.candles;
      d.tf = d.tf || lastGoodChart.tf;
      if (!d.coin || !d.coin.mint) d.coin = lastGoodChart.coin;
      if (!d.chart_status && lastGoodChart.chart_status) d.chart_status = lastGoodChart.chart_status;
      if (d.coin && !d.coin.status) d.coin.status = lastGoodChart.chart_status;
    }
    return d;
  }

  function applyTick(tick) {
    if (!tick) return;
    lastTick = tick;
    if (!desk) desk = {};
    if (tick.ts && state) state.ts = tick.ts;
    const s = tick.strategy || {};
    const incomingMode = s.mode ? String(s.mode).toLowerCase() : null;
    const prevMode = String(desk.mode || "").toLowerCase();
    const modeChanged = !!(incomingMode && prevMode && incomingMode !== prevMode);
    if (modeChanged) {
      lastGoodChart = null;
      lastChartKey = "";
      lastChartPullKey = "";
      desk.candles = [];
      desk.open = [];
      desk.trades = [];
      desk.equity_curve = [];
      desk.phase_line = "PHASE: SCANNING";
      desk._chartMintDirty = true;
    }
    if (s.equity != null) desk.equity = s.equity;
    if (s.pot_cash != null) desk.pot_cash = s.pot_cash;
    if (s.pot_start != null) desk.pot_start = s.pot_start;
    if (s.unrealized != null) desk.unrealized = s.unrealized;
    if (s.pnl_total != null) desk.pnl_total = s.pnl_total;
    else if (s.equity != null && desk.pot_start) desk.pnl_total = Math.round((s.equity - desk.pot_start) * 100) / 100;
    if (s.multiple != null) desk.multiple = s.multiple;
    if (s.trades_n != null) desk.trades_n = s.trades_n;
    if (s.wins != null) desk.wins = s.wins;
    if (s.losses != null) desk.losses = s.losses;
    if (s.equity_curve) desk.equity_curve = s.equity_curve;
    if (incomingMode) desk.mode = incomingMode;
    if (s.open) {
      const prevMint = (desk.open && desk.open[0] && desk.open[0].mint) || "";
      desk.open = s.open;
      const nowMint = (desk.open[0] && desk.open[0].mint) || "";
      if (nowMint !== prevMint) desk._chartMintDirty = true;
    } else if (modeChanged) {
      desk.open = [];
    }
    if (s.unrealized == null && desk.open && desk.open.length) {
      let u = 0, any = false;
      desk.open.forEach((o) => { if (o && o.pnl != null) { u += Number(o.pnl); any = true; } });
      if (any) desk.unrealized = Math.round(u * 100) / 100;
    }
    if (!desk.open || !desk.open.length) desk.unrealized = 0;
    if (s.closed) desk.trades = s.closed.map((row) => rememberImgs(Object.assign({}, row)));
    else if (modeChanged) desk.trades = [];
    if (s.rules) desk.rules = s.rules;
    if (s.phase_line) desk.phase_line = s.phase_line;
    else if (modeChanged) desk.phase_line = "PHASE: SCANNING";
    if (tick.coin) desk.coin = mergeCoin(desk.coin, tick.coin);
    if (tick.market_mode) desk.market_mode = Object.assign({}, desk.market_mode || {}, tick.market_mode);
    if (tick.copy) desk.copy = Object.assign({}, desk.copy || {}, tick.copy);
    if (tick.check && tick.check.mint) {
      const open = hasOpen(desk) || hasOpen(tick.strategy);
      if (!open) {
        const prev = desk.coin || {};
        const same = prev.mint === tick.check.mint;
        const chk = tick.check;
        desk.coin = mergeCoin(prev, {
          mint: chk.mint, name: chk.name || prev.name, symbol: chk.symbol || prev.symbol,
          status: chk.status, image: chk.image, images: chk.images,
          mc_src: chk.mc_src || prev.mc_src
        });
        if (posNum(chk.px) || chk.px === 0) desk.coin.px = chk.px;
        if (posNum(chk.mc)) { desk.coin.mc = chk.mc; if (chk.mc_src) desk.coin.mc_src = chk.mc_src; }
        if (posNum(chk.liq)) desk.coin.liq = chk.liq;
        if (posNum(chk.vol24)) desk.coin.vol24 = chk.vol24;
        desk.chart_status = chk.status || desk.chart_status;
        desk.candles = [];
        desk._chartMintDirty = false;
      }
    }
    if (tick.eval && (tick.eval.votes || tick.eval.kind === "buy" || tick.eval.kind === "skip" || tick.eval.kind === "running")) {
      const ev = tick.eval;
      desk.vote = Object.assign({}, desk.vote || {}, {
        mint: ev.mint, name: ev.name || (desk.vote && desk.vote.name), symbol: ev.symbol || (desk.vote && desk.vote.symbol),
        image: ev.image || (desk.vote && desk.vote.mint === ev.mint ? desk.vote.image : "") || (desk.coin && desk.coin.mint === ev.mint ? desk.coin.image : ""),
        images: ev.images || (desk.vote && desk.vote.mint === ev.mint ? desk.vote.images : null) || (desk.coin && desk.coin.mint === ev.mint ? desk.coin.images : null),
        ts: ev.ts, kind: ev.kind, yes: ev.yes, need: ev.need || 4,
        status: ev.status || eyeStatus(ev.kind),
        reason: ev.reason, candidates: ev.candidates, source: "agents"
      });
      if (Array.isArray(ev.votes)) {
        const map = {};
        ev.votes.forEach((v) => { if (v && v.agent) map[v.agent] = v; });
        desk.agents = AGENTS.map((n) => {
          const v = map[n] || {};
          const y = yn(v.yes != null ? v.yes : v.mark);
          let st = v.status;
          if (!st) {
            if (y === true) st = "pass";
            else if (y === false) st = "fail";
            else if (ev.kind === "running") st = "pending";
            else st = "idle";
          }
          return {
            name: n, yes: y, why: v.why || "", mark: v.mark,
            status: st, started_at: v.started_at, finished_at: v.finished_at, expected_s: v.expected_s
          };
        });
      }
    }
  }

  function yn(v) {
    if (v === true || v === 1 || v === "1" || v === "+" || v === "yes" || v === "true") return true;
    if (v === false || v === 0 || v === "0" || v === "-" || v === "no" || v === "false") return false;
    return null;
  }

  function eyeStatus(kind) {
    kind = String(kind || "").toLowerCase();
    if (kind === "buy") return "passed · buy";
    if (kind === "filter") return "failed · filter";
    if (!kind || kind === "idle") return "idle";
    return "failed · skip";
  }

  function money(n, d) {
    if (n == null || !isFinite(n)) return "—";
    const digits = d == null ? 2 : d;
    const abs = Math.abs(n);
    return (n < 0 ? "−" : "") + "$" + abs.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }
  function moneySign(n) {
    if (n == null || !isFinite(n)) return "—";
    const sign = n > 0 ? "+" : n < 0 ? "−" : "";
    return sign + "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function compact(n) {
    if (n == null || !isFinite(n)) return "—";
    const a = Math.abs(n);
    const s = n < 0 ? "−" : "";
    if (a >= 1e9) return s + "$" + (a / 1e9).toFixed(2) + "B";
    if (a >= 1e6) return s + "$" + (a / 1e6).toFixed(2) + "M";
    if (a >= 1e3) return s + "$" + (a / 1e3).toFixed(1) + "K";
    return s + "$" + a.toFixed(0);
  }
  const mcMemo = {};
  function posNum(v) {
    const n = Number(v);
    return (v != null && isFinite(n) && n > 0) ? n : null;
  }
  function rememberMc(coin) {
    if (!coin || !coin.mint) return coin;
    const got = posNum(coin.mc);
    if (got) {
      mcMemo[coin.mint] = { mc: got, src: coin.mc_src || (mcMemo[coin.mint] && mcMemo[coin.mint].src) };
    } else if (mcMemo[coin.mint]) {
      coin.mc = mcMemo[coin.mint].mc;
      coin.mc_src = coin.mc_src || mcMemo[coin.mint].src || "cache";
    }
    return coin;
  }
  function hasOpen(d) {
    return !!(d && d.open && d.open.length);
  }
  function mcMetric(coin) {
    const c = rememberMc(coin || {});
    const src = c.mc_src ? `<small class="mc-src">${esc(c.mc_src)}</small>` : "";
    return `<span>MC <b>${compact(c.mc)}</b>${src}</span>`;
  }
  const imgMemo = {};
  function imgList(obj) {
    if (!obj) return [];
    const mint = obj.mint;
    const raw = [].concat(obj.images || [], obj.image ? [obj.image] : [], (mint && imgMemo[mint] && imgMemo[mint].images) || []);
    const out = [];
    raw.forEach((u) => {
      if (typeof u === "string" && /^https:\/\//.test(u) && out.indexOf(u) < 0) out.push(u);
    });
    return out;
  }
  function rememberImgs(obj) {
    if (!obj || !obj.mint) return obj;
    const imgs = imgList(obj);
    if (imgs.length) {
      imgMemo[obj.mint] = { images: imgs, image: imgs[0] };
      obj.images = imgs;
      obj.image = obj.image || imgs[0];
    } else if (imgMemo[obj.mint]) {
      obj.images = imgMemo[obj.mint].images;
      obj.image = obj.image || imgMemo[obj.mint].image;
    }
    return obj;
  }
  function initialsOf(obj) {
    const nm = (obj && (obj.symbol || obj.name)) || "•";
    return String(nm).replace(/^\$/, "").slice(0, 2).toUpperCase() || "•";
  }
  function avatarHtml(obj, cls) {
    const o = rememberImgs(obj || {});
    const initials = initialsOf(o);
    const urls = imgList(o);
    const klass = cls ? " class=\"" + cls + "\"" : "";
    if (!urls.length) return esc(initials);
    const rest = urls.slice(1).join("|");
    return `<img${klass} src="${esc(urls[0])}" alt="" data-alts="${esc(rest)}" data-initials="${esc(initials)}" onerror="window.__deskImgErr&&window.__deskImgErr(this)">`;
  }
  window.__deskImgErr = function (el) {
    if (!el) return;
    const alts = (el.getAttribute("data-alts") || "").split("|").filter(Boolean);
    if (alts.length) {
      el.setAttribute("data-alts", alts.slice(1).join("|"));
      el.src = alts[0];
      return;
    }
    const span = document.createElement("span");
    span.textContent = el.getAttribute("data-initials") || "•";
    el.replaceWith(span);
  };
  function mergeCoin(prev, nxt) {
    prev = prev || {};
    nxt = nxt || {};
    const out = Object.assign({}, prev, nxt);
    const imgs = imgList(nxt).concat(imgList(prev));
    const seen = [];
    imgs.forEach((u) => { if (seen.indexOf(u) < 0) seen.push(u); });
    if (seen.length) {
      out.images = seen;
      out.image = (typeof nxt.image === "string" && nxt.image) ? nxt.image : (prev.image || seen[0]);
    } else {
      out.image = prev.image || nxt.image || null;
      out.images = prev.images || nxt.images;
    }
    rememberImgs(out);
    rememberMc(out);
    return out;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function clockNow() {
    return new Date().toLocaleTimeString("de-DE", { timeZone: TZ, hour12: false });
  }
  function parseTs(ts) {
    if (ts == null || ts === "") return null;
    if (typeof ts === "number") {
      const n = Number(ts);
      const d = new Date(n < 1e12 ? n * 1000 : n);
      return isNaN(d.getTime()) ? null : d;
    }
    const s = String(ts).trim();
    if (!s) return null;
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  }
  function tsMs(ts) {
    const d = parseTs(ts);
    return d ? d.getTime() : 0;
  }
  function hhmm(ts) {
    const d = parseTs(ts);
    if (!d) return "";
    try {
      return d.toLocaleTimeString("de-DE", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
    } catch (e) { return ""; }
  }
  function dayTime(ts) {
    const d = parseTs(ts);
    if (!d) return "";
    try {
      const parts = new Intl.DateTimeFormat("de-DE", {
        timeZone: TZ, day: "2-digit", month: "2-digit",
        hour: "2-digit", minute: "2-digit", hour12: false
      }).formatToParts(d);
      const get = (typ) => ((parts.find((p) => p.type === typ) || {}).value || "");
      const out = get("day") + "." + get("month") + ". " + get("hour") + ":" + get("minute");
      return /\d/.test(out) ? out : hhmm(ts);
    } catch (e) { return hhmm(ts); }
  }
  function shortMint(m) {
    if (!m) return "";
    const raw = String(m).replace(/`/g, "").trim();
    const s = raw.replace(/[.…]+$/g, "");
    if (!s) return "";
    if (raw.indexOf("…") >= 0 || s.length <= 12) return raw;
    if (/pump$/i.test(s)) return s.slice(0, 4) + "…pump";
    return s.slice(0, 4) + "…" + s.slice(-4);
  }
  function coinLabel(e, d) {
    if (!e) return "";
    let name = String(e.name || "").replace(/\s+\((paper|LIVE|live)\)$/i, "").trim();
    let title = String(e.title || "").replace(/\s+\((paper|LIVE|live)\)$/i, "").trim();
    if (title.indexOf(" · ") >= 0) title = title.split(" · ")[0].trim();
    if (!name) name = title;
    let symbol = String(e.symbol || "").replace(/^\$/, "").trim();
    const mint = e.mint || "";
    const pool = [].concat((d && d.trades) || [], (d && d.open) || []);
    if (d && d.coin) pool.push(d.coin);
    if (d && d.checked) pool.push(d.checked);
    if (d && d.vote) pool.push(d.vote);
    if (mint) {
      const hit = pool.find((x) => x && x.mint && x.mint === mint);
      if (hit) {
        if (!name) name = String(hit.name || "").trim();
        if (!symbol) symbol = String(hit.symbol || "").replace(/^\$/, "").trim();
      }
    }
    if (name && symbol) {
      return name + " ($" + symbol + ")";
    }
    if (name) return name;
    if (symbol) return "$" + symbol;
    const blob = String((e.text || "") + " " + (e.title || ""));
    const bm = blob.match(/`([1-9A-HJ-NP-Za-km-z]{4,44})(…|\.\.\.)?`/);
    if (bm) return bm[1] + (bm[2] ? "…" : "");
    if (mint) return shortMint(mint);
    return "";
  }

  function spark(curve, up) {
    if (!curve || curve.length < 2) {
      return `<svg viewBox="0 0 200 54" preserveAspectRatio="none"><path d="M0 40 H200" fill="none" stroke="${up ? "#30d158" : "#5c6578"}" stroke-width="2"/></svg>`;
    }
    const vals = curve.map((p) => Number(p.v)).filter(isFinite);
    const min = Math.min(...vals), max = Math.max(...vals);
    const span = Math.max(1e-9, max - min);
    const w = 200, h = 54, pad = 4;
    const pts = vals.map((v, i) => {
      const x = pad + (i / (vals.length - 1)) * (w - pad * 2);
      const y = h - pad - ((v - min) / span) * (h - pad * 2);
      return x.toFixed(1) + "," + y.toFixed(1);
    });
    const last = pts[pts.length - 1].split(",");
    const color = up ? "#30d158" : (vals[vals.length - 1] < vals[0] ? "#ff453a" : "#30d158");
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <path d="M${pts.join(" L")}" fill="none" stroke="${color}" stroke-width="2.2" stroke-linejoin="round"/>
      <circle cx="${last[0]}" cy="${last[1]}" r="3.2" fill="${color}"/>
    </svg>`;
  }

  function chartLevels(d) {
    const open = (d && d.open && d.open[0]) || null;
    const rules = (d && d.rules) || { tp: [4, 10, 20], trail: 40, stop: 25, timer: 75 };
    if (!open || open.entry == null) return { rules: rules, open: null, lines: [] };
    const entry = Number(open.entry);
    const lv = open.levels || {};
    const tps = lv.tps || open.tp_px || (rules.tp || []).map((m) => entry * Number(m));
    const lines = [];
    const add = (key, label, price, color) => {
      if (price == null || !isFinite(price)) return;
      lines.push({ key, label, price: Number(price), color });
    };
    add("entry", "Entry", lv.entry != null ? lv.entry : entry, "#64d2ff");
    add("sl", "SL", lv.stop != null ? lv.stop : entry * (1 - Number(rules.stop) / 100), "#ff453a");
    (tps || []).forEach((px, i) => add("tp" + (i + 1), "TP" + (i + 1), px, ["#30d158", "#ffd60a", "#bf5af2"][i] || "#bf5af2"));
    if (lv.trail_active || open.trail_active) {
      add("trail", "Trail", lv.trail != null ? lv.trail : open.trail_px, "#ff9f0a");
    }
    return { rules, open, lines, timerLeft: open.timer_left };
  }

  function drawChart(canvas, candles, d) {
    if (!canvas || !candles || candles.length < 2) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (w < 20 || h < 20) return;
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const padL = 8, padR = 58, padT = 16, padB = 22;
    const lows = candles.map((c) => c.l), highs = candles.map((c) => c.h);
    let min = Math.min(...lows), max = Math.max(...highs);
    const ov = chartLevels(d || desk || {});
    const near = [];
    ov.lines.forEach((ln) => {
      // include entry, sl, trail, and the next unused TP so the scale stays usable
      if (ln.key === "entry" || ln.key === "sl" || ln.key === "trail") near.push(ln.price);
    });
    const nextTp = ov.lines.find((ln) => ln.key.indexOf("tp") === 0 && max * 1.15 >= ln.price);
    if (nextTp) near.push(nextTp.price);
    if (near.length) {
      min = Math.min(min, ...near);
      max = Math.max(max, ...near);
    }
    const span = Math.max(1e-12, max - min) * 1.04;
    const mid = (max + min) / 2;
    min = mid - span / 2; max = mid + span / 2;
    const n = candles.length;
    const cw = (w - padL - padR) / n;
    const y = (v) => padT + (1 - (v - min) / (max - min)) * (h - padT - padB);
    // gridlines on
    ctx.strokeStyle = "rgba(255,255,255,.16)";
    ctx.lineWidth = 1;
    ctx.fillStyle = "#8b93a7";
    ctx.font = "11px Inter, sans-serif";
    ctx.textAlign = "right";
    for (let i = 0; i <= 4; i++) {
      const v = min + (max - min) * (i / 4);
      const yy = y(v);
      ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(w - padR, yy); ctx.stroke();
      ctx.fillText(v >= 1 ? v.toFixed(2) : v.toPrecision(3), w - 6, yy + 3);
    }
    ctx.strokeStyle = "rgba(255,255,255,.08)";
    const step = Math.max(1, Math.round(n / 6));
    for (let i = 0; i < n; i += step) {
      const x = padL + (i + 0.5) * cw;
      ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, h - padB); ctx.stroke();
    }
    candles.forEach((c, i) => {
      const x = padL + (i + 0.5) * cw;
      const up = c.c >= c.o;
      ctx.strokeStyle = up ? "#30d158" : "#ff453a";
      ctx.fillStyle = up ? "#30d158" : "#ff453a";
      ctx.beginPath();
      ctx.moveTo(x, y(c.h));
      ctx.lineTo(x, y(c.l));
      ctx.stroke();
      const body = Math.max(1.2, Math.abs(y(c.c) - y(c.o)));
      const top = Math.min(y(c.o), y(c.c));
      const bw = Math.max(1.5, Math.min(8, cw * 0.62));
      ctx.fillRect(x - bw / 2, top, bw, body);
    });
    // strategy overlay
    ov.lines.forEach((ln) => {
      const yy = y(ln.price);
      if (yy < padT - 2 || yy > h - padB + 2) return;
      ctx.strokeStyle = ln.color;
      ctx.lineWidth = 1.2;
      ctx.setLineDash([5, 4]);
      ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(w - padR, yy); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = ln.color;
      ctx.textAlign = "left";
      ctx.font = "10px Inter, sans-serif";
      const tag = ln.label + " " + (ln.price >= 1 ? ln.price.toFixed(4) : ln.price.toPrecision(4));
      ctx.fillRect(padL, yy - 7, ctx.measureText(tag).width + 8, 13);
      ctx.fillStyle = "#0b0f16";
      ctx.fillText(tag, padL + 4, yy + 3);
    });
    if (ov.open && ov.timerLeft != null) {
      ctx.fillStyle = "#e8ecf5";
      ctx.font = "11px Inter, sans-serif";
      ctx.textAlign = "left";
      ctx.fillText("TIMER " + Math.max(0, Math.round(ov.timerLeft)) + "m", padL + 4, padT - 4);
    }
    ctx.fillStyle = "#5c6578";
    ctx.textAlign = "center";
    const first = candles[0], last = candles[candles.length - 1];
    const fmt = (ts) => {
      const dte = new Date(ts * 1000);
      return dte.toLocaleTimeString("de-DE", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
    };
    if (first && first.t) ctx.fillText(fmt(first.t), padL + 20, h - 6);
    if (last && last.t) ctx.fillText(fmt(last.t), w - padR - 8, h - 6);
  }


  const AGENT_META = {
    "gmgn-skills": { label: "SCANNER", color: "#3ad0c8" },
    "tradingview-mcp": { label: "CHART READER", color: "#ff9f0a" },
    "timesfm": { label: "FORECASTER", color: "#ff7ad9" },
    "ai-hedge-fund": { label: "RISK MANAGER", color: "#ff453a" },
    "TradingAgents": { label: "BULL VS BEAR", color: "#bf5af2" }
  };
  const RING_R = 34;
  const RING_C = 2 * Math.PI * RING_R;

  function robotFace(name) {
    /* Original inline robot faces (not copied logos). Each is a distinct Grok-Bot-style head. */
    if (name === "gmgn-skills") {
      /* SCANNER — cyan, classic silver head + antenna */
      return `<svg viewBox="0 0 64 64" aria-hidden="true">
        <circle cx="32" cy="34" r="18.5" fill="#cfd3dc"/>
        <circle cx="32" cy="34" r="18.5" fill="none" stroke="#9aa1ae" stroke-width="1.2"/>
        <rect x="30.2" y="8" width="3.6" height="8" rx="1.2" fill="#9aa1ae"/>
        <circle cx="32" cy="7.2" r="3.1" fill="#3ad0c8"/>
        <ellipse cx="16.5" cy="34" rx="3.2" ry="4.2" fill="#b4b9c4"/>
        <ellipse cx="47.5" cy="34" rx="3.2" ry="4.2" fill="#b4b9c4"/>
        <rect x="20" y="28" width="24" height="11" rx="5.5" fill="#1a222c"/>
        <circle cx="26.5" cy="33.5" r="3.1" fill="#3ad0c8"/>
        <circle cx="37.5" cy="33.5" r="3.1" fill="#3ad0c8"/>
        <path d="M27 44c2.4 2.2 7.6 2.2 10 0" fill="none" stroke="#5c6470" stroke-width="1.6" stroke-linecap="round"/>
      </svg>`;
    }
    if (name === "tradingview-mcp") {
      /* CHART READER — orange, round glasses */
      return `<svg viewBox="0 0 64 64" aria-hidden="true">
        <circle cx="32" cy="34" r="18.5" fill="#d4c6b0"/>
        <circle cx="32" cy="34" r="18.5" fill="none" stroke="#b89a6a" stroke-width="1.2"/>
        <ellipse cx="16.5" cy="34" rx="3.2" ry="4.2" fill="#c4b49a"/>
        <ellipse cx="47.5" cy="34" rx="3.2" ry="4.2" fill="#c4b49a"/>
        <circle cx="24.5" cy="33" r="7.2" fill="none" stroke="#ff9f0a" stroke-width="2.2"/>
        <circle cx="39.5" cy="33" r="7.2" fill="none" stroke="#ff9f0a" stroke-width="2.2"/>
        <path d="M31.7 33h.6" stroke="#ff9f0a" stroke-width="2" stroke-linecap="round"/>
        <circle cx="24.5" cy="33" r="2.5" fill="#2a1f10"/>
        <circle cx="39.5" cy="33" r="2.5" fill="#2a1f10"/>
        <circle cx="25.2" cy="32.3" r="0.8" fill="#ffe0a8"/>
        <circle cx="40.2" cy="32.3" r="0.8" fill="#ffe0a8"/>
        <path d="M27 44.5c2.2 1.8 7.8 1.8 10 0" fill="none" stroke="#6a5840" stroke-width="1.6" stroke-linecap="round"/>
      </svg>`;
    }
    if (name === "timesfm") {
      /* FORECASTER — pink hood / bob */
      return `<svg viewBox="0 0 64 64" aria-hidden="true">
        <path d="M14 36c0-14 8-24 18-24s18 10 18 24c0 3-1 8-3 11-4 2-9 3-15 3s-11-1-15-3c-2-3-3-8-3-11z" fill="#f3a4d4"/>
        <path d="M14 36c0-14 8-24 18-24s18 10 18 24" fill="none" stroke="#e078b4" stroke-width="1.2"/>
        <circle cx="32" cy="36" r="14.5" fill="#ece4ea"/>
        <ellipse cx="26" cy="35.5" rx="3.3" ry="3.8" fill="#ff7ad9"/>
        <ellipse cx="38" cy="35.5" rx="3.3" ry="3.8" fill="#ff7ad9"/>
        <circle cx="26.7" cy="34.6" r="1" fill="#fff"/>
        <circle cx="38.7" cy="34.6" r="1" fill="#fff"/>
        <path d="M28 44c1.8 1.4 6.2 1.4 8 0" fill="none" stroke="#b0709a" stroke-width="1.5" stroke-linecap="round"/>
      </svg>`;
    }
    if (name === "ai-hedge-fund") {
      /* RISK MANAGER — red, stern angled brows */
      return `<svg viewBox="0 0 64 64" aria-hidden="true">
        <circle cx="32" cy="34" r="18.5" fill="#b8bac2"/>
        <circle cx="32" cy="34" r="18.5" fill="none" stroke="#8e9098" stroke-width="1.2"/>
        <rect x="18" y="22" width="28" height="4" rx="1" fill="#6a6e76"/>
        <ellipse cx="16.5" cy="34" rx="3.2" ry="4.2" fill="#9a9da6"/>
        <ellipse cx="47.5" cy="34" rx="3.2" ry="4.2" fill="#9a9da6"/>
        <path d="M21 28l9 3" stroke="#ff453a" stroke-width="2.3" stroke-linecap="round"/>
        <path d="M43 28l-9 3" stroke="#ff453a" stroke-width="2.3" stroke-linecap="round"/>
        <rect x="22" y="31.5" width="8" height="5" rx="1.2" fill="#1a1516"/>
        <rect x="34" y="31.5" width="8" height="5" rx="1.2" fill="#1a1516"/>
        <rect x="24" y="33" width="4" height="2.2" rx="0.6" fill="#ff453a"/>
        <rect x="36" y="33" width="4" height="2.2" rx="0.6" fill="#ff453a"/>
        <path d="M28 45h8" stroke="#5a4a4a" stroke-width="1.8" stroke-linecap="round"/>
      </svg>`;
    }
    /* BULL VS BEAR — purple tint, one horn + one rounded ear */
    return `<svg viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="32" cy="35" r="18.2" fill="#c8b4e6"/>
      <circle cx="32" cy="35" r="18.2" fill="none" stroke="#9b7cc8" stroke-width="1.2"/>
      <path d="M18 20c-1-6 6-9 9-4" fill="none" stroke="#bf5af2" stroke-width="3.2" stroke-linecap="round"/>
      <path d="M42 16c4-1 8 4 5 9" fill="#a57ad8"/>
      <ellipse cx="17" cy="35" rx="3.2" ry="4.2" fill="#b49cd4"/>
      <ellipse cx="47" cy="35" rx="3.2" ry="4.2" fill="#b49cd4"/>
      <rect x="20" y="30" width="24" height="10" rx="5" fill="#2a1840"/>
      <circle cx="26.5" cy="35" r="2.8" fill="#e2c8ff"/>
      <circle cx="37.5" cy="35" r="2.8" fill="#e2c8ff"/>
      <path d="M27 45c2.4 2.4 7.6 2.4 10 0" fill="none" stroke="#6a4a90" stroke-width="1.6" stroke-linecap="round"/>
    </svg>`;
  }

  function badgeSvg(status) {
    if (status === "pass") {
      return `<span class="agent-badge pass" aria-label="pass"><svg viewBox="0 0 18 18"><circle cx="9" cy="9" r="9" fill="#30d158"/><path d="M5 9.3l2.6 2.5 5.5-5.7" fill="none" stroke="#fff" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/></svg></span>`;
    }
    if (status === "fail") {
      return `<span class="agent-badge fail" aria-label="fail"><svg viewBox="0 0 18 18"><circle cx="9" cy="9" r="9" fill="#ff453a"/><path d="M6 6l6 6M12 6l-6 6" fill="none" stroke="#fff" stroke-width="2.1" stroke-linecap="round"/></svg></span>`;
    }
    return `<span class="agent-badge empty" aria-hidden="true"></span>`;
  }

  function agentStatusOf(a, vote) {
    if (a && a.status) return a.status;
    const y = yn(a && (a.yes != null ? a.yes : a.mark));
    if (y === true) return "pass";
    if (y === false) return "fail";
    if (vote && vote.kind === "running") return "pending";
    return "idle";
  }

  function ringProgress(a, now) {
    const st = agentStatusOf(a);
    if (st === "pass" || st === "fail") return 1;
    if (st !== "running") return 0;
    const exp = Number(a && a.expected_s) || 10;
    let t0 = Number(a && a.started_at) || 0;
    if (!t0) return 0.08;
    if (t0 > 1e12) t0 = t0 / 1000;
    const startMs = t0 * 1000;
    const p = ((now || Date.now()) - startMs) / (Math.max(exp, 0.5) * 1000);
    return Math.max(0.06, Math.min(0.92, p));
  }

  function setRingEl(bar, p, status, color) {
    if (!bar) return;
    const offset = RING_C * (1 - p);
    bar.style.strokeDasharray = String(RING_C);
    bar.style.strokeDashoffset = String(offset);
    bar.style.stroke = (status === "fail") ? "#ff453a" : color;
  }

  function agentLabelHtml(label) {
    const parts = String(label || "").trim().split(/\s+/);
    if (parts.length < 2) return esc(label);
    const rest = parts.pop();
    return esc(parts.join(" ")) + '<span class="agent-br"> </span>' + esc(rest);
  }

  function agentsCardHtml(vote, agents, d) {
    vote = vote || {};
    const nm = vote.symbol || vote.name || ((d && d.coin && (d.coin.symbol || d.coin.name)) || "—");
    if (d && d.coin && vote.mint && d.coin.mint === vote.mint) {
      vote = Object.assign({}, vote, { image: vote.image || d.coin.image, images: vote.images || d.coin.images, mint: vote.mint || d.coin.mint });
    }
    const cand = vote.candidates || {};
    const idx = cand.index != null ? cand.index : "–";
    const tot = cand.total != null ? cand.total : "–";
    const rows = (agents && agents.length ? agents : AGENTS.map((n) => ({ name: n, yes: null, status: "idle" })));
    const yesN = rows.filter((a) => agentStatusOf(a, vote) === "pass").length;
    const doneN = rows.filter((a) => { const s = agentStatusOf(a, vote); return s === "pass" || s === "fail"; }).length;
    const need = (vote.need != null ? vote.need : 4);
    let cap = "idle";
    let capCls = "";
    if (vote.kind === "running") { cap = "running"; capCls = "run"; }
    else if (doneN === rows.length && rows.length) {
      const passed = yesN >= need && vote.kind === "buy";
      if (vote.kind === "buy") { cap = "passed · buy"; capCls = "pass"; }
      else if (vote.kind === "skip" || doneN) { cap = "voted · no buy"; capCls = "fail"; }
    } else if (vote.kind === "filter") { cap = "waiting · filter"; }
    const cells = rows.map((a) => {
      const meta = AGENT_META[a.name] || { label: a.name, color: "#8b93a7" };
      const st = agentStatusOf(a, vote);
      const p = ringProgress(a);
      const color = st === "fail" ? "#ff453a" : meta.color;
      const off = RING_C * (1 - p);
      const title = [meta.label, st !== "idle" ? st : "", a.why || ""].filter(Boolean).join(" — ");
      return `<div class="agent-cell status-${st}" data-agent="${esc(a.name)}" title="${esc(title)}">
        <div class="agent-orb">
          <svg class="agent-ring" viewBox="0 0 80 80" aria-hidden="true">
            <circle class="track" cx="40" cy="40" r="${RING_R}" fill="none" stroke="rgba(255,255,255,.1)" stroke-width="4.5"/>
            <circle class="bar" cx="40" cy="40" r="${RING_R}" fill="none" stroke="${color}" stroke-width="4.5" stroke-linecap="round"
              stroke-dasharray="${RING_C}" stroke-dashoffset="${off}" transform="rotate(-90 40 40)"/>
          </svg>
          <div class="agent-face">${robotFace(a.name)}</div>
          ${badgeSvg(st)}
        </div>
        <div class="agent-label">${agentLabelHtml(meta.label)}</div>
      </div>`;
    }).join("");
    return `<div class="agents-card">
      <div class="agents-head">
        <div>
          <div class="agents-kicker">AGENTS</div>
          <div class="agents-name">${esc(nm)}</div>
          <div class="agents-cand">candidates · ${esc(String(idx))} / ${esc(String(tot))}</div>
        </div>
        <div class="agents-score">
          <div class="vote-score"><span class="score-n${yesN ? " on" : ""}">${yesN}</span><span class="score-den"> / 5</span></div>
          <div class="vote-cap ${capCls}">${esc(cap)}</div>
        </div>
      </div>
      <div class="agents-row">${cells}</div>
    </div>`;
  }

  let ringTimer = 0;
  function tickRings() {
    const stage = document.getElementById("agents-stage");
    if (!stage) return;
    const vote = (desk && desk.vote) || {};
    const agents = (desk && desk.agents) || [];
    stage.querySelectorAll(".agent-cell").forEach((cell) => {
      const name = cell.getAttribute("data-agent");
      const a = agents.find((x) => x && x.name === name) || { name: name };
      const meta = AGENT_META[name] || { color: "#8b93a7" };
      const st = agentStatusOf(a, vote);
      const p = ringProgress(a);
      setRingEl(cell.querySelector(".bar"), p, st, meta.color);
    });
  }

  function ensureRingTimer() {
    if (ringTimer) return;
    ringTimer = setInterval(tickRings, 120);
  }

  function normalizeAgents(d) {
    const vote = (d && d.vote) || {};
    const raw = (d && d.agents) || [];
    return AGENTS.map((n) => {
      const a = raw.find((x) => x && x.name === n) || {};
      const y = yn(a.yes != null ? a.yes : a.mark);
      let st = a.status;
      if (!st) {
        if (y === true) st = "pass";
        else if (y === false) st = "fail";
        else if (vote.kind === "running") st = "pending";
        else st = "idle";
      }
      return {
        name: n, yes: y, why: a.why || "", mark: a.mark,
        status: st, started_at: a.started_at, finished_at: a.finished_at,
        expected_s: a.expected_s
      };
    });
  }

  function evalKey(vote, agents) {
    vote = vote || {};
    const sig = (agents || []).map((a) => [a.name, a.status || "", a.yes === true ? "1" : a.yes === false ? "0" : "", a.started_at || ""].join(":")).join(",");
    return [vote.mint || "", vote.ts || "", vote.kind || "", sig].join("|");
  }

  let agentShown = { key: "", shownAt: 0 };

  function syncAgents(d) {
    const stage = document.getElementById("agents-stage");
    if (!stage) return;
    const vote = (d && d.vote) || {};
    const agents = normalizeAgents(d);
    const html = agentsCardHtml(vote, agents, d);
    const key = evalKey(vote, agents);
    if (agentShown.key === key && stage.querySelector(".agents-card")) {
      tickRings();
      return;
    }
    stage.innerHTML = html;
    stage.classList.add("is-enter");
    agentShown = { key, shownAt: Date.now() };
    ensureRingTimer();
    tickRings();
  }

  function agentList(d) { return ""; }

  function journalRows(d) {
    const ev = d.journal || [];
    if (!ev.length) return `<div class="empty">Noch keine Journal-Zeilen.</div>`;
    return ev.slice(0, 40).map((e) => {
      const kind = e.kind || "note";
      const title = e.title || e.name || "";
      let text = e.text || e.reason || e.debate || "";
      const heading = coinLabel(e, d);
      if (kind === "buy" && text && !heading) text = (e.name || title) + ": " + text;
      const body = text || (!heading ? title : "");
      const titleCore = String(title).split(" · ")[0].trim();
      const headingCore = heading.split(" ($")[0].trim();
      const showTitle = title && kind !== "filter" && titleCore && titleCore.toLowerCase() !== headingCore.toLowerCase();
      return `<div class="jrow">
        ${heading ? `<div class="jcoin">${esc(heading)}</div>` : ""}
        <div class="tm">${esc(hhmm(e.ts))}</div>
        <div class="jt"><span class="kind ${esc(kind)}">${esc(kind.toUpperCase())}</span>${showTitle ? `<span class="k">${esc(title)}</span>` : ""}${esc(body)}</div>
      </div>`;
    }).join("");
  }

  function tradeRows(d) {
    const ev = (d.trades || []).slice().sort((a, b) => tsMs(b.closed_at || b.ts) - tsMs(a.closed_at || a.ts));
    if (!ev.length) return `<div class="empty">Noch keine geschlossenen Trades.</div>`;
    return ev.map((t) => {
      const pnl = t.pnl;
      const up = pnl != null && pnl >= 0;
      const nm = t.symbol || t.name || "Coin";
      return `<div class="trow">
        <div class="tm">${esc(dayTime(t.closed_at || t.ts))}</div>
        <div>
          <div class="jt"><span class="tav">${avatarHtml(t, "tav-img")}</span><span class="kind ${esc(t.kind || "sell")}">${esc((t.kind || "sell").toUpperCase())}</span><span class="k">${esc(nm)}</span></div>
          <div class="tmeta">${esc(t.reason || "")}</div>
        </div>
        <div class="pnl ${up ? "up" : "dn"}">${moneySign(pnl)}</div>
      </div>`;
    }).join("");
  }

  function openRows(d) {
    const ev = (d.open || []).slice().sort((a, b) => tsMs(b.opened_at || b.ts) - tsMs(a.opened_at || a.ts));
    if (!ev.length) return `<div class="empty">Keine offenen Positionen.</div>`;
    return ev.map((t) => {
      const pnl = t.pnl;
      const up = pnl != null && pnl >= 0;
      const nm = t.symbol || t.name || "Coin";
      const left = t.timer_left != null ? Math.max(0, Math.round(t.timer_left)) + "m" : "—";
      return `<div class="trow">
        <div class="tm">${esc(dayTime(t.opened_at || t.ts))}</div>
        <div>
          <div class="jt"><span class="tav">${avatarHtml(t, "tav-img")}</span><span class="kind buy">OPEN</span><span class="k">${esc(nm)}</span></div>
          <div class="tmeta">${esc(t.phase || "")}${t.entry != null ? " · entry " + Number(t.entry).toPrecision(4) : ""} · timer ${esc(left)}</div>
        </div>
        <div class="pnl ${up ? "up" : "dn"}">${moneySign(pnl)}</div>
      </div>`;
    }).join("");
  }

  function staleText() {
    if (liveFresh()) return "";
    const last = Math.max(liveLast || 0, stateFreshAt || 0);
    if (!last) return "Keine Live-Daten — Verbindung wird aufgebaut…";
    const sec = Math.round((Date.now() - last) / 1000);
    if (sec < 20) return "";
    const ago = sec < 90 ? sec + "s" : Math.round(sec / 60) + " min";
    return "Keine Live-Daten · letzte Aktualisierung vor " + ago;
  }

  function paintChart(d) {
    const wrap = document.getElementById("chart-wrap");
    if (!wrap) return;
    const coin = rememberMc(d.coin || {});
    if (!hasOpen(d)) {
      const nm = coin.name || coin.symbol || "Kein Coin";
      const key = "scan|" + (coin.mint || "") + "|" + (coin.mc || "") + "|" + (coin.liq || "") + "|" + (coin.vol24 || "") + "|" + (d.chart_status || coin.status || "") + "|" + imgList(coin).join(" ");
      if (wrap.dataset.empty !== key) {
        const src = coin.mc_src ? `<small class="mc-src">${esc(coin.mc_src)}</small>` : "";
        wrap.innerHTML = `<div class="chart-placeholder">
          <div class="ph-kicker">SCANNING</div>
          <div class="ph-head"><div class="ph-av">${avatarHtml(coin)}</div><div class="ph-name">${esc(nm)}</div></div>
          <div class="ph-meta">
            <span>MC <b>${compact(coin.mc)}</b>${src}</span>
            <span>LIQ <b>${compact(coin.liq)}</b></span>
            <span>24H VOL <b>${compact(coin.vol24)}</b></span>
          </div>
          <div class="ph-status${(d.chart_status || coin.status || "").length > 88 ? " is-long" : ""}" id="ph-status">${esc(d.chart_status || coin.status || "")}</div>
        </div>`;
        wrap.dataset.empty = key;
        lastChartKey = key;
        const st = document.getElementById("ph-status");
        if (st && st.classList.contains("is-long")) {
          st.addEventListener("click", () => st.classList.toggle("is-open"));
        }
      }
      return;
    }
    const has = d.candles && d.candles.length > 1;
    const open = (d.open && d.open[0]) || {};
    const key = ((d.coin && d.coin.mint) || "") + "|" + (d.tf || selectedTf || "") + "|" + (has ? d.candles.length : 0) + "|" + (has ? d.candles[d.candles.length - 1].t || d.candles[d.candles.length - 1][0] : "") + "|" + (open.timer_left != null ? Math.round(open.timer_left) : "") + "|" + (open.peak || "") + "|" + ((open.levels && open.levels.trail_active) || open.trail_active || "");
    if (has) {
      let canvas = document.getElementById("chart");
      if (!canvas) {
        wrap.innerHTML = `<canvas id="chart"></canvas>`;
        canvas = document.getElementById("chart");
        lastChartKey = "";
        delete wrap.dataset.empty;
      }
      if (canvas && key !== lastChartKey) {
        drawChart(canvas, d.candles, d);
        lastChartKey = key;
      }
    } else {
      const msg = "Chart wird geladen… " + (d.chart_status || (d.coin && d.coin.status) || "");
      if (wrap.dataset.empty !== msg) {
        wrap.innerHTML = `<div class="chart-empty"></div>`;
        wrap.querySelector(".chart-empty").textContent = msg;
        wrap.dataset.empty = msg;
        lastChartKey = key;
      }
    }
  }

  function render() {
    const root = document.getElementById("app") || document.body;
    if (error && !desk) {
      root.innerHTML = `<div class="err">${esc(error)}</div>`;
      return;
    }
    const d = desk || {};
    const mode = String(d.mode || "paper").toLowerCase();
    const coin = d.coin || {};
    const rules = d.rules || { tp: [4, 10, 20], trail: 40, stop: 25, timer: 75 };
    const cash = d.pot_cash != null ? d.pot_cash : (d.pot_start != null ? d.pot_start : 100);
    const equity = d.equity != null ? d.equity : cash;
    const start = d.pot_start != null ? d.pot_start : 100;
    const pnl = d.pnl_total != null ? d.pnl_total : (equity - start);
    const openPos = hasOpen(d);
    let unreal = d.unrealized;
    if (unreal == null && openPos) {
      unreal = (d.open || []).reduce((a, o) => a + (o && o.pnl != null ? Number(o.pnl) : 0), 0);
    }
    if (!openPos) unreal = 0;
    // While a trade is open the big Balance tracks mark-to-market equity (cash + position value).
    // Once flat, Balance is the realized cash book.
    const balance = openPos ? equity : cash;
    const up = equity >= start;
    const phaseLine = d.phase_line || ((d.open && d.open[0] && d.open[0].phase_line) ? d.open[0].phase_line : "PHASE: SCANNING");
    rememberImgs(coin);
    const nm = coin.symbol || coin.name || "—";
    const img = avatarHtml(coin);
    const ch = coin.ch24;
    const chCls = ch == null ? "" : ch >= 0 ? "up" : "dn";
    const chTxt = ch == null ? "" : (ch >= 0 ? "+" : "") + Number(ch).toFixed(1) + "%";
    const rejects = (d.rejects || []).slice(0, 8).map((r) => `<span>${esc(r.label)} ${esc(r.n)}</span>`).join("");
    const open = (d.open || [])[0];
    const openHtml = open ? `<div class="openbanner">Offen: <b>${esc(open.symbol || open.name || "")}</b>
      · ${money(open.size)} · ${open.pct != null ? (open.pct >= 0 ? "+" : "") + Number(open.pct).toFixed(1) + "%" : "—"}
      · Timer ${open.timer_left != null ? open.timer_left + " min" : "—"}
      · TP ${rules.tp.map((x) => Number(x).toFixed(0) + "x").join("/")}</div>` : "";
    const statusLine = (d.chart_status || coin.status || "") + (d.checked && d.checked.mint && d.checked.mint !== coin.mint ? " · zuletzt geprüft: " + (d.checked.symbol || d.checked.name || "") + " · " + (d.checked.status || "") : "");
    rememberMc(coin);
    const metricsHtml = `${mcMetric(coin)}
            <span>LIQ <b>${compact(coin.liq)}</b></span>
            <span>24H VOL <b>${compact(coin.vol24)}</b></span>
            <span>PX <b>${coin.px != null ? (coin.px >= 1 ? money(coin.px) : "$" + Number(coin.px).toPrecision(4)) : "—"}</b> <b class="${chCls}">${esc(chTxt)}</b></span>`;
    const subHtml = `<span class="${up ? "up" : "dn"}">${Number(d.multiple || (equity / start) || 1).toFixed(2)}x</span>
            <span>${d.trades_n || 0} trades</span>
            <span class="up">${d.wins || 0}W</span>
            <span class="dn">${d.losses || 0}L</span>
            <span>Start ${money(start)} · PnL <span class="${pnl >= 0 ? "up" : "dn"}">${moneySign(pnl)}</span></span>`
      + (openPos ? `<span>uPnL <span class="${unreal >= 0 ? "up" : "dn"}">${moneySign(unreal)}</span></span>` : "");

    if (!document.getElementById("desk-root")) {
      root.innerHTML = `
      <div id="desk-root">
      <div class="topbar">
        <div class="brand">olli81</div>
        <div class="top-right">
          <span class="mode-badge paper" id="pill-mode">PAPER</span>
          <span class="pill" id="pill-live"><span class="dot" id="live-dot"></span><span id="live-lbl">Working</span> <span class="clock" id="clock"></span></span>
        </div>
      </div>
      <div id="stale-banner" class="stale-banner"></div>
      <div class="hero">
        <div>
          <div class="balance-lbl">Balance</div>
          <div class="balance" id="bal"></div>
          <div class="substats" id="substats"></div>
        </div>
        <div class="coin-av" id="hero-av"></div>
        <div class="equity-card">
          <div class="row"><span>Equity</span><span class="eq" id="eq-val"></span></div>
          <div class="row eq-unreal" id="eq-unreal"></div>
          <div id="eq-spark"></div>
        </div>
      </div>
      <div class="chart-card">
        <div class="phase-bar" id="phase-bar">PHASE: SCANNING</div>
        <div class="chart-head">
          <div class="chart-title"><span id="chart-name"></span><span id="chart-meta"></span>
            <div class="chart-status" id="chart-status"></div>
          </div>
          <div class="chart-tools">
            <div class="tf-sel" id="tf-sel">
              <button type="button" data-tf="1m">1m</button>
              <button type="button" data-tf="5m">5m</button>
              <button type="button" data-tf="15m">15m</button>
            </div>
            <div class="metrics" id="metrics"></div>
          </div>
        </div>
        <div class="rules" id="rules"></div>
        <div id="open-slot"></div>
        <div id="chart-wrap"></div>
      </div>
      <section class="agents-band" id="agents-stage"></section>
      <div class="bottom">
        <section class="panel journal-panel">
          <h2>Journal <em>Decision vault</em></h2>
          <div class="rejects" id="rejects"></div>
          <div class="jlist" id="jlist"></div>
        </section>
        <section class="panel" id="trades-panel">
          <div class="trade-head">
            <h2>Trades</h2>
            <div class="trade-tabs" id="trade-tabs">
              <button type="button" data-tab="open">OPEN</button>
              <button type="button" data-tab="closed">CLOSED</button>
            </div>
          </div>
          <div class="trade-sum" id="trade-sum"></div>
          <div class="tlist" id="tlist"></div>
        </section>
      </div>
      </div>`;
      bindUi();
    }

    const pillMode = document.getElementById("pill-mode");
    if (pillMode) {
      const live = mode === "live";
      pillMode.textContent = live ? "LIVE" : "PAPER";
      pillMode.className = "mode-badge " + (live ? "live" : "paper");
    }
    const liveDot = document.getElementById("live-dot");
    if (liveDot) liveDot.style.color = liveFresh() ? "var(--green)" : "var(--dim)";
    const clk = document.getElementById("clock");
    if (clk) clk.textContent = clockNow();
    const stale = document.getElementById("stale-banner");
    if (stale) {
      const msg = staleText();
      stale.textContent = msg;
      stale.className = "stale-banner" + (msg ? " show" : "");
    }
    const bal = document.getElementById("bal");
    if (bal) bal.textContent = money(balance);
    const sub = document.getElementById("substats");
    if (sub) sub.innerHTML = subHtml;
    const av = document.getElementById("hero-av");
    if (av && av.dataset.mint !== (coin.mint || "") + "|" + imgList(coin).join(" ")) {
      av.innerHTML = img;
      av.dataset.mint = (coin.mint || "") + "|" + imgList(coin).join(" ");
    }
    const eq = document.getElementById("eq-val");
    if (eq) {
      eq.textContent = money(equity);
      eq.style.color = up ? "var(--green)" : "var(--red)";
    }
    const eu = document.getElementById("eq-unreal");
    if (eu) {
      if (openPos) {
        eu.innerHTML = `<span>uPnL</span><span class="${unreal >= 0 ? "up" : "dn"}">${moneySign(unreal)}</span>`;
        eu.style.display = "";
      } else {
        eu.innerHTML = "";
        eu.style.display = "none";
      }
    }
    const sparkEl = document.getElementById("eq-spark");
    if (sparkEl) sparkEl.innerHTML = spark(d.equity_curve, up);
    const cn = document.getElementById("chart-name");
    if (cn) cn.textContent = coin.name || coin.symbol || "Kein Coin";
    const cm = document.getElementById("chart-meta");
    if (cm) cm.textContent = hasOpen(d) ? (" " + (coin.symbol || "") + " · " + (d.tf || selectedTf || "1m")) : (" " + (coin.symbol || ""));
    const tfSel = document.getElementById("tf-sel");
    if (tfSel) tfSel.style.display = hasOpen(d) ? "" : "none";
    const cs = document.getElementById("chart-status");
    if (cs) cs.textContent = statusLine;
    const met = document.getElementById("metrics");
    if (met) met.innerHTML = metricsHtml;
    const rulesEl = document.getElementById("rules");
    if (rulesEl) rulesEl.innerHTML = `<code>TP ${rules.tp.map((x) => Number(x).toFixed(0) + "x").join("/")}</code>
          <code>Trail −${Number(rules.trail).toFixed(0)}%</code>
          <code>Stop −${Number(rules.stop).toFixed(0)}%</code>
          <code>${Number(rules.timer).toFixed(0)} min timer</code>`;
    const openSlot = document.getElementById("open-slot");
    if (openSlot) openSlot.innerHTML = openHtml;
    const phaseEl = document.getElementById("phase-bar");
    if (phaseEl) phaseEl.textContent = phaseLine;
    document.querySelectorAll("#tf-sel button").forEach((b) => {
      b.className = b.getAttribute("data-tf") === selectedTf ? "on" : "";
    });
    if ((d.open && d.open.length) && !localStorage.getItem("desk_trades_tab")) {
      tradesTab = "open";
    }
    document.querySelectorAll("#trade-tabs button").forEach((b) => {
      b.className = b.getAttribute("data-tab") === tradesTab ? "on" : "";
    });
    paintChart(d);
    const rej = document.getElementById("rejects");
    if (rej) { rej.innerHTML = rejects; rej.style.display = rejects ? "" : "none"; }
    const jl = document.getElementById("jlist");
    if (jl) jl.innerHTML = journalRows(d);
    const ts = document.getElementById("trade-sum");
    if (ts) ts.innerHTML = `<div><div class="hint">Balance ${money(cash)} · start ${money(start)}</div><div class="big">${money(equity)}</div></div><div class="hint">PnL <span class="${pnl >= 0 ? "pnl up" : "pnl dn"}">${moneySign(pnl)}</span></div>`;
    const tl = document.getElementById("tlist");
    if (tl) tl.innerHTML = tradesTab === "open" ? openRows(d) : tradeRows(d);
    syncAgents(d);
  }

  function bindUi() {
    if (uiBound) return;
    uiBound = true;
    const tfSel = document.getElementById("tf-sel");
    if (tfSel) {
      tfSel.addEventListener("click", (ev) => {
        const btn = ev.target.closest("button[data-tf]");
        if (!btn) return;
        const tf = btn.getAttribute("data-tf");
        if (tf === selectedTf) return;
        selectedTf = tf;
        localStorage.setItem("desk_tf", tf);
        lastChartKey = "";
        document.querySelectorAll("#tf-sel button").forEach((b) => {
          b.className = b.getAttribute("data-tf") === tf ? "on" : "";
        });
        const dp = dataPath();
        const mint = desk && desk.coin && desk.coin.mint;
        if (liveOrigin && dp && mint && hasOpen(desk)) pullChart(liveOrigin, dp, mint, true);
      });
    }
    const tabs = document.getElementById("trade-tabs");
    if (tabs) {
      tabs.addEventListener("click", (ev) => {
        const btn = ev.target.closest("button[data-tab]");
        if (!btn) return;
        tradesTab = btn.getAttribute("data-tab") === "open" ? "open" : "closed";
        localStorage.setItem("desk_trades_tab", tradesTab);
        document.querySelectorAll("#trade-tabs button").forEach((b) => {
          b.className = b.getAttribute("data-tab") === tradesTab ? "on" : "";
        });
        const tl = document.getElementById("tlist");
        if (tl && desk) tl.innerHTML = tradesTab === "open" ? openRows(desk) : tradeRows(desk);
      });
    }
  }

  function tickClock() {
    const el = document.getElementById("clock");
    if (el) el.textContent = clockNow();
    const stale = document.getElementById("stale-banner");
    if (stale) {
      const msg = staleText();
      stale.textContent = msg;
      stale.className = "stale-banner" + (msg ? " show" : "");
    }
    const liveDot = document.getElementById("live-dot");
    if (liveDot) liveDot.style.color = liveFresh() ? "var(--green)" : "var(--dim)";
    if (desk && desk.open && desk.open[0] && desk.open[0].opened_at && desk.rules) {
      const open = desk.open[0];
      const timer = Number((desk.rules && desk.rules.timer) || 75);
      const t0 = Date.parse(open.opened_at);
      if (isFinite(t0)) {
        open.timer_left = Math.max(0, timer - (Date.now() - t0) / 60000);
        if (open.phase === "PRE-TP1") {
          const sl = Number((desk.rules && desk.rules.stop) || 25);
          const tp1 = ((desk.rules && desk.rules.tp) || [4])[0];
          open.phase_line = "PHASE: PRE-TP1 | SL: -" + sl + "% | TP1: " + tp1 + "x | TIMER: " + Math.round(open.timer_left) + "m";
          desk.phase_line = open.phase_line;
          const phaseEl = document.getElementById("phase-bar");
          if (phaseEl) phaseEl.textContent = open.phase_line;
        }
      }
      lastChartKey = "";
      const canvas = document.getElementById("chart");
      if (canvas && desk.candles) drawChart(canvas, desk.candles, desk);
    }
  }

  async function pullChart(origin, dp, mint, force) {
    if (!hasOpen(desk)) {
      if (desk) { desk.candles = []; desk._chartMintDirty = false; }
      return;
    }
    if (!origin || !dp || !mint || (chartInFlight && !force)) return;
    const pullKey = mint + ":" + (selectedTf || "1m");
    if (!force && desk.candles && desk.candles.length >= 2 && lastChartPullKey === pullKey && (Date.now() - lastChartPullAt) < 20000) return;
    chartInFlight = true;
    lastChartPullKey = pullKey;
    lastChartPullAt = Date.now();
    try {
      const cr = await fetchTimeout(`${origin}/d/${encodeURIComponent(dp)}/chart?mint=${encodeURIComponent(mint)}&tf=${encodeURIComponent(selectedTf)}&ts=${Date.now()}`, 8000);
      if (cr.ok) {
        const cj = await cr.json();
        if (cj && cj.candles && cj.candles.length >= 2) {
          desk.candles = cj.candles;
          desk.tf = cj.tf || selectedTf || desk.tf;
          if (cj.market) {
            const m = cj.market;
            desk.coin = mergeCoin(desk.coin, {
              name: m.name || desk.coin.name, symbol: m.symbol || desk.coin.symbol,
              image: m.image, images: m.images, mc_src: m.mc_src || desk.coin.mc_src
            });
            if (posNum(m.px) || m.px === 0) desk.coin.px = m.px;
            if (posNum(m.mc)) { desk.coin.mc = m.mc; if (m.mc_src) desk.coin.mc_src = m.mc_src; }
            if (posNum(m.liq)) desk.coin.liq = m.liq;
            if (posNum(m.vol24)) desk.coin.vol24 = m.vol24;
            if (m.ch24 != null) desk.coin.ch24 = m.ch24;
            rememberMc(desk.coin);
          }
          lastGoodChart = { candles: desk.candles, coin: desk.coin, tf: desk.tf, chart_status: desk.chart_status };
          paintChart(desk);
          const cn = document.getElementById("chart-name");
          if (cn) cn.textContent = desk.coin.name || desk.coin.symbol || "Kein Coin";
          const met = document.getElementById("metrics");
          if (met) {
            const coin = desk.coin || {};
            const ch = coin.ch24;
            const chCls = ch == null ? "" : ch >= 0 ? "up" : "dn";
            const chTxt = ch == null ? "" : (ch >= 0 ? "+" : "") + Number(ch).toFixed(1) + "%";
            met.innerHTML = `${mcMetric(coin)}<span>LIQ <b>${compact(coin.liq)}</b></span><span>24H VOL <b>${compact(coin.vol24)}</b></span><span>PX <b>${coin.px != null ? (coin.px >= 1 ? money(coin.px) : "$" + Number(coin.px).toPrecision(4)) : "—"}</b> <b class="${chCls}">${esc(chTxt)}</b></span>`;
          }
        }
      }
    } catch (e) { /* keep last candles, never block UI */ }
    finally {
      chartInFlight = false;
      if (desk) desk._chartMintDirty = false;
    }
  }

  async function pollLive() {
    if (window.__DESK_PREVIEW__) return;
    if (pollBusy) return;
    if (Date.now() < liveBackoffUntil) return;
    const dp = dataPath();
    if (!dp) return;
    pollBusy = true;
    try {
      const origin = await discoverLiveOrigin();
      if (!origin) {
        liveOk = false;
        liveFails += 1;
        liveBackoffUntil = Date.now() + Math.min(30000, 4000 * Math.pow(2, Math.min(liveFails, 3)));
        return;
      }
      const r = await fetchTimeout(`${origin}/d/${encodeURIComponent(dp)}/live?ts=${Date.now()}`, 8000);
      if (!r.ok) throw new Error("live " + r.status);
      const tick = await r.json();
      liveOk = true; liveLast = Date.now(); liveFails = 0; liveBackoffUntil = 0;
      applyTick(tick);
      render();
      if (desk && hasOpen(desk)) {
        const mint = desk.open[0].mint;
        if (mint) pullChart(origin, dp, mint, desk._chartMintDirty);
      }
    } catch (e) {
      liveOk = false;
      liveFails += 1;
      liveBackoffUntil = Date.now() + Math.min(30000, 4000 * Math.pow(2, Math.min(liveFails, 3)));
    } finally {
      pollBusy = false;
    }
  }

  window.addEventListener("resize", () => {
    if (desk && desk.candles) {
      lastChartKey = "";
      const canvas = document.getElementById("chart");
      if (canvas) drawChart(canvas, desk.candles, desk);
    }
  });
  setInterval(tickClock, 1000);
  setInterval(load, 60 * 1000);
  (function pollLoop() {
    const ms = (desk && hasOpen(desk)) ? 3000 : 5000;
    setTimeout(async () => {
      try { await pollLive(); } finally { pollLoop(); }
    }, ms);
  })();
  if (window.__DESK_PREVIEW__) {
    desk = window.__DESK_PREVIEW__;
    liveOk = true;
    liveLast = Date.now();
    stateFreshAt = Date.now();
    render();
    syncAgents(desk);
  } else {
    load().then(pollLive);
  }
})();

