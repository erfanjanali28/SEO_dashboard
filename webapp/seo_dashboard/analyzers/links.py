"""Internal linking, orphan pages, link suggestions and URL structure analysis."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from urllib.parse import urlparse

from . import html_pages, indexable, issue


def _snippet(text: str, phrase: str, width: int = 90) -> str | None:
    i = text.lower().find(phrase)
    if i < 0:
        return None
    a, b = max(0, i - width), min(len(text), i + len(phrase) + width)
    return ("…" if a else "") + text[a:b] + ("…" if b < len(text) else "")


def link_suggestions(crawl, kw_map: dict, max_per_target: int = 8, max_total: int = 1500) -> list[dict]:
    """Contextual internal link opportunities: source page mentions the target's
    keyword in body text but does not link to the target yet."""
    pages = [p for p in html_pages(crawl.pages) if indexable(p)]
    links_from = {p["url"]: {l["href"] for l in p.get("internal_links", [])} for p in pages}
    out = []
    # Weakly linked targets first: they benefit most.
    targets = sorted(pages, key=lambda p: p.get("inlink_count", 0))
    for target in targets:
        kws = [k for k, _ in kw_map.get(target["url"], [])[:4] if " " in k or len(k) > 6]
        if not kws:
            continue
        found = 0
        for src in pages:
            if src["url"] == target["url"] or target["url"] in links_from[src["url"]]:
                continue
            text = src.get("text", "")
            for kw in kws:
                snip = _snippet(text, kw)
                if snip:
                    rel = len(set(k for k, _ in kw_map.get(src["url"], [])[:8]) & set(k for k, _ in kw_map.get(target["url"], [])[:8]))
                    out.append({
                        "source_url": src["url"], "source_title": src.get("title") or "",
                        "target_url": target["url"], "target_title": target.get("title") or "",
                        "anchor_text": kw, "context": snip,
                        "target_inlinks": target.get("inlink_count", 0),
                        "priority": "high" if target.get("inlink_count", 0) <= 2 else "medium" if rel else "low",
                        "reason": "orphan/weakly linked target" if target.get("inlink_count", 0) <= 2 else "topical relevance",
                    })
                    found += 1
                    break
            if found >= max_per_target:
                break
        if len(out) >= max_total:
            break
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda x: (order[x["priority"]], x["target_inlinks"]))


def url_tree(crawl) -> dict:
    """Nested folder tree of discovered URLs for the structure graph."""
    root = {"name": urlparse(crawl.origin).netloc, "path": "/", "children": {}, "count": 0}
    all_urls = set(crawl.pages) | set(crawl.sitemaps.get("urls", []))
    for u in sorted(all_urls):
        p = urlparse(u)
        if (p.hostname or "").removeprefix("www.") != (urlparse(crawl.origin).hostname or "").removeprefix("www."):
            continue
        parts = [x for x in p.path.split("/") if x]
        node = root
        node["count"] += 1
        path = ""
        for part in parts:
            path += "/" + part
            node = node["children"].setdefault(part, {"name": part, "path": path, "children": {}, "count": 0})
            node["count"] += 1
        page = crawl.pages.get(u)
        node["url"] = u
        node["status"] = page.get("status") if page else None
        node["inlinks"] = page.get("inlink_count", 0) if page else 0
        node["title"] = (page or {}).get("title")

    def finalize(n):
        n["children"] = [finalize(c) for c in sorted(n["children"].values(), key=lambda c: -c["count"])]
        return n
    return finalize(root)


def analyze(crawl, kw_map: dict) -> dict:
    ok = html_pages(crawl.pages)
    idx = [p for p in ok if indexable(p)]
    issues = []
    sm_urls = set(crawl.sitemaps.get("urls", []))

    orphans = [p for p in idx if p.get("inlink_count", 0) == 0 and urlparse(p["url"]).path not in ("", "/")]
    sm_only = [u for u in sm_urls if u not in crawl.pages]
    if orphans:
        issues.append(issue("orphan_pages", "Internal linking", "high", "Orphan pages",
                            f"{len(orphans)} indexable pages get no internal links (found only through the sitemap or a redirect). Google treats them as unimportant.",
                            "Link to every orphan from relevant hub, category or related-content sections, using the suggestions in the Internal Links table.",
                            [p["url"] for p in orphans], impact=7, effort=2))
    weak = [p for p in idx if 0 < p.get("inlink_count", 0) <= 2 and urlparse(p["url"]).path not in ("", "/")]
    if weak:
        issues.append(issue("weak_internal_links", "Internal linking", "medium", "Pages with only 1–2 internal links",
                            "Pages with few inlinks receive little PageRank and are crawled less often.",
                            "Add 3–10 contextual links from related pages with descriptive anchors.", [p["url"] for p in weak], impact=5, effort=2))
    deep = [p for p in idx if (p.get("depth") or 0) > 3]
    if deep:
        issues.append(issue("deep_pages", "Internal linking", "medium", "Pages more than 3 clicks from home",
                            "Deep pages are crawled less and look less important.",
                            "Flatten the architecture: link these pages from category hubs, breadcrumbs or the home page.",
                            [p["url"] for p in deep], impact=4, effort=3, details=[{"url": p["url"], "depth": p["depth"]} for p in deep]))
    nofollow_int = [p["url"] for p in ok if any(l["nofollow"] for l in p.get("internal_links", []))]
    if nofollow_int:
        issues.append(issue("internal_nofollow", "Internal linking", "low", "Nofollow on internal links",
                            "rel=nofollow on internal links wastes link equity.", "Remove nofollow from internal links (keep it for login or untrusted UGC links).",
                            nofollow_int, impact=2, effort=1))
    generic_anchor = defaultdict(list)
    for p in ok:
        for l in p.get("internal_links", []):
            if re.fullmatch(r"(click here|here|read more|more|learn more|this|link|details|view more)", (l["text"] or "").strip().lower()):
                generic_anchor[p["url"]].append(l["href"])
    if generic_anchor:
        issues.append(issue("generic_anchors", "Internal linking", "low", "Generic anchor text",
                            "Anchors like 'click here' or 'read more' tell crawlers nothing about the target.",
                            "Use descriptive, keyword-rich anchors (for example 'emergency plumbing pricing').", list(generic_anchor), impact=3, effort=2))
    too_many = [p["url"] for p in ok if len(p.get("internal_links", [])) > 300]
    if too_many:
        issues.append(issue("too_many_links", "Internal linking", "low", "More than 300 internal links on a page",
                            "Very large link counts dilute equity and suggest mega-menu bloat.", "Trim navigation and footer links to the important hubs.", too_many, impact=2, effort=3))

    # URL structure
    url_problems = []
    for u in crawl.pages:
        path = urlparse(u).path
        probs = []
        if len(u) > 115:
            probs.append("longer than 115 characters")
        if re.search(r"[A-Z]", path):
            probs.append("uppercase characters")
        if "_" in path:
            probs.append("underscores (use hyphens)")
        if path.count("/") > 5:
            probs.append("folder depth above 4")
        if urlparse(u).query:
            probs.append("query parameters")
        if re.search(r"[^\x00-\x7F]", path):
            probs.append("non-ASCII characters")
        if re.search(r"\.(php|aspx?|jsp|html?)$", path):
            probs.append("file extension")
        if re.search(r"/\d{4}/\d{2}/", path):
            probs.append("date in URL (ages content)")
        if re.search(r"--|\s|%20", path):
            probs.append("spaces or double hyphens")
        if probs:
            url_problems.append({"url": u, "problems": probs})
    if url_problems:
        issues.append(issue("url_structure", "URL structure", "low", "URL structure problems",
                            f"{len(url_problems)} URLs are not short, lowercase, hyphenated and descriptive.",
                            "For new pages, use short, lowercase, hyphenated, keyword-descriptive slugs grouped in logical folders. Change existing URLs only with 301s and when the benefit is clear.",
                            [x["url"] for x in url_problems], impact=2, effort=4, details=url_problems))

    folders = Counter()
    for u in crawl.pages:
        parts = [x for x in urlparse(u).path.split("/") if x]
        folders["/" + parts[0] + "/" if parts else "/"] += 1
    depth_dist = Counter(str(p.get("depth")) if p.get("depth") is not None else "sitemap only" for p in ok)
    inlink_top = sorted(({"url": p["url"], "inlinks": p.get("inlink_count", 0)} for p in idx), key=lambda x: -x["inlinks"])
    suggestions = link_suggestions(crawl, kw_map)

    # Graph for the visualization: nodes = pages, edges = body + nav links (capped)
    node_ids = {p["url"]: i for i, p in enumerate(ok[:300])}
    edges = Counter()
    for p in ok[:300]:
        for l in p.get("internal_links", []):
            if l["href"] in node_ids and l["href"] != p["url"]:
                edges[(node_ids[p["url"]], node_ids[l["href"]])] += 1
    graph = {
        "nodes": [{"id": i, "url": u, "inlinks": crawl.pages[u].get("inlink_count", 0),
                   "depth": crawl.pages[u].get("depth"), "folder": (urlparse(u).path.strip("/").split("/") or [""])[0] or "home"}
                  for u, i in node_ids.items()],
        "links": [{"source": a, "target": b} for (a, b) in list(edges)[:3000]],
    }
    stats = {
        "orphans": [p["url"] for p in orphans], "sitemap_only": sm_only[:300],
        "depth_distribution": dict(depth_dist), "folders": dict(folders.most_common(30)),
        "top_linked": inlink_top[:25], "least_linked": list(reversed(inlink_top[-25:])),
        "url_problems": url_problems, "avg_inlinks": round(sum(x["inlinks"] for x in inlink_top) / len(inlink_top), 1) if inlink_top else 0,
    }
    return {"issues": issues, "stats": stats, "suggestions": suggestions, "tree": url_tree(crawl), "graph": graph}
