"""Every row of advice must be about that row.

The cases here come from a real site: a whole site served on www and non-www, a
production site with canonicals pointing at a development host, a dead cookies
page, project cards mistaken for keyword anchors, a template heading counted as a
question on every page, and one phone link listed once per page.
"""

import os
import sys
from collections import Counter
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

pytest.importorskip("fastapi")

from seo_dashboard.analyzers import conversion, geo, keywords, links, redirects  # noqa: E402
from test_redirects import O, PRICE, ROOF, STORY, by_from, dead, dead_tech, page, run  # noqa: E402


def twin_site():
    """The same pages on two hosts, with canonicals naming the non-www one."""
    pages = []
    for n, text in (("a", ROOF), ("b", PRICE), ("c", STORY)):
        apex, www = f"https://acme.test/{n}/", f"https://www.acme.test/{n}/"
        pages.append({**page(f"/{n}/", text, n), "url": apex, "final_url": apex, "canonical": apex})
        pages.append({**page(f"/{n}/", text, n), "url": www, "final_url": www, "canonical": apex})
    return pages


def crawl_of(pages, origin="https://www.acme.test"):
    return SimpleNamespace(pages={p["url"]: p for p in pages}, origin=origin, link_status={}, sitemaps={"urls": []}, robots={}, llms_txt={})


def analyze(pages, **kw):
    return redirects.analyze(crawl_of(pages), {}, {"redirect_suggestions": [], "broken_links": [], "links_to_redirects": []},
                             {"near_duplicates": [], "cannibalization": []}, [], **kw)


# ---------------- whole site on two hosts ----------------
def test_site_on_two_hosts_gets_one_host_redirect():
    out = analyze(twin_site())
    assert [r["action"] for r in out["redirects"]] == ["Redirect whole host"]
    row = out["redirects"][0]
    assert row["to"] == "https://acme.test/*" and "www.acme.test" in row["reason"] and "3 of 3" in row["reason"]
    assert out["summary"]["host_copies"] == 1


def test_host_redirect_follows_the_canonicals_not_the_crawl_start():
    """The crawl started on www, but the pages say non-www is the real one."""
    assert analyze(twin_site())["redirects"][0]["host_move"] == ["www.acme.test", "acme.test"]


def test_host_redirect_becomes_server_rules():
    rules = analyze(twin_site())["rules"]
    assert "RewriteCond %{HTTP_HOST} ^www\\.acme\\.test$ [NC]" in rules["apache"]
    assert "RewriteRule ^(.*)$ https://acme.test/$1 [R=301,L]" in rules["apache"]
    assert "server { server_name www.acme.test; return 301 https://acme.test$request_uri; }" in rules["nginx"]


def test_duplicate_host_pages_are_not_listed_one_by_one():
    pages = twin_site()
    for p in pages:
        p["canonical"] = "https://rnservis.krejtadev.cz" + p["url"].split(".test", 1)[1] if p["url"].endswith("/c/") else p["canonical"]
    out = analyze(pages)
    assert [c["url"] for c in out["canonicals"]] in (["https://acme.test/c/"], ["https://www.acme.test/c/"])


def test_one_host_only_gets_no_host_redirect():
    assert not analyze([page("/a/", ROOF, "A"), page("/b/", PRICE, "B")])["redirects"]


# ---------------- canonicals ----------------
def test_development_host_is_named_as_the_problem():
    declared = "https://rnservis.krejtadev.cz/reference/coop/"
    row = analyze([page("/reference/coop/", ROOF, "Coop", canonical=declared, inlink_count=7, in_sitemap=True), page("/other/", PRICE, "O")])["canonicals"][0]
    assert row["problem"] == "Canonical points to a development site" and row["priority"] == "high" and row["confidence"] == "high"
    assert row["target"] == O + "/reference/coop/"
    assert "rnservis.krejtadev.cz/reference/coop/" in row["reason"] and "7 internal links" in row["reason"] and "sitemap" in row["reason"]


@pytest.mark.parametrize("host", ["staging.acme.test", "dev.acme.test", "test2.acme.test", "acme-site.krejtadev.cz"])
def test_development_hosts_are_recognized(host):
    assert redirects._is_dev_host(host)


@pytest.mark.parametrize("host", ["partner.example.com", "developer.mozilla.org", "contest.example.com"])
def test_ordinary_hosts_are_not_called_development(host):
    assert not redirects._is_dev_host(host)


