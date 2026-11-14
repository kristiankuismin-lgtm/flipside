/* Flipside — one graph, two perspectives. */
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = v => v == null ? "—" : Math.round(v * 100) + "%";
const initials = s => (s || "?").replace(/[^A-Za-z0-9 ]/g, "").split(/\s+/)
  .slice(0, 2).map(w => w[0] || "").join("").toUpperCase() || "?";

let MODE = "home", F = null, I = null, SEL = null, TAB = 0;
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

function bars(rows, max) {
  const m = max ?? Math.max(...rows.map(r => r[1] || 0), 1);
  return rows.map(([lbl, v, cls, disp]) => `<div class="barrow">
    <span class="lbl">${esc(lbl)}</span>
    <span class="bart"><i class="${cls || ""}" style="width:${Math.round(100 * (v || 0) / m)}%"></i></span>
    <span class="pc">${esc(disp ?? (v == null ? "—" : v))}</span></div>`).join("");
}

function donut(parts, size = 118) {
  const tot = parts.reduce((a, p) => a + p.v, 0) || 1, R = size / 2, r = R * .64;
  let a0 = -Math.PI / 2, paths = "";
  for (const p of parts) {
    if (!p.v) continue;
    const frac = p.v / tot;
    // A full-circle slice would have identical start and end points, and an SVG
    // arc between two identical points draws nothing. Use a circle instead.
    if (frac > 0.999) {
      paths += `<circle cx="${R}" cy="${R}" r="${r}" fill="none"
        stroke="${p.c}" stroke-width="${R * .5}"/>`;
      a0 += 2 * Math.PI;
      continue;
    }
    const a1 = a0 + 2 * Math.PI * frac, big = a1 - a0 > Math.PI ? 1 : 0;
    const x0 = R + r * Math.cos(a0), y0 = R + r * Math.sin(a0);
    const x1 = R + r * Math.cos(a1), y1 = R + r * Math.sin(a1);
    paths += `<path d="M${x0} ${y0} A${r} ${r} 0 ${big} 1 ${x1} ${y1}" fill="none"
      stroke="${p.c}" stroke-width="${R * .5}"/>`;
    a0 = a1;
  }
  return `<div class="donutwrap"><svg width="${size}" height="${size}">${paths}</svg>
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
async function runFounder() {
  $("#view").innerHTML = `<div class="msg"><span class="spin"></span>Reading Cala's graph…</div>`;
  const r = await fetch("/analyze", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      company: PENDING_CO || $("#co")?.value || F?.company || "Gosta Labs",
      stage: $("#st")?.value || "series a",
      limit: +($("#n")?.value || 14) })
  });
  F = await r.json(); PENDING_CO = null; SEL = null; render();
}

