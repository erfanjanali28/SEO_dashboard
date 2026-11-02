/* SEO Dashboard SPA: hash routing, client/site management, audit views, charts. */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const app = $("#app");
const charts = [];
const C = { navy: "#1e3a5f", gold: "#b8860b", green: "#2d6a4f", amber: "#d4740e", red: "#c53030", slate: "#5a7fa8", plum: "#7b6d8d", teal: "#3d8b8b" };
const PALETTE = [C.navy, C.gold, C.green, C.amber, C.red, C.slate, C.plum, C.teal];
const SEV = { critical: C.red, high: C.amber, medium: C.gold, low: C.green };

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function safeUrl(u) { return /^https?:\/\//i.test(u || "") ? u : "#"; }
function link(u, text) { return u ? `<a href="${esc(safeUrl(u))}" target="_blank" rel="noopener noreferrer">${esc(text || u)}</a>` : ""; }
function shortUrl(u) { try { const p = new URL(u); return p.pathname + p.search || "/"; } catch { return u || ""; } }
function scoreClass(s) { return s == null ? "s-none" : s >= 80 ? "s-good" : s >= 55 ? "s-mid" : "s-bad"; }
function badge(s) { return `<span class="score-badge ${scoreClass(s)}">${s ?? "–"}</span>`; }
function sev(s) { return `<span class="pill sev-${esc(s)}">${esc(s)}</span>`; }
function initials(n) { return esc((n || "?").split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase()); }
function avatar(c, lg) {
  return c.photo ? `<img class="avatar ${lg ? "lg" : ""}" src="/uploads/${esc(c.photo)}" alt="${esc(c.name)}">`
    : `<div class="avatar ${lg ? "lg" : ""}">${initials(c.name)}</div>`;
}
function fmtDate(s) { return s ? new Date(s).toLocaleString() : "never"; }
function toast(msg, ms = 3500) { const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), ms); }

