"""Scores, Top 10 priority actions, and a 30/60/90-day roadmap."""

from __future__ import annotations

from collections import defaultdict

from . import SEVERITY_WEIGHT

CATEGORY_GROUPS = {
    "Technical": ["Status codes", "Redirects", "Indexability", "Crawlability", "Sitemaps", "JavaScript rendering", "International"],
    "On-page": ["On-page", "Content structure", "Images"],
    "Content": ["Content"],
    "Internal links": ["Internal linking", "Links", "URL structure"],
    "Schema": ["Schema"],
    "Performance": ["Performance", "Core Web Vitals"],
    "Mobile": ["Mobile"],
    "Security": ["Security"],
    "AI search (GEO)": ["AI search"],
    "Tracking & CRO": ["Tracking", "Conversion"],
}
OWNER = {
    "Status codes": "Developer", "Redirects": "Developer", "Indexability": "SEO + Developer", "Crawlability": "SEO",
    "Sitemaps": "Developer", "JavaScript rendering": "Developer", "International": "SEO + Developer",
    "On-page": "SEO / Content", "Content structure": "Content", "Images": "Content + Developer", "Content": "Content",
    "Internal linking": "SEO / Content", "Links": "Content", "URL structure": "SEO + Developer", "Schema": "Developer",
    "Performance": "Developer", "Core Web Vitals": "Developer", "Mobile": "Developer", "Security": "Developer / DevOps",
    "AI search": "SEO / Content", "Tracking": "Analytics", "Conversion": "CRO / Marketing",
}


def group_of(category: str) -> str:
    for g, cats in CATEGORY_GROUPS.items():
        if category in cats:
            return g
    return "Technical"


def scores(issues: list[dict], pages_ok: int, extra: dict | None = None) -> dict:
    """0–100 per group: penalty grows with severity and share of affected pages."""
    penalty = defaultdict(float)
    for i in issues:
        share = min(1.0, (i["count"] or 1) / max(pages_ok, 1)) if i["urls"] else 0.5
        penalty[group_of(i["category"])] += SEVERITY_WEIGHT[i["severity"]] * (0.35 + 0.65 * share) * 2.2
    out = {g: max(0, round(100 - penalty[g])) for g in CATEGORY_GROUPS}
    if extra:
        if extra.get("geo_avg") is not None:
            out["AI search (GEO)"] = round((out["AI search (GEO)"] + extra["geo_avg"]) / 2)
        if extra.get("perf_score") is not None:
            out["Performance"] = round((out["Performance"] + extra["perf_score"]) / 2)
    weights = {"Technical": 0.2, "On-page": 0.14, "Content": 0.14, "Internal links": 0.1, "Schema": 0.07,
               "Performance": 0.1, "Mobile": 0.07, "Security": 0.05, "AI search (GEO)": 0.08, "Tracking & CRO": 0.05}
    overall = round(sum(out[g] * w for g, w in weights.items()))
    return {"overall": overall, "categories": out}


def priority_value(i: dict, pages_ok: int) -> float:
    share = min(1.0, (i["count"] or 1) / max(pages_ok, 1)) if i["urls"] else 0.4
    return round(SEVERITY_WEIGHT[i["severity"]] * i["impact"] * (0.5 + share) / (0.5 + i["effort"] / 3), 2)


def top_actions(issues: list[dict], pages_ok: int, n: int = 10) -> list[dict]:
    ranked = sorted(issues, key=lambda i: -priority_value(i, pages_ok))
    out = []
    for rank, i in enumerate(ranked[:n], 1):
        out.append({
            "rank": rank, "id": i["id"], "title": i["title"], "category": i["category"], "severity": i["severity"],
            "affected": i["count"], "why": i["description"], "how": i["recommendation"],
            "owner": OWNER.get(i["category"], "SEO"), "effort": _effort_label(i["effort"]),
            "impact": _impact_label(i["impact"]), "score": priority_value(i, pages_ok),
            "example_urls": i["urls"][:5],
        })
    return out


