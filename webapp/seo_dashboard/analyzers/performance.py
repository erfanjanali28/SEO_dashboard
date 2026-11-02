"""Core Web Vitals and loading performance through the PageSpeed Insights v5 API.

PSI returns lab data (Lighthouse) and, when Chrome UX Report has enough
traffic, field data (LCP, INP, CLS at p75). A Google API key
(``PAGESPEED_API_KEY`` setting) raises the quota; without one PSI still
works at a low rate. Network failures degrade to an empty result.
"""

from __future__ import annotations

import requests

from . import issue

PSI = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
THRESHOLDS = {  # good / poor boundaries (Google, 2024+: INP replaced FID)
    "LCP": (2500, 4000), "INP": (200, 500), "CLS": (0.1, 0.25), "FCP": (1800, 3000), "TTFB": (800, 1800),
}
FIELD_KEYS = {
    "LARGEST_CONTENTFUL_PAINT_MS": "LCP", "INTERACTION_TO_NEXT_PAINT": "INP",
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": "CLS", "FIRST_CONTENTFUL_PAINT_MS": "FCP",
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": "TTFB",
}


def rate(metric: str, value) -> str:
    if value is None:
        return "n/a"
    good, poor = THRESHOLDS[metric]
    return "good" if value <= good else "poor" if value > poor else "needs improvement"


def run_psi(url: str, strategy: str, api_key: str | None = None, timeout: int = 90) -> dict:
    params = {"url": url, "strategy": strategy, "category": ["performance", "seo", "accessibility", "best-practices"]}
    if api_key:
        params["key"] = api_key
    try:
        r = requests.get(PSI, params=params, timeout=timeout)
        data = r.json()
    except Exception as exc:
        return {"url": url, "strategy": strategy, "error": f"{type(exc).__name__}: {exc}"[:200]}
    if "error" in data:
        return {"url": url, "strategy": strategy, "error": data["error"].get("message", "PSI error")[:200]}
    lh = data.get("lighthouseResult", {})
    audits = lh.get("audits", {})
    cats = lh.get("categories", {})

    def num(key):
        return audits.get(key, {}).get("numericValue")
    field = {}
    for k, v in (data.get("loadingExperience", {}).get("metrics") or {}).items():
        if k in FIELD_KEYS:
            val = v.get("percentile")
            if FIELD_KEYS[k] == "CLS" and val is not None:
                val = val / 100
            field[FIELD_KEYS[k]] = val
    opportunities = []
    for key, a in audits.items():
        details = a.get("details") or {}
        if details.get("type") == "opportunity" and (details.get("overallSavingsMs") or 0) > 100:
            opportunities.append({"id": key, "title": a.get("title"), "savings_ms": round(details["overallSavingsMs"])})
    opportunities.sort(key=lambda x: -x["savings_ms"])
    return {
        "url": url, "strategy": strategy,
        "scores": {k: round((v.get("score") or 0) * 100) for k, v in cats.items()},
        "lab": {"LCP": num("largest-contentful-paint"), "CLS": num("cumulative-layout-shift"),
                "FCP": num("first-contentful-paint"), "TBT": num("total-blocking-time"),
                "SI": num("speed-index"), "TTFB": num("server-response-time")},
        "field": field, "field_overall": data.get("loadingExperience", {}).get("overall_category"),
        "opportunities": opportunities[:10],
        "page_weight_kb": round((num("total-byte-weight") or 0) / 1024),
    }


def analyze(urls: list[str], api_key: str | None = None, enabled: bool = True) -> dict:
    results = []
    if enabled:
        for u in urls:
            for strategy in ("mobile", "desktop"):
                results.append(run_psi(u, strategy, api_key))
    issues = []
    good = [r for r in results if "error" not in r]
    mobile = [r for r in good if r["strategy"] == "mobile"]
    for metric in ("LCP", "INP", "CLS"):
        bad = []
        for r in mobile:
            val = r["field"].get(metric) if r["field"].get(metric) is not None else r["lab"].get(metric)
            if rate(metric, val) != "good" and val is not None:
                bad.append({"url": r["url"], "value": val, "rating": rate(metric, val),
                            "source": "field (CrUX)" if r["field"].get(metric) is not None else "lab"})
        if bad:
            sev = "high" if any(b["rating"] == "poor" for b in bad) else "medium"
            fix = {
                "LCP": "Preload the LCP image (fetchpriority=high), serve it as AVIF/WebP, cut TTFB with caching or a CDN, inline critical CSS, and defer render-blocking JS.",
                "INP": "Break up long tasks, defer or remove heavy third-party scripts, keep event handlers light, and move work off the main thread with web workers.",
                "CLS": "Set width/height on images, embeds and ads, reserve space for dynamic banners, and use font-display: optional or swap with size-adjusted fallbacks.",
            }[metric]
            issues.append(issue(f"cwv_{metric.lower()}", "Core Web Vitals", sev, f"{metric} needs work on mobile",
                                f"{len(bad)} tested pages miss the 'good' {metric} threshold ({THRESHOLDS[metric][0]}{'' if metric == 'CLS' else ' ms'}).",
                                fix, [b["url"] for b in bad], impact=7 if sev == "high" else 5, effort=5, details=bad))
    low_perf = [r for r in mobile if r["scores"].get("performance", 100) < 50]
    if low_perf:
        issues.append(issue("lighthouse_perf", "Performance", "high", "Lighthouse mobile performance below 50",
                            "Slow mobile pages lose rankings and conversions.",
                            "Work through the top PSI opportunities for each page, listed in the Performance tab.",
                            [r["url"] for r in low_perf], impact=6, effort=5,
                            details=[{"url": r["url"], "score": r["scores"]["performance"], "top": r["opportunities"][:3]} for r in low_perf]))
    errors = [r for r in results if "error" in r]
    return {"issues": issues, "results": results, "errors": errors, "tested": len(good)}