async function api(path, opts = {}) {
  const o = { ...opts, headers: { ...(opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}), ...(opts.headers || {}) } };
  if (o.body && !(o.body instanceof FormData) && typeof o.body !== "string") o.body = JSON.stringify(o.body);
  const r = await fetch(path, o);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = j.detail || msg; } catch {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

function modal(html) { $("#modal-box").innerHTML = html; $("#modal").classList.remove("hidden"); }
function closeModal() { $("#modal").classList.add("hidden"); }
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

function destroyCharts() { while (charts.length) charts.pop().destroy(); }
function chart(id, cfg) {
  const el = document.getElementById(id);
  if (!el || !window.Chart) return;
  const textColor = getComputedStyle(document.documentElement).getPropertyValue("--muted").trim() || "#666";
  Chart.defaults.color = textColor;
  if (cfg.type === "line") cfg.data.datasets.forEach((d) => { d.pointRadius = d.pointRadius ?? (d.data.length > 30 ? 0 : 3); d.borderWidth = 2; });
  cfg.options = Object.assign({ responsive: true, maintainAspectRatio: false, plugins: { legend: { display: cfg.type === "doughnut" || cfg.type === "pie" || (cfg.data.datasets || []).length > 1 } } }, cfg.options || {});
  charts.push(new Chart(el, cfg));
}
function barCfg(labels, data, label, color = C.navy, horizontal = false, max) {
  return { type: "bar", data: { labels, datasets: [{ label, data, backgroundColor: Array.isArray(color) ? color : color, borderRadius: 4 }] },
    options: { indexAxis: horizontal ? "y" : "x", scales: { [horizontal ? "x" : "y"]: { beginAtZero: true, ...(max ? { max } : {}) } } } };
}
function donutCfg(obj, colors) {
  const labels = Object.keys(obj);
  return { type: "doughnut", data: { labels, datasets: [{ data: labels.map((k) => obj[k]), backgroundColor: labels.map((k, i) => (colors && colors[k]) || PALETTE[i % PALETTE.length]) }] },
    options: { cutout: "58%", plugins: { legend: { position: "right" } } } };
}

/* Generic sortable / filterable table */
function dataTable(id, rows, cols, opts = {}) {
  const state = { q: "", sort: null, dir: 1, limit: opts.limit || 200 };
  const host = document.getElementById(id);
  if (!host) return;
  function render() {
    let r = rows;
    if (state.q) { const q = state.q.toLowerCase(); r = r.filter((x) => cols.some((c) => String(x[c.key] ?? "").toLowerCase().includes(q))); }
    if (state.sort) r = [...r].sort((a, b) => { const x = a[state.sort], y = b[state.sort]; return (x > y ? 1 : x < y ? -1 : 0) * state.dir; });
    const head = cols.map((c) => `<th data-k="${c.key}">${esc(c.label)}${state.sort === c.key ? (state.dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("");
    const body = r.slice(0, state.limit).map((x) => "<tr>" + cols.map((c) => `<td>${c.render ? c.render(x[c.key], x) : esc(Array.isArray(x[c.key]) ? x[c.key].join(", ") : x[c.key])}</td>`).join("") + "</tr>").join("");
    host.innerHTML = `${opts.noFilter ? "" : `<input class="filter" placeholder="Filter ${rows.length} rows…" value="${esc(state.q)}">`}
      <div class="table-wrap"><table class="data"><thead><tr>${head}</tr></thead><tbody>${body || `<tr><td colspan="${cols.length}" class="muted">No items</td></tr>`}</tbody></table></div>
      ${r.length > state.limit ? `<p class="muted small">Showing ${state.limit} of ${r.length}. <a href="#" data-more>Show more</a>. Export to Excel for the full list.</p>` : ""}`;
    const f = $("input.filter", host);
    if (f) { f.oninput = (e) => { state.q = e.target.value; render(); const n = $("input.filter", host); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }; }
    host.querySelectorAll("th").forEach((th) => th.onclick = () => { const k = th.dataset.k; state.dir = state.sort === k ? -state.dir : 1; state.sort = k; render(); });
    const more = $("[data-more]", host); if (more) more.onclick = (e) => { e.preventDefault(); state.limit += 500; render(); };
  }
  render();
}
const urlCol = (key = "url", label = "URL") => ({ key, label, render: (v) => link(v, shortUrl(v)) });

/* ---------------- Router ---------------- */
let pollTimer = null;
async function route() {
  clearInterval(pollTimer);
  destroyCharts();
  closeModal();
  const h = location.hash.replace(/^#/, "") || "/";
  const m = h.match(/^\/(client|site)\/(\d+)(?:\/(\w+))?/);
  try {
    if (h === "/settings") await viewSettings();
    else if (m && m[1] === "client") await viewClient(+m[2]);
    else if (m && m[1] === "site") await viewSite(+m[2], m[3] || "overview");
    else await viewClients();
  } catch (e) { app.innerHTML = `<div class="card"><h2>Error</h2><p>${esc(e.message)}</p></div>`; }
}
window.addEventListener("hashchange", route);

/* ---------------- Clients ---------------- */
async function viewClients() {
  const clients = await api("/api/clients");
  const sites = clients.flatMap((c) => c.sites);
  const scored = sites.filter((s) => s.score != null);
  app.innerHTML = `
    <div class="row space"><h1>Clients</h1><button class="btn gold" id="add-client">+ Add client</button></div>
    <div class="grid g4" style="margin:12px 0 18px">
      <div class="card kpi"><div class="l">Clients</div><div class="v">${clients.length}</div></div>
      <div class="card kpi"><div class="l">Websites</div><div class="v">${sites.length}</div></div>
      <div class="card kpi"><div class="l">Average score</div><div class="v">${scored.length ? Math.round(scored.reduce((a, s) => a + s.score, 0) / scored.length) : "–"}</div></div>
      <div class="card kpi"><div class="l">Scheduled</div><div class="v">${sites.filter((s) => s.interval_hours > 0).length}</div></div>
    </div>
    <div class="grid cards">${clients.map((c) => `
      <div class="card client-card" data-id="${c.id}">${avatar(c)}
        <div style="min-width:0"><h3 style="margin:0">${esc(c.name)}</h3><div class="muted small">${esc(c.company || "")} ${c.industry ? "· " + esc(c.industry) : ""}</div>
        <div class="small" style="margin-top:6px">${c.sites.map((s) => `${badge(s.score)} ${esc(shortHost(s.url))}`).join("<br>") || '<span class="muted">No websites yet</span>'}</div></div>
      </div>`).join("") || '<div class="card"><p>No clients yet. Add your first client to get started.</p></div>'}</div>`;
  document.querySelectorAll(".client-card").forEach((el) => el.onclick = () => location.hash = `#/client/${el.dataset.id}`);
  $("#add-client").onclick = () => clientForm();
}
function shortHost(u) { try { return new URL(u).host; } catch { return u; } }

function clientForm(c = {}) {
  modal(`<h2>${c.id ? "Edit" : "Add"} client</h2>
    <form id="cf"><label>Name *</label><input name="name" required value="${esc(c.name)}">
    <label>Company</label><input name="company" value="${esc(c.company)}">
    <label>Email</label><input name="email" type="email" value="${esc(c.email)}">
    <label>Industry / niche</label><input name="industry" value="${esc(c.industry)}" placeholder="e.g. home services, saas, ecommerce, legal">
    <label>Notes</label><textarea name="notes" rows="3">${esc(c.notes)}</textarea>
    <label>Photo / logo (PNG, JPG, GIF, WebP · max 5 MB)</label><input name="photo" type="file" accept="image/*">
    <div class="row" style="margin-top:16px"><button class="btn" type="submit">Save</button><button class="btn secondary" type="button" onclick="closeModal()">Cancel</button></div></form>`);
  $("#cf").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = Object.fromEntries([...fd.entries()].filter(([k]) => k !== "photo"));
    try {
      const saved = c.id ? await api(`/api/clients/${c.id}`, { method: "PUT", body }) : await api("/api/clients", { method: "POST", body });
      const file = fd.get("photo");
      if (file && file.size) { const up = new FormData(); up.append("file", file); await api(`/api/clients/${saved.id}/photo`, { method: "POST", body: up }); }
      closeModal(); location.hash = `#/client/${saved.id}`; route();
    } catch (err) { toast(err.message); }
  };
}

async function viewClient(id) {
  const c = await api(`/api/clients/${id}`);
  app.innerHTML = `
    <div class="card row">${avatar(c, true)}<div style="flex:1;min-width:200px"><h1>${esc(c.name)}</h1>
      <div class="muted">${esc(c.company || "")} ${c.email ? "· " + esc(c.email) : ""} ${c.industry ? "· " + esc(c.industry) : ""}</div><p>${esc(c.notes || "")}</p></div>
      <div class="row"><button class="btn secondary" id="edit">Edit / change photo</button><button class="btn danger" id="del">Delete</button></div></div>
    <div class="row space"><h2>Websites</h2><button class="btn gold" id="add-site">+ Add website</button></div>
    <div class="grid g2">${c.sites.map((s) => `
      <div class="card"><div class="row space"><h3 style="margin:0">${link(s.url, shortHost(s.url))}</h3>${badge(s.latest && s.latest.score)}</div>
      <p class="muted small">Schedule: ${s.interval_hours ? `every ${intervalLabel(s.interval_hours)}` : "manual"} · Last run: ${fmtDate(s.last_run_at)} · Max pages: ${s.max_pages}</p>
      <p class="small">${s.latest ? `Latest audit: ${esc(s.latest.status)} ${s.latest.status === "running" ? "(" + esc(s.latest.progress) + ")" : ""}` : "No audits yet"}</p>
      <div class="row"><a class="btn" href="#/site/${s.id}">Open dashboard</a><button class="btn secondary" data-run="${s.id}">Run audit now</button></div></div>`).join("") || '<div class="card">No websites yet.</div>'}</div>`;
  $("#edit").onclick = () => clientForm(c);
  $("#del").onclick = async () => { if (confirm(`Delete ${c.name} and all their websites and audits?`)) { await api(`/api/clients/${id}`, { method: "DELETE" }); location.hash = "#/"; } };
  $("#add-site").onclick = () => siteForm({ client_id: id, industry: c.industry });
  document.querySelectorAll("[data-run]").forEach((b) => b.onclick = async () => { await api(`/api/sites/${b.dataset.run}/audit`, { method: "POST" }); location.hash = `#/site/${b.dataset.run}`; });
}
function intervalLabel(h) { return h % 720 === 0 ? `${h / 720} month(s)` : h % 168 === 0 ? `${h / 168} week(s)` : h % 24 === 0 ? `${h / 24} day(s)` : `${h} hour(s)`; }

function siteForm(s = {}) {
  const presets = [[0, "Manual only"], [6, "Every 6 hours"], [24, "Daily"], [72, "Every 3 days"], [168, "Weekly"], [336, "Every 2 weeks"], [720, "Monthly"]];
  const custom = s.interval_hours && !presets.some(([v]) => v === s.interval_hours);
  modal(`<h2>${s.id ? "Edit" : "Add"} website</h2><form id="sf">
    <label>Domain or URL *</label><input name="url" required value="${esc(s.url)}" placeholder="example.com">
    <div class="grid g2"><div><label>Industry / niche (drives keyword research)</label><input name="industry" value="${esc(s.industry)}" placeholder="saas, ecommerce, local, legal, healthcare…"></div>
    <div><label>Location (for local keywords)</label><input name="location" value="${esc(s.location)}" placeholder="Austin"></div></div>
    <label>Seed keywords (comma-separated)</label><input name="seed_keywords" value="${esc(s.seed_keywords)}" placeholder="emergency plumber, drain cleaning">
    <label>Competitor domains (comma-separated)</label><input name="competitors" value="${esc(s.competitors)}">
    <div class="grid g2"><div><label>Audit interval</label><select name="interval_preset">${presets.map(([v, l]) => `<option value="${v}" ${s.interval_hours === v ? "selected" : ""}>${l}</option>`).join("")}<option value="custom" ${custom ? "selected" : ""}>Custom (hours)…</option></select></div>
    <div><label>Custom interval (hours)</label><input name="interval_custom" type="number" min="1" value="${custom ? s.interval_hours : ""}"></div></div>
    <div class="grid g2"><div><label>Max pages per crawl</label><input name="max_pages" type="number" min="5" max="2000" value="${s.max_pages || 150}"></div>
    <div><label>Language</label><input name="language" value="${esc(s.language || "en")}"></div></div>
    <div class="grid g2"><div><label>Windsor.ai GSC account (optional)</label><input name="windsor_gsc_account" value="${esc(s.windsor_gsc_account)}" placeholder="sc-domain:example.com"></div>
    <div><label>Windsor.ai GA4 account (optional)</label><input name="windsor_ga4_account" value="${esc(s.windsor_ga4_account)}" placeholder="properties/123456"></div></div>
    <div class="row" style="margin-top:16px"><button class="btn" type="submit">Save</button><button class="btn secondary" type="button" onclick="closeModal()">Cancel</button></div></form>`);
  $("#sf").onsubmit = async (e) => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target).entries());
    const interval = d.interval_preset === "custom" ? parseInt(d.interval_custom || "0", 10) : parseInt(d.interval_preset, 10);
    const body = { client_id: s.client_id, url: d.url, industry: d.industry, location: d.location, seed_keywords: d.seed_keywords, competitors: d.competitors,
      interval_hours: interval || 0, max_pages: parseInt(d.max_pages, 10) || 150, language: d.language || "en",
      windsor_gsc_account: d.windsor_gsc_account, windsor_ga4_account: d.windsor_ga4_account };
    try {
      const saved = s.id ? await api(`/api/sites/${s.id}`, { method: "PUT", body }) : await api("/api/sites", { method: "POST", body });
      closeModal();
      if (!s.id && confirm("Website saved. Run the first audit now?")) { await api(`/api/sites/${saved.id}/audit`, { method: "POST" }); location.hash = `#/site/${saved.id}`; }
      else route();
    } catch (err) { toast(err.message); }
  };
}

