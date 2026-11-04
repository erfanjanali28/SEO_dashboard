"""Crawler-visible metrics for a site we do not manage.

A first look uses only what any crawler can see from outside. It reads no
Search Console, GA4 or paid data, because none of that belongs to us.
"""

from __future__ import annotations

from . import html_pages, indexable

NOT_VISIBLE = [
    "Rankings, clicks and impressions (need Search Console)",
    "Traffic and conversions (need GA4)",
    "Backlinks and domain authority (need a backlink tool)",
    "Real-user Core Web Vitals (run PageSpeed separately)",
]


def _coverage(label: str, count: int, total: int) -> dict:
    pct = round(count / total * 100) if total else 0
    return {"label": label, "value": f"{pct}%", "detail": f"{count} of {total} pages",
            "status": "good" if pct >= 90 else "warn" if pct >= 60 else "bad"}


def _plain(label: str, value, status: str = "info", detail: str = "") -> dict:
    return {"label": label, "value": value, "detail": detail, "status": status}


def summary(crawl, tech: dict, link_stats: dict, geo_average) -> dict:
    ok = html_pages(crawl.pages)
    total = len(ok)
    skipped = sum(1 for p in crawl.pages.values() if p.get("skipped_by_robots"))
    errors = sum(1 for p in crawl.pages.values() if (p.get("status") or 0) >= 400)
    redirected = sum(1 for p in crawl.pages.values() if p.get("redirect_chain"))
    words = [p.get("word_count", 0) for p in ok]
    images = [i for p in ok for i in p.get("images", [])]
    with_alt = sum(1 for i in images if i.get("alt"))
    secure = crawl.origin.startswith("https://")
    ai = crawl.robots.get("ai_crawlers") or {}
    return {
        "groups": [
            {"name": "Crawl and indexability", "items": [
                _plain("HTML pages reached", total),
                _coverage("Indexable", sum(1 for p in ok if indexable(p)), total),
                _plain("Error URLs (4xx/5xx)", errors, "good" if not errors else "bad"),
                _plain("Redirecting URLs", redirected, "good" if not redirected else "warn"),
                _plain("Skipped by robots.txt", skipped),
                _plain("Average response", f"{tech.get('avg_response_ms', 0)} ms", "good" if tech.get("avg_response_ms", 0) < 800 else "warn"),
            ]},
            {"name": "On-page coverage", "items": [
                _coverage("Title tag", sum(1 for p in ok if p.get("title")), total),
                _coverage("Meta description", sum(1 for p in ok if p.get("meta_description")), total),
                _coverage("Exactly one H1", sum(1 for p in ok if len(p.get("h1") or []) == 1), total),
                _coverage("Canonical tag", sum(1 for p in ok if p.get("canonical")), total),
                _coverage("Open Graph tags", sum(1 for p in ok if p.get("og")), total),
                _coverage("Language attribute", sum(1 for p in ok if p.get("lang")), total),
                _coverage("Images with alt text", with_alt, len(images)) if images else _plain("Images with alt text", "No images"),
                _plain("Average words per page", round(sum(words) / total) if total else 0),
            ]},
            {"name": "Site setup", "items": [
                _plain("HTTPS", "Yes" if secure else "No", "good" if secure else "bad"),
                _plain("robots.txt", "Found" if crawl.robots.get("exists") else "Missing", "good" if crawl.robots.get("exists") else "warn"),
                _plain("XML sitemap", f"{len(crawl.sitemaps.get('urls', []))} URLs" if crawl.sitemaps.get("found") else "Missing", "good" if crawl.sitemaps.get("found") else "bad"),
                _plain("llms.txt", "Found" if (crawl.llms_txt.get("llms.txt") or {}).get("exists") else "Missing"),
                _coverage("Structured data", tech.get("pages_with_schema", 0), total),
                _plain("Schema types", ", ".join(list(tech.get("schema_types", {}))[:5]) or "None"),
                _plain("Mobile viewport", f"{sum(1 for p in ok if p.get('viewport'))} of {total} pages"),
                _plain("AI crawlers allowed", f"{sum(1 for v in ai.values() if v == 'allowed')} of {len(ai)}" if ai else "No rules found"),
            ]},
            {"name": "Internal linking and AI readiness", "items": [
                _plain("Orphan pages", len(link_stats.get("orphans", [])), "good" if not link_stats.get("orphans") else "warn"),
                _plain("Average inlinks per page", link_stats.get("avg_inlinks", 0)),
                _plain("AI answer readiness", f"{geo_average}/100" if geo_average is not None else "Not scored"),
                _plain("Platform signals", ", ".join(tech.get("frameworks", [])) or "None detected"),
            ]},
        ],
        "not_visible": NOT_VISIBLE,
    }