def _effort_label(e: int) -> str:
    return "Quick win (hours)" if e <= 2 else "Moderate (days)" if e <= 4 else "Project (weeks)"


def _impact_label(i: int) -> str:
    return "High" if i >= 7 else "Medium" if i >= 4 else "Low"


def roadmap(issues: list[dict], pages_ok: int, extras: dict) -> dict:
    """Assign every issue to a phase by severity and effort, then add strategic workstreams."""
    phases = {"30": [], "60": [], "90": []}
    for i in sorted(issues, key=lambda x: -priority_value(x, pages_ok)):
        task = {"task": i["title"], "action": i["recommendation"], "owner": OWNER.get(i["category"], "SEO"),
                "category": i["category"], "severity": i["severity"], "affected": i["count"], "issue_id": i["id"]}
        if i["severity"] == "critical" or (i["severity"] == "high" and i["effort"] <= 3) or i["category"] in ("Tracking",):
            phases["30"].append(task)
        elif i["severity"] == "high" or (i["severity"] == "medium" and i["effort"] <= 3):
            phases["60"].append(task)
        else:
            phases["90"].append(task)
    gap_count = extras.get("content_gaps", 0)
    phases["30"].insert(0, {"task": "Baseline and measurement", "action": "Connect GSC and GA4 (Windsor.ai sync), set up GTM and key events from the Conversion plan, and record baseline rankings, traffic and leads.",
                            "owner": "Analytics", "category": "Strategy", "severity": "high", "affected": None})
    phases["60"].append({"task": "Internal linking sprint", "action": f"Implement the top {min(extras.get('link_suggestions', 0), 100)} contextual link suggestions (Excel export) and give every orphan page at least 3 inlinks.",
                         "owner": "Content", "category": "Strategy", "severity": "medium", "affected": extras.get("link_suggestions")})
    phases["60"].append({"task": "AIO/GEO restructuring", "action": "Rewrite the 10 highest-traffic pages with answer-first formatting: question H2s, 40–60-word answers, tables and sourced statistics.",
                         "owner": "Content", "category": "Strategy", "severity": "medium", "affected": 10})
    phases["90"].append({"task": "Content gap production", "action": f"Publish the top 8–12 pages from {gap_count} keyword gaps, organized into topic clusters with pillar pages.",
                         "owner": "Content", "category": "Strategy", "severity": "medium", "affected": gap_count})
    phases["90"].append({"task": "Off-page authority", "action": "Pitch 8–10 guest posts and digital-PR placements from the Off-page list. Build review and directory profiles. Track every link.",
                         "owner": "Outreach", "category": "Strategy", "severity": "medium", "affected": None})
    phases["90"].append({"task": "Review and iterate", "action": "Re-audit, compare score trends and GSC ranking improvements, and re-prioritize for the next quarter.",
                         "owner": "SEO", "category": "Strategy", "severity": "low", "affected": None})
    return {
        "phases": [
            {"name": "Days 1–30: Fix foundations", "goal": "Remove crawl and indexing blockers, fix critical errors, and start measuring.", "tasks": phases["30"]},
            {"name": "Days 31–60: Optimize on-page and structure", "goal": "Lift existing pages: metadata, content structure, schema, internal links, Core Web Vitals.", "tasks": phases["60"]},
            {"name": "Days 61–90: Grow and expand", "goal": "Build new content, AI-search visibility and authority.", "tasks": phases["90"]},
        ],
        "kpis": [
            "Indexed pages (GSC Pages report) vs. submitted",
            "Organic clicks and impressions (GSC), compared month over month",
            "Average position and the number of keywords in the top 3 / top 10",
            "Core Web Vitals pass rate (mobile)",
            "Organic key events (leads) and conversion rate (GA4)",
            "AI referral sessions (chatgpt.com, perplexity.ai, gemini) and AI Overview citations",
            "Referring domains gained",
        ],
    }