/* ---------------- Settings ---------------- */
async function viewSettings() {
  const s = await api("/api/settings");
  app.innerHTML = `<h1>Settings</h1><form id="set" class="grid g2">
    <div class="card"><h2>Google Search Console + GA4 via Windsor.ai</h2>
      <p class="muted small">Connect your Google accounts at windsor.ai (connectors: Search Console, Google Analytics 4), copy your API key from the Windsor.ai dashboard, and paste it here. Every site's "Sync GSC/GA4" button and each scheduled audit then pull clicks, impressions, positions, sessions and key events automatically.</p>
      <label>Windsor.ai API key</label><input name="windsor_api_key" value="${esc(s.windsor_api_key || "")}" autocomplete="off"></div>
    <div class="card"><h2>Core Web Vitals (PageSpeed Insights)</h2>
      <p class="muted small">Optional Google API key with the PageSpeed Insights API enabled. It raises the quota. Without a key, PSI still works at a low rate.</p>
      <label>PageSpeed API key</label><input name="pagespeed_api_key" value="${esc(s.pagespeed_api_key || "")}" autocomplete="off">
      <label>Run PSI during audits</label><select name="pagespeed_enabled"><option value="1" ${s.pagespeed_enabled !== "0" ? "selected" : ""}>Yes</option><option value="0" ${s.pagespeed_enabled === "0" ? "selected" : ""}>No</option></select></div>
    <div class="card"><h2>Keyword volumes (DataForSEO, optional)</h2>
      <p class="muted small">Adds Google Ads search volume, CPC and competition to the keyword research.</p>
      <label>Login</label><input name="dataforseo_login" value="${esc(s.dataforseo_login || "")}">
      <label>Password</label><input name="dataforseo_password" type="password" value="${esc(s.dataforseo_password || "")}">
      <label>Location code (2840 = US, 2826 = UK, 2124 = CA, 2036 = AU)</label><input name="dataforseo_location_code" value="${esc(s.dataforseo_location_code || "")}"></div>
    <div class="card"><h2>Appearance</h2><label>Theme</label><select id="theme"><option value="">System</option><option value="light">Light</option><option value="dark">Dark</option></select>
      <div style="margin-top:18px"><button class="btn" type="submit">Save settings</button></div></div></form>`;
  let theme = ""; try { theme = localStorage.getItem("theme") || ""; } catch {}
  $("#theme").value = theme;
  $("#theme").onchange = (e) => { applyTheme(e.target.value); try { localStorage.setItem("theme", e.target.value); } catch {} };
  $("#set").onsubmit = async (e) => { e.preventDefault(); await api("/api/settings", { method: "PUT", body: Object.fromEntries(new FormData(e.target).entries()) }); toast("Settings saved"); route(); };
}
function applyTheme(t) { if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; }
try { applyTheme(localStorage.getItem("theme") || ""); } catch {}

/* ---------------- Site dashboard ---------------- */
const TABS = [["overview", "Overview"], ["priorities", "Top 10 & Roadmap"], ["technical", "Technical"], ["onpage", "On-page & Meta"], ["content", "Content"],
  ["links", "Internal Links"], ["structure", "URL Structure"], ["schema", "Schema"], ["performance", "Core Web Vitals"], ["keywords", "Keyword Research"],
  ["search", "Rankings & Traffic"], ["geo", "AIO / GEO"], ["conversion", "Lead Gen & Tracking"], ["offpage", "Off-page"], ["crawl", "Crawl Data"]];

async function viewSite(id, tab) {
  const s = await api(`/api/sites/${id}`);
  const c = s.client;
  const running = s.latest && s.latest.status === "running";
  const doneId = s.latest_done && s.latest_done.id;
  app.innerHTML = `
    <div class="card row">${avatar(c)}<div style="flex:1;min-width:220px"><div class="muted small"><a href="#/client/${c.id}">${esc(c.name)}</a></div>
      <h1 style="margin:2px 0">${link(s.url, shortHost(s.url))}</h1>
      <div class="muted small">${esc(s.industry || "general")} ${s.location ? "· " + esc(s.location) : ""} · Schedule: ${s.interval_hours ? "every " + intervalLabel(s.interval_hours) : "manual"} · Last run: ${fmtDate(s.last_run_at)}</div></div>
      <div class="row"><button class="btn gold" id="run" ${running ? "disabled" : ""}>${running ? "Audit running…" : "Run audit"}</button>
      <button class="btn secondary" id="sync">Sync GSC/GA4</button><button class="btn secondary" id="edit-site">Settings / schedule</button></div></div>
    ${running ? `<div class="card" style="margin-top:12px"><b>Audit in progress:</b> <span id="prog">${esc(s.latest.progress)}</span><div class="progress"><div></div></div></div>` : ""}
    ${s.latest && s.latest.status === "error" ? `<div class="card" style="margin-top:12px;border-color:var(--red)"><b class="bad">Last audit failed:</b><pre>${esc((s.latest.error || "").slice(0, 600))}</pre></div>` : ""}
    ${doneId ? `<div class="export-bar" style="margin-top:12px">
      <a class="btn" href="/api/audits/${doneId}/export.xlsx">⬇ Full report (Excel)</a>
      <a class="btn" href="/api/audits/${doneId}/internal-links.xlsx">⬇ Internal links (Excel)</a>
      <a class="btn secondary" href="/api/audits/${doneId}/report.html" target="_blank" rel="noopener">Printable report / PDF</a>
      <a class="btn secondary" href="/api/audits/${doneId}/report.html?download=1">⬇ HTML report</a></div>` : ""}
    <div class="tabs">${TABS.map(([k, l]) => `<button class="tab ${k === tab ? "active" : ""}" data-tab="${k}">${l}</button>`).join("")}</div>
    <div id="tab-body"></div>`;
  document.querySelectorAll(".tab").forEach((b) => b.onclick = () => location.hash = `#/site/${id}/${b.dataset.tab}`);
  $("#run").onclick = async () => { await api(`/api/sites/${id}/audit`, { method: "POST" }); route(); };
  $("#sync").onclick = async () => {
    toast("Syncing Search Console and GA4 from Windsor.ai…", 8000);
    try { const r = await api(`/api/sites/${id}/sync`, { method: "POST" }); toast(`Synced ${r.gsc_rows} GSC rows and ${r.ga4_rows} GA4 rows. ${r.errors.join(" ")}`, 8000); if (tab === "search") route(); }
    catch (e) { toast(e.message, 8000); }
  };
  $("#edit-site").onclick = () => siteForm(s);
  if (running) {
    pollTimer = setInterval(async () => {
      const a = await api(`/api/audits/${s.latest.id}`);
      const p = $("#prog"); if (p) p.textContent = a.progress;
      if (a.status !== "running") { clearInterval(pollTimer); toast(a.status === "done" ? "Audit complete" : "Audit failed"); route(); }
    }, 2500);
  }
  const body = $("#tab-body");
  if (tab === "search") return renderSearch(body, id);
  if (!doneId) { body.innerHTML = `<div class="card"><p>No completed audit yet. ${running ? "Results appear here as soon as the crawl finishes." : "Click <b>Run audit</b> to crawl the site."}</p></div>`; return; }
  const r = await api(`/api/audits/${doneId}/result`);
  const renderers = { overview: renderOverview, priorities: renderPriorities, technical: renderTechnical, onpage: renderOnpage, content: renderContent,
    links: renderLinks, structure: renderStructure, schema: renderSchema, performance: renderPerformance, keywords: renderKeywords, geo: renderGeo,
    conversion: renderConversion, offpage: renderOffpage, crawl: renderCrawl };
  (renderers[tab] || renderOverview)(body, r, s);
}

function issueList(issues) {
  return issues.map((i) => `<details class="issue ${esc(i.severity)}"><summary>${sev(i.severity)} ${esc(i.title)} <span class="muted">· ${esc(i.category)} · ${i.count} affected</span></summary>
    <p>${esc(i.description)}</p><p><b>Recommendation:</b> ${esc(i.recommendation)}</p>
    ${i.urls.length ? `<div class="urls">${i.urls.slice(0, 100).map((u) => link(u, shortUrl(u))).join("<br>")}${i.urls.length > 100 ? `<br>… ${i.urls.length - 100} more` : ""}</div>` : ""}
    ${i.details ? `<details><summary class="small">Details (${i.details.length})</summary><pre>${esc(JSON.stringify(i.details.slice(0, 40), null, 1))}</pre></details>` : ""}</details>`).join("") || '<p class="ok">No issues found in this area.</p>';
}
const byCat = (r, cats) => r.issues.filter((i) => cats.includes(i.category));