def test_canonical_rows_for_two_pages_differ():
    out = analyze([page("/a/", ROOF, "A", canonical="https://partner.test/x/"), page("/b/", PRICE, "B", canonical="https://partner.test/y/")])
    assert len({c["reason"] for c in out["canonicals"]}) == 2


# ---------------- dead pages ----------------
def test_dead_legal_page_is_restored_not_removed():
    pages = [page("/", STORY, "Home"), dead("/cookies/")]
    out = run(pages, tech=dead_tech("/cookies/", [O + "/"], "cookies"))
    row = by_from(out)[O + "/cookies/"]
    assert row["action"] == "Restore this page" and row["method"] == "restore" and row["to"] is None
    assert "cookies" not in out["rules"]["apache"] and out["summary"]["restore"] == 1
    assert "restore the page" in out["link_updates"][0]["why"]


def test_legal_link_in_czech_is_recognized():
    out = run([page("/", STORY, "Home"), dead("/zasady/")], tech=dead_tech("/zasady/", [O + "/"], "zpracováním osobních údajů."))
    assert by_from(out)[O + "/zasady/"]["method"] == "restore"


def test_dead_pages_get_their_own_explanation():
    pages = [page("/", STORY, "Home"), page("/services/roof/", ROOF, "Roof"), dead("/summer-sale"), dead("/winter-offer")]
    tech = {"redirect_suggestions": [{"from": O + "/summer-sale", "status": 404}, {"from": O + "/winter-offer", "status": 404}], "broken_links": []}
    rows = run(pages, tech=tech)["redirects"]
    assert len({r["reason"] for r in rows}) == 2 and "summer" in rows[0]["reason"] + rows[1]["reason"]


def test_link_in_the_template_is_described_as_one_edit():
    pages = [page(f"/p{i}/", STORY + f" extra{i}", f"P{i}") for i in range(4)]
    links_to = [{"source": p["url"], "target": O + "/kontakt", "final": O + "/kontakt/", "anchor": "Kontakt"} for p in pages]
    row = run(pages, tech={"links_to_redirects": links_to})["link_updates"][0]
    assert "site template" in row["why"] and "4 pages" in row["why"] and "/kontakt/" in row["why"]


def test_link_on_one_page_is_not_called_template():
    pages = [page(f"/p{i}/", STORY + f" extra{i}", f"P{i}") for i in range(4)]
    row = run(pages, tech={"links_to_redirects": [{"source": pages[0]["url"], "target": O + "/x", "final": O + "/y/", "anchor": "X"}]})["link_updates"][0]
    assert "site template" not in row["why"] and "1 page" in row["why"]


# ---------------- keyword stuffing ----------------
def anchor_page(path, text):
    return page(path, STORY, path, internal_links=[{"href": O + "/p/", "text": text, "nav": False}] * 6)


def test_project_card_anchor_is_not_stuffing():
    card = "coop plzen detail projektu"
    crawl = SimpleNamespace(pages={p["url"]: p for p in [anchor_page("/list/", card)]})
    assert not redirects.keyword_stuffing(crawl, {O + "/p/": [("coop plzen", 1)]})


def test_exact_keyword_anchor_is_stuffing_and_names_alternatives():
    crawl = SimpleNamespace(pages={p["url"]: p for p in [anchor_page("/list/", "roof repair")]})
    rows = redirects.keyword_stuffing(crawl, {O + "/p/": [("roof repair", 1), ("leak fixing", 1), ("tile work", 1)]})
    assert rows[0]["where"] == "Internal anchors" and "leak fixing" in rows[0]["recommendation"] and "6 of the 6" in rows[0]["recommendation"]


def test_brand_in_the_title_is_not_keyword_repetition():
    p = page("/a/", ROOF, "Retail technology and servis | RN Servis")
    assert not redirects.keyword_stuffing(SimpleNamespace(pages={p["url"]: p}), {p["url"]: [("servis", 1)]})


def test_real_title_repetition_is_still_flagged():
    p = page("/a/", ROOF, "Roof repair: cheap roof repair | Acme")
    rows = redirects.keyword_stuffing(SimpleNamespace(pages={p["url"]: p}), {p["url"]: [("roof repair", 1)]})
    assert [r["where"] for r in rows if r["where"] == "Title"] == ["Title"]


def test_one_linking_page_reads_correctly():
    out = run([page("/", STORY, "Home"), dead("/summer-sale")], tech=dead_tech("/summer-sale", [O + "/"], "Offer"))
    assert "1 page still links here" in out["redirects"][0]["reason"]


