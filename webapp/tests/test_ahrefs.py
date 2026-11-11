"""Ahrefs site analysis: free-only mode (0 API units), full mode with content gap,
fake GA4 key events, and the API endpoints. Ahrefs and Windsor.ai are mocked."""

import os
import sys
from datetime import date

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
pytest.importorskip("fastapi")
pytest.importorskip("httpx")


class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.text = data, status, str(data)

    def json(self):
        return self._d


def months(n=12):
    t = date.today().replace(day=1)
    out = []
    for i in range(n, 0, -1):
        y, m = t.year, t.month - i
        while m <= 0:
            m += 12
            y -= 1
        out.append(f"{y}-{m:02d}-01")
    return out


COMP_KW = [
    {"keyword": "seo agentura brno", "volume": 900, "keyword_difficulty": 25, "best_position": 3, "best_position_url": "https://comp.cz/sluzby/seo/", "is_commercial": True, "is_local": True},
    {"keyword": "seo agentura praha", "volume": 700, "keyword_difficulty": 30, "best_position": 5, "best_position_url": "https://comp.cz/sluzby/seo/", "is_commercial": True},
    {"keyword": "co je branding", "volume": 1200, "keyword_difficulty": 8, "best_position": 14, "best_position_url": "https://comp.cz/slovnik/branding/", "is_informational": True},
    {"keyword": "branding význam", "volume": 300, "keyword_difficulty": 10, "best_position": 12, "best_position_url": "https://comp.cz/slovnik/branding/", "is_informational": True},
    {"keyword": "facebook", "volume": 50000, "keyword_difficulty": 90, "best_position": 40, "best_position_url": "https://comp.cz/", "is_navigational": True},
    {"keyword": "marketingový mix", "volume": 800, "keyword_difficulty": 12, "best_position": 2, "best_position_url": "https://comp.cz/slovnik/mix/", "is_informational": True},
]


def make_get(units):
    def get(url, params=None, headers=None, timeout=None):
        p = params or {}
        if "api.ahrefs.com" in url:
            if headers.get("Authorization") != "Bearer good":
                return Resp({"error": "Invalid API key"}, 401)
            path = url.split("/v3/")[1]
            if path == "subscription-info/limits-and-usage":
                return Resp({"limits_and_usage": {"subscription": "Test", "units_limit_workspace": units, "units_usage_workspace": 0}})
            if path == "management/projects":
                return Resp({"projects": [{"project_id": "1242664", "project_name": "krejta.cz", "url": "krejta.cz/", "keyword_count": 52},
                                          {"project_id": "999", "project_name": "Other", "url": "www.other.cz/", "keyword_count": 0}]})
            if path == "public/domain-rating-free":
                return Resp({"domain_rating": {"targets": [{"target": "krejta.cz/", "domain_rating": 47.0}]}})
            if path.startswith("gsc/"):
                return Resp({"metrics": []})
            if not units:
                return Resp({"error": "API units limit reached. Expected usage: 50, API units left: 0."}, 400)
            ms = months()
            if path == "site-explorer/metrics":
                return Resp({"metrics": {"org_traffic": 1500, "org_cost": 123400, "org_keywords": 400, "org_keywords_1_3": 120}})
            if path == "site-explorer/backlinks-stats":
                return Resp({"metrics": {"live_refdomains": 300, "all_time_refdomains": 520, "live": 4000, "all_time": 9000}})
            if path == "site-explorer/domain-rating":
                return Resp({"domain_rating": {"domain_rating": 47.0, "ahrefs_rank": 812345}})
            if path == "site-explorer/metrics-history":
                return Resp({"metrics": [{"date": m, "org_traffic": 2000 - i * 50} for i, m in enumerate(ms)]})
            if path == "site-explorer/refdomains-history":
                return Resp({"refdomains": [{"date": m, "refdomains": 200 + i * 10} for i, m in enumerate(ms)]})
            if path == "site-explorer/domain-rating-history":
                return Resp({"domain_ratings": [{"date": m, "domain_rating": 47.0} for m in ms]})
            if path == "site-explorer/organic-competitors":
                return Resp({"competitors": [{"competitor_domain": "comp.cz", "domain_rating": 55, "keywords_common": 120, "keywords_competitor": 2000, "keywords_target": 280, "traffic": 9000}]})
            if path == "site-explorer/organic-keywords":
                if p["target"] == "comp.cz":
                    return Resp({"keywords": COMP_KW})
                if "is_branded" in p["select"]:
                    return Resp({"keywords": [{"keyword": "krejta", "is_branded": True}, {"keyword": "seo audit", "is_commercial": True}]})
                return Resp({"keywords": [{"keyword": "marketingový mix", "best_position": 7, "volume": 800}]})
            return Resp({"error": "unknown " + path}, 404)
        if "windsor.ai" in url:  # GA4 key events
            rows = []
            for i, m in enumerate(months(6)):
                rows += [{"account_id": "298270132", "account_name": "KREJTA.CZ – GA4", "date": m, "event_name": "contact_form_submit", "conversions": 4 + i},
                         {"account_id": "298270132", "account_name": "KREJTA.CZ – GA4", "date": m, "event_name": "cookie_souhlas", "conversions": 300}]
            if "fields" in p and p["fields"].startswith("account_id,account_name"):
                if url.endswith("googleanalytics4"):
                    return Resp({"data": [{"account_id": "298270132", "account_name": "KREJTA.CZ – GA4", "sessions": 1}]})
                return Resp({"data": [{"account_id": "https://krejta.cz/", "account_name": "https://krejta.cz/", "clicks": 1}]})
            return Resp({"data": rows})
        raise AssertionError(url)
    return get


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SEO_DASHBOARD_DATA", str(tmp_path))
    monkeypatch.setenv("SEO_DASHBOARD_DB", str(tmp_path / "a.db"))
    monkeypatch.setenv("SEO_DASHBOARD_SCHEDULER", "0")
    import importlib

    from seo_dashboard import db
    importlib.reload(db)
    db.init_db()
    from seo_dashboard.integrations import ahrefs, windsor
    importlib.reload(ahrefs)
    importlib.reload(windsor)
    from seo_dashboard.analyzers import ahrefs_report
    importlib.reload(ahrefs_report)
    db.set_setting("ahrefs_api_key", "good")
    db.set_setting("windsor_api_key", "w")
    cid = db.execute("INSERT INTO clients(name, created_at) VALUES('Krejta', 'x')")
    sid = db.execute("INSERT INTO sites(client_id, url, created_at) VALUES(?, 'https://www.krejta.cz/', 'x')", (cid,))
    for i, m in enumerate(months()):
        db.execute("INSERT INTO search_metrics(site_id, date, query, page, clicks, impressions, ctr, position, source) VALUES(?,?,?,?,?,?,?,?, 'gsc')",
                   (sid, m, "q", "/", 100 - i * 6, 5000 - i * 300, 0.02, 8))
    return db, ahrefs, ahrefs_report, sid, monkeypatch


