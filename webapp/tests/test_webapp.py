"""End-to-end tests for the SEO dashboard against a local fixture website.

Run: python3 -m pytest webapp/tests/ (needs requirements.txt + pytest + httpx).
"""

import io
import os
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
openpyxl = pytest.importorskip("openpyxl")

from fixture_server import serve  # noqa: E402


@pytest.fixture(scope="module")
def site_port():
    srv, port = serve()
    os.environ["CLAUDE_SEO_LOCAL_TARGETS"] = f"127.0.0.1:{port}"
    yield port
    srv.shutdown()


@pytest.fixture(scope="module")
def client(tmp_path_factory, site_port):
    data = tmp_path_factory.mktemp("data")
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
        c.put("/api/settings", json={"pagespeed_enabled": "0"})
        yield c


@pytest.fixture(scope="module")
def result(client, site_port, monkeypatch_module):
    from seo_dashboard.analyzers import keywords
    monkeypatch_module.setattr(keywords, "autocomplete", lambda q, hl="en", timeout=6: [])
    cid = client.post("/api/clients", json={"name": "Jane Rivera", "company": "Acme"}).json()["id"]
    sid = client.post("/api/sites", json={"client_id": cid, "url": f"http://127.0.0.1:{site_port}/", "industry": "home services",
                                          "location": "Austin", "max_pages": 30, "interval_hours": 24}).json()["id"]
    aid = client.post(f"/api/sites/{sid}/audit").json()["audit_id"]
    for _ in range(120):
        st = client.get(f"/api/audits/{aid}").json()
        if st["status"] != "running":
            break
        time.sleep(0.5)
    assert st["status"] == "done", st
    return {"aid": aid, "sid": sid, "cid": cid, "data": client.get(f"/api/audits/{aid}/result").json()}


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def ids(r):
    return {i["id"] for i in r["issues"]}


def test_detects_core_technical_issues(result):
    r = result["data"]
    found = ids(r)
    for expected in ("pages_404", "broken_internal_links", "noindex_pages", "noindex_in_sitemap", "missing_canonical",
                     "no_structured_data", "orphan_pages", "no_viewport", "ai_crawlers_blocked", "llms_missing",
                     "links_to_redirects", "missing_meta_description", "heading_skips"):
        assert expected in found, expected


def test_redirect_suggestion_and_redirect_not_parsed(result):
    r = result["data"]
    sugg = r["technical"]["redirect_suggestions"]
    assert any(s["from"].endswith("/old-page") and s["to"] for s in sugg)
    moved = next(p for p in r["pages"] if p["url"].endswith("/moved"))
    assert moved["status"] == 301 and moved["words"] is None


def test_scores_priorities_roadmap(result):
    r = result["data"]
    assert 0 <= r["scores"]["overall"] <= 100
    assert len(r["top10"]) == 10 and r["top10"][0]["rank"] == 1
    assert [p["name"][:7] for p in r["roadmap"]["phases"]] == ["Days 1–", "Days 31", "Days 61"]


def test_keywords_meta_links_geo_conversion(result):
    r = result["data"]
    assert r["keywords"]["keywords"] and r["keywords"]["intent_counts"]
    assert all(m["source_url"] and m["suggested_title"] for m in r["meta_suggestions"])
    assert all(len(m["suggested_title"]) <= 62 for m in r["meta_suggestions"])
    assert r["links"]["tree"]["children"]
    assert any(e["event_name"] == "generate_lead" for e in r["conversion"]["events"])
    assert any(e["event_name"] == "click_to_call" for e in r["conversion"]["events"])
    assert r["geo"]["brief"]["playbook"] and r["offpage"]["platforms"]


def test_exports(client, result):
    aid = result["aid"]
    x = client.get(f"/api/audits/{aid}/export.xlsx")
    assert x.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(x.content))
    assert {"Summary", "Top 10 Actions", "Roadmap 30-60-90", "Internal Link Suggestions", "Keyword Research"} <= set(wb.sheetnames)
    assert len(wb["Summary"]._charts) >= 2
    li = client.get(f"/api/audits/{aid}/internal-links.xlsx")
    assert li.status_code == 200 and "Internal Link Suggestions" in openpyxl.load_workbook(io.BytesIO(li.content)).sheetnames
    h = client.get(f"/api/audits/{aid}/report.html")
    assert h.status_code == 200 and h.text.count("<svg") >= 8 and "Top 10 priority actions" in h.text


def test_photo_upload_validation(client, result):
    cid = result["cid"]
    bad = client.post(f"/api/clients/{cid}/photo", files={"file": ("x.png", b"<svg onload=alert(1)>", "image/png")})
    assert bad.status_code == 400
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    ok = client.post(f"/api/clients/{cid}/photo", files={"file": ("x.png", png, "image/png")})
    assert ok.status_code == 200
    assert client.get(f"/uploads/{ok.json()['photo']}").status_code == 200
    assert client.get("/uploads/..%2Fdashboard.db").status_code == 404


def test_rejects_private_urls(client, result):
    r = client.post("/api/sites", json={"client_id": result["cid"], "url": "http://169.254.169.254/latest"})
    assert r.status_code == 400


def test_settings_masking(client):
    client.put("/api/settings", json={"windsor_api_key": "secret-key-1234"})
    s = client.get("/api/settings").json()
    assert s["windsor_api_key"].endswith("1234") and "secret" not in s["windsor_api_key"]
    client.put("/api/settings", json={"windsor_api_key": s["windsor_api_key"]})  # masked echo keeps value
    from seo_dashboard import db
    assert db.get_setting("windsor_api_key") == "secret-key-1234"


def test_search_metrics_trends(client, result):
    from datetime import date, timedelta

    from seo_dashboard import db
    sid = result["sid"]
    rows = []
    for d in range(60):
        day = (date.today() - timedelta(days=60 - d)).isoformat()
        rows.append((sid, day, "emergency plumber", "/", 5 + d, 100, 0.05, 20 - d * 0.2, "gsc"))
    db.executemany("INSERT INTO search_metrics(site_id,date,query,page,clicks,impressions,ctr,position,source) VALUES(?,?,?,?,?,?,?,?,?)", rows)
    s = client.get(f"/api/sites/{sid}/search").json()["search"]
    assert s["has_data"] and s["improved"] and s["improved"][0]["query"] == "emergency plumber"


def test_scheduler_due(result):
    from seo_dashboard import db, scheduler
    db.execute("UPDATE sites SET last_run_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (result["sid"],))
    assert any(s["id"] == result["sid"] for s in scheduler.due_sites())
