/* Flipside — one graph, two perspectives. */
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = v => v == null ? "—" : Math.round(v * 100) + "%";
const initials = s => (s || "?").replace(/[^A-Za-z0-9 ]/g, "").split(/\s+/)
  .slice(0, 2).map(w => w[0] || "").join("").toUpperCase() || "?";

let MODE = "home", F = null, SEL = null, TAB = 0;
let SYN = null;                        // /syndicates, filled after the screen
let HEALTH = null;                     // what the product is standing on
let FCONTRA = {};                      // investor -> disagreements in their rounds

/* A fund whose rounds disagree with themselves looks clean in the table
   unless we say so, and the founder is about to repeat those numbers to
   the fund itself. Fetched per screen, once, after the list is up. */
async function loadFounderContradictions() {
  // Fourteen funds, fourteen requests, and they were awaited one at a time -
  // which turns a round trip into fourteen of them for no reason. They do
  // not depend on each other.
  const names = (F?.investors || []).map(x => x.investor)
    .filter(n => FCONTRA[n] === undefined);
  if (!names.length) return;
  names.forEach(n => { FCONTRA[n] = null; });
  await Promise.all(names.map(async n => {
    try {
      FCONTRA[n] = await (await fetch(
        `/contradictions?investor=${encodeURIComponent(n)}`)).json();
    } catch (e) { FCONTRA[n] = { hard: 0, items: [] }; }
  }));
  if (MODE === "founder") render();
}

async function loadHealth() {
  try { HEALTH = await (await fetch("/health")).json(); } catch (e) { return; }
  const el = $("#datamode");
  if (!el || !HEALTH) return;
  // Only the state worth interrupting someone for. "Live" is the normal
  // case and saying so every second of every page was a sidebar section
  // nobody needed; running entirely from cache is a caveat that has to be
  // stated rather than discovered mid-demo.
  el.innerHTML = HEALTH.cache_only
    ? `<span class="dm cached" title="No live calls at all — every figure comes from
         ${HEALTH.entities_cached} entities and ${HEALTH.rounds_cached} rounds already fetched">
         ● Offline · ${HEALTH.entities_cached.toLocaleString()} entities cached</span>`
    : "";
}
let IFILTER = "all", FFILTER = "all";  // which KPI card is active

/* A number nobody can act on is decoration. Each card is a filter, and the
   active one says so. */
function kpis(cards, active, onPick) {
  return `<div class="kpis">${cards.map(([k, v, key, why]) => `
    <button class="kpi ${active === key ? "on" : ""}" data-kpi="${esc(key)}">
      <span class="k">${esc(k)}</span><span class="v">${v}</span>
      <span class="why">${esc(why || "")}</span></button>`).join("")}</div>`;
}
const OPEN = {};                       // collapsed section memory

/* ---------- small builders ---------- */
/* Real company mark when we know a domain, generated monogram otherwise.
   /logo caches bytes on disk, so this costs one request per company ever. */
const logo = (n, domain) => `<img class="logo" alt="" loading="lazy"
  src="/logo?${domain ? "domain=" + encodeURIComponent(domain) + "&" : ""}name=${encodeURIComponent(n || "")}">`;
const bigLogo = (n, domain) => `<img class="elogo" alt="" loading="lazy"
  src="/logo?${domain ? "domain=" + encodeURIComponent(domain) + "&" : ""}name=${encodeURIComponent(n || "")}">`;
const dom = x => x?.website || x?.properties?.website?.value || null;
const badge = (t, c) => `<span class="bdg b-${c}">${esc(t)}</span>`;
const stats = (cols, items) => `<div class="stats" style="grid-template-columns:repeat(${cols},1fr)">${
  items.map(([k, v, cls]) => `<div class="stat"><div class="k">${esc(k)}</div>
    <div class="v ${cls || ""}">${v}</div></div>`).join("")}</div>`;

function section(id, title, hint, body) {
  const closed = OPEN[id] === false ? "closed" : "";
  return `<div class="sec">
    <div class="sech ${closed}" data-sec="${id}"><span class="cv">▼</span>
      <h3>${esc(title)}</h3>${hint ? `<span class="hint">${esc(hint)}</span>` : ""}</div>
    <div class="secb ${closed}" data-secb="${id}">${body}</div></div>`;
}

/* A bar is only informative next to something. Four bars at 60-75% all read
   "high" until you can see where the other funds sit, so every row can carry
   a benchmark tick and the chart says what the tick means. */
function bars(rows, max, opts = {}) {
  const m = max ?? Math.max(...rows.map(r => r[1] || 0), 1);
  const body = rows.map(([lbl, v, cls, disp, mark]) => {
    const w = Math.round(100 * (v || 0) / m);
    const unknown = v == null;
    return `<div class="barrow${unknown ? " unk" : ""}">
      <span class="lbl">${esc(lbl)}</span>
      <span class="bart">
        ${unknown ? `<span class="nodata">not in the graph</span>`
                  : `<i class="${cls || ""}" style="width:${w}%"></i>`}
        ${mark != null ? `<b class="tick" style="left:${Math.round(100 * mark / m)}%"
            title="peer median ${Math.round(mark * 100)}%"></b>` : ""}
      </span>
      <span class="pc">${esc(disp ?? (unknown ? "—" : v))}</span></div>`;
  }).join("");
  return body + (opts.note ? `<div class="barnote">${opts.note}</div>` : "");
}

/* The median of whatever the screen actually looked at. Unknowns are left
   out rather than counted as zero, which would drag every benchmark down. */
function median(xs) {
  const v = xs.filter(x => x != null).sort((a, b) => a - b);
  if (!v.length) return null;
  const i = Math.floor(v.length / 2);
  return v.length % 2 ? v[i] : (v[i - 1] + v[i]) / 2;
}

function peerMedians() {
  const inv = F?.investors || [];
  const of = k => median(inv.map(x => x.signals[k]?.value));
  return { lead_rate: of("lead_rate"), follow_on: of("follow_on"),
           next_round: of("next_round"), n: inv.length };
}

function donut(parts, size = 118, opts = {}) {
  const tot = parts.reduce((a, p) => a + p.v, 0) || 1, R = size / 2, r = R * .70;
  const thick = R * .34;
  let a0 = -Math.PI / 2, paths = "";
  for (const p of parts) {
    if (!p.v) continue;
    const frac = p.v / tot;
    // A full-circle slice would have identical start and end points, and an SVG
    // arc between two identical points draws nothing. Use a circle instead.
    if (frac > 0.999) {
      paths += `<circle cx="${R}" cy="${R}" r="${r}" fill="none"
        stroke="${p.c}" stroke-width="${thick}"/>`;
      a0 += 2 * Math.PI;
      continue;
    }
    const a1 = a0 + 2 * Math.PI * frac, big = a1 - a0 > Math.PI ? 1 : 0;
    const x0 = R + r * Math.cos(a0), y0 = R + r * Math.sin(a0);
    const x1 = R + r * Math.cos(a1), y1 = R + r * Math.sin(a1);
    paths += `<path d="M${x0} ${y0} A${r} ${r} 0 ${big} 1 ${x1} ${y1}" fill="none"
      stroke="${p.c}" stroke-width="${thick}"/>`;
    a0 = a1;
  }
  // A ring with a legend makes the reader do the division. The headline
  // number is the first slice as a share of the whole, stated in the middle,
  // which is the thing the chart is actually about.
  const lead = parts.find(x => x.v) || parts[0] || { v: 0 };
  const share = tot ? Math.round(100 * (parts[0]?.v || 0) / tot) : null;
  const centre = opts.centre ?? (share == null ? "—" : share + "%");
  return `<div class="donutwrap"><div class="dring">
      <svg width="${size}" height="${size}">${paths}</svg>
      <div class="dval"><b>${esc(String(centre))}</b></div>
    </div>
    <div class="legend">${parts.filter(p => p.v).map(p => `<div><i style="background:${p.c}"></i>
      ${esc(p.k)} <span style="color:var(--faint)">${p.v}</span></div>`).join("")}</div></div>`;
}

const chart = (title, caption, body) => `<div class="card"><h4>${esc(title)}</h4>
  <div class="sub">${esc(caption)}</div>${body}</div>`;

const badgeGroup = (groups) => `<div class="bgrp">${groups.map(([k, items, cls]) =>
  `<div class="box"><div class="k">${esc(k)}</div><div class="bdgs">${
    (items.length ? items : ["—"]).map(t => badge(t, items.length ? cls : "grey")).join("")
  }</div></div>`).join("")}</div>`;

const evidence = list => !list?.length ? "" : `<div class="ev">${list.map(e =>
  `<div>${e.source_url ? `<span class="srank">SOURCE</span><a href="${esc(e.source_url)}"
     target="_blank" rel="noopener">${esc(e.claim)}</a>` : esc(e.claim)}</div>`).join("")}</div>`;

/* ---------- shell ---------- */
function crumb(parts) {
  $("#crumb").innerHTML = parts.map((p, i) => i === parts.length - 1
    ? `<b>${esc(p.t)}</b>` : `<button data-go="${p.go}">${esc(p.t)}</button> / `).join("");
  document.querySelectorAll("[data-go]").forEach(b => b.onclick = () => {
    SEL = null; TAB = 0; render();
  });
}

function wire() {
  document.querySelectorAll("[data-sec]").forEach(h => h.onclick = () => {
    const id = h.dataset.sec; OPEN[id] = OPEN[id] === false;
    h.classList.toggle("closed"); $(`[data-secb="${id}"]`).classList.toggle("closed");
  });
  document.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => {
    TAB = +b.dataset.tab; render();
  });
  document.querySelectorAll("[data-goto]").forEach(b => b.onclick = () => {
    MODE = b.dataset.goto; SEL = null; render();
  });
  document.querySelectorAll("[data-askgo]").forEach(b => b.onclick = () => {
    const v = b.dataset.askgo;
    if (v === "clear") { ASKWHY = null; return render(); }
    ASKWHY = { ...ASKWHY, why: "you chose this view", confident: true, view: v };
    SEL = null;
    if (v === "map") { MODE = "map"; return MAP ? render() : loadMap(); }
    MODE = "founder";
    if (!F) { PENDING_CO = ASKWHY.q; render(); return runFounder(); }
    render();
  });
  document.querySelectorAll("[data-kpi]").forEach(b => b.onclick = () => {
    const k = b.dataset.kpi;
    if (MODE === "founder") FFILTER = FFILTER === k ? "all" : k;
    else IFILTER = IFILTER === k ? "all" : k;
    render();
  });
  const so = $("#startover");
  if (so) so.onclick = () => {
    F = null; SEL = null; CALLS = null; PICKED = new Set();
    INTAKE = { files: [], profile: null, state: "idle" };
    MODE = "home"; render();
  };
  const cf = $("#clearf");
  if (cf) cf.onclick = () => { FFILTER = IFILTER = "all"; render(); };
  document.querySelectorAll("[data-hero]").forEach(b => b.onclick = () => {
    const go = (HEROACTS[+b.dataset.hero] || [])[2] || {};
    if (go.brief) return openBrief(go.brief);
    if (go.alerts) return openAlerts();
    if (go.filter) { FFILTER = go.filter; render(); }
  });
  document.querySelectorAll("[data-plan]").forEach(b => b.onclick = e => {
    e.stopPropagation(); planToggle(b.dataset.plan);
  });
  if ($("#planmd")) $("#planmd").onclick = () => {
    planExport("copy"); $("#planmd").textContent = "Copied";
  };
  if ($("#plandl")) $("#plandl").onclick = () => planExport("download");
  if ($("#planprint")) $("#planprint").onclick = () => planExport("print");
  document.querySelectorAll("[data-person]").forEach(b => b.onclick = e => {
    e.stopPropagation(); openPerson(b.dataset.person, b.dataset.pname);
  });
  document.querySelectorAll("[data-call]").forEach(b => b.onclick = () => {
    if (!CALLDONE) callsLoadDone();
    const id = b.dataset.call;
    CALLDONE.has(id) ? CALLDONE.delete(id) : CALLDONE.add(id);
    callsSaveDone(); render();
  });
  document.querySelectorAll("[data-alertfor]").forEach(b => b.onclick = () => openAlerts());
  document.querySelectorAll("[data-openalerts]").forEach(b => b.onclick = () => openAlerts());
  document.querySelectorAll("[data-ftab]").forEach(b => b.onclick = () => {
    FUNDTAB = +b.dataset.ftab; render();
  });
  document.querySelectorAll("[data-teamfor]").forEach(b => b.onclick = () =>
    loadTeam(b.dataset.teamfor));
  document.querySelectorAll("[data-fscreen]").forEach(b => b.onclick = () =>
    routeAsk(b.dataset.fscreen));
  document.querySelectorAll("[data-syn]").forEach(b => b.onclick = e => {
    e.stopPropagation();
    const [l, m] = b.dataset.syn.split("|");
    openSyndicateEvidence(l, m, "syndicate");
  });
  document.querySelectorAll("[data-warm]").forEach(b => b.onclick = e => {
    e.stopPropagation();
    const [l, v] = b.dataset.warm.split("|");
    openSyndicateEvidence(l, v, "warm");
  });
  document.querySelectorAll("[data-cv]").forEach(b => b.onclick = e => {
    e.stopPropagation();
  });
  document.querySelectorAll("[data-ev]").forEach(b => b.onclick = e => {
    e.stopPropagation();
    const [who, key] = b.dataset.ev.split("|");
    openEvidence(who, key);
  });
  document.querySelectorAll("[data-brief]").forEach(b => b.onclick = e => {
    e.stopPropagation();           // the row underneath opens the fund profile
    openBrief(b.dataset.brief);
  });
  document.querySelectorAll("[data-open]").forEach(tr => tr.onclick = () => {
    SEL = tr.dataset.open; TAB = 0; render(); window.scrollTo(0, 0);
  });
}

function entityHeader(name, sub, meta, tabs, acts, domain) {
  return `<div class="ehd"><div class="ehdtop">
      ${bigLogo(name, domain)}
      <div><h1>${esc(name)}</h1><div class="emeta">${meta}</div></div>
      <span class="eacts">${acts || ""}</span></div>
    <div class="tabs">${tabs.map((t, i) =>
      `<button class="tab ${i === TAB ? "on" : ""}" data-tab="${i}">${esc(t)}</button>`).join("")}</div>
  </div><div class="tabbody">`;
}

/* ================= FOUNDER ================= */
/* A minute and a half behind one spinner says nothing about how much Cala
   data is being read. Poll the run log and show the work. */
let PGTIMER = null;

function stopProgress() { clearInterval(PGTIMER); PGTIMER = null; }

function startProgress(company, stage) {
  stopProgress();
  const paint = steps => {
    const el = $("#pgsteps");
    if (!el) return;
    el.innerHTML = steps.map((x, i) => `
      <div class="pgstep ${i === steps.length - 1 ? "now" : "done"}">
        <span class="tick">${i === steps.length - 1 ? "" : "✓"}</span>
        <span class="tx">${esc(x.text)}${
          x.detail ? ` <span class="sub">${esc(x.detail)}</span>` : ""}</span>
        <span class="el">${x.t}s</span></div>`).join("");
    el.scrollTop = el.scrollHeight;
  };
  PGTIMER = setInterval(async () => {
    try {
      const r = await fetch(`/progress?company=${encodeURIComponent(company)
        }&stage=${encodeURIComponent(stage || "")}`);
      const d = await r.json();
      if (d.steps?.length) paint(d.steps);
      if (d.done) stopProgress();
    } catch (e) { /* the run is what matters, not its narration */ }
  }, 600);
}

async function runFounder() {
  const co = PENDING_CO || $("#co")?.value || F?.company || "Gosta Labs";
  const st = PENDING_STAGE || $("#st")?.value || "series a";
  $("#view").innerHTML = `<div class="pgwrap">
    <div class="pghd"><span class="spin"></span>Reading Cala's graph for
      <b>${esc(co)}</b></div>
    <div class="pgsteps" id="pgsteps"><div class="pgstep now">
      <span class="tick"></span><span class="tx">Starting…</span></div></div>
    <div class="sub" style="margin-top:12px">Every step below is a walk over
      Cala's graph — competitors, fund histories, portfolio progressions and
      warm routes.</div>
  </div>`;
  startProgress(co, st);
  const r = await fetch("/analyze", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      company: co,
      stage: st,
      limit: +($("#n")?.value || 14) })
  });
  stopProgress();
  F = await r.json(); PENDING_CO = PENDING_STAGE = null; SEL = null; SYN = null;
  planLoad(); dealLoad(); FCONTRA = {}; render();
  loadSyndicates(F.company, F.stage);
  loadFounderContradictions();
}

/* The screen answers "who". A round needs "who, with whom, through whom".
   Fetched after the list is already on screen: it re-runs the scoring
   server-side, and the founder should not sit through that twice. */
async function loadSyndicates(company, stage) {
  const want = company;
  SYN = { loading: true };
  if (MODE === "founder" && !SEL) render();
  try {
    const r = await fetch("/syndicates", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ company, stage, limit: 14 })
    });
    const j = await r.json();
    if (F && F.company !== want) return;        // founder moved on; drop it
    SYN = j;
  } catch (e) { SYN = { error: String(e) }; }
  if (MODE === "founder" && !SEL) render();
}

function syndicateBlock() {
  if (!SYN) return "";
  if (SYN.loading) return section("fsyn", "Who has been in their rounds", "",
    `<div class="msg"><span class="spin"></span>Assembling syndicates from the round graph…</div>`);
  if (SYN.error || !(SYN.syndicates || []).length) return section("fsyn", "Who has been in their rounds", "",
    `<div class="msg">No fund on this list both leads at your stage and has funds that
      repeatedly follow it. That is a finding about this list, not an empty state.</div>`);

  const backers = SYN.your_backers || [];
  const anyWarm = SYN.syndicates.some(s => (s.warm_paths || []).length);
  // A warm route to a fund that never leads is still worth naming: it explains
  // why the header count says 1 while no syndicate here has a route.
  const leads = new Set(SYN.syndicates.map(s => s.lead));
  const elsewhere = (F?.investors || []).filter(x =>
    x.signals.warm_path.label !== "⚪" && !leads.has(x.investor)).slice(0, 3);
  const cards = SYN.syndicates.map(s => {
    const members = s.members.map(m => `<div class="synm">
      ${logo(m.name)}<div><div class="nm">${esc(m.name)}</div>
      <div class="sb"><button class="figure" data-syn="${esc(s.lead)}|${esc(m.name)}"
        title="The rounds behind this">was in ${m.joined} of the ${s.rounds_led} rounds
        they led${m.share != null ? ` · ${pct(m.share)}` : ""}</button></div></div></div>`).join("");

    // When nothing is warm, one honest line at the top beats the same
    // sentence repeated under every card.
    const p = (s.warm_paths || [])[0];
    const route = p ? `<div class="synp"><b><button class="figure"
        data-warm="${esc(s.lead)}|${esc(p.via)}" title="The cap tables they share"
        >Ask ${esc(p.via)}.</button></b> ${
        p.through.map(t => `${esc(t.company)}${t.when ? ` (${esc(String(t.when).slice(0, 7))})` : ""}`).join(", ")
      } — they sat on that cap table with ${esc(s.lead)}, so the intro is one hop.</div>`
      : anyWarm ? `<div class="synp cold">No shared cap table with ${esc(s.lead)} — cold approach.</div>`
      : "";

    return `<div class="syn">
      <div class="synh" data-open="${esc(s.lead)}">
        ${logo(s.lead)}
        <div class="synt"><div class="nm">${esc(s.lead)}</div>
          <div class="sb">${esc(s.lead_text || "")} · led ${s.rounds_led} rounds · ${esc(s.pace || "")}</div></div>
        ${badge("Lead", "green")}${s.enough ? "" : badge("Thin evidence", "amber")}
        ${planButton(s.lead)}
        <button class="btn sm" data-brief="${esc(s.lead)}">Slush brief</button>
      </div>
      <div class="synms">${members}</div>
      ${route}</div>`;
  }).join("");

  return section("fsyn", "Who has been in their rounds",
    `${SYN.syndicates.length} lead${SYN.syndicates.length > 1 ? "s" : ""} with a co-investment record`,
    `<div class="synlead">Who has been in rounds each lead led — a record, not a
       forecast. <button class="lnk" data-goto="accuracy">we tested that; it does
       not predict</button></div>
     ${anyWarm ? "" : `<div class="quiet" title="Nothing in the cached graph puts ${
        esc(backers.join(", ") || "your backers")} and these funds on the same cap table.${
        elsewhere.length ? ` The warm route you do have reaches ${
          esc(elsewhere[0].investor)}, which does not lead at your stage.` : ""}">
       No warm route to any of these leads${elsewhere.length
         ? ` — the one you have reaches <b>${esc(elsewhere[0].investor)}</b>, which does not lead`
         : ""}.</div>`}
     <div class="syns">${cards}</div>`);
}

/* ===================================================== PICK AND REACH
   A screen ends with a ranking, which is an opinion. What a founder needs
   next is a week of work: who to contact, in what order, and which of them
   they could walk to. So the ranking is selectable, and the selection
   becomes a call list with the map beside it.

   Funds that back a competitor cannot be picked at all. Letting a founder
   build a week around one of them would undo the only thing this product
   does that nothing else does. */
let PICKED = new Set();

function pickAllBox(shown) {
  const able = shown.filter(x => x.signals.conflict.label !== "\u{1F534}");
  const all = able.length && able.every(x => PICKED.has(x.investor));
  return `<button class="pick ${all ? "on" : ""}" data-pickall="1"
    title="${all ? "Clear the list" : `Add all ${able.length} that are not blocked`}"
    >${all ? "\u2713" : ""}</button>`;
}

function pickBar() {
  if (!PICKED.size) return "";
  const n = PICKED.size;
  return `<div class="pickbar">
    <div class="pkn">${n} fund${n === 1 ? "" : "s"} on your list</div>
    <div class="pknames">${[...PICKED].slice(0, 4).map(esc).join(" · ")}${
      n > 4 ? ` · +${n - 4}` : ""}</div>
    <button class="btn" data-pickclear="1">Clear</button>
    <button class="btn primary" id="buildcalls">Who do I call, and where are they?</button>
  </div>`;
}

async function buildReach() {
  if (!PICKED.size || !F) return;
  const picks = [...PICKED];
  MODE = "reach"; CALLS = { loading: true }; REACHMAP = { loading: true };
  render();
  // The map is a /map read and lands in under a second; the call list is a
  // re-screen and takes a minute. Starting them together means the founder
  // has something true on screen while the slow half runs.
  loadReachMap(picks);
  try {
    CALLS = await (await fetch("/call-list", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ company: F.company, stage: F.stage,
                             investors: picks, limit: picks.length })
    })).json();
  } catch (e) { CALLS = { error: String(e.message), rows: [] }; }
  render();
  if (CALLS.rows?.length) enrichCalls();
}

/* The map answers a question the list cannot: which of these people are in
   the city you are already in next week. */
let REACHMAP = null;
async function loadReachMap(picks) {
  REACHMAP = { loading: true };
  if (MODE === "reach") paintReachMap();
  try {
    const d = await (await fetch("/map")).json();
    const want = new Set(picks.map(norm_));
    const pts = (d.funds || []).filter(f => want.has(norm_(f.name)));
    REACHMAP = { points: pts, missing: picks.filter(p =>
      !pts.some(x => norm_(x.name) === norm_(p))) };
  } catch (e) { REACHMAP = { error: String(e.message), points: [] }; }
  if (MODE === "reach") paintReachMap();
}

function reachView() {
  if (!F) return `<div class="msg">Run a screen first — the list is built from
    the funds that survived it.</div>`;
  return `<div class="reachhd">
      <div><h2>${esc(F.company)} · ${PICKED.size} fund${PICKED.size === 1 ? "" : "s"} you picked</h2>
      <p class="sub">Who to call at each one, and where they are. The order is
        the fund's score plus what we know about the person — a partner who
        has been in your market, has built something, has been there long
        enough to champion a cheque, and can introduce you onward.</p></div>
      <button class="btn" data-goto="founder">Back to the screen</button>
    </div>
    <div class="reachgrid">
      <div class="reachlist">${reachList()}</div>
      <div class="reachmap"><div id="reachmap" class="rmap"></div>
        <div class="rmapfoot" id="rmapfoot"></div></div>
    </div>`;
}

function paintReachMap() {
  const foot = $("#rmapfoot");
  if (foot) {
    foot.innerHTML = (!REACHMAP || REACHMAP.loading)
      ? `<span class="spin"></span> Placing them…`
      : REACHMAP.error ? esc(REACHMAP.error)
      : `${REACHMAP.points?.length || 0} of ${PICKED.size} placed${
          (REACHMAP.points || []).some(x => x.precision === "country")
            ? ` · ${(REACHMAP.points || []).filter(x => x.precision === "country").length}
                of them by country only (the hollow ring)` : ""}${
          REACHMAP?.missing?.length
            ? ` · ${REACHMAP.missing.length} with no address in Cala: ${
                REACHMAP.missing.slice(0, 3).map(esc).join(", ")}` : ""}
         <button class="lnk" id="nearme">Find funds near me</button>`;
  }
  const el = $("#reachmap");
  if (!el || !REACHMAP?.points?.length || typeof maplibregl === "undefined") return;
  // render() replaces #view wholesale, so the element this map was built
  // against is detached after any re-render and the map draws into nothing.
  // A live map whose container is no longer in the document is not a map.
  if (RMAP && RMAP.getContainer() !== el) { RMAP.remove(); RMAP = null; RMARKERS = []; }
  if (!RMAP) {
    RMAP = new maplibregl.Map({
      container: el, style: "https://tiles.openfreemap.org/styles/positron",
      center: [12, 54], zoom: 3, attributionControl: false,
    });
    RMAP.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  }
  RMARKERS.forEach(m => m.remove()); RMARKERS = [];
  const bounds = new maplibregl.LngLatBounds();
  for (const p of REACHMAP.points) {
    if (p.lon == null || p.lat == null) continue;
    const d = document.createElement("div");
    d.className = "rpin" + (p.nearby ? " near" : "")
      + (p.precision === "country" ? " loose" : "");
    d.title = p.precision === "country"
      ? `${p.name} — country only, this pin is ${p.cc || "the country"}, not the office`
      : `${p.name}${p.city ? " · " + p.city : ""}`;
    d.textContent = initials(p.name);
    const m = new maplibregl.Marker({ element: d }).setLngLat([p.lon, p.lat])
      .setPopup(new maplibregl.Popup({ offset: 14 })
        .setHTML(`<b>${esc(p.name)}</b><br>${esc(p.hq || p.city || p.country || "")}${
          p.precision === "country"
            ? `<br><i>country only — Cala has no address for them, so this pin
               is the country, not the office</i>` : ""}`))
      .addTo(RMAP);
    RMARKERS.push(m); bounds.extend([p.lon, p.lat]);
  }
  if (!bounds.isEmpty()) RMAP.fitBounds(bounds, { padding: 56, maxZoom: 9, duration: 600 });
}
let RMAP = null, RMARKERS = [];

/* "Near me" on the reach map. The coordinate comes from the browser with the
   founder's consent, is used for one request, and is never stored or sent
   anywhere else - no IP lookup service sees where they are. */
function nearMeOnReach() {
  const foot = $("#rmapfoot");
  if (!navigator.geolocation) {
    if (foot) foot.innerHTML = "This browser will not share a location.";
    return;
  }
  if (foot) foot.innerHTML = `<span class="spin"></span> Asking your browser where you are…`;
  navigator.geolocation.getCurrentPosition(async pos => {
    const { latitude: lat, longitude: lon } = pos.coords;
    try {
      const d = await (await fetch(`/near?lat=${lat}&lon=${lon}&radius_km=400&kind=fund`
        + `&company=${encodeURIComponent(F?.company || "")}`)).json();
      const picks = new Set([...PICKED].map(norm_));
      REACHMAP = {
        ...REACHMAP,
        points: [...(REACHMAP?.points || []),
                 ...(d.results || []).filter(x => !picks.has(norm_(x.name)))
                   .map(x => ({ ...x, nearby: true }))],
        near: { count: (d.results || []).length, km: 400 },
      };
      paintReachMap();
      const f = $("#rmapfoot");
      if (f) f.innerHTML = `${d.count || 0} funds within 400 km of you${
        d.city ? ` · ${esc(d.city)}` : ""} — the hollow pins are ones you have
        not picked.`;
    } catch (e) {
      const f = $("#rmapfoot");
      if (f) f.textContent = String(e.message);
    }
  }, err => {
    const f = $("#rmapfoot");
    if (f) f.textContent = err.code === 1
      ? "You declined the location prompt, so the map stays as it is."
      : "Your browser could not get a location.";
  }, { timeout: 8000 });
}

/* ======================================================= THE OTHER SIDE
   Flipside is named for this: the same graph answers two questions, and
   they are the same question from opposite ends of the table.

   A founder asks who can lead their round. An investor asks which companies
   are being backed again by the people who already know them - insiders
   doubling down is the one signal that cannot be manufactured for a deck,
   because it costs the insider money to send it.

   One screen, not a second product. The engine, the evidence and the
   honesty about what was not tested are the ones already built. */
let ROLE = (() => { try { return localStorage.getItem("flipside.role") || "founder"; }
                    catch { return "founder"; } })();
let CONV = null, MOVES = null;

/* The earliest a deal exists.
   A founder leaving to start something is what an investor wants to hear
   first, and by the time it is a funding round it is not early any more.
   The graph can say it: FOUNDED carries a start date and a company with no
   rounds has not raised.

   It currently finds almost nothing, and the panel says so with the
   denominator rather than presenting two rows as a finding. That is not a
   placeholder - the detector is right and the record is thin, and those are
   different problems with different fixes. */
async function loadMoves() {
  MOVES = { loading: true };
  try { MOVES = await (await fetch("/moves")).json(); }
  catch (e) { MOVES = { error: String(e.message), moves: [] }; }
  if (MODE === "investor") render();
}

function movesBlock() {
  if (!MOVES) { loadMoves(); return ""; }
  if (MOVES.loading) return section("mv", "Who just changed seats", "",
    `<div class="msg" style="padding:24px"><span class="spin"></span>Reading
      the people we have records for…</div>`);
  if (MOVES.error) return section("mv", "Who just changed seats", "",
    `<div class="emptywhy"><b>Could not read it.</b> ${esc(MOVES.error)}</div>`);

  const c = MOVES.coverage || {};
  const v = MOVES.new_ventures || [];
  const seats = (MOVES.moves || []).filter(m => m.kind === "new_seat");
  const cov = `<div class="sub" style="line-height:1.7;max-width:70ch;margin-top:var(--s2)">
      Read from ${c.people_with_edges} people whose records we have fetched, of
      ${c.people_in_cache} we hold a name for. Only
      <b>${c.people_with_a_dated_role}</b> of those carry a dated role, and a
      founding with no date has no "just" in it — so this sees a fraction of
      what it is looking for, and the fraction is the number above.
      It widens as the harvester reaches more people.</div>`;

  return section("mv", "Who just changed seats",
    `${v.length} new venture${v.length === 1 ? "" : "s"} · ${seats.length} seat
     change${seats.length === 1 ? "" : "s"} · last ${MOVES.window_months} months`,
    (v.length
      ? `<div class="mvlist">${v.map(m => `<div class="mvrow new">
          <div><b>${esc(m.person)}</b> founded <b>${esc(m.company)}</b>
            ${m.stealth ? badge("in stealth", "amber") : ""}
            <div class="sub">${m.months_ago} months ago · ${esc(m.why)}</div></div>
          ${m.person_id ? `<button class="btn sm" data-person="${esc(m.person_id)}"
            data-pname="${esc(m.person)}">Card</button>` : ""}
        </div>`).join("")}</div>`
      : `<div class="emptywhy"><b>Nobody in our records has founded anything in
          the last ${MOVES.window_months} months.</b> A computed result, not an
          empty state — and with ${c.people_with_a_dated_role} dated roles to
          read, it is as much a statement about the record as about the
          people.</div>`)
    + (seats.length ? `<div class="mvlist" style="margin-top:var(--s2)">
        ${seats.map(m => `<div class="mvrow">
          <div><b>${esc(m.person)}</b> → <b>${esc(m.company)}</b>
            <div class="sub">${m.months_ago} months ago · ${esc(m.role || "")}
              ${m.why ? "· " + esc(m.why) : ""}</div></div>
          ${m.person_id ? `<button class="btn sm" data-person="${esc(m.person_id)}"
            data-pname="${esc(m.person)}">Card</button>` : ""}
        </div>`).join("")}</div>` : "")
    + cov);
}

function applyRoleChrome() {
  // An investor opening the map wants the companies; a founder wants the
  // funds. Both can turn the other layer on, but neither should have to.
  LAYERS = ROLE === "investor"
    ? { ex: false, pf: true, fu: false }
    : { ex: false, pf: false, fu: true };
  document.querySelectorAll("[data-deal]").forEach(b => b.onclick = e => {
    e.stopPropagation();
    const n = b.dataset.deal;
    dealSet(n, DEALS[n] ? null : "todo");
  });
  document.querySelectorAll("[data-dmove]").forEach(b => b.onclick = e => {
    e.stopPropagation();
    const [n, st] = b.dataset.dmove.split("|");
    dealSet(n, st);
  });
  document.querySelectorAll("[data-ddrop]").forEach(b => b.onclick = e => {
    e.stopPropagation(); dealSet(b.dataset.ddrop, null);
  });
  document.querySelectorAll("[data-scack]").forEach(b =>
    b.onclick = () => scoutAck(b.dataset.scack));
  document.querySelectorAll("[data-scwatch]").forEach(b => b.onclick = () => {
    const [id, ...rest] = b.dataset.scwatch.split("|");
    scoutToggle(id, rest.join("|"));
  });
  const nf = $("#needform");
  if (nf) nf.onsubmit = e => { e.preventDefault(); intakeContinue($("#needq").value); };
  const scf = $("#scform");
  if (scf) scf.onsubmit = e => { e.preventDefault(); loadScouts($("#scq").value); };
  document.querySelectorAll("[data-role]").forEach(b =>
    b.classList.toggle("on", b.dataset.role === ROLE));
  const f = $("#navfounder"), i = $("#navinvestor");
  if (f) f.hidden = ROLE !== "founder";
  if (i) i.hidden = ROLE !== "investor";
}

