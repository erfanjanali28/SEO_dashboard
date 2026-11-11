"""Ahrefs site analysis + content gap, built into the dashboard.

Follows the agency's Ahrefs site-analysis workflow:

* Part A, overview: Site Explorer metrics, Domain Rating, backlinks and
  12-month histories, each explained as what it is, this domain's value,
  its effect on organic search, and an action. Includes the chain
  inputs → impressions → clicks → leads and the broken link in it.
* Part B, conversions: GA4 key events by month (via Windsor.ai), with
  fake key events (cookie consent, generic click, page_view) flagged and
  removed from the lead count.
* Part C, content gap: a competitor's top keywords vs. the target's,
  grouped into topics and prioritized (commercial/local first, then
  low-difficulty informational quick wins), plus the shared keywords.

Paid Site Explorer calls only run when the workspace has API units; free
data (project match, public DR, GSC Insights, Windsor.ai GSC/GA4 and the
dashboard's own crawl) is always used, and the report says what was
skipped and why.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, timedelta

from .. import db
from ..integrations import ahrefs, windsor

COMP_ROWS = 200     # competitor keywords, sorted by volume (the skill's 200-row method)
TARGET_ROWS = 500   # target keywords, for membership and shared-keyword positions
# Ahrefs charges per row for these columns (docs: volume, KD, traffic = 10 units each).
UNIT_ESTIMATE = COMP_ROWS * 30 + TARGET_ROWS * 10 + 600

FAKE_EVENT = re.compile(r"cookie|consent|souhlas|nesouhlas|^click$|page_view|scroll|session_start|first_visit|user_engagement", re.I)
REAL_EVENT = re.compile(r"form|lead|contact|kontakt|submit|purchase|copy_email|copy_phone|call|phone|tel|mail|book|rezerv|sign_up|whatsapp|quote|poptav|order|objedn", re.I)
STOP = set("""a an the of for to in on at by and or with without from is are what how why when where which who best top vs
co je jak proc kde kdy ktery ktera ktere pro na v ve s se z za do od o u k ke i a nebo jako cena ceny
čo ako prečo kde kedy ktorý pre na v vo s so z zo do od o u k ku i a alebo""".split())


def _month(s) -> str:
    return str(s)[:7]


def _pct(a, b):
    return round((a - b) / b * 100, 1) if b else None


def _first_last(series: list[tuple[str, float]]):
    vals = [(m, v) for m, v in series if v is not None]
    return (vals[0], vals[-1]) if vals else (None, None)


def _peak_drop(series: list[tuple[str, float]]):
    vals = [(m, v) for m, v in series if v is not None]
    if not vals:
        return None
    peak = max(vals, key=lambda x: x[1])
    last = vals[-1]
    return {"peak_month": peak[0], "peak": peak[1], "last_month": last[0], "last": last[1], "change_pct": _pct(last[1], peak[1])}


def _gsc_monthly(site: dict, project: dict | None, since: str) -> tuple[list[dict], str]:
    rows = db.rows("SELECT substr(date,1,7) m, SUM(clicks) clicks, SUM(impressions) impressions FROM search_metrics "
                   "WHERE site_id = ? AND date >= ? GROUP BY m ORDER BY m", (site["id"], since))
    if rows:
        return [{"month": r["m"], "clicks": r["clicks"], "impressions": r["impressions"]} for r in rows], "Search Console via Windsor.ai"
    if project:
        hist = ahrefs.gsc_history(project["project_id"], since)
        if hist:
            return [{"month": _month(h["date"]), "clicks": h.get("clicks"), "impressions": h.get("impressions")} for h in hist], "Search Console via Ahrefs GSC Insights"
    return [], ""


def ga4_conversions(site: dict) -> dict:
    """Part B: key events by month and event, fake ones flagged."""
    key = db.get_setting("windsor_api_key")
    if not key:
        return {"available": False, "reason": "Add a Windsor.ai API key to check GA4 conversions (Ahrefs does not track conversions)."}
    try:
        chosen, _notes = windsor.resolve_accounts(site, key)
        if not chosen.get("ga4"):
            return {"available": False, "reason": "No GA4 property matched this website. Pick one under the site's Settings / schedule."}
        rows = windsor.fetch(windsor.GA4, ["account_id", "date", "event_name", "conversions", "sessions"], key, days=365, account=chosen["ga4"])
    except windsor.WindsorError as exc:
        return {"available": False, "reason": f"GA4 via Windsor.ai: {exc}"}
    by = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if (r.get("conversions") or 0) > 0:
            by[r.get("event_name") or "(not set)"][_month(windsor._norm_date(r.get("date")))] += r.get("conversions") or 0
    months = sorted({m for ev in by.values() for m in ev})
    events = []
    for name, per in by.items():
        kind = "fake" if FAKE_EVENT.search(name) else "lead" if REAL_EVENT.search(name) else "other"
        events.append({"event": name, "kind": kind, "total": round(sum(per.values())), "first_month": min(per),
                       "by_month": {m: round(per.get(m, 0)) for m in months}})
    events.sort(key=lambda e: (-(e["kind"] == "lead"), -e["total"]))
    fake = [e for e in events if e["kind"] == "fake"]
    leads_by_month = {m: sum(e["by_month"][m] for e in events if e["kind"] == "lead") for m in months}
    return {"available": True, "property": chosen["ga4"], "months": months, "events": events,
            "leads_by_month": leads_by_month, "fake_events": [e["event"] for e in fake],
            "warning": (f"{', '.join(e['event'] for e in fake)} {'is' if len(fake) == 1 else 'are'} counted as key events. "
                        "They are not leads, so they inflate the conversion total and can make period comparisons show a fake crash. "
                        "Unmark them as key events in GA4 (Admin → Events).") if fake else None}


def _topic_key(kw: str, freq: Counter) -> str:
    toks = [t for t in re.findall(r"\w+", kw.lower()) if t not in STOP and len(t) > 2]
    if not toks:
        return kw.lower()
    return max(toks, key=lambda t: (freq[t], len(t)))


def content_gap(target: str, competitor: str, country: str) -> dict:
    today = date.today().isoformat()
    sel = "keyword,volume,keyword_difficulty,best_position,sum_traffic,best_position_url,is_commercial,is_local,is_transactional,is_informational,is_branded,is_navigational"
    comp = ahrefs.get("site-explorer/organic-keywords", {"target": competitor, "date": today, "country": country, "mode": "subdomains",
                                                         "select": sel, "order_by": "volume:desc", "limit": COMP_ROWS}).get("keywords", [])
    tgt = ahrefs.get("site-explorer/organic-keywords", {"target": target, "date": today, "country": country, "mode": "subdomains",
                                                        "select": "keyword,best_position,volume", "order_by": "volume:desc", "limit": TARGET_ROWS}).get("keywords", [])
    tpos = {k["keyword"].lower(): k.get("best_position") for k in tgt if k.get("keyword")}
    gap = [k for k in comp if k.get("keyword") and k["keyword"].lower() not in tpos]
    shared = [{"keyword": k["keyword"], "volume": k.get("volume"), "competitor_position": k.get("best_position"),
               "target_position": tpos[k["keyword"].lower()],
               "winner": "competitor" if (k.get("best_position") or 999) < (tpos[k["keyword"].lower()] or 999) else "you"}
              for k in comp if k.get("keyword") and k["keyword"].lower() in tpos]
    freq = Counter(t for k in gap for t in set(re.findall(r"\w+", k["keyword"].lower())) if t not in STOP and len(t) > 2)
    topics, skipped = defaultdict(list), []
    for k in gap:
        if k.get("is_navigational") or k.get("is_branded"):
            skipped.append({"keyword": k["keyword"], "volume": k.get("volume"), "why": "brand or navigation search"})
            continue
        topics[_topic_key(k["keyword"], freq)].append(k)
    rows = []
    for topic, kws in topics.items():
        vol = sum(k.get("volume") or 0 for k in kws)
        kds = [k["keyword_difficulty"] for k in kws if k.get("keyword_difficulty") is not None]
        pos = [k["best_position"] for k in kws if k.get("best_position")]
        commercial = any(k.get("is_commercial") or k.get("is_local") or k.get("is_transactional") for k in kws)
        kd = round(sum(kds) / len(kds)) if kds else None
        comp_pos = min(pos) if pos else None
        if commercial:
            priority, action = 1, "Build or strengthen a service/commercial page. These searches bring leads."
        elif kd is not None and kd < 20:
            priority = 2
            action = "Quick win: write an answer-first article (two-sentence definition, an example, FAQ, named author)."
            if comp_pos and comp_pos > 10:
                action += " Winnable: the competitor itself ranks below position 10."
        else:
            priority, action = 3, "Longer-term informational content. Brings impressions and AI citations, not leads by itself."
        top_url = kws[0].get("best_position_url") or ""
        rows.append({"topic": topic, "keywords": [k["keyword"] for k in sorted(kws, key=lambda k: -(k.get("volume") or 0))][:12],
                     "keyword_count": len(kws), "volume": vol, "kd": kd, "competitor_position": comp_pos, "priority": priority,
                     "intent": "commercial/local" if commercial else "informational", "action": action,
                     "competitor_url": re.sub(r"^https?://[^/]+", "", top_url)})
    rows.sort(key=lambda r: (r["priority"], -r["volume"]))
    paths = Counter((re.sub(r"^https?://[^/]+", "", k.get("best_position_url") or "").split("/") + ["", ""])[1] for k in comp)
    source = [{"section": "/" + p + "/" if p else "/", "keywords": n} for p, n in paths.most_common(6)]
    return {"competitor": competitor, "country": country, "competitor_rows": len(comp), "target_rows": len(tgt),
            "topics": rows, "shared": sorted(shared, key=lambda s: -(s["volume"] or 0))[:60], "skipped": skipped[:40],
            "competitor_sections": source,
            "method": f"Manual content gap: the competitor's top {len(comp)} keywords by search volume in {country}, "
                      f"compared with the target's top {len(tgt)}. Keywords outside those lists are not compared."}


def _explain(metric: str, ctx: dict) -> dict:
    """What it is → this domain's value → SEO effect → action."""
    t = {
        "refdomains": ("Unique websites linking to the site.",
                       "Links are the main input for authority. Growth only helps when it comes from relevant sites with real authority."),
        "dr": ("Domain Rating: the strength of the whole domain's backlink profile on a 0–100 scale.",
               "A higher DR makes every page easier to rank. It rises slowly and only with links from strong sites."),
        "traffic": ("Ahrefs' estimate of monthly organic visits from the keywords it tracks.",
                    "It is an estimate. Always compare it with GA4 organic sessions, because a flat line can hide long-tail losses."),
        "keywords": ("The number of keywords the site ranks for in the top 100.",
                     "Coverage: more ranking keywords means more chances to be found. Compare it with competitors."),
        "top3": ("Keywords ranking in positions 1–3.",
                 "Top-3 positions get most of the clicks. Strong top-3 but few keywords means good rankings with too little coverage."),
        "impressions": ("How often the site appears in Google results (Search Console).",
                        "The earliest warning sign: impressions fall first, then clicks, then leads."),
        "crawled": ("Pages the crawler could reach, by HTTP status.",
                    "Non-200 pages waste crawl budget and leak link equity. Fixing them is a quick win."),
        "intent": ("Ranking keywords split by search intent.",
                   "Commercial, local and transactional keywords bring leads. Informational ones bring visibility and AI citations."),
    }[metric]
    return {"what": t[0], "effect": t[1], **ctx}


