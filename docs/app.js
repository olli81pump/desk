(function () {
  const LS_KEY = "desk_data_path";
  const POLL_MS = 60 * 1000;

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
  let emptyFixture = false;

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
    root.innerHTML = `<div style="padding:24px 16px;font:17px -apple-system,system-ui;color:#fff">
      <div style="font-size:22px;font-weight:600;margin-bottom:8px">Zugang einrichten</div>
      <div style="color:rgba(235,235,245,.6);margin-bottom:16px">Füge den Zugangscode aus dem Grok-Bot-Chat ein. Das ist nur einmal nötig.</div>
      <input id="dpIn" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Zugangscode"
        style="width:100%;box-sizing:border-box;height:48px;border-radius:12px;border:0;background:#1c1c1e;color:#fff;padding:0 14px;font:16px ui-monospace,monospace">
      <button id="dpBtn" style="margin-top:12px;width:100%;height:50px;border-radius:14px;border:0;background:#00d35a;color:#000;font:600 17px -apple-system,system-ui">Speichern</button>
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
    if (q.get("fixture") === "empty") {
      emptyFixture = true;
      state = emptyState();
      error = null;
      render();
      return;
    }
    if (q.get("fixture") === "error") {
      state = null;
      error = "state.json konnte nicht geladen werden.";
      render();
      return;
    }
    const dp = dataPath();
    if (!dp) {
      state = null;
      error = null;
      showPathPrompt();
      return;
    }
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
      mode: "PAPER", balance: 200, stack: 200, fomo_handle: "olli81",
      signup_url: "https://fomo.family/r/olli81",
      profile_url: "https://fomo.family/profile/olli81?r=olli81",
      notifier: "telegram",
      notifier_note: "Web-Push ist in Plan B nicht verfügbar. Meldungen kommen über Telegram.",
      settings: { stop_pct: 6, trail_pct: 12, stack_pct: 8, analyst_mode: "rules", mode: "PAPER" },
      positions: [], activity: [], waiting: [], coins: {},
      agents: {
        scanner: { name: "Scanner", card: "0 pools", sub: "0 passed · 0 killed", feed: [] },
        auditor: { name: "Auditor", card: "0 taken apart", sub: "idle", latest: null },
        analyst: { name: "Analyst", card: "Scoring", sub: "mode rules · 0 scored", min_score: 70, last: null },
        executor: { name: "Executor", card: "0 trades", sub: "8% of stack" },
        risk: { name: "Risk", card: "Idle", sub: "No exits yet", pills: { stop: "stop -6%", trail: "trail 12%" } }
      }
    };
  }

  function el(html) {
    const d = document.createElement("div");
    d.innerHTML = html.trim();
    return d.firstElementChild;
  }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function money(n) {
    const x = Number(n);
    if (!Number.isFinite(x)) return "—";
    const sign = x < 0 ? "-" : "";
    return sign + "$" + Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function coinA(c, label) {
    const href = (c && (c.link || c.coin_url)) || (typeof c === "string" ? c : "#");
    const text = label || (c && (c.name || c.symbol || c.mint)) || "coin";
    return `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(text)}</a>`;
  }

  function shell(inner, tab) {
    const mode = (state && state.mode) || "PAPER";
    return `
      <header class="top">
        <div class="brand">Grok Bot Desk <span>· ${esc(mode)}</span></div>
        <div class="badge">${esc(mode)}</div>
      </header>
      <div class="pad">${inner}</div>
      <div class="tabs"><nav>
        <button data-go="/home" class="${tab==="home"?"on":""}">Home</button>
        <button data-go="/agents" class="${tab==="agents"||tab==="auditor"||tab==="coin"?"on":""}">Agents</button>
        <button data-go="/account" class="${tab==="account"?"on":""}">Account</button>
      </nav></div>`;
  }

  function viewHome() {
    if (!state) return "";
    const pos = state.positions || [];
    const act = state.activity || [];
    let positions = `<div class="empty">Keine offenen Positionen.</div>`;
    if (pos.length) {
      positions = pos.map((p) => `
        <div class="card pos">
          <div>
            <div class="name">${coinA(p)}</div>
            <div class="meta">entry ${esc(p.entry_price)} · ${money(p.size_usd)} · stop -${esc(p.stop_pct)}%</div>
          </div>
          <a class="btn sell" href="${esc(p.link)}" target="_blank" rel="noopener">Sell on FOMO</a>
        </div>`).join("");
    }
    let feed = `<div class="empty">Noch keine Aktivität.</div>`;
    if (act.length) {
      feed = `<div class="card">${act.map((a) => {
        const tone = a.tone === "kill" ? "kill" : (a.tone === "bad" ? "bad" : (a.tone === "good" || a.tone === "pass" || a.tone === "buy" ? "good" : ""));
        return `<div class="row ${tone}">
          <div class="title">${a.link ? coinA({link:a.link,name:a.title}) : esc(a.title)}
            <div class="sub">${esc(a.agent || "")}${a.detail ? " · " + esc(a.detail) : ""}</div>
          </div>
          <div class="right">${esc(a.right || "")}</div>
        </div>`;
      }).join("")}</div>`;
    }
    return `
      <div class="hero">
        <div class="kicker">${esc(state.mode)} · Stack</div>
        <div class="balance">${money(state.balance)}</div>
        <div class="muted">${esc(state.fomo_handle || "olli81")}</div>
        ${state.ticket_warning ? `<div class="warn">${esc(state.ticket_warning)}</div>` : ""}
      </div>
      <div class="section"><h2>Positionen</h2></div>
      ${positions}
      <div class="section"><h2>Aktivität</h2></div>
      ${feed}`;
  }

  function viewAgents() {
    const A = (state && state.agents) || {};
    const cards = ["scanner","auditor","analyst","executor","risk"].map((k) => {
      const a = A[k] || { name: k };
      const go = k === "auditor" ? "/auditor" : (k === "scanner" ? "/agents" : "/agents");
      const pills = a.pills ? `<div class="pills">
        <span class="pill stop">${esc(a.pills.stop)}</span>
        <span class="pill trail">${esc(a.pills.trail)}</span>
      </div>` : "";
      let feed = "";
      if (a.feed && a.feed.length) {
        feed = a.feed.slice(0, 8).map((f) => `
          <div class="row ${f.verdict==="kill"?"kill":""}">
            <div class="title">${coinA(f, f.name || f.symbol)}
              <div class="sub">${f.verdict==="pass" ? "liq " + esc(f.liq) + " · → auditor" : esc(f.reason||"")}</div>
            </div>
            <div class="right">${esc(f.verdict==="kill"?f.reason:"→ auditor")}</div>
          </div>`).join("");
        feed = `<div style="margin-top:8px">${feed}</div>`;
      } else if (k === "scanner") {
        feed = `<div class="empty" style="margin-top:8px;padding:16px">Keine Pools in der Warteschlange.</div>`;
      }
      const score = k === "analyst" && a.last ? ring(a.last.score, a.min_score || 70) : "";
      return `<div class="card agent" data-go="${k==="auditor"?"/auditor":k==="analyst"?"/agents":"/agents"}">
        <div class="head"><div class="n">${esc(a.name)}</div><div class="muted">${a.paused?"pausiert":""}</div></div>
        <div class="card-n">${esc(a.card || "")}</div>
        <div class="muted">${esc(a.sub || "")}</div>
        ${score}${pills}${feed}
      </div>`;
    }).join("");
    return `<h1 class="screen">Agents</h1><div class="agent-grid">${cards}</div>`;
  }

  function ring(score, min) {
    const s = Number(score) || 0;
    const c = 2 * Math.PI * 36;
    const dash = c * Math.min(s, 100) / 100;
    const col = s >= min ? "#3ee08a" : "#3ee0d4";
    return `<div class="ring-wrap"><svg width="96" height="96" viewBox="0 0 96 96">
      <circle cx="48" cy="48" r="36" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="8"/>
      <circle cx="48" cy="48" r="36" fill="none" stroke="${col}" stroke-width="8"
        stroke-dasharray="${dash} ${c}" stroke-linecap="round" transform="rotate(-90 48 48)"/>
      <text x="48" y="53" text-anchor="middle" fill="#eef1f6" font-size="20" font-weight="650">${s}</text>
    </svg></div>`;
  }

  function viewAuditor(mint) {
    const latest = (state && (mint && state.coins && state.coins[mint] && state.coins[mint].audit)) || (state && state.latest_audit);
    const layers = (latest && latest.layers) || [];
    let body;
    if (!latest || !layers.length) {
      body = `<div class="empty">Noch kein Audit. Der Auditor nimmt Münzen auseinander, sobald der Scanner sie durchlässt.</div>`;
    } else {
      const grid = layers.map((L) => {
        const cls = L.pass === true ? "ok" : (L.pass === false ? "red" : "grey");
        return `<div class="layer ${cls}"><div class="n">${esc(L.n)}. ${esc(L.name)}</div><div class="v">${esc(L.value)}</div></div>`;
      }).join("");
      const head = latest.passed ? "8/8 → Executor" : (latest.reason || "red");
      body = `<div class="card">
        <div class="kicker">${latest.link ? coinA(latest, latest.name || latest.mint) : esc(latest.mint||"")}</div>
        <div class="card-n">${esc(head)}</div>
        <div class="muted">${latest.holders != null ? esc(latest.holders) + " holders" : ""}</div>
        <div class="layers">${grid}</div>
      </div>`;
    }
    return `<button class="back" data-go="/agents">← Agents</button>
      <h1 class="screen">Auditor</h1>${body}`;
  }

  function viewCoin(mint) {
    const c = state && state.coins && state.coins[mint];
    if (!c) {
      return `<button class="back" data-go="/home">← Home</button>
        <h1 class="screen">Coin</h1><div class="empty">Diese Münze kenne ich noch nicht.</div>`;
    }
    const pos = c.position;
    const stop = pos && pos.trail_active;
    return `<button class="back" data-go="/home">← Home</button>
      <h1 class="screen">${esc(c.name || c.symbol || mint)}</h1>
      <div class="muted" style="margin-bottom:10px">${coinA(c, c.symbol || mint)} · ${esc(mint)}</div>
      <canvas class="chart" id="chart" width="358" height="160"></canvas>
      <div class="legend">${stop || (pos) ? `<span><i class="swatch"></i>Risk trailing stop</span>` : ""}</div>
      ${pos ? `<div class="card pos" style="margin-top:12px">
        <div><div class="name">Open · stop -${esc(pos.stop_pct)}%</div>
        <div class="meta">entry ${esc(pos.entry_price)} · ${money(pos.size_usd)}</div></div>
        <a class="btn sell" href="${esc(pos.link)}" target="_blank" rel="noopener">Sell on FOMO</a>
      </div>` : ""}
      <div class="section"><h2>Auditor</h2></div>
      ${c.audit && c.audit.layers ? `<div class="layers">${c.audit.layers.map((L)=>{
        const cls = L.pass===true?"ok":(L.pass===false?"red":"grey");
        return `<div class="layer ${cls}"><div class="n">${esc(L.n)}. ${esc(L.name)}</div><div class="v">${esc(L.value)}</div></div>`;
      }).join("")}</div>` : `<div class="empty">Kein Audit.</div>`}`;
  }

  function viewAccount() {
    const s = (state && state.settings) || {};
    const keys = Object.keys(s).sort();
    const rows = keys.map((k) => `<div class="setting"><div class="k">${esc(k)}</div><div class="v">${esc(s[k])}</div></div>`).join("");
    return `<h1 class="screen">Account</h1>
      <div class="card">
        <div class="kicker">Notifier</div>
        <div class="card-n">Telegram</div>
        <div class="muted">${esc((state && state.notifier_note) || "Web-Push ist in Plan B nicht verfügbar. Meldungen kommen über Telegram.")}</div>
        <div style="margin-top:10px">${state && state.profile_url ? `<a href="${esc(state.profile_url)}" target="_blank" rel="noopener">FOMO-Profil ${esc(state.fomo_handle)}</a>` : ""}</div>
        <div style="margin-top:6px">${state && state.signup_url ? `<a href="${esc(state.signup_url)}" target="_blank" rel="noopener">${esc(state.signup_url)}</a>` : ""}</div>
        <div class="muted" style="margin-top:8px">Einstellungen sind hier nur lesbar. Ändern geht per Telegram, z. B. set stop to -8%.</div>
      </div>
      <div class="section"><h2>Settings</h2></div>
      <div class="card">${rows || `<div class="empty">Keine Settings geladen.</div>`}</div>`;
  }

  function drawChart() {
    const cnv = document.getElementById("chart");
    if (!cnv || !state) return;
    const { route, mint } = parseHash();
    const c = state.coins && state.coins[mint];
    const ctx = cnv.getContext("2d");
    const w = cnv.width, h = cnv.height;
    ctx.clearRect(0, 0, w, h);
    const pts = (c && c.prices) || [];
    if (pts.length < 2) {
      ctx.fillStyle = "#5c6478";
      ctx.fillText("Noch keine Kerzen.", 16, h/2);
      return;
    }
    const prices = pts.map((p) => Number(p.price)).filter(Number.isFinite);
    let lo = Math.min(...prices), hi = Math.max(...prices);
    if (lo === hi) { lo *= 0.99; hi *= 1.01; }
    const pos = c.position;
    const entry = pos && Number(pos.entry_price);
    const stopPct = pos && Number(pos.stop_pct);
    const trail = pos && pos.trail_active && pos.peak_price != null
      ? Number(pos.peak_price) * (1 - (Number(state.settings && state.settings.trail_pct) || 12) / 100)
      : (entry && stopPct != null ? entry * (1 - stopPct / 100) : null);
    const xs = (i) => 8 + (i / (pts.length - 1)) * (w - 16);
    const ys = (p) => 10 + (1 - (p - lo) / (hi - lo)) * (h - 20);
    ctx.strokeStyle = "#3ee0d4";
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    prices.forEach((p, i) => { const x = xs(i), y = ys(p); i ? ctx.lineTo(x,y) : ctx.moveTo(x,y); });
    ctx.stroke();
    if (trail != null && Number.isFinite(trail)) {
      ctx.strokeStyle = "#ff9f43";
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(8, ys(trail));
      ctx.lineTo(w - 8, ys(trail));
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

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
    else if (route === "auditor") inner = viewAuditor(mint);
    else if (route === "coin") inner = viewCoin(mint);
    else if (route === "account") inner = viewAccount();
    else inner = viewHome();
    root.innerHTML = shell(inner, tab);
    bind(root);
    if (route === "coin") requestAnimationFrame(drawChart);
  }

  function bind(root) {
    root.querySelectorAll("[data-go]").forEach((b) => {
      b.addEventListener("click", (e) => { e.preventDefault(); go(b.getAttribute("data-go")); });
    });
  }

  window.addEventListener("hashchange", () => {
    const h = parseHash();
    if (h.data) localStorage.setItem(LS_KEY, h.data);
    render();
  });
  load();
  setInterval(load, POLL_MS);
})();