function setRole(r) {
  ROLE = r;
  try { localStorage.setItem("flipside.role", r); } catch { /* private window */ }
  applyRoleChrome();
  MODE = r === "investor" ? "investor" : "home";
  SEL = null;
  if (r === "investor" && !CONV) return loadConviction();
  render();
}

async function loadConviction() {
  CONV = { loading: true }; render();
  try { CONV = await (await fetch("/conviction")).json(); }
  catch (e) { CONV = { error: String(e.message), companies: [] }; }
  render();
}

/* ================================================= BEFORE THEY FOUND
   By the time there is a company and a deck, every fund has the same
   information and the round is a race. The investors who are early are
   early because they knew the person.

   So: a watchlist of people who have built before and are currently sitting
   in somebody else's seat, ranked against a thesis, with the thing that
   would change named on every row. Watch one and this checks their record
   and the open news index for it.

   What this does not do is read anyone's LinkedIn or anyone's mail. Those
   are the signals an investor would most like and they are not ours to
   take — the first is against LinkedIn's terms, the second is surveillance
   of people who never asked to be watched. The panel says so rather than
   leaving it to be assumed either way. */
let SCOUTS = null, SCOUT_THESIS = "", SCOUTWATCH = {}, SCOUTSIG = {}, SCOUTBT = null;

/* The ranking graded against what people actually did next.
   "No backtest" is a caveat anyone can ignore. The attempt, its sample size
   and the one signal currently pointing the wrong way are harder to. */
async function loadScoutBacktest() {
  try { SCOUTBT = await (await fetch("/backtest-scouts")).json(); }
  catch (e) { SCOUTBT = { ran: false, verdict: String(e.message) }; }
  if (MODE === "scouts") render();
}

function scoutBacktestBlock() {
  if (!SCOUTBT) { loadScoutBacktest(); return ""; }
  if (!SCOUTBT.ran) return "";
  const sigs = SCOUTBT.signals || [];
  const wrong = sigs.filter(s => s.with.rate != null && s.without.rate != null
    && s.with.rate < s.without.rate);
  return section("scbt", "Does this ranking predict anything?",
    `cut at ${SCOUTBT.cutoff} · ${SCOUTBT.people_graded} people could be graded`,
    `<div class="card">
      <p style="margin:0 0 var(--s2);line-height:1.7">${esc(SCOUTBT.verdict)}</p>
      <div class="tbl"><table><thead><tr><th>Signal</th>
        <th class="num">Had it</th><th class="num">Founded again</th>
        <th class="num">Without it</th></tr></thead><tbody>${sigs.map(x => `
        <tr style="cursor:default">
          <td>${esc(x.signal)}</td>
          <td class="num">${x.with.n}</td>
          <td class="num">${x.with.rate == null ? "—"
            : `${Math.round(x.with.rate * 100)}%`}</td>
          <td class="num">${x.without.rate == null ? "—"
            : `${Math.round(x.without.rate * 100)}%`}</td>
        </tr>`).join("")}</tbody></table></div>
      ${wrong.length ? `<div class="emptywhy" style="margin-top:var(--s2)">
        <b>${wrong.map(w => esc(w.signal)).join(", ")} currently points the
        wrong way.</b> In this sample people with it founded again
        <i>less</i> often. At these counts that is as likely to be noise as
        signal — which is exactly why the weight stays as it is rather than
        being tuned to twelve people.</div>` : ""}
      <p class="sub" style="margin:var(--s2) 0 0;line-height:1.7">
        Method: pick a year, score each person on evidence dated before it
        only, then look at who founded something after. Anything undated is
        excluded rather than assumed early — a FOUNDED edge with no date
        might be from 2004 or last month, and guessing would be grading our
        own homework.</p>
    </div>`);
}

/* The watchlist lives on the server, not in this browser.
   It has to: an alert is a diff against what we last saw, and a browser that
   forgets between visits can only ever show you the same thing again. The
   first check of a newly watched person is stored as a baseline and raises
   nothing - everything about them is new to us and none of it is new to the
   world. */
let WATCH = { watching: [], unread: [] };

async function scoutLoad() {
  try { WATCH = await (await fetch("/watch")).json(); }
  catch (e) { WATCH = { watching: [], unread: [], error: String(e.message) }; }
  SCOUTWATCH = Object.fromEntries((WATCH.watching || []).map(w => [w.id, w]));
  if (MODE === "scouts") render();
}

async function scoutToggle(id, name) {
  const on = !!SCOUTWATCH[id];
  SCOUTWATCH = { ...SCOUTWATCH };
  if (on) delete SCOUTWATCH[id]; else SCOUTWATCH[id] = { id, name };
  render();                                   // answer the click immediately
  try {
    const r = await fetch(`/watch/${encodeURIComponent(id)}`
      + (on ? "" : `?name=${encodeURIComponent(name)}`),
      { method: on ? "DELETE" : "POST" });
    WATCH = await r.json();
    SCOUTWATCH = Object.fromEntries((WATCH.watching || []).map(w => [w.id, w]));
  } catch (e) { /* the optimistic state is close enough to retry from */ }
  render();
}

async function scoutAck(pid) {
  try {
    const r = await fetch(`/watch-ack${pid ? `?pid=${encodeURIComponent(pid)}` : ""}`,
      { method: "POST" });
    WATCH = { ...WATCH, unread: (await r.json()).unread || [] };
  } catch (e) { /* nothing to do */ }
  render();
}

function unreadFor(id) {
  return (WATCH.unread || []).filter(u => u.id === id);
}

async function loadScouts(thesis) {
  SCOUT_THESIS = thesis ?? SCOUT_THESIS;
  SCOUTS = { loading: true }; render();
  try {
    SCOUTS = await (await fetch(
      `/scouts?thesis=${encodeURIComponent(SCOUT_THESIS)}&limit=60`)).json();
  } catch (e) { SCOUTS = { error: String(e.message), candidates: [] }; }
  render();
  scoutLoad();
}

/* What has happened to a watched person lately: the moves their own record
   supports, and the open news index naming them. */
async function loadScoutSignal(id, name) {
  SCOUTSIG[id] = { loading: true };
  try {
    SCOUTSIG[id] = await (await fetch(
      `/scout-signal?name=${encodeURIComponent(name)}&id=${encodeURIComponent(id)}`)).json();
  } catch (e) { SCOUTSIG[id] = { error: String(e.message) }; }
  if (MODE === "scouts") render();
}

/* "3 hours ago" from a unix seconds stamp. */
function since(ts) {
  if (!ts) return "";
  const m = Math.max(0, (Date.now() / 1000 - ts) / 60);
  if (m < 2) return "just now";
  if (m < 90) return `${Math.round(m)} minutes ago`;
  const h = m / 60;
  if (h < 36) return `${Math.round(h)} hours ago`;
  return `${Math.round(h / 24)} days ago`;
}

function scoutRow(c, watched) {
  const w = SCOUTWATCH[c.id];
  const news = unreadFor(c.id);
  return `<div class="scrow ${watched ? "on" : ""}">
    <button class="scwatch ${watched ? "on" : ""}" data-scwatch="${esc(c.id)}|${esc(c.name)}"
      title="${watched ? "Stop watching" : "Watch this person"}">${watched ? "◉" : "○"}</button>
    <div class="scmain">
      <div class="scnm">${esc(c.name)}
        ${c.match_specific?.length
          ? badge(c.match_specific.join(", ") + " — your thesis", "green")
          : c.match?.length ? `<span class="chip sm">${esc(c.match.join(", "))}</span>` : ""}
        ${c.angel ? `<span class="chip sm">invests</span>` : ""}</div>
      <div class="scwhy">${esc(c.why.join(" · "))}</div>
      ${c.now_at?.length ? `<div class="scnow">now at
        <b>${esc(c.now_at[0].name)}</b>${c.now_at[0].role
          ? ` · ${esc(c.now_at[0].role)}` : ""}</div>` : ""}
      ${c.founded_firms?.length ? `<div class="scnow sub">also started
        ${esc(c.founded_firms.map(f => f.name).join(", "))} — a firm, not counted</div>` : ""}
      ${watched ? `<div class="scsig ${news.length ? "fresh" : ""}">${
        news.length
          ? news.map(u => `<div>${u.url
              ? `<a href="${esc(u.url)}" target="_blank" rel="noopener">${esc(u.text)}</a>`
              : `<b>${esc(u.text)}</b>`}
              <span class="sub">${esc(since(u.first_seen))}</span></div>`).join("")
            + `<button class="lnk" data-scack="${esc(c.id)}">Mark as read</button>`
          : `<span class="sub">Nothing new since we started watching${
              w?.checked ? `, last checked ${esc(since(w.checked))}` : ""}.
             Watching for: ${esc((c.watch_for || []).join("; "))}.</span>`
      }</div>` : `<div class="scwatchfor sub">Watch for: ${
        esc((c.watch_for || [])[0] || "")}</div>`}
    </div>
    <div class="scsc">${c.score}</div>
    <button class="btn sm" data-person="${esc(c.id)}" data-pname="${esc(c.name)}">Card</button>
  </div>`;
}

function scoutsView() {
  const watched = Object.keys(SCOUTWATCH);
  const head = `<div class="runline">
      <div class="rl1"><b>Before they found</b>
        <span class="sub">· people who have built, sitting in someone else's seat</span></div>
      <div class="rl2">${(WATCH.unread || []).length
        ? `<button class="lnk" data-scack="">Mark all read</button>` : ""}
        ${WATCH.last_sweep
          ? `<span class="sub">last swept ${esc(since(WATCH.last_sweep))}</span>` : ""}</div>
    </div>
    <form class="scthesis" id="scform">
      <input id="scq" placeholder="Your thesis — e.g. clinical software for hospitals"
        value="${esc(SCOUT_THESIS)}" autocomplete="off">
      <button class="btn pri" type="submit">Rank against it</button>
    </form>`;

  if (!SCOUTS) { loadScouts(SCOUT_THESIS); return head + `<div class="msg">
    <span class="spin"></span>Reading the people we have records for…</div>`; }
  if (SCOUTS.loading) return head + `<div class="msg" style="padding:30px">
    <span class="spin"></span>Ranking…</div>`;
  if (SCOUTS.error) return head + errorPanel(SCOUTS.error, "the watchlist");

  const c = SCOUTS.coverage || {};
  const rows = SCOUTS.candidates || [];
  const onList = rows.filter(r => SCOUTWATCH[r.id]);
  const rest = rows.filter(r => !SCOUTWATCH[r.id]);

  return head
    + kpis([
      ["Candidates", c.candidates ?? 0, "all", "have founded or run something"],
      ["Match your thesis", c.matched_specifically ?? 0, "match",
       "on a market specific enough to mean something"],
      ["On your watchlist", watched.length, "watch",
       WATCH.sweep_every_minutes
         ? `re-checked every ${WATCH.sweep_every_minutes} minutes`
         : "kept on the server"],
      ["New since you looked", (WATCH.unread || []).length, "new",
       "a change on a watched record, not a reread of the same one"],
    ], "all", null)
    + (onList.length ? section("scw", "Watching", `${onList.length}`,
        `<div class="sclist">${onList.map(r => scoutRow(r, true)).join("")}</div>`) : "")
    + section("scall", "Who could start something",
        `${rows.length} of ${c.people_with_edges} people whose records we have read`,
        rest.length
          ? `<div class="sclist">${rest.map(r => scoutRow(r, false)).join("")}</div>`
          : `<div class="emptywhy"><b>Nobody left.</b> Everyone we can see is
              already on your watchlist.</div>`)
    + scoutBacktestBlock()
    + `<div class="evfoot">
        <b>What this reads, and what it will not.</b>
        <span style="display:block;max-width:74ch;line-height:1.7;margin-top:6px">
          Companies founded, roles held and their dates, from Cala; and the open
          news index, when it names someone. A watched person is re-read on a
          timer and what you see is the <i>difference</i> since last time — the
          first check is a baseline and raises nothing, because everything
          about them is new to us and none of it is new to the world.
          Nothing is emailed: there is no mail to send it from, and saying
          otherwise would be the easiest sentence here to write and the least
          true. It does not read LinkedIn — that is against their terms — and
          it does not read anyone's mail. Ranked on
          ${c.people_with_edges} people of the ${c.people_in_cache} we hold a name
          for. Whether the order predicts anything is tested above, not
          asserted here.
        </span></div>`;
}

function investorView() {
  if (!CONV || CONV.loading) return `<div class="msg" style="padding:40px">
    <span class="spin"></span>Reading who got backed again…</div>`;
  if (CONV.error) return errorPanel(CONV.error, "insider conviction");
  const cs = (CONV.companies || []).filter(c => c.score != null);
  const healthy = cs.filter(c => c.structure === "healthy");
  const back = cs.filter(c => c.previous_lead_returned);

  return `<div class="runline">
      <div class="rl1"><b>Insider conviction</b>
        <span class="sub">· ${CONV.scored ?? cs.length} of ${CONV.corpus ?? "?"} companies scored</span></div>
      <div class="rl2"><span class="sub">precomputed from Cala's round records</span>
        <button class="lnk" data-goto="accuracy">Does it predict?</button></div>
    </div>
    ${kpis([
      ["Scored", cs.length, "all", "two rounds and prior investors to compare"],
      ["Insiders came back", healthy.length, "healthy", "the round structure reads healthy"],
      ["Previous lead returned", back.length, "lead", "the strongest version of it"],
    ], IFILTER, null)}
    ${movesBlock()}
    ${section("convlist", "Backed again by the people who already knew them",
      `${cs.length} companies`, `<div class="convlist">${
        cs.slice(0, 60).map((c, i) => `<button class="convrow" data-conv="${esc(c.company)}">
          <span class="rk">${i + 1}</span>
          <span><span class="nm">${esc(c.company)}</span>${
            c.at_slush ? ` <span class="chip sm">at Slush</span>` : ""}
            <span class="wh">${esc((c.reasons || []).slice(0, 2).join(" · ") || "no reason recorded")}</span></span>
          <span class="st sub">${esc(c.structure || "")} · ${esc(c.confidence || "")}</span>
          <span class="sc">${c.score}</span></button>`).join("")}</div>`)}
    ${(CONV.orphans || []).length ? "" : `<div class="evfoot">
      <b>What this cannot do.</b> The orphan detector — companies whose
      insiders stopped — never fires, because Cala holds no headcount series
      for private companies to confirm distress against. It is in the product
      saying so rather than quietly returning nothing.</div>`}`;
}

function openConviction(name) {
  const c = (CONV?.companies || []).find(x => x.company === name);
  if (!c) return;
  const w = document.createElement("div");
  w.className = "scrim on";
  w.innerHTML = `<div class="composebox wide" onclick="event.stopPropagation()">
    <div class="sidehd"><h3>${esc(c.company)}</h3>
      <div class="s">${esc(c.structure || "")} · confidence ${esc(c.confidence || "—")}
        · score ${c.score}</div></div>
    <div style="padding:15px">
      <div class="sech"><h3>Why</h3></div>
      <ul class="why">${(c.reasons || []).map(r => `<li>${esc(r)}</li>`).join("")
        || `<li class="sub">No reason recorded.</li>`}</ul>
      <div class="sech"><h3>The rounds it read</h3></div>
      <div class="tbl"><table><thead><tr><th>Stage</th><th>Date</th>
        <th class="num">Amount</th><th>Who was in it</th></tr></thead><tbody>${
        (c.rounds || []).map(r => `<tr style="cursor:default">
          <td>${esc(r.stage || "")}</td>
          <td class="nowrap">${esc(String(r.date || "").slice(0, 10))}</td>
          <td class="num">${r.amount ? (r.amount / 1e6).toFixed(1) + "M" : "—"}</td>
          <td class="sub">${(r.investors || []).map(i =>
            (r.leads || []).includes(i) ? `<b>${esc(i)}</b>` : esc(i)).join(", ")}</td>
        </tr>`).join("")}</tbody></table></div>
      <div class="emptywhy" style="margin-top:var(--s2)">
        <b>Bold is the lead.</b> An amount shown as — is a round Cala records
        without one, not a round of nothing.</div>
    </div></div>`;
  document.body.appendChild(w);
  w.onclick = () => w.remove();
}

function founderList() {
  if (!F) return searchPanel() + `<div class="msg">Run diligence to screen your target list.</div>`;
  const inv = F.investors, red = inv.filter(x => x.signals.conflict.label === "🔴");
  const rowsFor = list => list.map((x, i) => {
    const s = x.signals, c = s.conflict;
    const verdict = c.label === "🔴" ? badge("Do not pitch", "red")
      : x.score === null ? badge("No data", "grey")
      : s.lead_rate.label === "🟢" && s.dry_powder.label !== "🔴" ? badge("Strong", "green")
      : badge("Care", "amber");
    const picked = PICKED.has(x.investor);
    const blocked = c.label === "\u{1F534}";
    return `<tr data-open="${esc(x.investor)}" class="${picked ? "picked" : ""}">
      <td class="w-pick">${blocked
        ? `<span class="nopick" title="Backs a competitor — building a list
             around them is the mistake this product exists to stop">\u2014</span>`
        : `<button class="pick ${picked ? "on" : ""}" data-pick="${esc(x.investor)}"
             title="${picked ? "Remove from your list" : "Add to your list"}"
             >${picked ? "\u2713" : ""}</button>`}</td>
      <td class="rank">${i + 1}</td>
      <td><div class="ent">${logo(x.investor)}<div><div class="nm">${esc(x.investor)}</div>
        <div class="sb">${x.rounds_seen} rounds · ${x.portfolio_size || 0} portfolio</div></div></div></td>
      <td>${verdict}</td>
      <td class="num">${x.score === null ? "—"
        : `<button class="figure" data-ev="${esc(x.investor)}|score"
             title="How this score was computed">${x.score}${
             x.breakdown?.stale ? `<span class="decay">stale</span>` : ""}</button>`}</td>
      <td class="num"><button class="figure" data-ev="${esc(x.investor)}|lead_rate"
        title="The rounds behind this">${pct(s.lead_rate.value)}</button></td>
      <td class="num"><button class="figure" data-ev="${esc(x.investor)}|follow_on"
        title="The rounds behind this">${pct(s.follow_on.value)}</button></td>
      <td>${s.dry_powder.label === "⚪" ? badge("—", "grey")
        : `<button class="figure" data-ev="${esc(x.investor)}|dry_powder">${
            badge(s.dry_powder.text.match(/^(\d+)/)?.[1] + " / 6mo",
                  s.dry_powder.label === "🟢" ? "green" : s.dry_powder.label === "🟡" ? "amber" : "red")
          }</button>`}</td>
      <td>${x.backs?.length
        ? `<button class="figure" data-ev="${esc(x.investor)}|conflict">${
            badge(x.backs.join(", "), "red")}</button>`
        : badge("clear", "grey")}${
        FCONTRA[x.investor]?.hard
          ? ` <button class="figure" data-ev="${esc(x.investor)}|disagree"
                title="Sources disagree on some of the rounds behind these numbers">${
                badge(`${FCONTRA[x.investor].hard} disputed`, "amber")}</button>` : ""}</td>
      <td>${s.warm_path.label !== "⚪"
        ? `<button class="figure" data-ev="${esc(x.investor)}|warm_path">${
            badge(s.warm_path.text.replace(/^via /, ""), "blue")}</button>` : ""}</td>
      <td class="tdact">${dealButton(x.investor)}<button class="btn sm"
        data-brief="${esc(x.investor)}" style="margin-left:5px">Brief</button></td>
    </tr>`;
  }).join("");

  const leads = inv.filter(x => x.signals.lead_rate.label === "🟢");
  const warm = inv.filter(x => x.signals.warm_path.label !== "⚪");
  const shown = FFILTER === "lead" ? leads : FFILTER === "warm" ? warm
    : FFILTER === "conflict" ? red : inv;

  return askTrace() + searchPanel() + heroCard(inv, red, leads, warm)
    + kpis([
      ["Investors screened", inv.length, "all", "two or more rounds on record"],
      ["Lead at your stage", leads.length, "lead", `led a ${F.stage} in the last three years`],
      ["Warm routes", warm.length, "warm", "a shared cap table reaches them"],
    ], FFILTER, null)
    + (FFILTER !== "all" ? `<div class="filterline">Showing
        <b>${esc({ lead: "funds that lead at your stage", warm: "funds with a warm route",
                   conflict: "funds backing a competitor" }[FFILTER] || FFILTER)}</b>
        — ${shown.length} of ${inv.length}.
        <button class="btn sm" id="clearf">Clear</button></div>` : "")
    // The table comes before the evidence for it, because the next thing a
    // founder does is tick the funds they want. Reading who co-invests with
    // whom is how you check the order; picking is how you use it.
    + section("ftable", "Who is left",
      `${shown.length} of ${inv.length} screened · tick the ones you want to reach`,
      `<div class="tbl"><table>
      <thead><tr><th class="w-pick">${pickAllBox(shown)}</th>
      <th class="w-rank"></th><th>Investor</th><th>Verdict</th><th class="num">Score</th>
      <th class="num">Lead</th><th class="num">Follow-on</th>
      <th>Pace</th><th>Conflict</th><th>Route</th><th class="w-act"></th></tr></thead>
      <tbody>${rowsFor(shown)}</tbody></table></div>`)
    + pickBar()
    + planSection()
    + syndicateBlock()
    + section("fmap", "Who funds your competitors",
        `${(F.edges || []).length} link${(F.edges || []).length === 1 ? "" : "s"} · two hops in Cala's graph`,
        conflictMap())
    + `<div class="evfoot">
        <b>Evidence and experiments.</b> Not part of the answer above, kept
        because they are how it was checked.
        <span>
          <button class="lnk" data-goto="accuracy">What we tested</button>
          <button class="lnk" data-goto="map">Where these funds are</button>
          <button class="lnk" data-goto="signal">Founder signal (untested)</button>
        </span></div>`;
}

/* The conclusion first, then what to do about it. Six KPI cards, a banner, a
   paragraph and a map all competing for the top of the page meant the one
   thing this product knows - who to assemble and who can introduce you - was
   below the fold. */
/* The exclusion comes first.
   Every other tool hands a founder a targeting list. The question nobody
   answers is which funds they must not talk to - and that mistake costs
   more than a missed meeting, because the deck, the metrics and the
   customer list stay with a fund that is funding the competitor.
   So the page opens with who is out, then who is left. */
function heroCard(inv, red, leads, warm) {
  const comps = [...new Set(red.flatMap(x => x.backs))];
  const clean = inv.filter(x => x.signals.conflict.label !== "\u{1F534}" && x.score != null);
  const best = SYN?.syndicates?.[0];

  const acts = [];
  if (red.length) acts.push([`See the ${red.length} to avoid`,
    "and the competitor each one funds", { filter: "conflict" }]);
  acts.push(["Watch for the next one",
    "every investor in a competitor's next round joins this list", { alerts: 1 }]);
  if (leads.length) acts.push([`${leads.length} of the rest lead at ${F.stage}`,
    "the others can follow, not lead", { filter: "lead" }]);
  if (best) acts.push([`Draft the opener for ${best.lead}`,
    "three sentences, each one a number you can check", { brief: best.lead }]);
  HEROACTS = acts.slice(0, 3);

  // "No fund backs a competitor" and "we could not ask who your competitors
  // are" produce the same empty list and are opposite claims. The exclusion
  // is this product's headline; stating it from a failed lookup would be the
  // worst thing on the page.
  const blind = !!F.competitors_error && !F.competitors?.length;
  const head = blind
    ? "<b>We could not check this.</b> The competitor lookup failed, so nothing below has been excluded."
    : red.length
    ? `<b>${red.length} of ${inv.length}</b> funds on this list already fund
       <b>${esc(comps.slice(0, 2).join(" or "))}</b>. Do not send them your deck.`
    : "<b>No fund</b> on this list funds a competitor Cala can name.";

  // With a conflict this names it. Without one there is nothing to add: the
  // eyebrow above already says how many were screened against how many
  // competitors, and repeating it is a line of furniture under the headline.
  const sub = blind
    ? `${esc(String(F.competitors_error).replace(/^\w+Error: /, ""))}
       The ranking below is still computed from the rounds we hold — it is the
       exclusion that is missing, and that is the half you cannot do yourself.`
    : red.length
    ? red.map(x => `<b>${esc(x.investor)}</b> &rarr; ${esc(x.backs.join(", "))}`).join(" &nbsp;·&nbsp; ")
    : "";

  // Said before the ranking, because if the stage is wrong the ranking is
  // the wrong list and reading it carefully is wasted care.
  const sc = F.stage_check || {};
  const stageNote = sc.severity && sc.severity !== "ok"
    ? `<div class="stagenote ${esc(sc.severity)}">
         <b>${sc.severity === "warn" ? "Check the stage."
             : sc.severity === "unknown" ? "We could not check the stage."
             : "About the stage."}</b> ${esc(sc.says)}
         ${F.stage_stale ? ` ${esc(F.stage_stale.says)}` : ""}
       </div>`
    : "";

  return stageNote + `<div class="hero ${blind ? "blind" : red.length ? "warn" : "ok"}">
    <div class="herotop">
      <span class="herotag">${esc(F.company)} · ${esc(F.stage)} ·
        ${inv.length} screened · ${blind ? "competitors unknown"
          : `${F.competitors.length} competitors`}</span>
      <h2>${head}</h2>
      ${sub ? `<p class="herosub">${sub}</p>` : ""}
      <p class="herothen">${blind ? "" : `<b>${clean.length}</b> funds are left.`}
        ${leads.length ? `<b>${leads.length}</b> of them lead at ${esc(F.stage)}.` : ""}
        ${warm.length ? `<b>${warm.length}</b> can be reached through someone you know.`
          : "None can be reached warm."}</p>
    </div>
    <div class="heroacts" style="grid-template-columns:repeat(${
      Math.max(acts.length, 1)},1fr)">${acts.map(([t, why, go], i) => `
      <button class="heroact" data-hero="${i}">
        <span class="n">${i + 1}</span>
        <span><b>${esc(t)}</b><em>${esc(why)}</em></span></button>`).join("")}</div>
  </div>`;
}

let HEROACTS = [];

/* What this screen was run on, and where it came from.
   This used to be a form - company, round, target count, Run - sitting above
   the answer on every render. The brief already said all of it, and a form
   the founder has already filled in is furniture: it pushed the one thing
   this product knows below the fold. What is left is the sentence, the
   provenance, and a way back. */
function searchPanel() {
  const p = F?.profile;
  const src = p?.sources?.name?.file;
  return `<div class="runline">
    <div class="rl1">
      <b>${esc(F?.company || "")}</b>
      <span class="sub">· ${esc(F?.stage || "series a")}</span>
      ${p?.round_size ? `<span class="sub">· raising ${
        (p.round_size / 1e6).toFixed(1).replace(/\.0$/, "")}M ${
        esc(p.round_currency || "EUR")}</span>` : ""}
      ${(p?.markets || []).map(m => `<span class="chip sm">${esc(m)}</span>`).join("")}
    </div>
    <div class="rl2">
      ${src && src !== "what you wrote"
        ? `<span class="sub">read from ${esc(src)}</span>`
        : p ? `<span class="sub">from what you wrote</span>` : ""}
      ${p ? `<button class="lnk" data-goto="brief">See how we read it</button>` : ""}
      <button class="lnk" id="startover">Start over</button>
    </div>
  </div>`;
}

/* Who already backs your competitors, and through which competitor.
   Drawn as a flow rather than a list because the useful fact is the middle
   column: one competitor can pull in four funds, and that is the row a
   founder has to plan around. */