function founderList() {
  if (!F) return searchPanel() + `<div class="msg">Run diligence to screen your target list.</div>`;
  const inv = F.investors, red = inv.filter(x => x.signals.conflict.label === "🔴");
  const rows = inv.map((x, i) => {
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
      <td class="num">${x.score === null ? "—" : x.score}</td>
      <td class="num">${pct(s.lead_rate.value)}</td>
      <td class="num">${pct(s.follow_on.value)}</td>
      <td>${s.dry_powder.label === "⚪" ? badge("—", "grey")
        : badge(s.dry_powder.text.match(/^(\d+)/)?.[1] + " / 6mo",
                s.dry_powder.label === "🟢" ? "green" : s.dry_powder.label === "🟡" ? "amber" : "red")}</td>
      <td>${x.backs?.length ? badge(x.backs.join(", "), "red") : badge("clear", "grey")}</td>
      <td>${s.warm_path.label !== "⚪" ? badge(s.warm_path.text.replace(/^via /, ""), "blue") : ""}</td>
    </tr>`;
  }).join("");

  return searchPanel() + stats(6, [
    ["Investors screened", inv.length],
    ["Backing a competitor", `<span style="color:var(--red)">${red.length}</span>`],
    ["Stopped deploying", `<span style="color:var(--amber)">${inv.filter(x => x.signals.dry_powder.label === "🔴").length}</span>`],
    ["Lead at your stage", `<span style="color:var(--green)">${inv.filter(x => x.signals.lead_rate.label === "🟢").length}</span>`],
    ["Competitors in Cala", F.competitors.length],
    ["Warm routes found", inv.filter(x => x.signals.warm_path.label !== "⚪").length],
  ]) + (red.length ? `<div class="verdict red"><b>${red.length} fund${red.length > 1 ? "s" : ""} in your
      list already back a competitor.</b> ${red.map(x => `${esc(x.investor)} → ${esc(x.backs.join(", "))}`).join(" · ")}</div>` : "")
    + section("ftable", "Target list", "", `<div class="tbl"><table>
      <thead><tr><th></th><th>Investor</th><th>Verdict</th><th style="text-align:right">Score</th>
      <th style="text-align:right">Lead</th><th style="text-align:right">Follow-on</th>
      <th>Pace</th><th>Conflict</th><th>Route</th></tr></thead><tbody>${rows}</tbody></table></div>`)
    + section("fmap", "Conflict map", "", conflictMap());
}

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

function conflictMap() {
  const edges = F.edges || [];
  if (!edges.length) return `<div class="msg">No fund in this list backs a named competitor —
    a computed result, not an empty state.</div>`;
  const comps = [...new Set(edges.map(e => e.competitor))];
  const funds = [...new Set(edges.map(e => e.investor))];
  const H = Math.max(comps.length, funds.length, 3) * 46 + 72, W = 1000;
  const x1 = 120, x2 = W / 2, x3 = W - 140, my = H / 2;
  const y = (i, n) => 58 + (H - 86) * (n === 1 ? .5 : i / (n - 1));
  const node = (x, yy, w, t, c) => `<g><rect class="mnode ${c}" x="${x - w / 2}" y="${yy - 14}"
      width="${w}" height="28" rx="7"/><text class="mlbl ${c === "hot" ? "hot" : ""}" x="${x}"
      y="${yy + 4}" text-anchor="middle">${esc(t.length > 24 ? t.slice(0, 23) + "…" : t)}</text></g>`;
  return `<div class="mapbox"><svg viewBox="0 0 ${W} ${H}">
    <text class="mhd" x="${x1}" y="28" text-anchor="middle">YOU</text>
    <text class="mhd" x="${x2}" y="28" text-anchor="middle">COMPETITORS</text>
    <text class="mhd" x="${x3}" y="28" text-anchor="middle">FUNDS BACKING THEM</text>
    ${comps.map((_, i) => `<path class="medge" d="M${x1 + 56} ${my} C${x1 + 130} ${my},${x2 - 90} ${y(i, comps.length)},${x2 - 100} ${y(i, comps.length)}"/>`).join("")}
    ${edges.map(e => { const i = comps.indexOf(e.competitor), j = funds.indexOf(e.investor);
      return `<path class="medge hot" d="M${x2 + 100} ${y(i, comps.length)} C${x2 + 180} ${y(i, comps.length)},${x3 - 120} ${y(j, funds.length)},${x3 - 95} ${y(j, funds.length)}"/>`; }).join("")}
    ${node(x1, my, 110, F.company, "me")}
    ${comps.map((c, i) => node(x2, y(i, comps.length), 200, c, "")).join("")}
    ${funds.map((f, i) => node(x3, y(i, funds.length), 190, f, "hot")).join("")}
  </svg></div>`;
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
    badge(x.evidence_depth === "hyva" ? "well covered"
      : x.evidence_depth === "ohut" ? "thin coverage" : "insufficient",
      x.evidence_depth === "hyva" ? "green" : x.evidence_depth === "ohut" ? "amber" : "grey"),
  ].filter(Boolean).join(" · ");
  let body = entityHeader(x.investor, "", meta, tabs,
    `<button class="btn" id="composeit">Compose intro</button>
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
      + section("fo-sig", "Signal strength", "", `<div class="card">${bars([
          ["Lead rate", s.lead_rate.value, s.lead_rate.label === "🟢" ? "g" : s.lead_rate.label === "🟡" ? "a" : s.lead_rate.value == null ? "n" : "r", pct(s.lead_rate.value)],
          ["Follow-on", s.follow_on.value, s.follow_on.label === "🟢" ? "g" : s.follow_on.label === "🟡" ? "a" : s.follow_on.value == null ? "n" : "r", pct(s.follow_on.value)],
          ["Portfolio progression", s.next_round.value, s.next_round.label === "🟢" ? "g" : "a", pct(s.next_round.value)],
          ["Deployment pace", Math.min(s.dry_powder.value ?? 0, 1), s.dry_powder.label === "🟢" ? "g" : s.dry_powder.label === "🟡" ? "a" : "r", s.dry_powder.label === "⚪" ? "—" : "ok"],
        ], 1)}</div>`)
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
            ["Evidence depth", [x.evidence_depth === "hyva" ? "well covered"
              : x.evidence_depth === "ohut" ? "thin" : "insufficient"], "grey"],
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
const STRUCT = { "pre-emption": ["Pre-emption", "green"], "healthy": ["Healthy up-round", "blue"],
  "bridge": ["Bridge / extension", "red"], "unknown": ["Structure unknown", "grey"] };

async function loadInvestor() {
  $("#view").innerHTML = `<div class="msg"><span class="spin"></span>Scoring insider conviction…</div>`;
  I = await (await fetch("/conviction")).json();
  SEL = null; render();
}

function investorList() {
  if (!I) return `<div class="msg"><span class="spin"></span>Loading…</div>`;
  if (I.error) return `<div class="msg">${esc(I.error)}</div>`;
  const cs = I.companies || [];
  const pre = cs.filter(c => c.structure === "pre-emption");
  const bridge = cs.filter(c => c.structure === "bridge");
  const orphans = I.orphans || [];
  const atSlush = cs.filter(c => c.at_slush);

  const rows = cs.map((c, i) => {
    const [sl, sc] = STRUCT[c.structure] || STRUCT.unknown;
    const back = c.insiders.filter(x => x.returned).length;
    return `<tr data-open="${esc(c.company)}">
      <td class="rank">${i + 1}</td>
      <td><div class="ent">${logo(c.company)}<div><div class="nm">${esc(c.company)}</div>
        <div class="sb">${c.rounds.length} rounds · ${c.n_insiders} insiders</div></div></div></td>
      <td class="num" style="color:${c.score >= 70 ? "var(--green)" : c.score < 40 ? "var(--red)" : "var(--ink)"}">${c.score}</td>
      <td>${badge(sl, sc)}</td>
      <td class="num">${back}/${c.n_insiders}</td>
      <td>${c.previous_lead_returned === true ? badge("returned", "green")
        : c.previous_lead_returned === false ? badge("walked away", "red") : badge("—", "grey")}</td>
      <td>${badge(c.confidence, c.confidence === "High" ? "green" : c.confidence === "Medium" ? "amber" : "grey")}</td>
      <td>${c.at_slush ? badge("Slush 2026", "accent") : ""}</td>
    </tr>`;
  }).join("");

  return stats(6, [
    ["Companies scored", cs.length],
    ["Pre-emptions", `<span style="color:var(--green)">${pre.length}</span>`],
    ["Bridges", `<span style="color:var(--red)">${bridge.length}</span>`],
    ["Lead walked away", `<span style="color:var(--amber)">${cs.filter(c => c.previous_lead_returned === false).length}</span>`],
    ["Exhibiting at Slush", atSlush.length],
    ["Pool follow-on rate", pct(I.pool_baseline)],
  ])
  + (pre.length ? section("ipre", "Pre-emptions", "",
      `<div class="hl">${pre.slice(0, 6).map(c => `<div class="hlc green"><div class="hlhd">${logo(c.company)}
        <div><div class="nm">${esc(c.company)}</div><div class="sb">${c.rounds.at(-1).stage}</div></div>
        ${badge(c.score, "green")}</div>
        <div class="hlm"><div><div class="k">Insiders back</div><div class="v">${c.insiders.filter(x => x.returned).length}/${c.n_insiders}</div></div>
        <div><div class="k">Previous lead</div><div class="v">${c.previous_lead_returned ? "returned" : "—"}</div></div></div></div>`).join("")}</div>`) : "")
  + section("itbl", "Conviction ranking", "", `<div class="tbl"><table>
      <thead><tr><th></th><th>Company</th><th style="text-align:right">Conviction</th><th>Round structure</th>
      <th style="text-align:right">Insiders back</th><th>Previous lead</th><th>Confidence</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table></div>`)
  + (orphans.length ? section("iorph", "Well-performing orphans",
      "growing, but their lead's fund has stopped deploying",
      `<div class="hl">${orphans.map(o => `<div class="hlc"><div class="hlhd">${logo(o.company)}
        <div><div class="nm">${esc(o.company)}</div><div class="sb">${o.months} months since last round</div></div>
        ${badge("needs a new lead", "amber")}</div>
        <ul class="reasons">${o.why.map(w => `<li>${esc(w)}</li>`).join("")}</ul></div>`).join("")}</div>`)
    : section("iorph", "Well-performing orphans", "none found in this corpus",
      `<div class="msg" style="padding:26px">No company met every condition: lead's fund slowed,
       15+ months since the last round, and headcount still growing.
       An empty list here is a statement about coverage, not a bug.</div>`));
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
function render() {
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
    parts = [{ t: "Slush 2026" }, { t: "Exhibitor map" }];
    html = mapView();
  } else if (MODE === "accuracy") {
    parts = [{ t: "Method" }, { t: "Backtest" }];
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
  if (MODE === "map" && MAP?.points) setTimeout(initMap, 30);
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
  if (cm) cm.onclick = () => openCompose();
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
    if (m.placed) $("#ct-m").textContent = m.placed + " placed";
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
  $("#view").innerHTML = `<div class="msg"><span class="spin"></span>Placing exhibitors…</div>`;
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
  return stats(5, [
    ["Slush exhibitors placed", MAP.placed],
    ["Funded companies placed", (MAP.portfolio || []).length],
    ["Funds placed", (MAP.funds || []).length],
    ["Exact street coordinates", MAP.exact],
    ["Checked for funding", MAP.walked || 0],
  ])
  + section("gmap", "Where the floor comes from",
      `${MAP.placed} placed · ${MAP.unplaced} addresses we could not resolve`,
      `<div class="maproot">
        <div class="mapbox">
          <div id="mlmap"></div>
          <div class="mapctl">
            <button class="btn" data-fly="eu">Europe</button>
            <button class="btn" data-fly="nordics">Nordics</button>
            <button class="btn" data-fly="world">World</button>
          </div>
          <div class="mapctl" style="top:auto;bottom:11px;left:auto;right:11px">
            <button class="btn ${MAPMODE === "co" ? "pri" : ""}" data-mm="co">Companies</button>
            <button class="btn ${MAPMODE === "pf" ? "pri" : ""}" data-mm="pf">Funded</button>
            <button class="btn ${MAPMODE === "fu" ? "pri" : ""}" data-mm="fu">Funds</button>
            <button class="btn ${MAPMODE === "pp" ? "pri" : ""}" data-mm="pp">People</button>
          </div>
          <div class="mapsearch"><span style="color:var(--faint)">⌕</span>
            <input id="mapq" autocomplete="off" placeholder="${
              MAPMODE === "pp" ? "Find a founder or investor"
              : MAPMODE === "fu" ? "Filter funds, or type a city"
              : MAPMODE === "pf" ? "Filter funded companies, or type a city"
              : "Filter exhibitors, or type a city"}"></div>
          <div class="maplegend">
            ${Object.entries(STATUS).map(([k, [c, lbl]]) =>
              `<span class="sw"><i style="background:${c}"></i>${lbl}${
                MAP.status?.[k] ? ` (${MAP.status[k]})` : ""}</span>`).join("")}
            <span class="sw"><i style="background:#c2614f"></i>fund</span>
            <span class="sw" id="precisenote"></span>
          </div>
        </div>
        <div class="side">
          <div class="sidehd"><h3 id="sidet">Exhibitors</h3>
            <div class="s" id="sides">Click a pin, or filter to narrow the list</div></div>
          <div class="sidebody" id="sideb"></div>
        </div>
      </div>`);
}

/* MapLibre + OpenFreeMap (OpenMapTiles schema, no API key). The vendored
   library is local; only the tiles need the network, and if they fail the
   markers still render over a plain background. */
let ML = null, MLMARKERS = [], MAPMODE = "co", PPMARKER = null, PPTIMER = null, PLTIMER = null;

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
  $("#sidet").textContent = title || "Exhibitors";
  $("#sides").textContent = `${points.length} shown`;
  $("#sideb").innerHTML = points.length ? points.slice(0, 60).map(p => `
    <div class="sideitem">
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
    </div>`).join("") : `<div class="msg" style="padding:26px">Nothing matches.</div>`;
}

function initMap() {
  const el = document.getElementById("mlmap");
  if (!el || !window.maplibregl || !MAP?.points) return;
  MLMARKERS = [];
  ML = new maplibregl.Map({
    container: "mlmap",
    style: "https://tiles.openfreemap.org/styles/liberty",
    center: FLY.eu.center, zoom: FLY.eu.zoom, attributionControl: true,
  });
  ML.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

  // A precisely geocoded entity sits on its real address and is never moved.
  // Only city-centroid fallbacks are spread, and they are drawn hollow so the
  // map never implies a precision it does not have.
  const layer = MAPMODE === "fu" ? (MAP.funds || [])
              : MAPMODE === "pf" ? (MAP.portfolio || [])
              : MAP.points;
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
    d.className = "mkr";
    const isFund = p.kind === "fund";
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
  sideList(layer, MAPMODE === "fu" ? "Funds"
                : MAPMODE === "pf" ? "Funded companies" : "Slush exhibitors");
  const pn = $("#precisenote");
  if (pn && MAP.exact != null)
    pn.innerHTML = `<i style="background:transparent;border:2px dashed #9b958c"></i>city only (${MAP.placed - MAP.exact})`;

  document.querySelectorAll("[data-fly]").forEach(b => b.onclick = () => {
    const f = FLY[b.dataset.fly]; ML.flyTo({ center: f.center, zoom: f.zoom, duration: 700 });
  });
  document.querySelectorAll("[data-mm]").forEach(b => b.onclick = () => {
    MAPMODE = b.dataset.mm; render();
  });

  const q = $("#mapq");
  if (!q) return;
  q.oninput = MAPMODE === "pp" ? peopleSearch : () => {
    const t = q.value.trim().toLowerCase();
    const active = MAPMODE === "fu" ? (MAP.funds || [])
                 : MAPMODE === "pf" ? (MAP.portfolio || []) : MAP.points;
    const shown = [];
    for (const { el, p } of MLMARKERS) {
      const hit = !t || p.name.toLowerCase().includes(t) ||
        (p.hq || "").toLowerCase().includes(t) ||
        (p.industries || []).join(" ").toLowerCase().includes(t);
      el.style.display = hit ? "" : "none";
      if (hit) shown.push(p);
    }
    sideList(shown, t ? `Matching "${q.value.trim()}"`
      : MAPMODE === "fu" ? "Funds" : MAPMODE === "pf" ? "Funded companies" : "Slush exhibitors");
    clearTimeout(PLTIMER);
    if (!t) { fitTo(active); return; }
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
    $("#sides").textContent = "Cala holds no address on a person — we locate them through the company they work at";
    $("#sideb").innerHTML = `<div class="msg" style="padding:26px">
      Type a founder or investor name.</div>`;
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
    $("#sides").textContent = `${d.results.length} found · click to place on the map`;
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

  return stats(4, [
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

function homeView() {
  return `<div class="home">
    <div class="homehd"><span class="sq">F</span><h1>What are you looking at today?</h1></div>
    <div class="ask">
      <textarea id="askbox" rows="2" placeholder="A company you're raising for, a fund you're meeting, or just ask — try &quot;Gosta Labs&quot;"></textarea>
      <div class="askfoot">
        <button class="send" id="asksend" title="Run">↑</button>
      </div>
    </div>
    <div class="chips">${CHIPS.map(([ic, label, q]) =>
      `<button class="chip" data-q="${esc(q)}"><span class="ic">${ic}</span>${esc(label)}</button>`).join("")}</div>
  </div>`;
}

/* Route free text. Keywords first, otherwise treat it as a company name. */
function routeAsk(text) {
  const q = (text || "").trim();
  if (!q) return;
  const low = q.toLowerCase();
  if (/\b(map|slush floor|where|location|geograph)/.test(low)) { MODE = "map"; SEL = null; return MAP ? render() : loadMap(); }
  if (/\b(accur|backtest|valid|proof|evidence|work\b)/.test(low)) { MODE = "accuracy"; SEL = null; return BT ? render() : loadBacktest(); }
  if (/\b(conviction|insider|double|doubling|orphan|deal ?flow|silent|unannounced|raising)/.test(low)) { MODE = "investor"; SEL = null; return I ? render() : loadInvestor(); }
  MODE = "founder"; SEL = null;
  PENDING_CO = q;                     // picked up by runFounder
  render();
  runFounder();
}
let PENDING_CO = null;

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
render();

/* ================= ENTITY CARD (person / fund) ================= */
let ENT = null, ENTLOAD = null;

async function loadEntity(id, kind, name) {
  MODE = "entity"; SEL = null; TAB = 0;
  ENTLOAD = { id, kind, name };
  ENT = null; render();
  try {
    ENT = await (await fetch(`/entity/${id}?kind=${kind}`)).json();
  } catch (e) { ENT = { error: String(e.message) }; }
  render();
}

const RANKCLS = { FILING: "b-green", PRIMARY: "b-blue", PRESS: "b-amber", AGGREGATOR: "b-grey" };
const rankChip = r => r ? `<span class="bdg ${RANKCLS[r] || "b-grey"}"
  style="font-size:9.5px;letter-spacing:.05em">${esc(r)}</span>` : "";

function entityView() {
  if (!ENT) return `<div class="msg"><span class="spin"></span>Opening ${esc(ENTLOAD?.name || "profile")}…</div>`;
  if (ENT.error) return `<div class="msg">Could not open this profile.<br>
    <span style="color:var(--dim)">${esc(ENT.error)}</span></div>`;

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
  const statRow = isPerson
    ? [["Roles", (counts.IS_CEO_OF || 0) + (counts.WORKS_AT || 0)],
       ["Founded", counts.FOUNDED || 0],
       ["Investments", counts.INVESTED_IN || 0],
       ["Rounds on record", counts.PARTICIPATES_IN_FUNDING_ROUND || 0],
       ["Boards", counts.IS_MEMBER_OF || 0]]
    : [["Investments", counts.INVESTED_IN || 0],
       ["Rounds on record", counts.PARTICIPATES_IN_FUNDING_ROUND || 0],
       ["Industries", counts.OPERATES_IN_INDUSTRY || 0],
       ["Events", counts.PARTICIPATES_IN_EVENT || 0],
       ["Employees", val("employee_count") ?? "—"]];

  let body = `<div class="ehd"><div class="ehdtop">
      ${bigLogo(ENT.name, val("website"))}
      <div style="min-width:0"><h1>${esc(ENT.name)}</h1><div class="emeta">${meta}</div></div>
      <span class="eacts">
        <button class="btn" id="composeit">Compose intro</button>
        ${isPerson ? "" : `<button class="btn" id="screenit">Screen this fund</button>`}
        <button class="btn" onclick="window.print()">Export</button></span>
    </div><div class="tabs">
      <button class="tab ${TAB === 0 ? "on" : ""}" data-tab="0">Profile</button>
      ${isPerson ? `<button class="tab ${TAB === 1 ? "on" : ""}" data-tab="1">Founder signal</button>` : ""}
      </div></div><div class="tabbody">`;

  if (isPerson && TAB === 1) return body + founderSignalTab() + "</div>";

  if (val("description"))
    body += `<p class="lede">${esc(val("description"))}
      ${src("description") ? `<a href="${esc(src("description"))}" target="_blank"
        rel="noopener" style="font-size:12px"> source</a>` : ""}</p>`;

  body += stats(5, statRow.map(([k, v]) => [k, v, "mono"]));

  for (const g of ENT.groups || []) {
    body += section("ent-" + g.rel, g.label, `${g.items.length} on record`,
      `<div class="hl">${g.items.map(it => `<div class="hlc">
        <div class="hlhd">${logo(it.name)}
          <div style="min-width:0"><div class="nm">${esc(it.name)}</div>
            <div class="sb">${esc(it.role || it.type || "")}</div></div>
          ${rankChip(it.rank)}</div>
        ${it.source ? `<div class="ev" style="margin-top:4px"><div>
          <a href="${esc(it.source)}" target="_blank" rel="noopener">${
            esc(String(it.source).replace(/^https?:\/\/(www\.)?/, "").slice(0, 46))}</a></div></div>` : ""}
      </div>`).join("")}</div>`);
  }

  if (!(ENT.groups || []).length)
    body += `<div class="msg">Cala holds this entity but no connections we surface here.
      Unknown is not zero.</div>`;

  return body + "</div>";
}


/* ================= COMPOSE ================= */
/* Drafts an approach grounded in what the graph actually says, then hands it
   to the user's own mail client. Nothing is sent from here: the message goes
   out from their account, after they have read it. */
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
      <div class="s">Opens in your own mail client — nothing is sent from Flipside</div></div>
    <div style="padding:15px">
      <div class="fld" style="margin-bottom:11px"><label>To</label>
        <input id="cto" placeholder="name@fund.com" style="width:100%"></div>
      <div class="fld" style="margin-bottom:11px"><label>Subject</label>
        <input id="csub" value="${esc(d.subject)}" style="width:100%"></div>
      <div class="fld"><label>Message</label>
        <textarea id="cbody" rows="11" style="width:100%;border:1px solid var(--line2);
          border-radius:8px;padding:11px">${esc(d.body)}</textarea></div>
      <div style="display:flex;gap:8px;margin-top:13px">
        <button class="btn pri" id="cmail">Open in mail client</button>
        <button class="btn" id="ccopy">Copy</button>
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
    location.href = `mailto:${encodeURIComponent(to)}?subject=${
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
  if (!FSIG) return `<div class="msg"><span class="spin"></span>Reading the graph…</div>`;
  if (FSIG.error) return `<div class="msg">${esc(FSIG.error)}</div>`;

  const f = FSIG, gh = f.github, comps = (f.components || []).filter(c => c.counted);
  const uncounted = (f.components || []).filter(c => !c.counted);

  if (f.score === null) return `<div class="verdict grey">
    <b>Not enough to read.</b> ${esc((f.reasons || [])[0] || "")}</div>`;

  const max = Math.max(...comps.map(c => c.contribution), 1);
  return stats(4, [
    ["Founder signal", f.score, "mono"],
    ["Confidence", f.confidence],
    ["Connections read", f.evidence_edges, "mono"],
    ["Ships code publicly", gh ? (f.github_signal?.label || "yes") : "unknown"],
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
    : section("fs-gh", "GitHub", "", `<div class="card"><div class="sub">${
        esc(f.github_error || "No GitHub account matched this name with enough confidence to attribute.")}
        </div><div style="font-size:12.8px;color:var(--dim);margin-top:7px">
        A same-name account is not evidence — we decline rather than credit someone
        else's work.</div></div>`))
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