def test_body_stuffing_advice_uses_the_page_numbers():
    stuffed = page("/a/", " ".join(["roof repair is what we sell every day"] * 40), "A")
    crawl = SimpleNamespace(pages={stuffed["url"]: stuffed})
    row = redirects.keyword_stuffing(crawl, {stuffed["url"]: [("roof repair", 1), ("leak fixing", 1)]})[0]
    assert "40 times in 320 words" in row["recommendation"] and "leak fixing" in row["recommendation"]


# ---------------- AI answer fixes ----------------
def geo_page(path, h1, **kw):
    return {"url": O + path, "status": 200, "word_count": 300, "text": "plain words here", "h1": [h1], "title": h1, "headings": [{"level": 2, "text": f"Our {h1} process"}],
            "sections": [], "first_paragraph": "", "external_links": [], "dates": {}, "schema": [], "question_headings": [], "meta_robots": "", "x_robots_tag": "", **kw}


def test_fixes_name_the_page_they_are_for():
    _, _, a = geo.page_score(geo_page("/roofs/", "Roof repair"))
    _, _, b = geo.page_score(geo_page("/gutters/", "Gutter cleaning"))
    assert not set(a) & set(b)
    assert "Our Roof repair process" in a[0]


def test_author_advice_depends_on_the_page_type():
    _, _, article = geo.page_score(geo_page("/blog/guide/", "Roof guide"))
    _, _, service = geo.page_score(geo_page("/services/roofs/", "Roof repair"))
    assert any("byline" in f for f in article) and not any("byline" in f for f in service)


def test_template_question_is_not_a_page_strength():
    q = "Ready to transform your space?"
    pages = [geo_page(f"/p{i}/", f"Page {i}", question_headings=[q]) for i in range(5)]
    out = geo.analyze(SimpleNamespace(pages={p["url"]: p for p in pages}, origin=O, robots={}, llms_txt={}))
    assert all(q not in str(p["strengths"]) and q not in p["question_headings"] for p in out["pages"])


def test_template_heading_is_never_suggested_for_rewording():
    pages = [geo_page(f"/p{i}/", f"Page {i}", headings=[{"level": 2, "text": "NAVIGACE"}, {"level": 2, "text": f"Own section {i}"}]) for i in range(5)]
    out = geo.analyze(SimpleNamespace(pages={p["url"]: p for p in pages}, origin=O, robots={}, llms_txt={}))
    assert all("NAVIGACE" not in " ".join(p["fixes"]) and "Own section" in p["fixes"][0] for p in out["pages"])


def test_brand_is_left_out_of_the_page_topic():
    p = geo_page("/a/", "Roof repair")
    p["h1"] = []
    p["title"] = "Bezobslužná prodejna Liberec | RN Servis"
    fixes = geo.page_score(p)[2]
    assert any("'Bezobslužná prodejna Liberec'" in f for f in fixes) and not any("RN Servis" in f for f in fixes)


def test_question_built_on_the_brand_is_dropped():
    research = {"questions": ["why klíč rn servis", "how long does a refit take"], "keywords": []}
    crawl = SimpleNamespace(pages={}, origin="https://rnservis.cz", robots={}, llms_txt={})
    q = geo.analyze(crawl, research)["brief"]["question_opportunities"]
    assert [x["question"] for x in q] == ["how long does a refit take"]


def test_real_page_question_still_counts():
    pages = [geo_page(f"/p{i}/", f"Page {i}") for i in range(4)] + [geo_page("/faq/", "FAQ", question_headings=["How long does it take?"])]
    out = geo.analyze(SimpleNamespace(pages={p["url"]: p for p in pages}, origin=O, robots={}, llms_txt={}))
    assert "How long does it take?" in next(p for p in out["pages"] if p["url"].endswith("/faq/"))["question_headings"]


def test_question_opportunities_name_the_question_and_page():
    research = {"questions": ["how much is a roof", "why do roofs leak"],
                "keywords": [{"keyword": "how much is a roof", "target_url": O + "/roofs/"}, {"keyword": "why do roofs leak", "target_url": None, "suggested_slug": "/why-roofs-leak/"}]}
    q = geo.analyze(SimpleNamespace(pages={}, origin=O, robots={}, llms_txt={}), research)["brief"]["question_opportunities"]
    assert "how much is a roof" in q[0]["action"] and "/roofs/" in q[0]["action"] and "/why-roofs-leak/" in q[1]["action"]


