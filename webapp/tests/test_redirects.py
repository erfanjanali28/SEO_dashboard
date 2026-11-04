"""Redirect, canonical, cannibalization and first-look behaviour.

The unit tests build a small fake crawl so each rule is checked on its own. The
rules that protect a site (never redirect home, never merge different intent)
matter more here than the happy paths.
"""

import os
import sqlite3
import sys
import time
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
openpyxl = pytest.importorskip("openpyxl")

from seo_dashboard.analyzers import redirects  # noqa: E402

O = "https://acme.test"
ROOF = " ".join(f"roof repair detail number {w} explains flashing tiles gutters and leaks" for w in "abcdefghijklmnopqrstuvwxyz")
PRICE = " ".join(f"pricing table row {w} covers invoices discounts contracts and payment terms" for w in "abcdefghijklmnopqrstuvwxyz")
STORY = " ".join(f"company history chapter {w} recalls founders offices people and early projects" for w in "abcdefghijklmnopqrstuvwxyz")


def page(path, text=ROOF, title="Page", status=200, **kw):
    url = O + path
    return {"url": url, "status": status, "final_url": url, "redirect_chain": [], "word_count": len(text.split()), "text": text,
            "title": title, "h1": [title], "text_hash": str(hash(text)), "canonical": None, "meta_robots": "", "x_robots_tag": "",
            "internal_links": [], "inlink_count": 0, "inlinks": [], "depth": 1, "lang": "en", "forms": [], "ctas": [], "schema": [], **kw}


def dead(path, status=404):
    return {"url": O + path, "status": status, "final_url": O + path, "redirect_chain": []}


def run(pages, tech=None, cont=None, suggestions=None, gsc=None, kw=None, link_status=None):
    crawl = SimpleNamespace(pages={p["url"]: p for p in pages}, origin=O, link_status=link_status or {}, sitemaps={"urls": []}, robots={}, llms_txt={})
    tech = {"redirect_suggestions": [], "broken_links": [], "links_to_redirects": [], **(tech or {})}
    cont = {"near_duplicates": [], "cannibalization": [], **(cont or {})}
    return redirects.analyze(crawl, kw or {}, tech, cont, suggestions or [], gsc)


def by_from(result):
    return {r["from"]: r for r in result["redirects"]}


def dead_tech(path, sources=(), anchor="", status=404):
    return {"redirect_suggestions": [{"from": O + path, "status": status}],
            "broken_links": [{"source": s, "target": O + path, "status": status, "anchor": anchor, "internal": True} for s in sources]}


def test_404_goes_to_matching_page_using_anchor_text():
    pages = [page("/", title="Home", text=STORY), page("/services/roof-repair/", title="Roof repair"), page("/pricing/", title="Pricing", text=PRICE), dead("/old/roof-fixes")]
    out = run(pages, tech=dead_tech("/old/roof-fixes", [O + "/"], "roof repair"))
    row = by_from(out)[O + "/old/roof-fixes"]
    assert row["method"] == "301" and row["to"] == O + "/services/roof-repair/"
    assert any(u["kind"] == "Fix broken link" and u["new"] == row["to"] for u in out["link_updates"])


def test_404_uses_diacritic_free_matching():
    pages = [page("/strechy/", title="Střechy Brno"), dead("/stare-strechy")]
    assert by_from(run(pages, tech=dead_tech("/stare-strechy")))[O + "/stare-strechy"]["to"] == O + "/strechy/"


def test_404_with_no_equivalent_gets_410_and_never_the_home_page():
    pages = [page("/", title="Home", text=STORY), page("/services/roof-repair/", title="Roof repair"), dead("/old-page")]
    out = run(pages, tech=dead_tech("/old-page", [O + "/"], "Old offers"))
    row = by_from(out)[O + "/old-page"]
    assert row["method"] == "410" and row["to"] is None
    assert any(u["kind"] == "Remove broken link" for u in out["link_updates"])


