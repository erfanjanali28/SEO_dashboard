"""AI Overviews (AIO) and Generative Engine Optimization (GEO) analysis.

Scores each page for answer extraction (direct answers under question
headings, 40–60-word answer blocks, lists and tables, statistics, sources,
freshness, authorship, structured data) and checks site-level prerequisites
(AI crawler access, server-rendered content, entity markup, llms.txt).
Produces a written brief the team can act on.
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

from . import html_pages, indexable, issue
from .content import UTILITY
from .conversion import page_type
from .keywords import _brand
from .technical import suggest_schema_type

BOILERPLATE_SHARE = 0.3      # a question on this share of pages comes from the template


def _plain_heading(p: dict, boilerplate: frozenset) -> str | None:
    """The first H2 or H3 of the page's own content that is not already a question."""
    return next((h["text"] for h in p.get("headings", [])
                 if h["level"] in (2, 3) and "?" not in h["text"] and h["text"] not in boilerplate), None)


def _topic(p: dict) -> str:
    """What the page is about, without the brand part of a title."""
    text = (p.get("h1") or [None])[0] or p.get("title") or "this topic"
    return re.split(r"\s[|–—]\s", text)[0][:70]


def _author_fix(p: dict, topic: str) -> str:
    kind = page_type(p)
    if kind == "blog/article":
        return f"Add a byline to '{topic}' with the writer's credentials, plus Person schema."
    return f"Show who stands behind '{topic}': a named specialist, team or company credentials."


def page_score(p: dict, boilerplate: frozenset = frozenset()) -> tuple[int, list[str], list[str]]:
    """Score one page. ``boilerplate`` holds headings that come from the site template."""
    score, good, fixes = 0, [], []
    sections = p.get("sections", [])
    qh = [q for q in p.get("question_headings", []) if q not in boilerplate]
    topic = _topic(p)
    words = p.get("word_count", 0)
    paragraphs = [s["words"] for s in sections if s["kind"] == "p"]
    answer_blocks = [s for s in sections if s["kind"] == "p" and 25 <= s["words"] <= 80]
    if qh:
        score += 15
        good.append(f"{len(qh)} question heading{'s' if len(qh) != 1 else ''}, such as '{qh[0][:50]}'")
    else:
        plain = _plain_heading(p, boilerplate)
        fixes.append(f"Reword the heading '{plain[:70]}' as a question a customer would ask." if plain
                     else f"Add 2–4 question headings about '{topic}'; the page has none to reword.")
    if answer_blocks:
        score += 20
        good.append(f"{len(answer_blocks)} of {len(paragraphs)} paragraphs are quotable (25–80 words)")
    elif qh:
        fixes.append(f"Under '{qh[0][:70]}', add a direct 40–60 word answer before any detail.")
    elif paragraphs:
        fixes.append(f"Its {len(paragraphs)} paragraph{'s' if len(paragraphs) != 1 else ''} run {min(paragraphs)}–{max(paragraphs)} words, so none is a quotable answer. Add a 40–60 word summary of '{topic}'.")
    else:
        fixes.append(f"There is no paragraph text under the headings. Add a 40–60 word answer about '{topic}'.")
    fp = p.get("first_paragraph", "")
    intro = len(fp.split())
    if 20 <= intro <= 70:
        score += 10
        good.append(f"{intro}-word intro summarizes the topic")
    elif not fp:
        fixes.append(f"No intro paragraph. Open with 1–2 sentences that define '{topic}' and state the key takeaway.")
    elif intro < 20:
        fixes.append(f"The intro is only {intro} words. Expand it to 1–2 sentences defining '{topic}'.")
    else:
        fixes.append(f"The intro runs {intro} words. Cut it below 70 so it can be quoted on its own.")
    if p.get("lists") or p.get("tables"):
        score += 10
        good.append(f"{(p.get('lists') or 0) + (p.get('tables') or 0)} lists or tables")
    else:
        fixes.append(f"{words} words with no list or table. Put the main points about '{topic}' in one.")
    text = p.get("text", "")
    stats = len(re.findall(r"\b\d+(?:\.\d+)?\s?(?:%|percent|million|billion|x\b)", text))
    if stats >= 2:
        score += 10
        good.append(f"{stats} statistics")
    else:
        found = f"Only {stats} figure" if stats else "No figures"
        fixes.append(f"{found} in {words} words. Add sourced numbers about '{topic}', which AI answers can quote.")
    ext = [l for l in p.get("external_links", []) if not l["nav"]]
    if ext:
        score += 5
        good.append(f"{len(ext)} outbound source link{'s' if len(ext) != 1 else ''}")
    else:
        fixes.append(f"No outbound links in the body. Cite 2–3 sources that back up the claims about '{topic}'.")
    if p.get("author_signals"):
        score += 10
        good.append("author attribution")
    else:
        fixes.append(_author_fix(p, topic))
    if p.get("dates", {}).get("modified") or p.get("dates", {}).get("published"):
        score += 5
        good.append("dated content")
    else:
        fixes.append(f"Nothing shows when '{topic}' was last updated. Add a visible date and dateModified in the schema.")
    if p.get("schema"):
        score += 10
        good.append(f"{len(p['schema'])} structured data block{'s' if len(p['schema']) != 1 else ''}")
    else:
        fixes.append(f"'{topic}' has no structured data. Add {suggest_schema_type(p)} JSON-LD.")
    if p.get("word_count", 0) >= 600:
        score += 5
    if not p.get("spa_shell"):
        score += 0
    else:
        score -= 20
        fixes.insert(0, f"Only {words} words are in the initial HTML. Server-render '{topic}', because most AI crawlers do not run JavaScript.")
    return max(0, min(100, score)), good, fixes


