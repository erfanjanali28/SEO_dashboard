"""Windsor.ai integration: account listing, auto-matching and per-account filtering
against a mocked multi-account workspace (no network)."""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

pytest.importorskip("requests")

GSC_ACCOUNTS = ["https://krejta.cz/", "atemit.cz", "https://www.prezuvky.sk/"]
GA4_ACCOUNTS = [("298270132", "KREJTA.CZ – GA4"), ("360347584", "Atemit.cz GA4"), ("320230937", "Prezuvky.sk")]


class FakeResp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.text = data, status, str(data)

    def json(self):
        return self._d


def fake_get(calls, bad_key=False, strict_select=False):
    def get(url, params=None, timeout=None):
        calls.append((url, dict(params)))
        if bad_key:
            return FakeResp({"error": "invalid key"}, 401)
        sel = params.get("select_accounts")
        if url.endswith("searchconsole"):
            rows = [{"account_id": a, "account_name": a, "date": "2026-10-20", "query": f"q {a}", "page": a,
                     "clicks": 3, "impressions": 30, "ctr": 0.1, "position": 4.2} for a in GSC_ACCOUNTS]
        else:
            rows = [{"account_id": i, "account_name": n, "date": "20261020", "landing_page": "/", "session_default_channel_group": "Organic Search",
                     "sessions": 10, "totalusers": 8, "engaged_sessions": 6, "conversions": 1} for i, n in GA4_ACCOUNTS]
        if sel:
            # strict_select simulates Windsor ignoring an unexpected select_accounts spelling
            rows = [] if strict_select else [r for r in rows if r["account_id"] == sel]
        return FakeResp({"data": rows})
    return get


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SEO_DASHBOARD_DATA", str(tmp_path))
    monkeypatch.setenv("SEO_DASHBOARD_DB", str(tmp_path / "w.db"))
    import importlib

    from seo_dashboard import db
    importlib.reload(db)
    db.init_db()
    from seo_dashboard.integrations import windsor
    importlib.reload(windsor)
    db.set_setting("windsor_api_key", "k")
    cid = db.execute("INSERT INTO clients(name, created_at) VALUES('c', 'x')")

    def site(url, gsc=None, ga4=None):
        sid = db.execute("INSERT INTO sites(client_id, url, windsor_gsc_account, windsor_ga4_account, created_at) VALUES(?,?,?,?, 'x')",
                         (cid, url, gsc, ga4))
        return db.row("SELECT * FROM sites WHERE id = ?", (sid,))
    return db, windsor, site, monkeypatch


def test_list_and_auto_match(env):
    db, windsor, site, mp = env
    mp.setattr(windsor.requests, "get", fake_get([]))
    acc = windsor.list_accounts()
    assert len(acc["gsc"]) == 3 and len(acc["ga4"]) == 3
    assert windsor.auto_match("https://www.krejta.cz", acc) == {"gsc": "https://krejta.cz/", "ga4": "298270132"}
    assert windsor.auto_match("atemit.cz", acc) == {"gsc": "atemit.cz", "ga4": "360347584"}
    assert windsor.auto_match("https://unknown.com", acc) == {"gsc": None, "ga4": None}


def test_sync_keeps_only_the_sites_own_rows(env):
    db, windsor, site, mp = env
    mp.setattr(windsor.requests, "get", fake_get([]))
    s = site("https://krejta.cz/")
    r = windsor.sync_site(s)
    assert r["accounts"] == {"gsc": "https://krejta.cz/", "ga4": "298270132"} and not r["errors"]
    assert {x["query"] for x in db.rows("SELECT query FROM search_metrics")} == {"q https://krejta.cz/"}
    assert db.row("SELECT COUNT(*) n FROM analytics_metrics")["n"] == 1
    saved = db.row("SELECT * FROM sites WHERE id = ?", (s["id"],))
    assert saved["windsor_gsc_account"] == "https://krejta.cz/"  # remembered for next time


def test_select_accounts_fallback_filters_locally(env):
    db, windsor, site, mp = env
    mp.setattr(windsor.requests, "get", fake_get([], strict_select=True))
    s = site("https://atemit.cz", gsc="sc-domain:atemit.cz", ga4="360347584")
    r = windsor.sync_site(s)
    assert r["gsc_rows"] == 1 and r["ga4_rows"] == 1
    assert db.row("SELECT query FROM search_metrics")["query"] == "q atemit.cz"


def test_resync_removes_previously_mixed_rows(env):
    db, windsor, site, mp = env
    s = site("https://krejta.cz/", gsc="https://krejta.cz/", ga4="298270132")
    db.execute("INSERT INTO search_metrics(site_id, date, query, page, clicks, impressions, ctr, position, source) "
               "VALUES(?, date('now','-5 day'), 'someone else', '/x', 9, 9, 1, 1, 'gsc')", (s["id"],))
    mp.setattr(windsor.requests, "get", fake_get([]))
    windsor.sync_site(s)
    assert "someone else" not in {x["query"] for x in db.rows("SELECT query FROM search_metrics")}


def test_unmatched_site_does_not_import_everything(env):
    db, windsor, site, mp = env
    mp.setattr(windsor.requests, "get", fake_get([]))
    r = windsor.sync_site(site("https://unknown.com"))
    assert r["gsc_rows"] == 0 and r["ga4_rows"] == 0 and any("Choose one" in n for n in r["notes"])
    assert db.row("SELECT COUNT(*) n FROM search_metrics")["n"] == 0


def test_bad_key_message(env):
    db, windsor, site, mp = env
    mp.setattr(windsor.requests, "get", fake_get([], bad_key=True))
    with pytest.raises(windsor.WindsorError, match="rejected the API key"):
        windsor.list_accounts()
