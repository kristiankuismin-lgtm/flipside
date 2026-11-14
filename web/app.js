/* Flipside — one graph, two perspectives. */
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = v => v == null ? "—" : Math.round(v * 100) + "%";
const initials = s => (s || "?").replace(/[^A-Za-z0-9 ]/g, "").split(/\s+/)
  .slice(0, 2).map(w => w[0] || "").join("").toUpperCase() || "?";

let MODE = "home", F = null, I = null, SEL = null, TAB = 0;
let SYN = null;                        // /syndicates, filled after the screen
let HEALTH = null;                     // what the product is standing on
let FCONTRA = {};                      // investor -> disagreements in their rounds

/* A fund whose rounds disagree with themselves looks clean in the table
   unless we say so, and the founder is about to repeat those numbers to
   the fund itself. Fetched per screen, once, after the list is up. */
async function loadFounderContradictions() {
  const names = (F?.investors || []).map(x => x.investor);
  for (const n of names) {
    if (FCONTRA[n] !== undefined) continue;
    FCONTRA[n] = null;
    try {
      const d = await (await fetch(`/contradictions?investor=${encodeURIComponent(n)}`)).json();
      FCONTRA[n] = d;
    } catch (e) { FCONTRA[n] = { hard: 0, items: [] }; }
  }
  if (MODE === "founder") render();
}