def test_zero_units_runs_free_parts(env):
    db, ahrefs, rep, sid, mp = env
    mp.setattr(ahrefs.requests, "get", make_get(0))
    r = rep.run(sid)
    assert r["project"]["project_id"] == "1242664"
    assert r["plan"]["units_left"] == 0 and any("0" in s and "units" in s for s in r["skipped"])
    assert "gap" not in r
    titles = {c["title"] for c in r["cards"]}
    assert {"Domain Rating", "Impressions"} <= titles
    imp = next(c for c in r["cards"] if c["title"] == "Impressions")
    assert imp["status"] == "warn" and "Windsor.ai" in imp["value"]
    assert r["chain"][1]["ok"] is False and "Impressions" in r["headline"]
    assert r["conversions"].get("fake_events") == ["cookie_souhlas"], r["conversions"]
    assert all(v < 100 for v in r["conversions"]["leads_by_month"].values())  # cookie events excluded
    assert db.row("SELECT COUNT(*) n FROM ahrefs_reports")["n"] == 1


def test_full_run_with_content_gap(env):
    db, ahrefs, rep, sid, mp = env
    mp.setattr(ahrefs.requests, "get", make_get(100000))
    r = rep.run(sid)
    assert not r["skipped"]
    rd = next(c for c in r["cards"] if c["title"] == "Referring domains")
    assert rd["status"] == "warn" and "DR stayed flat" in rd["action"]
    assert {"Referring domains", "Domain Rating", "Organic traffic (Ahrefs)"} <= set(r["indexed"])
    g = r["gap"]
    assert g["competitor"] == "comp.cz"
    topics = {t["topic"]: t for t in g["topics"]}
    assert topics["agentura"]["priority"] == 1 or topics.get("seo", {}).get("priority") == 1
    assert topics["branding"]["priority"] == 2 and "Winnable" in topics["branding"]["action"]
    assert any(s["keyword"] == "facebook" for s in g["skipped"])
    assert g["shared"][0]["keyword"] == "marketingový mix" and g["shared"][0]["winner"] == "competitor"
    assert r["quick_wins"] and r["long_term"]


def test_competitor_from_site_settings(env):
    db, ahrefs, rep, sid, mp = env
    mp.setattr(ahrefs.requests, "get", make_get(100000))
    db.execute("UPDATE sites SET competitors = 'https://www.comp.cz/' WHERE id = ?", (sid,))
    assert rep.run(sid)["gap"]["competitor"] == "comp.cz"


def test_bad_key(env):
    db, ahrefs, rep, sid, mp = env
    mp.setattr(ahrefs.requests, "get", make_get(0))
    db.set_setting("ahrefs_api_key", "wrong")
    with pytest.raises(ahrefs.AhrefsError, match="rejected the API key"):
        ahrefs.limits()


def test_endpoints(env):
    db, ahrefs, rep, sid, mp = env
    mp.setattr(ahrefs.requests, "get", make_get(0))
    import importlib

    from seo_dashboard import app as app_mod
    importlib.reload(app_mod)
    from fastapi.testclient import TestClient
    with TestClient(app_mod.app) as c:
        t = c.post("/api/ahrefs/test").json()
        assert t["units_left"] == 0 and len(t["projects"]) == 2
        p = c.get("/api/ahrefs/projects", params={"site_url": "https://krejta.cz"}).json()
        assert p["suggested"] == "1242664"
        assert c.get(f"/api/sites/{sid}/ahrefs").json()["report"] is None
        assert c.post(f"/api/sites/{sid}/ahrefs?gap=0").json()["report"]["project"]["project_id"] == "1242664"
        assert c.get(f"/api/sites/{sid}/ahrefs").json()["report"]["domain"] == "krejta.cz"
        s = c.get("/api/settings").json()
        assert s["ahrefs_api_key"].startswith("•")