def test_internal_link_suggestion_can_decide_the_target():
    pages = [page("/services/gutter/", title="Gutter care"), page("/services/tiles/", title="Tile work"), page("/about/", title="About", text=STORY), dead("/services/gutter-tile")]
    sugg = [{"source_url": O + "/about/", "target_url": O + "/services/tiles/", "anchor_text": "tile", "target_title": ""}]
    out = run(pages, tech=dead_tech("/services/gutter-tile", [O + "/about/"]), suggestions=sugg)
    assert by_from(out)[O + "/services/gutter-tile"]["to"] == O + "/services/tiles/"


def test_identical_content_redirects_but_parameter_url_is_canonicalized():
    keep = page("/roof/", title="Roof")
    copy = page("/roof-copy/", title="Roof")
    param = page("/roof/?sort=asc", title="Roof")
    out = run([keep, copy, param])
    assert by_from(out)[O + "/roof-copy/"]["to"] == O + "/roof/"
    assert O + "/roof/?sort=asc" not in by_from(out)
    assert next(c for c in out["canonicals"] if c["url"] == O + "/roof/?sort=asc")["target"] == O + "/roof/"


def test_same_page_in_two_folders_is_canonicalized_not_redirected():
    out = run([page("/a/widget/", title="Widget", inlink_count=9), page("/b/widget/", title="Widget")])
    assert not out["redirects"]
    assert next(c for c in out["canonicals"] if c["url"] == O + "/b/widget/")["target"] == O + "/a/widget/"


def test_home_page_is_never_redirected():
    out = run([page("/", title="Home"), page("/landing/", title="Landing", inlink_count=50)])
    assert O + "/" not in by_from(out)
    assert by_from(out)[O + "/landing/"]["to"] == O + "/"


def test_pages_already_canonicalized_need_nothing():
    out = run([page("/roof/", title="Roof"), page("/roof-copy/", title="Roof", canonical=O + "/roof/")])
    assert not out["redirects"] and out["summary"]["already_canonicalized"] == 1


def cannibal(*paths, kw="roof repair", **extra):
    return {"cannibalization": [{"keyword": kw, "pages": [O + p for p in paths], **extra}]}


def test_cannibalization_same_text_redirects_to_the_page_with_clicks():
    a, b = page("/a/", ROOF + " extra words here for the first", "A"), page("/b/", ROOF + " other words there for the second", "B", inlink_count=30)
    gsc = [{"query": "roof repair", "page": O + "/a/", "clicks": 40, "impressions": 900}]
    out = run([a, b], cont=cannibal("/a/", "/b/", source="search console"), gsc=gsc)
    assert by_from(out)[O + "/b/"]["to"] == O + "/a/"


def test_cannibalization_with_little_shared_text_keeps_both():
    out = run([page("/a/", ROOF, "A"), page("/b/", PRICE, "B")], cont=cannibal("/a/", "/b/"))
    assert not out["redirects"]
    assert out["decisions"][0]["action"] == "Keep both and differentiate"


def test_cannibalization_different_page_types_keeps_both():
    blog, contact = page("/blog/roof-guide/", ROOF, "Guide"), page("/contact", ROOF + " contact us today", "Contact")
    assert redirects.page_type(blog) != redirects.page_type(contact)
    out = run([blog, contact], cont=cannibal("/blog/roof-guide/", "/contact"))
    assert not out["redirects"]
    assert out["decisions"][0]["action"] == "Keep both and differentiate" and "page types" in out["decisions"][0]["why"]


