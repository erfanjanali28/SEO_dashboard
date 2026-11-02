"""Content quality analyzer: thin, duplicate, outdated, generic content,
content structure, keyword cannibalization and content gaps."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

from . import html_pages, indexable, issue

UTILITY = re.compile(r"/(contact|login|register|cart|checkout|account|privacy|terms|cookie|sitemap|search|thank|404|tag|author|page/\d+)", re.I)
GENERIC_PHRASES = [
    "in today's fast-paced world", "in today's digital age", "look no further", "unlock the power",
    "delve into", "game-changer", "a testament to", "navigate the complexities", "it's important to note",
    "in conclusion", "elevate your", "seamless experience", "cutting-edge", "one-stop shop",
    "world-class", "we are committed to", "best-in-class", "tailored solutions", "lorem ipsum",
    "harness the power", "ever-evolving landscape", "embark on a journey", "rest assured",
]


def _shingles(text: str, k: int = 5) -> set:
    w = re.findall(r"\w+", text.lower())[:2500]
    return {" ".join(w[i:i + k]) for i in range(0, max(len(w) - k, 0), 2)}


def _parse_date(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")[:25])
    except ValueError:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s))
        return datetime(int(m[1]), int(m[2]), int(m[3])) if m else None


def analyze(crawl, kw_map: dict, research: dict | None = None) -> dict:
    ok = [p for p in html_pages(crawl.pages) if indexable(p)]
    issues = []
    now = datetime.now(timezone.utc)
    lastmod = crawl.sitemaps.get("lastmod", {})

    content_pages = [p for p in ok if not UTILITY.search(urlparse(p["url"]).path)]
    thin = [p for p in content_pages if p.get("word_count", 0) < 300 and urlparse(p["url"]).path not in ("", "/")]
    if thin:
        issues.append(issue("thin_content", "Content", "high" if len(thin) > len(content_pages) / 3 else "medium",
                            "Thin content (under 300 words)",
                            f"{len(thin)} pages have little main content. Thin pages rarely rank and can drag down site-wide quality signals.",
                            "Expand them with original detail (examples, data, FAQs, media), merge them into a stronger page with a 301, or noindex them if they are utility pages.",
                            [p["url"] for p in thin], impact=6, effort=5,
                            details=[{"url": p["url"], "words": p.get("word_count", 0)} for p in thin]))

    # Near-duplicate detection (shingle Jaccard) among the first 250 content pages
    sh = {p["url"]: _shingles(p.get("text", "")) for p in content_pages[:250] if p.get("word_count", 0) > 80}
    urls = list(sh)
    near = []
    for i in range(len(urls)):
        for j in range(i + 1, len(urls)):
            a, b = sh[urls[i]], sh[urls[j]]
            if not a or not b:
                continue
            jac = len(a & b) / len(a | b)
            if jac >= 0.6:
                near.append({"url_a": urls[i], "url_b": urls[j], "similarity": round(jac, 2)})
    if near:
        issues.append(issue("near_duplicate", "Content", "high", "Near-duplicate content",
                            f"{len(near)} page pairs share 60% or more of their text.",
                            "Differentiate each page (unique intro, local or product specifics, distinct FAQs) or consolidate them with a 301 or canonical.",
                            [n["url_a"] for n in near] + [n["url_b"] for n in near], impact=6, effort=5, details=near))

    outdated = []
    for p in content_pages:
        d = _parse_date(p.get("dates", {}).get("modified")) or _parse_date(lastmod.get(p["url"])) or _parse_date(p.get("dates", {}).get("published"))
        years = re.findall(r"\b(20[12]\d)\b", (p.get("title") or "") + " " + " ".join(p.get("h1", [])))
        stale_year = years and int(max(years)) < now.year - 1
        if d:
            d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            age = (now - d).days
            if age > 540 or stale_year:
                outdated.append({"url": p["url"], "last_updated": d.date().isoformat(), "age_days": age})
        elif stale_year:
            outdated.append({"url": p["url"], "last_updated": None, "age_days": None, "year_in_title": max(years)})
    if outdated:
        issues.append(issue("outdated_content", "Content", "medium", "Outdated content",
                            "These pages have not been updated in over 18 months, or their title names a past year.",
                            "Refresh statistics, examples, screenshots and the year; add 'Last updated' plus dateModified schema; re-submit in Search Console.",
                            [o["url"] for o in outdated], impact=5, effort=4, details=outdated))

    generic = []
    for p in content_pages:
        t = p.get("text", "").lower()
        hits = [g for g in GENERIC_PHRASES if g in t]
        if len(hits) >= 2 or "lorem ipsum" in hits:
            generic.append({"url": p["url"], "phrases": hits})
    if generic:
        issues.append(issue("generic_content", "Content", "medium", "Generic or boilerplate copy",
                            "Pages lean on stock phrases common in templated or unedited AI copy. They lack information gain and E-E-A-T.",
                            "Rewrite with first-hand experience: specific numbers, named examples, original photos, expert quotes and clear author attribution.",
                            [g["url"] for g in generic], impact=5, effort=5, details=generic))

    no_author = [p["url"] for p in content_pages if re.search(r"/(blog|news|article|guide|post)", p["url"]) and not p.get("author_signals")]
    if no_author:
        issues.append(issue("no_author", "Content", "medium", "Articles without author attribution",
                            "Articles show no author, which weakens Experience and Expertise signals.",
                            "Add a visible author byline linking to a bio page with credentials, plus Person schema.", no_author, impact=4, effort=2))

    # Content structure
    structure = []
    for p in content_pages:
        problems = []
        h2 = [h for h in p.get("headings", []) if h["level"] == 2]
        if p.get("word_count", 0) > 600 and not h2:
            problems.append("no H2 subheadings")
        if p.get("avg_paragraph_words", 0) > 120:
            problems.append(f"long paragraphs (average {p['avg_paragraph_words']} words)")
        if p.get("word_count", 0) > 800 and not p.get("lists") and not p.get("tables"):
            problems.append("no lists or tables")
        if p.get("word_count", 0) > 400 and not p.get("images"):
            problems.append("no images")
        if problems:
            structure.append({"url": p["url"], "problems": problems})
    if structure:
        issues.append(issue("content_structure", "Content structure", "medium", "Weak content structure",
                            "Long text without clear sections is hard to scan and hard for search engines to extract answers from.",
                            "Break the content into descriptive H2/H3 sections, keep paragraphs to 2–4 sentences, and add lists, tables and visuals.",
                            [s["url"] for s in structure], impact=4, effort=3, details=structure))

    # Cannibalization by primary keyword
    by_kw = defaultdict(list)
    for p in ok:
        kws = kw_map.get(p["url"], [])
        if kws and " " in kws[0][0]:
            by_kw[kws[0][0]].append(p["url"])
    cannibal = [{"keyword": k, "pages": v} for k, v in by_kw.items() if len(v) > 1]
    for c in (research or {}).get("gsc_cannibalization", []):
        cannibal.append({"keyword": c["keyword"], "pages": c["pages"], "source": "search console", "impressions": c["impressions"]})
    if cannibal:
        issues.append(issue("cannibalization", "Content", "high", "Keyword cannibalization",
                            f"{len(cannibal)} keywords are targeted by several pages, which then compete with each other.",
                            "Pick one primary page per keyword. Merge or 301 the weaker pages, re-target them to distinct long-tail intents, and point internal anchors at the primary page.",
                            [u for c in cannibal for u in c["pages"]], impact=7, effort=4, details=cannibal))

    gaps = [k for k in (research or {}).get("keywords", []) if k["status"] == "content gap"]
    if gaps:
        top = sorted(gaps, key=lambda r: -r["priority"])[:60]
        issues.append(issue("content_gaps", "Content", "medium", "Content gaps",
                            f"{len(gaps)} relevant keywords have no matching page.",
                            "Plan new pages or sections for the top gaps (see the Keywords tab). Each gap lists a suggested slug and its funnel stage.",
                            [], impact=7, effort=6,
                            details=[{"keyword": g["keyword"], "intent": g["intent"], "suggested_slug": g["suggested_slug"], "priority": g["priority"]} for g in top]))

    word_counts = [p.get("word_count", 0) for p in content_pages]
    stats = {
        "content_pages": len(content_pages),
        "avg_words": round(sum(word_counts) / len(word_counts)) if word_counts else 0,
        "word_buckets": {
            "<300": sum(1 for w in word_counts if w < 300),
            "300-799": sum(1 for w in word_counts if 300 <= w < 800),
            "800-1499": sum(1 for w in word_counts if 800 <= w < 1500),
            "1500+": sum(1 for w in word_counts if w >= 1500),
        },
        "outdated": outdated, "near_duplicates": near, "cannibalization": cannibal,
        "structure": structure,
    }
    return {"issues": issues, "stats": stats}