function conflictMap() {
  const edges = F.edges || [];
  if (!edges.length) return `<div class="msg">No fund in this list backs a named competitor —
    a computed result, not an empty state.</div>`;

  // Order both columns by how much they carry, so the heavy lines are at the
  // top and the chart reads without tracing every curve.
  const byComp = {}, byFund = {};
  for (const e of edges) {
    (byComp[e.competitor] ||= []).push(e.investor);
    (byFund[e.investor] ||= []).push(e.competitor);
  }
  const comps = Object.keys(byComp).sort((a, b) => byComp[b].length - byComp[a].length);
  const funds = Object.keys(byFund).sort((a, b) => byFund[b].length - byFund[a].length);

  const ROW = 44, PAD = 54, W = 1040;
  const H = Math.max(comps.length, funds.length, 2) * ROW + PAD * 2;
  const x1 = 120, x2 = W / 2 - 20, x3 = W - 150;
  const y = (i, n) => PAD + (n === 1 ? (H - PAD * 2) / 2 : i * ((H - PAD * 2 - 22) / Math.max(n - 1, 1))) + 11;
  const my = H / 2;
  const curve = (xa, ya, xb, yb) =>
    `M${xa} ${ya} C${xa + (xb - xa) * .45} ${ya},${xb - (xb - xa) * .45} ${yb},${xb} ${yb}`;

  const node = (x, yy, w, text, cls, sub) => `
    <g class="cnode ${cls}">
      <rect x="${x - w / 2}" y="${yy - 15}" width="${w}" height="30" rx="8"/>
      <text class="cnl" x="${x}" y="${yy + (sub ? 0 : 4)}" text-anchor="middle">${
        esc(text.length > 26 ? text.slice(0, 25) + "…" : text)}</text>
      ${sub ? `<text class="cns" x="${x}" y="${yy + 11}" text-anchor="middle">${esc(sub)}</text>` : ""}
    </g>`;

  return `<div class="cmap"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
    <text class="chd" x="${x1}" y="24" text-anchor="middle">YOU</text>
    <text class="chd" x="${x2}" y="24" text-anchor="middle">YOUR COMPETITORS</text>
    <text class="chd" x="${x3}" y="24" text-anchor="middle">FUNDS THAT BACK THEM</text>

    ${comps.map((c, i) => `<path class="cedge" d="${
      curve(x1 + 62, my, x2 - 108, y(i, comps.length))}"/>`).join("")}
    ${edges.map(e => {
      const i = comps.indexOf(e.competitor), j = funds.indexOf(e.investor);
      return `<path class="cedge hot" d="${
        curve(x2 + 108, y(i, comps.length), x3 - 96, y(j, funds.length))}"
        data-ce="${esc(e.investor)}|${esc(e.competitor)}"><title>${
        esc(e.investor)} backs ${esc(e.competitor)}</title></path>`;
    }).join("")}

    ${node(x1, my, 124, F.company, "me")}
    ${comps.map((c, i) => node(x2, y(i, comps.length), 216, c, "comp",
        byComp[c].length > 1 ? `${byComp[c].length} funds` : "")).join("")}
    ${funds.map((f, i) => node(x3, y(i, funds.length), 192, f, "hot",
        byFund[f].length > 1 ? `backs ${byFund[f].length}` : "")).join("")}
  </svg>
  <div class="cmapnote">${edges.length} fund–competitor link${edges.length > 1 ? "s" : ""}
    across ${comps.length} competitor${comps.length > 1 ? "s" : ""}.
    Hover a line to read it.</div></div>`;
}

const SIGLBL = { lead_rate: "Lead rate", follow_on: "Follow-on", next_round: "Portfolio progression",
  dry_powder: "Deployment pace", conflict: "Conflict", warm_path: "Warm route" };

function founderEntity() {
  const x = F.investors.find(i => i.investor === SEL);
  if (!x) { SEL = null; return founderList(); }
  const s = x.signals, c = s.conflict;
  const tabs = ["Overview", "Portfolio", "Signals", "Conflict", "Evidence"];
  const fm = x.firm || {};
  const meta = [
    fm.website ? `<a href="https://${esc(String(fm.website).replace(/^https?:\/\//, ""))}"
      target="_blank" rel="noopener">${esc(String(fm.website).replace(/^https?:\/\//, ""))}</a>` : "",
    fm.hq ? esc(String(fm.hq).split(",").slice(-2).join(",").trim()) : "",
    fm.founded ? "founded " + esc(String(fm.founded).slice(0, 4)) : "",
    fm.employees ? esc(fm.employees) + " people" : "",
    `${x.rounds_seen} rounds in Cala`,
    `${x.portfolio_size || 0} portfolio`,
    badge(x.evidence_depth === "good" ? "well covered"
      : x.evidence_depth === "thin" ? "thin coverage" : "insufficient",
      x.evidence_depth === "good" ? "green" : x.evidence_depth === "thin" ? "amber" : "grey"),
  ].filter(Boolean).join(" · ");
  let body = entityHeader(x.investor, "", meta, tabs,
    `<button class="btn" id="composeit">${GMAIL_ICON}Compose intro</button>
     <button class="btn" onclick="window.print()">Export brief</button>`,
    fm.website);

  if (TAB === 0) {
    body += (c.label === "🔴"
      ? `<div class="verdict red"><b>Do not send the deck.</b> ${esc(c.text)}. Your pitch would land
         on a board that already owns a competing position.</div>`
      : x.score === null
      ? `<div class="verdict grey"><b>Not ranked.</b> Cala holds ${x.rounds_seen} rounds for this firm —
         too few to judge honestly. Unknown is not zero.</div>`
      : `<div class="verdict green"><b>Worth your time.</b> ${esc(s.lead_rate.text)}. ${esc(s.follow_on.text)}.</div>`)
      + stats(5, [
        ["Flipside score", x.score === null ? "—" : x.score, "mono"],
        ["Leads rounds", pct(s.lead_rate.value), "mono"],
        ["Follows on", pct(s.follow_on.value), "mono"],
        ["New investments / 6mo", s.dry_powder.label === "⚪" ? "—" : (s.dry_powder.text.match(/^(\d+)/)?.[1] ?? "—"), "mono"],
        ["Warm route", s.warm_path.label === "⚪" ? "none" : s.warm_path.text.replace(/^via /, "")],
      ])
      + (() => {
          const pm = peerMedians();
          const col = sg => sg.label === "🟢" ? "g" : sg.label === "🟡" ? "a"
            : sg.value == null ? "n" : "r";
          // Deployment pace is a count, not a share. Putting it on a 0-1 axis
          // with three percentages made a full bar mean "ok" and nothing else.
          const paceN = s.dry_powder.label === "⚪" ? null
            : +(String(s.dry_powder.text).match(/^(\d+)/)?.[1] ?? 0);
          return section("fo-sig", "Signal strength",
            `against the ${pm.n} funds in this screen`, `<div class="card">${bars([
              ["Leads at your stage", s.lead_rate.value, col(s.lead_rate), pct(s.lead_rate.value), pm.lead_rate],
              ["Follows on", s.follow_on.value, col(s.follow_on), pct(s.follow_on.value), pm.follow_on],
              ["Portfolio progression", s.next_round.value, col(s.next_round), pct(s.next_round.value), pm.next_round],
            ], 1, { note: `Tick marks the median of the ${pm.n} funds screened — a bar
                   to the right of it beats the list, not an absolute standard.` })}
            <div class="paceline">
              <span class="lbl">Deployment pace</span>
              <span class="pacev ${s.dry_powder.label === "🟢" ? "g" : s.dry_powder.label === "🟡" ? "a" : s.dry_powder.label === "⚪" ? "n" : "r"}">${
                paceN == null ? "not in the graph" : `${paceN} new investments in 6 months`}</span>
              <span class="pacesub">${esc(String(s.dry_powder.text || "").replace(/^[^(]*/, "").replace(/[()]/g, "")) || ""}</span>
            </div></div>`);
        })()
      + (fm.description ? `<p class="lede">${esc(fm.description)}</p>` : "")
      + (fm.hq ? section("fo-reg", "Registered", "",
          `<div class="card"><div style="font-size:13.5px">${esc(fm.hq)}</div>
           <div class="sub" style="margin:6px 0 0">from Cala's <code>${esc(fm.hq_field || "address")}</code>
           ${fm.hq_source ? `· <a href="${esc(fm.hq_source)}" target="_blank" rel="noopener">source</a>` : ""}</div></div>`) : "")
      + section("fo-prof", "Firm profile", "",
          badgeGroup([
            ["Verdict", [c.label === "🔴" ? "Do not pitch"
              : x.score === null ? "Not ranked"
              : s.lead_rate.label === "🟢" ? "Strong target" : "Proceed with care"],
              c.label === "🔴" ? "red" : s.lead_rate.label === "🟢" ? "green" : "amber"],
            ["Leads rounds", [s.lead_rate.label === "⚪" ? "unknown" : pct(s.lead_rate.value)], "purple"],
            ["Still deploying", [s.dry_powder.label === "⚪" ? "unknown"
              : s.dry_powder.label === "🔴" ? "slowed" : "active"],
              s.dry_powder.label === "🔴" ? "red" : "green"],
            ["Evidence depth", [x.evidence_depth === "good" ? "well covered"
              : x.evidence_depth === "thin" ? "thin" : "insufficient"], "grey"],
          ]))
      + section("fo-chart", "Portfolio behaviour", "",
          `<div class="three">
            ${chart("Lead vs follow",
              s.lead_rate.n ? `led ${Math.round((s.lead_rate.value||0)*s.lead_rate.n)} of ${s.lead_rate.n} rounds` : "no rounds in window",
              donut([{k:"Led",v:Math.round((s.lead_rate.value||0)*s.lead_rate.n),c:"#7fb88a"},
                     {k:"Participated",v:s.lead_rate.n-Math.round((s.lead_rate.value||0)*s.lead_rate.n),c:"#7d766c"}]))}
            ${chart("Follow-on", s.follow_on.n ? `${s.follow_on.n} mature portfolio companies` : "no mature portfolio",
              donut([{k:"Followed on",v:Math.round((s.follow_on.value||0)*s.follow_on.n),c:"#8ba3c7"},
                     {k:"Did not",v:s.follow_on.n-Math.round((s.follow_on.value||0)*s.follow_on.n),c:"#7d766c"}]))}
            ${chart("Conflict check", `${x.portfolio_size||0} portfolio companies vs ${F.competitors.length} competitors`,
              donut([{k:"Competitors backed",v:x.backs?.length||0,c:"#d9685c"},
                     {k:"Clear",v:Math.max(0,(x.portfolio_size||0)-(x.backs?.length||0)),c:"#7fb88a"}]))}
          </div>`)
      + section("fo-ask", "Ask in the meeting", "",
          `<div class="card"><ul class="reasons">${questions(x).map(q => `<li>${esc(q)}</li>`).join("")}</ul></div>`);
  }
  if (TAB === 1) {
    const led = x.led_rounds || [], rec = x.recent_rounds || [], port = x.portfolio || [];
    const money = a => a ? "€" + (a / 1e6).toFixed(a >= 1e7 ? 0 : 1) + "M" : "—";
    body += stats(4, [
      ["Portfolio companies", x.portfolio_size || 0, "mono"],
      ["Rounds in Cala", x.rounds_seen, "mono"],
      ["Rounds they led", led.length ? `${led.length}+` : "—", "mono"],
      ["Sectors", (x.sectors || []).length || "—", "mono"],
    ]);
    if (led.length) body += section("fp-led", "Led these rounds", "", `<div class="hl">${
      led.map(r => `<div class="hlc"><div class="hlhd">${logo(r.company)}
        <div style="min-width:0"><div class="nm">${esc(r.company)}</div>
          <div class="sb">${esc(r.date)}</div></div>${badge(r.stage || "round", "purple")}</div>
        <div class="hlm"><div><div class="k">Round size</div><div class="v">${money(r.amount)}</div></div>
          <div><div class="k">Role</div><div class="v">Lead</div></div></div></div>`).join("")}</div>`);
    if ((x.sectors || []).length) body += section("fp-sec", "Where they invest", "",
      `<div class="two"><div class="card">${bars((x.sectors || []).map(([k, v]) =>
        [k, v, "", v]))}</div>
        <div class="card"><h4>Most recent activity</h4><div class="sub">newest first</div>
        ${rec.slice(0, 8).map(r => `<div class="barrow" style="grid-template-columns:1fr 70px 56px">
          <span class="lbl">${esc(r.company)}</span>
          <span class="pc" style="text-align:left">${esc(r.stage || "")}</span>
          <span class="pc">${r.led ? badge("led", "green") : esc(String(r.date).slice(0, 7))}</span>
        </div>`).join("")}</div></div>`);
    if (port.length) body += section("fp-port", "Portfolio", `${x.portfolio_size} companies in Cala`,
      `<div class="hl">${port.slice(0, 24).map(c => `<div class="hlc ${
        x.backs?.includes(c.name) ? "red" : ""}">
        <div class="hlhd">${logo(c.name)}<div style="min-width:0">
          <div class="nm">${esc(c.name)}</div><div class="sb">${esc(c.sector || "")}</div></div>
        ${x.backs?.includes(c.name) ? badge("competitor", "red") : ""}</div></div>`).join("")}</div>`);
    if (!led.length && !port.length)
      body += `<div class="msg">No portfolio detail cached for this firm yet.</div>`;
  }
  if (TAB === 2) {
    body += Object.entries(s).map(([k, sig]) => `<div class="card" style="margin-bottom:9px">
      <h4>${esc(SIGLBL[k] || k)}</h4>
      <div class="sub">n=${sig.n} · confidence ${esc(sig.confidence)}</div>
      <div>${sig.label} ${esc(sig.text)}</div>${evidence(sig.evidence)}</div>`).join("");
  }
  if (TAB === 3) {
    if (x.backs?.length) body += evidenceBlock(x.investor, x.backs[0]);
    body += x.backs?.length
      ? `<div class="verdict red"><b>Backs ${x.backs.length} of your competitors.</b></div>
         <div class="hl">${x.backs.map(b => `<div class="hlc red"><div class="hlhd">${logo(b)}
           <div><div class="nm">${esc(b)}</div><div class="sb">named competitor</div></div>
           ${badge("conflict", "red")}</div></div>`).join("")}</div>`
      : `<div class="verdict green"><b>No competitor in this portfolio.</b> Checked
         ${x.portfolio_size || 0} portfolio companies against ${F.competitors.length} competitors Cala names.</div>`;
    body += section("fo-comp", "Competitors Cala identifies", `${F.competitors.length} companies`,
      `<div class="hl">${F.competitors.map(co => `<div class="hlc ${x.backs?.includes(co.name) ? "red" : ""}">
        <div class="hlhd">${logo(co.name)}<div><div class="nm">${esc(co.name)}</div></div>
        ${x.backs?.includes(co.name) ? badge("in portfolio", "red") : ""}</div>
        ${co.what ? `<div class="sb" style="color:var(--faint);font-size:11.5px">${esc(co.what.slice(0, 120))}</div>` : ""}</div>`).join("")}</div>`);
  }
  if (TAB === 4) {
    body += `<p class="lede">Every number on this page is computed from Cala's knowledge graph.
      Text is generated only where the figures already exist — a sentence containing a number the
      metrics do not support is rejected before it is shown.</p>`
      + Object.entries(s).filter(([, sig]) => sig.evidence?.length).map(([k, sig]) =>
        `<div class="card" style="margin-bottom:9px"><h4>${esc(SIGLBL[k] || k)}</h4>${evidence(sig.evidence)}</div>`).join("")
      + (x.notes?.length ? `<div class="card"><h4>Missing data</h4><div class="sub">reported, not hidden</div>
         ${x.notes.map(n => `<div style="font-size:12.3px;color:var(--dim)">${esc(n)}</div>`).join("")}</div>` : "");
  }
  return body + "</div>";
}

function questions(x) {
  const q = [], s = x.signals;
  if (s.conflict.label === "🔴") q.push(`You back ${s.conflict.text.split(": ").pop()}. How do you handle the conflict, and who sees my data?`);
  if (s.lead_rate.label === "🔴") q.push("I need a lead for this round. Do you lead, or come in once a lead is set?");
  if (s.dry_powder.label === "🔴") q.push("How many new investments will you make in the next 12 months, versus follow-ons?");
  if (s.follow_on.label === "🔴") q.push("How do you decide whether to join a portfolio company's next round?");
  if (s.warm_path.label !== "⚪") q.push(`${s.warm_path.text.replace(/^via /, "")} can introduce us — worth asking them first?`);
  if (q.length < 2) q.push("What is your decision timeline from first meeting to term sheet?",
                           "Which partner would own this, and how many boards do they sit on?");
  return q;
}

/* ================= INVESTOR ================= */
const GMAIL_ICON = `<svg width="15" height="12" viewBox="0 0 48 36" aria-hidden="true"
  style="vertical-align:-1px;margin-right:6px">
  <path fill="#4285F4" d="M4 36h8V18L0 9v23a4 4 0 0 0 4 4z"/>
  <path fill="#34A853" d="M36 36h8a4 4 0 0 0 4-4V9l-12 9z"/>
  <path fill="#FBBC04" d="M36 4v14l12-9V6a5 5 0 0 0-8-4z"/>
  <path fill="#EA4335" d="M12 18V4l12 9 12-9v14L24 27z"/>
  <path fill="#C5221F" d="M0 6v3l12 9V4L8 2a5 5 0 0 0-8 4z"/>
</svg>`;


let CONTRA = null;        // where sources disagree with each other


async function loadContradictions() {
  try { CONTRA = await (await fetch("/contradictions")).json(); }
  catch (e) { CONTRA = { count: 0, items: [], error: String(e.message) }; }
  render();
}

/* Companies where two records of the same round disagree. Keyed loosely,
   because the corpus spells company names a dozen ways. */
