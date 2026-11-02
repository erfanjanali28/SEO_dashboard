"""Search Console / GA4 trend queries for charts: keyword performance over
time, ranking improvements and declines, and top pages."""

from __future__ import annotations

from datetime import date, timedelta

from . import db


def gsc_rows(site_id: int, days: int = 90) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    return db.rows("SELECT date, query, page, clicks, impressions, ctr, position FROM search_metrics "
                   "WHERE site_id = ? AND date >= ?", (site_id, since))


def ga4_rows(site_id: int, days: int = 90) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    return db.rows("SELECT date, landing_page, channel, sessions, users, engaged_sessions, conversions "
                   "FROM analytics_metrics WHERE site_id = ? AND date >= ?", (site_id, since))


def search_performance(site_id: int, days: int = 90, window: int = 28) -> dict:
    daily = db.rows(
        "SELECT date, SUM(clicks) clicks, SUM(impressions) impressions, "
        "SUM(position * impressions) / NULLIF(SUM(impressions), 0) position "
        "FROM search_metrics WHERE site_id = ? AND date >= ? GROUP BY date ORDER BY date",
        (site_id, (date.today() - timedelta(days=days)).isoformat()))
    if not daily:
        return {"has_data": False}
    last = max(d["date"] for d in daily)
    end = date.fromisoformat(last)
    cur_from = (end - timedelta(days=window - 1)).isoformat()
    prev_from = (end - timedelta(days=2 * window - 1)).isoformat()
    prev_to = (end - timedelta(days=window)).isoformat()

    def by_query(a, b):
        return {r["query"]: r for r in db.rows(
            "SELECT query, SUM(clicks) clicks, SUM(impressions) impressions, "
            "SUM(position * impressions) / NULLIF(SUM(impressions), 0) position "
            "FROM search_metrics WHERE site_id = ? AND date BETWEEN ? AND ? AND query IS NOT NULL "
            "GROUP BY query", (site_id, a, b))}
    cur, prev = by_query(cur_from, last), by_query(prev_from, prev_to)
    changes = []
    for q, c in cur.items():
        p = prev.get(q)
        if p and c["position"] and p["position"] and c["impressions"] >= 10:
            changes.append({"query": q, "position": round(c["position"], 1), "prev_position": round(p["position"], 1),
                            "change": round(p["position"] - c["position"], 1), "clicks": c["clicks"], "impressions": c["impressions"],
                            "clicks_change": c["clicks"] - p["clicks"]})
    improved = sorted([c for c in changes if c["change"] > 0], key=lambda x: -x["change"] * (x["impressions"] ** 0.5))[:50]
    declined = sorted([c for c in changes if c["change"] < 0], key=lambda x: x["change"] * (x["impressions"] ** 0.5))[:50]
    top_queries = sorted(cur.values(), key=lambda x: -x["clicks"])[:50]
    top_q = [q["query"] for q in top_queries[:8]]
    series = {}
    if top_q:
        marks = ",".join("?" * len(top_q))
        for r in db.rows(
            f"SELECT date, query, SUM(position * impressions) / NULLIF(SUM(impressions), 0) position, SUM(clicks) clicks "
            f"FROM search_metrics WHERE site_id = ? AND query IN ({marks}) GROUP BY date, query ORDER BY date",
            (site_id, *top_q)):
            series.setdefault(r["query"], []).append({"date": r["date"], "position": round(r["position"] or 0, 1), "clicks": r["clicks"]})
    buckets = {"1-3": 0, "4-10": 0, "11-20": 0, "21-50": 0, "51+": 0}
    for c in cur.values():
        pos = c["position"] or 100
        key = "1-3" if pos <= 3 else "4-10" if pos <= 10 else "11-20" if pos <= 20 else "21-50" if pos <= 50 else "51+"
        buckets[key] += 1
    top_pages = db.rows(
        "SELECT page, SUM(clicks) clicks, SUM(impressions) impressions, "
        "SUM(position * impressions) / NULLIF(SUM(impressions), 0) position FROM search_metrics "
        "WHERE site_id = ? AND date BETWEEN ? AND ? GROUP BY page ORDER BY clicks DESC LIMIT 50", (site_id, cur_from, last))
    tot = lambda rows, k: round(sum((r[k] or 0) for r in rows.values()))
    return {
        "has_data": True, "daily": daily, "improved": improved, "declined": declined,
        "top_queries": top_queries, "query_series": series, "position_buckets": buckets, "top_pages": top_pages,
        "totals": {"clicks": tot(cur, "clicks"), "impressions": tot(cur, "impressions"),
                   "prev_clicks": tot(prev, "clicks"), "prev_impressions": tot(prev, "impressions"),
                   "keywords": len(cur), "top10": buckets["1-3"] + buckets["4-10"]},
        "window": {"current": [cur_from, last], "previous": [prev_from, prev_to]},
    }


def analytics_summary(site_id: int, days: int = 90) -> dict:
    daily = db.rows(
        "SELECT date, SUM(sessions) sessions, SUM(users) users, SUM(conversions) conversions FROM analytics_metrics "
        "WHERE site_id = ? AND date >= ? AND (channel = 'Organic Search' OR channel IS NULL) GROUP BY date ORDER BY date",
        (site_id, (date.today() - timedelta(days=days)).isoformat()))
    if not daily:
        return {"has_data": False}
    pages = db.rows(
        "SELECT landing_page, SUM(sessions) sessions, SUM(conversions) conversions FROM analytics_metrics "
        "WHERE site_id = ? AND channel = 'Organic Search' GROUP BY landing_page ORDER BY sessions DESC LIMIT 30", (site_id,))
    channels = db.rows("SELECT channel, SUM(sessions) sessions FROM analytics_metrics WHERE site_id = ? GROUP BY channel ORDER BY sessions DESC", (site_id,))
    return {"has_data": True, "daily": daily, "landing_pages": pages, "channels": channels}


def audit_history(site_id: int) -> list[dict]:
    return db.rows("SELECT id, started_at, score, pages_crawled, issues_critical, issues_high, issues_medium, issues_low "
                   "FROM audits WHERE site_id = ? AND status = 'done' ORDER BY started_at", (site_id,))
