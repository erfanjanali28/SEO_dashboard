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
    else if (h === "/first-look") await viewFirstLook();
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

/* ---------------- First look: websites that are not our projects ---------------- */
async function viewFirstLook() {
  const sites = await api("/api/first-look");
  const running = sites.some((s) => s.status === "running");
  app.innerHTML = `
    <h1>First look</h1>
    <p class="muted">Review a website you do not manage, using only what a crawler can see from outside. These sites stay out of Clients, are never scheduled, and use none of your Search Console, GA4 or paid API data. Crawls obey robots.txt and wait at least 1 second between requests.</p>
    <form id="fl" class="card">
      <label>Websites (one per line)</label><textarea name="urls" rows="3" required placeholder="example.com&#10;competitor.cz"></textarea>
      <div class="row" style="margin-top:10px"><div><label>Pages per crawl</label><select name="max_pages">${[25, 50, 100, 250, 500].map((n) => `<option value="${n}" ${n === 100 ? "selected" : ""}>${n}</option>`).join("")}</select></div>
      <button class="btn gold" type="submit" style="align-self:flex-end">Start first look</button></div>
      <p class="muted small">At 1 second per page, 100 pages takes about 2 minutes.</p>
    </form>
    <h2>Reviewed websites</h2>
    <div class="grid g2">${sites.map((s) => `
      <div class="card"><div class="row space"><h3 style="margin:0">${link(s.url, shortHost(s.url))}</h3>${badge(s.score)}</div>
        <p class="muted small">Last run: ${fmtDate(s.last_run_at)}${s.pages_crawled != null ? ` · ${s.pages_crawled} URLs crawled` : ""}${s.issues_critical != null ? ` · ${s.issues_critical} critical, ${s.issues_high} high` : ""}</p>
        ${s.status === "running" ? `<p class="small"><b>Crawling:</b> ${esc(s.progress)}</p><div class="progress"><div></div></div>` : ""}
        ${s.status === "error" ? `<p class="small bad">${esc((s.error || "").split("\n")[0].slice(0, 200))}</p>` : ""}
        <div class="row" style="margin-top:8px"><a class="btn" href="#/site/${s.id}">Open</a>
        <button class="btn secondary" data-rerun="${esc(s.url)}" data-pages="${s.max_pages}" ${s.status === "running" ? "disabled" : ""}>Run again</button>
        <button class="btn danger" data-del="${s.id}" data-host="${esc(shortHost(s.url))}">Remove</button></div></div>`).join("") || '<div class="card"><p>Nothing reviewed yet. Add a website above.</p></div>'}</div>`;
  $("#fl").onsubmit = async (e) => {
    e.preventDefault();
    const d = new FormData(e.target);
    const urls = String(d.get("urls")).split(/[\s,]+/).filter(Boolean);
    const failed = [];
    for (const url of urls) {
      try { await api("/api/first-look", { method: "POST", body: { url, max_pages: parseInt(d.get("max_pages"), 10) } }); }
      catch (err) { failed.push(`${url}: ${err.message}`); }
    }
    if (failed.length) toast(failed.join(" "), 8000);
    route();
  };
  document.querySelectorAll("[data-rerun]").forEach((b) => b.onclick = async () => {
    await api("/api/first-look", { method: "POST", body: { url: b.dataset.rerun, max_pages: parseInt(b.dataset.pages, 10) } }); route();
  });
  document.querySelectorAll("[data-del]").forEach((b) => b.onclick = async () => {
    if (confirm(`Remove ${b.dataset.host} and its results?`)) { await api(`/api/sites/${b.dataset.del}`, { method: "DELETE" }); route(); }
  });
  if (running) pollTimer = setInterval(async () => {
    if (location.hash !== "#/first-look") return clearInterval(pollTimer);
    const now = await api("/api/first-look");
    if (!now.some((s) => s.status === "running")) { clearInterval(pollTimer); toast("First look complete"); route(); }
    else now.forEach((s) => { if (s.status === "running") { const el = [...document.querySelectorAll("[data-rerun]")].find((b) => b.dataset.rerun === s.url); const p = el && el.closest(".card").querySelector("p.small b"); if (p) p.parentElement.innerHTML = `<b>Crawling:</b> ${esc(s.progress)}`; } });
  }, 2500);
}

