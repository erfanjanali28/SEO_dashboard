"""Audit pipeline: crawl → analyzers → scores/priorities/roadmap → SQLite."""

from __future__ import annotations

import json
import threading
import traceback
from collections import Counter
from urllib.parse import urlparse

from . import db, metrics
from .analyzers import content, conversion, geo, html_pages, indexable, keywords, links, offpage, performance, priorities, technical
from .crawler import crawl
from .integrations import dataforseo

_running: dict[int, threading.Thread] = {}


def _progress(audit_id: int):
    def cb(msg: str):
        db.execute("UPDATE audits SET progress = ? WHERE id = ?", (msg, audit_id))
    return cb


def run_audit(site_id: int, audit_id: int | None = None) -> int:
    site = db.row("SELECT * FROM sites WHERE id = ?", (site_id,))
    if not site:
        raise ValueError("site not found")
    if audit_id is None:
        audit_id = db.execute("INSERT INTO audits(site_id, status, progress, started_at) VALUES(?, 'running', 'Starting', ?)",
                              (site_id, db.now_iso()))
    cb = _progress(audit_id)
    try:
        result = build_result(site, cb)
        sev = Counter(i["severity"] for i in result["issues"])
        db.execute(
            "UPDATE audits SET status='done', progress='Complete', finished_at=?, score=?, pages_crawled=?, "
            "issues_critical=?, issues_high=?, issues_medium=?, issues_low=?, result=? WHERE id=?",
            (db.now_iso(), result["scores"]["overall"], result["meta"]["pages_crawled"], sev["critical"], sev["high"],
             sev["medium"], sev["low"], json.dumps(result, default=str), audit_id))
        db.execute("UPDATE sites SET last_run_at = ? WHERE id = ?", (db.now_iso(), site_id))
    except Exception as exc:
        db.execute("UPDATE audits SET status='error', finished_at=?, error=? WHERE id=?",
                   (db.now_iso(), f"{exc}\n{traceback.format_exc()[-1500:]}", audit_id))
    return audit_id


def start_audit(site_id: int) -> int:
    """Run in a background thread; returns the audit id immediately."""
    if site_id in _running and _running[site_id].is_alive():
        r = db.row("SELECT id FROM audits WHERE site_id = ? AND status = 'running' ORDER BY id DESC", (site_id,))
        if r:
            return r["id"]
    audit_id = db.execute("INSERT INTO audits(site_id, status, progress, started_at) VALUES(?, 'running', 'Queued', ?)",
                          (site_id, db.now_iso()))
    t = threading.Thread(target=run_audit, args=(site_id, audit_id), daemon=True, name=f"audit-{site_id}")
    _running[site_id] = t
    t.start()
    return audit_id


def build_result(site: dict, progress=None, live_keywords: bool = True, run_psi: bool | None = None) -> dict:
    progress = progress or (lambda m: None)
    cr = crawl(site["url"], max_pages=int(site.get("max_pages") or 150), progress=progress)
    ok = html_pages(cr.pages)
    progress("Analyzing keywords")
    kw_map = {p["url"]: keywords.page_keywords(p) for p in ok}
    gsc = metrics.gsc_rows(site["id"]) if site.get("id") else []
    ga4 = metrics.ga4_rows(site["id"]) if site.get("id") else []
    research = keywords.keyword_research(cr, site, kw_map, gsc, live=live_keywords, provider=dataforseo.provider_for(site))
    meta_sugg = keywords.meta_suggestions(cr, kw_map)
    progress("Running technical checks")
    tech = technical.analyze(cr)
    progress("Analyzing content")
    cont = content.analyze(cr, kw_map, research)
    progress("Mapping internal links")
    lnk = links.analyze(cr, kw_map)
    progress("Scoring AI search readiness")
    g = geo.analyze(cr, research)
    progress("Building the conversion tracking plan")
    conv = conversion.analyze(cr, ga4)
    if run_psi is None:
        run_psi = (db.get_setting("pagespeed_enabled", "1") != "0")
    progress("Measuring Core Web Vitals")
    sample = _psi_sample(cr, ok)
    perf = performance.analyze(sample, db.get_setting("pagespeed_api_key"), enabled=run_psi)
    off = offpage.analyze(site, research, urlparse(cr.origin).hostname or "")

    issues = tech["issues"] + cont["issues"] + lnk["issues"] + g["issues"] + conv["issues"] + perf["issues"]
    perf_scores = [r["scores"].get("performance") for r in perf["results"] if "error" not in r and r["strategy"] == "mobile"]
    sc = priorities.scores(issues, len(ok), {"geo_avg": g["average"] if g["pages"] else None,
                                             "perf_score": round(sum(perf_scores) / len(perf_scores)) if perf_scores else None})
    top10 = priorities.top_actions(issues, len(ok))
    plan = priorities.roadmap(issues, len(ok), {"content_gaps": research["status_counts"].get("content gap", 0),
                                                "link_suggestions": len(lnk["suggestions"])})
    pages_summary = []
    for p in cr.pages.values():
        kws = kw_map.get(p["url"], [])
        pages_summary.append({
            "url": p["url"], "status": p.get("status"), "title": p.get("title"), "meta_description": p.get("meta_description"),
            "h1": (p.get("h1") or [None])[0], "words": p.get("word_count"), "inlinks": p.get("inlink_count", 0),
            "outlinks": len(p.get("internal_links", [])), "depth": p.get("depth"), "ms": p.get("elapsed_ms"),
            "size_kb": round((p.get("size") or 0) / 1024, 1), "indexable": indexable(p) if "word_count" in p else False,
            "canonical": p.get("canonical"), "schema": sorted({t for it in p.get("schema", []) for t in technical._types(it)}),
            "primary_keyword": kws[0][0] if kws else None, "keywords": [k for k, _ in kws[:6]],
            "in_sitemap": p.get("in_sitemap"), "final_url": p.get("final_url"), "error": p.get("error"),
            "aio_score": next((x["score"] for x in g["pages"] if x["url"] == p["url"]), None),
            "page_type": conversion.page_type(p) if "word_count" in p else None,
        })
    return {
        "meta": {"site_url": site["url"], "origin": cr.origin, "pages_crawled": len(cr.pages), "html_pages": len(ok),
                 "generated_at": db.now_iso(), "industry": site.get("industry"), "crawl_errors": cr.errors},
        "scores": sc, "issues": sorted(issues, key=lambda i: -priorities.priority_value(i, len(ok))),
        "top10": top10, "roadmap": plan,
        "technical": tech["stats"], "content": cont["stats"],
        "links": {"stats": lnk["stats"], "suggestions": lnk["suggestions"], "tree": lnk["tree"], "graph": lnk["graph"]},
        "keywords": research, "meta_suggestions": meta_sugg, "performance": perf, "geo": g,
        "conversion": conv, "offpage": off, "pages": pages_summary,
        "robots": cr.robots, "sitemaps": {k: v for k, v in cr.sitemaps.items() if k != "lastmod"} | {"url_count": len(cr.sitemaps.get("urls", []))},
        "llms_txt": cr.llms_txt,
    }


def _psi_sample(cr, ok, n: int = 4) -> list[str]:
    home = cr.origin + "/"
    picks = [home] if home in cr.pages else []
    by_type = {}
    for p in ok:
        t = conversion.page_type(p)
        if t not in by_type and t != "home" and indexable(p):
            by_type[t] = p["url"]
    picks += list(by_type.values())
    return picks[:n]