def test_partial_overlap_needs_a_merge_and_warns_about_stuffing():
    half = " ".join(ROOF.split()[:len(ROOF.split()) // 2 + 30])
    kw = {O + "/a/": [("roof repair", 1)], O + "/b/": [("roof repair", 1)]}
    out = run([page("/a/", ROOF, "A", inlink_count=9), page("/b/", half + " " + PRICE, "B")], cont=cannibal("/a/", "/b/"), kw=kw)
    row = by_from(out)[O + "/b/"]
    assert row["action"] == "Merge, then 301" and row["merge_first"]
    assert "rewrite while merging" in row["reason"]


def test_a_page_that_owns_another_keyword_is_not_redirected():
    a, b, c = page("/a/", ROOF + " one two three four five", "A", inlink_count=9), page("/b/", ROOF + " six seven eight nine ten", "B", inlink_count=5), page("/c/", ROOF + " red green blue pink gold", "C")
    cont = {"cannibalization": [{"keyword": "roof repair", "pages": [a["url"], b["url"]]}, {"keyword": "tile leaks", "pages": [b["url"], c["url"]]}]}
    out = run([a, b, c], cont=cont)
    assert b["url"] not in by_from(out)
    assert c["url"] in by_from(out)


def test_different_languages_are_never_consolidated():
    out = run([page("/en/roof/", title="Roof"), page("/cs/roof/", title="Roof", lang="cs")])
    assert not out["redirects"] and not any("rel" in (c["tag"] or "") and c["problem"] == "Duplicate content" for c in out["canonicals"])


def test_template_family_is_not_collapsed():
    cities = [page(f"/city-{n}/", ROOF + f" city {n}", f"City {n}") for n in "abcd"]
    near = [{"url_a": x["url"], "url_b": y["url"], "similarity": 0.95} for i, x in enumerate(cities) for y in cities[i + 1:]]
    out = run(cities, cont={"near_duplicates": near})
    assert not out["redirects"]
    assert all(d["action"].startswith("Keep both") for d in out["decisions"])


def test_targets_never_form_a_redirect_chain():
    """A 404 pointing at a page being consolidated must go to the final page."""
    a, b = page("/roof/", ROOF + " one two three four five", "Roof", inlink_count=9), page("/roof-repair/", ROOF + " six seven eight nine ten", "Roof repair")
    out = run([a, b, dead("/roof-repair-old")], tech=dead_tech("/roof-repair-old"), cont=cannibal("/roof/", "/roof-repair/"))
    rows = by_from(out)
    assert not ({r["to"] for r in rows.values()} & set(rows))
    assert rows[O + "/roof-repair-old"]["to"] == a["url"]


def test_suggestion_to_a_redirected_url_is_retargeted():
    a, b = page("/roof/", title="Roof", inlink_count=9), page("/roof-copy/", title="Roof")
    other = page("/about/", STORY, "About")
    sugg = [{"source_url": other["url"], "target_url": b["url"], "anchor_text": "roof repair", "target_title": ""}]
    out = run([a, b, other], suggestions=sugg)
    row = next(u for u in out["link_updates"] if u["kind"] == "Retarget suggestion")
    assert row["new"] == a["url"]


def test_same_anchor_on_different_pages_is_aligned():
    src = page("/about/", STORY, "About", internal_links=[{"href": O + "/x/", "text": "roof repair", "nav": False}, {"href": O + "/y/", "text": "roof repair", "nav": False}])
    kw = {O + "/x/": [("roof repair", 1)], O + "/y/": [("roof repair", 1)]}
    out = run([src, page("/x/", ROOF, "Roof repair", inlink_count=9), page("/y/", PRICE, "Roof repair prices")], kw=kw)
    row = next(u for u in out["link_updates"] if u["kind"] == "Align anchor")
    assert row["current"] == O + "/y/" and row["new"] == O + "/x/"


def test_service_page_beats_a_listing_without_click_data():
    service, listing = page("/services/water/", ROOF, "Water supply"), page("/references/category/water/", PRICE, "Water supply", inlink_count=40)
    out = run([service, listing], cont=cannibal("/services/water/", "/references/category/water/", kw="water supply"))
    assert out["decisions"][0]["winner"] == service["url"]


def test_clicks_still_beat_the_listing_rule():
    service, listing = page("/services/water/", ROOF, "Water supply"), page("/references/category/water/", PRICE, "Water supply")
    gsc = [{"query": "water supply", "page": listing["url"], "clicks": 50, "impressions": 900}]
    out = run([service, listing], cont=cannibal("/services/water/", "/references/category/water/", kw="water supply"), gsc=gsc)
    assert out["decisions"][0]["winner"] == listing["url"]


def test_phrase_missing_from_the_title_is_not_a_keyword_conflict():
    links = [{"href": O + "/x/", "text": "contact us", "nav": False}, {"href": O + "/y/", "text": "contact us", "nav": False}]
    kw = {O + "/x/": [("contact us", 1)], O + "/y/": [("contact us", 1)]}
    out = run([page("/about/", STORY, "About", internal_links=links), page("/x/", ROOF, "Careers"), page("/y/", PRICE, "Open position")], kw=kw)
    assert not [u for u in out["link_updates"] if u["kind"] == "Align anchor"]


def test_generic_labels_are_not_anchor_conflicts():
    links = [{"href": O + "/x/", "text": "read more", "nav": False}, {"href": O + "/y/", "text": "read more", "nav": False}]
    out = run([page("/about/", STORY, "About", internal_links=links), page("/x/", ROOF, "X"), page("/y/", PRICE, "Y")])
    assert not [u for u in out["link_updates"] if u["kind"] == "Align anchor"]


def test_anchors_never_move_a_page_to_another_language():
    links = [{"href": O + "/en/x/", "text": "roof repair", "nav": False}, {"href": O + "/cs/x/", "text": "roof repair", "nav": False}]
    kw = {O + "/en/x/": [("roof repair", 1)], O + "/cs/x/": [("roof repair", 1)]}
    pages = [page("/en/about/", STORY, "About", internal_links=links), page("/en/x/", ROOF, "Roof repair"), page("/cs/x/", PRICE, "Roof repair", inlink_count=50, lang="cs")]
    sugg = [{"source_url": O + "/en/about/", "target_url": u, "anchor_text": "roof repair", "target_title": ""} for u in (O + "/en/x/", O + "/cs/x/")]
    assert not run(pages, kw=kw, suggestions=sugg)["link_updates"]


def test_sitewide_link_is_one_update_with_a_page_count():
    links = {"links_to_redirects": [{"source": O + f"/p{i}/", "target": O + "/moved", "final": O + "/final/", "anchor": "Contact"} for i in range(5)]}
    pages = [page(f"/p{i}/", STORY + f" {i}", f"P{i}") for i in range(5)] + [page("/final/", PRICE, "Final")]
    out = run(pages, tech=links)
    assert len(out["link_updates"]) == 1 and out["link_updates"][0]["pages"] == 5 and out["summary"]["links_affected"] == 5


def test_typo_url_is_high_confidence():
    pages = [page("/en/testimonials/", STORY, "Our work"), dead("/en/testimionals")]
    row = by_from(run(pages, tech=dead_tech("/en/testimionals")))[O + "/en/testimionals"]
    assert row["to"] == O + "/en/testimonials/" and row["confidence"] == "high" and "typo" in row["reason"]


def test_static_files_are_revalidated_so_updates_appear(app_client):
    client, _ = app_client
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/static/app.js").headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("declared, status, problem", [
    ("/gone/", 404, "Canonical points to an error page"),
    ("https://other.test/page/", None, "Canonical points to another domain"),
])
def test_canonical_problems(declared, status, problem):
    url = declared if declared.startswith("http") else O + declared
    out = run([page("/a/", canonical=url)], link_status={url: {"status": status}} if status else None)
    assert next(c for c in out["canonicals"] if c["url"] == O + "/a/")["problem"] == problem


