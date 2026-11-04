"""Growth and decline comparison: direction of each metric, honesty about crawl
differences, and period comparison."""

import json
import os
import sys
from copy import deepcopy
from datetime import date, timedelta

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from seo_dashboard import comparison  # noqa: E402


def page(url, status=200, words=500, inlinks=5, **kw):
    return {"url": url, "status": status, "title": "T", "meta_description": "D", "h1": "H", "canonical": url, "indexable": True,
            "words": words, "inlinks": inlinks, "schema": ["Article"], **kw}


def audit_result(score=70, pages=None, issues=None, crawled=10, **tech):
    return {
        "meta": {"pages_crawled": crawled}, "scores": {"overall": score, "categories": {"Technical": score, "Performance": 80}},
        "issues": issues or [], "pages": pages if pages is not None else [page("https://a.test/")],
        "technical": {"redirect_suggestions": [], "broken_links": [], "links_to_redirects": [], "avg_response_ms": 300, **tech},
        "content": {"avg_words": 500, "near_duplicates": [], "cannibalization": [], "outdated": []},
        "links": {"stats": {"orphans": [], "avg_inlinks": 4}}, "geo": {"average": 60},
    }


def issue(id_, count=3, severity="high"):
    return {"id": id_, "title": id_, "severity": severity, "category": "Technical", "count": count}


def compare(old, new):
    return comparison.compare_audits({"result": json.dumps(old)}, {"result": json.dumps(new)})


def row(result, label):
    return next(m for m in result["metrics"] if m["label"] == label)


def test_fewer_problems_counts_as_improvement():
    out = compare(audit_result(redirect_suggestions=[1, 2, 3]), audit_result(redirect_suggestions=[1]))
    m = row(out, "404 URLs")
    assert (m["before"], m["after"], m["change"], m["status"]) == (3, 1, -2, "improved")


def test_more_problems_counts_as_decline():
    m = row(compare(audit_result(), audit_result(broken_links=[1, 2])), "Broken links")
    assert m["status"] == "declined" and m["change"] == 2


def test_slower_response_is_a_decline():
    assert row(compare(audit_result(avg_response_ms=300), audit_result(avg_response_ms=900)), "Average response")["status"] == "declined"


def test_crawl_size_is_neutral_not_growth():
    assert row(compare(audit_result(crawled=10), audit_result(crawled=10000)), "URLs crawled")["status"] == "neutral"


def test_coverage_uses_percentages_so_a_bigger_crawl_is_not_growth():
    old = audit_result(pages=[page(f"https://a.test/{i}") for i in range(10)])
    new = audit_result(pages=[page(f"https://a.test/{i}", meta_description=None if i % 2 else "D") for i in range(100)])
    m = row(compare(old, new), "Pages with a meta description")
    assert (m["before"], m["after"], m["status"]) == (100.0, 50.0, "declined")


def test_verdicts():
    assert compare(audit_result(70), audit_result(80))["verdict"] == "Growing"
    assert compare(audit_result(80), audit_result(70))["verdict"] == "Declining"
    assert compare(audit_result(70), audit_result(70))["verdict"] == "No change"
    assert compare(audit_result(70, redirect_suggestions=[1]), audit_result(70, broken_links=[1]))["verdict"] == "Stable"


def test_flat_score_is_never_declining():
    """Real case: a score of 78 on both audits with a few small declines."""
    assert compare(audit_result(78), audit_result(78, broken_links=[1, 2]))["verdict"] == "Stable"


def test_score_drop_with_more_improvements_is_mixed():
    assert compare(audit_result(80, redirect_suggestions=[1], broken_links=[1]), audit_result(78))["verdict"] == "Mixed"


def test_normal_response_variation_is_not_a_decline():
    m = row(compare(audit_result(avg_response_ms=820), audit_result(avg_response_ms=822)), "Average response")
    assert m["status"] == "unchanged" and m["change"] == 2


def test_check_added_later_is_not_a_new_problem():
    """Real case: the first audit ran before keyword stuffing was checked."""
    new = audit_result(issues=[issue("keyword_stuffing", 19, "medium")])
    new["redirects"] = {}
    out = compare(audit_result(), new)
    assert out["issues"]["new"] == [] and row(out, "Medium issues")["status"] == "unchanged"
    assert any("Added to the dashboard" in w for w in out["warnings"])


def test_later_check_counts_once_both_audits_could_run_it():
    old, new = audit_result(), audit_result(issues=[issue("keyword_stuffing", 19, "medium")])
    old["redirects"] = new["redirects"] = {}
    out = compare(old, new)
    assert [i["title"] for i in out["issues"]["new"]] == ["keyword_stuffing"] and row(out, "Medium issues")["status"] == "declined"


def test_score_rise_with_more_declines_is_mixed_not_growth():
    old = audit_result(70)
    new = audit_result(71, broken_links=[1], redirect_suggestions=[1], links_to_redirects=[1])
    assert compare(old, new)["verdict"] == "Mixed"


