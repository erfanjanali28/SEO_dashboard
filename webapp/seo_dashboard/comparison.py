"""Growth and decline: two audits side by side, and two search or traffic periods.

Each metric knows which direction is better, so fewer 404s reads as an
improvement. Coverage is compared as a percentage of pages, because a raw count
grows whenever a crawl simply sees more pages. Where two audits are not like for
like, the result says so instead of reporting it as growth.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from . import db

CRAWL_SIZE_TOLERANCE = 0.2   # crawl sizes further apart than this are not like for like
MIN_WORD_CHANGE = 50
MIN_WORD_SHARE = 0.2
MIN_INLINK_CHANGE = 3
MAX_PAGE_CHANGES = 1000
RESPONSE_NOISE = 0.1         # server response varies between runs; smaller swings are not a change
# Checks added to the dashboard later, with the result key that marks an audit
# able to run them. Finding one for the first time is not a change on the site.
LATER_CHECKS = {"keyword_stuffing": "redirects"}
MAX_MOVERS = 50


def metric(group: str, label: str, before, after, better: str | None = "up", unit: str = "", noise: float = 0) -> dict:
    """One comparable row. ``better`` is 'up', 'down', or None when neither is good or bad.

    ``noise`` is the share of the old value that counts as normal variation.
    """
    change = round(after - before, 1) if before is not None and after is not None else None
    if change is None or better is None:
        status = "neutral"
    elif abs(change) <= abs(before) * noise:
        status = "unchanged"
    else:
        status = "improved" if (change > 0) == (better == "up") else "declined"
    return {"group": group, "label": label, "before": before, "after": after, "change": change, "unit": unit,
            "percent": round(change / abs(before) * 100, 1) if change is not None and before else None, "status": status}


def _html_pages(result: dict) -> list[dict]:
    return [p for p in result.get("pages", []) if p.get("status") and 200 <= p["status"] < 300 and p.get("words") is not None]


def _coverage(result: dict, test) -> float | None:
    pages = _html_pages(result)
    return round(sum(1 for p in pages if test(p)) / len(pages) * 100, 1) if pages else None


def _later_checks(old: dict, new: dict) -> list[dict]:
    """Issues in ``new`` from checks that did not exist when ``old`` ran."""
    return [i for i in new.get("issues", []) if i["id"] in LATER_CHECKS and LATER_CHECKS[i["id"]] not in old]


def _severity(result: dict, ignore: frozenset = frozenset()) -> Counter:
    return Counter(i["severity"] for i in result.get("issues", []) if i["id"] not in ignore)


def _metrics(old: dict, new: dict) -> list[dict]:
    later = frozenset(i["id"] for i in _later_checks(old, new))

    def pair(getter):
        return getter(old), getter(new)

    def tech(key, default=None):
        return lambda r: r.get("technical", {}).get(key, default)

    def size(getter):
        def read(r):
            v = getter(r)
            return len(v) if v is not None else None
        return read

    rows = [metric("Score", "Overall score", *pair(lambda r: r["scores"]["overall"]))]
    groups = sorted(set(old["scores"].get("categories", {})) | set(new["scores"].get("categories", {})))
    rows += [metric("Score", g, old["scores"]["categories"].get(g), new["scores"]["categories"].get(g)) for g in groups]
    for level in ("critical", "high", "medium", "low"):
        rows.append(metric("Issues", f"{level.capitalize()} issues", _severity(old)[level], _severity(new, later)[level], "down"))
    rows += [
        metric("Crawl and indexing", "URLs crawled", *pair(lambda r: r["meta"].get("pages_crawled")), None),
        metric("Crawl and indexing", "Indexable pages", *pair(lambda r: _coverage(r, lambda p: p.get("indexable"))), "up", "%"),
        metric("Crawl and indexing", "404 URLs", *pair(size(tech("redirect_suggestions"))), "down"),
        metric("Crawl and indexing", "Broken links", *pair(size(tech("broken_links"))), "down"),
        metric("Crawl and indexing", "Links through redirects", *pair(size(tech("links_to_redirects"))), "down"),
        metric("Crawl and indexing", "Average response", *pair(tech("avg_response_ms")), "down", " ms", RESPONSE_NOISE),
        metric("On-page", "Pages with a title", *pair(lambda r: _coverage(r, lambda p: p.get("title"))), "up", "%"),
        metric("On-page", "Pages with a meta description", *pair(lambda r: _coverage(r, lambda p: p.get("meta_description"))), "up", "%"),
        metric("On-page", "Pages with an H1", *pair(lambda r: _coverage(r, lambda p: p.get("h1"))), "up", "%"),
        metric("On-page", "Pages with a canonical", *pair(lambda r: _coverage(r, lambda p: p.get("canonical"))), "up", "%"),
        metric("On-page", "Pages with schema", *pair(lambda r: _coverage(r, lambda p: p.get("schema"))), "up", "%"),
        metric("Content", "Average words per page", *pair(lambda r: r.get("content", {}).get("avg_words")), "up"),
        metric("Content", "Near-duplicate pairs", *pair(size(lambda r: r.get("content", {}).get("near_duplicates"))), "down"),
        metric("Content", "Cannibalized keywords", *pair(size(lambda r: r.get("content", {}).get("cannibalization"))), "down"),
        metric("Content", "Outdated pages", *pair(size(lambda r: r.get("content", {}).get("outdated"))), "down"),
        metric("Links", "Orphan pages", *pair(size(lambda r: r.get("links", {}).get("stats", {}).get("orphans"))), "down"),
        metric("Links", "Average inlinks per page", *pair(lambda r: r.get("links", {}).get("stats", {}).get("avg_inlinks")), "up"),
        metric("AI search", "AI answer readiness", *pair(lambda r: r.get("geo", {}).get("average")), "up"),
    ]
    return rows


def _issue_changes(old: dict, new: dict) -> dict:
    before = {i["id"]: i for i in old.get("issues", [])}
    after = {i["id"]: i for i in new.get("issues", [])}

    def brief(i, **extra):
        return {"title": i["title"], "severity": i["severity"], "category": i["category"], **extra}

    both = before.keys() & after.keys()
    later = {i["id"] for i in _later_checks(old, new)}
    return {
        "new": [brief(after[k], count=after[k]["count"]) for k in after.keys() - before.keys() - later],
        "resolved": [brief(before[k], count=before[k]["count"]) for k in before.keys() - after.keys()],
        "worse": [brief(after[k], before=before[k]["count"], after=after[k]["count"]) for k in both if after[k]["count"] > before[k]["count"]],
        "better": [brief(after[k], before=before[k]["count"], after=after[k]["count"]) for k in both if after[k]["count"] < before[k]["count"]],
    }


def _text_change(field: str, label: str, a: dict, b: dict) -> tuple | None:
    x, y = a.get(field), b.get(field)
    if x == y:
        return None
    if not x:
        return f"{label} added", None, y, "improved"
    if not y:
        return f"{label} removed", x, None, "declined"
    return f"{label} changed", x, y, "neutral"


def page_changes(old: dict, new: dict) -> list[dict]:
    """What changed per URL. Ordered so regressions come first."""
    before = {p["url"]: p for p in old.get("pages", [])}
    after = {p["url"]: p for p in new.get("pages", [])}
    rows = []

    def add(url, change, was, now, status):
        rows.append({"url": url, "change": change, "before": was, "after": now, "status": status})

    for url in after.keys() - before.keys():
        add(url, "Newly found", None, after[url].get("status"), "neutral")
    for url in before.keys() - after.keys():
        add(url, "No longer found", before[url].get("status"), None, "neutral")
    for url in before.keys() & after.keys():
        a, b = before[url], after[url]
        sa, sb = a.get("status"), b.get("status")
        if sa and sb and sa != sb:
            status = "declined" if sa < 400 <= sb else "improved" if sb < 400 <= sa else "neutral"
            add(url, "Status changed", sa, sb, status)
        if a.get("indexable") != b.get("indexable") and sa and sb and sa < 300 and sb < 300:
            add(url, "Now indexable" if b.get("indexable") else "No longer indexable", a.get("indexable"), b.get("indexable"),
                "improved" if b.get("indexable") else "declined")
        for field, label in (("title", "Title"), ("meta_description", "Meta description"), ("h1", "H1"), ("canonical", "Canonical")):
            found = _text_change(field, label, a, b)
            if found:
                add(url, *found)
        wa, wb = a.get("words"), b.get("words")
        if wa is not None and wb is not None and abs(wb - wa) >= MIN_WORD_CHANGE and abs(wb - wa) >= max(wa, 1) * MIN_WORD_SHARE:
            add(url, "Content grew" if wb > wa else "Content shrank", wa, wb, "improved" if wb > wa else "declined")
        ia, ib = a.get("inlinks", 0), b.get("inlinks", 0)
        if abs(ib - ia) >= MIN_INLINK_CHANGE and abs(ib - ia) >= max(ia, 1) * 0.5:
            add(url, "More internal links" if ib > ia else "Fewer internal links", ia, ib, "improved" if ib > ia else "declined")
    order = {"declined": 0, "improved": 1, "neutral": 2}
    return sorted(rows, key=lambda r: (order[r["status"]], r["change"], r["url"]))[:MAX_PAGE_CHANGES]


def _warnings(old: dict, new: dict, pages: list[dict]) -> list[str]:
    notes = []
    a, b = old["meta"].get("pages_crawled") or 0, new["meta"].get("pages_crawled") or 0
    if a and b and abs(a - b) / max(a, b) > CRAWL_SIZE_TOLERANCE:
        notes.append(f"The crawls differ in size ({a} and {b} URLs), so issue counts are not like for like. Percentages are safer to compare.")
    found = sum(1 for p in pages if p["change"] == "Newly found")
    gone = sum(1 for p in pages if p["change"] == "No longer found")
    if found or gone:
        notes.append(f"{found} URLs were newly found and {gone} no longer found. A crawl limit can cause this without the site changing, so check before treating them as new or removed pages.")
    if old["meta"].get("method") != new["meta"].get("method"):
        notes.append("The dashboard's scoring rules changed between these audits, so a small score or AI readiness change may come from the rules, not the site.")
    later = _later_checks(old, new)
    if later:
        names = ", ".join(i["title"] for i in later)
        notes.append(f"Added to the dashboard after the older audit: {names}. These are left out of the issue counts because they are not changes on the site, but they can still lower the newer scores.")
    if ("Performance" in old["scores"].get("categories", {})) != ("Performance" in new["scores"].get("categories", {})):
        notes.append("Only one of these audits measured performance, so the overall scores use different areas.")
    return notes


def _verdict(score_change: int, improved: int, declined: int) -> str:
    """Growing or Declining needs the score and most metrics to agree."""
    if not improved and not declined and not score_change:
        return "No change"
    if not score_change:
        return "Stable"
    if score_change > 0 and improved > declined:
        return "Growing"
    if score_change < 0 and declined > improved:
        return "Declining"
    return "Mixed"


def compare_audits(old_row: dict, new_row: dict) -> dict:
    old, new = db.load_audit_result(old_row), db.load_audit_result(new_row)
    rows = _metrics(old, new)
    tally = Counter(r["status"] for r in rows)
    score_change = new["scores"]["overall"] - old["scores"]["overall"]
    pages = page_changes(old, new)
    return {
        "verdict": _verdict(score_change, tally["improved"], tally["declined"]),
        "score_before": old["scores"]["overall"], "score_after": new["scores"]["overall"], "score_change": score_change,
        "improved": tally["improved"], "declined": tally["declined"], "unchanged": tally["unchanged"],
        "metrics": rows, "issues": _issue_changes(old, new), "pages": pages,
        "page_tally": dict(Counter(p["status"] for p in pages)),
        "warnings": _warnings(old, new, pages),
    }


def site_audits(site_id: int) -> list[dict]:
    return db.rows("SELECT id, started_at, finished_at, score, pages_crawled FROM audits WHERE site_id = ? AND status = 'done' ORDER BY id", (site_id,))


# ---------------- search and traffic periods ----------------
def _windows(last: str, days: int) -> dict:
    end = date.fromisoformat(last)
    return {"current": [(end - timedelta(days=days - 1)).isoformat(), last],
            "previous": [(end - timedelta(days=2 * days - 1)).isoformat(), (end - timedelta(days=days)).isoformat()]}


def _movers(before: dict, after: dict, key: str) -> dict:
    rows = []
    for k in before.keys() | after.keys():
        a, b = before.get(k, {}), after.get(k, {})
        was, now = a.get(key) or 0, b.get(key) or 0
        if was != now:
            rows.append({"item": k, "before": round(was), "after": round(now), "change": round(now - was)})
    return {"gainers": sorted([r for r in rows if r["change"] > 0], key=lambda r: -r["change"])[:MAX_MOVERS],
            "losers": sorted([r for r in rows if r["change"] < 0], key=lambda r: r["change"])[:MAX_MOVERS]}


def _search_totals(site_id: int, span: list[str]) -> dict:
    r = db.row("SELECT SUM(clicks) clicks, SUM(impressions) impressions, SUM(position * impressions) / NULLIF(SUM(impressions), 0) position "
               "FROM search_metrics WHERE site_id = ? AND date BETWEEN ? AND ?", (site_id, *span))
    return {"clicks": r["clicks"] or 0, "impressions": r["impressions"] or 0, "position": round(r["position"], 1) if r["position"] else None}


def _search_group(site_id: int, column: str, span: list[str]) -> dict:
    rows = db.rows(f"SELECT {column} item, SUM(clicks) clicks, SUM(impressions) impressions, SUM(position * impressions) / NULLIF(SUM(impressions), 0) position "
                   f"FROM search_metrics WHERE site_id = ? AND date BETWEEN ? AND ? AND {column} IS NOT NULL GROUP BY {column}", (site_id, *span))
    return {r["item"]: r for r in rows}


def _ctr(t: dict) -> float:
    return round(t["clicks"] / t["impressions"] * 100, 2) if t["impressions"] else 0


def _search_section(site_id: int, days: int) -> dict:
    bounds = db.row("SELECT MIN(date) first, MAX(date) last FROM search_metrics WHERE site_id = ?", (site_id,))
    if not bounds or not bounds["last"]:
        return {"has_data": False}
    w = _windows(bounds["last"], days)
    cur, prev = _search_totals(site_id, w["current"]), _search_totals(site_id, w["previous"])
    q_cur, q_prev = _search_group(site_id, "query", w["current"]), _search_group(site_id, "query", w["previous"])
    top10 = lambda g: sum(1 for r in g.values() if r["position"] and r["position"] <= 10)
    return {
        "has_data": True, "window": w, "partial": bounds["first"] > w["previous"][0],
        "metrics": [
            metric("Search Console", "Clicks", prev["clicks"], cur["clicks"]),
            metric("Search Console", "Impressions", prev["impressions"], cur["impressions"]),
            metric("Search Console", "Click-through rate", _ctr(prev), _ctr(cur), "up", "%"),
            metric("Search Console", "Average position", prev["position"], cur["position"], "down"),
            metric("Search Console", "Keywords in the top 10", top10(q_prev), top10(q_cur)),
        ],
        "keywords_won": len(q_cur.keys() - q_prev.keys()), "keywords_lost": len(q_prev.keys() - q_cur.keys()),
        "queries": _movers(q_prev, q_cur, "clicks"),
        "pages": _movers(_search_group(site_id, "page", w["previous"]), _search_group(site_id, "page", w["current"]), "clicks"),
    }


def _traffic_section(site_id: int, days: int) -> dict:
    organic = "(channel = 'Organic Search' OR channel IS NULL)"
    bounds = db.row(f"SELECT MIN(date) first, MAX(date) last FROM analytics_metrics WHERE site_id = ? AND {organic}", (site_id,))
    if not bounds or not bounds["last"]:
        return {"has_data": False}
    w = _windows(bounds["last"], days)

    def totals(span):
        return db.row(f"SELECT COALESCE(SUM(sessions), 0) sessions, COALESCE(SUM(users), 0) users, COALESCE(SUM(conversions), 0) conversions "
                      f"FROM analytics_metrics WHERE site_id = ? AND {organic} AND date BETWEEN ? AND ?", (site_id, *span))

    def by_page(span):
        rows = db.rows(f"SELECT landing_page item, SUM(sessions) sessions FROM analytics_metrics WHERE site_id = ? AND {organic} "
                       "AND date BETWEEN ? AND ? AND landing_page IS NOT NULL GROUP BY landing_page", (site_id, *span))
        return {r["item"]: r for r in rows}

    cur, prev = totals(w["current"]), totals(w["previous"])
    return {
        "has_data": True, "window": w, "partial": bounds["first"] > w["previous"][0],
        "metrics": [metric("GA4 organic", "Sessions", prev["sessions"], cur["sessions"]),
                    metric("GA4 organic", "Users", prev["users"], cur["users"]),
                    metric("GA4 organic", "Key events", prev["conversions"], cur["conversions"])],
        "pages": _movers(by_page(w["previous"]), by_page(w["current"]), "sessions"),
    }


def compare_periods(site_id: int, days: int = 28) -> dict:
    return {"days": days, "search": _search_section(site_id, days), "traffic": _traffic_section(site_id, days)}