async function renderOverview(el, r, s) {
  const sc = r.scores;
  const sevc = { critical: 0, high: 0, medium: 0, low: 0 };
  r.issues.forEach((i) => sevc[i.severity]++);
  const changes = await api(`/api/sites/${s.id}/changes`).catch(() => ({ available: false }));
  el.innerHTML = `
    <div class="grid g4">
      <div class="card kpi"><div class="l">Overall score</div><div class="v">${badge(sc.overall)}</div>${changes.available ? `<div class="small ${changes.score_change >= 0 ? "ok" : "bad"}">${changes.score_change >= 0 ? "▲" : "▼"} ${Math.abs(changes.score_change)} vs previous audit</div>` : ""}</div>
      <div class="card kpi"><div class="l">URLs crawled</div><div class="v">${r.meta.pages_crawled}</div><div class="small muted">${r.technical.indexable} indexable</div></div>
      <div class="card kpi"><div class="l">Critical / high issues</div><div class="v">${sevc.critical} / ${sevc.high}</div></div>
      <div class="card kpi"><div class="l">404 URLs</div><div class="v">${r.technical.redirect_suggestions.length}</div></div>
      <div class="card kpi"><div class="l">Pages without schema</div><div class="v">${r.technical.schema_suggestions.length}</div></div>
      <div class="card kpi"><div class="l">Orphan pages</div><div class="v">${r.links.stats.orphans.length}</div></div>
      <div class="card kpi"><div class="l">Link suggestions</div><div class="v">${r.links.suggestions.length}</div></div>
      <div class="card kpi"><div class="l">AI answer readiness</div><div class="v">${r.geo.average}/100</div></div>
    </div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><h3>Score by category</h3><div class="chart-box"><canvas id="c-cat"></canvas></div></div>
      <div class="card"><h3>Issues by severity</h3><div class="chart-box"><canvas id="c-sev"></canvas></div></div>
      <div class="card"><h3>Score history</h3><div class="chart-box"><canvas id="c-hist"></canvas></div></div>
      <div class="card"><h3>HTTP status codes</h3><div class="chart-box"><canvas id="c-status"></canvas></div></div>
    </div>
    ${changes.available ? `<div class="card" style="margin-top:16px"><h3>Changes since the previous audit</h3><div class="grid g3">
      <div><b class="bad">New issues (${changes.new.length})</b><ul>${changes.new.map((i) => `<li>${sev(i.severity)} ${esc(i.title)}</li>`).join("")}</ul></div>
      <div><b class="ok">Resolved (${changes.resolved.length})</b><ul>${changes.resolved.map((i) => `<li>${esc(i.title)}</li>`).join("")}</ul></div>
      <div><b>Changed counts</b><ul>${changes.changed.map((i) => `<li>${esc(i.title)}: ${i.before} → ${i.after}</li>`).join("")}</ul></div></div></div>` : ""}
    <h2>Top 10 priority actions</h2>${topList(r.top10.slice(0, 5))}<p><a href="#/site/${s.id}/priorities">See all 10 and the 30/60/90-day roadmap →</a></p>`;
  const cats = Object.keys(sc.categories);
  chart("c-cat", barCfg(cats, cats.map((k) => sc.categories[k]), "Score", cats.map((k) => sc.categories[k] >= 80 ? C.green : sc.categories[k] >= 55 ? C.amber : C.red), true, 100));
  chart("c-sev", donutCfg(sevc, SEV));
  chart("c-hist", { type: "line", data: { labels: s.history.map((h) => h.started_at.slice(0, 10)), datasets: [{ label: "Score", data: s.history.map((h) => h.score), borderColor: C.navy, tension: .3, fill: false },
    { label: "Critical + high issues", data: s.history.map((h) => h.issues_critical + h.issues_high), borderColor: C.red, tension: .3, yAxisID: "y1" }] },
    options: { scales: { y: { min: 0, max: 100 }, y1: { position: "right", beginAtZero: true, grid: { drawOnChartArea: false } } } } });
  chart("c-status", donutCfg(r.technical.status_counts, { "2xx": C.green, "3xx": C.gold, "4xx": C.red, "5xx": "#7f1d1d", error: "#6b7280" }));
}

function topList(items) {
  return items.map((a) => `<div class="action"><div class="rank">${a.rank}</div><div><b>${esc(a.title)}</b> ${sev(a.severity)} <span class="muted small">${esc(a.category)} · ${a.affected} affected</span>
    <p class="small">${esc(a.why)}</p><p class="small"><b>How:</b> ${esc(a.how)}</p><p class="muted small">Owner: ${esc(a.owner)} · Effort: ${esc(a.effort)} · Impact: ${esc(a.impact)}</p></div></div>`).join("");
}

function renderPriorities(el, r) {
  el.innerHTML = `<h2>Top 10 priority actions</h2><div class="card"><div class="chart-box"><canvas id="c-top"></canvas></div></div><div style="margin-top:12px">${topList(r.top10)}</div>
    <h2>30/60/90-day implementation roadmap</h2><div class="grid g3">${r.roadmap.phases.map((p) => `<div class="card phase"><h3>${esc(p.name)}</h3><p class="muted small">${esc(p.goal)}</p>
      ${p.tasks.map((t) => `<div class="task"><b>${esc(t.task)}</b> ${sev(t.severity)}<div class="small">${esc(t.action)}</div><div class="muted small">Owner: ${esc(t.owner)}${t.affected ? ` · ${t.affected} affected` : ""}</div></div>`).join("")}</div>`).join("")}</div>
    <div class="card" style="margin-top:16px"><h3>KPIs to track</h3><ul>${r.roadmap.kpis.map((k) => `<li>${esc(k)}</li>`).join("")}</ul></div>`;
  chart("c-top", barCfg(r.top10.map((a) => `${a.rank}. ${a.title.slice(0, 40)}`), r.top10.map((a) => a.score), "Priority score", r.top10.map((a) => SEV[a.severity]), true));
}

function renderTechnical(el, r) {
  const t = r.technical;
  const cats = ["Status codes", "Redirects", "Indexability", "Crawlability", "Sitemaps", "JavaScript rendering", "Security", "Mobile", "International"];
  const issues = byCat(r, cats);
  const counts = {}; issues.forEach((i) => counts[i.category] = (counts[i.category] || 0) + i.count);
  el.innerHTML = `<div class="grid g2"><div class="card"><h3>Affected URLs by technical area</h3><div class="chart-box"><canvas id="c-ta"></canvas></div></div>
    <div class="card"><h3>Crawl files</h3>
      <div class="check"><span class="${r.robots.exists ? "ok" : "bad"}">${r.robots.exists ? "✓" : "✗"}</span> robots.txt ${r.robots.disallow_all ? '<b class="bad">blocks all</b>' : ""} ${link(r.robots.url, "view")}</div>
      <div class="check"><span class="${r.sitemaps.found ? "ok" : "bad"}">${r.sitemaps.found ? "✓" : "✗"}</span> XML sitemap: ${r.sitemaps.url_count} URLs in ${r.sitemaps.checked.filter((x) => x.type).length} file(s)</div>
      <div class="check"><span class="${r.llms_txt["llms.txt"].exists ? "ok" : "bad"}">${r.llms_txt["llms.txt"].exists ? "✓" : "✗"}</span> llms.txt ${r.llms_txt["llms-full.txt"].exists ? "+ llms-full.txt" : ""}</div>
      <div class="check"><span>⚙</span> Frameworks detected: ${esc(t.frameworks.join(", ") || "none")}</div>
      <div class="check"><span>⏱</span> Average server response: ${t.avg_response_ms} ms</div>
      <h3>AI crawler access</h3>${Object.entries(r.robots.ai_crawlers || {}).map(([b, v]) => `<span class="pill ${v === "allowed" ? "sev-low" : "sev-critical"}">${esc(b)}: ${esc(v)}</span> `).join("") || '<span class="muted">No robots.txt</span>'}
    </div></div>
    <h2>Issues</h2>${issueList(issues)}
    <h2>404 pages and suggested 301 redirects</h2><div id="t-301"></div>
    <h2>Broken links</h2><div id="t-broken"></div>
    <h2>Internal links that point to redirects</h2><div id="t-l2r"></div>`;
  chart("c-ta", barCfg(Object.keys(counts), Object.values(counts), "Affected URLs", C.red, true));
  dataTable("t-301", t.redirect_suggestions, [urlCol("from", "404 URL"), { key: "status", label: "Status" }, urlCol("to", "Suggested 301 target"), { key: "confidence", label: "Confidence" }, { key: "linked_from", label: "Linked from", render: (v) => (v || []).slice(0, 5).map((u) => link(u, shortUrl(u))).join("<br>") }]);
  dataTable("t-broken", t.broken_links, [urlCol("source", "Source"), urlCol("target", "Broken target"), { key: "status", label: "Status" }, { key: "anchor", label: "Anchor" }, { key: "internal", label: "Internal" }]);
  dataTable("t-l2r", t.links_to_redirects, [urlCol("source", "Source"), urlCol("target", "Linked URL"), urlCol("final", "Update to"), { key: "anchor", label: "Anchor" }]);
}