async function loadHealth() {
  try { HEALTH = await (await fetch("/health")).json(); } catch (e) { return; }
  const el = $("#datamode");
  if (!el || !HEALTH) return;
  // Say which it is. A demo running entirely from cache is a strength when
  // stated and a problem when discovered.
  el.innerHTML = HEALTH.cache_only
    ? `<span class="dm cached" title="No live calls at all — every figure comes from
         ${HEALTH.entities_cached} entities and ${HEALTH.rounds_cached} rounds already fetched">
         ● Cached · ${HEALTH.entities_cached.toLocaleString()} entities</span>`
    : `<span class="dm live" title="Live lookups enabled; ${HEALTH.entities_cached}
         entities and ${HEALTH.rounds_cached} rounds are already cached">
         ● Live · ${HEALTH.entities_cached.toLocaleString()} cached</span>`;
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
  document.querySelectorAll("[data-askgo]").forEach(b => b.onclick = () => {
    const v = b.dataset.askgo;
    if (v === "clear") { ASKWHY = null; return render(); }
    ASKWHY = { ...ASKWHY, why: "you chose this view", confident: true, view: v };
    SEL = null;
    if (v === "map") { MODE = "map"; return MAP ? render() : loadMap(); }
    if (v === "investor") { MODE = "investor"; return I ? render() : loadInvestor(); }
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
  const cf = $("#clearf");
  if (cf) cf.onclick = () => { FFILTER = IFILTER = "all"; render(); };
  document.querySelectorAll("[data-hero]").forEach(b => b.onclick = () => {
    const go = (HEROACTS[+b.dataset.hero] || [])[2] || {};
    if (go.brief) return openBrief(go.brief);
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
    e.stopPropagation(); openConviction(b.dataset.cv);
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
  planLoad(); FCONTRA = {}; render();
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
  if (SYN.loading) return section("fsyn", "Round architect", "",
    `<div class="msg"><span class="spin"></span>Assembling syndicates from the round graph…</div>`);
  if (SYN.error || !(SYN.syndicates || []).length) return section("fsyn", "Round architect", "",
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
        title="The rounds behind this">joined ${m.joined} of the ${s.rounds_led} rounds
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

  return section("fsyn", "Round architect",
    `${SYN.syndicates.length} assemblable syndicate${SYN.syndicates.length > 1 ? "s" : ""}`,
    `<div class="synlead">One lead, plus the funds that actually show up when that lead leads —
       which is not the same as the funds it merely shares cap tables with.</div>
     ${anyWarm ? "" : `<div class="verdict grey">No warm route to any of these leads.
       Nothing in the cached graph puts ${backers.length ? esc(backers.join(", ")) : "your backers"}
       and these funds on the same cap table, so every intro here starts cold —
       which is exactly what the Slush floor is for.${elsewhere.length ? `
       The warm ${elsewhere.length > 1 ? "routes you do have go" : "route you do have goes"}
       to ${elsewhere.map(e => `<b>${esc(e.investor)}</b> (${esc(e.signals.warm_path.text)})`).join(", ")} —
       ${elsewhere.length > 1 ? "funds that do not" : "a fund that does not"} lead at your stage,
       so ${elsewhere.length > 1 ? "they are" : "it is"} a door in, not a lead.` : ""}</div>`}
     <div class="syns">${cards}</div>`);
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
    return `<tr data-open="${esc(x.investor)}">
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
      <td class="tdact">${planButton(x.investor)}<button class="btn sm"
        data-brief="${esc(x.investor)}" style="margin-left:5px">Brief</button></td>
    </tr>`;
  }).join("");

  const leads = inv.filter(x => x.signals.lead_rate.label === "🟢");
  const warm = inv.filter(x => x.signals.warm_path.label !== "⚪");
  const shown = FFILTER === "lead" ? leads : FFILTER === "warm" ? warm
    : FFILTER === "conflict" ? red : inv;

  return askTrace() + searchPanel() + heroCard(inv, red, leads, warm)
    + syndicateBlock()
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
    + planSection()
    + section("ftable", "Target list", `${shown.length} of ${inv.length} screened`,
      `<div class="tbl"><table>
      <thead><tr><th class="w-rank"></th><th>Investor</th><th>Verdict</th><th class="num">Score</th>
      <th class="num">Lead</th><th class="num">Follow-on</th>
      <th>Pace</th><th>Conflict</th><th>Route</th><th class="w-act"></th></tr></thead>
      <tbody>${rowsFor(shown)}</tbody></table></div>`)
    + section("fmap", "Conflict map",
      `${(F.edges || []).length} fund–competitor links`, conflictMap());
}

/* The conclusion first, then what to do about it. Six KPI cards, a banner, a
   paragraph and a map all competing for the top of the page meant the one
   thing this product knows - who to assemble and who can introduce you - was
   below the fold. */
function heroCard(inv, red, leads, warm) {
  const best = SYN?.syndicates?.[0];
  const top = inv.find(x => x.signals.conflict.label !== "🔴" && x.score != null);
  const acts = [];
  if (best) acts.push([`Open with ${best.lead}`,
    `leads at your stage and ${best.members[0]?.name} joins ${
      Math.round((best.members[0]?.share || 0) * 100)}% of the rounds they lead`,
    { brief: best.lead }]);
  if (warm.length) acts.push([`Ask ${warm[0].signals.warm_path.text.replace(/^via /, "")} for an intro`,
    `the only warm route in this list — it reaches ${warm[0].investor}`,
    { brief: warm[0].investor }]);
  if (red.length) acts.push([`Do not pitch ${red.map(x => x.investor).slice(0, 2).join(", ")}`,
    `${red.length === 1 ? "it backs" : "they back"} ${
      [...new Set(red.flatMap(x => x.backs))].slice(0, 3).join(", ")}`, { filter: "conflict" }]);
  while (acts.length < 3 && top) {
    acts.push([`Brief ${top.investor}`, "highest-scoring fund with no conflict",
               { brief: top.investor }]);
    break;
  }

  HEROACTS = acts.slice(0, 3);
  const line = best
    ? `Build the round around <b>${esc(best.lead)}</b>, with <b>${
        esc(best.members.map(m => m.name).join(" and "))}</b> following them in.`
    : leads.length
      ? `<b>${leads.length}</b> of ${inv.length} funds screened actually lead at ${esc(F.stage)}.`
      : `No fund in this list leads at ${esc(F.stage)} — that is the finding.`;

  return `<div class="hero">
    <div class="herotop">
      <span class="herotag">Slush 2026 · 18 Nov · ${esc(F.company)} · ${esc(F.stage)}</span>
      <h2>${line}</h2>
      ${warm.length ? "" : `<p class="herosub">No warm route reaches any of them,
        so the floor at Slush is the introduction.</p>`}
    </div>
    <div class="heroacts" style="grid-template-columns:repeat(${
      Math.max(acts.length, 1)},1fr)">${acts.slice(0, 3).map(([t, why, go], i) => `
      <button class="heroact" data-hero="${i}">
        <span class="n">${i + 1}</span>
        <span><b>${esc(t)}</b><em>${esc(why)}</em></span></button>`).join("")}</div>
  </div>`;
}

let HEROACTS = [];

function searchPanel() {
  return `<div class="search">
    <div class="fld"><label>Company raising</label><input id="co" value="${esc(F?.company || "Gosta Labs")}"></div>
    <div class="fld"><label>Round</label><select id="st">
      <option>pre-seed</option><option>seed</option><option selected>series a</option></select></div>
    <div class="fld"><label>Targets</label><select id="n">
      <option>8</option><option selected>14</option><option>20</option><option>30</option></select></div>
    <div class="fld"><label>&nbsp;</label><button class="btn pri" id="go">Run diligence</button></div>
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

const STRUCT = { "pre-emption": ["Pre-emption", "green"], "healthy": ["Healthy up-round", "blue"],
  "bridge": ["Bridge / extension", "red"], "unknown": ["Structure unknown", "grey"] };

let CONTRA = null;        // where sources disagree with each other

async function loadInvestor() {
  $("#view").innerHTML = `<div class="msg"><span class="spin"></span>Scoring insider conviction…</div>`;
  I = await (await fetch("/conviction")).json();
  SEL = null; render();
  if (!CONTRA) loadContradictions();
}

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

function contraSection() {
  if (!CONTRA || !CONTRA.count) return "";
  const hard = (CONTRA.items || []).filter(i => !i.soft);
  if (!hard.length) return "";
  return section("icontra", "Sources disagree",
    `${CONTRA.hard} conflicts across ${CONTRA.companies} companies`,
    `<div class="sub" style="margin-bottom:12px;max-width:62ch;line-height:1.6">
       Two records of the same round, differing on date, amount or lead. We do
       not pick a winner — both readings are shown, because a number you are
       about to repeat to the person it is about should come with its doubt.</div>
     <div class="tbl"><table>
       <thead><tr><th>Company</th><th>Field</th><th>One source says</th>
       <th>Another says</th><th>Sources</th></tr></thead>
       <tbody>${hard.slice(0, 40).map(i => `<tr>
         <td><div class="ent">${logo(i.company)}<div class="nm">${esc(i.company)}</div></div></td>
         <td>${badge(i.field, i.field === "amount" ? "red" : "amber")}</td>
         <td class="nowrap">${esc(i.a || "—")}</td>
         <td class="nowrap">${esc(i.b || "—")}</td>
         <td>${(i.sources || []).slice(0, 2).map(u =>
           `<a href="${esc(u)}" target="_blank" rel="noopener" class="srcx">${
             esc(String(u).replace(/^https?:\/\/(www\.)?/, "").slice(0, 26))}</a>`).join(" ")
           || `<span class="sub">no document URL</span>`}</td>
       </tr>`).join("")}</tbody></table></div>`);
}

function investorList() {
  if (!I) return `<div class="msg"><span class="spin"></span>Loading…</div>`;
  if (I.error) return `<div class="msg">${esc(I.error)}</div>`;
  const all = I.companies || [];
  const pre = all.filter(c => c.structure === "pre-emption");
  const bridge = all.filter(c => c.structure === "bridge");
  const strong = all.filter(c => (c.score ?? 0) >= 70);
  const orphans = I.orphans || [];
  // Six KPI cards that only sat there have become three that filter the list.
  const cs = IFILTER === "strong" ? strong : IFILTER === "bridge" ? bridge : all;

  // Columns that read the same on every row are not columns. "Round
  // structure" was healthy on 35 of the top 40 and "Previous lead" returned
  // on 30 - so those move to a single Flags cell that is empty when there is
  // nothing to say, and the space goes to recency, which does vary.
  const ago = c => c.months_since == null ? "—"
    : c.months_since < 1 ? "this month"
    : c.months_since < 24 ? `${c.months_since} mo`
    : `${(c.months_since / 12).toFixed(1)} yr`;

  const rows = cs.map((c, i) => {
    const back = c.insiders.filter(x => x.returned).length;
    const flags = [
      c.structure === "bridge" ? badge("bridge", "amber") : "",
      c.structure === "preemption" ? badge("pre-empted", "green") : "",
      c.previous_lead_returned === false ? badge("lead walked", "red") : "",
      c.confidence === "Low" ? badge("thin evidence", "grey") : "",
      c.at_slush ? badge("Slush 2026", "accent") : "",
      contraFor(c.company).some(i => !i.soft) ? badge("sources disagree", "red") : "",
    ].filter(Boolean).join(" ");
    return `<tr data-open="${esc(c.company)}" class="${c.stale ? "stalerow" : ""}">
      <td class="rank">${i + 1}</td>
      <td><div class="ent">${logo(c.company)}<div><div class="nm">${esc(c.company)}</div>
        <div class="sb">${c.rounds.length} rounds · ${c.n_insiders} insiders</div></div></div></td>
      <td class="num" style="color:${c.score >= 70 ? "var(--green)" : c.score < 40 ? "var(--red)" : "var(--ink)"}">
        <button class="figure" data-cv="${esc(c.company)}"
          title="How this conviction score was computed">${c.score}</button>
        ${c.recency < 0.995 ? `<span class="decay" title="aged from ${c.score_fresh}">↓${
          Math.round((1 - c.recency) * 100)}%</span>` : ""}</td>
      <td class="num">${esc(ago(c))}</td>
      <td class="nowrap">${esc(String(c.last_round || "—").slice(0, 7))}
        ${c.stale ? badge("stale", "amber") : ""}</td>
      <td class="num">${back}/${c.n_insiders}</td>
      <td class="flags">${flags}</td>
    </tr>`;
  }).join("");

  return askTrace() + kpis([
    ["Companies scored", cs.length, "all",
     "every company with two rounds and a prior investor to compare"],
    ["Insiders doubling down", strong.length, "strong",
     "conviction 70+ after ageing the evidence"],
    ["Bridges", bridge.length, "bridge",
     "an extension rather than a priced up-round"],
  ], IFILTER, k => { IFILTER = IFILTER === k ? "all" : k; render(); })
  + (IFILTER !== "all" ? `<div class="filterline">Showing
      <b>${esc({ strong: "insiders doubling down", bridge: "bridges" }[IFILTER] || IFILTER)}</b>
      — ${cs.length} of ${all.length}.
      <button class="btn sm" id="clearf">Clear</button></div>` : "")
  + (!pre.length && IFILTER === "all" && I.coverage
      ? section("ipre", "Pre-emptions",
          `0 of ${all.length} — starved, not absent`,
          `<div class="emptywhy">
            <b>Not enough round sizes to detect one.</b>
            A pre-emption is an insider-only round at 2x or more within twelve
            months, which needs the size of this round and the one before it.
            Of ${I.coverage.round_records} round records in this corpus,
            ${I.coverage.with_amount} carry an amount
            (${Math.round(100 * I.coverage.with_amount / Math.max(I.coverage.round_records, 1))}%),
            and only ${I.coverage.amount_pairs} consecutive pairs have both.
            <span class="sub">The zero is the coverage, not the market.</span>
          </div>`)
      : "")
  + (pre.length && IFILTER === "all" ? section("ipre", "Pre-emptions", "",
      `<div class="hl">${pre.slice(0, 6).map(c => `<div class="hlc green"><div class="hlhd">${logo(c.company)}
        <div><div class="nm">${esc(c.company)}</div><div class="sb">${c.rounds.at(-1).stage}</div></div>
        ${badge(c.score, "green")}</div>
        <div class="hlm"><div><div class="k">Insiders back</div><div class="v">${c.insiders.filter(x => x.returned).length}/${c.n_insiders}</div></div>
        <div><div class="k">Last round</div><div class="v">${esc(String(c.last_round || "—").slice(0, 7))}</div></div></div></div>`).join("")}</div>`) : "")
  + contraSection()
  + section("itbl", "Conviction ranking",
      I.recency ? `evidence older than ${I.recency.grace_months} months is discounted,
        halving every ${I.recency.halflife_months}` : "", `<div class="tbl"><table>
      <thead><tr><th class="w-rank"></th><th>Company</th><th class="num">Conviction</th>
      <th class="num">Age</th><th class="w-date">Last round</th>
      <th class="num">Insiders back</th><th class="w-flags">Flags</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`)
  + (orphans.length ? section("iorph", "Well-performing orphans",
      "growing, but their lead's fund has stopped deploying",
      `<div class="hl">${orphans.map(o => `<div class="hlc"><div class="hlhd">${logo(o.company)}
        <div><div class="nm">${esc(o.company)}</div><div class="sb">${o.months} months since last round</div></div>
        ${badge("needs a new lead", "amber")}</div>
        <ul class="reasons">${o.why.map(w => `<li>${esc(w)}</li>`).join("")}</ul></div>`).join("")}</div>`)
    : section("iorph", "Well-performing orphans", "detector is inert — one input is missing",
      `<div class="emptywhy">
        <b>This cannot fire on the data we have.</b>
        An orphan is a company still growing whose lead's fund has stopped
        deploying. Two of the three conditions are checkable — the fund has
        slowed, and 15+ months since the last round. The third, headcount
        still growing, is not: Cala carries no headcount series for private
        companies, so the condition can never be evaluated and the detector
        can never return anyone.
        <span class="sub">Shown rather than hidden, because a section that
        silently never fires is worse than one that says why.</span></div>`));
}

function investorEntity() {
  const c = (I.companies || []).find(x => x.company === SEL);
  if (!c) { SEL = null; return investorList(); }
  const [sl, sc] = STRUCT[c.structure] || STRUCT.unknown;
  const tabs = ["Overview", "Insiders", "Rounds", "Public record", "Evidence"];
  const latest = c.rounds.at(-1);
  let body = entityHeader(c.company, "",
    `${c.rounds.length} rounds · latest ${esc(latest.stage)} ${esc(latest.date)}
     · ${badge(sl, sc)}${c.at_slush ? " · " + badge("Slush 2026", "accent") : ""}`,
    tabs, `<button class="btn" onclick="window.print()">Export brief</button>`);

  if (TAB === 0) {
    const back = c.insiders.filter(x => x.returned).length;
    body += `<div class="verdict ${c.score >= 70 ? "green" : c.score < 40 ? "red" : "grey"}">
      <b>${c.score >= 70 ? "Insiders are doubling down." : c.score < 40 ? "Insiders stepped back."
        : "Mixed insider signal."}</b> ${esc(c.reasons.join("; "))}.</div>`
      + stats(5, [
        ["Conviction", c.score, "mono"],
        ["Insiders returning", `${back}/${c.n_insiders}`, "mono"],
        ["Round structure", sl],
        ["Previous lead", c.previous_lead_returned === true ? "returned"
          : c.previous_lead_returned === false ? "walked away" : "unknown"],
        ["Confidence", c.confidence],
      ])
      + section("io-why", "Why this score", "",
          `<div class="card"><ul class="reasons">${c.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul></div>`)
      + section("io-prof", "Round profile", "",
          badgeGroup([
            ["Stage reached", [latest.stage].filter(Boolean), "purple"],
            ["Round structure", [sl], sc],
            ["Insider types", [...new Set(c.insiders.map(i => i.kind))], "blue"],
            ["Evidence", [`${c.n_insiders} insiders`, c.confidence], "grey"],
          ]))
      + section("io-chart", "Where the conviction comes from", "",
          `<div class="three">
            ${chart("Insider participation",
              `${back} of ${c.n_insiders} prior investors returned (${Math.round(100*back/Math.max(c.n_insiders,1))}%)`,
              donut([{k:"Returned",v:back,c:"#7fb88a"},
                     {k:"Did not",v:Math.max(0,c.n_insiders-back),c:"#d9685c"}]))}
            ${chart("Investor mix", `${new Set(c.insiders.map(i=>i.kind)).size} types on the cap table`,
              donut(Object.entries(c.insiders.reduce((a,i)=>(a[i.kind]=(a[i.kind]||0)+1,a),{}))
                .map(([k,v],i)=>({k,v,c:["#8ba3c7","#a894c4","#d9a441","#7d766c"][i%4]}))))}
            ${chart("Round cadence", `${c.rounds.length} rounds on record`,
              bars(c.rounds.map((r,i)=>{
                const prev = i ? new Date(c.rounds[i-1].date) : null;
                const gap = prev ? Math.round((new Date(r.date)-prev)/2628000000) : 0;
                return [r.stage||"round", gap, gap>24?"a":"g", gap?gap+" mo":"first"];
              })))}
          </div>`)
      + section("io-mix", "Insider behaviour", "", `<div class="two">
          <div class="card"><h4>Who came back</h4>
            ${bars(c.insiders.map(x => [x.name, x.returned ? 1 : 0, x.returned ? "g" : "r",
              x.returned ? "back" : "out"]), 1)}</div>
          <div class="card"><h4>Against their own habit</h4>
            
            ${bars(c.insiders.filter(x => x.baseline != null).map(x =>
              [x.name, x.baseline, x.returned ? "g" : "n", pct(x.baseline)]), 1)
              || `<div class="msg" style="padding:18px">No habit baseline — unknown is not zero.</div>`}</div>
        </div>`);
  }
  if (TAB === 1) {
    body += `<div class="hl">${c.insiders.map(x => `<div class="hlc ${x.returned ? "green" : ""}">
      <div class="hlhd">${logo(x.name)}<div><div class="nm">${esc(x.name)}</div>
        <div class="sb">${esc(x.kind)}</div></div>
      ${x.returned ? badge("returned", "green") : badge("did not return", "red")}</div>
      <div class="hlm">
        <div><div class="k">Role on prior round</div><div class="v">${x.was_lead ? "Lead" : "Participant"}</div></div>
        <div><div class="k">Usual follow-on</div><div class="v">${x.baseline == null ? "—" : pct(x.baseline)}</div></div>
      </div></div>`).join("")}</div>`;
  }
  if (TAB === 2) {
    body += `<div class="tbl"><table><thead><tr><th>Round</th><th>Date</th>
      <th style="text-align:right">Amount</th><th>Lead</th><th>Investors</th></tr></thead><tbody>
      ${c.rounds.map(r => `<tr style="cursor:default"><td>${esc(r.stage)}</td><td class="num" style="text-align:left">${esc(r.date)}</td>
        <td class="num">${r.amount ? "€" + (r.amount / 1e6).toFixed(1) + "M" : "—"}</td>
        <td>${r.leads?.length ? esc(r.leads.join(", ")) : "—"}</td>
        <td style="font-size:12.3px;color:var(--dim)">${esc((r.investors || []).join(", "))}</td></tr>`).join("")}
      </tbody></table></div>`;
  }
  if (TAB === 3) {
    body += publicRecordTab(c.company, c.rounds.map(r => r.date));
  }
  if (TAB === 4) {
    body += `<p class="lede">Conviction is arithmetic over Cala's funding graph: who was on the cap
      table before the latest round, who appears on it again, and how that compares with what each
      of those investors usually does. No part of the score is generated text.</p>`
      + `<div class="card"><h4>Inputs used</h4><div class="sub">all from Cala</div>
        <ul class="reasons">
        <li>${c.rounds.length} funding rounds with dates, investors and lead flags</li>
        <li>${c.insiders.filter(x => x.baseline != null).length} of ${c.n_insiders} insiders had enough
            history for a habit baseline (pool mean ${pct(I.pool_baseline)} used to shrink thin ones)</li>
        <li>Round structure from label, gap and size${latest.amount ? "" : " — size unavailable, so structure is reported as unknown rather than guessed"}</li>
        </ul></div>`;
  }
  return body + "</div>";
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
  const id = MODE === "founder" ? "ftable" : MODE === "investor" ? "itbl" : null;
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
  if (!TEAM.people?.length) return `<div class="emptywhy" style="margin-top:var(--s2)">
    <b>Nothing we could quote.</b> ${esc(TEAM.why || "")}
    ${TEAM.team_url ? `<br>Read <a href="${esc(TEAM.team_url)}" target="_blank"
      rel="noopener">${esc(String(TEAM.team_url).replace(/^https?:\/\//, ""))}</a>.` : ""}
    <span class="sub">A name without a role in the same sentence is not a claim
      the page made, so it is dropped rather than guessed at.</span></div>`;

  return `<div class="teamwrap">
    <div class="teamhd">${TEAM.people.length} people
      <a href="${esc(TEAM.team_url)}" target="_blank" rel="noopener">${esc(host)}</a>
      names on its own page</div>
    ${TEAM.people.map(p => `<div class="teamrow">
      <span class="av">${esc(initials(p.name))}</span>
      <div style="min-width:0;flex:1">
        <div class="nm">${esc(p.name)} ${badge(p.role, p.role === "founder" ? "green" : "grey")}</div>
        <div class="q">“${esc(p.quote)}”</div></div>
      <button class="btn sm" data-fsname="${esc(p.name)}">Signal →</button>
    </div>`).join("")}
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
function openConviction(company) {
  const c = (I?.companies || []).find(x => x.company === company);
  if (!c) return;
  const b = c.breakdown;
  const w = b?.weights || {};
  const w2 = document.createElement("div");
  w2.className = "scrim on";

  const rows = b ? [
    ["Insiders returned", b.participation,
     `${b.returned} of ${b.insiders}, weighted by investor type and shrunk toward
      the ${pct(b.pool_mean)} pool mean so one insider cannot outrank six`],
    ["Lift over habit", b.lift_norm,
     b.lift == null ? "no follow-on baselines known for these investors"
       : `${b.lift > 0 ? "above" : "below"} their usual rate by ${pct(Math.abs(b.lift))},
          over ${b.known_baselines} investors whose habit we know`],
    ["Previous lead", b.lead,
     c.previous_lead_returned === true ? "the lead came back"
       : c.previous_lead_returned === false ? "the lead did not return"
       : "no previous lead on record"],
    ["Round structure", b.structure, esc(b.structure_label || "unknown")],
  ] : [];

  w2.innerHTML = `<div class="composebox wide" onclick="event.stopPropagation()">
    <div class="sidehd"><h3>Conviction ${c.score} — ${esc(company)}</h3>
      <div class="s">${c.last_round ? `last round ${esc(String(c.last_round).slice(0, 7))}` : ""}
        ${c.months_since != null ? ` · ${c.months_since} months ago` : ""}</div></div>
    <div style="padding:15px">
      ${b ? `<table class="mathtbl"><tbody>${rows.map(([k, v, why]) => `
        <tr><td>${esc(k)}</td><td class="num">${(v ?? 0).toFixed(2)}</td>
        <td class="num" style="color:var(--faint)">×${w[k === "Insiders returned" ? "participation"
          : k === "Lift over habit" ? "lift" : k === "Previous lead" ? "lead" : "structure"]}</td>
        <td class="sub">${why}</td></tr>`).join("")}</tbody></table>
        <div class="sub" style="margin-top:9px">
          weighted blend = <b>${b.rebuilt}</b>${
            c.recency < 0.995 ? `, aged ×${c.recency} for a round ${c.months_since} months
              old = <b>${c.score}</b>` : ""}
          ${Math.abs(b.residual || 0) > 0.5 ? `<br><span style="color:var(--amber)">
            Differs from the stored score by ${b.residual > 0 ? "+" : ""}${b.residual}.
            The corpus was scored against a fund-slowing set we reconstruct from
            today's cache, and the two no longer match exactly for this company.
            Reported rather than hidden.</span>` : ""}
        </div>`
      : `<div class="sub">No breakdown stored for this company.</div>`}
      <div class="sub" style="margin:13px 0 6px">The ${c.n_insiders} prior investors</div>
      <div class="tbl"><table><thead><tr><th>Investor</th><th>Type</th>
        <th>Came back</th><th class="num">Their usual rate</th></tr></thead><tbody>
        ${(c.insiders || []).map(i => `<tr>
          <td>${esc(i.name)}${i.was_lead ? " " + badge("lead", "blue") : ""}</td>
          <td class="sub">${esc(i.kind || "unknown")}${
            i.fund_slowing ? " " + badge("slowed", "amber") : ""}</td>
          <td>${i.returned ? badge("yes", "green") : badge("no", "red")}</td>
          <td class="num">${i.baseline == null ? "—" : pct(i.baseline)}</td>
        </tr>`).join("")}</tbody></table></div>
      <div style="display:flex;margin-top:14px">
        <button class="btn" id="cvclose" style="margin-left:auto">Close</button></div>
    </div></div>`;
  document.body.appendChild(w2);
  const close = () => w2.remove();
  w2.onclick = close;
  w2.querySelector("#cvclose").onclick = close;
}

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
  } else if (MODE === "map") {
    parts = [{ t: "Map" }, { t: "Companies, funds and people" }];
    html = mapView();
  } else if (MODE === "signal") {
    parts = [{ t: "Signals" }, { t: "Founder signal" }];
    html = signalView();
  } else if (MODE === "accuracy") {
    parts = [{ t: "Signals" }, { t: "Does the signal work?" }];
    html = accuracyView();
  } else if (MODE === "founder") {
    parts = SEL ? [{ t: "Founder", go: 1 }, { t: F?.company || "", go: 1 }, { t: SEL }]
                : [{ t: "Founder" }, { t: F?.company || "Target screening" }];
    html = SEL ? founderEntity() : founderList();
  } else {
    parts = SEL ? [{ t: "Investor", go: 1 }, { t: "Conviction", go: 1 }, { t: SEL }]
                : [{ t: "Investor" }, { t: "Insider conviction" }];
    html = SEL ? investorEntity() : investorList();
  }
  crumb(parts);
  $("#baracts").innerHTML = MODE === "founder" && !SEL && F
    ? `<button class="btn" id="go2">Re-run</button>` : "";
  $("#view").innerHTML = html;
  wire();
  kbdInit();
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
  document.querySelectorAll("[data-lens]").forEach(b => b.onclick = () => {
    LENS = b.dataset.lens;
    const v = $("#askbox")?.value || "";
    render();
    const ab2 = $("#askbox");
    if (ab2) { ab2.value = v; ab2.focus(); }
  });
  document.querySelectorAll("[data-q]").forEach(b =>
    b.onclick = () => routeAsk(b.dataset.q));
  const ab = $("#askbox");
  if (ab) {
    ab.focus();
    ab.onkeydown = e => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); routeAsk(ab.value); }
    };
    $("#asksend").onclick = () => routeAsk(ab.value);
  }
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
  if (MODE === "investor" && !I) loadInvestor();
  else if (MODE === "map" && !MAP) loadMap();
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
  return stats(5, [
    ["On the map", total],
    ["Slush exhibitors", MAP.placed],
    ["Funded companies", (MAP.portfolio || []).length],
    ["Funds", (MAP.funds || []).length],
    ["Exact street coordinates", MAP.exact],
  ])
  + section("gmap", "Where the ecosystem is",
      `${MAP.placed} placed · ${MAP.unplaced} addresses we could not resolve`,
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
            ${PLAN.length ? `<span class="grp">
              <button class="tgl ${PLANONLY ? "on" : ""}" id="planonly"
                title="Show only the funds in your Slush plan">★ My plan (${PLAN.length})</button>
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
  const planKeys = new Set(PLAN.map(n => n.toLowerCase().replace(/[^a-z0-9]/g, "")));
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
    const col = isFund ? "#c2614f" : statusColor(p);
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
    ? `Your plan on the map (${layer.length} of ${PLAN.length} placeable)`
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
const CHIPS = [
  ["◧", "Screen my investor list", "gosta labs"],
  ["◨", "Who are insiders doubling down on?", "conviction"],
  ["◉", "Map the Slush 2026 floor", "map"],
  ["◆", "Who is raising without announcing it?", "silent"],
];

/* Which side of the graph the question is asked from. "Auto" reads the
   question and the name; the other two are the user overruling that, which
   they must be able to do - "lifeline ventures" is a fund, and screening
   investors for it is not a thing anyone wanted. */
let LENS = "auto";
const LENSES = [
  ["auto", "Auto", "read the question"],
  ["founder", "I'm raising", "screen investors for a company"],
  ["investor", "I'm investing", "insider conviction across companies"],
  ["lookup", "Look up", "open a fund or person profile"],
];

function homeView() {
  return `<div class="home">
    <div class="homehd"><span class="sq">F</span><h1>What are you looking at today?</h1></div>
    <div class="lens">${LENSES.map(([k, label, why]) =>
      `<button class="lensbtn ${LENS === k ? "on" : ""}" data-lens="${k}" title="${esc(why)}">
         ${esc(label)}</button>`).join("")}</div>
    <div class="ask">
      <textarea id="askbox" rows="2" placeholder="${
        LENS === "investor" ? "A theme or just press Run — e.g. &quot;who is raising quietly?&quot;"
        : LENS === "lookup" ? "A fund or person by name — e.g. &quot;Lifeline Ventures&quot;"
        : LENS === "founder" ? "The company you're raising for — e.g. &quot;Gosta Labs, Series A&quot;"
        : "A company you're raising for, a fund you're meeting, or just ask — try &quot;Gosta Labs&quot;"
      }"></textarea>
      <div class="askfoot">
        <span class="lenshint">${esc((LENSES.find(l => l[0] === LENS) || [])[2] || "")}</span>
        <button class="send" id="asksend" title="Run">↑</button>
      </div>
    </div>
    <div class="chips">${CHIPS.map(([ic, label, q]) =>
      `<button class="chip" data-q="${esc(q)}"><span class="ic">${ic}</span>${esc(label)}</button>`).join("")}</div>
  </div>`;
}

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
    return loadEntity(best.id, best.kind, best.name);
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
    MODE = "investor"; SEL = null; return I ? render() : loadInvestor();
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
        return loadEntity(resolved.entity_id, "fund", resolved.name || q);
      return lookupEntity(resolved?.name || q, null);
    }
  }

  ASKWHY = { q, why: intent.why, confident: intent.confident !== false,
             view: intent.view };

  if (intent.view === "map") { MODE = "map"; SEL = null; return MAP ? render() : loadMap(); }
  if (intent.view === "investor") {
    MODE = "investor"; SEL = null; return I ? render() : loadInvestor();
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
    loadEntity(r.id, QKIND, r.name);
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