def test_canonical_to_redirect_uses_the_final_url():
    final = page("/final/", PRICE, "Final")
    moved = {**dead("/moved/"), "status": 301, "final_url": final["url"], "redirect_chain": [[O + "/moved/", 301]], "final_status": 200}
    out = run([page("/a/", canonical=moved["url"]), moved, final])
    row = next(c for c in out["canonicals"] if c["url"] == O + "/a/")
    assert row["target"] == final["url"] and final["url"] in row["tag"]


def test_canonical_between_different_pages_is_flagged():
    out = run([page("/a/", ROOF, "A", canonical=O + "/b/"), page("/b/", PRICE, "B", canonical=O + "/b/")])
    assert next(c for c in out["canonicals"] if c["url"] == O + "/a/")["problem"] == "Canonical between different pages"


def test_noindex_with_canonical_is_a_conflict():
    out = run([page("/a/", ROOF, "A", canonical=O + "/b/", meta_robots="noindex"), page("/b/", PRICE, "B")])
    row = next(c for c in out["canonicals"] if c["url"] == O + "/a/")
    assert row["problem"] == "Noindex combined with canonical" and row["target"] is None


def test_keyword_stuffing_is_flagged_but_natural_copy_is_not():
    stuffed = page("/a/", " ".join(["roof repair is what we sell every day"] * 40), "A")
    natural = page("/b/", PRICE + " roof repair", "B")
    crawl = SimpleNamespace(pages={stuffed["url"]: stuffed, natural["url"]: natural})
    rows = redirects.keyword_stuffing(crawl, {stuffed["url"]: [("roof repair", 1)], natural["url"]: [("roof repair", 1)]})
    assert [r["url"] for r in rows] == [stuffed["url"]] and rows[0]["severity"] == "high"