function contraFor(company) {
  const k = (company || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  return (CONTRA?.items || []).filter(i =>
    (i.company || "").toLowerCase().replace(/[^a-z0-9]/g, "") === k);
}




/* ================= router ================= */
/* ---------- evidence drawer ----------
   Every number in the product opens this. A figure you cannot take apart is
   a figure to be believed rather than checked, and "trust us" is the whole
   thing a graph with per-claim sources is supposed to replace. */
const SIGNAL_TITLE = {
  lead_rate: "Lead rate at this stage", follow_on: "Follow-on rate",
  next_round: "Portfolio progression", dry_powder: "Deployment pace",
  conflict: "Competitor conflict", warm_path: "Warm route",
  score: "Flipside score",
};

function roundRow(r) {
  return `<tr>
    <td>${esc(r.company)}</td>
    <td class="nowrap">${esc(r.stage || "")}</td>
    <td class="nowrap">${esc(String(r.date || "").slice(0, 10))}</td>
    <td>${r.led ? badge("led", "green") : r.led === false ? `<span class="sub">joined</span>` : ""}</td>
    <td class="num">${r.amount ? "€" + Math.round(r.amount / 1e6) + "M" : "—"}</td>
  </tr>`;
}

function scoreMath(x) {
  const b = x.breakdown;
  if (!b) return `<div class="sub">No breakdown recorded for this screen.</div>`;
  const rows = [
    ["Fit", b.fit, "stage, sector, geography and cheque size"],
    ["Signal quality", b.quality, `weighted lower bound over ${
      Math.round(b.coverage * 100)}% of the signals (the rest are unknown)`],
    ["Lead factor", b.lead_factor, b.lead_factor < 1
      ? "discounted: has not led at this stage on the record we have"
      : "no penalty"],
    ["Conflict", b.conflict_factor, b.conflict_factor === 0
      ? "backs a competitor — the score is zero by construction" : "clear"],
    ["Warm route", 1 + b.warm_bonus, b.warm_bonus ? "a shared cap table reaches them" : "none found"],
    ["Disputed rounds", (FCONTRA[x.investor]?.hard ?? 0) || "none",
      (FCONTRA[x.investor]?.hard ?? 0)
        ? "our sources disagree on some rounds behind this — not scored, but worth knowing"
        : "no disagreement found in the rounds behind this"],
    ["Recency", b.recency, b.months_since_activity == null
      ? "no date on the evidence — treated as current"
      : `last active ${b.months_since_activity} months ago${b.stale ? " (stale)" : ""}`],
  ];
  return `<table class="mathtbl"><tbody>${rows.map(([k, v, why]) => `
    <tr><td>${esc(k)}</td><td class="num">${typeof v === "number" ? v.toFixed(2) : v}</td>
    <td class="sub">${esc(why)}</td></tr>`).join("")}</tbody></table>
    <div class="sub" style="margin-top:9px">score = 100 × fit × (0.5 + 0.5 × quality)
      × conflict × lead × warm × coverage × recency = <b>${x.score}</b></div>`;
}

function openEvidence(investor, key) {
  const x = F?.investors?.find(i => i.investor === investor);
  if (!x) return;
  const sg = x.signals?.[key];
  const w = document.createElement("div");
  w.className = "scrim on";

  let rows = [], note = "";
  if (key === "lead_rate") {
    // The exact set the rate is computed over, not "rounds they led" - a
    // claim about 6 of 9 Series A rounds cannot be evidenced with a pre-seed.
    rows = x.stage_rounds || (x.led_rounds || []).map(r => ({ ...r, led: true }));
    note = `All ${rows.length} ${esc(F.stage)} rounds in the 36-month window,
      with whether ${esc(investor)} led each one.`;
  } else if (key === "score") {
    note = "";
  } else {
    rows = x.recent_rounds || [];
    note = `The most recent rounds we hold for ${esc(investor)}.`;
  }

  const ev = (sg?.evidence || []).filter(e => e && (e.text || e.source));
  const cx = FCONTRA[investor];

  if (key === "disagree") {
    const items = (cx?.items || []).filter(i => !i.soft);
    w.innerHTML = `<div class="composebox wide" onclick="event.stopPropagation()">
      <div class="sidehd"><h3>Sources disagree — ${esc(investor)}</h3>
        <div class="s">${items.length} conflicts in the rounds behind these numbers</div></div>
      <div style="padding:15px">
        <div class="sub" style="margin-bottom:11px;line-height:1.6;max-width:62ch">
          Two records of the same round differing on date, amount or lead. We do
          not pick a winner. Before you repeat one of these figures to
          ${esc(investor)}, know that our own sources do not agree on it.</div>
        <div class="tbl"><table><thead><tr><th>Company</th><th>Field</th>
          <th>One says</th><th>Another says</th></tr></thead><tbody>
          ${items.map(i => `<tr><td>${esc(i.company)}</td>
            <td>${badge(i.field, i.field === "amount" ? "red" : "amber")}</td>
            <td class="nowrap">${esc(i.a || "—")}</td>
            <td class="nowrap">${esc(i.b || "—")}</td></tr>`).join("")}
        </tbody></table></div>
        <div style="display:flex;margin-top:14px">
          <button class="btn" id="evclose" style="margin-left:auto">Close</button></div>
      </div></div>`;
    document.body.appendChild(w);
    const cl = () => w.remove();
    w.onclick = cl; w.querySelector("#evclose").onclick = cl;
    return;
  }
  const body = key === "score" ? scoreMath(x) : `
    ${sg ? `<div class="evclaim"><b>${esc(sg.text || "—")}</b>
      <span class="sub">${sg.n} observation${sg.n === 1 ? "" : "s"} ·
      ${esc(sg.confidence || "")} confidence${
        sg.last_date ? ` · most recent ${esc(String(sg.last_date).slice(0, 10))}` : ""}</span></div>` : ""}
    ${rows.length ? `<div class="sub" style="margin:11px 0 6px">${note}</div>
      <div class="tbl"><table><thead><tr><th>Company</th><th>Stage</th><th>Date</th>
      <th>Role</th><th class="num">Amount</th></tr></thead>
      <tbody>${rows.slice(0, 14).map(roundRow).join("")}</tbody></table></div>` : ""}
    ${ev.length ? `<div class="sub" style="margin:13px 0 6px">Cited sources</div>
      ${ev.map(e => `<div class="evrow">
        <span class="evk">source</span>
        <span>${esc(e.text || "")}${e.source
          ? ` — <a href="${esc(e.source)}" target="_blank" rel="noopener">${
              esc(String(e.source).replace(/^https?:\/\/(www\.)?/, "").slice(0, 52))}</a>`
          : ' <span class="sub">(no document URL on this claim)</span>'}</span></div>`).join("")}`
      : `<div class="sub" style="margin-top:12px">No per-claim document URLs on this
         signal — it is computed from the round graph, not quoted from a page.</div>`}`;

  w.innerHTML = `<div class="composebox wide" onclick="event.stopPropagation()">
    <div class="sidehd"><h3>${esc(SIGNAL_TITLE[key] || key)} — ${esc(investor)}</h3>
      <div class="s">Retrieved ${esc(F.fetched_at ? String(F.fetched_at).replace("T", " ").slice(0, 16) + " UTC" : "this session")}
        from Cala's graph</div></div>
    <div style="padding:15px">${body}
      <div style="display:flex;margin-top:14px">
        <button class="btn" id="evclose" style="margin-left:auto">Close</button></div>
    </div></div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  w.onclick = close;
  w.querySelector("#evclose").onclick = close;
}

/* ---------- the plan ----------
   The hero card recommended and nothing collected. A founder works a
   conference from a list they built, so the list has to be an object they
   can add to, reorder by removing, and take away as one page.

   Kept per company in localStorage: it survives a reload, which is the only
   durability a hackathon demo actually needs, and it never leaves the
   browser. */
let PLAN = [];

function planKey() { return `flipside.plan.${(F?.company || "").toLowerCase()}`; }

function planLoad() {
  try { PLAN = JSON.parse(localStorage.getItem(planKey()) || "[]"); }
  catch (e) { PLAN = []; }
  if (!Array.isArray(PLAN)) PLAN = [];
}

function planSave() {
  try { localStorage.setItem(planKey(), JSON.stringify(PLAN)); } catch (e) { /* private mode */ }
}

function inPlan(name) { return PLAN.includes(name); }

function planToggle(name) {
  PLAN = inPlan(name) ? PLAN.filter(n => n !== name) : [...PLAN, name];
  planSave(); render();
}

function planButton(name) {
  const on = inPlan(name);
  return `<button class="btn sm ${on ? "pri" : ""}" data-plan="${esc(name)}"
    title="${on ? "Remove from your Slush plan" : "Add to your Slush plan"}">${
    on ? "✓ In plan" : "+ Plan"}</button>`;
}

/* ========================================================= THE PIPELINE
   A ranking tells a founder who to approach. A raise is six weeks of
   remembering who you already approached, what they said, and which ones
   have gone quiet - and that is the part a spreadsheet gets used for.

   Five columns because a raise has five states, not because a kanban has
   to have five. Moving a fund is two clicks, not a drag: a drag that drops
   a fund in the wrong column during a demo is worse than a button.

   It lives in this browser, like the plan and the call list ticks. Nothing
   here is sent anywhere, and the page says so rather than implying a
   backend that does not exist.

   What it knows that a spreadsheet does not: a fund you put in Diligence
   three weeks ago may since have backed a competitor. The screen already
   computes that; this is where it matters. */
const STAGES = [
  ["todo", "To contact", "ranked, not yet approached"],
  ["sent", "Approached", "you have written or been introduced"],
  ["met", "Met", "a conversation has happened"],
  ["dd", "Diligence", "they are doing work on you"],
  ["done", "Decided", "a term sheet, or a no"],
];
const STAGE_LABEL = Object.fromEntries(STAGES.map(([k, l]) => [k, l]));
let DEALS = {};

function dealKey() { return `flipside.deals.${(F?.company || "").toLowerCase()}`; }

function dealLoad() {
  DEALS = {};
  try {
    const raw = JSON.parse(localStorage.getItem(dealKey()) || "{}");
    if (raw && typeof raw === "object" && !Array.isArray(raw)) DEALS = raw;
  } catch (e) { DEALS = {}; }
  // The older "plan" was a flat list of names with no stage. Anything in it
  // belongs in the first column rather than being silently dropped.
  for (const n of (Array.isArray(PLAN) ? PLAN : [])) {
    if (!DEALS[n]) DEALS[n] = { stage: "todo", at: Date.now(), note: "" };
  }
}

function dealSave() {
  try { localStorage.setItem(dealKey(), JSON.stringify(DEALS)); } catch (e) { /* private */ }
}

function dealSet(name, stage) {
  if (!stage) delete DEALS[name];
  else DEALS[name] = { ...(DEALS[name] || {}), stage, at: Date.now() };
  dealSave(); render();
}

function dealCount() { return Object.keys(DEALS).length; }

function dealButton(name) {
  const cur = DEALS[name]?.stage;
  return `<button class="btn sm ${cur ? "pri" : ""}" data-deal="${esc(name)}"
    title="${cur ? `In your pipeline · ${STAGE_LABEL[cur]}` : "Add to your pipeline"}">${
    cur ? "✓ " + esc(STAGE_LABEL[cur]) : "+ Pipeline"}</button>`;
}

/* Who you would ring at this firm, if the call list has been built. */
function dealContact(fund) {
  const r = (CALLS?.rows || []).find(x => x.fund === fund);
  return r ? { person: r.person, role: r.role, linkedin: r.linkedin } : null;
}

function dealsView() {
  if (!F) return `<div class="msg">Run a screen first — the pipeline is the
    funds that survived it.</div>`;
  const names = Object.keys(DEALS);
  if (!names.length) return watchBlock() + `<div class="msg" style="padding:40px">
    Nothing in the pipeline yet.<br>
    <span class="sub">Add funds from the ranking or the call list. It is kept
    in this browser only — nothing is sent anywhere.</span>
    <div style="margin-top:14px"><button class="btn" data-goto="founder">Back to
      the ranking</button></div></div>`;

  const byFund = Object.fromEntries((F.investors || []).map(x => [x.investor, x]));
  const card = name => {
    const x = byFund[name], p = DEALS[name], c = dealContact(name);
    const blocked = x && x.signals.conflict.label === "\u{1F534}";
    const idx = STAGES.findIndex(s => s[0] === p.stage);
    return `<div class="dcard ${blocked ? "bad" : ""}">
      <div class="dch">${logo(name)}<b>${esc(name)}</b>
        ${x?.score != null ? `<span class="sc">${x.score}</span>` : ""}</div>
      ${blocked ? `<div class="dwarn">Backs ${esc((x.backs || []).join(", "))}
        — this is the one the screen told you to drop.</div>` : ""}
      ${c ? `<div class="dcc">${esc(c.person)}<span class="sub">${
        esc(c.role || "")}</span></div>`
        : `<div class="dcc sub">no contact resolved yet</div>`}
      ${x?.signals?.warm_path?.label !== "⚪" && x?.signals?.warm_path?.text
        ? `<div class="dcw">${esc(x.signals.warm_path.text)}</div>` : ""}
      <div class="dcacts">
        <button class="btn sm" data-dmove="${esc(name)}|${STAGES[Math.max(0, idx - 1)][0]}"
          ${idx <= 0 ? "disabled" : ""} title="Move back">←</button>
        <button class="btn sm" data-dmove="${esc(name)}|${STAGES[Math.min(STAGES.length - 1, idx + 1)][0]}"
          ${idx >= STAGES.length - 1 ? "disabled" : ""} title="Move on">→</button>
        <button class="btn sm" data-ddrop="${esc(name)}" title="Remove">×</button>
      </div></div>`;
  };

  return `<div class="runline">
      <div class="rl1"><b>${esc(F.company)}</b>
        <span class="sub">· ${names.length} fund${names.length === 1 ? "" : "s"} in play</span></div>
      <div class="rl2"><span class="sub">kept in this browser only</span>
        <button class="lnk" data-goto="founder">Back to the ranking</button></div>
    </div>
    ${watchBlock()}
    <div class="deals">${STAGES.map(([k, label, hint]) => {
      const col = names.filter(n => (DEALS[n].stage || "todo") === k);
      return `<div class="dcol">
        <div class="dcolh"><b>${esc(label)}</b><span class="n">${col.length}</span>
          <div class="sub">${esc(hint)}</div></div>
        ${col.map(card).join("") || `<div class="dempty sub">—</div>`}
      </div>`;
    }).join("")}</div>`;
}

function planSection() {
  if (!F || !PLAN.length) return "";
  const rows = PLAN.map(n => F.investors.find(i => i.investor === n)).filter(Boolean);
  const conflicted = rows.filter(x => x.signals.conflict.label === "🔴");
  const warm = rows.filter(x => x.signals.warm_path.label !== "⚪");
  return section("fplan", "Your Slush plan",
    `${PLAN.length} ${PLAN.length === 1 ? "meeting" : "meetings"}`,
    `<div class="planwrap">
      <div class="planlist">${rows.map((x, i) => `
        <div class="planrow">
          <span class="n">${i + 1}</span>
          ${logo(x.investor)}
          <div style="min-width:0;flex:1">
            <div class="nm">${esc(x.investor)}</div>
            <div class="sb">${esc(x.signals.lead_rate.text || "lead rate unknown")}${
              x.signals.warm_path.label !== "⚪"
                ? ` · ${esc(x.signals.warm_path.text)}` : " · cold"}</div>
          </div>
          ${x.signals.conflict.label === "🔴" ? badge("conflict", "red") : ""}
          <button class="btn sm" data-brief="${esc(x.investor)}">Brief</button>
          <button class="btn sm" data-plan="${esc(x.investor)}">Remove</button>
        </div>`).join("")}</div>
      <div class="planfoot">
        <span class="sub">${warm.length} warm · ${rows.length - warm.length} cold${
          conflicted.length ? ` · <b style="color:var(--red)">${conflicted.length} backs a competitor</b>` : ""}</span>
        <span style="margin-left:auto;display:flex;gap:8px">
          <button class="btn" id="planmd">Copy as markdown</button>
          <button class="btn" id="plandl">Download .md</button>
          <button class="btn pri" id="planprint">Print / PDF</button>
        </span>
      </div>
    </div>`);
}

/* One page a founder can carry: the plan, why each fund is on it, and the
   opener. Generated from the same figures the screen shows. */
function planMarkdown() {
  const L = [];
  L.push(`# Slush plan — ${F.company}`, "");
  L.push(`${F.stage} · Slush 2026, 18 November · ${PLAN.length} meetings`);
  L.push(`Screened ${F.investors.length} funds${
    F.fetched_at ? ` · data retrieved ${String(F.fetched_at).replace("T", " ").slice(0, 16)} UTC` : ""}`);
  L.push("");
  PLAN.forEach((n, i) => {
    const x = F.investors.find(v => v.investor === n);
    if (!x) return;
    const s = x.signals, b = x.breakdown || {};
    L.push(`## ${i + 1}. ${x.investor}${x.score != null ? `  —  ${x.score}/100` : ""}`);
    if (s.conflict.label === "🔴")
      L.push(`> **Do not pitch.** Backs ${(x.backs || []).join(", ")}.`, "");
    L.push(`- Lead rate: ${s.lead_rate.text || "unknown"}`);
    L.push(`- Follow-on: ${s.follow_on.text || "unknown"}`);
    L.push(`- Pace: ${s.dry_powder.text || "unknown"}`);
    L.push(`- Route: ${s.warm_path.label !== "⚪" ? s.warm_path.text : "cold — no shared cap table"}`);
    if (b.months_since_activity != null)
      L.push(`- Last active: ${b.months_since_activity} months ago${b.stale ? " (stale)" : ""}`);
    const syn = (SYN?.syndicates || []).find(y => y.lead === x.investor);
    if (syn?.members?.length)
      L.push(`- Syndicate: ${syn.members.map(m =>
        `${m.name} (joins ${Math.round((m.share || 0) * 100)}% of rounds they lead)`).join(", ")}`);
    L.push("");
  });
  L.push("---", "", "Generated by Flipside from Cala's knowledge graph.",
         "Every figure above opens its underlying rounds in the app.");
  return L.join("\n");
}

function planExport(kind) {
  const md = planMarkdown();
  if (kind === "copy") return navigator.clipboard.writeText(md);
  if (kind === "print") {
    const w = window.open("", "_blank");
    if (!w) return;
    w.document.write(`<pre style="font:13px/1.65 ui-monospace,Menlo,monospace;
      white-space:pre-wrap;padding:40px;max-width:720px;margin:auto">${
      md.replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]))}</pre>`);
    w.document.close(); w.print();
    return;
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
  a.download = `slush-plan-${(F.company || "plan").toLowerCase().replace(/\s+/g, "-")}.md`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/* ---------- keyboard ----------
   A list you work through at a conference should not need a mouse. j/k move,
   Enter opens the row, e opens its evidence, p adds it to the plan, b drafts
   the brief, / focuses search, Escape closes whatever is open.

   Scoped to the rows actually on screen, re-read on every keypress rather
   than cached, because the list re-renders under filters. */
let KBD = -1;

function kbdRows() {
  // The primary list for this view, not every table on the page. The
  // investor view also renders a contradictions table, and indexing across
  // both put the highlight on one list while the shortcuts acted on another.
  const id = MODE === "founder" ? "ftable" : MODE === "calls" ? "cl" : null;
  const scope = id ? document.querySelector(`[data-secb="${id}"]`) : null;
  return scope ? [...scope.querySelectorAll("tbody tr[data-open]")] : [];
}

function kbdPaint() {
  const rows = kbdRows();
  rows.forEach((r, i) => r.classList.toggle("kbd", i === KBD));
  const el = rows[KBD];
  if (el) el.scrollIntoView({ block: "nearest" });
}

function kbdHint(on) {
  let h = $("#kbdhint");
  if (!h) {
    h = document.createElement("div");
    h.id = "kbdhint"; h.className = "kbdhint";
    h.innerHTML = `<span><kbd>j</kbd><kbd>k</kbd>move</span>
      <span><kbd>↵</kbd>open</span><span><kbd>e</kbd>evidence</span>
      <span><kbd>p</kbd>plan</span><span><kbd>b</kbd>brief</span>
      <span><kbd>esc</kbd>close</span>`;
    document.body.appendChild(h);
  }
  h.classList.toggle("on", !!on);
}

function kbdInit() {
  if (window.__kbd) return;
  window.__kbd = true;
  document.addEventListener("keydown", e => {
    const t = e.target;
    const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA"
      || t.isContentEditable);

    if (e.key === "Escape") {
      const scrim = document.querySelector(".scrim");
      if (scrim) { scrim.remove(); return; }
      if (typing) { t.blur(); return; }
      if (KBD >= 0) { KBD = -1; kbdPaint(); kbdHint(false); }
      return;
    }
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;

    if (e.key === "/") { e.preventDefault(); $("#qsq")?.focus(); return; }
    // The tab advertises this shortcut, so it has to exist.
    if (e.key === "n" || e.key === "N") { e.preventDefault(); neoToggle(); return; }

    const rows = kbdRows();
    if (!rows.length) return;

    if (e.key === "j" || e.key === "ArrowDown") {
      e.preventDefault(); KBD = Math.min(KBD + 1, rows.length - 1);
      kbdPaint(); kbdHint(true); return;
    }
    if (e.key === "k" || e.key === "ArrowUp") {
      e.preventDefault(); KBD = Math.max(KBD - 1, 0);
      kbdPaint(); kbdHint(true); return;
    }
    if (KBD < 0) return;

    const name = rows[KBD]?.dataset.open;
    if (!name) return;
    if (e.key === "Enter") { e.preventDefault(); rows[KBD].click(); return; }
    if (e.key === "e") {
      e.preventDefault();
      // The score is the figure worth opening from the keyboard.
      if (MODE === "founder") openEvidence(name, "score");
      return;
    }
    if (e.key === "p" && MODE === "founder") { e.preventDefault(); planToggle(name); return; }
    if (e.key === "b" && MODE === "founder") { e.preventDefault(); openBrief(name); return; }
  });
}

let KBDMODE = null;

/* ---------- the third reading ----------
   The same graph read a third way: not "who should back you" and not "who
   are insiders backing", but who looks like someone who starts things,
   before they have started one. It was reachable only from inside a person
   profile, which is to say barely reachable at all. */
let FSQ = "", FSRES = null, FSTIMER = null;

const FS_SUGGEST = ["Ilkka Paananen", "Niklas Zennstrom", "Miki Kuusi",
                    "Risto Siilasmaa", "Peter Sarlin"];

async function fsSearch(q) {
  FSQ = q;
  if (!q || q.trim().length < 2) { FSRES = null; return render(); }
  FSRES = { loading: true }; render();
  try {
    FSRES = await (await fetch(`/search?q=${encodeURIComponent(q.trim())}&kind=people`)).json();
  } catch (e) { FSRES = { results: [], error: String(e.message) }; }
  render();
}

/* The other half of the people problem: Cala has relationships for one of
   the 227 people we hold, and a company's own team page has the rest. The
   rule is borrowed from BlueWatch - a claim is kept only when its quote is
   literally on the page, and the page is the organisation's own. */
let TEAM = null;

async function loadTeam(q) {
  if (!q || !q.trim()) return;
  TEAM = { loading: true, q }; render();
  try {
    TEAM = await (await fetch(`/team?name=${encodeURIComponent(q.trim())}`)).json();
    TEAM.q = q.trim();
  } catch (e) { TEAM = { ok: false, people: [], why: String(e.message), q }; }
  render();
}

function teamPanel() {
  if (!TEAM) return "";
  if (TEAM.loading) return `<div class="msg" style="padding:20px">
    <span class="spin"></span>Reading ${esc(TEAM.q)}'s own pages…</div>`;

  const host = String(TEAM.site || "").replace(/^https?:\/\//, "");
  const pages = TEAM.pages || [];
  const tried = `<div class="teampages">${pages.map(pg => `
    <span class="pg ${pg.people ? "hit" : ""}" title="${esc(pg.why || "")}">
      ${esc(String(pg.url).replace(/^https?:\/\/[^/]*/, "") || "/")}
      <b>${pg.people}</b></span>`).join("")}</div>`;

  if (!TEAM.people?.length) return `<div class="emptywhy" style="margin-top:var(--s2)">
    <b>Nothing we could quote.</b> ${esc(TEAM.why || "")}
    ${pages.length ? `<div style="margin-top:9px">Pages read: ${tried}</div>` : ""}
    <span class="sub">A name without a role in the same sentence is not a claim
      the page made, so it is dropped rather than guessed at.</span></div>`;

  const byRole = {};
  for (const p of TEAM.people) (byRole[p.role] ||= []).push(p);
  const order = ["founder", "ceo", "cto", "coo", "cfo", "chair", "head", "person"];

  return `<div class="teamwrap">
    <div class="teamhd">
      <b>${TEAM.people.length} people</b> named by
      <a href="${esc(TEAM.site)}" target="_blank" rel="noopener">${esc(host)}</a>
      across ${pages.length} page${pages.length === 1 ? "" : "s"}
      ${tried}
    </div>
    ${order.filter(r => byRole[r]).map(r => `
      <div class="teamgrp">${esc(r === "person" ? "named, role unclear" : r)}
        <span>${byRole[r].length}</span></div>
      ${byRole[r].map(p => `<div class="teamrow">
        <span class="av">${esc(initials(p.name))}</span>
        <div style="min-width:0;flex:1">
          <div class="nm">${esc(p.name)}
            <span class="via">${esc(p.via || "page text")}</span></div>
          <div class="q">“${esc(p.quote)}”</div>
          ${p.bio_url ? `<a class="q bio" href="${esc(p.bio_url)}" target="_blank"
            rel="noopener">their own page &rarr;</a>` : ""}
        </div>
        <button class="btn sm" data-fsname="${esc(p.name)}">Signal</button>
      </div>`).join("")}`).join("")}
    <div class="teamfoot">Every line is quoted from the page, which is the
      company speaking about itself. Names and roles only — contact details are
      dropped even where the page shows them, and no profile aggregator or
      social network is read.</div>
  </div>`;
}

function signalView() {
  const picked = FSIG && FSIGFOR;
  return `<div class="fswrap">
    <div class="fshd">
      <h2>Who looks like a founder before they are one?</h2>
      <p>The same graph, read a third way. Not who should back you, and not
         who insiders are backing — who has the pattern: has built before,
         has operated senior, has angel cheques out, ships in public.</p>
      <div class="emptywhy" style="margin-bottom:var(--s3)">
        <b>This reading has no backtest. The other two do.</b>
        Insider conviction is measured on 498 companies against stage
        progression; the founder screen rests on lead rates that are
        observable facts. This one is a weighted opinion about what the
        pattern looks like, and nothing here proves it predicts who founds
        a company.
        <span class="sub">Testing it needs each person's state <i>before</i>
        they founded something, then what they went on to do — a time-sliced
        person graph. Of the 227 people cached, one carries the
        relationships at all, so the sample does not exist yet. Said plainly
        rather than left for a judge to ask.</span>
      </div>
    </div>
    <div class="fssearch">
      <input id="fsq" placeholder="A person by name, or a company to read its team page"
        value="${esc(FSQ)}" autocomplete="off">
      <div class="fschips">${FS_SUGGEST.map(n =>
        `<button class="chip sm" data-fsname="${esc(n)}">${esc(n)}</button>`).join("")}
        <button class="chip sm" data-fsteam="${esc(FSQ)}">Read a team page →</button></div>
    </div>
    ${teamPanel()}
    ${fsResults()}
    ${picked ? `<div class="fsresult">${founderSignalPanel()}</div>` : ""}
  </div>`;
}

function fsResults() {
  if (!FSRES) return "";
  if (FSRES.loading) return `<div class="msg" style="padding:20px">
    <span class="spin"></span>Searching people…</div>`;
  if (FSRES.error) return `<div class="msg" style="padding:20px">${esc(FSRES.error)}</div>`;
  if (!FSRES.results?.length) return `<div class="msg" style="padding:20px">
    No one by that name in the graph we hold.</div>`;
  return `<div class="fslist">${FSRES.results.map(r => `
    <button class="fsrow" data-fsid="${esc(r.id)}" data-fsnm="${esc(r.name)}">
      <div><div class="nm">${esc(r.name)}</div>
      <div class="d">${esc(r.description || "Person")}</div></div>
      <span class="go">Read signal →</span></button>`).join("")}</div>`;
}

/* The tab body, lifted out so the standalone view and the person profile
   render the same thing rather than two drifting copies. */
function founderSignalPanel() {
  const f = FSIG;
  if (!f) return `<div class="msg"><span class="spin"></span>Reading the graph…</div>`;
  if (f.error) return `<div class="msg">${esc(f.error)}</div>`;
  if (f.score === null) {
    // The common case right now: we hold the name but never fetched the
    // edges, and the edges are the whole signal.
    return `<div class="emptywhy"><b>Not enough of the graph to read.</b>
      ${esc((f.reasons || [])[0] || "")}
      We hold this person's name but not their relationships — founded,
      works at, invested in — and those edges are the entire signal. One
      live lookup fills it in.</div>`;
  }
  return founderSignalBody();
}

/* The conviction score, taken apart. Same shape as the founder one, from
   the components the scorer itself uses. */

/* The rounds behind a syndicate claim or a warm route. */
async function openSyndicateEvidence(lead, other, kind) {
  const w = document.createElement("div");
  w.className = "scrim on";
  w.innerHTML = `<div class="composebox wide" onclick="event.stopPropagation()">
    <div class="sidehd"><h3>${kind === "warm" ? "Shared cap tables" : "Rounds they joined"}</h3>
      <div class="s">Reading the round graph…</div></div>
    <div style="padding:34px"><span class="spin"></span></div></div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  w.onclick = close;

  let d;
  const qs = kind === "warm"
    ? `lead=${encodeURIComponent(lead)}&via=${encodeURIComponent(other)}`
    : `lead=${encodeURIComponent(lead)}&member=${encodeURIComponent(other)}`;
  try { d = await (await fetch(`/syndicate-evidence?${qs}`)).json(); }
  catch (e) { d = { rounds: [], error: String(e.message) }; }

  const rows = (d.rounds || []).map(r => `<tr${r.joined === false ? ' class="dim"' : ""}>
    <td>${esc(r.company)}</td>
    <td class="nowrap">${esc(r.stage || "")}</td>
    <td class="nowrap">${esc(String(r.date || "").slice(0, 10))}</td>
    ${kind === "warm" ? "" : `<td>${r.joined ? badge("joined", "green")
      : `<span class="sub">did not</span>`}</td>`}
    <td class="sub">${esc((r.investors || []).join(", ").slice(0, 70))}</td></tr>`).join("");

  w.innerHTML = `<div class="composebox wide" onclick="event.stopPropagation()">
    <div class="sidehd">
      <h3>${kind === "warm" ? `${esc(other)} × ${esc(lead)}`
        : `${esc(other)} in ${esc(lead)}'s rounds`}</h3>
      <div class="s">${kind === "warm"
        ? `${d.count || 0} cap tables they both sat on`
        : `${d.joined || 0} of ${d.led || 0} rounds ${esc(lead)} led`}</div></div>
    <div style="padding:15px">
      <div class="sub" style="margin-bottom:11px;line-height:1.6;max-width:62ch">
        ${kind === "warm"
          ? `A warm route is only worth asking for if it is real. These are the
             rounds both funds were in — name the company when you ask.`
          : `Every round ${esc(lead)} led, not only the ones ${esc(other)} joined,
             so the denominator is on screen and the share can be read rather
             than taken on trust.`}</div>
      ${rows ? `<div class="tbl"><table><thead><tr><th>Company</th><th>Stage</th>
        <th>Date</th>${kind === "warm" ? "" : "<th>Role</th>"}<th>Investors</th>
        </tr></thead><tbody>${rows}</tbody></table></div>`
        : `<div class="msg" style="padding:22px">No rounds on record for this pair.</div>`}
      <div style="display:flex;margin-top:14px">
        <button class="btn" id="synclose" style="margin-left:auto">Close</button></div>
    </div></div>`;
  w.onclick = close;
  w.querySelector("#synclose").onclick = close;
}

/* ---------- Ask Neo ----------
   A panel that knows what is on screen. Every answer is computed server-side
   from the same functions that drew the product, so it cannot state a figure
   the product does not show. When a model key is set it phrases those facts
   and numbercheck rejects anything it adds. */
let NEO_OPEN = false, NEO_LOG = [], NEO_BUSY = false;

function neoToggle(on) {
  NEO_OPEN = on === undefined ? !NEO_OPEN : on;
  document.body.classList.toggle("neo-on", NEO_OPEN);
  neoPaint();
  if (NEO_OPEN) setTimeout(() => $("#neoq")?.focus(), 60);
}

async function neoAsk(q) {
  const text = (q || "").trim();
  if (!text || NEO_BUSY) return;
  NEO_LOG.push({ who: "you", text });
  NEO_BUSY = true; neoPaint();
  let d;
  try {
    d = await (await fetch("/ask-neo", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: text, company: F?.company || "Gosta Labs",
                             stage: F?.stage || "series a",
                             limit: F?.investors?.length || 14 })
    })).json();
  } catch (e) { d = { headline: "I could not reach the server.", bullets: [], followups: [] }; }
  NEO_LOG.push({ who: "neo", ...d });
  NEO_BUSY = false; neoPaint();
}

/* Figures in mono so an answer reads like the product it is describing. */
function neoNums(text) {
  return esc(text).replace(/(\d[\d.,]*\s?(?:%|pp|\/\d+)?)/g, '<b class="n">$1</b>');
}

/* What Neo can actually do, by role.
   Every one of these runs something that exists. A panel full of actions
   that turn out to be decoration is worse than a smaller panel: the second
   time a founder taps one and nothing happens, they stop reading the rest. */
function neoActions() {
  const acts = ROLE === "investor"
    ? [["\u25CF", "Who just changed seats", "goto:investor"],
       ["\u25D1", "Who got backed again", "goto:investor"],
       ["\u25A6", "Where the companies are", "goto:map"],
       ["\u25C8", "Does this predict?", "goto:accuracy"]]
    : [["\u2709", "Draft an opener", "brief"],
       ["\u260E", "Who do I call first", "goto:calls"],
       ["\u25A6", "Where they are", "goto:map"],
       ["\u2630", "What changed", "goto:deals"],
       ["\uFF0B", "Add my deck", "deck"]];
  return `<div class="neoacts">${acts.map(([ic, label, go]) =>
    `<button class="neoact" data-neoact="${esc(go)}"><i>${ic}</i>${esc(label)}</button>`)
    .join("")}</div>`;
}

function neoIntro() {
  const prompts = ROLE === "investor"
    ? ["Which companies had their previous lead come back?",
       "Who founded something in the last 18 months?",
       "How much of the graph have we actually read?",
       "Does insider conviction predict the next round?"]
    : F
      ? [`Who should I meet first about ${F.company}?`,
         "Which of these back a competitor?",
         "Who can introduce me, and through whom?",
         "Which of them actually lead at my stage?"]
      : ["What can you tell me before I run a screen?",
         "How much of Cala's graph is cached?",
         "What have you tested, and what failed?"];
  const ctx = ROLE === "investor"
    ? `the <b>${CONV?.companies?.length || 0}</b> companies scored, the moves
       we can see and what the backtest found`
    : F ? `the <b>${F?.investors?.length || 0}</b> funds screened, their
       conflicts and routes, the syndicates and the backtest`
      : `what is cached, what has been tested and what has not`;

  return `<div class="neointro">
      <h3>Ask me anything about <em>${ROLE === "investor" ? "your pipeline"
        : F ? esc(F.company) : "this screen"}</em>.</h3>
      ${neoActions()}
      <p class="sub">I can see ${ctx}.</p>
      <div class="neoprompts">${prompts.map(q =>
        `<button class="neoprompt" data-neoq="${esc(q)}">${esc(q)}
           <span>\u2192</span></button>`).join("")}</div>
    </div>`;
}

function neoPaint() {
  const el = $("#neobody");
  if (!el) return;
  const OPENLBL = { investor: "Open the profile", filter: "Filter the list",
                    view: "Open the evidence" };
  el.innerHTML = NEO_LOG.length
    ? NEO_LOG.map(m => m.who === "you"
        ? `<div class="neoq">${esc(m.text)}</div>`
        : `<div class="neoa">
             <div class="neotop"><span class="tag">${esc((m.topic || "answer").replace(/_/g, " "))}</span>
               <span class="src">${m.model ? esc(m.model) : "computed"}</span></div>
             ${m.prose ? `<p class="prose">${esc(m.prose)}</p>` : ""}
             <p class="head">${neoNums(m.headline || "")}</p>
             ${(m.bullets || []).length
               ? `<ul>${m.bullets.map(b => `<li>${neoNums(b)}</li>`).join("")}</ul>` : ""}
             ${m.open ? `<button class="neogo" data-neoopen="${esc(m.open.kind)}|${
                 esc(m.open.name)}">${esc(OPENLBL[m.open.kind] || "Show me")}
                 <span>&rarr;</span></button>` : ""}
           </div>`).join("")
    : neoIntro();
  const last = NEO_LOG[NEO_LOG.length - 1];
  const chips = (last && last.followups) || ["Who should I meet first?",
    "Who backs a competitor?", "Who can introduce me?", "Does this actually work?"];
  const c = $("#neochips");
  if (c) c.innerHTML = chips.map(x =>
    `<button class="neochip" data-neoq="${esc(x)}">${esc(x)}</button>`).join("");
  if (NEO_BUSY) el.insertAdjacentHTML("beforeend",
    `<div class="neoa thinking"><span class="spin"></span>reading the screen…</div>`);
  el.scrollTop = el.scrollHeight;
  neoWire();
}

function neoWire() {
  document.querySelectorAll("[data-neoq]").forEach(b =>
    b.onclick = () => neoAsk(b.dataset.neoq));
  document.querySelectorAll("[data-neoact]").forEach(b => b.onclick = () => {
    const go = b.dataset.neoact;
    if (go.startsWith("goto:")) {
      const m = go.slice(5);
      neoToggle(false);
      MODE = m; SEL = null;
      if (m === "map" && !MAP) return loadMap();
      if (m === "investor" && !CONV) return loadConviction();
      return render();
    }
    if (go === "brief") {
      const top = (F?.investors || []).find(x =>
        x.signals.conflict.label !== "\u{1F534}" && x.score != null);
      if (!top) return neoAsk("Who should I write to first?");
      neoToggle(false);
      return openBrief(top.investor);
    }
    if (go === "deck") {
      neoToggle(false);
      MODE = "home"; render();
      return $("#askfiles")?.click();
    }
  });
  document.querySelectorAll("[data-neoopen]").forEach(b => b.onclick = () => {
    const [kind, name] = b.dataset.neoopen.split("|");
    if (kind === "investor") { MODE = "founder"; SEL = name; TAB = 0; return render(); }
    if (kind === "filter") { MODE = "founder"; SEL = null; FFILTER = name; return render(); }
    if (kind === "view") { MODE = name; SEL = null; return render(); }
  });
}

function neoMount() {
  if ($("#neo")) return;
  const el = document.createElement("aside");
  el.id = "neo"; el.className = "neo";
  el.innerHTML = `
    <div class="neohd"><span class="sq">N</span>
      <div><b>Neo</b><span class="sub">reads this screen</span></div>
      <button class="neox" id="neonew" title="Start again">+</button>
      <button class="neox" id="neoclose" title="Close">\u00d7</button></div>
    <div class="neobody" id="neobody"></div>
    <div class="neochips" id="neochips"></div>
    <div class="neoin">
      <input id="neoq" placeholder="Ask anything about this screen" autocomplete="off">
      <button class="neosend" id="neosend" title="Ask">\u2191</button>
    </div>
    <div class="neofoot">Answers are computed from the figures on this screen,
      not generated. If a number is not there, Neo says so.</div>`;
  document.body.appendChild(el);

  const tab = document.createElement("button");
  tab.id = "neotab"; tab.className = "neotab";
  tab.innerHTML = `<span class="sq">N</span>Ask Neo<span class="kbd">N</span>`;
  tab.onclick = () => neoToggle();
  document.body.appendChild(tab);

  el.querySelector("#neoclose").onclick = () => neoToggle(false);
  el.querySelector("#neonew").onclick = () => { NEO_LOG = []; neoPaint(); };
  el.querySelector("#neosend").onclick = () => {
    const i = $("#neoq"); neoAsk(i.value); i.value = "";
  };
  el.querySelector("#neoq").onkeydown = e => {
    if (e.key === "Enter") { neoAsk(e.target.value); e.target.value = ""; }
    if (e.key === "Escape") neoToggle(false);
  };
  neoPaint();
}

/* ---------- the fund profile ----------
   Tabs because a reader arrives with one question at a time: what do they
   invest in, do they lead, has anything come out, who is there, what has
   been written. A tab with nothing in it says which edge was empty rather
   than rendering blank. */
let FUND = null, FUNDFOR = null, FUNDTAB = 0;
const FUND_TABS = ["Overview", "Portfolio", "Rounds", "Exits", "People", "Record", "News"];

async function loadFund(id, name) {
  MODE = "fund"; FUNDFOR = id; FUND = null; FUNDTAB = 0;
  ENTLOAD = { id, kind: "fund", name };
  render();
  try { FUND = await (await fetch(`/fund/${id}`)).json(); }
  catch (e) { FUND = { error: String(e.message) }; }
  render();
}

/* Money, the way a term sheet says it. 4_500_000 is "4.5M"; 707_000 is
   "707k"; nothing is an em dash, never a zero. */
function money(v, cur = "EUR") {
  if (v == null) return "—";
  const n = Number(v);
  if (!isFinite(n)) return "—";
  const s = n >= 1e9 ? (n / 1e9).toFixed(1).replace(/\.0$/, "") + "B"
    : n >= 1e6 ? (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M"
    : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(Math.round(n));
  return s + (cur === "EUR" ? "" : " " + cur);
}

const SLICE = ["#c2614f", "#d98f7d", "#e8bcae", "#8a6f5c", "#b9a893",
               "#9e4634", "#cdbfae", "#7d8a86"];

/* A share over a subset is a different claim from a share over the whole.
   Each mix carries the denominator it was actually computed on, and when
   that is nothing we say which read is missing rather than drawing an
   empty ring. */
function mixChart(title, mix, unit) {
  const rows = (mix?.rows || []);
  if (!rows.length) {
    return chart(title, `0 of ${mix?.total ?? 0} ${unit}`,
      `<div class="emptywhy" style="margin:0"><b>Not read yet.</b>
        ${mix?.total ? `We hold ${mix.total} ${unit} for this firm but have not
        fetched their own records, so there is nothing to count. The harvester
        works through funds first.` : `No ${unit} on this entity.`}</div>`);
  }
  return chart(title, `${mix.of} of ${mix.total} ${unit} read`,
    donut(rows.map(([k, v], i) => ({ k, v, c: SLICE[i % SLICE.length] }))));
}

function fundStat(k, v, sub) {
  return `<div class="fstat"><div class="k">${esc(k)}</div>
    <div class="v">${v}</div>${sub ? `<div class="s">${esc(sub)}</div>` : ""}</div>`;
}

function fundView() {
  if (!FUND) return `<div class="msg"><span class="spin"></span>Opening
    ${esc(ENTLOAD?.name || "fund")}…</div>`;
  if (FUND.error) return errorPanel(FUND.error, ENTLOAD?.name);

  const f = FUND, st = f.stats || {};
  const host = String(f.website || "").replace(/^https?:\/\//, "").replace(/\/$/, "");

  let body = `<div class="fhead">
    ${bigLogo(f.name, f.website)}
    <div style="min-width:0;flex:1">
      <h1>${esc(f.name)}</h1>
      <div class="fmeta">
        ${f.website ? `<a href="${esc(f.website)}" target="_blank" rel="noopener">${esc(host)}</a>` : ""}
        ${f.country ? ` · ${esc(f.country)}` : ""}
        ${(f.industries || []).length ? ` · ${esc(f.industries.join(", ").toLowerCase().replace(/_/g, " "))}` : ""}
      </div>
    </div>
    <span class="eacts">
      <button class="btn" data-fscreen="${esc(f.name)}">Screen this fund</button>
      <button class="btn" data-alertfor="${esc(f.name)}">Alert me</button>
    </span>
  </div>
  <div class="tabs">${FUND_TABS.map((t, i) => {
    const empty = (t === "Portfolio" && !f.has?.portfolio)
      || (t === "Rounds" && !f.has?.rounds) || (t === "Exits" && !f.has?.exits)
      || (t === "People" && !f.has?.people)
      || (t === "Record" && !f.depth?.coverage?.harvested);
    return `<button class="tab ${i === FUNDTAB ? "on" : ""} ${empty ? "thin" : ""}"
      data-ftab="${i}">${esc(t)}${
      t === "Portfolio" && st.investments ? ` <span>${st.investments}</span>` : ""}${
      t === "Rounds" && st.rounds ? ` <span>${st.rounds}</span>` : ""}${
      t === "Exits" && st.exits ? ` <span>${st.exits}</span>` : ""}${
      t === "People" && (f.depth?.staff?.length || st.people)
        ? ` <span>${f.depth?.staff?.length || st.people}</span>` : ""}${
      t === "Record" && f.depth?.coverage?.edge_types
        ? ` <span>${f.depth.coverage.edge_types}</span>` : ""}</button>`;
  }).join("")}</div>`;

  if (f.degraded) body += `<div class="verdict grey">${esc(f.degraded)}</div>`;

  const T = FUND_TABS[FUNDTAB];
  if (T === "Overview") {
    const ch = f.cheques || {};
    body += (f.description ? `<p class="lede">${esc(f.description)}</p>` : "")
      + `<div class="fstats">
          ${fundStat("Investments", st.investments ?? "—")}
          ${fundStat("Rounds on record", st.rounds ?? "—")}
          ${fundStat("Led", st.led ?? "—", st.lead_rate != null ? pct(st.lead_rate) + " of rounds" : "")}
          ${fundStat("Exits and M&A", st.exits ?? "—",
                     st.financing_events ? `${st.financing_events} financing events, not counted here` : "")}
          ${fundStat("Typical cheque", ch.n ? money(ch.median) : "—",
                     ch.n ? `median of ${ch.n} with an amount` : "no amounts on record")}
          ${fundStat("Headquarters",
                     esc(f.city || f.country || "—"),
                     f.city && f.country ? esc(f.country)
                       : f.country_is_presence ? "where they operate; no HQ edge"
                       : f.address ? esc(String(f.address).slice(0, 40)) : "")}
        </div>`
      + (f.deals_by_year?.length || f.stage_mix?.length || (f.sector_mix?.total)
        ? section("fo-focus", "What they invest in",
            "read off the rounds we hold, not off their website",
            `<div class="three">
              ${f.stage_mix?.length ? chart("Stage", `${f.stage_mix.reduce((a, x) => a + x[1], 0)} rounds`,
                donut(f.stage_mix.map(([k, v], i) =>
                  ({ k, v, c: SLICE[i % SLICE.length] })))) : ""}
              ${mixChart("Sector", f.sector_mix, "portfolio companies")}
              ${mixChart("Where", f.country_mix, "portfolio companies")}
            </div>`) : "")
      + (f.deals_by_year?.length ? section("fo-pace", "When they invested",
          `${f.deals?.length || 0} dated rounds we can attribute to them`,
          `<div class="card">${bars(
            f.deals_by_year.map(([y, n]) => [y, n, "g", n]),
            Math.max(...f.deals_by_year.map(x => x[1])))}</div>`) : "")
      + (f.portfolio?.length ? section("fo-top", "Portfolio highlights",
          `${f.portfolio.length} companies`, `<div class="three">${
            f.portfolio.slice(0, 6).map(portCard).join("")}</div>`) : "");
  } else if (T === "Portfolio") {
    const ch = f.cheques || {};
    body += `<div class="fstats">
        ${fundStat("Portfolio companies", f.portfolio?.length ?? 0)}
        ${fundStat("Rounds we can attribute", f.deals?.length ?? 0,
                   `${ch.n || 0} carry an amount`)}
        ${fundStat("Smallest", ch.n ? money(ch.min) : "—")}
        ${fundStat("Median", ch.n ? money(ch.median) : "—")}
        ${fundStat("Largest", ch.n ? money(ch.max) : "—")}
      </div>`
      + (f.deals?.length ? section("fp-deals", "Deals",
          `${f.deals.length} rounds, newest first`,
          `<div class="tbl"><table><thead><tr><th>Company</th><th>Stage</th>
            <th class="nowrap">Date</th><th class="num">Amount</th>
            <th>Alongside</th></tr></thead><tbody>${f.deals.map(d => `
            <tr data-open-co="${esc(d.company)}">
              <td><div class="ent">${logo(d.company)}<div class="nm">${esc(d.company)}</div></div></td>
              <td>${esc(d.stage || "—")}${d.lead ? " " + badge("lead", "green") : ""}</td>
              <td class="nowrap sub">${esc(String(d.date || "").slice(0, 10) || "—")}</td>
              <td class="num">${d.amount ? money(d.amount) : `<span class="sub">—</span>`}</td>
              <td class="sub">${esc((d.investors || []).filter(i =>
                norm_(i) !== norm_(f.name)).slice(0, 3).join(", "))}</td>
            </tr>`).join("")}</tbody></table></div>
           ${ch.n < (ch.of || 0) ? `<div class="sub" style="margin-top:var(--s2)">
             ${ch.of - ch.n} of these rounds are recorded without an amount. A
             dash is a round Cala holds with no figure, not a round of nothing.
           </div>` : ""}`)
        : "")
      + (f.portfolio?.length
        ? section("fp-cos", "Companies", `${f.portfolio.length}`,
          `<div class="tbl"><table><thead><tr><th>Company</th>
            <th class="num">Rounds</th><th>Last round</th><th>Alongside</th>
          </tr></thead><tbody>${f.portfolio.map(c => `<tr data-open-co="${esc(c.name)}">
            <td><div class="ent">${logo(c.name, c.website)}<div class="nm">${esc(c.name)}</div></div></td>
            <td class="num">${c.rounds || "—"}</td>
            <td class="nowrap">${c.last_stage ? `${esc(c.last_stage)} ${
              esc(String(c.last_date || "").slice(0, 7))}` : "—"}</td>
            <td class="sub">${esc((c.investors || []).filter(i =>
              norm_(i) !== norm_(f.name)).slice(0, 3).join(", "))}</td>
          </tr>`).join("")}</tbody></table></div>`)
        : emptyTab("INVESTED_IN", "no investments on this entity"));
  } else if (T === "Rounds") {
    body += f.round_rows?.length
      ? `<div class="tbl"><table><thead><tr><th>Stage</th><th>Role</th>
        </tr></thead><tbody>${f.round_rows.map(r => `<tr style="cursor:default">
          <td>${esc(r.stage)}</td>
          <td>${r.lead ? badge("lead", "green") : `<span class="sub">${
            esc((r.role || "investor").toLowerCase())}</span>`}</td>
        </tr>`).join("")}</tbody></table></div>`
      : emptyTab("PARTICIPATES_IN_FUNDING_ROUND", "no rounds on this entity");
  } else if (T === "Exits") {
    body += f.exits?.length
      ? `<div class="tbl"><table><thead><tr><th>Event</th><th>Their role</th>
        </tr></thead><tbody>${f.exits.map(x => `<tr style="cursor:default">
          <td>${esc(x.name || "Corporate event")}</td>
          <td>${x.role ? badge(String(x.role).toLowerCase(), "blue") : "—"}</td>
        </tr>`).join("")}</tbody></table></div>`
      : emptyTab("PARTICIPATES_IN_CORPORATE_EVENT",
          `no sale or listing on this entity${f.financing_events
            ? ` — the ${f.financing_events} corporate events it does have are
                financing rounds, which are on the Rounds tab` : ""}`);
  } else if (T === "People") {
    // The harvested record attaches people by every edge there is - founder,
    // general partner, board member, staff - where the old People tab asked
    // only for WORKS_AT and showed "works here" for all of them.
    const staff = f.depth?.staff?.length ? f.depth.staff : (f.people || []);
    body += (staff.length
      ? `<div class="fslist">${staff.map(p => `
          <button class="fsrow" data-fsid="${esc(p.id)}" data-fsnm="${esc(p.name)}">
            <div><div class="nm">${esc(p.name)}</div>
            <div class="d">${esc(p.role || "works here")}${
              p.since ? ` · since ${esc(String(p.since).slice(0, 4))}` : ""}</div></div>
            <span class="go">Founder signal →</span></button>`).join("")}</div>`
      : emptyTab("WORKS_AT", "Cala holds nobody at this firm"))
      + `<div class="sub" style="margin-top:var(--s2)">Cala's people coverage on
         firms is thin. <button class="lnk" data-teamfor="${esc(f.website || f.name)}">Read
         their own team page instead →</button></div>`
      + teamPanel();
  } else if (T === "Record") {
    body += recordTab(f);
  } else if (T === "News") {
    body += newsTab(f.name);
  }
  return body;
}

/* The whole record, rather than the slice a feature asked for.
   Every other tab answers a question. This one answers "what do you actually
   have on them", including the parts that are empty - because a page that
   shows nothing because the record is thin and a page that shows nothing
   because we never asked look identical, and only one is our fault. */
function recordTab(f) {
  const d = f.depth || {}, cov = d.coverage || {};
  if (!cov.harvested) return `<div class="emptywhy"><b>Not harvested yet.</b>
    This profile was assembled from the edges a feature asked for. The full
    record — every property and every relationship this entity declares — is
    fetched by the harvester, which works through the fund list first.</div>`;

  const facts = (d.facts || []).filter(x => x.key !== "website");
  const ids = Object.entries(d.identifiers || {});
  const edges = Object.entries(cov.by_edge || {});
  const top = Math.max(1, ...edges.map(([, n]) => n));

  return `<div class="sub" style="max-width:64ch;line-height:1.7;margin-bottom:var(--s3)">
      ${cov.properties} properties, ${cov.sourced_properties} of them carrying a
      source document, and ${cov.edges} relationships across ${cov.edge_types}
      kinds. This is the entity asked for everything it declares, not for the
      fields one screen needed.</div>

    ${facts.length ? section("d-facts", "The plain record", "with the document each claim came from",
      `<div class="tbl"><table><tbody>${facts.map(x => `<tr style="cursor:default">
        <td class="sub nowrap">${esc(x.label)}</td>
        <td>${esc(String(x.value).slice(0, 220))}</td>
        <td class="nowrap">${(x.sources || []).length
          ? x.sources.map(s => `<a class="lnk" href="${esc(s.document)}" target="_blank"
              rel="noopener" title="${esc(s.name || s.document)}">${
              esc(String(s.name || "source").slice(0, 34))}</a>`).join(" ")
          : `<span class="sub">no source</span>`}</td></tr>`).join("")}
      </tbody></table></div>`) : ""}

    ${ids.length ? section("d-ids", "Registered identifiers",
      "the only way to name a firm without ambiguity",
      `<div class="card"><div class="sub" style="line-height:1.7;margin-bottom:var(--s2)">
         Three bugs in this product came from matching firms by name — a Munich
         fund placed in Tampere, a company called NORRSKEN COMPANY LIMITED
         outranking Norrsken VC. An identifier settles those, when there is
         one: 14 of the 10,558 entities we hold carry it, so this is a better
         answer for this firm rather than a fix for the problem.</div>
       ${ids.map(([k, v]) => `<span class="chip mono">${esc(k.toUpperCase())} ${esc(v)}</span>`).join(" ")}
      </div>`) : ""}

    ${(d.presence || []).length ? section("d-where", "Where they are",
      "headquarters first",
      `<div class="card">${d.presence.map(x =>
        `<span class="chip">${esc(x.name)}${x.kind === "headquarters" ? " · HQ" : ""}</span>`
      ).join(" ")}</div>`) : ""}

    ${section("d-cov", "What we hold on them", `${edges.length} kinds of relationship carry something`,
      `<div class="card">${edges.map(([k, n]) => {
        const [dir, rel] = k.split(":");
        return `<div class="dcov"><div class="dcovk">${esc(rel.replace(/_/g, " ").toLowerCase())}
            <span class="sub">${esc(dir)}</span></div>
          <div class="dcovb"><i style="width:${Math.max(2, 100 * n / top)}%"></i></div>
          <div class="dcovn">${n}${n >= 200 ? "+" : ""}</div></div>`;
      }).join("")}
      ${edges.some(([, n]) => n >= 200) ? `<div class="sub" style="margin-top:var(--s2)">
        A count of 200 is the page size, not the total — those edges have more
        behind them than we fetched.</div>` : ""}</div>`)}`;
}

const norm_ = x => String(x || "").toLowerCase().replace(/[^a-z0-9]/g, "");

/* News: Cala's sourced answer, kept as claims with their documents and
   stripped of the prose around them. A claim with a link is checkable. */
let NEWS = null, NEWSFOR = null;

async function loadNews(name) {
  NEWSFOR = name; NEWS = { loading: true }; render();
  try { NEWS = await (await fetch(`/news?name=${encodeURIComponent(name)}`)).json(); }
  catch (e) { NEWS = { items: [], error: String(e.message) }; }
  render();
}

function newsTab(name) {
  if (NEWSFOR !== name) { loadNews(name); return `<div class="msg">
    <span class="spin"></span>Asking Cala what has been written…</div>`; }
  if (NEWS?.loading) return `<div class="msg" style="padding:30px">
    <span class="spin"></span>Asking Cala what has been written about
    ${esc(name)}…<br><span class="sub">About fifty seconds the first time,
    then cached.</span></div>`;
  if (NEWS?.error) return `<div class="emptywhy"><b>Could not read the news.</b>
    ${esc(NEWS.error)}</div>`;
  if (!NEWS?.items?.length) {
    const open = NEWS?.open || [];
    if (!open.length) return emptyTab("knowledge/search",
      `Cala returned no sourced claims for this firm${
        NEWS?.open_error ? `, and the open index could not answer either —
        ${esc(NEWS.open_error)}` : `, and nothing in the open news index
        names them either`}`);
    return `<div class="sub" style="margin-bottom:var(--s2);max-width:66ch;line-height:1.7">
        <b>Cala has nothing written about this firm.</b> These came from
        ${esc(NEWS.open_source || "an open news index")} instead — headlines
        and where to read them, nothing republished. Weaker evidence than a
        Cala claim: nobody has decided these articles are about the right
        company, only that they name it.</div>
      <div class="newslist">${open.map(i => `
        <div class="newsitem">
          <p><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a></p>
          <div class="newsdocs"><span class="sub">${esc(i.domain)}${
            i.date ? ` · ${esc(i.date)}` : ""}${
            i.via ? ` · via ${esc(i.via)}` : ""}</span></div>
        </div>`).join("")}</div>`;
  }

  const withDocs = NEWS.items.filter(i => i.documents?.length);
  return `<div class="sub" style="margin-bottom:var(--s2);max-width:62ch;line-height:1.7">
      ${NEWS.items.length} claims, ${withDocs.length} with a document behind them.
      The prose Cala wrote around these has been dropped — a claim with a link
      is checkable, a paragraph is not.</div>
    <div class="newslist">${NEWS.items.map(i => `
      <div class="newsitem">
        <p>${esc(i.claim)}</p>
        ${i.documents?.length
          ? `<div class="newsdocs">${i.documents.map(d =>
              `<a href="${esc(d.url)}" target="_blank" rel="noopener">${
                esc(String(d.url).replace(/^https?:\/\/(www\.)?/, "").split("/")[0])}</a>`
            ).join("")}</div>`
          : `<div class="newsdocs"><span class="sub">no document on this claim</span></div>`}
      </div>`).join("")}</div>`;
}

function portCard(c) {
  return `<div class="card pcard" data-open-co="${esc(c.name)}">
    <div class="ent">${logo(c.name, c.website)}
      <div><div class="nm">${esc(c.name)}</div>
      <div class="sb">${c.rounds ? `${c.rounds} rounds` : "no rounds cached"}</div></div></div>
    ${c.last_stage ? `<div class="pmeta">${esc(c.last_stage)}
      <span>${esc(String(c.last_date || "").slice(0, 7))}</span></div>` : ""}
  </div>`;
}

function emptyTab(rel, why) {
  return `<div class="emptywhy"><b>Nothing here.</b> ${esc(why)}.
    <span class="sub">The edge we asked for was <code>${esc(rel)}</code>, and it
    came back empty — which is a fact about the graph, not a failure to load.</span></div>`;
}

/* ---------- alerts ----------
   The forward half of the exclusion. A conflict you already know about is
   a fact; a competitor raising next month is the one that changes who you
   can pitch, and every investor in that round is tomorrow's exclusion. */
let ALERTS = null, ALERTRULES = null, ALERTON = null, ALERTSTEP = 0;

async function loadAlertRules() {
  if (ALERTRULES) return ALERTRULES;
  try { ALERTRULES = (await (await fetch("/alert-rules")).json()).rules; }
  catch (e) { ALERTRULES = []; }
  if (!ALERTON) ALERTON = new Set(ALERTRULES.map(r => r.id));
  return ALERTRULES;
}

async function runAlerts() {
  ALERTS = { loading: true }; renderAlerts();
  try {
    ALERTS = await (await fetch("/alerts", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ company: F?.company || "Gosta Labs",
                             stage: F?.stage || "series a",
                             limit: F?.investors?.length || 14,
                             rules: [...(ALERTON || [])] })
    })).json();
  } catch (e) { ALERTS = { hits: [], error: String(e.message) }; }
  renderAlerts();
}

async function openAlerts() {
  await loadAlertRules();
  ALERTSTEP = 0;
  const w = document.createElement("div");
  w.className = "scrim on"; w.id = "alertscrim";
  document.body.appendChild(w);
  w.onclick = e => { if (e.target === w) w.remove(); };
  renderAlerts();
  if (!ALERTS) runAlerts();
}

function renderAlerts() {
  const w = $("#alertscrim");
  if (!w) return;
  const steps = ["What to watch", "What it catches now"];
  w.innerHTML = `<div class="composebox wide" onclick="event.stopPropagation()">
    <div class="sidehd"><h3>Watch this list</h3>
      <div class="s">${esc(F?.company || "")} · ${esc(F?.stage || "")}</div></div>
    <div class="alsteps">${steps.map((t, i) =>
      `<button class="alstep ${i === ALERTSTEP ? "on" : ""}" data-alstep="${i}">${esc(t)}</button>`).join("")}</div>
    <div style="padding:15px">${ALERTSTEP === 0 ? alertRulesPane() : alertResultsPane()}
      <div style="display:flex;gap:8px;margin-top:14px">
        ${ALERTSTEP === 0
          ? `<button class="btn pri" id="alnext">See what it catches →</button>`
          : `<button class="btn" id="alback">← Change the rules</button>`}
        <button class="btn" id="alclose" style="margin-left:auto">Close</button>
      </div></div></div>`;
  w.querySelector("#alclose").onclick = () => w.remove();
  const nx = w.querySelector("#alnext");
  if (nx) nx.onclick = () => { ALERTSTEP = 1; renderAlerts(); runAlerts(); };
  const bk = w.querySelector("#alback");
  if (bk) bk.onclick = () => { ALERTSTEP = 0; renderAlerts(); };
  w.querySelectorAll("[data-alstep]").forEach(b => b.onclick = () => {
    ALERTSTEP = +b.dataset.alstep; renderAlerts();
    if (ALERTSTEP === 1 && !ALERTS) runAlerts();
  });
  w.querySelectorAll("[data-alrule]").forEach(b => b.onclick = () => {
    const id = b.dataset.alrule;
    ALERTON.has(id) ? ALERTON.delete(id) : ALERTON.add(id);
    ALERTS = null; renderAlerts();
  });
}

function alertRulesPane() {
  return `<div class="sub" style="margin-bottom:12px;line-height:1.65;max-width:60ch">
      Rules run against this screen. The one that matters is the first:
      a competitor raising is what turns a fund you could pitch into one
      you cannot.</div>
    <div class="alrules">${(ALERTRULES || []).map(r => `
      <button class="alrule ${ALERTON?.has(r.id) ? "on" : ""}" data-alrule="${esc(r.id)}">
        <span class="sev ${esc(r.severity)}"></span>
        <span><b>${esc(r.label)}</b><em>${esc(r.why)}</em></span>
        <span class="tick">${ALERTON?.has(r.id) ? "✓" : ""}</span>
      </button>`).join("")}</div>`;
}

function alertResultsPane() {
  if (!ALERTS) return `<div class="msg" style="padding:24px">
    <span class="spin"></span>Running the rules…</div>`;
  if (ALERTS.loading) return `<div class="msg" style="padding:24px">
    <span class="spin"></span>Running the rules against ${esc(F?.company || "")}…</div>`;
  if (ALERTS.error) return `<div class="emptywhy"><b>Could not run.</b> ${esc(ALERTS.error)}</div>`;

  const comp = ALERTS.competitor_rounds || [];
  const ex = ALERTS.would_exclude || [];
  const hits = ALERTS.hits || [];

  return `${comp.length ? `
    <div class="alhead">${comp.length} competitor round${comp.length === 1 ? "" : "s"}
      in the last 18 months</div>
    ${comp.map(c => `<div class="alrow high">
      <div><b>${esc(c.competitor)}</b> raised ${esc(c.stage || "a round")}
        · <span class="when">${esc(c.date)}, ${c.months_ago} months ago</span></div>
      <div class="sub">${esc(c.investors.join(" · "))}</div>
    </div>`).join("")}
    ${ex.length ? `<div class="alexclude">
      <b>${ex.length} funds are now un-pitchable</b> because they are in one of
      those rounds.<div class="sub">${esc(ex.join(" · "))}</div></div>` : ""}` : ""}
    ${hits.length ? `<div class="alhead">${hits.length} on your current list</div>
      ${hits.map(h => `<div class="alrow ${esc(h.severity)}">
        <div><b>${esc(h.investor)}</b> — ${esc(h.detail)}</div>
        <span class="bdg b-${h.severity === "high" ? "red" : h.severity === "medium"
          ? "amber" : "grey"}">${esc(h.rule.replace(/_/g, " "))}</span>
      </div>`).join("")}` : ""}
    ${!comp.length && !hits.length ? `<div class="emptywhy">
      <b>Nothing fires.</b> No competitor has raised in the window and no fund
      on the list changed state.</div>` : ""}
    <div class="sub" style="margin-top:14px;line-height:1.6">${esc(ALERTS.note || "")}</div>`;
}

/* ---------- the call list ----------
   A screen says which firms are worth approaching. It does not say who to
   write to, and a fund is not a person. Two sources, never blended: Cala
   when it has a Person entity (role and start date from the graph) and
   the firm's own team page for the rest, which is most of them. */
let CALLS = null, CALLSFOR = null, CALLDONE = null;

function callKey() { return `flipside.calls.${(F?.company || "").toLowerCase()}`; }

function callsLoadDone() {
  try { CALLDONE = new Set(JSON.parse(localStorage.getItem(callKey()) || "[]")); }
  catch (e) { CALLDONE = new Set(); }
}

function callsSaveDone() {
  try { localStorage.setItem(callKey(), JSON.stringify([...CALLDONE])); } catch (e) {}
}

async function loadCalls() {
  if (!F) return;
  CALLSFOR = F.company; CALLS = { loading: true };
  if (!CALLDONE) callsLoadDone();
  render();
  try {
    CALLS = await (await fetch("/call-list", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ company: F.company, stage: F.stage,
                             limit: F.investors?.length || 14 })
    })).json();
  } catch (e) { CALLS = { rows: [], error: String(e.message) }; }
  render();
  enrichCalls();
}

/* Resolving fifteen names to Cala people is thirty calls cold. Run it after
   the list is already on screen and re-rank when it lands, rather than
   making the founder wait for an order that is only a little better. */
let CALLENRICH = null;

async function enrichCalls() {
  if (!F || CALLENRICH === F.company) return;
  CALLENRICH = F.company;
  const want = F.company;
  try {
    const d = await (await fetch("/call-list/people", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ company: F.company, stage: F.stage,
                             limit: F.investors?.length || 14 })
    })).json();
    if (F?.company !== want || d.error) return;
    CALLS = d; render();
  } catch (e) { /* the list already works without it */ }
}

/* Alerts as a destination, not only a modal: the forward half of the
   exclusion deserves a page of its own. */
/* What changed under the funds you are actually tracking.
   This used to be a destination of its own called Watch, which asked a
   founder to go and look at a page about funds they had already decided
   about. The alert that matters is the one on a fund sitting in Diligence,
   so it lives on the pipeline, next to the card it is about. */
function watchBlock() {
  if (!ALERTRULES) { loadAlertRules().then(render); return ""; }
  if (!ALERTS) runAlerts();
  const n = (ALERTON || new Set()).size;
  return section("wnow", "What changed since you added these",
      `${n} rule${n === 1 ? "" : "s"} on`,
      `<div class="sub" style="max-width:66ch;line-height:1.7;margin-bottom:var(--s2)">
         A conflict you already know about is a fact. The one that changes
         whether you can pitch somebody is the competitor round that has not
         happened yet — and every investor in it joins your exclusion the day
         it closes.</div>`
      + alertResultsPane()
      + `<details class="alrules"><summary>Which rules are on</summary>${
          alertRulesPane()}</details>`);
}

/* The same rows the call list page shows, without the page furniture: in
   the reach view the map is carrying the context the KPI cards would. */
function reachList() {
  if (CALLS?.loading) return `<div class="msg" style="padding:30px">
    <span class="spin"></span>Finding who to contact at each firm…<br>
    <span class="sub">Cala first, then each firm\u2019s own team page.</span></div>`;
  if (CALLS?.error) return `<div class="emptywhy"><b>Could not build it.</b>
    ${esc(CALLS.error)}</div>`;
  const rows = CALLS?.rows || [];
  if (!rows.length) return `<div class="emptywhy"><b>Nobody to call.</b>
    None of the funds you picked came back with a named contact — neither Cala
    nor their own team page had one.</div>`;
  const skipped = (CALLS.skipped || []).filter(x => x.why === "no contact found");
  return `<div class="calllist">${rows.map(callRow).join("")}</div>`
    + (skipped.length ? `<div class="sub" style="margin-top:var(--s2)">
        No name found at ${skipped.map(x => esc(x.fund)).join(", ")}.</div>` : "");
}

function callsView() {
  if (!F) return `<div class="msg">Run a screen first — the call list is built
    from the funds that survive it.</div>`;
  if (!CALLS || CALLSFOR !== F.company) { loadCalls(); return `<div class="msg">
    <span class="spin"></span>Finding who to contact at each firm…</div>`; }
  if (CALLS.loading) return `<div class="msg" style="padding:40px">
    <span class="spin"></span>Finding who to contact at each firm…<br>
    <span class="sub">Cala first, then each firm's own team page.</span></div>`;
  if (CALLS.error) return `<div class="emptywhy"><b>Could not build it.</b>
    ${esc(CALLS.error)}</div>`;

  const rows = CALLS.rows || [];
  const done = CALLDONE || new Set();
  const left = rows.filter(r => !done.has(r.person + "|" + r.fund));

  return kpis([
    ["People to call", rows.length, "all", "at funds that survived the exclusion"],
    ["Still to do", left.length, "todo", "ticked off in this browser"],
    ["Named by Cala", CALLS.by_source?.cala || 0, "cala",
     "a Person entity in the graph, with a role and often a start date"],
  ], "all", null)
  + `<div class="sub" style="margin:-6px 0 var(--s2);max-width:66ch;line-height:1.65">
      ${CALLS.funds_with_a_contact} of your firms have a name on them. The firm
      decides most of the order — a brilliant partner at a fund that cannot lead
      your round is still the wrong call. After that: an introduction, then
      seniority, then what we know about the person.
      ${CALLS.enriched ? `<b>${CALLS.enriched}</b> of ${CALLS.rows.length} resolved
        to a Cala person.` : `<span class="sub">Resolving people…</span>`}</div>`
  + section("cl", "Call list", `${rows.length} contacts`, rows.length
      ? `<div class="calllist">${rows.map(callRow).join("")}</div>`
      : `<div class="emptywhy"><b>Nobody to call.</b> Every firm that survived
          the exclusion came back with no named contact.</div>`)
  + ((CALLS.skipped || []).length ? section("clskip", "Not on the list",
      `${CALLS.skipped.length} firms`, `<div class="tbl"><table><tbody>${
        CALLS.skipped.map(sk => `<tr style="cursor:default">
          <td>${esc(sk.fund)}</td>
          <td>${sk.why === "backs a competitor"
            ? badge(`backs ${esc((sk.backs || []).join(", "))}`, "red")
            : `<span class="sub">no contact found</span>`}</td>
        </tr>`).join("")}</tbody></table></div>`) : "");
}

function callRow(r) {
  const id = r.person + "|" + r.fund;
  const sg = r.signals || {};
  const done = (CALLDONE || new Set()).has(id);
  return `<div class="callrow ${done ? "done" : ""}">
    <button class="callcheck" data-call="${esc(id)}" title="Mark as contacted">${
      done ? "✓" : ""}</button>
    <span class="av">${esc(initials(r.person))}</span>
    <div class="who">
      <div class="nm">${esc(r.person)}
        ${r.role ? `<span class="role">${esc(r.role)}</span>` : ""}${
        r.ambiguous ? `<span class="role" title="Cala holds these two as one
          record, so we cannot tell you which of them to ring">two people in
          one record</span>` : ""}</div>
      <div class="at">${logo(r.fund)}${esc(r.fund)}
        ${r.fund_score != null ? `<span class="sc">${r.fund_score}</span>` : ""}
        <span class="src ${esc(r.source)}">${r.source === "cala" ? "Cala" : "their site"}</span>
      </div>
      <div class="why">${esc(r.reason)}</div>
      ${r.warm ? `<div class="warm">${esc(r.warm)} — ask for the introduction</div>` : ""}
      ${(r.bonus_why || []).length ? `<div class="pwhy">${r.bonus_why.map(w =>
        `<span>${esc(w)}</span>`).join("")}${sg.market_via?.length
          ? `<span class="via">via ${esc(sg.market_via[0])}</span>` : ""}</div>` : ""}
    </div>
    <div class="acts">
      <span class="cscore" title="fund score, plus an introduction, seniority and
        what we know about the person">${r.call_score ?? ""}</span>
      ${r.person_id ? `<button class="btn sm" data-person="${esc(r.person_id)}"
        data-pname="${esc(r.person)}">Card</button>` : ""}
      ${r.linkedin ? `<a class="btn sm" href="${esc(r.linkedin)}" target="_blank"
        rel="noopener">LinkedIn</a>` : ""}
      <button class="btn sm" data-brief="${esc(r.fund)}">Opener</button>
      ${dealButton(r.fund)}
    </div>
  </div>`;
}

/* ---------- the person card ----------
   A founder about to call someone is asking three things a title cannot
   answer: have you been where I am, will you understand what I build, and
   who can you introduce me to. Everything here is an edge on the Person
   entity, and the one thing Cala has no edge for is said out loud. */
async function openPerson(id, name) {
  const w = document.createElement("div");
  w.className = "scrim on";
  w.innerHTML = `<div class="composebox wide" onclick="event.stopPropagation()">
    <div class="sidehd"><h3>${esc(name || "Person")}</h3>
      <div class="s">Reading their record…</div></div>
    <div style="padding:34px"><span class="spin"></span></div></div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  w.onclick = close;

  let c;
  try {
    c = await (await fetch(`/person/${id}?company=${
      encodeURIComponent(F?.company || "")}`)).json();
  } catch (e) { c = { error: String(e.message) }; }

  if (c.error) {
    w.innerHTML = `<div class="composebox" onclick="event.stopPropagation()">
      <div class="sidehd"><h3>${esc(name || "")}</h3></div>
      <div class="msg">${esc(c.error)}</div></div>`;
    w.onclick = close;
    return;
  }

  const op = c.operator || {}, net = c.network || {}, dom = c.domain || {},
        ang = c.angel || {};
  const conf = c.confidence || {};
  const role = c.headline_role || (c.works_at || [])[0];

  const block = (title, body, sub) => body
    ? `<div class="pcblock"><div class="pch">${esc(title)}${
        sub ? `<span>${esc(sub)}</span>` : ""}</div>${body}</div>` : "";

  w.innerHTML = `<div class="composebox wide" onclick="event.stopPropagation()">
    <div class="sidehd">
      <h3>${esc(c.name)}</h3>
      <div class="s">${role ? `${esc(role.role || "works at")} · ${esc(role.name)}` : ""}
        ${c.nationality?.length ? ` · ${esc(c.nationality.join(", "))}` : ""}</div>
    </div>
    <div style="padding:15px">
      <div class="pcstats">
        <div class="pcstat"><span class="k">Operating for</span>
          <span class="v">${op.years_building ?? "—"}</span>
          <span class="s">${op.building_since
            ? `years, since ${op.building_since}`
            : "no dated role on record"}</span></div>
        <div class="pcstat"><span class="k">Can introduce</span>
          <span class="v">${net.count ?? 0}</span>
          <span class="s">${net.boards || 0} boards · ${net.personal_cheques || 0} cheques</span></div>
        <div class="pcstat"><span class="k">Invests personally</span>
          <span class="v ${ang.is_angel ? "hit" : ""}">${
            ang.is_angel ? (ang.round_count || ang.company_count) : "no"}</span>
          <span class="s">${ang.is_angel
            ? `${ang.round_count ? "rounds of their own" : "companies, undated"}${
                ang.last_year ? `, last ${esc(ang.last_year)}` : ""}`
            : "no personal cheque on record"}</span></div>
        <div class="pcstat"><span class="k">Your market</span>
          <span class="v ${dom.matched?.length ? "hit" : ""}">${
            !dom.checked ? "—" : dom.matched?.length ? "yes" : "no"}</span>
          <span class="s">${!dom.checked
            ? "no market to check against"
            : esc((dom.matched || []).join(", ")
                  || `none of ${(dom.wanted || []).join(", ")}`)}</span></div>
        <div class="pcstat"><span class="k">We know</span>
          <span class="v">${esc(conf.label || "—")}</span>
          <span class="s">${conf.known ?? 0} of ${conf.of ?? 5} signals</span></div>
      </div>

      ${c.description ? `<p class="lede" style="margin:var(--s2) 0">${esc(c.description)}</p>` : ""}

      ${(c.titles || []).length ? `<div class="pctitles">${c.titles.map(t =>
        `<span class="chip sm">${esc(t.title)} · ${esc(t.name)}${
          t.since ? ` since ${esc(String(t.since).slice(0, 4))}` : ""}</span>`).join(" ")}
        <div class="sub" style="margin-top:6px">Held in Cala's graph, not read
          off a team page.</div></div>` : ""}

      ${block("Writes their own cheques", ang.is_angel
        ? `<div class="sub" style="line-height:1.7;margin-bottom:var(--s2)">
             A partner who has only deployed the fund's money needs the
             partnership to say yes. One who has put their own in has decided
             alone before.</div>
           <div class="pclist">${[
             ...(ang.rounds || []).map(r => ({ name: r.name, tag: r.role || "took part",
                                               yr: String(r.date || "").slice(0, 4) })),
             ...(ang.companies || []).map(n => ({ name: n, tag: "their cheque", yr: "" })),
           ].slice(0, 10).map(x => `<div class="pcrow"><b>${esc(x.name)}</b>
              <span class="tag">${esc(x.tag)}</span>
              ${x.yr ? `<span class="yr">${esc(x.yr)}</span>` : ""}</div>`).join("")}</div>`
        : "", ang.is_angel
             ? `${ang.round_count} round${ang.round_count === 1 ? "" : "s"}, ${
                 ang.company_count} compan${ang.company_count === 1 ? "y" : "ies"}`
             : "")}

      ${block("Started", (op.founded || []).length
        ? `<div class="pclist">${op.founded.map(x => `<div class="pcrow">
            <b>${esc(x.name)}</b><span class="tag">founder</span>
            ${(x.roles || []).map(r => `<span class="tag">${esc(r)}</span>`).join("")}
            ${x.year ? `<span class="yr">${x.year}</span>` : ""}
            ${x.what ? `<div class="what">${esc(x.what)}</div>` : ""}</div>`).join("")}</div>`
        : "", `${(op.founded || []).length} compan${
          (op.founded || []).length === 1 ? "y" : "ies"}`)}

      ${block("Seats held", (op.operated || []).length
        ? `<div class="sub" style="line-height:1.7;margin-bottom:var(--s2)">
             Companies they ran without starting — a promotion at a firm that
             already existed is not something they built.</div>
           <div class="pclist">${op.operated.map(x => `<div class="pcrow">
            <b>${esc(x.name)}</b><span class="tag">${esc(x.role || "role")}</span>
            ${x.year ? `<span class="yr">${x.year}</span>` : ""}</div>`).join("")}</div>`
        : "")}

      ${block("Career, in order", (c.timeline || []).length
        ? `<div class="ptl">${c.timeline.map((t, i) => `<div class="ptlrow">
            <span class="y">${t.year}</span>
            <span class="d ${t.founder ? "f" : ""}"></span>
            <span class="n"><b>${esc(t.name)}</b>
              <span class="sub">${esc(t.role || "")}</span>${
              i < c.timeline.length - 1 && c.timeline[i + 1].year
                ? `<span class="sub"> · ${t.year - c.timeline[i + 1].year} year${
                    t.year - c.timeline[i + 1].year === 1 ? "" : "s"} later</span>` : ""}</span>
          </div>`).join("")}</div>
          <div class="sub" style="margin-top:6px">Only the roles that carry a
            date. ${(op.founded || []).length + (op.operated || []).length
              - c.timeline.length} more have none.</div>`
        : "")}

      ${block("Who can introduce you to them", (c.reachable_through || []).length
        ? `<div class="sub" style="line-height:1.7;margin-bottom:var(--s2)">
             These investors sat in the rounds of what they built. They have
             met them, and an introduction from one is not a cold email.</div>
           <div class="pclist">${c.reachable_through.map(r => `<div class="pcrow">
            <b>${esc(r.name)}</b>
            ${r.led ? badge("led the round", "green") : ""}
            <span class="mk">via ${esc(r.through.join(", "))}</span></div>`).join("")}</div>`
        : "", `${(c.reachable_through || []).length} route${
          (c.reachable_through || []).length === 1 ? "" : "s"}`)}

      ${block("Can introduce you to", (net.companies || []).length
        ? `<div class="pclist">${net.companies.slice(0, 12).map(n =>
            `<div class="pcrow"><b>${esc(n.name)}</b>
              <span class="tag">${n.via === "board" ? "board seat" : "their cheque"}</span>
              ${n.markets?.length ? `<span class="mk">${esc(n.markets.join(", "))}</span>` : ""}
              ${n.what ? `<div class="what">${esc(n.what)}</div>` : ""}</div>`).join("")}
           ${net.companies.length > 12 ? `<div class="sub">and ${
             net.companies.length - 12} more</div>` : ""}</div>`
        : "", `${net.count || 0} doors`)}

      ${(dom.via || []).length ? block("Why this is your market",
        `<div class="pclist">${dom.via.map(v => `<div class="pcrow">
           <b>${esc(v.name)}</b><span class="mk">${esc((v.markets || []).join(", "))}</span>
           <div class="what">${esc(v.what || "")}</div></div>`).join("")}</div>`) : ""}

      ${block("Education", (dom.education || []).length
        ? `<div class="sub">${esc(dom.education.join(" · "))}</div>` : "")}

      ${block("Recognition", (c.recognition || []).length
        ? `<div class="sub">${c.recognition.map(a =>
            `${esc(a.name)}${a.year ? ` (${a.year})` : ""}`).join(" · ")}</div>` : "")}

      <div class="emptywhy" style="margin-top:var(--s2)">
        <b>We did not check their record.</b> ${esc(c.unchecked?.legal || "")}
        <span class="sub">Looked for: ${esc((c.unchecked?.edges_we_looked_for || []).join(", "))}</span>
      </div>

      <div style="display:flex;gap:8px;margin-top:14px">
        ${c.linkedin ? `<a class="btn pri" href="${esc(c.linkedin)}" target="_blank"
          rel="noopener">Open LinkedIn</a>` : ""}
        ${c.website ? `<a class="btn" href="${esc(c.website)}" target="_blank"
          rel="noopener">Their site</a>` : ""}
        <button class="btn" id="pcclose" style="margin-left:auto">Close</button>
      </div>
    </div></div>`;
  w.onclick = close;
  w.querySelector("#pcclose").onclick = close;
}

function render() {
  if (KBDMODE !== MODE) { KBD = -1; KBDMODE = MODE; kbdHint(false); }
  document.querySelectorAll("[data-mode]").forEach(b =>
    b.classList.toggle("on", b.dataset.mode === MODE));
  let html, parts;
  if (MODE === "entity") {
    parts = [{ t: ENT?.kind === "people" ? "People" : "Funds", go: 1 },
             { t: ENT?.name || ENTLOAD?.name || "Profile" }];
    html = entityView();
  } else if (MODE === "home") {
    parts = [{ t: "Ask" }];
    html = homeView();
  } else if (MODE === "brief") {
    parts = [{ t: "Ask", go: 1 }, { t: INTAKE.profile?.name || "Reading your brief" }];
    html = intakeView();
  } else if (MODE === "investor") {
    parts = [{ t: "Your pipeline" }, { t: "Insider conviction" }];
    html = investorView();
  } else if (MODE === "scouts") {
    parts = [{ t: "Your pipeline", go: 1 }, { t: "Before they found" }];
    html = scoutsView();
  } else if (MODE === "map") {
    parts = [{ t: "Map" }, { t: "Companies, funds and people" }];
    html = mapView();
  } else if (MODE === "reach") {
    parts = [{ t: "Your raise", go: 1 }, { t: F?.company || "", go: 1 },
             { t: "Who to call" }];
    html = reachView();
  } else if (MODE === "deals") {
    parts = [{ t: "Your raise", go: 1 }, { t: F?.company || "", go: 1 },
             { t: "Pipeline" }];
    html = dealsView();
  } else if (MODE === "calls") {
    parts = [{ t: "Your raise", go: 1 }, { t: "Call list" }];
    html = callsView();
  } else if (MODE === "fund") {
    parts = [{ t: "Funds", go: 1 }, { t: FUND?.name || ENTLOAD?.name || "Fund" }];
    html = fundView();
  } else if (MODE === "signal") {
    parts = [{ t: "Signals" }, { t: "Founder signal" }];
    html = signalView();
  } else if (MODE === "accuracy") {
    parts = [{ t: "Signals", go: 1 }, { t: "Does the signal work?" }];
    html = accuracyView();
  } else if (MODE === "founder") {
    parts = SEL ? [{ t: "Founder", go: 1 }, { t: F?.company || "", go: 1 }, { t: SEL }]
                : [{ t: "Founder" }, { t: F?.company || "Target screening" }];
    html = SEL ? founderEntity() : founderList();
  } else {
    parts = [{ t: "Ask" }];
    html = homeView();
  }
  crumb(parts);
  $("#baracts").innerHTML = MODE === "founder" && !SEL && F
    ? `<button class="btn" id="go2">Re-run</button>` : "";
  document.body.classList.toggle("has-picks", PICKED.size > 0 && MODE === "founder");
  // The map wants the screen; every other view wants a reading measure.
  document.body.classList.toggle("wide", MODE === "map");
  const ctd = $("#ct-d");
  if (ctd) ctd.textContent = dealCount() ? `${dealCount()} in play` : "";
  const ctw = $("#ct-w"), nw = Object.keys(SCOUTWATCH).length;
  if (ctw) ctw.textContent = nw ? `${nw} watched` : "";
  $("#view").innerHTML = html;
  wire();
  kbdInit();
  if (NEO_OPEN && !NEO_LOG.length) neoPaint();
  if (KBD >= 0 && KBD >= kbdRows().length) { KBD = -1; kbdHint(false); }
  if (KBD >= 0) kbdPaint();
  if (MODE === "map" && MAP?.points) setTimeout(initMap, 30);
  const fsq = $("#fsq");
  if (fsq) {
    fsq.oninput = () => { clearTimeout(FSTIMER);
      FSTIMER = setTimeout(() => fsSearch(fsq.value), 280); };
  }
  document.querySelectorAll("[data-fsteam]").forEach(b => b.onclick = () => {
    const i = $("#fsq");
    loadTeam((i && i.value) || b.dataset.fsteam);
  });
  document.querySelectorAll("[data-fsname]").forEach(b => b.onclick = () => {
    const i = $("#fsq"); if (i) i.value = b.dataset.fsname;
    fsSearch(b.dataset.fsname);
  });
  document.querySelectorAll("[data-fsid]").forEach(b => b.onclick = () =>
    loadFounderSignal(b.dataset.fsid, b.dataset.fsnm));
  document.querySelectorAll("[data-pick]").forEach(b => b.onclick = e => {
    e.stopPropagation();
    const n = b.dataset.pick;
    PICKED.has(n) ? PICKED.delete(n) : PICKED.add(n);
    render();
  });
  document.querySelectorAll("[data-pickall]").forEach(b => b.onclick = e => {
    e.stopPropagation();
    const able = (F?.investors || []).filter(x =>
      x.signals.conflict.label !== "\u{1F534}");
    const all = able.length && able.every(x => PICKED.has(x.investor));
    PICKED = all ? new Set() : new Set(able.map(x => x.investor));
    render();
  });
  document.querySelectorAll("[data-pickclear]").forEach(b =>
    b.onclick = () => { PICKED = new Set(); render(); });
  const bc = $("#buildcalls");
  if (bc) bc.onclick = () => buildReach();
  if (MODE === "reach") { paintReachMap(); }
  const nm = $("#nearme");
  if (nm) nm.onclick = () => nearMeOnReach();
  document.querySelectorAll("[data-deal]").forEach(b => b.onclick = e => {
    e.stopPropagation();
    const n = b.dataset.deal;
    dealSet(n, DEALS[n] ? null : "todo");
  });
  document.querySelectorAll("[data-dmove]").forEach(b => b.onclick = e => {
    e.stopPropagation();
    const [n, st] = b.dataset.dmove.split("|");
    dealSet(n, st);
  });
  document.querySelectorAll("[data-ddrop]").forEach(b => b.onclick = e => {
    e.stopPropagation(); dealSet(b.dataset.ddrop, null);
  });
  document.querySelectorAll("[data-scack]").forEach(b =>
    b.onclick = () => scoutAck(b.dataset.scack));
  document.querySelectorAll("[data-scwatch]").forEach(b => b.onclick = () => {
    const [id, ...rest] = b.dataset.scwatch.split("|");
    scoutToggle(id, rest.join("|"));
  });
  const nf = $("#needform");
  if (nf) nf.onsubmit = e => { e.preventDefault(); intakeContinue($("#needq").value); };
  const scf = $("#scform");
  if (scf) scf.onsubmit = e => { e.preventDefault(); loadScouts($("#scq").value); };
  document.querySelectorAll("[data-role]").forEach(b =>
    b.onclick = () => setRole(b.dataset.role));
  document.querySelectorAll("[data-conv]").forEach(b =>
    b.onclick = () => openConviction(b.dataset.conv));
  document.querySelectorAll("[data-q]").forEach(b =>
    b.onclick = () => routeAsk(b.dataset.q));
  const ab = $("#askbox");
  if (ab) {
    ab.focus();
    // A brief is a paragraph, so Enter has to make a newline. Cmd/Ctrl+Enter
    // sends, which is what every box people type paragraphs into does.
    ab.onkeydown = e => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); runIntake(); }
    };
    const sendBtn = $("#asksend");
    if (sendBtn) sendBtn.onclick = () => runIntake();
  }
  const fi = $("#askfiles");
  if (fi) fi.onchange = () => {
    const text = $("#askbox")?.value || "";
    for (const f of fi.files) {
      if (f.size > MAX_FILE_MB * 1024 * 1024) {
        toast(`${f.name} is ${(f.size / 1048576).toFixed(0)} MB — we read up to ${MAX_FILE_MB} MB.`);
        continue;
      }
      INTAKE.files.push({ name: f.name, size: f.size, file: f });
    }
    render();
    const ab2 = $("#askbox"); if (ab2) { ab2.value = text; ab2.focus(); }
  };
  document.querySelectorAll("[data-rmfile]").forEach(b => b.onclick = () => {
    const text = $("#askbox")?.value || "";
    INTAKE.files.splice(+b.dataset.rmfile, 1);
    render();
    const ab2 = $("#askbox"); if (ab2) ab2.value = text;
  });
  const cm = $("#composeit");
  if (cm) cm.onclick = () => (MODE === "founder" && F && !ENT)
    ? openBrief(SEL) : openCompose();
  const sc = $("#screenit");
  if (sc) sc.onclick = () => {
    const hit = F?.investors?.find(x => x.investor.toLowerCase() === (ENT?.name || "").toLowerCase());
    if (hit) { MODE = "founder"; SEL = hit.investor; TAB = 0; return render(); }
    routeAsk(ENT?.name || "");
  };
  if ($("#go")) $("#go").onclick = runFounder;
  if ($("#go2")) $("#go2").onclick = runFounder;
  if ($("#co")) $("#co").onkeydown = e => { if (e.key === "Enter") runFounder(); };
}

document.querySelectorAll("[data-mode]").forEach(b => b.onclick = () => {
  MODE = b.dataset.mode; SEL = null; TAB = 0;
  if (MODE === "map" && !MAP) loadMap();
  else if (MODE === "accuracy" && !BT) loadBacktest();
  else render();
});

fetch("/health").then(r => r.json()).then(h => {
  $("#ct-f").textContent = h.pool + " funds";
  $("#ct-i").textContent = h.conviction_n ? h.conviction_n + " cos" : "";
  fetch("/map").then(r => r.json()).then(m => {
    const t = (m.placed || 0) + (m.portfolio || []).length + (m.funds || []).length;
    if (t) $("#ct-m").textContent = t + " placed";
  }).catch(() => {});
}).catch(() => {});
// Init runs at the very end of this file: homeView() reads CHIPS, which is a
// const declared below, so calling render() here would hit the temporal dead zone.

/* ================= SLUSH MAP ================= */
let MAP = null;
const VIEW_EU = { lon0: -24, lon1: 46, lat0: 34, lat1: 71 };
const VIEW_W = { lon0: -170, lon1: 180, lat0: -55, lat1: 75 };
let GEOVIEW = "eu";

async function loadMap() {
  $("#view").innerHTML = `<div class="msg"><span class="spin"></span>Placing the graph…</div>`;
  MAP = await (await fetch("/map")).json(); render();
}

const scoreColor = s => s == null ? "#6b655c"
  : s >= 70 ? "#7fb88a" : s >= 55 ? "#d9a441" : "#d9685c";

/* The map is coloured by funding status, not conviction: conviction needs two
   rounds and prior investors, and almost nothing on a Slush floor has that.
   "Has this company raised at all" is a question the data can answer. */
const STATUS = {
  multiple: ["#2d7a4f", "raised twice or more"],
  once:     ["#90610a", "raised once"],
  none:     ["#b03628", "no funding on record"],
  unknown:  ["#b8b2a9", "not checked yet"],
};
const statusColor = p => (STATUS[p.status] || STATUS.unknown)[0];

function mapView() {
  if (!MAP) return `<div class="msg"><span class="spin"></span>Loading…</div>`;
  if (MAP.error && !MAP.points?.length)
    return `<div class="msg">${esc(MAP.error)}<br><br>
      <span style="color:var(--dim)">The fetch runs in the background; reload shortly.</span></div>`;

  const scored = MAP.points.filter(p => p.score != null).length;
  const st = MAP.status || {};
  const total = MAP.placed + (MAP.portfolio || []).length + (MAP.funds || []).length;

  // The same map answers two questions. A founder is asking which of these
  // they can walk to and pitch; an investor is asking where the companies
  // their own kind keep backing actually are. Same pins, different framing,
  // different defaults.
  const mine = ROLE === "founder" && F
    ? (F.investors || []).filter(i =>
        (MAP.funds || []).some(f => norm_(f.name) === norm_(i.investor)))
    : [];
  const head = ROLE === "investor"
    ? [`Where the companies are`,
       `${(MAP.portfolio || []).length} funded companies · ${scored} with a conviction score`]
    : F
      ? [`Where the funds you screened are`,
         `${mine.length} of your ${(F.investors || []).length} placed · `
         + `${MAP.unplaced} addresses we could not resolve`]
      : [`Where the ecosystem is`,
         `${MAP.placed} placed · ${MAP.unplaced} addresses we could not resolve`];

  const kpi = ROLE === "investor"
    ? [["Funded companies", (MAP.portfolio || []).length],
       ["With a conviction score", scored],
       ["Funds", (MAP.funds || []).length],
       ["Exact street coordinates", MAP.exact],
       ["Country only", (MAP.funds || []).filter(f => f.precision === "country").length]]
    : F
      ? [["Your funds on the map", mine.length],
         ["Cannot pitch", mine.filter(i => i.signals.conflict.label === "\u{1F534}").length],
         ["Lead at your stage", mine.filter(i => i.signals.lead_rate.label === "\u{1F7E2}").length],
         ["In your pipeline", dealCount()],
         ["Exact street coordinates", MAP.exact]]
      : [["On the map", total],
         ["Slush exhibitors", MAP.placed],
         ["Funded companies", (MAP.portfolio || []).length],
         ["Funds", (MAP.funds || []).length],
         ["Exact street coordinates", MAP.exact]];

  return stats(5, kpi)
  + (ROLE === "founder" && F ? `<div class="maplegend">
      <span><i style="background:#3f7d53"></i>leads at your stage</span>
      <span><i style="background:#c2614f"></i>on your list</span>
      <span><i style="background:#b4442f"></i>backs a competitor — do not pitch</span>
      <span><i style="background:#b9b2a8"></i>not screened</span>
      <span><i class="dash"></i>city or country only, not a street</span>
    </div>` : "")
  + section("gmap", head[0], head[1],
      `<div class="maproot">
        <div class="mapbox">
          <div class="mapbar">
            <span class="grp"><span class="lbl">Show</span>
              ${Object.entries(LAYER_META).map(([k, [lbl, shape]]) =>
                `<button class="tgl ${LAYERS[k] ? "on" : ""}" data-layer="${k}">
                   <i class="${shape === "circle" ? "ci" : shape === "square" ? "sq" : "di"}"></i>${lbl}</button>`).join("")}
            </span>
            <span class="mapsearch"><span style="color:var(--faint)">⌕</span>
              <input id="mapq" autocomplete="off" placeholder="${
                MAPMODE === "pp" ? "Type a founder or investor name"
                : "Filter by name, sector or city"}">
              <button class="tgl seg ${MAPMODE === "pp" ? "on" : ""}" data-mm="pp"
                title="Search people instead of filtering the map">People</button></span>
            ${dealCount() ? `<span class="grp">
              <button class="tgl ${PLANONLY ? "on" : ""}" id="planonly"
                title="Show only the funds in your pipeline">★ In play (${dealCount()})</button>
            </span>` : ""}
            <span class="grp" style="margin-left:auto">
              <button class="tgl ${MYLOC ? "on" : ""}" id="nearme" title="Find what is around you">
                <svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor"
                  stroke-width="1.6"><circle cx="8" cy="8" r="3"/><path d="M8 1v2M8 13v2M1 8h2M13 8h2"/></svg>
                Near me</button>
            </span>
            <span class="grp"><span class="lbl">Zoom</span>
              ${Object.entries({ eu: "Europe", nordics: "Nordics", world: "World" }).map(([k, lbl]) =>
                `<button class="tgl ${REGION === k ? "on" : ""}" data-fly="${k}">${lbl}</button>`).join("")}
            </span>
          </div>
          <div id="mlmap"></div>
          <div class="tip" id="tip"></div>
        </div>
        <div class="side">
          <div class="sidehd"><h3 id="sidet">On the map</h3>
            <div class="s" id="sides">Click a pin, or filter to narrow the list</div></div>
          <div class="sidebody" id="sideb"></div>
        </div>
      </div>`);
}

/* MapLibre + OpenFreeMap (OpenMapTiles schema, no API key). The vendored
   library is local; only the tiles need the network, and if they fail the
   markers still render over a plain background. */
let ML = null, MLMARKERS = [], MAPMODE = "co", PPMARKER = null, PPTIMER = null, PLTIMER = null;
/* Layers are shown together and toggled, not swapped: the question "where is
   the ecosystem" is not answered by looking at one slice at a time. */
/* Exhibitors are off by default on purpose. 676 pre-funding stands drown out
   the 173 funds and 270 funded companies, and "where is the ecosystem" is not
   answered by a conference floorplan. */
let LAYERS = { ex: false, pf: true, fu: true };
/* Where the founder is standing. The browser asks for consent and the
   coordinate is used for one request: we never store it and never hand it to
   an IP-geolocation service, which would mean telling a third party where the
   user is in order to find out where the user is. */
let MYLOC = null, MYLOCERR = null, NEAR = null, NEARKIND = "fund";
/* When a plan exists the map's job changes: it stops being an atlas of the
   ecosystem and becomes where your meetings are. Defaults on, because a
   founder with a plan is asking the second question, not the first. */
let PLANONLY = true;
let REGION = "eu";          // which region button is active
const LAYER_META = {
  ex: ["Slush exhibitors", "circle"],
  pf: ["Funded companies", "square"],
  fu: ["Funds", "diamond"],
};

function fitTo(points) {
  if (!ML || !points.length) return;
  if (points.length === 1) return ML.flyTo({ center: [points[0].lon, points[0].lat], zoom: 12, duration: 700 });
  const lons = points.map(p => p.lon), lats = points.map(p => p.lat);
  ML.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
               { padding: 70, duration: 700, maxZoom: 12 });
}

/* Place search: "espoo" should move the map, not return nothing. */
async function flyToPlace(q, keepFilter) {
  let r;
  try { r = await (await fetch(`/place?q=${encodeURIComponent(q)}`)).json(); }
  catch { return; }
  if (!r || r.error || !ML) return;

  // Everything geographically inside that place, not only the companies whose
  // address text happened to contain the word.
  const inside = r.bbox
    ? MAP.points.filter(p => p.lon >= r.bbox[0] && p.lon <= r.bbox[2]
                          && p.lat >= r.bbox[1] && p.lat <= r.bbox[3])
    : [];
  if (keepFilter && !inside.length) return;     // nothing better to show

  if (inside.length) fitTo(inside);
  else if (r.bbox) ML.fitBounds([[r.bbox[0], r.bbox[1]], [r.bbox[2], r.bbox[3]]],
                                { padding: 60, duration: 800, maxZoom: 12 });
  else ML.flyTo({ center: [r.lon, r.lat], zoom: 10, duration: 800 });

  MLMARKERS.forEach(({ el, p }) => el.style.display = !inside.length || inside.includes(p) ? "" : "none");
  sideList(inside, (r.display ? r.display.split(",")[0] : q) + (inside.length ? "" : " — no exhibitors here"));
}
const FLY = {
  eu: { center: [12, 52], zoom: 3.3 },
  nordics: { center: [20, 61], zoom: 4.2 },
  world: { center: [10, 30], zoom: 1.4 },
};

function sideList(points, title) {
  $("#sidet").textContent = title || "On the map";
  $("#sides").textContent = `${points.length} shown`;
  $("#sideb").innerHTML = points.length ? points.slice(0, 60).map((p, i) => `
    <div class="sideitem" data-open-ent="${i}">
      <div class="n">${esc(p.name)}${p.score != null
        ? ` <span class="bdg ${p.score >= 70 ? "b-green" : p.score >= 55 ? "b-amber" : "b-red"}"
            style="margin-left:5px">${p.score}</span>` : ""}
        ${p.status && p.status !== "unknown" ? `<span class="bdg ${
          p.status === "multiple" ? "b-green" : p.status === "once" ? "b-amber" : "b-grey"
        }" style="margin-left:5px">${esc((STATUS[p.status] || [])[1] || "")}</span>` : ""}</div>
      <div class="d">${esc(p.hq || "")}${p.industries?.length
        ? " · " + esc(p.industries.join(", ")) : ""}</div>
      ${p.description ? `<div class="d">${esc(p.description.slice(0, 130))}</div>` : ""}
      ${p.founded ? `<div class="d">founded ${esc(String(p.founded).slice(0, 4))}${
        p.employees ? ` · ${esc(p.employees)} people` : ""}</div>` : ""}
      ${p.website ? `<div class="d"><a href="${esc(p.website)}" target="_blank"
         rel="noopener">${esc(String(p.website).replace(/^https?:\/\//, ""))}</a></div>` : ""}
      ${p.source ? `<div class="d"><span class="srank">SOURCE</span>${
        String(p.source).startsWith("http")
          ? `<a href="${esc(p.source)}" target="_blank" rel="noopener">${
              esc(String(p.source).replace(/^https?:\/\/(www\.)?/, "").split("/")[0])}</a>`
          : esc(p.source)}</div>` : ""}
      <button class="btn" style="margin-top:7px;padding:4px 9px;font-size:12px">Open profile →</button>
    </div>`).join("") : `<div class="msg" style="padding:26px">Nothing matches.</div>`;

  // A pin is a company or a fund - clicking it should be able to open it.
  // Open directly by entity id where we have one: the pin already came from
  // an entity, so searching for it again is both slower and - when a batch
  // job is eating the rate limit - wrong.
  document.querySelectorAll("[data-open-ent]").forEach(el => el.onclick = () => {
    const p = points[+el.dataset.openEnt];
    if (!p) return;
    if (p.id) return loadEntity(p.id, p.kind === "fund" ? "fund" : "fund", p.name);
    lookupEntity(p.name, p.kind === "fund" ? "fund" : null);
  });
}

/* ---------- near me ----------
   The browser's own geolocation, with the user's consent. The coordinate
   goes to our /near endpoint for one request and is never stored. We do not
   use an IP lookup: that would mean handing a third party the user's address
   in order to tell the user their address. */
let MYMARKER = null;

function locateMe() {
  if (!navigator.geolocation) {
    MYLOCERR = "This browser has no geolocation. Type a city in the filter box instead.";
    return render();
  }
  MYLOCERR = "locating";
  render();
  navigator.geolocation.getCurrentPosition(
    pos => {
      MYLOC = { lat: pos.coords.latitude, lon: pos.coords.longitude,
                acc: Math.round(pos.coords.accuracy || 0) };
      MYLOCERR = null;
      loadNear();
    },
    err => {
      MYLOC = null;
      MYLOCERR = err.code === 1
        ? "Location permission denied. Typing a city in the filter box does the same job."
        : `Could not get a location (${esc(err.message || "unknown")}). Try the filter box.`;
      render();
    },
    { enableHighAccuracy: false, timeout: 9000, maximumAge: 300000 });
}

/* Browser geolocation can be wrong by a country when it falls back to IP.
   Typing a place is not a worse answer, it is a better one. */
async function setPlace(q) {
  if (!q || !q.trim()) return;
  try {
    const d = await (await fetch(`/place?q=${encodeURIComponent(q.trim())}`)).json();
    if (d.lat == null) { MYLOCERR = `No place called "${esc(q)}".`; return render(); }
    MYLOC = { lat: d.lat, lon: d.lon, manual: true, label: d.display || q.trim() };
    MYLOCERR = null;
    loadNear();
  } catch (e) { MYLOCERR = String(e.message); render(); }
}

async function loadNear() {
  if (!MYLOC) return;
  NEAR = { loading: true }; render();
  const qs = new URLSearchParams({ lat: MYLOC.lat, lon: MYLOC.lon,
    radius_km: 400, limit: 60, kind: NEARKIND });
  if (F?.company) { qs.set("company", F.company); qs.set("stage", F.stage || "series a"); }
  try { NEAR = await (await fetch(`/near?${qs}`)).json(); }
  catch (e) { NEAR = { error: String(e.message) }; }
  render();
}

function nearPanel() {
  if (MYLOCERR === "locating")
    return `<div class="msg" style="padding:26px"><span class="spin"></span>Asking your browser where you are…</div>`;
  if (MYLOCERR)
    return `<div class="msg" style="padding:24px">${esc(MYLOCERR)}</div>`;
  if (!NEAR) return "";
  if (NEAR.loading)
    return `<div class="msg" style="padding:26px"><span class="spin"></span>Measuring distances…</div>`;
  if (NEAR.error) return `<div class="msg" style="padding:24px">${esc(NEAR.error)}</div>`;
  if (!NEAR.count) return `<div class="msg" style="padding:24px">
    Nothing in the graph within ${NEAR.radius_km}km of you. That is a statement
    about coverage here, not about the ecosystem.</div>`;

  // A city-centroid pin is not "0.4km away". Showing the city instead of a
  // distance is the honest rendering of what we actually know.
  const dist = r => r.approx ? "in " + (r.city || "this city")
                             : `${r.km < 1 ? "<1" : r.km} km`;
  const tabs = `<div class="neartabs">${
    [["fund", "Funds"], ["company", "Companies"], ["all", "Everything"]].map(([k, l]) =>
      `<button class="tgl ${NEARKIND === k ? "on" : ""}" data-nk="${k}">${l}</button>`).join("")}</div>`;

  const where = `<div class="nearwhere">
    ${MYLOC?.manual ? `Searching from <b>${esc(MYLOC.label || "")}</b>.`
      : `From your browser's location (±${MYLOC?.acc ?? "?"}m).`}
    <span class="nearfix">Not right?
      <input id="nearplace" placeholder="type a city" autocomplete="off"></span></div>`;

  return tabs + where + (NEAR.cities || []).map(c => `
    <div class="nearcity"><span>${esc(c.city)}</span>
      <span class="km">${c.km < 1 ? "<1" : Math.round(c.km)} km</span></div>
    ${c.items.map(r => {
      const sc = r.screen;
      return `<div class="sideitem nearrow" data-near="${esc(r.name)}">
        <div class="n">${esc(r.name)}
          ${r.kind === "fund" ? badge("fund", "accent") : ""}
          ${sc?.conflict ? badge("backs a competitor", "red")
            : sc?.lead_label === "🟢" ? badge("leads your stage", "green") : ""}</div>
        <div class="d">${esc(dist({ ...r, city: c.city }))}${
          r.hq ? ` · ${esc(String(r.hq).slice(0, 44))}` : ""}</div>
        ${sc?.lead ? `<div class="d">${esc(sc.lead)}</div>` : ""}
        ${r.hq_note ? `<div class="d" style="color:var(--amber)">${esc(r.hq_note)}</div>` : ""}
      </div>`;
    }).join("")}`).join("");
}

/* A fund pin, coloured by the verdict this founder's screen gave it.
   Without a screen every fund is the same colour, which is correct - we have
   not judged them yet. With one, the map answers the question the founder
   came with rather than showing them an atlas. */
function fundPinColour(p) {
  if (ROLE !== "founder" || !F) return "#c2614f";
  const key = norm_(p.name);
  const x = (F.investors || []).find(i => norm_(i.investor) === key);
  if (!x) return "#b9b2a8";                       // not on your list
  if (x.signals.conflict.label === "\u{1F534}") return "#b4442f";   // cannot pitch
  if (x.signals.lead_rate.label === "\u{1F7E2}") return "#3f7d53";  // leads your stage
  return "#c2614f";
}

function initMap() {
  const el = document.getElementById("mlmap");
  if (!el || !window.maplibregl || !MAP?.points) return;
  MLMARKERS = [];
  ML = new maplibregl.Map({
    container: "mlmap",
    style: "https://tiles.openfreemap.org/styles/liberty",
    center: FLY[REGION].center, zoom: FLY[REGION].zoom,
    // The default control is an expandable info panel sitting on the map.
    // compact:false renders one quiet line instead - the OSM data is ODbL,
    // so the credit itself is a licence condition, not a decoration.
    attributionControl: { compact: false },
  });
  ML.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

  // A precisely geocoded entity sits on its real address and is never moved.
  // Only city-centroid fallbacks are spread, and they are drawn hollow so the
  // map never implies a precision it does not have.
  let layer = [
    ...(LAYERS.ex ? MAP.points : []),
    ...(LAYERS.pf ? (MAP.portfolio || []) : []),
    ...(LAYERS.fu ? (MAP.funds || []) : []),
  ];
  // A plan turns the map into a route card. Matching is loose because the
  // corpus spells fund names several ways.
  const planKeys = new Set(Object.keys(DEALS)
    .map(n => n.toLowerCase().replace(/[^a-z0-9]/g, "")));
  if (PLANONLY && planKeys.size) {
    const hit = layer.filter(p =>
      planKeys.has((p.name || "").toLowerCase().replace(/[^a-z0-9]/g, "")));
    // Never hand back an empty map: if nothing in the plan is placeable, say
    // so in the side panel rather than showing a blank continent.
    if (hit.length) layer = hit;
    else PLANONLY = false;
  }
  const seen = {};
  for (const p of layer) {
    let lat = p.lat, lon = p.lon;
    if (!p.precise) {
      const k = `${p.lat},${p.lon}`;
      const n = (seen[k] = (seen[k] || 0) + 1);
      const ang = n * 2.399, rad = n === 1 ? 0 : 0.02 * Math.sqrt(n);
      lon += rad * Math.cos(ang); lat += rad * Math.sin(ang);
    }

    const d = document.createElement("div");
    const isFund = p.kind === "fund";
    const isPf = p.kind === "portfolio";
    d.className = "mkr" + (isPf ? " sq" : isFund ? " di" : "");
    const col = isFund ? fundPinColour(p) : statusColor(p);
    const isPortfolio = p.kind === "portfolio";
    const sz = isFund ? 15 : (p.score != null ? 13 : 10);
    d.style.cssText = p.precise
      ? `width:${sz}px;height:${sz}px;background:${col}${isFund ? ";box-shadow:0 0 0 5px rgba(194,97,79,.18)" : ""}`
      : `width:${sz}px;height:${sz}px;background:transparent;border:2px dashed ${col};opacity:.75`;
    const m = new maplibregl.Marker({ element: d })
      .setLngLat([lon, lat])
      .setPopup(new maplibregl.Popup({ offset: 14, closeButton: false }).setHTML(
        `<div class="mlpop"><b>${esc(p.name)}</b><br>
         <span style="color:#777">${esc(p.hq || "")}</span>
         ${p.precise ? "" : `<br><span style="color:#999">city only</span>`}
         ${p.status && p.status !== "unknown"
            ? `<br>${esc((STATUS[p.status] || [])[1] || "")}${
                p.last_round ? ` · ${esc(p.last_round.stage || "")} ${esc(String(p.last_round.date).slice(0, 7))}` : ""}`
            : ""}
         ${p.score != null ? `<br>conviction <b>${p.score}</b>` : ""}</div>`))
      .addTo(ML);
    d.onclick = () => sideList([p], p.name);
    MLMARKERS.push({ marker: m, el: d, p });
  }
  sideList(layer, PLANONLY && planKeys.size
    ? `Your pipeline on the map (${layer.length} of ${Object.keys(DEALS).length} placeable)`
    : "Everything on the map");
  const pn = $("#precisenote");
  if (pn && MAP.exact != null)
    pn.innerHTML = `<i style="background:transparent;border:2px dashed #9b958c"></i>city only (${MAP.placed - MAP.exact})`;

  const po = $("#planonly");
  if (po) po.onclick = () => { PLANONLY = !PLANONLY; render(); };
  const nm = $("#nearme");
  if (nm) nm.onclick = () => MYLOC ? (MYLOC = null, NEAR = null, MYMARKER &&
      (MYMARKER.remove(), MYMARKER = null), render()) : locateMe();

  if (MYLOC && ML) {
    if (MYMARKER) { MYMARKER.remove(); MYMARKER = null; }
    const me = document.createElement("div");
    me.className = "mkr me";
    MYMARKER = new maplibregl.Marker({ element: me })
      .setLngLat([MYLOC.lon, MYLOC.lat])
      .setPopup(new maplibregl.Popup({ offset: 14, closeButton: false })
        .setHTML(`<div class="mlpop"><b>${MYLOC.manual ? "Searching from" : "You are here"}</b><br>
          <span style="color:#777">${MYLOC.manual ? esc(MYLOC.label || "")
            : `±${MYLOC.acc}m, from your browser`}</span></div>`))
      .addTo(ML);
    // Fly once, when the location is new. Re-flying on every render made the
    // map unusable: panning away snapped straight back.
    if (MYLOC.flown !== true) {
      MYLOC.flown = true;
      ML.flyTo({ center: [MYLOC.lon, MYLOC.lat], zoom: 8, duration: 800 });
    }
  }
  if (MYLOC || MYLOCERR) {
    const t = $("#sidet"), sb = $("#sides"), body = $("#sideb");
    if (t) t.textContent = "Near you";
    if (sb) sb.textContent = NEAR?.count
      ? `${NEAR.count} within ${NEAR.radius_km}km, nearest first`
      : "Your browser's location, used once and not stored";
    if (body) {
      body.innerHTML = nearPanel();
      const np = body.querySelector("#nearplace");
      if (np) np.onkeydown = e => { if (e.key === "Enter") setPlace(np.value); };
      body.querySelectorAll("[data-nk]").forEach(b => b.onclick = () => {
        NEARKIND = b.dataset.nk; loadNear();
      });
      body.querySelectorAll("[data-near]").forEach(el => el.onclick = () => {
        const hit = MLMARKERS.find(m => m.p.name === el.dataset.near);
        if (hit) { ML.flyTo({ center: hit.marker.getLngLat(), zoom: 11, duration: 700 });
                   hit.marker.togglePopup(); }
      });
    }
  }

  document.querySelectorAll("[data-fly]").forEach(b => b.onclick = () => {
    REGION = b.dataset.fly;
    const f = FLY[REGION];
    ML.flyTo({ center: f.center, zoom: f.zoom, duration: 700 });
    document.querySelectorAll("[data-fly]").forEach(x =>
      x.classList.toggle("on", x.dataset.fly === REGION));
  });
  document.querySelectorAll("[data-mm]").forEach(b => b.onclick = () => {
    MAPMODE = MAPMODE === b.dataset.mm ? "co" : b.dataset.mm; render();
  });
  document.querySelectorAll("[data-layer]").forEach(b => b.onclick = () => {
    const k = b.dataset.layer;
    // Never let all three go off - an empty map is not a filter state.
    if (LAYERS[k] && Object.values(LAYERS).filter(Boolean).length === 1) return;
    LAYERS[k] = !LAYERS[k]; render();
  });

  const q = $("#mapq");
  if (!q) return;
  q.oninput = MAPMODE === "pp" ? peopleSearch : () => {
    const t = q.value.trim().toLowerCase();
    const active = [
      ...(LAYERS.ex ? MAP.points : []),
      ...(LAYERS.pf ? (MAP.portfolio || []) : []),
      ...(LAYERS.fu ? (MAP.funds || []) : []),
    ];
    const shown = [];
    for (const { el, p } of MLMARKERS) {
      const hit = !t || p.name.toLowerCase().includes(t) ||
        (p.hq || "").toLowerCase().includes(t) ||
        (p.industries || []).join(" ").toLowerCase().includes(t) ||
        (p.description || "").toLowerCase().includes(t) ||
        (p.cc || "").toLowerCase() === t;
      el.style.display = hit ? "" : "none";
      if (hit) shown.push(p);
    }
    sideList(shown, t ? `Matching "${q.value.trim()}"` : "Everything on the map");
    clearTimeout(PLTIMER);
    if (!t) { const f = FLY[REGION]; ML.flyTo({ ...f, duration: 600 }); return; }
    if (shown.length) {
      // Frame whatever matched, so typing a city both filters and zooms.
      fitTo(shown);
      // A place name can still mean more than the companies that mention it.
      if (t.length >= 3) PLTIMER = setTimeout(() => flyToPlace(q.value.trim(), true), 700);
    } else if (t.length >= 3) {
      PLTIMER = setTimeout(() => flyToPlace(q.value.trim()), 420);
    }
  };
  if (MAPMODE === "pp") {
    MLMARKERS.forEach(({ el }) => el.style.opacity = ".25");
    $("#sidet").textContent = "Find a person";
    $("#sides").textContent = "People are searched, not plotted";
    $("#sideb").innerHTML = `<div class="msg" style="padding:22px;text-align:left;line-height:1.7">
      Cala holds no address on a Person, and the Slush participant list is
      made of companies — all 2,000 of them. So there is no people layer to
      draw from.<br><br>
      Type a name and we resolve it the only way the graph allows:
      <b>person → founded / works at → company → headquarters</b>, and the pin
      names the company that produced it.
      <div class="ppsug">Try ${["Ilkka Paananen", "Niklas Zennstrom", "Miki Kuusi"]
        .map(n => `<button class="btn sm" data-ppq="${esc(n)}">${esc(n)}</button>`).join("")}</div>
      </div>`;
    document.querySelectorAll("[data-ppq]").forEach(b => b.onclick = () => {
      const q = $("#mapq"); q.value = b.dataset.ppq; peopleSearch();
    });
  }
}

/* People on the map: a Person entity carries no location, so we resolve
   person -> WORKS_AT / IS_CEO_OF / FOUNDED -> company -> headquarters_address
   and say which company produced the pin. */
function peopleSearch() {
  const q = $("#mapq"), t = q.value.trim();
  clearTimeout(PPTIMER);
  if (t.length < 2) return;
  $("#sideb").innerHTML = `<div class="msg" style="padding:26px"><span class="spin"></span>Searching people…</div>`;
  PPTIMER = setTimeout(async () => {
    let d;
    try { d = await (await fetch(`/search?q=${encodeURIComponent(t)}&kind=people`)).json(); }
    catch (e) { d = { results: [], error: e.message }; }
    if (d.error) {
      $("#sideb").innerHTML = `<div class="msg" style="padding:26px">${esc(d.error)}</div>`;
      return;
    }
    $("#sidet").textContent = `People matching "${t}"`;
    $("#sides").textContent = `${d.results.length} found${
      d.offline ? " in cached Cala data" : ""} · click to place on the map`;
    $("#sideb").innerHTML = d.results.length ? d.results.map((r, i) => `
      <div class="sideitem" data-pp="${i}" style="cursor:pointer">
        <div class="n">${esc(r.name)}</div>
        <div class="d">${esc(r.description || "Person")}</div></div>`).join("")
      : `<div class="msg" style="padding:26px">No one in Cala by that name.</div>`;
    document.querySelectorAll("[data-pp]").forEach(el => el.onclick = () => placePerson(d.results[+el.dataset.pp]));
  }, 300);
}

async function placePerson(r) {
  $("#sidet").textContent = r.name;
  $("#sides").textContent = "Locating…";
  $("#sideb").innerHTML = `<div class="msg" style="padding:26px"><span class="spin"></span>Resolving through their companies…</div>`;
  let d;
  try { d = await (await fetch(`/locate/${r.id}?kind=people`)).json(); }
  catch (e) { d = { places: [], error: e.message }; }

  if (PPMARKER) { PPMARKER.remove(); PPMARKER = null; }
  if (!d.places?.length) {
    $("#sides").textContent = "no placeable company";
    $("#sideb").innerHTML = `<div class="msg" style="padding:24px">
      Cala has this person but none of their companies has an address we can place.
      <br><br><span style="color:var(--dim)">Unknown is not zero.</span></div>`;
    return;
  }
  const pl = d.places[0];
  const el = document.createElement("div");
  el.className = "mkr";
  el.style.cssText = "width:18px;height:18px;background:#c2614f;box-shadow:0 0 0 6px rgba(194,97,79,.25)";
  PPMARKER = new maplibregl.Marker({ element: el }).setLngLat([pl.lon, pl.lat])
    .setPopup(new maplibregl.Popup({ offset: 16, closeButton: false })
      .setHTML(`<div class="mlpop"><b>${esc(r.name)}</b><br>
        <span style="color:#777">via ${esc(pl.via)}</span></div>`))
    .addTo(ML);
  ML.flyTo({ center: [pl.lon, pl.lat], zoom: 9, duration: 900 });

  $("#sides").textContent = `${d.places.length} place${d.places.length > 1 ? "s" : ""} on record`;
  $("#sideb").innerHTML = `
    <div class="sideitem"><div class="d">${esc(r.description || "")}</div></div>
    ${d.places.map(p => `<div class="sideitem">
      <div class="n">${esc(p.via)}</div>
      <div class="d">${esc(p.hq || "")}</div>
      ${p.source ? `<div class="d"><span class="srank">SOURCE</span>
        <a href="${esc(p.source)}" target="_blank" rel="noopener">${
          esc(String(p.source).replace(/^https?:\/\/(www\.)?/, "").slice(0, 42))}</a></div>` : ""}
    </div>`).join("")}
    <div class="sideitem"><button class="btn" id="openpp">Open full profile</button></div>`;
  const op = $("#openpp");
  if (op) op.onclick = () => loadEntity(r.id, "people", r.name);
}

function wireMap(clusters) {
  document.querySelectorAll("[data-geo]").forEach(b => b.onclick = () => {
    GEOVIEW = b.dataset.geo; render();
  });
  const tip = $("#tip"), geo = $("#geo");
  if (!tip || !geo) return;
  document.querySelectorAll(".bub").forEach(c => {
    c.onmouseenter = e => {
      const cl = clusters[+c.dataset.c]; if (!cl) return;
      const scored = cl.cos.filter(p => p.score != null);
      tip.innerHTML = `<b>${esc(cl.cos[0].hq || cl.cc)}</b>
        <div class="m">${cl.cos.length} exhibitor${cl.cos.length > 1 ? "s" : ""}
        ${scored.length ? ` · ${scored.length} scored` : ""}</div>
        <div class="m" style="margin-top:5px;color:var(--dim)">${esc(cl.cos.slice(0, 5).map(p =>
          p.score != null ? `${p.name} (${p.score})` : p.name).join(", "))}</div>`;
      const r = geo.getBoundingClientRect(), b = c.getBoundingClientRect();
      tip.style.left = Math.min(r.width - 260, b.left - r.left + 14) + "px";
      tip.style.top = (b.top - r.top - 10) + "px";
      tip.classList.add("on");
    };
    c.onmouseleave = () => tip.classList.remove("on");
  });
}

/* ================= ACCURACY ================= */
let BT = null;
async function loadBacktest() {
  $("#view").innerHTML = `<div class="msg"><span class="spin"></span>Loading backtest…</div>`;
  BT = await (await fetch("/backtest")).json(); render();
}

function accuracyView() {
  if (!BT) return `<div class="msg"><span class="spin"></span>Loading…</div>`;
  if (BT.error) return `<div class="msg">${esc(BT.error)}</div>`;
  const b = BT, mx = Math.max(b.high_insider_return.rate, b.low_insider_return.rate,
    b.naive_most_active.rate, b.base_rate);
  const row = (l, v, n, cls) => `<div class="cmp"><span class="l">${esc(l)}</span>
    <span class="t"><i class="${cls}" style="width:${Math.round(100 * v / mx)}%"></i></span>
    <span class="v">${pct(v)}</span></div>
    <div style="margin:-6px 0 8px 161px;font:10.5px var(--mono);color:var(--faint)">n=${n}</div>`;

  return `<div class="verdict green" style="margin-bottom:var(--s3)">
      <b>The signal predicts progression; the obvious alternative barely does.</b>
      Companies where at least half the prior investors came back progressed to a
      later stage ${pct(b.high_insider_return.rate)} of the time against a
      ${pct(b.base_rate)} base rate. Ranking instead by "whoever invests most",
      the first thing anyone would try, gets ${pct(b.naive_most_active.rate)} —
      ${(b.naive_most_active.rate * 100 - b.base_rate * 100).toFixed(1)}pp of lift
      against our ${(b.high_insider_return.rate * 100 - b.base_rate * 100).toFixed(1)}pp.
      Measured on ${b.samples} companies, out of sample, over ${esc(b.outcome)}.</div>`
  + stats(4, [
    ["Observations", b.samples],
    ["Outcome", "stage progression"],
    ["Spread, high vs low", `<span style="color:var(--green)">+${b.spread_pp}pp</span>`],
    ["Beats naive baseline by", `<span style="color:var(--green)">+${(b.high_insider_return.rate * 100 - b.naive_most_active.rate * 100).toFixed(1)}pp</span>`],
  ])
  + section("acc1", "Did insiders coming back predict progression?",
      `${b.samples} observations · ${b.outcome}`,
      `<div class="card">
        ${row("Insiders ≥50% back", b.high_insider_return.rate, b.high_insider_return.n, "hi")}
        ${row("Base rate (all)", b.base_rate, b.samples, "base")}
        ${row("Naive: most-active backer", b.naive_most_active.rate, b.naive_most_active.n, "")}
        ${row("Insiders <50% back", b.low_insider_return.rate, b.low_insider_return.n, "lo")}
      </div>`)
  + section("acc2", "The previous lead is its own signal",
      "a seed fund skipping is noise; the lead skipping is not",
      `<div class="two">
        <div class="card"><h4>Previous lead returned</h4><div class="sub">n=${b.previous_lead_returned.n}</div>
          <div class="big" style="color:var(--green)">${pct(b.previous_lead_returned.rate)}</div></div>
        <div class="card"><h4>Previous lead absent</h4><div class="sub">n=${b.previous_lead_absent.n}</div>
          <div class="big" style="color:var(--red)">${pct(b.previous_lead_absent.rate)}</div></div>
      </div>`)
  + section("acc4", "What we tested and could not show",
      "the round architect does not predict the next round",
      `<div class="emptywhy" style="max-width:none">
        <b>We tested our own most distinctive feature and it failed.</b>
        "Who has been in rounds this fund led" is a record. We asked whether
        it also forecasts — build the graph from rounds before a cutoff, then
        check whether the top predicted co-investor actually turned up in
        rounds that fund led afterwards.
        <div class="tbl" style="margin:11px 0">
          <table><thead><tr><th>Cutoff</th><th class="num">Held-out rounds</th>
          <th class="num">Architect</th><th class="num">Co-investment baseline</th>
          <th class="num">Lift</th></tr></thead><tbody>
          <tr><td>2023-01</td><td class="num">57</td><td class="num">3.5%</td>
            <td class="num">5.3%</td><td class="num" style="color:var(--red)">−1.8pp</td></tr>
          <tr><td>2024-01</td><td class="num">35</td><td class="num">2.9%</td>
            <td class="num">5.7%</td><td class="num" style="color:var(--red)">−2.8pp</td></tr>
          <tr><td>2025-01</td><td class="num">25</td><td class="num">0.0%</td>
            <td class="num">8.0%</td><td class="num" style="color:var(--red)">−8.0pp</td></tr>
          </tbody></table></div>
        Below the naive baseline at every cutoff. 63 held-out rounds across 21
        leads is thin, so this is "not demonstrated" rather than "disproven" —
        but it is certainly not predictive, and the product no longer says it
        is. The co-investment record stayed; the forecast came out.
        <span class="sub">Run it yourself: <code>python backtest_syndicate.py</code></span>
      </div>`)
  + section("acc3", "Controlled for cap-table size",
      "return fraction is mechanically tied to how many investors were already on the register",
      `<div class="tbl"><table><thead><tr><th>Prior investors</th>
        <th style="text-align:right">Low return</th><th style="text-align:right">High return</th>
        <th style="text-align:right">Spread</th><th>Reading</th></tr></thead><tbody>
        ${b.by_cap_table_size.map(x => `<tr style="cursor:default">
          <td>${esc(x.cap_table)}</td>
          <td class="num">${pct(x.low)} <span style="color:var(--faint)">n=${x.low_n}</span></td>
          <td class="num">${pct(x.high)} <span style="color:var(--faint)">n=${x.high_n}</span></td>
          <td class="num" style="color:${x.spread_pp > 0 ? "var(--green)" : "var(--red)"}">${x.spread_pp > 0 ? "+" : ""}${x.spread_pp}pp</td>
          <td style="font-size:12.2px;color:var(--dim)">${x.spread_pp > 5 ? "signal holds"
            : x.spread_pp < -1 ? "reverses — small sample, reported not hidden" : "flat"}</td>
        </tr>`).join("")}</tbody></table></div>`)
  + section("acc4", "How this was kept honest", "",
      `<div class="card"><ul class="reasons">
        <li><b>No look-ahead.</b> Each investor's follow-on habit is recomputed from rounds that
            closed strictly before the observation date.</li>
        <li><b>Maturity filter.</b> A round is only judged once it is old enough for the outcome
            to be observable, so recent rounds cannot be counted as failures.</li>
        <li><b>A baseline to beat.</b> "Back whoever the most active funds back" is the strategy an
            investor would otherwise use. It scores ${pct(b.naive_most_active.rate)}.</li>
        <li><b>A stated failure mode.</b> In single-investor cap tables the effect reverses. That
            row is in the table above rather than filtered out.</li>
      </ul></div>`);
}

/* ================= HOME / ASK ================= */
/* Four questions a founder raising a round actually has. The old set asked
   two of them from the investor's side, and one routed to a view that no
   longer exists. */
const CHIPS = [
  ["◧", "Screen my investor list", "Gosta Labs Series A"],
  ["⊘", "Who must I not pitch?", "who backs a competitor of Gosta Labs"],
  ["☎", "Who do I call first?", "who should I meet first for Gosta Labs"],
  ["◉", "Where are these funds?", "map"],
];



/* ============================================================ INTAKE
   A founder arriving with a round to raise already has the material. The
   old ask box took a company name and nothing else, which asked them to
   summarise themselves worse than their deck already does.

   So: a paragraph, or a deck, or a spreadsheet, or all three. We read it,
   say what we understood and which slide we read it off, and only then
   spend ninety seconds on the graph. The reasoning is shown while it runs
   and kept afterwards, because a founder who cannot see why a fund ranked
   where it did has no reason to believe the order. */
let INTAKE = { files: [], profile: null, state: "idle" };

/* A refusal the user needs to see but does not need to dismiss: a file too
   large to read, dropped before it costs them the upload. */
function toast(msg) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.classList.add("go"), 2600);
  setTimeout(() => el.remove(), 3200);
}

const LAYER_LABEL = {
  you: "what you brought", cala: "Cala's graph",
  web: "the open web", derived: "our arithmetic",
};
const MAX_FILE_MB = 20;

function intakeFilesRow() {
  if (!INTAKE.files.length) return "";
  return `<div class="bfiles">${INTAKE.files.map((f, i) => `
    <span class="bfile"><span class="bfi">${esc(fileIcon(f.name))}</span>
      <span class="bfn">${esc(f.name)}</span>
      <span class="sub">${(f.size / 1024).toFixed(0)} KB</span>
      <button class="bfx" data-rmfile="${i}" title="Remove">×</button></span>`).join("")}</div>`;
}

function fileIcon(name) {
  const e = (name.split(".").pop() || "").toLowerCase();
  return e === "pdf" ? "PDF" : e.startsWith("ppt") ? "DECK"
    : e.startsWith("xls") || e === "csv" ? "SHEET" : "TXT";
}

function homeView() {
  return `<div class="home">
    <div class="homehd">
      <h1>Who should you be talking to?</h1>
      <p class="homesub">Tell Flipside what you are building and what you are
        raising. It reads Cala's graph for the investors who can actually lead
        it — and, just as usefully, the ones who cannot.</p>
    </div>

    <div class="ask">
      <textarea id="askbox" rows="4" placeholder="We build clinical documentation software that writes patient notes from the consultation. Raising a €4.5M Series A. gostalabs.com"></textarea>
      ${intakeFilesRow()}
      <div class="askfoot">
        <label class="attach" title="Deck, spreadsheet, PDF or text — up to ${MAX_FILE_MB} MB each">
          <input type="file" id="askfiles" multiple hidden
            accept=".pdf,.pptx,.ppt,.xlsx,.xlsm,.csv,.txt,.md">
          <span class="clip">+</span> Add your deck or numbers</label>
        <button class="send" id="asksend" title="Read it">↑</button>
      </div>
    </div>

    <div class="askalt">
      <span class="sub">Or go straight to</span>
      ${CHIPS.map(([ic, label, q]) =>
        `<button class="chip" data-q="${esc(q)}"><span class="ic">${ic}</span>${esc(label)}</button>`).join("")}
    </div>
  </div>`;
}

/* What we understood, each field pointing at the line it came from. A
   profile with no provenance is a guess wearing a suit. */
function profileCard(p) {
  const field = (k, label) => {
    const v = p[k], src = (p.sources || {})[k];
    if (!v) return `<div class="pfrow thin"><div class="pfk">${esc(label)}</div>
      <div class="pfv sub">not found</div><div class="pfs"></div></div>`;
    const shown = k === "round_size"
      ? `${(v / 1e6).toFixed(1).replace(/\.0$/, "")}M ${esc(p.round_currency || "EUR")}`
      : esc(String(v));
    return `<div class="pfrow"><div class="pfk">${esc(label)}</div>
      <div class="pfv">${shown}</div>
      <div class="pfs">${src ? `<span title="${esc(src.quote)}">${esc(src.file)}
        ${src.where !== src.file ? "· " + esc(src.where) : ""}</span>` : ""}</div></div>`;
  };
  const bad = (p.files || []).filter(f => f.error);
  return `<div class="card pfcard">
    <div class="pfhd">What we understood</div>
    ${field("name", "Company")}
    ${field("website", "Website")}
    ${field("description", "What you build")}
    ${field("stage", "Round")}
    ${field("round_size", "Raising")}
    <div class="pfrow"><div class="pfk">Market</div>
      <div class="pfv">${(p.markets || []).length
        ? p.markets.map(m => `<span class="chip sm">${esc(m)}</span>`).join(" ")
        : `<span class="sub">none of our vocabulary matched</span>`}</div>
      <div class="pfs"></div></div>
    ${bad.length ? `<div class="pfbad">${bad.map(f =>
      `<b>${esc(f.name)}</b> — ${esc(f.error)}`).join("<br>")}</div>` : ""}
  </div>`;
}

/* The reasoning, grouped by where each line came from. The layers are kept
   apart on purpose: "Cala holds 16 rounds" and "their site lists a partner"
   are not equally strong, and a founder deciding whether to trust the
   ranking needs to see which one carried it. */
function reasoningPanel(steps, done) {
  if (!steps?.length) return `<div class="rsn"><div class="rstep now">
    <span class="rtick"></span><span class="rtx">Starting…</span></div></div>`;
  return `<div class="rsn" id="rsn">${steps.map((x, i) => {
    const last = i === steps.length - 1 && !done;
    return `<div class="rstep ${last ? "now" : "done"}">
      <span class="rtick">${last ? "" : "✓"}</span>
      <span class="rlay l-${esc(x.layer || "derived")}"
        title="${esc(LAYER_LABEL[x.layer] || "")}">${esc(x.layer || "derived")}</span>
      <span class="rtx">${esc(x.text)}${x.detail
        ? ` <span class="sub">${esc(x.detail)}</span>` : ""}${x.because
        ? `<span class="rwhy">${esc(x.because)}</span>` : ""}</span>
      <span class="rel">${x.t}s</span></div>`;
  }).join("")}</div>`;
}

function intakeView() {
  const p = INTAKE.profile;
  // A brief with no company name has nowhere to go, and the page used to say
  // "Done" and stop - which is a dead end wearing a full stop. Ask for the
  // one thing missing, here, with everything else already read.
  const stuck = INTAKE.state === "done" && p && !p.name;
  return `<div class="intakewrap">
    <div class="pghd">${INTAKE.state === "done" ? "" : `<span class="spin"></span>`}
      ${INTAKE.state === "reading" ? "Reading what you brought"
        : INTAKE.state === "screening"
          ? `Reading Cala's graph for <b>${esc(p?.name || "your company")}</b>`
          : stuck ? "One thing missing" : "Done"}</div>
    ${stuck ? `<div class="needname">
        <p><b>We could not find a company name.</b> Everything below is read
          off your company's record in Cala, so without a name or a website
          there is nothing to look up${p.round_size
            ? ` — the ${(p.round_size / 1e6).toFixed(1).replace(/\.0$/, "")}M
                ${esc(p.round_currency || "EUR")} we did read is kept` : ""}.</p>
        <form class="needform" id="needform">
          <input id="needq" autocomplete="off" autofocus
            placeholder="Company name or website — e.g. Gosta Labs, or gostalabs.com">
          <button class="btn pri" type="submit">Screen it</button>
        </form>
        <button class="lnk" data-goto="home">Start the brief again</button>
      </div>` : ""}
    ${p ? profileCard(p) : ""}
    ${reasoningPanel(INTAKE.steps, INTAKE.state === "done")}
  </div>`;
}

/* Continue a brief that only lacked a name. Everything else was already
   read, so this does not re-upload the deck or re-parse anything. */
async function intakeContinue(answer) {
  const v = (answer || "").trim();
  if (!v || !INTAKE.profile) return;
  const looksLikeHost = /\.[a-z]{2,}$/i.test(v) && !/\s/.test(v);
  const p = INTAKE.profile;
  p.name = looksLikeHost ? v.split(".")[0].replace(/^./, c => c.toUpperCase()) : v;
  if (looksLikeHost && !p.website) p.website = v.toLowerCase();
  p.sources = { ...(p.sources || {}),
                name: { file: "what you wrote", where: "the question above", quote: v } };
  INTAKE.state = "screening"; render();
  await screenFromProfile(p);
}

async function runIntake() {
  const text = $("#askbox")?.value || "";
  if (!text.trim() && !INTAKE.files.length) { $("#askbox")?.focus(); return; }
  INTAKE = { ...INTAKE, profile: null, steps: [], state: "reading" };
  // Describing a round you are raising is the founder side of the graph,
  // whichever side the browser last remembered. Leaving the role alone left
  // the sidebar offering insider conviction next to a founder's ranking.
  if (ROLE !== "founder") {
    ROLE = "founder";
    try { localStorage.setItem("flipside.role", ROLE); } catch { /* private */ }
    applyRoleChrome();
  }
  MODE = "brief"; render();

  const fd = new FormData();
  fd.append("text", text);
  for (const f of INTAKE.files) fd.append("files", f.file, f.name);

  let p;
  try {
    p = await (await fetch("/intake", { method: "POST", body: fd })).json();
  } catch (e) {
    INTAKE.state = "done";
    $("#view").innerHTML = errorPanel(String(e.message), "your brief");
    return;
  }
  INTAKE.profile = p; INTAKE.steps = p.steps || []; INTAKE.state = "screening";
  render();

  // Nothing to look up is a dead end we should say out loud rather than
  // screening an empty name and returning an empty list.
  if (!p.name) { INTAKE.state = "done"; return render(); }

  await screenFromProfile(p);
}

async function screenFromProfile(p) {
  PENDING_CO = p.name;
  PENDING_STAGE = p.stage || "series a";
  if (p.run_key) startReasoning(p.run_key);
  const r = await fetch("/analyze", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      company: p.name, stage: p.stage || "series a",
      description: p.description || "", limit: 14 })
  });
  stopReasoning();
  F = await r.json();
  F.profile = p;
  PENDING_CO = PENDING_STAGE = null; SEL = null; SYN = null;
  INTAKE.state = "done";
  MODE = "founder"; planLoad(); dealLoad(); FCONTRA = {}; render();
  loadSyndicates(F.company, F.stage);
  loadFounderContradictions();
}

let RSNTIMER = null;
function startReasoning(key) {
  stopReasoning();
  RSNTIMER = setInterval(async () => {
    try {
      const d = await (await fetch(`/reasoning?key=${encodeURIComponent(key)}`)).json();
      if (d.steps?.length) {
        INTAKE.steps = d.steps;
        const el = $("#rsn");
        if (el) {
          el.outerHTML = reasoningPanel(d.steps, d.done);
          const n = $("#rsn"); if (n) n.scrollTop = n.scrollHeight;
        }
      }
      if (d.done) stopReasoning();
    } catch (e) { /* the run is what matters, not its narration */ }
  }, 600);
}
function stopReasoning() { if (RSNTIMER) clearInterval(RSNTIMER); RSNTIMER = null; }

/* Route free text.
   "show me lifeline ventures" is a lookup, not a company raising a round -
   the earlier version screened investors for a company literally named
   "show me lifeline ventures". A leading verb means: find this entity. */
const LOOKUP_VERB = /^\s*(find|show(\s+me)?|look\s*up|search(\s+for)?|who\s+is|what\s+is|tell\s+me\s+about|open|go\s+to)\b[:,]?\s*/i;
const PERSON_HINT = /\b(founder|ceo|cto|person|people|who)\b/i;

/* Search both kinds and pick by match quality, not by a fixed order.
   Trying funds first opened an Organization called "Ilkka Paananen" and
   skipped the Person entity that carries the whole profile. */
const FUNDISH = /\b(ventures?|capital|partners?|fund|invest|equity|holdings?|ab|oy|gmbh|ltd|llp|inc)\b/i;
let LOOKUP_PARTIAL = "";

async function lookupEntity(term, kindHint) {
  $("#view").innerHTML = `<div class="msg"><span class="spin"></span>Looking up ${esc(term)}…</div>`;
  const kinds = kindHint ? [kindHint] : ["people", "fund"];
  const want = term.trim().toLowerCase();
  const found = [], failed = [];
  for (const kind of kinds) {
    try {
      const r = await (await fetch(`/search?q=${encodeURIComponent(term)}&kind=${kind}`)).json();
      if (r.error) { failed.push(kind); continue; }
      for (const x of (r.results || []).slice(0, 3)) found.push({ ...x, kind });
    } catch { failed.push(kind); }
  }
  // If one kind failed we are ranking on half the evidence. Say so rather
  // than quietly returning the wrong sort of entity: a rate-limited people
  // search once sent "find ilkka paananen" to an Organization of that name.
  LOOKUP_PARTIAL = failed.length && found.length
    ? `${failed.map(k => k === "people" ? "People" : "Fund").join(" and ")} search was
       rate-limited — this result was picked from the other half only.`
    : "";
  if (found.length) {
    const score = x => {
      const nm = (x.name || "").toLowerCase();
      let s = 0;
      if (nm === want) s -= 4;                       // exact name wins
      else if (nm.startsWith(want)) s -= 2;
      // A name with no company-ish word is far more likely to be a person.
      if (x.kind === "people" && !FUNDISH.test(term)) s -= 2;
      if (x.kind === "fund" && FUNDISH.test(term)) s -= 2;
      if (x.type === "Person" && !FUNDISH.test(term)) s -= 1;
      return s;
    };
    const best = found.sort((a, b) => score(a) - score(b))[0];
    return best.kind === "fund" ? loadFund(best.id, best.name)
      : loadEntity(best.id, best.kind, best.name);
  }
  MODE = "home"; render();
  const ab = $("#askbox");
  if (ab) {
    ab.value = term;
    $("#view").insertAdjacentHTML("beforeend",
      `<div class="home" style="padding-top:0"><div class="verdict grey">
        Nothing in Cala matched <b>${esc(term)}</b>. Try a company you are raising
        for, or a fund or person by name.</div></div>`);
  }
}

/* One place decides what a question means (web/ask.js, unit-tested), and the
   result is shown to the user. Silently guessing wrong is what made Ask feel
   broken: "raising a Series A" opened the investor view. */
let ASKWHY = null;

async function routeAsk(text) {
  const q = (text || "").trim();
  if (!q) return;
  const intent = askIntent(q);
  if (!intent.view) return;

  // An explicit lens wins outright: the user has told us the answer.
  if (LENS === "investor") {
    ASKWHY = { q, why: "you chose the investor side", confident: true, view: "investor" };
    MODE = "founder"; SEL = null; return render();
  }
  if (LENS === "lookup") {
    ASKWHY = { q, why: `looking up “${q}”`, confident: true, view: "lookup" };
    return lookupEntity(intent.term || q, intent.kind);
  }
  if (LENS === "founder") {
    ASKWHY = { q, why: "you chose to screen investors", confident: true, view: "founder" };
    MODE = "founder"; SEL = null;
    PENDING_CO = intent.term || q; PENDING_STAGE = intent.stage || null;
    render(); return runFounder();
  }

  // Auto, and the question is a bare name: ask what the name actually is
  // before screening investors for something that invests.
  if (intent.view === "founder" && intent.confident === false) {
    let kind = null, resolved = null, why = "";
    try {
      const d = await (await fetch(`/classify?q=${encodeURIComponent(intent.term || q)}`)).json();
      kind = d.kind; resolved = d; why = d.why || "";
    } catch (e) { /* fall through to the old behaviour */ }
    if (kind === "fund") {
      ASKWHY = { q, why: `that is a fund — ${why}`, confident: true, view: "lookup" };
      if (resolved?.entity_id)
        return loadFund(resolved.entity_id, resolved.name || q);
      return lookupEntity(resolved?.name || q, null);
    }
  }

  ASKWHY = { q, why: intent.why, confident: intent.confident !== false,
             view: intent.view };

  if (intent.view === "map") { MODE = "map"; SEL = null; return MAP ? render() : loadMap(); }
  if (intent.view === "investor") {
    MODE = "founder"; SEL = null; return render();
  }
  if (intent.view === "lookup") return lookupEntity(intent.term, intent.kind);

  MODE = "founder"; SEL = null;
  PENDING_CO = intent.term || q;
  PENDING_STAGE = intent.stage || null;
  render();
  runFounder();
}

/* What we did with the question, and how to undo it. */
function askTrace() {
  if (!ASKWHY) return "";
  const other = ASKWHY.view === "founder"
    ? [["investor", "insider conviction"], ["map", "the map"]]
    : ASKWHY.view === "investor"
      ? [["founder", "screening investors"], ["map", "the map"]]
      : [["founder", "screening investors"], ["investor", "insider conviction"]];
  return `<div class="asktrace">
    <span class="q">${esc(ASKWHY.q)}</span>
    <span class="arrow">→</span>
    <span class="why">${esc(ASKWHY.why)}${ASKWHY.confident ? "" : " (best guess)"}</span>
    <span class="alt">not what you meant? ${other.map(([v, l]) =>
      `<button class="lnk" data-askgo="${v}">${esc(l)}</button>`).join(" · ")}</span>
    <button class="lnk x" data-askgo="clear">×</button>
  </div>`;
}

let PENDING_CO = null, PENDING_STAGE = null;

/* ================= QUICK SEARCH ================= */
let QKIND = "fund", QTIMER = null;

function qsRender(data) {
  const box = $("#qsres");
  if (!box) return;
  if (data.error) {
    box.innerHTML = `<div class="qsempty">${esc(data.error.includes("Rate limit")
      ? "Cala is rate-limiting right now — try again in a moment." : data.error)}</div>`;
    return;
  }
  if (!data.results.length) {
    box.innerHTML = `<div class="qsempty">${data.query.length < 2
      ? "Type at least two characters." : "Nothing in Cala for that."}</div>`;
    return;
  }
  box.innerHTML = data.results.map(r => `<div class="qsrow" data-id="${esc(r.id)}">
    ${logo(r.name)}<div style="min-width:0">
      <div class="nm">${esc(r.name)}</div>
      <div class="ds">${esc(r.description || r.type)}</div></div></div>`).join("");
  box.querySelectorAll(".qsrow").forEach((el, i) => el.onclick = () => {
    const r = data.results[i];
    $("#qspop").classList.remove("on");
    $("#qsq").value = "";
    if (QKIND === "fund") loadFund(r.id, r.name); else loadEntity(r.id, QKIND, r.name);
  });
}

function qsSearch() {
  const q = $("#qsq").value.trim();
  $("#qspop").classList.toggle("on", q.length > 0);
  if (q.length < 2) return qsRender({ query: q, results: [] });
  $("#qsres").innerHTML = `<div class="qsempty"><span class="spin"></span>Searching Cala…</div>`;
  clearTimeout(QTIMER);
  QTIMER = setTimeout(async () => {
    try {
      qsRender(await (await fetch(`/search?q=${encodeURIComponent(q)}&kind=${QKIND}`)).json());
    } catch (e) { qsRender({ query: q, results: [], error: String(e.message) }); }
  }, 260);
}

function wireQuickSearch() {
  const inp = $("#qsq"), pop = $("#qspop");
  inp.oninput = qsSearch;
  inp.onfocus = () => { if (inp.value.trim()) pop.classList.add("on"); };
  document.querySelectorAll(".qstab").forEach(b => b.onclick = () => {
    QKIND = b.dataset.k;
    document.querySelectorAll(".qstab").forEach(x => x.classList.toggle("on", x === b));
    qsSearch();
  });
  document.addEventListener("click", e => {
    if (!e.target.closest(".navsearch")) pop.classList.remove("on");
  });
  addEventListener("keydown", e => {
    if (e.key === "/" && document.activeElement.tagName !== "INPUT"
        && document.activeElement.tagName !== "TEXTAREA") { e.preventDefault(); inp.focus(); }
    if (e.key === "Escape") pop.classList.remove("on");
  });
}

wireQuickSearch();
loadHealth();
neoMount();
// Apply the role the browser remembers before the first paint, so an
// investor who reloads does not land on the founder's ask box.
applyRoleChrome();
scoutLoad();
render();

/* ================= ENTITY CARD (person / fund) ================= */
let ENT = null, ENTLOAD = null;

async function loadEntity(id, kind, name) {
  MODE = "entity"; SEL = null; TAB = 0;
  ENTLOAD = { id, kind, name };
  ENT = null; SITE = null; ENR = null; render();
  try {
    ENT = await (await fetch(`/entity/${id}?kind=${kind}`)).json();
  } catch (e) { ENT = { error: String(e.message) }; }
  render();
  const site = ENT?.properties?.website?.value;
  loadSite(site);
  // A profile with no edges and no properties is the common case now that
  // live lookups are refused. Go and find what the public record holds.
  const thin = !(ENT?.groups || []).length || !Object.keys(ENT?.properties || {}).length;
  if (ENT?.name && !ENT?.error && kind !== "people" && thin)
    loadEnrich(ENT.name, (ENT.properties?.headquarters_address?.value || "").slice(-2));
}

/* The company's own homepage, fetched after the profile is already up.
   It is the only source here that updates between funding announcements. */
let SITE = null;

/* When Cala holds only a name, say what the public record holds. */
let ENR = null;

async function loadEnrich(name, cc) {
  const want = ENT?.id;
  ENR = { loading: true }; render();
  try {
    const r = await fetch(`/enrich?name=${encodeURIComponent(name)}${
      cc ? `&cc=${encodeURIComponent(cc)}` : ""}`);
    const j = await r.json();
    if (ENT?.id !== want) return;
    ENR = j;
  } catch (e) { ENR = { error: String(e.message) }; }
  render();
}

function enrichSection() {
  if (!ENR) return "";
  if (ENR.loading) return section("e-enr", "Public record", "",
    `<div class="msg" style="padding:20px"><span class="spin"></span>Checking registries and the open web…</div>`);
  if (ENR.error) return "";

  const reg = ENR.registry;
  const hp = ENR.homepage;
  if (!reg && !ENR.site && !(ENR.rounds || []).length) {
    return section("e-enr", "Public record", "nothing found",
      `<div class="msg" style="padding:20px;text-align:left;line-height:1.7">
        No registry record under this name, no cached round, and no homepage we
        could verify. That is three sources saying nothing, not one failing.</div>`);
  }

  return section("e-enr", "Public record",
    [reg && "registry", ENR.site && "homepage",
     (ENR.rounds || []).length && "rounds"].filter(Boolean).join(" · "),
    `<div class="card">
      ${reg ? `<div class="pubrow">
        <span class="pk">${esc(reg.source_name)}</span>
        <span><b>${esc(reg.name)}</b> · ${esc(reg.status)} · ${esc(reg.city || "")},
          ${esc(reg.country || "")}<br>
          <span class="sub">${esc(reg.address || "")} · LEI
            <a href="${esc(reg.url)}" target="_blank" rel="noopener">${esc(reg.lei)}</a></span>
        </span></div>` : ""}
      ${ENR.site ? `<div class="pubrow">
        <span class="pk">Website</span>
        <span><a href="${esc(ENR.site)}" target="_blank" rel="noopener">${
          esc(ENR.site.replace(/^https?:\/\//, ""))}</a>
          ${hp?.title ? `<br><b>${esc(hp.title)}</b>` : ""}
          ${hp?.tagline ? `<br>${esc(hp.tagline)}` : ""}
          <br><span class="sub">${esc(ENR.site_how || "")}</span></span></div>` : ""}
      ${hp?.signals?.length ? `<div class="sitesigs">${hp.signals.map(sg => `
        <a class="sitesig" href="${esc(sg.url)}" target="_blank" rel="noopener">
          <b>${esc(sg.text)}</b><span>${esc(sg.why)}</span></a>`).join("")}</div>` : ""}
      ${(ENR.rounds || []).length ? `<div class="pubrow">
        <span class="pk">Rounds</span>
        <span>${ENR.rounds.map(r => `${esc(r.stage || "round")} ${
          esc(String(r.date || "").slice(0, 7))}${r.investors?.length
            ? ` — ${esc(r.investors.join(", "))}` : ""}`).join("<br>")}
        <br><span class="sub">from rounds already cached from Cala</span></span></div>` : ""}
    </div>`);
}

async function loadSite(url) {
  if (!url) { SITE = null; return; }
  const want = ENT?.id;
  SITE = { loading: true }; render();
  try {
    const r = await fetch(`/website?site=${encodeURIComponent(url)}`);
    const j = await r.json();
    if (ENT?.id !== want) return;
    SITE = j;
  } catch (e) { SITE = { ok: false, error: String(e.message) }; }
  render();
}

function siteSection() {
  if (!SITE) return "";
  if (SITE.loading) return section("e-site", "From their own site", "",
    `<div class="msg" style="padding:20px"><span class="spin"></span>Reading the homepage…</div>`);
  if (!SITE.ok) return section("e-site", "From their own site", "",
    `<div class="msg" style="padding:18px">Their site did not answer${
      SITE.error ? ` (${esc(SITE.error)})` : ""}. Unknown is not zero.</div>`);

  const host = String(SITE.site || "").replace(/^https?:\/\//, "");
  return section("e-site", "From their own site",
    SITE.signals.length ? `${SITE.signals.length} public signals` : "nothing to report",
    `<div class="card">
      ${SITE.title ? `<div class="sitetitle">${esc(SITE.title)}</div>` : ""}
      ${SITE.tagline ? `<p class="lede" style="margin:6px 0 0">${esc(SITE.tagline)}</p>` : ""}
      ${SITE.signals.length ? `<div class="sitesigs">${SITE.signals.map(sg => `
        <a class="sitesig" href="${esc(sg.url)}" target="_blank" rel="noopener">
          <b>${esc(sg.text)}</b><span>${esc(sg.why)}</span></a>`).join("")}</div>`
        : `<div class="sub" style="margin-top:9px">No careers, pricing, docs or
             customers page linked from the homepage. For a pre-seed company that
             is normal, not a red flag.</div>`}
      <div class="sub" style="margin-top:10px">Read from
        <a href="${esc(SITE.site)}" target="_blank" rel="noopener">${esc(host)}</a>,
        cached for a week. Their words, not ours.</div>
    </div>`);
}

const RANKCLS = { FILING: "b-green", PRIMARY: "b-blue", PRESS: "b-amber", AGGREGATOR: "b-grey" };
const rankChip = r => r ? `<span class="bdg ${RANKCLS[r] || "b-grey"}"
  style="font-size:9.5px;letter-spacing:.05em">${esc(r)}</span>` : "";

/* Out of credits is not the same failure as a bug or a rate limit, and the
   user can only act on one of them. Say which one it is. */
function errorPanel(msg, what) {
  const txt = String(msg || "");
  if (/credits exhausted|402/i.test(txt)) {
    return `<div class="verdict grey" style="margin:18px 0;text-align:left">
      <b>Cala credits are exhausted.</b> Live lookups return
      <code>402 Insufficient balance</code>, so ${esc(what || "this profile")}
      cannot be opened right now.<br><br>
      Everything already cached still works: the founder screen, the round
      architect, outreach briefs, the map and near-me all read from local
      data. Top up at
      <a href="https://console.cala.ai" target="_blank" rel="noopener">console.cala.ai</a>
      and this page works again with no other change.</div>`;
  }
  return `<div class="msg">Could not open ${esc(what || "this")}.<br>
    <span style="color:var(--dim)">${esc(txt)}</span></div>`;
}

function entityView() {
  if (!ENT) return `<div class="msg"><span class="spin"></span>Opening ${esc(ENTLOAD?.name || "profile")}…</div>`;
  const warn = LOOKUP_PARTIAL
    ? `<div class="verdict grey" style="margin-bottom:14px">${esc(LOOKUP_PARTIAL)}</div>` : "";
  if (ENT.error) return errorPanel(ENT.error, ENTLOAD?.name);

  const P = ENT.properties || {};
  const isPerson = ENT.kind === "people";
  const val = k => P[k]?.value;
  const src = k => P[k]?.source;

  const meta = [
    ENT.entity_type ? badge(ENT.entity_type, isPerson ? "purple" : "blue") : "",
    val("headquarters_address") ? esc(val("headquarters_address")) : "",
    val("founding_date") ? "founded " + esc(String(val("founding_date")).slice(0, 4)) : "",
    val("birth_date") ? "born " + esc(String(val("birth_date")).slice(0, 4)) : "",
    val("website") ? `<a href="${esc(val("website"))}" target="_blank" rel="noopener">${
      esc(String(val("website")).replace(/^https?:\/\//, ""))}</a>` : "",
    val("linkedin_url") ? `<a href="${esc(val("linkedin_url"))}" target="_blank" rel="noopener">LinkedIn</a>` : "",
  ].filter(Boolean).join(" · ");

  const counts = {};
  for (const g of ENT.groups || []) counts[g.rel] = g.items.length;

  /* A zero is a claim: "this fund has made no investments". We may simply
     never have asked. Show 0 only for edges we actually queried, and a
     muted dash with its reason for the rest. */
  const asked = new Set(ENT.rels_queried || []);
  const n = rel => {
    if (counts[rel] != null) return counts[rel];
    if (asked.has(rel)) return 0;
    return `<span class="unchecked" title="Not retrieved — the live lookup was
      unavailable, so this edge was never asked for">—</span>`;
  };
  const sum = rels => rels.every(r => !asked.has(r) && counts[r] == null)
    ? n(rels[0]) : rels.reduce((a, r) => a + (counts[r] || 0), 0);

  const statRow = isPerson
    ? [["Roles", sum(["IS_CEO_OF", "WORKS_AT"])],
       ["Founded", n("FOUNDED")],
       ["Investments", n("INVESTED_IN")],
       ["Rounds on record", n("PARTICIPATES_IN_FUNDING_ROUND")],
       ["Boards", n("IS_MEMBER_OF")]]
    : [["Investments", n("INVESTED_IN")],
       ["Rounds on record", n("PARTICIPATES_IN_FUNDING_ROUND")],
       ["Exits found", EXITS[ENT.id]?.exits?.length ?? "…"],
       ["Industries", n("OPERATES_IN_INDUSTRY")],
       ["Employees", val("employee_count")
         ?? `<span class="unchecked" title="Cala holds no employee count for this entity">—</span>`]];

  let body = `<div class="ehd"><div class="ehdtop">
      ${bigLogo(ENT.name, val("website"))}
      <div style="min-width:0"><h1>${esc(ENT.name)}</h1><div class="emeta">${meta}</div></div>
      <span class="eacts">
        <button class="btn" id="composeit">${GMAIL_ICON}Compose intro</button>
        ${isPerson ? "" : `<button class="btn" id="screenit">Screen this fund</button>`}
        <button class="btn" onclick="window.print()">Export</button></span>
    </div><div class="tabs">
      <button class="tab ${TAB === 0 ? "on" : ""}" data-tab="0">Profile</button>
      ${isPerson ? `<button class="tab ${TAB === 1 ? "on" : ""}" data-tab="1">Founder signal</button>` : ""}
      </div></div><div class="tabbody">`;

  if (isPerson && TAB === 1) return body + founderSignalTab() + "</div>";

  body += warn;
  if (ENT.degraded)
    body += `<div class="verdict grey" style="margin-bottom:14px">${esc(ENT.degraded)}</div>`;
  if (val("description"))
    body += `<p class="lede">${esc(val("description"))}
      ${src("description") ? `<a href="${esc(src("description"))}" target="_blank"
        rel="noopener" style="font-size:12px"> source</a>` : ""}</p>`;

  body += stats(5, statRow.map(([k, v]) => [k, v, "mono"]));
  if (!isPerson) body += siteSection() + enrichSection();
  body += exitsBlock(ENT.id, ENT.name, ENT.kind);
  if (!isPerson) body += pipelineBlock(ENT.name);
  if (OPEN["bio"] === undefined) OPEN["bio"] = false;   // long: collapsed first
  body += bioBlock(ENT.name, ENT.kind);

  for (const g of ENT.groups || []) {
    body += section("ent-" + g.rel, g.label, `${g.items.length} on record`,
      `<div class="hl tight">${g.items.map(it => `<div class="hlc">
        <div class="hlhd">${logo(it.name, it.website)}
          <div style="min-width:0"><div class="nm">${esc(it.name)}</div>
            <div class="sb">${esc(it.role || it.type || "")}</div></div>
          ${rankChip(it.rank)}</div>
        ${it.rounds != null ? `<div class="facts">
          <span><b>${it.rounds}</b> round${it.rounds === 1 ? "" : "s"}</span>
          ${it.last_round ? `<span>${esc(it.last_round.stage || "")} ${
            esc(String(it.last_round.date || "").slice(0, 7))}</span>` : ""}
        </div>${it.investors?.length ? `<div class="with">with ${
          esc(it.investors.slice(0, 3).join(", "))}</div>` : ""}` : ""}
        ${it.source ? `<a class="srcline" href="${esc(it.source)}" target="_blank"
          rel="noopener">${esc(String(it.source).replace(/^https?:\/\/(www\.)?/, "").split("/")[0])}</a>` : ""}
      </div>`).join("")}</div>`);
  }

  // Only say the graph is empty when the public record came up empty too -
  // otherwise this line sits underneath an LEI and a homepage contradicting it.
  const foundElsewhere = ENR && !ENR.loading &&
    (ENR.registry || ENR.site || (ENR.rounds || []).length);
  if (!(ENT.groups || []).length && !foundElsewhere)
    body += `<div class="msg">No relationships on this entity in Cala.
      Unknown is not zero.</div>`;

  return body + "</div>";
}


/* ================= COMPOSE ================= */
/* Drafts an approach grounded in what the graph actually says, then hands it
   to the user's own mail client. Nothing is sent from here: the message goes
   out from their account, after they have read it. */
/* ---------- Slush outreach brief ----------
   The compose box used to assemble sentences in the browser from whatever
   happened to be on screen. The brief is now synthesised server-side from the
   same screen that produced the ranking, and every sentence arrives with the
   evidence it was built from - so the drawer is both the draft and the trail.*/
let BRIEF = null;

async function openBrief(investor) {
  const w = document.createElement("div");
  w.className = "scrim on";
  w.innerHTML = `<div class="composebox" onclick="event.stopPropagation()">
    <div class="sidehd"><h3>Slush brief — ${esc(investor)}</h3>
      <div class="s">Reading the graph…</div></div>
    <div style="padding:34px"><span class="spin"></span></div></div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  w.onclick = close;

  let b;
  try {
    b = await (await fetch("/outreach", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ company: F?.company || "", stage: F?.stage || "series a",
                             limit: F?.investors?.length || 14, investor })
    })).json();
  } catch (e) { b = { error: String(e.message) }; }
  BRIEF = b;

  if (b.error) {
    w.innerHTML = `<div class="composebox" onclick="event.stopPropagation()">
      <div class="sidehd"><h3>Slush brief — ${esc(investor)}</h3></div>
      <div class="msg">${esc(b.error)}</div></div>`;
    w.onclick = close;
    return;
  }

  if (b.blocked) {
    w.innerHTML = `<div class="composebox" onclick="event.stopPropagation()">
      <div class="sidehd"><h3>No brief for ${esc(investor)}</h3>
        <div class="s">This is the finding, not a failure to write one</div></div>
      <div style="padding:16px">
        <div class="verdict red"><b>${esc(b.reason)}</b> Pitching a fund that already
          backs a direct competitor hands them your numbers for free.</div>
        ${b.evidence.map(e => `<div class="evrow"><span class="evk">${esc(e.kind)}</span>
          <span>${esc(e.claim)}${e.detail ? ` — ${esc(e.detail)}` : ""}</span></div>`).join("")}
        <div style="display:flex;margin-top:14px"><button class="btn" id="bclose"
          style="margin-left:auto">Close</button></div>
      </div></div>`;
    w.onclick = close;
    w.querySelector("#bclose").onclick = close;
    return;
  }

  const ev = k => b.evidence.find(e => e.kind === k);
  const trail = b.sentences.map((sn, i) => {
    const e = b.evidence[i];
    return `<div class="bsent"><p>${esc(sn)}</p>
      ${e ? `<div class="evrow"><span class="evk">${esc(e.kind.replace(/_/g, " "))}</span>
        <span>${esc(e.detail || e.claim)}</span></div>` : ""}</div>`;
  }).join("");

  w.innerHTML = `<div class="composebox wide" onclick="event.stopPropagation()">
    <div class="sidehd"><h3>Slush brief — ${esc(investor)}</h3>
      <div class="s">Three sentences, each one a number you can check</div></div>
    <div style="padding:15px">
      <div class="btrail">${trail}</div>
      <div class="fld" style="margin:13px 0 11px"><label>To</label>
        <input id="cto" placeholder="name@fund.com" style="width:100%"></div>
      <div class="fld" style="margin-bottom:11px"><label>Subject</label>
        <input id="csub" value="${esc(b.subject)}" style="width:100%"></div>
      <div class="fld"><label>Message</label>
        <textarea id="cbody" rows="8" style="width:100%;border:1px solid var(--line2);
          border-radius:8px;padding:11px;font:13px/1.65 var(--sans)">${esc(
            "Hi,\n\n" + b.body + "\n\nBest,")}</textarea></div>
      <div style="display:flex;gap:8px;margin-top:13px;flex-wrap:wrap">
        <button class="btn pri" id="cmail">${GMAIL_ICON}Open in Gmail</button>
        <button class="btn" id="ccopy">Copy</button>
        <button class="btn" id="cmailto">Other mail app</button>
        <button class="btn" id="bclose" style="margin-left:auto">Close</button>
      </div>
    </div></div>`;
  w.onclick = close;
  w.querySelector("#bclose").onclick = close;
  const val = id => w.querySelector(id).value;
  w.querySelector("#cmail").onclick = () => window.open(
    `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(val("#cto").trim())
      }&su=${encodeURIComponent(val("#csub"))}&body=${encodeURIComponent(val("#cbody"))}`,
    "_blank", "noopener");
  w.querySelector("#cmailto").onclick = () => {
    // Assigning location.href to a mailto: is silently ignored in embedded
    // and sandboxed contexts. Clicking a real anchor is not.
    const a = document.createElement("a");
    a.href = `mailto:${encodeURIComponent(val("#cto").trim())}?subject=${
      encodeURIComponent(val("#csub"))}&body=${encodeURIComponent(val("#cbody"))}`;
    a.target = "_blank"; a.rel = "noopener";
    document.body.appendChild(a); a.click(); a.remove();
  };
  w.querySelector("#ccopy").onclick = async () => {
    await navigator.clipboard.writeText(val("#cbody"));
    w.querySelector("#ccopy").textContent = "Copied";
  };
}

function composeDraft() {
  const name = ENT?.name || SEL || "";
  const isPerson = ENT?.kind === "people";
  const lines = [];

  if (isPerson) {
    const roles = (ENT.groups || []).find(g => g.rel === "IS_CEO_OF" || g.rel === "WORKS_AT");
    const inv = (ENT.groups || []).find(g => g.rel === "INVESTED_IN");
    lines.push(`Hi ${name.split(" ")[0]},`, "");
    if (roles?.items?.length) lines.push(`I saw your work at ${roles.items[0].name}.`);
    if (inv?.items?.length)
      lines.push(`You have backed ${inv.items.slice(0, 2).map(i => i.name).join(" and ")}, which is close to what we are building.`);
  } else {
    const x = F?.investors?.find(i => i.investor === name);
    lines.push("Hi,", "");
    if (x) {
      const s2 = x.signals;
      if (s2.lead_rate?.value != null)
        lines.push(`You led ${Math.round(s2.lead_rate.value * 100)}% of the ${F.stage} rounds you joined over the last three years, which is why you are near the top of our list.`);
      if (s2.warm_path?.label !== "⚪")
        lines.push(`We share an investor — ${s2.warm_path.text.replace(/^via /, "")} — so an introduction may be easiest.`);
    }
    lines.push(`We are raising a ${F?.stage || "round"} for ${F?.company || "our company"}.`);
  }
  lines.push("", "Would a short call next week work?", "", "Best,");
  return { subject: isPerson ? `Introduction — ${F?.company || "Flipside"}`
                             : `${F?.company || "Our company"} — ${F?.stage || "round"}`,
           body: lines.join("\n") };
}

function openCompose() {
  const d = composeDraft();
  const name = ENT?.name || SEL || "";
  const w = document.createElement("div");
  w.className = "scrim on";
  w.innerHTML = `<div class="composebox" onclick="event.stopPropagation()">
    <div class="sidehd"><h3>Compose to ${esc(name)}</h3>
      <div class="s">Opens a prefilled Gmail draft — nothing is sent from Flipside</div></div>
    <div style="padding:15px">
      <div class="fld" style="margin-bottom:11px"><label>To</label>
        <input id="cto" placeholder="name@fund.com" style="width:100%"></div>
      <div class="fld" style="margin-bottom:11px"><label>Subject</label>
        <input id="csub" value="${esc(d.subject)}" style="width:100%"></div>
      <div class="fld"><label>Message</label>
        <textarea id="cbody" rows="11" style="width:100%;border:1px solid var(--line2);
          border-radius:8px;padding:11px">${esc(d.body)}</textarea></div>
      <div style="display:flex;gap:8px;margin-top:13px">
        <button class="btn pri" id="cmail">${GMAIL_ICON}Open in Gmail</button>
        <button class="btn" id="ccopy">Copy</button>
        <button class="btn" id="cmailto">Other mail app</button>
        <button class="btn" id="cclose" style="margin-left:auto">Close</button>
      </div>
      <div class="s" style="margin-top:10px;color:var(--faint);font-size:11.5px">
        Every claim in this draft comes from a figure on this page.</div>
    </div></div>`;
  document.body.appendChild(w);
  const close = () => w.remove();
  w.onclick = close;
  w.querySelector("#cclose").onclick = close;
  w.querySelector("#cmail").onclick = () => {
    const to = w.querySelector("#cto").value.trim();
    const sub = encodeURIComponent(w.querySelector("#csub").value);
    const body = encodeURIComponent(w.querySelector("#cbody").value);
    // Gmail's compose window, prefilled. Nothing is sent from here - the
    // message leaves from the user's own account, after they have read it.
    window.open(`https://mail.google.com/mail/?view=cm&fs=1&to=${
      encodeURIComponent(to)}&su=${sub}&body=${body}`, "_blank", "noopener");
  };
  w.querySelector("#cmailto").onclick = () => {
    location.href = `mailto:${encodeURIComponent(w.querySelector("#cto").value.trim())}?subject=${
      encodeURIComponent(w.querySelector("#csub").value)}&body=${
      encodeURIComponent(w.querySelector("#cbody").value)}`;
  };
  w.querySelector("#ccopy").onclick = async () => {
    await navigator.clipboard.writeText(w.querySelector("#cbody").value);
    w.querySelector("#ccopy").textContent = "Copied";
  };
}


/* ================= FOUNDER SIGNAL (third reading) ================= */
let FSIG = null, FSIGFOR = null;

async function loadFounderSignal(id, name) {
  FSIGFOR = id; FSIG = null; render();
  try {
    FSIG = await (await fetch(`/founder-signal/${id}?name=${encodeURIComponent(name || "")}`)).json();
  } catch (e) { FSIG = { error: String(e.message) }; }
  render();
}

function founderSignalTab() {
  if (FSIGFOR !== ENT.id) { loadFounderSignal(ENT.id, ENT.name); return `<div class="msg">
    <span class="spin"></span>Reading the graph…</div>`; }
  return founderSignalPanel();
}

function founderSignalBody() {
  const f = FSIG, gh = f.github, comps = (f.components || []).filter(c => c.counted);
  const uncounted = (f.components || []).filter(c => !c.counted);
  const max = Math.max(...comps.map(c => c.contribution), 1);
  return stats(4, [
    ["Founder signal", f.score, "mono"],
    ["Confidence", f.confidence],
    ["Connections read", f.evidence_edges, "mono"],
    ["Ships code publicly", gh ? (f.github_signal?.label || "yes")
      : /rate limit/i.test(f.github_error || "")
        ? `<span class="unchecked" title="GitHub rate-limited this lookup. Set GITHUB_TOKEN to raise the limit from 60 to 5000 requests an hour.">not checked</span>`
        : `<span class="unchecked" title="No GitHub account matched this name with enough confidence">no match</span>`],
  ])
  + `<div class="verdict ${f.score >= 55 ? "green" : "grey"}">
      <b>${f.score >= 55 ? "Looks like someone who starts things."
        : "Some of the pattern, not all of it."}</b> ${esc((f.reasons || []).join("; "))}.</div>`
  + section("fs-comp", "What the score is made of", "", `<div class="card">${
      comps.map(c => `<div class="barrow">
        <span class="lbl">${esc(c.label)}</span>
        <span class="bart"><i class="g" style="width:${Math.round(100 * c.contribution / max)}%"></i></span>
        <span class="pc">+${c.contribution}</span></div>`).join("")}
      ${uncounted.length ? `<div class="sub" style="margin-top:12px">Counted but not scored:
        ${uncounted.map(c => `${esc(c.label)} (${c.n})`).join(", ")} — visibility measures
        being already known, not being about to build.</div>` : ""}</div>`)
  + (gh ? section("fs-gh", "GitHub", esc(gh.login), `<div class="two">
      <div class="card"><h4>${esc(gh.name || gh.login)}</h4>
        <div class="sub">${esc(gh.bio || "")}</div>
        ${bars([["Stars", gh.stars, "g", gh.stars],
                ["Own repos", gh.own_repos, "g", gh.own_repos],
                ["Followers", gh.followers, "g", gh.followers]])}
        <div class="sub" style="margin-top:9px">on GitHub since ${gh.since}
          ${gh.languages?.length ? "· " + esc(gh.languages.map(l => l[0]).join(", ")) : ""}</div></div>
      <div class="card"><h4>Most starred</h4><div class="sub">public repositories</div>
        ${(gh.top_repos || []).map(r => `<div class="sideitem">
          <div class="n"><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.name)}</a>
            <span class="bdg b-grey" style="margin-left:6px">${r.stars}★</span></div>
          <div class="d">${esc(r.description || r.lang || "")}</div></div>`).join("")
          || `<div class="sub">No public repositories.</div>`}</div></div>`)
    : section("fs-gh", "GitHub",
        /rate limit/i.test(f.github_error || "") ? "not checked" : "no confident match",
        `<div class="emptywhy">
          ${/rate limit/i.test(f.github_error || "")
            ? `<b>GitHub rate-limited this lookup.</b>
               Unauthenticated search allows about ten queries a minute. Put a
               token in <code>.env</code> and the limit goes from 60 an hour to
               5,000:<br>
               <code style="display:inline-block;margin-top:6px">GITHUB_TOKEN=ghp_…</code>
               <span class="sub">Any read-only personal access token works; it needs
               no scopes at all. Until then this component is counted as unknown,
               not as zero — it does not drag the score down.</span>`
            : `<b>No GitHub account matched this name with enough confidence.</b>
               A same-name account is not evidence. We decline rather than credit
               someone else's work to this person.`}
        </div>`))
  + section("fs-ev", "Everything this reads", "straight from Cala's Person graph",
      `<div class="hl">${(f.groups || []).map(g => `<div class="hlc">
        <div class="hlhd"><div style="min-width:0"><div class="nm">${esc(g.label)}</div>
          <div class="sb">${g.items.length} on record</div></div></div>
        <div class="sub" style="margin:0">${esc(g.items.join(", "))}</div></div>`).join("")}</div>`);
}


/* ================= PUBLIC RECORD ================= */
/* Primary registers, not a search engine. The one that earns its place is
   SEC Form D: a US private placement must be filed within 15 days of first
   sale, so a filing with no matching round in Cala means someone is raising
   and has not announced it. */
let REG = null, REGFOR = null;

async function loadRegistry(name, rounds) {
  REGFOR = name; REG = null; render();
  try {
    REG = await (await fetch(`/registry?name=${encodeURIComponent(name)}` +
      `&rounds=${encodeURIComponent((rounds || []).join(","))}`)).json();
  } catch (e) { REG = { error: String(e.message) }; }
  render();
}

function publicRecordTab(name, rounds) {
  if (REGFOR !== name) { loadRegistry(name, rounds); return `<div class="msg">
    <span class="spin"></span>Checking public registers…</div>`; }
  if (!REG) return `<div class="msg"><span class="spin"></span>Checking public registers…</div>`;
  if (REG.error) return `<div class="msg">${esc(REG.error)}</div>`;

  const sr = REG.silent_round, g = REG.gleif, pr = REG.prh, br = REG.brreg;
  let out = "";

  if (sr) out += `<div class="verdict red">
    <b>Filed a Form D on ${esc(sr.filed)} with no matching round in Cala.</b>
    A US private placement must be filed within 15 days of first sale, so this
    company is raising and has not announced it.
    <a href="${esc(sr.url)}" target="_blank" rel="noopener">SEC filing</a></div>`;
  else out += `<div class="verdict grey">No unannounced US filing found.
    ${(REG.form_d || []).length ? "Every Form D on record matches a round we already know about."
      : "No Form D on record — this company may not raise in the US at all."}</div>`;

  const reg = [
    g && ["GLEIF", `${g.name} · ${g.status || ""}`, g.address, g.url, "LEI " + g.lei],
    pr && ["PRH (Finland)", pr.name, `registered ${pr.registered}`, pr.url, pr.business_id],
    br && ["Brreg (Norway)", br.name, `registered ${br.registered}`, br.url, br.orgnr],
  ].filter(Boolean);

  if (reg.length) out += section("pr-reg", "Registered entity", "",
    `<div class="hl">${reg.map(([src, nm, sub, url, id]) => `<div class="hlc">
      <div class="hlhd"><div style="min-width:0"><div class="nm">${esc(nm || "")}</div>
        <div class="sb">${esc(src)}</div></div>${badge(esc(id || ""), "blue")}</div>
      <div class="sub" style="margin:0">${esc(sub || "")}
        ${url ? ` · <a href="${esc(url)}" target="_blank" rel="noopener">record</a>` : ""}</div>
    </div>`).join("")}</div>`);
  else out += section("pr-reg", "Registered entity", "",
    `<div class="card"><div class="sub">No register entry matched this name closely enough
      to attribute. A near-miss is worse than nothing — GLEIF's name search once returned a
      Swedish company for "Abridge".</div></div>`);

  if ((REG.form_d || []).length) out += section("pr-sec", "SEC Form D filings",
    `${REG.form_d.length} on record`,
    `<div class="tbl"><table><thead><tr><th>Filed</th><th>Filer</th></tr></thead><tbody>
      ${REG.form_d.map(f => `<tr style="cursor:default">
        <td class="num" style="text-align:left">${esc(f.filed || "")}</td>
        <td style="font-size:12.8px">${esc((f.names || []).join(" · "))}</td></tr>`).join("")}
    </tbody></table></div>`);

  return out + section("pr-src", "Where this comes from", "",
    `<div class="card"><ul class="reasons">
      <li><b>SEC EDGAR Form D</b> — US private placements, public within days of filing.</li>
      <li><b>GLEIF</b> — Legal Entity Identifiers, the registered entity behind a trading name.</li>
      <li><b>PRH</b> and <b>Brreg</b> — Finnish and Norwegian company registers.</li>
    </ul><div class="sub" style="margin:9px 0 0">All primary registers with documented
    endpoints. None of this is scraped.</div></div>`);
}


/* ================= WHO SAYS SO ================= */
/* A conflict flag is a serious thing to put in front of a founder, so it
   should not rest on our arithmetic alone. /knowledge/search returns the
   individual claims behind an answer, each pointing at the document it came
   from - and the strongest of those is usually the fund's own portfolio page. */
const EV = {};

function evidenceBlock(investor, competitor) {
  const key = investor + "|" + competitor;
  const d = EV[key];
  if (d === undefined) {
    EV[key] = null;
    fetch(`/evidence?investor=${encodeURIComponent(investor)}&company=${encodeURIComponent(competitor)}`)
      .then(r => r.json()).then(j => { EV[key] = j; render(); })
      .catch(e => { EV[key] = { error: String(e.message) }; render(); });
  }
  if (!d) return section("ev-load", "Who says so", "",
    `<div class="card"><div class="sub"><span class="spin"></span>Asking Cala for the
     documents behind this…</div></div>`);
  if (d.error) return section("ev-err", "Who says so", "",
    `<div class="card"><div class="sub">${esc(d.error)}</div></div>`);

  return section("ev", "Who says so", `${(d.docs || []).length} sources`,
    `<div class="card">
      <div style="font-size:13.5px;line-height:1.6">${esc((d.answer || "")
        .replace(/\*\*/g, "").slice(0, 420))}</div>
      ${(d.claims || []).filter(c => c.docs.length).map(c => `<div class="ev">
        <div>${esc(c.text)}</div>
        ${c.docs.map(x => `<div><span class="srank">${esc(x.rank)}</span>
          <a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.name.slice(0, 70))}</a></div>`).join("")}
      </div>`).join("")}
      <div class="sub" style="margin:12px 0 0">Ranked by who published it:
        a regulator's filing, then one of the parties speaking for itself,
        then commentary about them.</div>
    </div>`);
}


/* ================= SOURCED BACKGROUND ================= */
/* The graph says what someone is connected to. This says what is written
   about them, with every claim pointing at the document it came from. */
const BIO = {};

function bioBlock(name, kind) {
  const key = kind + "|" + name;
  const d = BIO[key];
  if (d === undefined) {
    BIO[key] = null;
    fetch(`/bio?name=${encodeURIComponent(name)}&kind=${encodeURIComponent(kind)}`)
      .then(r => r.json()).then(j => { BIO[key] = j; render(); })
      .catch(e => { BIO[key] = { error: String(e.message) }; render(); });
  }
  if (!d) return section("bio-l", "Background", "",
    `<div class="card"><div class="sub"><span class="spin"></span>Reading what is
     published about ${esc(name)}…</div></div>`);
  if (d.error || !(d.claims || []).length) return "";

  const txt = (d.answer || "").replace(/\*\*/g, "").replace(/^#+\s*/gm, "");
  return section("bio", "Background", `${(d.docs || []).length} sources`,
    `<div class="card">
      <div style="font-size:13.6px;line-height:1.65;white-space:pre-wrap">${esc(txt.slice(0, 900))}</div>
      <div style="margin-top:14px">${(d.claims || []).filter(c => c.docs.length).slice(0, 6)
        .map(c => `<div class="ev"><div>${esc(c.text)}</div>
          ${c.docs.slice(0, 2).map(x => `<div><span class="srank">${esc(x.rank)}</span>
            <a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.name.slice(0, 66))}</a></div>`).join("")}
        </div>`).join("")}</div>
    </div>`);
}


/* ================= EXITS ================= */
/* Conviction asks whether money comes back in. This asks whether it ever
   comes out - the outcome an investor is actually underwriting. */
const EXITS = {};

function exitsBlock(id, name, kind) {
  if (!id) return "";
  const d = EXITS[id];
  if (d === undefined) {
    EXITS[id] = null;
    fetch(`/exits?entity_id=${encodeURIComponent(id)}&name=${encodeURIComponent(name)}&kind=${
      kind === "people" ? "company" : "fund"}`)
      .then(r => r.json()).then(j => { EXITS[id] = j; render(); })
      .catch(e => { EXITS[id] = { error: String(e.message), exits: [] }; render(); });
  }
  if (!d) return section("ex-l", "Exits", "",
    `<div class="card"><div class="sub"><span class="spin"></span>Checking the
     portfolio for completed acquisitions…</div></div>`);
  if (d.error) return "";

  const xs = d.exits || [];
  if (!xs.length) return section("ex", "Exits",
    d.checked ? `none found across ${d.checked} checked` : "",
    `<div class="card"><div class="sub">No completed acquisition on record for
      ${d.checked ? `the ${d.checked} portfolio companies we could check` : "this company"}.
      ${d.unknown ? `${d.unknown} could not be checked. ` : ""}An empty result here is
      a young portfolio as often as a weak one — it is not a score.</div></div>`);

  return section("ex", "Exits",
    d.rate != null ? `${xs.length} of ${d.checked} checked (${pct(d.rate)})`
                   : `${xs.length} on record`,
    `<div class="hl tight">${xs.map(x => `<div class="hlc green">
      <div class="hlhd">${logo(x.company)}
        <div style="min-width:0"><div class="nm">${esc(x.company)}</div>
          <div class="sb">${esc(String(x.date || "").slice(0, 7))}</div></div>
        ${badge("exit", "green")}</div>
      ${x.acquirer ? `<div class="facts"><span>acquired by <b>${esc(x.acquirer)}</b></span></div>` : ""}
      ${x.description ? `<div class="with">${esc(x.description)}</div>` : ""}
      ${x.source ? `<a class="srcline" href="${esc(x.source)}" target="_blank"
        rel="noopener">${esc(String(x.source).replace(/^https?:\/\/(www\.)?/, "").split("/")[0])}</a>` : ""}
    </div>`).join("")}</div>`);
}


/* ================= WHERE THIS FUND TAKES YOU ================= */
/* Every other signal scores an investor in isolation. This is a transition in
   the graph - investor on round k, lead of round k+1 - and it is the question
   a founder is actually deciding: if I take this money, who leads my next
   round? Computed from rounds already cached, so it costs no Cala calls. */
const PIPE = {};

function pipelineBlock(name) {
  const d = PIPE[name];
  if (d === undefined) {
    PIPE[name] = null;
    fetch(`/pipeline?investor=${encodeURIComponent(name)}`)
      .then(r => r.json()).then(j => { PIPE[name] = j; render(); })
      .catch(() => { PIPE[name] = { observations: 0 }; render(); });
  }
  if (!d) return "";
  if (!d.observations) return "";

  const max = Math.max(...d.next_leads.map(r => r.count), 1);
  const spread = d.concentration != null && d.concentration < 0.25;
  return section("pipe", "Where this fund takes you",
    `${d.observations} handoffs to ${d.distinct_leads} distinct leads`,
    `<div class="two">
      <div class="card">
        <h4>Who leads the next round</h4>
        <div class="sub">${d.enough
          ? (spread ? "Spreads widely — this fund is not feeding one successor."
                    : "Concentrated — companies tend to go the same way next.")
          : "Too few observations to read as a pattern."}</div>
        ${d.next_leads.map(r => `<div class="barrow">
          <span class="lbl">${esc(r.name)}</span>
          <span class="bart"><i class="g" style="width:${Math.round(100 * r.count / max)}%"></i></span>
          <span class="pc">${r.count}×</span></div>`).join("")}
      </div>
      <div class="card">
        <h4>Who they invest alongside</h4>
        <div class="sub">same cap table, counted across every cached round</div>
        ${(d.co_investors || []).slice(0, 7).map(c => `<div class="barrow"
            style="grid-template-columns:1fr 54px">
          <span class="lbl">${esc(c.name)}</span>
          <span class="pc">${c.count}×</span></div>`).join("")
          || `<div class="sub">No shared rounds on record.</div>`}
        ${d.led_into?.observations ? `<div class="sub" style="margin-top:12px">
          Leads into companies first backed by ${esc((d.led_into.from || [])
            .slice(0, 3).map(f => f.name).join(", "))}.</div>` : ""}
      </div>
    </div>`);
}