function renderOnpage(el, r) {
  const issues = byCat(r, ["On-page", "Content structure", "Images"]);
  el.innerHTML = `<div class="card"><h3>On-page issues (affected URLs)</h3><div class="chart-box"><canvas id="c-op"></canvas></div></div>
    <h2>Keyword and meta tag suggestions</h2><p class="muted">For each page: the target keyword, its secondary keywords, and rewritten title and description.</p><div id="t-meta"></div>
    <h2>Issues</h2>${issueList(issues)}`;
  chart("c-op", barCfg(issues.map((i) => i.title), issues.map((i) => i.count), "URLs", issues.map((i) => SEV[i.severity]), true));
  dataTable("t-meta", r.meta_suggestions, [urlCol("source_url", "Source URL"), { key: "target_keyword", label: "Target keyword" }, { key: "current_title", label: "Current title" },
    { key: "suggested_title", label: "Suggested title", render: (v) => `<b>${esc(v)}</b> <span class="muted small">(${(v || "").length})</span>` },
    { key: "current_description", label: "Current description" }, { key: "suggested_description", label: "Suggested description", render: (v) => `<b>${esc(v)}</b> <span class="muted small">(${(v || "").length})</span>` },
    { key: "secondary_keywords", label: "Secondary keywords" }, { key: "reasons", label: "Why" }]);
}

function renderContent(el, r) {
  const ct = r.content;
  const issues = byCat(r, ["Content"]);
  el.innerHTML = `<div class="grid g2"><div class="card"><h3>Pages by word count</h3><div class="chart-box"><canvas id="c-wc"></canvas></div></div>
    <div class="card"><h3>Content issues</h3><div class="chart-box"><canvas id="c-ci"></canvas></div></div></div>
    <p class="muted">${ct.content_pages} content pages · average ${ct.avg_words} words</p>
    <h2>Issues: thin, duplicate, outdated, generic content, cannibalization and gaps</h2>${issueList(issues)}
    <h2>Keyword cannibalization</h2><div id="t-can"></div><h2>Outdated content</h2><div id="t-old"></div><h2>Content structure</h2><div id="t-struct"></div>`;
  chart("c-wc", barCfg(Object.keys(ct.word_buckets), Object.values(ct.word_buckets), "Pages", C.green));
  chart("c-ci", donutCfg(Object.fromEntries(issues.map((i) => [i.title, i.count]))));
  dataTable("t-can", ct.cannibalization, [{ key: "keyword", label: "Keyword" }, { key: "pages", label: "Competing pages", render: (v) => v.map((u) => link(u, shortUrl(u))).join("<br>") }, { key: "source", label: "Source" }]);
  dataTable("t-old", ct.outdated, [urlCol(), { key: "last_updated", label: "Last updated" }, { key: "age_days", label: "Age (days)" }]);
  dataTable("t-struct", ct.structure, [urlCol(), { key: "problems", label: "Problems" }]);
}

function renderLinks(el, r, s) {
  const st = r.links.stats;
  el.innerHTML = `<div class="grid g4"><div class="card kpi"><div class="l">Orphan pages</div><div class="v">${st.orphans.length}</div></div>
    <div class="card kpi"><div class="l">Avg inlinks / page</div><div class="v">${st.avg_inlinks}</div></div>
    <div class="card kpi"><div class="l">Link suggestions</div><div class="v">${r.links.suggestions.length}</div></div>
    <div class="card kpi"><div class="l">Sitemap-only URLs</div><div class="v">${st.sitemap_only.length}</div></div></div>
    <div class="grid g2" style="margin-top:16px"><div class="card"><h3>Click depth distribution</h3><div class="chart-box"><canvas id="c-depth"></canvas></div></div>
    <div class="card"><h3>Most internally linked pages</h3><div class="chart-box"><canvas id="c-top"></canvas></div></div></div>
    <div class="row space"><h2>Internal link building suggestions</h2><a class="btn" href="/api/audits/${s.latest_done.id}/internal-links.xlsx">⬇ Export to Excel</a></div>
    <p class="muted">Each row: add a link on the <b>source URL</b>, pointing to the <b>target URL</b>, with the suggested anchor at the quoted spot. Weakly linked and orphan targets come first.</p>
    <div id="t-sugg"></div><h2>Issues</h2>${issueList(byCat(r, ["Internal linking", "Links"]))}
    <h2>Orphan pages</h2><div id="t-orph"></div><h2>Least linked pages</h2><div id="t-least"></div>`;
  chart("c-depth", barCfg(Object.keys(st.depth_distribution), Object.values(st.depth_distribution), "Pages", C.slate));
  chart("c-top", barCfg(st.top_linked.slice(0, 12).map((x) => shortUrl(x.url)), st.top_linked.slice(0, 12).map((x) => x.inlinks), "Inlinks", C.navy, true));
  dataTable("t-sugg", r.links.suggestions, [{ key: "priority", label: "Priority", render: (v) => sev(v === "high" ? "high" : v === "medium" ? "medium" : "low") }, urlCol("source_url", "Source URL"),
    urlCol("target_url", "Target URL"), { key: "anchor_text", label: "Anchor" }, { key: "context", label: "Context" }, { key: "target_inlinks", label: "Target inlinks" }]);
  dataTable("t-orph", st.orphans.map((u) => ({ url: u })), [urlCol()]);
  dataTable("t-least", st.least_linked, [urlCol(), { key: "inlinks", label: "Inlinks" }]);
}

function renderStructure(el, r) {
  el.innerHTML = `<div class="card"><div class="row space"><h3>URL structure graph</h3><div class="row">
      <button class="btn secondary" id="v-tree">Folder tree</button><button class="btn secondary" id="v-graph">Internal link network</button></div></div>
    <p class="muted small">Tree: click a folder to expand or collapse it. Node color shows HTTP status (green 2xx, gold 3xx, red 4xx/5xx, grey sitemap-only). Network: node size reflects inlinks; drag nodes to explore.</p>
    <div id="viz"></div></div>
    <div class="grid g2" style="margin-top:16px"><div class="card"><h3>URLs per top-level folder</h3><div class="chart-box"><canvas id="c-fold"></canvas></div></div>
    <div class="card"><h3>URL structure issues</h3>${issueList(byCat(r, ["URL structure"]))}</div></div>
    <h2>URL problems</h2><div id="t-urlp"></div>`;
  const f = r.links.stats.folders;
  chart("c-fold", barCfg(Object.keys(f), Object.values(f), "URLs", C.gold, true));
  dataTable("t-urlp", r.links.stats.url_problems, [urlCol(), { key: "problems", label: "Problems" }]);
  $("#v-tree").onclick = () => drawTree(r.links.tree);
  $("#v-graph").onclick = () => drawGraph(r.links.graph);
  drawTree(r.links.tree);
}

function statusColor(st) { return st == null ? "#9aa5b1" : st < 300 ? C.green : st < 400 ? C.gold : C.red; }

function drawTree(data) {
  const box = $("#viz");
  if (!window.d3) { box.innerHTML = '<p class="muted">The D3 library could not load (offline?).</p>'; return; }
  box.innerHTML = '<svg id="tree-svg"></svg>';
  const svg = d3.select("#tree-svg");
  const width = box.clientWidth || 1000;
  const g = svg.append("g").attr("transform", "translate(160,20)");
  svg.call(d3.zoom().scaleExtent([0.2, 3]).on("zoom", (e) => g.attr("transform", e.transform)));
  const root = d3.hierarchy(data);
  root.x0 = 300; root.y0 = 0;
  root.descendants().forEach((d) => { d._children = d.children; if (d.depth >= 2) d.children = null; });
  const tree = d3.tree().nodeSize([22, 200]);
  function update(src) {
    tree(root);
    const nodes = root.descendants(), links = root.links();
    const minX = d3.min(nodes, (d) => d.x);
    g.attr("transform", `translate(160,${-minX + 30})`);
    const node = g.selectAll("g.node").data(nodes, (d) => d.data.path);
    const enter = node.enter().append("g").attr("class", "node").attr("transform", () => `translate(${src.y0},${src.x0})`)
      .style("cursor", (d) => d._children ? "pointer" : "default").on("click", (e, d) => { d.children = d.children ? null : d._children; update(d); });
    enter.append("circle").attr("r", (d) => Math.max(4, Math.min(12, Math.sqrt(d.data.count) * 2)))
      .attr("fill", (d) => d._children && !d.children ? "#fff" : statusColor(d.data.status)).attr("stroke", (d) => statusColor(d.data.status));
    enter.append("text").attr("dy", "0.32em").attr("x", (d) => d._children ? -14 : 14).attr("text-anchor", (d) => d._children ? "end" : "start")
      .text((d) => `${d.data.name}${d.data.count > 1 ? ` (${d.data.count})` : ""}`);
    enter.append("title").text((d) => `${d.data.url || d.data.path}\nStatus: ${d.data.status ?? "–"}\nInlinks: ${d.data.inlinks ?? "–"}\n${d.data.title || ""}`);
    node.merge(enter).transition().duration(300).attr("transform", (d) => `translate(${d.y},${d.x})`);
    node.merge(enter).select("circle").attr("fill", (d) => d._children && !d.children ? "#fff" : statusColor(d.data.status));
    node.exit().remove();
    const lk = g.selectAll("path.link").data(links, (d) => d.target.data.path);
    lk.enter().insert("path", "g").attr("class", "link").merge(lk).transition().duration(300)
      .attr("d", d3.linkHorizontal().x((d) => d.y).y((d) => d.x));
    lk.exit().remove();
    nodes.forEach((d) => { d.x0 = d.x; d.y0 = d.y; });
  }
  update(root);
}