def build(site: dict, audit_result: dict | None = None, run_gap: bool = True) -> dict:
    today = date.today()
    since = (today.replace(day=1) - timedelta(days=365)).replace(day=1).isoformat()
    domain = ahrefs.domain_of(site["url"])
    out = {"domain": domain, "generated_at": db.now_iso(), "sections": [], "skipped": [], "notes": []}
    lim = ahrefs.limits()
    units_left = None
    if lim.get("units_limit_workspace") is not None:
        units_left = (lim.get("units_limit_workspace") or 0) - (lim.get("units_usage_workspace") or 0)
    out["plan"] = {"subscription": lim.get("subscription"), "units_left": units_left, "reset": lim.get("usage_reset_date"),
                   "estimate": UNIT_ESTIMATE if run_gap else 600}
    project = None
    if site.get("ahrefs_project_id"):
        project = next((p for p in ahrefs.projects() if str(p["project_id"]) == str(site["ahrefs_project_id"])), None)
    if not project:
        project = ahrefs.match_project(site["url"], ahrefs.projects())
    out["project"] = project
    paid = units_left is None or units_left > 0
    if not paid:
        out["skipped"].append("Site Explorer metrics, histories, competitors and the content gap need Ahrefs API units, "
                              f"and this workspace has 0 ({lim.get('subscription') or 'current plan'}). They run automatically once units are available.")

    # ---------- Part A ----------
    metrics, bl, dr, hist, rd_hist, dr_hist, comps, intents = {}, {}, None, [], [], [], [], {}
    country = ahrefs.country_for(site)
    if paid:
        try:
            p = {"target": domain, "date": today.isoformat(), "mode": "subdomains"}
            metrics = ahrefs.get("site-explorer/metrics", p).get("metrics", {})
            bl = ahrefs.get("site-explorer/backlinks-stats", p).get("metrics", {})
            d = ahrefs.get("site-explorer/domain-rating", {"target": domain, "date": today.isoformat()}).get("domain_rating", {})
            dr, out["ahrefs_rank"] = d.get("domain_rating"), d.get("ahrefs_rank")
            h = {"target": domain, "date_from": since, "history_grouping": "monthly", "mode": "subdomains"}
            hist = ahrefs.get("site-explorer/metrics-history", {**h, "select": "date,org_traffic,org_cost"}).get("metrics", [])
            rd_hist = ahrefs.get("site-explorer/refdomains-history", h).get("refdomains", [])
            dr_hist = ahrefs.get("site-explorer/domain-rating-history", {k: v for k, v in h.items() if k != "mode"}).get("domain_ratings", [])
            comps = ahrefs.get("site-explorer/organic-competitors", {"target": domain, "date": today.isoformat(), "country": country, "mode": "subdomains",
                                                                     "select": "competitor_domain,domain_rating,keywords_common,keywords_competitor,keywords_target,traffic,share",
                                                                     "order_by": "keywords_common:desc", "limit": 8}).get("competitors", [])
            kws = ahrefs.get("site-explorer/organic-keywords", {"target": domain, "date": today.isoformat(), "country": country, "mode": "subdomains",
                                                                "select": "keyword,is_branded,is_commercial,is_local,is_transactional,is_informational",
                                                                "order_by": "sum_traffic:desc", "limit": 1000}).get("keywords", [])
            intents = {k: sum(1 for x in kws if x.get(f"is_{k}")) for k in ("branded", "commercial", "local", "transactional", "informational")}
        except ahrefs.UnitsError as exc:
            paid = False
            out["skipped"].append(f"Ahrefs stopped paid calls part-way: {exc}")
    if dr is None:
        dr = ahrefs.free_domain_rating(domain)
    gsc, gsc_source = _gsc_monthly(site, project, since)

    cards = []
    rd_series = [(_month(r["date"]), r.get("refdomains")) for r in rd_hist]
    dr_series = [(_month(r["date"]), r.get("domain_rating")) for r in dr_hist]
    (rd0, rd1), (dr0, dr1) = _first_last(rd_series), _first_last(dr_series)
    if bl or rd1:
        live = bl.get("live_refdomains") or (rd1 or (None, None))[1]
        allt = bl.get("all_time_refdomains")
        rd_growth = _pct(rd1[1], rd0[1]) if rd0 and rd1 else None
        dr_change = round(dr1[1] - dr0[1], 1) if dr0 and dr1 else None
        flat_dr = rd_growth is not None and rd_growth > 20 and (dr_change or 0) < 1
        value = f"{live} referring domains now" + (f" ({rd_growth:+}% in 12 months)" if rd_growth is not None else "") + (f", {allt} all-time" if allt else "")
        action = ("Referring domains grew but DR stayed flat: the new links are low-quality (likely nofollow or from weak sites). "
                  "Stop volume link building and earn 10–20 relevant links from DR 40+ sites." if flat_dr else
                  f"{allt - live} linking domains have been lost over time: check lost links and reclaim the valuable ones." if allt and live and allt > live * 1.5 else
                  "Keep earning relevant links. Quality beats volume.")
        cards.append(_explain("refdomains", {"key": "refdomains", "title": "Referring domains", "value": value, "action": action,
                                             "status": "warn" if flat_dr else "ok"}))
    if dr is not None:
        dr_change = round(dr1[1] - dr0[1], 1) if dr0 and dr1 else None
        cards.append(_explain("dr", {"key": "dr", "title": "Domain Rating", "value": f"DR {dr}" + (f" ({dr_change:+} in 12 months)" if dr_change is not None else "")
                                     + (f", Ahrefs Rank #{out.get('ahrefs_rank'):,}" if out.get("ahrefs_rank") else ""),
                                     "action": "The 12-month DR trend needs Ahrefs API units. A DR that is not rising needs 10–20 relevant links from DR 40+ sites, not more links in volume." if dr_change is None
                                     else "DR is not rising: you need around 10–20 relevant links from DR 40+ sites, not more links in volume." if dr_change <= 0
                                     else "DR is rising. Keep the link quality bar high.",
                                     "status": "info" if dr_change is None else "warn" if dr_change <= 0 else "ok"}))
    if metrics:
        tr = [(_month(r["date"]), r.get("org_traffic")) for r in hist]
        pd = _peak_drop(tr)
        cards.append(_explain("traffic", {"key": "traffic", "title": "Organic traffic (Ahrefs estimate)",
                                          "value": f"{metrics.get('org_traffic', 0):,} visits/month, worth about ${round((metrics.get('org_cost') or 0) / 100):,}"
                                          + (f"; {pd['change_pct']:+}% since the {pd['peak_month']} peak" if pd and pd['change_pct'] else ""),
                                          "action": (f"Estimated traffic fell {pd['change_pct']}% since {pd['peak_month']}. Confirm it with GA4 Organic Search sessions, then find which pages and keywords lost positions in Ahrefs (Organic keywords → Lost) and refresh or re-link those pages."
                                                     if pd and (pd["change_pct"] or 0) < -20 else "Compare with GA4 Organic Search sessions before drawing conclusions."),
                                          "status": "warn" if pd and (pd["change_pct"] or 0) < -20 else "ok"}))
        kw, top3 = metrics.get("org_keywords", 0), metrics.get("org_keywords_1_3", 0)
        bigger = [c for c in comps if (c.get("keywords_common", 0) + c.get("keywords_competitor", 0)) > kw * 2]
        cards.append(_explain("keywords", {"key": "keywords", "title": "Ranking keywords", "value": f"{kw:,} keywords in the top 100",
                                           "action": (f"Competitors such as {', '.join(c['competitor_domain'] for c in bigger[:3])} rank for far more keywords. Coverage, not rankings, is the gap: see the content gap."
                                                      if bigger else "Grow coverage with the content-gap topics below."), "status": "warn" if bigger else "ok"}))
        cards.append(_explain("top3", {"key": "top3", "title": "Top-3 positions", "value": f"{top3:,} keywords in positions 1–3 ({round(top3 / kw * 100) if kw else 0}% of all)",
                                       "action": "Strong rankings, too little coverage: publish more pages on related topics." if kw and top3 / kw > 0.2
                                       else "Push the striking-distance keywords (positions 4–10) into the top 3 with internal links and content updates.", "status": "ok"}))
    if intents:
        lead_kw = intents["commercial"] + intents["local"] + intents["transactional"]
        cards.append(_explain("intent", {"key": "intent", "title": "Keywords by intent", "value": ", ".join(f"{k}: {v}" for k, v in intents.items()),
                                         "action": "No transactional keywords: there are no buy-intent pages. Build service/offer pages." if not intents["transactional"]
                                         else "Protect and expand the commercial and local keywords. They are the ones that bring leads.",
                                         "status": "warn" if not lead_kw else "ok"}))
    imp_pd = _peak_drop([(g["month"], g["impressions"]) for g in gsc])
    if gsc:
        cards.append(_explain("impressions", {"key": "impressions", "title": "Impressions", "value":
                     f"{round(gsc[-1]['impressions'] or 0):,} in {gsc[-1]['month']}" + (f"; peak {round(imp_pd['peak']):,} in {imp_pd['peak_month']} ({imp_pd['change_pct']:+}%)" if imp_pd and imp_pd['change_pct'] else "") + f". Source: {gsc_source}",
                     "action": "Impressions are falling: check which pages and queries lost visibility (Rankings & Traffic tab), compare the timing with Google updates, and check whether AI Overviews now answer those queries."
                     if imp_pd and (imp_pd["change_pct"] or 0) < -15 else "Impressions are stable or growing.", "status": "warn" if imp_pd and (imp_pd["change_pct"] or 0) < -15 else "ok"}))
    if audit_result:
        sc = audit_result.get("technical", {}).get("status_counts", {})
        bad = sum(v for k, v in sc.items() if k != "2xx")
        cards.append(_explain("crawled", {"key": "crawled", "title": "Crawled pages", "value": ", ".join(f"{k}: {v}" for k, v in sc.items()) + " (from this dashboard's latest audit)",
                                          "action": f"Fix the {bad} non-200 URLs (redirect targets, 404s) and update internal links. See the Technical tab." if bad else "All crawled pages return 200.",
                                          "status": "warn" if bad else "ok"}))
    out["cards"] = cards
    out["competitors"] = comps

    # Indexed performance chart: every series = 100 in its first month
    series = {"Referring domains": rd_series, "Domain Rating": dr_series,
              "Organic traffic (Ahrefs)": [(_month(r["date"]), r.get("org_traffic")) for r in hist],
              "Impressions (GSC)": [(g["month"], g["impressions"]) for g in gsc], "Clicks (GSC)": [(g["month"], g["clicks"]) for g in gsc]}
    indexed = {}
    for name, s in series.items():
        s = [(m, v) for m, v in s if v]
        if len(s) >= 2:
            base = s[0][1]
            indexed[name] = [{"month": m, "index": round(v / base * 100, 1), "value": v} for m, v in s]
    out["indexed"] = indexed

    # ---------- Part B ----------
    conv = ga4_conversions(site)
    out["conversions"] = conv

    # ---------- the chain ----------
    chain = []
    inputs = [c for c in cards if c["key"] in ("refdomains", "dr", "crawled") and c["status"] in ("ok", "warn")]
    chain.append({"step": "Inputs (links, pages, content)", "ok": None if not inputs else not any(c["status"] == "warn" for c in inputs)})
    chain.append({"step": "Impressions", "ok": not (imp_pd and (imp_pd["change_pct"] or 0) < -15) if gsc else None})
    clk = _peak_drop([(g["month"], g["clicks"]) for g in gsc])
    chain.append({"step": "Clicks", "ok": not (clk and (clk["change_pct"] or 0) < -15) if gsc else None})
    leads = list(conv.get("leads_by_month", {}).values()) if conv.get("available") else []
    lead_drop = _pct(sum(leads[-3:]), sum(leads[-6:-3])) if len(leads) >= 6 else None
    chain.append({"step": "Leads", "ok": None if not leads else not (lead_drop is not None and lead_drop < -20)})
    broken = next((c["step"] for c in chain if c["ok"] is False), None)
    out["chain"] = chain
    out["headline"] = (f"The chain breaks at **{broken}**." if broken else "No link in the chain inputs → impressions → clicks → leads is clearly broken with the data available.") + (
        f" Domain Rating is {dr}." if dr is not None else "") + (" Paid Ahrefs metrics were skipped (no API units)." if not paid else "")

    # ---------- Part C ----------
    if run_gap and paid:
        comp = next((c.strip() for c in (site.get("competitors") or "").split(",") if c.strip()), None)
        comp = ahrefs.domain_of(comp) if comp else (comps[0]["competitor_domain"] if comps else None)
        if comp:
            try:
                out["gap"] = content_gap(domain, comp, country)
            except ahrefs.UnitsError as exc:
                out["skipped"].append(f"Content gap skipped: {exc}")
        else:
            out["skipped"].append("Content gap skipped: add a competitor domain to the site's settings (no organic competitor was found).")

    # ---------- issues & quick wins ----------
    issues = [{"title": c["title"], "detail": c["action"]} for c in cards if c["status"] == "warn"]
    if conv.get("warning"):
        issues.insert(0, {"title": "Fake key events in GA4", "detail": conv["warning"]})
    gap = out.get("gap") or {}
    p1 = [t for t in gap.get("topics", []) if t["priority"] == 1][:3]
    p2 = [t for t in gap.get("topics", []) if t["priority"] == 2][:3]
    out["issues"] = issues[:4]
    out["quick_wins"] = ([f"Remove fake key events: {', '.join(conv['fake_events'])}"] if conv.get("fake_events") else []) + \
        [f"Write '{t['topic']}' ({t['volume']:,} searches/month, KD {t['kd']})" for t in p2] + \
        [c["action"] for c in cards if c["key"] == "crawled" and c["status"] == "warn"]
    out["long_term"] = [f"Commercial page for '{t['topic']}' ({t['volume']:,} searches/month)" for t in p1] + \
        [c["action"] for c in cards if c["key"] in ("refdomains", "dr") and c["status"] == "warn"]
    out["next_step"] = "Turn the content-gap topics into a content calendar (Excel export), starting with priority-1 topics."
    return out


def run(site_id: int, run_gap: bool = True) -> dict:
    site = db.row("SELECT * FROM sites WHERE id = ?", (site_id,))
    a = db.row("SELECT * FROM audits WHERE site_id = ? AND status='done' ORDER BY id DESC LIMIT 1", (site_id,))
    result = build(site, db.load_audit_result(a), run_gap=run_gap)
    import json
    db.execute("INSERT INTO ahrefs_reports(site_id, created_at, result) VALUES(?,?,?)", (site_id, result["generated_at"], json.dumps(result, default=str)))
    return result
