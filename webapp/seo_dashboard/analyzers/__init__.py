"""Analyzers turn a crawl into issues, scores, suggestions and plans.

Every issue shares one shape so the dashboard, priorities engine and Excel
export can treat them uniformly::

    {"id", "category", "severity", "title", "description",
     "recommendation", "urls", "count", "impact", "effort"}

severity is one of critical | high | medium | low; impact and effort are 1-10.
"""

SEVERITY_WEIGHT = {"critical": 10, "high": 6, "medium": 3, "low": 1}


def issue(id_, category, severity, title, description, recommendation, urls=None,
          impact=5, effort=3, details=None):
    urls = list(dict.fromkeys(urls or []))
    out = {
        "id": id_, "category": category, "severity": severity, "title": title,
        "description": description, "recommendation": recommendation,
        "urls": urls[:500], "count": len(urls) if urls else 1,
        "impact": impact, "effort": effort,
    }
    if details:
        out["details"] = details[:500]
    return out


def html_pages(crawl_pages: dict) -> list[dict]:
    """Pages that returned 2xx HTML and were parsed."""
    return [p for p in crawl_pages.values()
            if p.get("status") and 200 <= p["status"] < 300 and "word_count" in p]


def indexable(page: dict) -> bool:
    robots = f"{page.get('meta_robots', '')} {page.get('x_robots_tag', '')}".lower()
    if "noindex" in robots or page.get("blocked_by_robots"):
        return False
    canon = page.get("canonical")
    return not canon or canon.rstrip("/") == page["url"].rstrip("/") or canon.rstrip("/") == page.get("final_url", "").rstrip("/")
