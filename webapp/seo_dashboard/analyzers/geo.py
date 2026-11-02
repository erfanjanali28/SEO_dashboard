"""AI Overviews (AIO) and Generative Engine Optimization (GEO) analysis.

Scores each page for answer extraction (direct answers under question
headings, 40–60-word answer blocks, lists and tables, statistics, sources,
freshness, authorship, structured data) and checks site-level prerequisites
(AI crawler access, server-rendered content, entity markup, llms.txt).
Produces a written brief the team can act on.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from . import html_pages, indexable, issue
from .content import UTILITY


def page_score(p: dict) -> tuple[int, list[str], list[str]]:
    score, good, fixes = 0, [], []
    sections = p.get("sections", [])
    qh = p.get("question_headings", [])
    answer_blocks = [s for s in sections if s["kind"] == "p" and 25 <= s["words"] <= 80]
    if qh:
        score += 15
        good.append(f"{len(qh)} question-style headings")
    else:
        fixes.append("Phrase 2–4 H2/H3s as the questions users ask (e.g. 'How much does X cost?').")
    if answer_blocks:
        score += 20
        good.append(f"{len(answer_blocks)} concise answer paragraphs (25–80 words)")
    else:
        fixes.append("Put a 40–60 word direct answer right under each question heading, and lead with the answer.")
    fp = p.get("first_paragraph", "")
    if 20 <= len(fp.split()) <= 70:
        score += 10
        good.append("intro summarizes the topic concisely")
    else:
        fixes.append("Open with a 1–2 sentence TL;DR that defines the topic and states the key takeaway.")
    if p.get("lists") or p.get("tables"):
        score += 10
        good.append("uses lists/tables")
    else:
        fixes.append("Add a bulleted list, numbered steps or a comparison table. These are easy to extract.")
    text = p.get("text", "")
    stats = len(re.findall(r"\b\d+(?:\.\d+)?\s?(?:%|percent|million|billion|x\b)", text))
    if stats >= 2:
        score += 10
        good.append(f"{stats} statistics")
    else:
        fixes.append("Add specific, sourced statistics and numbers. LLMs prefer quotable facts.")
    ext = [l for l in p.get("external_links", []) if not l["nav"]]
    if ext:
        score += 5
        good.append("cites external sources")
    else:
        fixes.append("Cite 2–3 authoritative sources inline.")
    if p.get("author_signals"):
        score += 10
        good.append("author attribution")
    else:
        fixes.append("Add an author byline with credentials and Person schema (E-E-A-T).")
    if p.get("dates", {}).get("modified") or p.get("dates", {}).get("published"):
        score += 5
        good.append("dated content")
    else:
        fixes.append("Show a visible 'Last updated' date and add dateModified to the schema.")
    if p.get("schema"):
        score += 10
        good.append("structured data present")
    else:
        fixes.append("Add JSON-LD (Article/Product/Service + Organization + BreadcrumbList).")
    if p.get("word_count", 0) >= 600:
        score += 5
    if not p.get("spa_shell"):
        score += 0
    else:
        score -= 20
        fixes.insert(0, "Server-render the content. Most AI crawlers do not execute JavaScript.")
    return max(0, min(100, score)), good, fixes


def analyze(crawl, research: dict | None = None) -> dict:
    pages = [p for p in html_pages(crawl.pages) if indexable(p) and not UTILITY.search(urlparse(p["url"]).path)]
    scored = []
    for p in pages:
        s, good, fixes = page_score(p)
        scored.append({"url": p["url"], "title": p.get("title"), "score": s, "strengths": good, "fixes": fixes[:5],
                       "question_headings": p.get("question_headings", [])[:6]})
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
    questions = (research or {}).get("questions", [])[:40]
    q_map = []
    for q in questions:
        kw = next((k for k in (research or {}).get("keywords", []) if k["keyword"] == q), None)
        q_map.append({"question": q, "target_url": kw.get("target_url") if kw else None,
                      "action": "Add a Q&A section to the target page" if kw and kw.get("target_url") else "Create a dedicated answer page or FAQ section"})

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