def test_listing_labels_are_not_keyword_stuffing():
    """Real case: a category name repeating as a card tag, with almost no prose."""
    listing = page("/references/water/", " ".join(["water supply project card location budget"] * 40), "Water", prose="A short intro to our work.")
    crawl = SimpleNamespace(pages={listing["url"]: listing})
    assert not redirects.keyword_stuffing(crawl, {listing["url"]: [("water supply", 1)]})


def test_long_card_anchors_are_not_anchor_stuffing():
    text = "project name location okres budget million crowns without tax"
    src = page("/list/", STORY, "List", internal_links=[{"href": O + "/p/", "text": text, "nav": False}] * 6)
    crawl = SimpleNamespace(pages={src["url"]: src})
    assert not redirects.keyword_stuffing(crawl, {})


def test_server_rules_skip_low_confidence_and_query_strings():
    rows = [
        {"from": O + "/a/", "to": O + "/b/", "confidence": "high", "source": "x"},
        {"from": O + "/c/", "to": None, "confidence": "medium", "source": "x"},
        {"from": O + "/d/", "to": O + "/b/", "confidence": "low", "source": "x"},
        {"from": O + "/e/?id=1", "to": O + "/b/", "confidence": "high", "source": "x"},
        {"from": O + "/f/\nRedirect 301 /admin http://evil.test", "to": O + "/b/", "confidence": "high", "source": "x"},
    ]
    rules = redirects.server_rules(rows)
    assert f"Redirect 301 /a/ {O}/b/" in rules["apache"] and "Redirect gone /c/" in rules["apache"]
    assert "location = /c/ { return 410; }" in rules["nginx"]
    assert "/d/" not in rules["apache"] and "/e/" not in rules["apache"] and "evil" not in rules["apache"]
    assert rules["skipped"] == 2


# ---------------- first look ----------------
@pytest.fixture(scope="module")
def app_client(tmp_path_factory):
    from fixture_server import serve
    srv, port = serve()
    os.environ["CLAUDE_SEO_LOCAL_TARGETS"] = f"127.0.0.1:{port}"
    data = tmp_path_factory.mktemp("fl")
    os.environ["SEO_DASHBOARD_DATA"] = str(data)
    os.environ["SEO_DASHBOARD_DB"] = str(data / "t.db")
    os.environ["SEO_DASHBOARD_SCHEDULER"] = "0"
    import importlib

    from seo_dashboard import db
    importlib.reload(db)
    from seo_dashboard import app as app_mod
    importlib.reload(app_mod)
    from seo_dashboard import audit
    audit.FIRST_LOOK_DELAY = 0
    from fastapi.testclient import TestClient
    with TestClient(app_mod.app) as c:
        yield c, port
    srv.shutdown()


def finish(client, site_id, audit_id):
    for _ in range(120):
        st = client.get(f"/api/audits/{audit_id}").json()
        if st["status"] != "running":
            return st
        time.sleep(0.25)
    raise AssertionError("audit did not finish")


@pytest.fixture(scope="module")
def first_look(app_client):
    import fixture_server
    client, port = app_client
    fixture_server.PAGES["/"] = fixture_server.PAGES["/"].replace("</main>", '<a href="/private/secret">Members</a></main>')
    fixture_server.PAGES["/private/secret"] = "<html><body>secret</body></html>"
    fixture_server.HITS.clear()
    r = client.post("/api/first-look", json={"url": f"http://127.0.0.1:{port}/", "max_pages": 30}).json()
    st = finish(client, r["site_id"], r["audit_id"])
    assert st["status"] == "done", st
    return {"sid": r["site_id"], "aid": r["audit_id"], "data": client.get(f"/api/audits/{r['audit_id']}/result").json(), "port": port}