# ---------------- conversion plan ----------------
def conv_page(path, **kw):
    return {"url": O + path, "status": 200, "word_count": 300, "h1": ["H"], "title": "T", "forms": [], "ctas": [], "tel_links": 0, "mailto_links": 0, "tracking": {}, **kw}


def test_phone_link_in_the_template_is_one_row():
    pages = [conv_page(f"/p{i}/", tel_links=1 + i % 2) for i in range(10)]
    ev = conversion.analyze(SimpleNamespace(pages={p["url"]: p for p in pages}, origin=O))["events"]
    assert len(ev) == 1 and ev[0]["pages"] == 10 and "10 of 10 pages" in ev[0]["why"]


def test_same_page_on_two_hosts_is_planned_once():
    a, b = conv_page("/kontakt/", tel_links=1), conv_page("/kontakt/", tel_links=1)
    b["url"] = "https://www.acme.test/kontakt/"
    pages = [a, b] + [conv_page(f"/p{i}/") for i in range(8)]
    ev = conversion.analyze(SimpleNamespace(pages={p["url"]: p for p in pages}, origin=O))["events"]
    assert len(ev) == 1 and "/kontakt/" in ev[0]["why"]


def test_phone_link_on_few_pages_stays_per_page():
    pages = [conv_page("/kontakt/", tel_links=2), conv_page("/o-nas/", tel_links=1)] + [conv_page(f"/p{i}/") for i in range(8)]
    ev = conversion.analyze(SimpleNamespace(pages={p["url"]: p for p in pages}, origin=O))["events"]
    assert len(ev) == 2 and len({e["why"] for e in ev}) == 2


# ---------------- smaller columns ----------------
def test_meta_reason_names_the_keyword():
    p = page("/a/", ROOF, "Roof repair and fixing services near you today", meta_description="A long enough description about something entirely different from the page topic here.")
    rows = keywords.meta_suggestions(SimpleNamespace(pages={p["url"]: p}, origin=O), {p["url"]: [("gutter", 1)]})
    assert any("'gutter' is missing from the description" in r for r in rows[0]["reasons"])


def test_link_suggestion_reason_is_specific():
    a = page("/a/", "we fix roof tiles and other things every day of the week", "A", inlink_count=1)
    b = page("/b/", STORY, "B", inlink_count=9)
    rows = links.link_suggestions(SimpleNamespace(pages={a["url"]: a, b["url"]: b}), {b["url"]: [("roof tiles", 1)], a["url"]: []})
    assert "'roof tiles'" in rows[0]["reason"]


# ---------------- the rule itself ----------------
def repeated(rows, field):
    values = Counter()
    for r in rows:
        v = r.get(field)
        for text in (v if isinstance(v, list) else [v]):
            if isinstance(text, str):
                values[text] += 1
    return [t for t, n in values.items() if n > 1]


def test_full_audit_never_repeats_advice(client, full_audit):
    data = full_audit
    plan, conv, brief = data["redirects"], data["conversion"], data["geo"]["brief"]
    columns = {
        "redirect reason": (plan["redirects"], "reason"), "canonical reason": (plan["canonicals"], "reason"), "cannibalization why": (plan["decisions"], "why"),
        "link update why": (plan["link_updates"], "why"), "stuffing fix": (plan["stuffing"], "recommendation"), "geo fixes": (data["geo"]["pages"], "fixes"),
        "question action": (brief["question_opportunities"], "action"), "event why": (conv["events"], "why"), "lead gap fix": (conv["lead_gaps"], "recommendation"),
        "opportunity fix": (conv["opportunities"], "recommendation"), "link suggestion reason": (data["links"]["suggestions"], "reason"),
    }
    problems = {name: repeated(rows, field) for name, (rows, field) in columns.items() if repeated(rows, field)}
    assert not problems


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from fixture_server import serve
    srv, port = serve()
    os.environ["CLAUDE_SEO_LOCAL_TARGETS"] = f"127.0.0.1:{port}"
    data = tmp_path_factory.mktemp("rows")
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
        c.port = port
        yield c
    srv.shutdown()


@pytest.fixture(scope="module")
def full_audit(client):
    import time

    from seo_dashboard import audit
    audit.FIRST_LOOK_DELAY = 0
    r = client.post("/api/first-look", json={"url": f"http://127.0.0.1:{client.port}/", "max_pages": 30}).json()
    for _ in range(120):
        st = client.get(f"/api/audits/{r['audit_id']}").json()
        if st["status"] != "running":
            break
        time.sleep(0.25)
    assert st["status"] == "done", st
    return client.get(f"/api/audits/{r['audit_id']}/result").json()