function drawGraph(data) {
  const box = $("#viz");
  if (!window.d3) { box.innerHTML = '<p class="muted">The D3 library could not load.</p>'; return; }
  box.innerHTML = '<svg id="graph-svg"></svg>';
  const svg = d3.select("#graph-svg");
  const w = box.clientWidth || 1000, h = 640;
  const g = svg.append("g");
  svg.call(d3.zoom().scaleExtent([0.1, 4]).on("zoom", (e) => g.attr("transform", e.transform)));
  const folders = [...new Set(data.nodes.map((n) => n.folder))];
  const color = d3.scaleOrdinal(folders, PALETTE);
  const nodes = data.nodes.map((n) => ({ ...n })), links = data.links.map((l) => ({ ...l }));
  const sim = d3.forceSimulation(nodes).force("link", d3.forceLink(links).id((d) => d.id).distance(60))
    .force("charge", d3.forceManyBody().strength(-60)).force("center", d3.forceCenter(w / 2, h / 2)).force("collide", d3.forceCollide(8));
  const line = g.append("g").selectAll("line").data(links).join("line").attr("stroke", "#9aa5b1").attr("stroke-opacity", 0.25);
  const node = g.append("g").selectAll("circle").data(nodes).join("circle").attr("r", (d) => 3 + Math.sqrt(d.inlinks || 0) * 1.6)
    .attr("fill", (d) => d.inlinks === 0 ? C.red : color(d.folder)).attr("stroke", "#fff").attr("stroke-width", 0.8)
    .call(d3.drag().on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; }).on("end", (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));
  node.append("title").text((d) => `${d.url}\nInlinks: ${d.inlinks}\nDepth: ${d.depth ?? "sitemap only"}`);
  sim.on("tick", () => {
    line.attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
    node.attr("cx", (d) => d.x).attr("cy", (d) => d.y);
  });
  box.insertAdjacentHTML("beforeend", `<p class="small">${folders.slice(0, 10).map((f) => `<span class="pill" style="background:${color(f)};color:#fff">${esc(f)}</span>`).join(" ")} <span class="pill" style="background:${C.red};color:#fff">orphan</span></p>`);
}

function renderSchema(el, r) {
  const t = r.technical;
  el.innerHTML = `<div class="grid g2"><div class="card"><h3>Schema types found</h3><div class="chart-box"><canvas id="c-st"></canvas></div></div>
    <div class="card"><h3>Coverage</h3><div class="chart-box"><canvas id="c-cov"></canvas></div></div></div>
    <h2>Issues</h2>${issueList(byCat(r, ["Schema"]))}
    <h2>Pages without structured data, with suggested types</h2><div id="t-ns"></div><h2>Validation problems</h2><div id="t-sp"></div>`;
  chart("c-st", barCfg(Object.keys(t.schema_types), Object.values(t.schema_types), "Occurrences", C.plum, true));
  chart("c-cov", donutCfg({ "With schema": t.pages_with_schema, "Without schema": t.pages_ok - t.pages_with_schema }, { "With schema": C.green, "Without schema": C.red }));
  dataTable("t-ns", t.schema_suggestions, [urlCol(), { key: "suggested", label: "Suggested schema" }]);
  dataTable("t-sp", t.schema_problems, [urlCol(), { key: "type", label: "Type" }, { key: "problems", label: "Problems", render: (v) => v.map(esc).join("<br>") }]);
}

function renderPerformance(el, r) {
  const res = r.performance.results.filter((x) => !x.error);
  const mobile = res.filter((x) => x.strategy === "mobile");
  const val = (x, m) => x.field[m] ?? x.lab[m];
  el.innerHTML = `${r.performance.errors.length ? `<div class="card"><b>PageSpeed Insights:</b> ${r.performance.errors.length} test(s) failed. ${esc(r.performance.errors[0].error)}. Add an API key in Settings, or check network access.</div>` : ""}
    <div class="grid g2" style="margin-top:12px"><div class="card"><h3>Lighthouse performance score</h3><div class="chart-box"><canvas id="c-ps"></canvas></div></div>
    <div class="card"><h3>Mobile LCP (ms): good ≤ 2500</h3><div class="chart-box"><canvas id="c-lcp"></canvas></div></div>
    <div class="card"><h3>Mobile CLS: good ≤ 0.1</h3><div class="chart-box"><canvas id="c-cls"></canvas></div></div>
    <div class="card"><h3>Server response by page (crawl)</h3><div class="chart-box"><canvas id="c-ttfb"></canvas></div></div></div>
    <h2>Results</h2><div id="t-psi"></div><h2>Issues</h2>${issueList(byCat(r, ["Performance", "Core Web Vitals", "Mobile"]))}`;
  chart("c-ps", { type: "bar", data: { labels: mobile.map((x) => shortUrl(x.url)), datasets: [
    { label: "Mobile", data: mobile.map((x) => x.scores.performance), backgroundColor: C.navy },
    { label: "Desktop", data: mobile.map((x) => (res.find((y) => y.url === x.url && y.strategy === "desktop") || { scores: {} }).scores.performance), backgroundColor: C.gold }] }, options: { scales: { y: { min: 0, max: 100 } } } });
  chart("c-lcp", barCfg(mobile.map((x) => shortUrl(x.url)), mobile.map((x) => val(x, "LCP")), "LCP", mobile.map((x) => (val(x, "LCP") || 0) <= 2500 ? C.green : (val(x, "LCP") || 0) <= 4000 ? C.amber : C.red)));
  chart("c-cls", barCfg(mobile.map((x) => shortUrl(x.url)), mobile.map((x) => val(x, "CLS")), "CLS", mobile.map((x) => (val(x, "CLS") || 0) <= 0.1 ? C.green : (val(x, "CLS") || 0) <= 0.25 ? C.amber : C.red)));
  const pages = r.pages.filter((p) => p.ms).sort((a, b) => b.ms - a.ms).slice(0, 15);
  chart("c-ttfb", barCfg(pages.map((p) => shortUrl(p.url)), pages.map((p) => p.ms), "ms", pages.map((p) => p.ms > 800 ? C.red : C.green), true));
  dataTable("t-psi", res.map((x) => ({ url: x.url, strategy: x.strategy, perf: x.scores.performance, seo: x.scores.seo, lcp: val(x, "LCP") && Math.round(val(x, "LCP")), inp: x.field.INP, cls: val(x, "CLS") != null ? (+val(x, "CLS")).toFixed(3) : null, field: x.field_overall || "lab only", opp: x.opportunities.slice(0, 3).map((o) => `${o.title} (−${o.savings_ms} ms)`) })),
    [urlCol(), { key: "strategy", label: "Device" }, { key: "perf", label: "Perf" }, { key: "seo", label: "SEO" }, { key: "lcp", label: "LCP ms" }, { key: "inp", label: "INP ms" }, { key: "cls", label: "CLS" }, { key: "field", label: "CrUX" }, { key: "opp", label: "Top opportunities", render: (v) => v.map(esc).join("<br>") }]);
}