def test_first_look_stays_out_of_clients(app_client, first_look):
    client, _ = app_client
    assert client.get("/api/clients").json() == []
    rows = client.get("/api/first-look").json()
    assert [r["id"] for r in rows] == [first_look["sid"]] and rows[0]["status"] == "done"
    assert client.get(f"/api/sites/{first_look['sid']}").json()["first_look"] is True


def test_first_look_never_fetches_disallowed_urls(first_look):
    import fixture_server
    assert not any(p.startswith("/private") for p in fixture_server.HITS)
    skipped = [p for p in first_look["data"]["pages"] if p["url"].endswith("/private/secret")]
    assert skipped and skipped[0]["status"] is None
    assert first_look["data"]["technical"]["status_counts"].get("skipped") == 1


def test_first_look_uses_crawl_data_only(app_client, first_look, monkeypatch):
    client, _ = app_client
    data = first_look["data"]
    assert not {"Performance", "Tracking & CRO"} & set(data["scores"]["categories"])
    assert not [i for i in data["issues"] if i["category"] in ("Tracking", "Conversion")]
    assert data["redirects"]["summary"]["used_search_console"] is False
    labels = {i["label"] for g in data["first_look"]["groups"] for i in g["items"]}
    assert {"Title tag", "Canonical tag", "XML sitemap", "Structured data"} <= labels
    assert client.post(f"/api/sites/{first_look['sid']}/sync").status_code == 400


def test_first_look_score_is_not_inflated_by_unmeasured_areas():
    from seo_dashboard.analyzers import priorities
    bad = [{"category": "Status codes", "severity": "critical", "count": 5, "urls": ["u"] * 5}] * 12
    full = priorities.scores(bad, 5)["overall"]
    partial = priorities.scores(bad, 5, exclude=("Performance", "Tracking & CRO"))["overall"]
    assert partial < full


def test_adding_a_site_twice_reuses_it(app_client, first_look):
    client, port = app_client
    r = client.post("/api/first-look", json={"url": f"http://127.0.0.1:{port}/"}).json()
    assert r["site_id"] == first_look["sid"]
    finish(client, r["site_id"], r["audit_id"])
    assert len(client.get("/api/first-look").json()) == 1


def test_first_look_rejects_private_addresses(app_client):
    client, _ = app_client
    assert client.post("/api/first-look", json={"url": "http://169.254.169.254/"}).status_code == 400


def test_exports_include_the_plan(app_client, first_look):
    import io
    client, _ = app_client
    wb = openpyxl.load_workbook(io.BytesIO(client.get(f"/api/audits/{first_look['aid']}/export.xlsx").content))
    assert {"Redirect Plan", "Canonical Plan", "Cannibalization Decisions", "Link Updates", "Keyword Stuffing"} <= set(wb.sheetnames)
    assert client.get(f"/api/audits/{first_look['aid']}/report.html").status_code == 200


def test_site_that_disallows_everything_reports_it_and_fetches_nothing(monkeypatch, tmp_path):
    import fixture_server
    from seo_dashboard import crawler
    srv, port = fixture_server.serve()
    monkeypatch.setenv("CLAUDE_SEO_LOCAL_TARGETS", f"127.0.0.1:{port}")
    monkeypatch.setitem(fixture_server.PAGES, "/robots.txt", "User-agent: *\nDisallow: /\n")
    try:
        with pytest.raises(RuntimeError, match="does not allow crawling"):
            crawler.crawl(f"http://127.0.0.1:{port}/", max_pages=5, respect_robots=True, check_external=0)
    finally:
        srv.shutdown()


def test_old_database_is_upgraded_and_keeps_its_clients(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE clients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, company TEXT, email TEXT, industry TEXT, notes TEXT, photo TEXT, created_at TEXT NOT NULL)")
    con.execute("INSERT INTO clients(name, created_at) VALUES('Aquaprocon', '2026-11-02')")
    con.commit()
    con.close()
    from seo_dashboard import db
    monkeypatch.setattr(db, "DB_PATH", str(path))
    monkeypatch.setattr(db, "UPLOAD_DIR", str(tmp_path / "up"))
    db.init_db()
    db.init_db()
    assert db.rows("SELECT name, kind FROM clients") == [{"name": "Aquaprocon", "kind": "client"}]