def test_issue_changes():
    old = audit_result(issues=[issue("gone"), issue("worse", 2), issue("better", 9), issue("same", 4)])
    new = audit_result(issues=[issue("fresh"), issue("worse", 7), issue("better", 1), issue("same", 4)])
    i = compare(old, new)["issues"]
    assert [x["title"] for x in i["new"]] == ["fresh"] and [x["title"] for x in i["resolved"]] == ["gone"]
    assert (i["worse"][0]["before"], i["worse"][0]["after"]) == (2, 7)
    assert (i["better"][0]["before"], i["better"][0]["after"]) == (9, 1)


def test_broken_page_is_the_first_page_change():
    old = audit_result(pages=[page("https://a.test/a"), page("https://a.test/b")])
    new = audit_result(pages=[page("https://a.test/a", title="New title"), page("https://a.test/b", status=404)])
    rows = compare(old, new)["pages"]
    assert (rows[0]["url"], rows[0]["change"], rows[0]["status"]) == ("https://a.test/b", "Status changed", "declined")
    assert next(r for r in rows if r["change"] == "Title changed")["status"] == "neutral"


@pytest.mark.parametrize("before, after, change, status", [
    (dict(indexable=True), dict(indexable=False), "No longer indexable", "declined"),
    (dict(indexable=False), dict(indexable=True), "Now indexable", "improved"),
    (dict(canonical=None), dict(), "Canonical added", "improved"),
    (dict(), dict(meta_description=None), "Meta description removed", "declined"),
    (dict(words=500), dict(words=900), "Content grew", "improved"),
    (dict(words=500), dict(words=300), "Content shrank", "declined"),
    (dict(inlinks=4), dict(inlinks=12), "More internal links", "improved"),
    (dict(inlinks=12), dict(inlinks=4), "Fewer internal links", "declined"),
])
def test_page_level_changes(before, after, change, status):
    u = "https://a.test/a"
    rows = compare(audit_result(pages=[page(u, **before)]), audit_result(pages=[page(u, **after)]))["pages"]
    assert (change, status) in {(r["change"], r["status"]) for r in rows}


def test_small_changes_are_not_reported_as_page_changes():
    u = "https://a.test/a"
    assert not compare(audit_result(pages=[page(u, words=500, inlinks=5)]), audit_result(pages=[page(u, words=520, inlinks=6)]))["pages"]


def test_crawl_size_difference_is_warned():
    warnings = compare(audit_result(crawled=20), audit_result(crawled=100))["warnings"]
    assert any("not like for like" in w for w in warnings)


def test_pages_found_or_lost_may_just_be_the_crawl_limit():
    out = compare(audit_result(pages=[page("https://a.test/old")]), audit_result(pages=[page("https://a.test/new")]))
    assert any("crawl limit" in w for w in out["warnings"])
    assert {r["status"] for r in out["pages"]} == {"neutral"}


def test_comparing_full_audit_with_first_look_is_warned():
    full, first = audit_result(), audit_result()
    del first["scores"]["categories"]["Performance"]
    assert any("performance" in w for w in compare(full, first)["warnings"])


def test_audit_from_before_a_field_existed_shows_nothing_rather_than_failing():
    old = audit_result()
    del old["content"]["cannibalization"], old["geo"]
    out = compare(old, audit_result())
    assert row(out, "Cannibalized keywords")["status"] == "neutral" and row(out, "AI answer readiness")["change"] is None


# ---------------- API and periods ----------------
@pytest.fixture(scope="module")
def client(tmp_path_factory):
    data = tmp_path_factory.mktemp("cmp")
    os.environ["SEO_DASHBOARD_DATA"] = str(data)
    os.environ["SEO_DASHBOARD_DB"] = str(data / "t.db")
    os.environ["SEO_DASHBOARD_SCHEDULER"] = "0"
    import importlib

    from seo_dashboard import db
    importlib.reload(db)
    from seo_dashboard import app as app_mod
    importlib.reload(app_mod)
    from fastapi.testclient import TestClient
    with TestClient(app_mod.app) as c:
        yield c


def new_site(client, url="https://a.test/"):
    from seo_dashboard import db
    cid = db.execute("INSERT INTO clients(name, created_at) VALUES('C', ?)", (db.now_iso(),))
    return db.execute("INSERT INTO sites(client_id, url, created_at) VALUES(?, ?, ?)", (cid, url, db.now_iso()))


def add_audit(sid, score, status="done"):
    from seo_dashboard import db
    return db.execute("INSERT INTO audits(site_id, status, started_at, score, pages_crawled, result) VALUES(?,?,?,?,?,?)",
                      (sid, status, db.now_iso(), score, 10, json.dumps(deepcopy(audit_result(score)))))


def test_api_needs_two_audits(client):
    sid = new_site(client)
    add_audit(sid, 70)
    d = client.get(f"/api/sites/{sid}/compare").json()
    assert d["available"] is False and len(d["audits"]) == 1