def analyze(crawl, research: dict | None = None) -> dict:
    pages = [p for p in html_pages(crawl.pages) if indexable(p) and not UTILITY.search(urlparse(p["url"]).path)]
    seen_on = Counter(t for p in pages for t in {h["text"] for h in p.get("headings", [])} | set(p.get("question_headings", [])))
    boilerplate = frozenset(t for t, n in seen_on.items() if n >= 3 and n >= len(pages) * BOILERPLATE_SHARE)
    scored = []
    for p in pages:
        s, good, fixes = page_score(p, boilerplate)
        scored.append({"url": p["url"], "title": p.get("title"), "score": s, "strengths": good, "fixes": fixes[:5],
                       "question_headings": [q for q in p.get("question_headings", []) if q not in boilerplate][:6]})
    scored.sort(key=lambda x: x["score"])
    avg = round(sum(s["score"] for s in scored) / len(scored)) if scored else 0

    robots = crawl.robots.get("ai_crawlers", {})
    search_bots = {b: robots.get(b, "allowed") for b in ("OAI-SearchBot", "ChatGPT-User", "PerplexityBot", "Claude-SearchBot", "Google-Extended", "GPTBot", "ClaudeBot", "CCBot")}
    home = crawl.pages.get(crawl.origin + "/") or (pages[0] if pages else {})
    org_schema = [it for it in home.get("schema", []) if any(t in str(it.get("@type")) for t in ("Organization", "LocalBusiness"))]
    same_as = org_schema[0].get("sameAs") if org_schema else None
    spa = sum(1 for p in pages if p.get("spa_shell"))
    llms = crawl.llms_txt.get("llms.txt", {})
    prereq = [
        {"check": "AI search crawlers allowed in robots.txt", "ok": all(v == "allowed" for k, v in search_bots.items() if k in ("OAI-SearchBot", "PerplexityBot", "Claude-SearchBot")),
         "detail": ", ".join(f"{k}: {v}" for k, v in search_bots.items())},
        {"check": "Content present in the initial HTML (no JS-only shell)", "ok": spa == 0, "detail": f"{spa} pages are client-side-rendered shells"},
        {"check": "Organization/LocalBusiness entity markup with sameAs", "ok": bool(same_as), "detail": "sameAs links help Google and LLMs resolve your brand entity"},
        {"check": "llms.txt published", "ok": bool(llms.get("exists")), "detail": "an emerging convention for LLM agents (low impact)"},
        {"check": "Indexable in Google (prerequisite for AI Overviews)", "ok": not crawl.robots.get("disallow_all"), "detail": "AI Overviews draw only on indexed pages that are eligible for snippets"},
        {"check": "No nosnippet / max-snippet:0 restrictions", "ok": not any("nosnippet" in (p.get("meta_robots") or "").lower() or "max-snippet:0" in (p.get("meta_robots") or "").lower() for p in pages),
         "detail": "Snippet controls also exclude the page from AI Overviews"},
    ]
    brand = re.sub(r"\W+", "", _brand(crawl).lower())
    # "why acme" comes from adding question words to the brand name. Nobody searches that.
    questions = [q for q in (research or {}).get("questions", []) if len(brand) < 4 or brand not in re.sub(r"\W+", "", q.lower())][:40]
    q_map = []
    for q in questions:
        kw = next((k for k in (research or {}).get("keywords", []) if k["keyword"] == q), None)
        target = kw.get("target_url") if kw else None
        slug = kw.get("suggested_slug") if kw else None
        q_map.append({"question": q, "target_url": target,
                      "action": f"Add '{q}' as a heading on {urlparse(target).path or '/'} with a 40–60 word answer." if target
                      else f"No page answers '{q}'. Create {slug}, or add it to an FAQ." if slug
                      else f"No page answers '{q}'. Add it to an FAQ."})

    issues = []
    weak = [s for s in scored if s["score"] < 50]
    if weak:
        issues.append(issue("aio_low_suitability", "AI search", "high" if len(weak) > len(scored) / 2 else "medium",
                            "Low suitability for AI Overviews and answer extraction",
                            f"{len(weak)} pages score under 50/100 for answer extraction (average {avg}).",
                            "Restructure them into question headings, each followed by a 40–60-word direct answer, plus lists, tables, sourced statistics, author bylines and dates. See the AIO/GEO brief.",
                            [s["url"] for s in weak], impact=7, effort=4,
                            details=[{"url": s["url"], "score": s["score"], "fixes": s["fixes"][:3]} for s in weak]))
    if not same_as:
        issues.append(issue("entity_sameas", "AI search", "medium", "Brand entity not linked (no sameAs)",
                            "LLMs and Google's Knowledge Graph connect brands to entities through consistent sameAs references.",
                            "Add Organization schema with sameAs links to LinkedIn, Crunchbase, Wikipedia/Wikidata, YouTube and your social profiles. Keep NAP and brand name consistent everywhere.",
                            [crawl.origin + "/"], impact=5, effort=2))

    brief = {
        "summary": (f"Average AI answer-readiness is {avg}/100 across {len(scored)} content pages. "
                    f"{sum(1 for p in prereq if p['ok'])}/{len(prereq)} technical prerequisites are met."),
        "what_it_is": [
            "AI Overviews (AIO) are Google's generated answers above the blue links. They cite pages that are already indexed, rank reasonably well (usually top 10–20) and contain a clear, extractable passage answering the query.",
            "GEO (Generative Engine Optimization) is the practice of getting your brand cited by ChatGPT Search, Perplexity, Claude, Gemini and Copilot. Those engines retrieve pages with their own crawlers (most without running JavaScript) and quote passages that are self-contained, factual and attributable.",
            "Both reward the same things: crawlable server-rendered HTML, question-led structure, direct answers, original data, clear authorship and freshness, and a well-defined brand entity mentioned across the web.",
        ],
        "playbook": [
            {"step": "1. Unblock and render", "actions": ["Allow OAI-SearchBot, PerplexityBot, Claude-SearchBot and Googlebot in robots.txt", "Server-render all primary content", "Avoid nosnippet on pages you want cited"]},
            {"step": "2. Answer-first formatting", "actions": ["One question per H2/H3, phrased the way users ask it", "40–60-word answer immediately under the heading, then the detail", "TL;DR summary at the top of long guides", "Steps as numbered lists, comparisons as tables"]},
            {"step": "3. Information gain", "actions": ["Publish original statistics, surveys, benchmarks and pricing ranges", "Quote named experts and add first-hand photos", "Cite primary sources inline"]},
            {"step": "4. Entity and trust", "actions": ["Organization/LocalBusiness + Person schema with sameAs", "Author bio pages with credentials", "Consistent brand mentions on Reddit, YouTube, LinkedIn, industry directories and review sites (LLMs weight these heavily)"]},
            {"step": "5. Freshness", "actions": ["Refresh key pages every quarter with a visible updated date and dateModified", "Keep the year current in time-sensitive titles"]},
            {"step": "6. Measure", "actions": ["Track AI referrals in GA4 (sources chatgpt.com, perplexity.ai, gemini.google.com, copilot.microsoft.com)", "Monitor AI Overview presence for your top 50 queries monthly", "Log brand mentions in AI answers with a fixed prompt set"]},
        ],
        "answer_template": "## {Question phrased as the user asks it}?\n{Direct answer in 40–60 words: definition or number first, then the key qualifier.}\n\n- Supporting point with a statistic (source)\n- Supporting point with an example\n\n{Optional table or numbered steps}",
        "prerequisites": prereq, "question_opportunities": q_map,
        "priority_pages": scored[:15],
    }
    return {"issues": issues, "pages": scored, "average": avg, "brief": brief, "ai_crawlers": search_bots}