function renderKeywords(el, r) {
  const k = r.keywords;
  el.innerHTML = `<div class="grid g4"><div class="card kpi"><div class="l">Keywords researched</div><div class="v">${k.keywords.length}</div></div>
    <div class="card kpi"><div class="l">Content gaps</div><div class="v">${k.status_counts["content gap"] || 0}</div></div>
    <div class="card kpi"><div class="l">Clusters</div><div class="v">${k.clusters.length}</div></div>
    <div class="card kpi"><div class="l">Striking distance (positions 4–20)</div><div class="v">${k.striking_distance.length}</div></div></div>
    <p class="muted small">Niche: <b>${esc(k.industry)}</b> · Seeds: ${esc(k.seeds.join(", "))} · Sources: on-site terms, industry modifiers, question patterns${k.autocomplete_used ? ", Google Autocomplete" : ""}${k.volume_provider ? ", DataForSEO volumes" : ""}, Search Console (when synced).</p>
    <div class="grid g3" style="margin-top:12px"><div class="card"><h3>By search intent</h3><div class="chart-box"><canvas id="c-int"></canvas></div></div>
    <div class="card"><h3>Coverage</h3><div class="chart-box"><canvas id="c-cov"></canvas></div></div>
    <div class="card"><h3>Largest clusters</h3><div class="chart-box"><canvas id="c-cl"></canvas></div></div></div>
    <h2>Keyword universe</h2><p class="muted small">Each keyword is mapped to a <b>target URL</b>, or flagged as a <b>content gap</b> with a proposed slug.</p><div id="t-kw"></div>
    <h2>Topic clusters</h2><div id="t-cl"></div><h2>Striking-distance keywords (quick wins)</h2><div id="t-sd"></div>`;
  chart("c-int", donutCfg(k.intent_counts));
  chart("c-cov", donutCfg(k.status_counts, { covered: C.green, ranking: C.navy, "content gap": C.red }));
  chart("c-cl", barCfg(k.clusters.slice(0, 10).map((c) => c.cluster), k.clusters.slice(0, 10).map((c) => c.size), "Keywords", C.gold, true));
  dataTable("t-kw", k.keywords, [{ key: "keyword", label: "Keyword" }, { key: "intent", label: "Intent" }, { key: "funnel", label: "Funnel" }, { key: "priority", label: "Priority" },
    { key: "status", label: "Status", render: (v) => `<span class="pill ${v === "content gap" ? "sev-critical" : "sev-low"}">${esc(v)}</span>` }, urlCol("target_url", "Target URL"),
    { key: "suggested_slug", label: "New page slug", render: (v, x) => x.status === "content gap" ? esc(v) : "" }, { key: "search_volume", label: "Volume" },
    { key: "gsc_impressions", label: "GSC impr." }, { key: "gsc_position", label: "GSC pos." }, { key: "source", label: "Source" }]);
  dataTable("t-cl", k.clusters, [{ key: "cluster", label: "Cluster" }, { key: "size", label: "Size" }, urlCol("pillar_url", "Pillar page"), { key: "keywords", label: "Keywords", render: (v) => esc(v.slice(0, 15).join(", ")) }]);
  dataTable("t-sd", k.striking_distance, [{ key: "keyword", label: "Keyword" }, { key: "gsc_position", label: "Position" }, { key: "gsc_impressions", label: "Impressions" }, urlCol("target_url", "Page")]);
}

async function renderSearch(el, id) {
  const { search: s, analytics: a } = await api(`/api/sites/${id}/search`);
  if (!s.has_data && !a.has_data) {
    el.innerHTML = `<div class="card"><h3>No Search Console or GA4 data yet</h3><ol><li>Connect Google Search Console and GA4 in your Windsor.ai account.</li>
      <li>Paste the Windsor.ai API key in <a href="#/settings">Settings</a>.</li><li>Click <b>Sync GSC/GA4</b> above. Scheduled audits then sync automatically.</li></ol>
      <p class="muted">Once synced, this tab charts clicks, impressions and positions over time, ranking improvements and declines, and organic landing-page conversions.</p></div>`;
    return;
  }
  const t = s.totals || {};
  const delta = (a, b) => b ? `<span class="small ${a >= b ? "ok" : "bad"}">${a >= b ? "▲" : "▼"} ${Math.abs(Math.round((a - b) / b * 100))}%</span>` : "";
  el.innerHTML = `${s.has_data ? `<div class="grid g4"><div class="card kpi"><div class="l">Clicks (28d)</div><div class="v">${t.clicks}</div>${delta(t.clicks, t.prev_clicks)}</div>
    <div class="card kpi"><div class="l">Impressions (28d)</div><div class="v">${t.impressions}</div>${delta(t.impressions, t.prev_impressions)}</div>
    <div class="card kpi"><div class="l">Ranking keywords</div><div class="v">${t.keywords}</div></div><div class="card kpi"><div class="l">In top 10</div><div class="v">${t.top10}</div></div></div>
    <div class="grid g2" style="margin-top:16px"><div class="card"><h3>Clicks & impressions trend</h3><div class="chart-box tall"><canvas id="c-ci"></canvas></div></div>
    <div class="card"><h3>Average position trend</h3><div class="chart-box tall"><canvas id="c-pos"></canvas></div></div>
    <div class="card"><h3>Top keyword rankings over time</h3><div class="chart-box tall"><canvas id="c-kw"></canvas></div></div>
    <div class="card"><h3>Keywords by position</h3><div class="chart-box tall"><canvas id="c-bk"></canvas></div></div>
    <div class="card"><h3>Biggest ranking improvements</h3><div class="chart-box tall"><canvas id="c-imp"></canvas></div></div>
    <div class="card"><h3>Biggest declines</h3><div class="chart-box tall"><canvas id="c-dec"></canvas></div></div></div>
    <h2>Ranking improvements</h2><div id="t-imp"></div><h2>Declines</h2><div id="t-dec"></div><h2>Top queries</h2><div id="t-q"></div><h2>Top pages</h2><div id="t-p"></div>` : ""}
    ${a.has_data ? `<h2>Organic traffic & conversions (GA4)</h2><div class="grid g2"><div class="card"><h3>Organic sessions & key events</h3><div class="chart-box"><canvas id="c-ga"></canvas></div></div>
      <div class="card"><h3>Sessions by channel</h3><div class="chart-box"><canvas id="c-ch"></canvas></div></div></div><h2>Organic landing pages</h2><div id="t-lp"></div>` : ""}`;
  if (s.has_data) {
    const labels = s.daily.map((d) => d.date);
    chart("c-ci", { type: "line", data: { labels, datasets: [{ label: "Clicks", data: s.daily.map((d) => d.clicks), borderColor: C.navy, yAxisID: "y", tension: .25 }, { label: "Impressions", data: s.daily.map((d) => d.impressions), borderColor: C.gold, yAxisID: "y1", tension: .25 }] },
      options: { scales: { y: { beginAtZero: true }, y1: { position: "right", beginAtZero: true, grid: { drawOnChartArea: false } } } } });
    chart("c-pos", { type: "line", data: { labels, datasets: [{ label: "Avg position", data: s.daily.map((d) => d.position), borderColor: C.green, tension: .25 }] }, options: { scales: { y: { reverse: true } } } });
    const qs = Object.keys(s.query_series);
    const allDates = [...new Set(qs.flatMap((q) => s.query_series[q].map((p) => p.date)))].sort();
    chart("c-kw", { type: "line", data: { labels: allDates, datasets: qs.map((q, i) => { const m = Object.fromEntries(s.query_series[q].map((p) => [p.date, p.position])); return { label: q, data: allDates.map((d) => m[d] ?? null), borderColor: PALETTE[i % 8], spanGaps: true, tension: .25 }; }) }, options: { scales: { y: { reverse: true } } } });
    chart("c-bk", barCfg(Object.keys(s.position_buckets), Object.values(s.position_buckets), "Keywords", [C.green, C.green, C.gold, C.amber, C.red]));
    chart("c-imp", barCfg(s.improved.slice(0, 12).map((x) => x.query), s.improved.slice(0, 12).map((x) => x.change), "Positions gained", C.green, true));
    chart("c-dec", barCfg(s.declined.slice(0, 12).map((x) => x.query), s.declined.slice(0, 12).map((x) => x.change), "Positions lost", C.red, true));
    const qc = [{ key: "query", label: "Query" }, { key: "prev_position", label: "Previous" }, { key: "position", label: "Now" }, { key: "change", label: "Change" }, { key: "clicks", label: "Clicks" }, { key: "impressions", label: "Impr." }];
    dataTable("t-imp", s.improved, qc); dataTable("t-dec", s.declined, qc);
    dataTable("t-q", s.top_queries.map((q) => ({ ...q, position: q.position && q.position.toFixed(1) })), [{ key: "query", label: "Query" }, { key: "clicks", label: "Clicks" }, { key: "impressions", label: "Impressions" }, { key: "position", label: "Position" }]);
    dataTable("t-p", s.top_pages.map((q) => ({ ...q, position: q.position && q.position.toFixed(1) })), [urlCol("page", "Page"), { key: "clicks", label: "Clicks" }, { key: "impressions", label: "Impressions" }, { key: "position", label: "Position" }]);
  }
  if (a.has_data) {
    chart("c-ga", { type: "line", data: { labels: a.daily.map((d) => d.date), datasets: [{ label: "Organic sessions", data: a.daily.map((d) => d.sessions), borderColor: C.navy, tension: .25 }, { label: "Key events", data: a.daily.map((d) => d.conversions), borderColor: C.gold, yAxisID: "y1", tension: .25 }] },
      options: { scales: { y1: { position: "right", beginAtZero: true, grid: { drawOnChartArea: false } } } } });
    chart("c-ch", donutCfg(Object.fromEntries(a.channels.slice(0, 8).map((c) => [c.channel || "(not set)", c.sessions]))));
    dataTable("t-lp", a.landing_pages, [{ key: "landing_page", label: "Landing page" }, { key: "sessions", label: "Sessions" }, { key: "conversions", label: "Key events" }]);
  }
}