function firstLookCard(f) {
  const cls = { good: "ok", warn: "warn", bad: "bad", info: "" };
  return `<div class="card" style="margin-bottom:16px"><h2 style="margin-top:0">What a crawler can see</h2><div class="grid g2">${f.groups.map((g) => `<div><h3>${esc(g.name)}</h3>
    <table class="metric-list">${g.items.map((i) => `<tr><td>${esc(i.label)}</td><td class="${cls[i.status] || ""}"><b>${esc(i.value)}</b></td><td class="muted small">${esc(i.detail)}</td></tr>`).join("")}</table></div>`).join("")}</div>
    <p class="muted small" style="margin-top:12px"><b>Not visible from outside:</b> ${f.not_visible.map(esc).join("; ")}.</p></div>`;
}

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
async function loadAhrefsProjects(s, suggestOnly) {
  const note = $("#a-note"), el = $("#a-proj");
  if (!note || !el) return;
  try {
    const r = await api(`/api/ahrefs/projects${s.url ? "?site_url=" + encodeURIComponent(s.url) : ""}`);
    const pick = (suggestOnly ? "" : s.ahrefs_project_id) || r.suggested || "";
    el.innerHTML = `<option value="">Auto-detect from the domain</option>` + r.projects.map((p) =>
      `<option value="${esc(p.id)}" ${p.id === pick ? "selected" : ""}>${esc(p.name)} (${esc(p.url)})</option>`).join("");
    note.innerHTML = `${r.projects.length} Ahrefs project(s) found.` + (s.url && !r.suggested ? " <b>No project matches this domain. Pick one, or add the domain as a project in Ahrefs.</b>" : "");
  } catch (e) {
    note.innerHTML = /API key/.test(e.message) ? `Ahrefs is not connected. <a href="#/settings">Add your Ahrefs API key in Settings</a>.` : `Ahrefs projects could not be loaded: ${esc(e.message)}`;
  }
}
async function loadWindsorAccounts(s, suggestOnly) {
  const note = $("#w-note");
  if (!note) return;
  try {
    const r = await api(`/api/windsor/accounts${s.url ? "?site_url=" + encodeURIComponent(s.url) : ""}`);
    for (const [key, sel] of [["gsc", "#w-gsc"], ["ga4", "#w-ga4"]]) {
      const el = $(sel); if (!el) continue;
      const current = suggestOnly ? "" : (key === "gsc" ? s.windsor_gsc_account : s.windsor_ga4_account) || "";
      const pick = current || (r.suggested && r.suggested[key]) || "";
      el.innerHTML = `<option value="">Auto-detect from the domain</option>` + r[key].map((a) =>
        `<option value="${esc(a.id)}" ${a.id === pick ? "selected" : ""}>${esc(a.name)}${a.name !== a.id ? " (" + esc(a.id) + ")" : ""}</option>`).join("");
    }
    const sug = r.suggested || {};
    note.innerHTML = `${r.gsc.length} Search Console site(s) and ${r.ga4.length} GA4 propert${r.ga4.length === 1 ? "y" : "ies"} found in your Windsor.ai account.` +
      (s.url && !(sug.gsc && sug.ga4) ? ` <b>Not every account could be matched to this domain. Pick it from the list.</b>` : "");
  } catch (e) {
    note.innerHTML = `Windsor.ai accounts could not be loaded: ${esc(e.message)} <a href="#/settings">Open Settings</a>`;
  }
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
    <div class="grid g2"><div><label>Windsor.ai: Search Console site</label><select name="windsor_gsc_account" id="w-gsc"><option value="">Auto-detect from the domain</option>${s.windsor_gsc_account ? `<option value="${esc(s.windsor_gsc_account)}" selected>${esc(s.windsor_gsc_account)}</option>` : ""}</select></div>
    <div><label>Windsor.ai: GA4 property</label><select name="windsor_ga4_account" id="w-ga4"><option value="">Auto-detect from the domain</option>${s.windsor_ga4_account ? `<option value="${esc(s.windsor_ga4_account)}" selected>${esc(s.windsor_ga4_account)}</option>` : ""}</select></div></div>
    <p class="muted small" id="w-note">Loading your Windsor.ai accounts…</p>
    <label>Ahrefs project</label><select name="ahrefs_project_id" id="a-proj"><option value="">Auto-detect from the domain</option>${s.ahrefs_project_id ? `<option value="${esc(s.ahrefs_project_id)}" selected>${esc(s.ahrefs_project_id)}</option>` : ""}</select>
    <p class="muted small" id="a-note">Loading your Ahrefs projects…</p>
    <div class="row" style="margin-top:16px"><button class="btn" type="submit">Save</button><button class="btn secondary" type="button" onclick="closeModal()">Cancel</button></div></form>`);
  loadWindsorAccounts(s);
  loadAhrefsProjects(s);
  $("#sf [name=url]").onchange = () => { const u = { ...s, url: $("#sf [name=url]").value }; loadWindsorAccounts(u, true); loadAhrefsProjects(u, true); };
  $("#sf").onsubmit = async (e) => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target).entries());
    const interval = d.interval_preset === "custom" ? parseInt(d.interval_custom || "0", 10) : parseInt(d.interval_preset, 10);
    const body = { client_id: s.client_id, url: d.url, industry: d.industry, location: d.location, seed_keywords: d.seed_keywords, competitors: d.competitors,
      interval_hours: interval || 0, max_pages: parseInt(d.max_pages, 10) || 150, language: d.language || "en",
      windsor_gsc_account: d.windsor_gsc_account, windsor_ga4_account: d.windsor_ga4_account, ahrefs_project_id: d.ahrefs_project_id };
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
      <p class="muted small">This app connects with your Windsor.ai <b>API key</b>, never your password.</p>
      <ol class="small"><li>Sign in at <a href="https://onboard.windsor.ai" target="_blank" rel="noopener">onboard.windsor.ai</a> and make sure the <b>Google Search Console</b> and <b>Google Analytics 4</b> connectors are connected.</li>
      <li>Copy your API key from your Windsor.ai account (it is shown on the connector / data preview pages and in your account settings).</li>
      <li>Paste it below, click <b>Save settings</b>, then <b>Test connection</b>.</li></ol>
      <label>Windsor.ai API key</label><input name="windsor_api_key" value="${esc(s.windsor_api_key || "")}" autocomplete="off">
      <div class="row" style="margin-top:10px"><button class="btn secondary" type="button" id="w-test">Test connection</button></div><div id="w-result" class="small" style="margin-top:8px"></div></div>
    <div class="card"><h2>Ahrefs</h2>
      <p class="muted small">Ahrefs connects apps with an <b>API key</b>, not your login and password.</p>
      <ol class="small"><li>In Ahrefs, open <b>Account settings → API keys</b> (workspace owner or admin) and create a key.</li>
      <li>Paste it below, click <b>Save settings</b>, then <b>Test connection</b>.</li>
      <li>Every website that is a project in your Ahrefs account then gets the <b>Ahrefs</b> tab analysis.</li></ol>
      <label>Ahrefs API key</label><input name="ahrefs_api_key" value="${esc(s.ahrefs_api_key || "")}" autocomplete="off">
      <label>Keyword country (2 letters, e.g. CZ; empty = from the domain ending)</label><input name="ahrefs_country" maxlength="2" value="${esc(s.ahrefs_country || "")}">
      <label>Run the Ahrefs analysis with every scheduled audit</label><select name="ahrefs_auto"><option value="0" ${s.ahrefs_auto !== "1" ? "selected" : ""}>No (run it manually, saves API units)</option><option value="1" ${s.ahrefs_auto === "1" ? "selected" : ""}>Yes</option></select>
      <div class="row" style="margin-top:10px"><button class="btn secondary" type="button" id="a-test">Test connection</button></div><div id="a-result" class="small" style="margin-top:8px"></div></div>
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
  $("#w-test").onclick = async () => {
    const out = $("#w-result"); out.textContent = "Testing…";
    try {
      const r = await api("/api/windsor/test", { method: "POST" });
      out.innerHTML = `<span class="ok">✓ Connected.</span> ${r.gsc_accounts} Search Console site(s): ${r.gsc.map((a) => esc(a.name)).join(", ") || "none"}.<br>${r.ga4_accounts} GA4 propert${r.ga4_accounts === 1 ? "y" : "ies"}: ${r.ga4.map((a) => esc(a.name)).join(", ") || "none"}.`;
    } catch (e) { out.innerHTML = `<span class="bad">✗ ${esc(e.message)}</span> Save the key first if you just pasted it.`; }
  };
  $("#a-test").onclick = async () => {
    const out = $("#a-result"); out.textContent = "Testing…";
    try {
      const r = await api("/api/ahrefs/test", { method: "POST" });
      out.innerHTML = `<span class="ok">✓ Connected</span> (${esc(r.subscription || "plan unknown")}). ${r.projects.length} project(s): ${r.projects.slice(0, 12).map((p) => esc(p.name)).join(", ")}${r.projects.length > 12 ? "…" : ""}.<br>` +
        (r.units_left === 0 ? `<span class="bad">API units left: 0.</span> Only the free parts run (project match, Domain Rating, Search Console, GA4, crawl data) until the plan includes API units${r.reset ? " (usage resets " + esc(r.reset.slice(0, 10)) + ")" : ""}.`
          : `API units left: ${r.units_left == null ? "unlimited" : r.units_left.toLocaleString()}.`);
    } catch (e) { out.innerHTML = `<span class="bad">✗ ${esc(e.message)}</span> Save the key first if you just pasted it.`; }
  };
  $("#set").onsubmit = async (e) => {
    e.preventDefault();
    const sent = Object.fromEntries(new FormData(e.target).entries());
    const saved = await api("/api/settings", { method: "PUT", body: sent });
    // A server still running older code silently ignores settings it does not know.
    const dropped = Object.keys(sent).filter((k) => sent[k] && !(k in saved));
    if (dropped.length) {
      modal(`<h2>Not saved: the app server is out of date</h2>
        <p>The page is the new version, but the server behind it is still running older code, so it ignored: <b>${dropped.map(esc).join(", ")}</b>.</p>
        <ol><li>Close <b>every</b> black terminal window running the dashboard (or restart the computer).</li>
        <li>Start the dashboard again (<code>start-dashboard</code>).</li><li>Press <b>Ctrl+F5</b> and save the key again.</li></ol>
        <button class="btn" onclick="closeModal()">OK</button>`);
      return;
    }
    toast("Settings saved"); route();
  };
}
function applyTheme(t) { if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; }
try { applyTheme(localStorage.getItem("theme") || ""); } catch {}

/* ---------------- Site dashboard ---------------- */
const TABS = [["overview", "Overview"], ["growth", "Growth & Decline"], ["priorities", "Top 10 & Roadmap"], ["technical", "Technical"], ["onpage", "On-page & Meta"], ["content", "Content"],
  ["links", "Internal Links"], ["redirects", "Redirects & Canonicals"], ["structure", "URL Structure"], ["schema", "Schema"], ["performance", "Core Web Vitals"], ["keywords", "Keyword Research"],
  ["search", "Rankings & Traffic"], ["geo", "AIO / GEO"], ["conversion", "Lead Gen & Tracking"], ["offpage", "Off-page"], ["ahrefs", "Ahrefs"], ["crawl", "Crawl Data"]];
const FIRST_LOOK_HIDDEN = new Set(["performance", "keywords", "search", "conversion", "offpage"]);

async function viewSite(id, tab) {
  const s = await api(`/api/sites/${id}`);
  const c = s.client;
  const running = s.latest && s.latest.status === "running";
  const doneId = s.latest_done && s.latest_done.id;
  const fl = s.first_look;
  const tabs = fl ? TABS.filter(([k]) => !FIRST_LOOK_HIDDEN.has(k)) : TABS;
  if (fl && FIRST_LOOK_HIDDEN.has(tab)) tab = "overview";
  app.innerHTML = `
    <div class="card row">${avatar(c)}<div style="flex:1;min-width:220px"><div class="muted small"><a href="${fl ? "#/first-look" : `#/client/${c.id}`}">${esc(c.name)}</a></div>
      <h1 style="margin:2px 0">${link(s.url, shortHost(s.url))}</h1>
      <div class="muted small">${fl ? `Crawl data only · up to ${s.max_pages} pages` : `${esc(s.industry || "general")} ${s.location ? "· " + esc(s.location) : ""} · Schedule: ${s.interval_hours ? "every " + intervalLabel(s.interval_hours) : "manual"}`} · Last run: ${fmtDate(s.last_run_at)}</div></div>
      <div class="row"><button class="btn gold" id="run" ${running ? "disabled" : ""}>${running ? "Audit running…" : "Run audit"}</button>
      ${fl ? "" : `<button class="btn secondary" id="sync">Sync GSC/GA4</button><button class="btn secondary" id="edit-site">Settings / schedule</button>`}</div></div>
    ${running ? `<div class="card" style="margin-top:12px"><b>Audit in progress:</b> <span id="prog">${esc(s.latest.progress)}</span><div class="progress"><div></div></div></div>` : ""}
    ${s.latest && s.latest.status === "error" ? `<div class="card" style="margin-top:12px;border-color:var(--red)"><b class="bad">Last audit failed:</b><pre>${esc((s.latest.error || "").slice(0, 600))}</pre></div>` : ""}
    ${doneId ? `<div class="export-bar" style="margin-top:12px">
      <a class="btn" href="/api/audits/${doneId}/export.xlsx">⬇ Full report (Excel)</a>
      <a class="btn" href="/api/audits/${doneId}/internal-links.xlsx">⬇ Internal links (Excel)</a>
      <a class="btn secondary" href="/api/audits/${doneId}/report.html" target="_blank" rel="noopener">Printable report / PDF</a>
      <a class="btn secondary" href="/api/audits/${doneId}/report.html?download=1">⬇ HTML report</a></div>` : ""}
    <div class="tabs">${tabs.map(([k, l]) => `<button class="tab ${k === tab ? "active" : ""}" data-tab="${k}">${l}</button>`).join("")}</div>
    <div id="tab-body"></div>`;
  document.querySelectorAll(".tab").forEach((b) => b.onclick = () => location.hash = `#/site/${id}/${b.dataset.tab}`);
  $("#run").onclick = async () => { await api(`/api/sites/${id}/audit`, { method: "POST" }); route(); };
  if (!fl) $("#sync").onclick = async () => {
    toast("Syncing Search Console and GA4 from Windsor.ai…", 8000);
    try { const r = await api(`/api/sites/${id}/sync`, { method: "POST" }); toast(`Synced ${r.gsc_rows} Search Console rows (${r.accounts.gsc || "no site"}) and ${r.ga4_rows} GA4 rows (${r.accounts.ga4 || "no property"}). ${r.notes.concat(r.errors).join(" ")}`, 12000); if (tab === "search") route(); }
    catch (e) { toast(e.message, 8000); }
  };
  if (!fl) $("#edit-site").onclick = () => siteForm(s);
  if (running) {
    pollTimer = setInterval(async () => {
      const a = await api(`/api/audits/${s.latest.id}`);
      const p = $("#prog"); if (p) p.textContent = a.progress;
      if (a.status !== "running") { clearInterval(pollTimer); toast(a.status === "done" ? "Audit complete" : "Audit failed"); route(); }
    }, 2500);
  }
  const body = $("#tab-body");
  if (tab === "search") return renderSearch(body, id);
  if (tab === "ahrefs") return renderAhrefs(body, s);
  if (!doneId) { body.innerHTML = `<div class="card"><p>No completed audit yet. ${running ? "Results appear here as soon as the crawl finishes." : "Click <b>Run audit</b> to crawl the site."}</p></div>`; return; }
  const r = await api(`/api/audits/${doneId}/result`);
  const renderers = { overview: renderOverview, growth: renderGrowth, priorities: renderPriorities, technical: renderTechnical, onpage: renderOnpage, content: renderContent,
    links: renderLinks, redirects: renderRedirects, structure: renderStructure, schema: renderSchema, performance: renderPerformance, keywords: renderKeywords, geo: renderGeo,
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
  el.innerHTML = `${r.first_look ? firstLookCard(r.first_look) : ""}
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
  dataTable("t-ev", c.events, [{ key: "priority", label: "Priority", render: (v) => sev(v) },
    { key: "page_url", label: "Page", render: (v, e) => e.pages > 1 ? `${e.pages} pages<div class="muted small">site template</div>` : link(v, shortUrl(v)) }, { key: "event_name", label: "GA4 event", render: (v) => `<code>${esc(v)}</code>` },
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

function confPill(v) { const map = { high: "sev-low", medium: "sev-medium", low: "sev-high" }; return `<span class="pill ${map[v] || ""}">${esc(v)}</span>`; }

function renderRedirects(el, r, s) {
  const p = r.redirects;
  if (!p) { el.innerHTML = `<div class="card"><p>This audit ran before redirect and canonical suggestions existed. Click <b>Run audit</b> to generate them.</p></div>`; return; }
  const m = p.summary;
  const kpi = (label, value, note) => `<div class="card kpi"><div class="l">${label}</div><div class="v">${value}</div>${note ? `<div class="small muted">${note}</div>` : ""}</div>`;
  el.innerHTML = `
    <div class="grid g4">
      ${kpi("301 redirects", m.redirects)}
      ${kpi("410 (let go)", m.gone, m.restore ? `Plus ${m.restore} to restore` : "No equivalent page")}
      ${kpi("Canonical fixes", m.canonical_fixes, `${m.canonical_missing} pages just need a self-canonical`)}
      ${kpi("Keep both, differentiate", m.differentiate, "No redirect needed")}
      ${kpi("Internal link updates", m.link_updates, `Across ${m.links_affected} links`)}
      ${kpi("Keyword stuffing flags", m.stuffing)}
      ${kpi("Already canonicalized", m.already_canonicalized, "Correct today")}
      ${kpi("Search Console used", m.used_search_console ? "Yes" : "No", m.used_search_console ? "Clicks decide the primary page" : "Primary page chosen from crawl signals")}
    </div>
    <div class="card" style="margin-top:16px"><h3 style="margin-top:0">How these are decided</h3>
      <p class="small"><b>301</b> when a URL is dead or truly the same page as another, with the target taken from anchor text, topic, URL similarity and the internal link suggestions.
      <b>Canonical</b> when both URLs must stay reachable, such as parameter versions or one page in two folders.
      <b>Keep both</b> when pages share a keyword but differ in intent or text. A redirect there would lose content, and a canonical would be ignored.
      <b>410</b> when nothing similar exists, because redirecting to the home page counts as a soft 404.</p>
      <p class="small bad"><b>Review before deploying.</b> These are suggestions from crawl data. Check every "Merge, then 301" by hand, and don't deploy "low" confidence rows without looking at both pages.</p></div>
    <h2>Redirect plan</h2><div id="t-rd"></div>
    <h2>Canonical plan</h2><div id="t-can"></div>
    <h2>Keyword cannibalization decisions</h2><div id="t-dec"></div>
    <h2>Internal links to update</h2><p class="muted small">Do these first, so nothing depends on the redirects.</p><div id="t-upd"></div>
    <h2>Keyword stuffing guard</h2><p class="muted small">Density is a warning sign, not a Google metric. Use it to find repetitive copy, especially before merging pages.</p><div id="t-stuff"></div>
    <h2>Server rules</h2><p class="muted small">High and medium confidence rows only.${p.rules.skipped ? ` ${p.rules.skipped} rows with query strings need a rewrite rule and are left out.` : ""}</p>
    <div class="grid g2"><div class="card"><div class="row space"><h3 style="margin:0">Apache (.htaccess)</h3><button class="btn secondary" data-copy="apache">Copy</button></div><pre class="rules" id="r-apache"></pre></div>
    <div class="card"><div class="row space"><h3 style="margin:0">nginx</h3><button class="btn secondary" data-copy="nginx">Copy</button></div><pre class="rules" id="r-nginx"></pre></div></div>`;
  $("#r-apache").textContent = p.rules.apache || "Nothing to deploy.";
  $("#r-nginx").textContent = p.rules.nginx || "Nothing to deploy.";
  document.querySelectorAll("[data-copy]").forEach((b) => b.onclick = async () => {
    try { await navigator.clipboard.writeText(p.rules[b.dataset.copy]); toast("Copied"); } catch { toast("Copy failed. Select the text instead."); }
  });
  const reason = (v) => `<span class="small">${esc(v)}</span>`;
  dataTable("t-rd", p.redirects, [urlCol("from", "From"), { key: "action", label: "Action" }, { key: "to", label: "Target", render: (v) => v ? link(v, shortUrl(v)) : '<span class="muted">none</span>' },
    { key: "confidence", label: "Confidence", render: confPill }, { key: "source", label: "Flagged by" }, { key: "inlinks", label: "Inlinks" }, { key: "reason", label: "Reason", render: reason }]);
  dataTable("t-can", p.canonicals, [urlCol("url", "Page"), { key: "problem", label: "Problem" }, { key: "current", label: "Current", render: (v) => v ? link(v, shortUrl(v)) : '<span class="muted">none</span>' },
    { key: "target", label: "Suggested canonical", render: (v) => v ? link(v, shortUrl(v)) : '<span class="muted">your call</span>' }, { key: "priority", label: "Priority", render: sev }, { key: "reason", label: "Reason", render: reason }]);
  dataTable("t-dec", p.decisions, [{ key: "keyword", label: "Keyword" }, urlCol("winner", "Primary page"), urlCol("other", "Competing page"), { key: "action", label: "Decision" },
    { key: "similarity", label: "Shared text", render: (v) => v == null ? "" : `${Math.round(v * 100)}%` }, { key: "why", label: "Why", render: reason }, { key: "source", label: "Source" }]);
  dataTable("t-upd", p.link_updates, [{ key: "kind", label: "Change" }, { key: "sources", label: "On pages", render: (v) => `${link(v[0], shortUrl(v[0]))}${v.length > 1 ? `<div class="muted small">and ${v.length - 1} more</div>` : ""}` }, { key: "pages", label: "Pages" }, { key: "current", label: "Current target", render: (v) => v ? link(v, shortUrl(v)) : "" },
    { key: "new", label: "New target", render: (v) => v ? link(v, shortUrl(v)) : '<span class="muted">remove</span>' }, { key: "anchor", label: "Anchor" }, { key: "why", label: "Why", render: reason }]);
  dataTable("t-stuff", p.stuffing, [urlCol(), { key: "keyword", label: "Keyword" }, { key: "where", label: "Where" }, { key: "occurrences", label: "Count" },
    { key: "density", label: "Density", render: (v) => v == null ? "" : `${v}%` }, { key: "severity", label: "Severity", render: sev }, { key: "recommendation", label: "Fix", render: reason }]);
}

/* ---------------- Growth & Decline ---------------- */
const STATUS_CLASS = { improved: "ok", declined: "bad" };
const VERDICT_CLASS = { Growing: "ok", Declining: "bad", Mixed: "warn", Stable: "muted", "No change": "muted" };
function shortDate(s) { return s ? new Date(s).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : ""; }
function shortDateTime(s) { return s ? new Date(s).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : ""; }
function metricValue(v, unit) { return v == null ? '<span class="muted">n/a</span>' : `${esc(typeof v === "number" ? v.toLocaleString() : v)}${esc(unit || "")}`; }
function changeCell(m) {
  if (m.change == null) return '<span class="muted">n/a</span>';
  if (m.change === 0) return '<span class="muted">No change</span>';
  const text = `${m.change > 0 ? "▲ +" : "▼ "}${esc(m.change.toLocaleString())}${esc(m.unit || "")}${m.percent != null && !m.unit ? ` (${m.percent > 0 ? "+" : ""}${m.percent}%)` : ""}`;
  return `<span class="${STATUS_CLASS[m.status] || "muted"}" ${m.status === "unchanged" ? 'title="Within normal variation"' : ""}>${text}</span>`;
}
function metricTable(rows) {
  const groups = [...new Set(rows.map((m) => m.group))];
  return groups.map((g) => `<div class="card"><h3 style="margin-top:0">${esc(g)}</h3><table class="metric-list"><thead><tr><th>Metric</th><th>Before</th><th>After</th><th>Change</th></tr></thead><tbody>
    ${rows.filter((m) => m.group === g).map((m) => `<tr><td>${esc(m.label)}</td><td>${metricValue(m.before, m.unit)}</td><td><b>${metricValue(m.after, m.unit)}</b></td><td>${changeCell(m)}</td></tr>`).join("")}</tbody></table></div>`).join("");
}
const issueLine = (i, note) => `<li>${sev(i.severity)} ${esc(i.title)} <span class="muted small">${esc(note)}</span></li>`;

async function renderGrowth(el, r, s) {
  el.innerHTML = `<div id="g-audits"><p class="muted">Comparing…</p></div><div id="g-periods"></div>`;
  await loadAuditCompare(s);
  if (!s.first_look) await loadPeriodCompare(s, 28);
}

async function loadAuditCompare(s, base, current) {
  const host = $("#g-audits");
  destroyCharts();
  const q = base && current ? `?base=${base}&current=${current}` : "";
  const d = await api(`/api/sites/${s.id}/compare${q}`);
  if (!d.available) {
    host.innerHTML = `<div class="card"><h3 style="margin-top:0">One more audit needed</h3><p>A comparison needs two completed audits. This website has ${d.audits.length}. Click <b>Run audit</b> to take the next snapshot.</p></div>`;
    return;
  }
  const options = (sel) => d.audits.map((a) => `<option value="${a.id}" ${a.id === sel ? "selected" : ""}>${esc(shortDateTime(a.started_at))} · score ${a.score ?? "–"} · ${a.pages_crawled ?? "?"} URLs</option>`).join("");
  const iss = d.issues;
  host.innerHTML = `
    <div class="card row"><div><label>Compare</label><select id="g-base">${options(d.base)}</select></div>
      <div><label>With</label><select id="g-current">${options(d.current)}</select></div></div>
    ${d.warnings.map((w) => `<div class="card notice">${esc(w)}</div>`).join("")}
    <div class="grid g4" style="margin-top:16px">
      <div class="card kpi"><div class="l">Overall trend</div><div class="v ${VERDICT_CLASS[d.verdict]}">${esc(d.verdict)}</div></div>
      <div class="card kpi"><div class="l">Score</div><div class="v">${d.score_before} → ${d.score_after}</div><div class="small ${d.score_change > 0 ? "ok" : d.score_change < 0 ? "bad" : "muted"}">${d.score_change > 0 ? "▲ +" : d.score_change < 0 ? "▼ " : ""}${d.score_change || "No change"}</div></div>
      <div class="card kpi"><div class="l">Metrics improved</div><div class="v ok">${d.improved}</div></div>
      <div class="card kpi"><div class="l">Metrics declined</div><div class="v bad">${d.declined}</div></div>
    </div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><h3>Score over time</h3><div class="chart-box"><canvas id="c-trend"></canvas></div></div>
      <div class="card"><h3>Score by category</h3><div class="chart-box"><canvas id="c-compare"></canvas></div></div>
    </div>
    <h2>Metrics</h2><div class="grid g2">${metricTable(d.metrics)}</div>
    <h2>Issues</h2><div class="grid g2">
      <div class="card"><h3 class="bad" style="margin-top:0">New or worse (${iss.new.length + iss.worse.length})</h3><ul>${iss.new.map((i) => issueLine(i, `new, ${i.count} affected`)).join("")}${iss.worse.map((i) => issueLine(i, `${i.before} → ${i.after} affected`)).join("") || (iss.new.length ? "" : "<li class='muted'>None</li>")}</ul></div>
      <div class="card"><h3 class="ok" style="margin-top:0">Resolved or better (${iss.resolved.length + iss.better.length})</h3><ul>${iss.resolved.map((i) => issueLine(i, "resolved")).join("")}${iss.better.map((i) => issueLine(i, `${i.before} → ${i.after} affected`)).join("") || (iss.resolved.length ? "" : "<li class='muted'>None</li>")}</ul></div>
    </div>
    <h2>Page changes</h2><p class="muted small">${d.page_tally.declined || 0} got worse, ${d.page_tally.improved || 0} got better, and ${d.page_tally.neutral || 0} changed without a clear direction.</p><div id="t-pc"></div>`;
  const onPick = () => { const a = +$("#g-base").value, b = +$("#g-current").value; if (a === b) { toast("Choose two different audits"); return; } loadAuditCompare(s, a, b).catch((e) => toast(e.message)); };
  $("#g-base").onchange = onPick; $("#g-current").onchange = onPick;
  chart("c-trend", { type: "line", data: { labels: d.audits.map((a) => shortDate(a.started_at)), datasets: [{ label: "Score", data: d.audits.map((a) => a.score), borderColor: C.navy, tension: .25 }] }, options: { scales: { y: { suggestedMin: 0, suggestedMax: 100 } } } });
  const cats = d.metrics.filter((m) => m.group === "Score" && m.label !== "Overall score");
  chart("c-compare", { type: "bar", data: { labels: cats.map((m) => m.label), datasets: [{ label: "Before", data: cats.map((m) => m.before), backgroundColor: "#a9b8c9", borderRadius: 3 }, { label: "After", data: cats.map((m) => m.after), backgroundColor: C.navy, borderRadius: 3 }] }, options: { scales: { y: { beginAtZero: true, max: 100 } } } });
  const stateLabel = { improved: "Better", declined: "Worse", neutral: "Changed" };
  dataTable("t-pc", d.pages, [urlCol(), { key: "change", label: "What changed" }, { key: "status", label: "Direction", render: (v) => `<span class="${STATUS_CLASS[v] || "muted"}">${stateLabel[v]}</span>` },
    { key: "before", label: "Before", render: (v) => v == null ? '<span class="muted">none</span>' : `<span class="small">${esc(v)}</span>` }, { key: "after", label: "After", render: (v) => v == null ? '<span class="muted">none</span>' : `<span class="small">${esc(v)}</span>` }]);
}

async function loadPeriodCompare(s, days) {
  const host = $("#g-periods");
  const d = await api(`/api/sites/${s.id}/compare/periods?days=${days}`);
  if (!d.search.has_data && !d.traffic.has_data) {
    host.innerHTML = `<h2>Traffic and rankings</h2><div class="card"><p>No Search Console or GA4 data yet. Click <b>Sync GSC/GA4</b> above, and clicks, rankings and sessions will be compared here.</p></div>`;
    return;
  }
  const sections = [d.search, d.traffic].filter((x) => x.has_data);
  const w = sections[0].window;
  host.innerHTML = `<div class="row space"><h2>Traffic and rankings</h2><div class="row"><label>Period</label><select id="g-days">${[7, 28, 90].map((n) => `<option value="${n}" ${n === d.days ? "selected" : ""}>Last ${n} days</option>`).join("")}</select></div></div>
    <p class="muted small">${esc(w.current[0])} to ${esc(w.current[1])}, compared with ${esc(w.previous[0])} to ${esc(w.previous[1])}.</p>
    ${sections.some((x) => x.partial) ? `<div class="card notice">Not enough history to fill the earlier period, so its totals are low and growth looks larger than it is. Sync more days or choose a shorter period.</div>` : ""}
    <div class="grid g2">${metricTable(sections.flatMap((x) => x.metrics))}</div>
    ${d.search.has_data ? `<p class="small">${d.search.keywords_won} keywords started ranking and ${d.search.keywords_lost} stopped.</p>
      <div class="grid g2"><div><h3>Queries gaining clicks</h3><div id="t-qg"></div></div><div><h3>Queries losing clicks</h3><div id="t-ql"></div></div>
      <div><h3>Pages gaining clicks</h3><div id="t-pg"></div></div><div><h3>Pages losing clicks</h3><div id="t-pl"></div></div></div>` : ""}
    ${d.traffic.has_data ? `<div class="grid g2"><div><h3>Landing pages gaining sessions</h3><div id="t-lg"></div></div><div><h3>Landing pages losing sessions</h3><div id="t-ll"></div></div></div>` : ""}`;
  $("#g-days").onchange = (e) => loadPeriodCompare(s, +e.target.value).catch((err) => toast(err.message));
  const moved = (id, rows, label, render) => dataTable(id, rows, [{ key: "item", label, render }, { key: "before", label: "Before" }, { key: "after", label: "After" },
    { key: "change", label: "Change", render: (v) => `<span class="${v > 0 ? "ok" : "bad"}">${v > 0 ? "+" : ""}${esc(v)}</span>` }], { noFilter: true, limit: 15 });
  const pageCell = (v) => /^https?:/i.test(v) ? link(v, shortUrl(v)) : esc(v);
  if (d.search.has_data) {
    moved("t-qg", d.search.queries.gainers, "Query"); moved("t-ql", d.search.queries.losers, "Query");
    moved("t-pg", d.search.pages.gainers, "Page", pageCell); moved("t-pl", d.search.pages.losers, "Page", pageCell);
  }
  if (d.traffic.has_data) { moved("t-lg", d.traffic.pages.gainers, "Landing page", pageCell); moved("t-ll", d.traffic.pages.losers, "Landing page", pageCell); }
}

function renderCrawl(el, r) {
  el.innerHTML = `<h2>All crawled URLs</h2><div id="t-pages"></div><h2>All issues</h2>${issueList(r.issues)}`;
  dataTable("t-pages", r.pages, [urlCol(), { key: "status", label: "Status" }, { key: "indexable", label: "Indexable", render: (v) => v ? "✓" : "✗" }, { key: "title", label: "Title" },
    { key: "words", label: "Words" }, { key: "inlinks", label: "Inlinks" }, { key: "depth", label: "Depth" }, { key: "ms", label: "ms" }, { key: "schema", label: "Schema" },
    { key: "primary_keyword", label: "Primary keyword" }, { key: "page_type", label: "Type" }, { key: "aio_score", label: "AIO" }]);
}

route();

/* ---------------- Ahrefs ---------------- */
function mdBold(t) { return esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>"); }

async function renderAhrefs(el, s) {
  const data = await api(`/api/sites/${s.id}/ahrefs`);
  if (!data.configured) {
    el.innerHTML = `<div class="card"><h3>Connect Ahrefs</h3><p>Add your Ahrefs <b>API key</b> in <a href="#/settings">Settings</a> (Ahrefs → Account settings → API keys). Every website that is a project in your Ahrefs account then gets this analysis: overview metrics explained, conversions, content gap and strategy.</p></div>`;
    return;
  }
  const r = data.report;
  el.innerHTML = `<div class="card row space"><div><h3 style="margin:0">Ahrefs site analysis</h3>
      <div class="muted small">${r ? "Last run " + fmtDate(r.generated_at) : "Not run yet for this website."} ${r && r.project ? "· Project: " + esc(r.project.project_name) + " (" + esc(r.project.url) + ")" : r ? "· <b>No matching Ahrefs project</b>" : ""}</div></div>
      <div class="row"><label class="small" style="margin:0"><input type="checkbox" id="a-gap" checked style="width:auto"> Include content gap</label>
      <button class="btn gold" id="a-run">${r ? "Run again" : "Run Ahrefs analysis"}</button></div></div><div id="a-body"></div>`;
  $("#a-run").onclick = async () => {
    const b = $("#a-run"); b.disabled = true; b.textContent = "Running… (up to a minute)";
    try { await api(`/api/sites/${s.id}/ahrefs?gap=${$("#a-gap").checked ? 1 : 0}`, { method: "POST" }); route(); }
    catch (e) { toast(e.message, 10000); b.disabled = false; b.textContent = "Run Ahrefs analysis"; }
  };
  if (!r) return;
  const body = $("#a-body");
  const plan = r.plan || {};
  const statusIcon = (ok) => ok === true ? '<span class="ok">✓</span>' : ok === false ? '<span class="bad">✗</span>' : '<span class="muted">?</span>';
  body.innerHTML = `
    <div class="card" style="margin-top:12px"><h3>Headline</h3><p>${mdBold(r.headline)}</p>
      <div class="row" style="gap:6px;flex-wrap:wrap">${r.chain.map((c, i) => `${i ? '<span class="muted">→</span>' : ""}<span class="pill ${c.ok === false ? "sev-critical" : c.ok ? "sev-low" : ""}">${statusIcon(c.ok)} ${esc(c.step)}</span>`).join(" ")}</div>
      <p class="muted small">Plan: ${esc(plan.subscription || "?")} · API units left: ${plan.units_left == null ? "unlimited" : plan.units_left.toLocaleString()} · a full run uses about ${plan.estimate ? plan.estimate.toLocaleString() : "?"} units.</p>
      ${r.skipped.length ? `<div class="issue medium"><b>Not included this time</b><ul>${r.skipped.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}</div>
    ${Object.keys(r.indexed || {}).length ? `<div class="card" style="margin-top:12px"><h3>Performance, indexed (first month = 100)</h3><p class="muted small">Every metric starts at 100, so lines on very different scales fit on one chart. A line that falls below 100 has dropped since the first month.</p><div class="chart-box tall"><canvas id="c-idx"></canvas></div></div>` : ""}
    <h2>Part A: Overview, explained</h2>
    <div class="grid g2">${r.cards.map((c) => `<div class="card" style="border-left:4px solid ${c.status === "warn" ? "var(--amber)" : c.status === "info" ? "var(--border)" : "var(--green)"}">
      <h3 style="margin-top:0">${esc(c.title)}</h3><p class="small"><b>What it is:</b> ${esc(c.what)}</p><p><b>${esc(c.value)}</b></p>
      <p class="small"><b>Effect on organic search:</b> ${esc(c.effect)}</p><p class="small"><b>Action:</b> ${esc(c.action)}</p></div>`).join("") || '<div class="card muted">No overview metrics yet.</div>'}</div>
    ${r.competitors && r.competitors.length ? `<h3>Top organic competitors</h3><div id="t-ac"></div>` : ""}
    <h2>Part B: Conversions (GA4)</h2><div id="a-conv"></div>
    <h2>Part C: Content gap</h2><div id="a-gap-body"></div>
    <h2>Biggest issues</h2><div class="card">${r.issues.length ? `<ol>${r.issues.map((i) => `<li><b>${esc(i.title)}:</b> ${esc(i.detail)}</li>`).join("")}</ol>` : '<p class="ok">No major issue found in the data available.</p>'}</div>
    <div class="grid g2" style="margin-top:12px"><div class="card"><h3>Quick wins</h3><ul>${r.quick_wins.map((x) => `<li>${esc(x)}</li>`).join("") || "<li class='muted'>None yet</li>"}</ul></div>
      <div class="card"><h3>Long-term work</h3><ul>${r.long_term.map((x) => `<li>${esc(x)}</li>`).join("") || "<li class='muted'>None yet</li>"}</ul></div></div>
    <div class="card" style="margin-top:12px"><b>Next step:</b> ${esc(r.next_step)}</div>`;
  const idx = r.indexed || {};
  if (Object.keys(idx).length) {
    const months = [...new Set(Object.values(idx).flatMap((v) => v.map((p) => p.month)))].sort();
    chart("c-idx", { type: "line", data: { labels: months, datasets: Object.entries(idx).map(([name, pts], i) => {
      const m = Object.fromEntries(pts.map((p) => [p.month, p.index])); return { label: name, data: months.map((x) => m[x] ?? null), borderColor: PALETTE[i % 8], spanGaps: true, tension: .25 }; }) },
      options: { plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y}` } } } } });
  }
  if (r.competitors && r.competitors.length) dataTable("t-ac", r.competitors, [{ key: "competitor_domain", label: "Competitor" }, { key: "domain_rating", label: "DR" },
    { key: "keywords_common", label: "Shared keywords" }, { key: "keywords_competitor", label: "Only they rank" }, { key: "keywords_target", label: "Only you rank" }, { key: "traffic", label: "Traffic" }], { noFilter: true });
  const cv = r.conversions || {};
  const conv = $("#a-conv");
  if (!cv.available) conv.innerHTML = `<div class="card muted">${esc(cv.reason || "Not available.")}</div>`;
  else {
    conv.innerHTML = `${cv.warning ? `<div class="issue critical"><b>Fake key events found.</b> ${esc(cv.warning)}</div>` : ""}
      <div class="card"><h3>Real leads per month</h3><div class="chart-box"><canvas id="c-leads"></canvas></div></div><div id="t-ev" style="margin-top:12px"></div>`;
    chart("c-leads", barCfg(cv.months, cv.months.map((m) => cv.leads_by_month[m]), "Leads", C.green));
    dataTable("t-ev", cv.events, [{ key: "event", label: "Key event" }, { key: "kind", label: "Type", render: (v) => `<span class="pill ${v === "fake" ? "sev-critical" : v === "lead" ? "sev-low" : ""}">${esc(v)}</span>` },
      { key: "total", label: "Total (12 mo)" }, { key: "first_month", label: "Tracked since" }], { noFilter: true });
  }
  const g = r.gap, gb = $("#a-gap-body");
  if (!g) gb.innerHTML = `<div class="card muted">Not run. ${r.skipped.some((x) => /units/i.test(x)) ? "It needs Ahrefs API units." : "Tick “Include content gap” and add a competitor in the site's settings, or let it use the top organic competitor."}</div>`;
  else {
    gb.innerHTML = `<p class="muted small">${esc(g.method)} Competitor: <b>${esc(g.competitor)}</b>.</p>
      <div class="grid g2"><div class="card"><h3>Where the competitor's traffic comes from</h3><div class="chart-box"><canvas id="c-sec"></canvas></div></div>
      <div class="card"><h3>Gap topics by priority (searches/month)</h3><div class="chart-box"><canvas id="c-top"></canvas></div></div></div>
      <div class="issue medium" style="margin-top:12px">Informational topics bring back impressions and AI citations, but they <b>won't fix a drop in commercial leads on their own</b>. Do priority 1 first. For every new page: a two-sentence definition at the top, an example, an FAQ section and a named author.</div>
      <h3>Topics (gap)</h3><div id="t-topics"></div><h3>Shared keywords: where the competitor wins</h3><div id="t-shared"></div>
      <details class="issue low"><summary>Skipped keywords (${g.skipped.length})</summary><p class="small">${g.skipped.map((k) => esc(k.keyword) + " (" + esc(k.why) + ")").join(" · ")}</p></details>`;
    chart("c-sec", barCfg(g.competitor_sections.map((x) => x.section), g.competitor_sections.map((x) => x.keywords), "Keywords", C.slate, true));
    const tops = g.topics.slice(0, 12);
    chart("c-top", barCfg(tops.map((t) => t.topic), tops.map((t) => t.volume), "Searches/month", tops.map((t) => t.priority === 1 ? C.red : t.priority === 2 ? C.gold : C.slate), true));
    dataTable("t-topics", g.topics, [{ key: "priority", label: "Priority", render: (v) => `<span class="pill ${v === 1 ? "sev-critical" : v === 2 ? "sev-medium" : "sev-low"}">P${v}</span>` },
      { key: "topic", label: "Topic" }, { key: "keywords", label: "Keywords", render: (v) => esc(v.slice(0, 6).join(", ")) }, { key: "volume", label: "Searches/mo" },
      { key: "kd", label: "KD" }, { key: "competitor_position", label: "Competitor pos." }, { key: "intent", label: "Intent" }, { key: "action", label: "Action" }]);
    dataTable("t-shared", g.shared, [{ key: "keyword", label: "Keyword" }, { key: "volume", label: "Volume" }, { key: "competitor_position", label: "Competitor" },
      { key: "target_position", label: "You" }, { key: "winner", label: "Winner", render: (v) => `<span class="${v === "you" ? "ok" : "bad"}">${esc(v)}</span>` }]);
  }
}