def test_api_defaults_to_the_latest_two_and_skips_failed_audits(client):
    sid = new_site(client)
    first, second = add_audit(sid, 60), add_audit(sid, 70)
    add_audit(sid, None, status="error")
    third = add_audit(sid, 75)
    d = client.get(f"/api/sites/{sid}/compare").json()
    assert (d["base"], d["current"], d["score_change"]) == (second, third, 5) and len(d["audits"]) == 3
    assert first in {a["id"] for a in d["audits"]}


def test_api_picks_any_two_and_always_treats_the_older_as_baseline(client):
    sid = new_site(client)
    a, _, c = add_audit(sid, 60), add_audit(sid, 70), add_audit(sid, 90)
    d = client.get(f"/api/sites/{sid}/compare?base={c}&current={a}").json()
    assert (d["base"], d["current"], d["score_change"]) == (a, c, 30)


def test_api_rejects_same_audit_and_another_sites_audit(client):
    sid, other = new_site(client), new_site(client)
    a, b = add_audit(sid, 60), add_audit(sid, 70)
    foreign = add_audit(other, 50)
    assert client.get(f"/api/sites/{sid}/compare?base={a}&current={a}").status_code == 400
    assert client.get(f"/api/sites/{sid}/compare?base={a}&current={foreign}").status_code == 404
    assert client.get("/api/sites/999999/compare").status_code == 404
    assert b


def seed_search(sid, days_ago, query, page_url, clicks, impressions, position):
    from seo_dashboard import db
    day = (date.today() - timedelta(days=days_ago)).isoformat()
    db.execute("INSERT INTO search_metrics(site_id,date,query,page,clicks,impressions,ctr,position,source) VALUES(?,?,?,?,?,?,?,?,'gsc')",
               (sid, day, query, page_url, clicks, impressions, 0, position))


def test_periods_without_data(client):
    d = client.get(f"/api/sites/{new_site(client)}/compare/periods").json()
    assert d["search"]["has_data"] is False and d["traffic"]["has_data"] is False


def test_periods_compare_search_with_lower_position_as_better(client):
    sid = new_site(client)
    seed_search(sid, 40, "roof repair", "https://a.test/r", 10, 100, 12)
    seed_search(sid, 40, "lost term", "https://a.test/l", 8, 100, 5)
    seed_search(sid, 5, "roof repair", "https://a.test/r", 30, 100, 4)
    seed_search(sid, 5, "new term", "https://a.test/n", 2, 100, 6)
    s = client.get(f"/api/sites/{sid}/compare/periods?days=28").json()["search"]
    by = {m["label"]: m for m in s["metrics"]}
    assert (by["Clicks"]["before"], by["Clicks"]["after"], by["Clicks"]["status"]) == (18, 32, "improved")
    assert by["Average position"]["status"] == "improved" and by["Average position"]["change"] < 0
    assert (s["keywords_won"], s["keywords_lost"]) == (1, 1)
    assert s["queries"]["gainers"][0]["item"] == "roof repair" and s["queries"]["losers"][0]["item"] == "lost term"
    assert s["pages"]["gainers"][0]["change"] == 20


def test_short_history_is_flagged_so_growth_is_not_overstated(client):
    sid = new_site(client)
    seed_search(sid, 5, "roof repair", "https://a.test/r", 30, 100, 4)
    assert client.get(f"/api/sites/{sid}/compare/periods").json()["search"]["partial"] is True


def test_full_history_is_not_flagged(client):
    sid = new_site(client)
    seed_search(sid, 5, "a", "https://a.test/", 1, 10, 4)
    seed_search(sid, 60, "a", "https://a.test/", 1, 10, 4)
    assert client.get(f"/api/sites/{sid}/compare/periods").json()["search"]["partial"] is False


def test_periods_count_organic_traffic_only(client):
    from seo_dashboard import db
    sid = new_site(client)
    today = date.today()
    rows = [(sid, (today - timedelta(days=d)).isoformat(), lp, ch, s, s, s, c) for d, lp, ch, s, c in [
        (40, "/a", "Organic Search", 100, 2), (5, "/a", "Organic Search", 150, 5), (5, "/a", "Paid Search", 9999, 500)]]
    db.executemany("INSERT INTO analytics_metrics(site_id,date,landing_page,channel,sessions,users,engaged_sessions,conversions) VALUES(?,?,?,?,?,?,?,?)", rows)
    t = client.get(f"/api/sites/{sid}/compare/periods").json()["traffic"]
    by = {m["label"]: m for m in t["metrics"]}
    assert (by["Sessions"]["before"], by["Sessions"]["after"], by["Sessions"]["status"]) == (100, 150, "improved")
    assert by["Key events"]["after"] == 5


def test_period_days_are_clamped(client):
    assert client.get(f"/api/sites/{new_site(client)}/compare/periods?days=1").json()["days"] == 7