function renderGeo(el, r) {
  const g = r.geo, b = g.brief;
  const bands = { "0-24": 0, "25-49": 0, "50-74": 0, "75-100": 0 };
  g.pages.forEach((p) => bands[p.score < 25 ? "0-24" : p.score < 50 ? "25-49" : p.score < 75 ? "50-74" : "75-100"]++);
  el.innerHTML = `<div class="card"><h2>AIO & GEO brief</h2><p><b>${esc(b.summary)}</b></p>${b.what_it_is.map((x) => `<p>${esc(x)}</p>`).join("")}</div>
    <div class="grid g2" style="margin-top:16px"><div class="card"><h3>Pages by AI answer-readiness</h3><div class="chart-box"><canvas id="c-ai"></canvas></div></div>
    <div class="card"><h3>Technical prerequisites</h3>${b.prerequisites.map((p) => `<div class="check"><span class="${p.ok ? "ok" : "bad"}">${p.ok ? "✓" : "✗"}</span><div><b>${esc(p.check)}</b><div class="muted small">${esc(p.detail)}</div></div></div>`).join("")}</div></div>
    <h2>Optimization playbook</h2><div class="grid g3">${b.playbook.map((s) => `<div class="card"><h3>${esc(s.step)}</h3><ul>${s.actions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></div>`).join("")}</div>
    <div class="card" style="margin-top:16px"><h3>Answer block template</h3><pre>${esc(b.answer_template)}</pre></div>
    <h2>Page-level AIO scores and fixes</h2><div id="t-ai"></div><h2>Question opportunities</h2><div id="t-q"></div><h2>Issues</h2>${issueList(byCat(r, ["AI search"]))}`;
  chart("c-ai", barCfg(Object.keys(bands), Object.values(bands), "Pages", [C.red, C.amber, C.gold, C.green]));
  dataTable("t-ai", g.pages, [urlCol(), { key: "score", label: "Score", render: (v) => badge(v) }, { key: "strengths", label: "Strengths", render: (v) => v.map(esc).join("<br>") }, { key: "fixes", label: "Fixes", render: (v) => v.map(esc).join("<br>") }]);
  dataTable("t-q", b.question_opportunities, [{ key: "question", label: "Question" }, urlCol("target_url", "Target page"), { key: "action", label: "Action" }]);
}

function renderConversion(el, r) {
  const c = r.conversion;
  const evc = {}; c.events.forEach((e) => evc[e.event_name] = (evc[e.event_name] || 0) + 1);
  el.innerHTML = `<div class="grid g4"><div class="card kpi"><div class="l">Events to implement</div><div class="v">${c.events.length}</div></div>
    <div class="card kpi"><div class="l">Key events</div><div class="v">${c.key_events.length}</div></div>
    <div class="card kpi"><div class="l">Lead-gen gaps</div><div class="v">${c.lead_gaps.length}</div></div>
    <div class="card kpi"><div class="l">Tracking detected</div><div class="v small">${esc(Object.keys(c.tracking_detected).join(", ") || "none")}</div></div></div>
    <div class="grid g2" style="margin-top:16px"><div class="card"><h3>Recommended events</h3><div class="chart-box"><canvas id="c-ev"></canvas></div></div>
    <div class="card"><h3>Pages by commercial role</h3><div class="chart-box"><canvas id="c-pt"></canvas></div></div></div>
    <div class="card" style="margin-top:16px"><h3>Implementation steps (GA4 + Google Tag Manager)</h3><ol>${c.setup_steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></div>
    <h2>Event plan: where to put each event, what type, and how to trigger it</h2><div id="t-ev"></div>
    <h2>Lead-generation gaps</h2><div id="t-gap"></div><h2>Lead-generation opportunity spots</h2><div id="t-opp"></div><h2>Issues</h2>${issueList(byCat(r, ["Tracking", "Conversion"]))}`;
  chart("c-ev", barCfg(Object.keys(evc), Object.values(evc), "Placements", C.navy, true));
  chart("c-pt", donutCfg(c.page_types));
  dataTable("t-ev", c.events, [{ key: "priority", label: "Priority", render: (v) => sev(v) }, urlCol("page_url", "Page"), { key: "event_name", label: "GA4 event", render: (v) => `<code>${esc(v)}</code>` },
    { key: "element", label: "Element" }, { key: "gtm_trigger", label: "GTM trigger" }, { key: "parameters", label: "Parameters" }, { key: "key_event", label: "Key event", render: (v) => v ? "✓" : "" }, { key: "why", label: "Why" }]);
  dataTable("t-gap", c.lead_gaps, [urlCol(), { key: "page_type", label: "Type" }, { key: "problem", label: "Problem" }, { key: "recommendation", label: "Recommendation" }]);
  dataTable("t-opp", c.opportunities, [urlCol(), { key: "page_type", label: "Type" }, { key: "opportunity", label: "Opportunity" }, { key: "recommendation", label: "Recommendation" }, { key: "sessions", label: "Sessions" }]);
}

function renderOffpage(el, r) {
  const o = r.offpage;
  el.innerHTML = `<div class="grid g2"><div class="card"><h3>Platforms by cost</h3><div class="chart-box"><canvas id="c-cost"></canvas></div></div>
    <div class="card"><h3>Guidelines</h3><ul>${o.guidelines.map((g) => `<li>${esc(g)}</li>`).join("")}</ul></div></div>
    <h2>Guest posting and contributor platforms (${esc(o.niche)})</h2><div id="t-pl"></div>
    <h2>Prospecting searches: click to find niche blogs that accept guest posts</h2><div id="t-fp"></div>
    <h2>Digital PR sources</h2><div id="t-pr"></div>
    <div class="card" style="margin-top:16px"><h3>Pitch topic ideas (from informational keywords)</h3><p>${o.pitch_topics.map(esc).join(" · ") || "Run keyword research first."}</p></div>`;
  chart("c-cost", donutCfg({ Free: o.free_count, "Paid / membership": o.paid_count }, { Free: C.green, "Paid / membership": C.gold }));
  dataTable("t-pl", o.platforms, [{ key: "name", label: "Platform", render: (v, x) => x.url ? link(x.url, v) : esc(v) }, { key: "cost", label: "Cost" }, { key: "type", label: "Type" }, { key: "notes", label: "Notes" }]);
  dataTable("t-fp", o.footprints, [{ key: "keyword", label: "Keyword" }, { key: "type", label: "Type" }, { key: "query", label: "Search", render: (v, x) => link(x.google_url, v) }]);
  dataTable("t-pr", o.pr_sources, [{ key: "name", label: "Source", render: (v, x) => link(x.url, v) }, { key: "cost", label: "Cost" }, { key: "type", label: "Type" }]);
}

function renderCrawl(el, r) {
  el.innerHTML = `<h2>All crawled URLs</h2><div id="t-pages"></div><h2>All issues</h2>${issueList(r.issues)}`;
  dataTable("t-pages", r.pages, [urlCol(), { key: "status", label: "Status" }, { key: "indexable", label: "Indexable", render: (v) => v ? "✓" : "✗" }, { key: "title", label: "Title" },
    { key: "words", label: "Words" }, { key: "inlinks", label: "Inlinks" }, { key: "depth", label: "Depth" }, { key: "ms", label: "ms" }, { key: "schema", label: "Schema" },
    { key: "primary_keyword", label: "Primary keyword" }, { key: "page_type", label: "Type" }, { key: "aio_score", label: "AIO" }]);
}

route();
