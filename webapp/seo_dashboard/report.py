"""Self-contained, printable HTML report with inline SVG charts.

Open it in a browser and use Print → Save as PDF for a client-ready PDF.
The client photo/logo is embedded as a data URI, so the file stands alone.
"""

from __future__ import annotations

import base64
import html
import mimetypes
import os
from collections import Counter

from . import db

PALETTE = ["#1e3a5f", "#b8860b", "#2d6a4f", "#d4740e", "#c53030", "#5a7fa8", "#7b6d8d", "#3d8b8b"]
SEV_COLOR = {"critical": "#c53030", "high": "#d4740e", "medium": "#b8860b", "low": "#2d6a4f"}
e = html.escape


def svg_bar(data: dict, title: str, width: int = 640, color: str = "#1e3a5f", max_items: int = 14, value_max: float | None = None) -> str:
    items = list(data.items())[:max_items]
    if not items:
        return ""
    bar_h, gap, label_w = 22, 8, 210
    h = len(items) * (bar_h + gap) + 40
    vmax = value_max or max((v or 0) for _, v in items) or 1
    out = [f'<figure><svg viewBox="0 0 {width} {h}" width="100%" role="img" aria-label="{e(title)}">']
    for i, (k, v) in enumerate(items):
        y = 10 + i * (bar_h + gap)
        w = (width - label_w - 60) * (v or 0) / vmax
        label = str(k)[:34] + ("…" if len(str(k)) > 34 else "")
        out.append(f'<text x="{label_w - 8}" y="{y + 15}" text-anchor="end" font-size="12" fill="#333">{e(label)}</text>')
        out.append(f'<rect x="{label_w}" y="{y}" width="{max(w, 1):.1f}" height="{bar_h}" rx="3" fill="{color}"/>')
        out.append(f'<text x="{label_w + w + 6:.1f}" y="{y + 15}" font-size="12" fill="#333">{v}</text>')
    out.append(f'</svg><figcaption>{e(title)}</figcaption></figure>')
    return "".join(out)


def svg_donut(data: dict, title: str, colors: dict | None = None) -> str:
    total = sum(v for v in data.values() if v) or 0
    if not total:
        return ""
    import math
    cx = cy = 90
    r, inner = 80, 48
    out = [f'<figure><svg viewBox="0 0 420 190" width="100%" style="max-width:520px" role="img" aria-label="{e(title)}">']
    ang = -math.pi / 2
    for i, (k, v) in enumerate(data.items()):
        if not v:
            continue
        frac = v / total
        a2 = ang + frac * 2 * math.pi
        large = 1 if frac > 0.5 else 0
        col = (colors or {}).get(k, PALETTE[i % len(PALETTE)])
        if frac >= 0.999:
            out.append(f'<circle cx="{cx}" cy="{cy}" r="{(r + inner) / 2}" fill="none" stroke="{col}" stroke-width="{r - inner}"/>')
        else:
            x1, y1 = cx + r * math.cos(ang), cy + r * math.sin(ang)
            x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
            x3, y3 = cx + inner * math.cos(a2), cy + inner * math.sin(a2)
            x4, y4 = cx + inner * math.cos(ang), cy + inner * math.sin(ang)
            out.append(f'<path d="M{x1:.1f},{y1:.1f} A{r},{r} 0 {large} 1 {x2:.1f},{y2:.1f} L{x3:.1f},{y3:.1f} A{inner},{inner} 0 {large} 0 {x4:.1f},{y4:.1f} Z" fill="{col}"/>')
        ang = a2
    out.append(f'<text x="{cx}" y="{cy + 6}" text-anchor="middle" font-size="18" font-weight="bold" fill="#1e3a5f">{total}</text>')
    for i, (k, v) in enumerate(data.items()):
        col = (colors or {}).get(k, PALETTE[i % len(PALETTE)])
        out.append(f'<rect x="200" y="{18 + i * 22}" width="12" height="12" fill="{col}"/><text x="218" y="{29 + i * 22}" font-size="12" fill="#333">{e(str(k))}: {v} ({round(100 * (v or 0) / total)}%)</text>')
    out.append(f'</svg><figcaption>{e(title)}</figcaption></figure>')
    return "".join(out)


def svg_line(points: list[tuple[str, float]], title: str, reverse: bool = False, color: str = "#1e3a5f") -> str:
    pts = [(d, v) for d, v in points if v is not None]
    if len(pts) < 2:
        return ""
    W, H, pad = 640, 220, 40
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi = lo + 1
    def xy(i, v):
        x = pad + i * (W - 2 * pad) / (len(pts) - 1)
        frac = (v - lo) / (hi - lo)
        y = pad + (frac if reverse else 1 - frac) * (H - 2 * pad)
        return x, y
    path = " ".join(f"{'M' if i == 0 else 'L'}{xy(i, v)[0]:.1f},{xy(i, v)[1]:.1f}" for i, (_, v) in enumerate(pts))
    out = [f'<figure><svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="{e(title)}">',
           f'<line x1="{pad}" y1="{H - pad}" x2="{W - pad}" y2="{H - pad}" stroke="#ccc"/>',
           f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5"/>',
           f'<text x="{pad}" y="{H - 12}" font-size="11" fill="#666">{e(pts[0][0])}</text>',
           f'<text x="{W - pad}" y="{H - 12}" font-size="11" fill="#666" text-anchor="end">{e(pts[-1][0])}</text>',
           f'<text x="6" y="{pad if not reverse else H - pad}" font-size="11" fill="#666">{round(hi, 1)}</text>',
           f'<text x="6" y="{H - pad if not reverse else pad}" font-size="11" fill="#666">{round(lo, 1)}</text>',
           f'</svg><figcaption>{e(title)}</figcaption></figure>']
    return "".join(out)


def _table(rows: list[dict], cols: list[tuple[str, str]], limit: int = 50) -> str:
    if not rows:
        return '<p class="muted">No items.</p>'
    head = "".join(f"<th>{e(lbl)}</th>" for _, lbl in cols)
    body = []
    for r in rows[:limit]:
        cells = []
        for k, _ in cols:
            v = r.get(k)
            if isinstance(v, (list, tuple)):
                v = ", ".join(str(x) for x in v[:6])
            cls = f' class="sev-{v}"' if k == "severity" else ""
            cells.append(f"<td{cls}>{e(str(v if v is not None else ''))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    more = f'<p class="muted">… {len(rows) - limit} more rows in the Excel export.</p>' if len(rows) > limit else ""
    return f'<table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>{more}'


def _photo(client: dict) -> str:
    p = client.get("photo")
    if not p:
        return ""
    path = os.path.join(db.UPLOAD_DIR, os.path.basename(p))
    if not os.path.exists(path):
        return ""
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as fh:
        data = base64.b64encode(fh.read()).decode()
    return f'<img class="client-photo" src="data:{mime};base64,{data}" alt="{e(client.get("name", ""))}">'


def render(result: dict, client: dict, site: dict, history: list[dict], search: dict) -> str:
    sc = result["scores"]
    sev = Counter(i["severity"] for i in result["issues"])
    sections = []

    def section(title, body):
        sections.append((title, body))

    top = "".join(
        f'<div class="action"><div class="rank">{a["rank"]}</div><div><h4>{e(a["title"])} <span class="pill sev-{a["severity"]}">{a["severity"]}</span></h4>'
        f'<p>{e(a["why"])}</p><p><b>Fix:</b> {e(a["how"])}</p><p class="muted">Owner: {e(a["owner"])} · Effort: {e(a["effort"])} · Impact: {e(a["impact"])} · Affected: {a["affected"]}</p></div></div>'
        for a in result["top10"])
    section("Executive summary",
            f'<p>The site scored <b>{sc["overall"]}/100</b> across {result["meta"]["pages_crawled"]} crawled URLs. '
            f'We found {sev["critical"]} critical, {sev["high"]} high, {sev["medium"]} medium and {sev["low"]} low-severity issues.</p>'
            + '<div class="grid2">' + svg_bar(sc["categories"], "Score by category (0–100)", value_max=100)
            + svg_donut({k: sev.get(k, 0) for k in ("critical", "high", "medium", "low")}, "Issues by severity", SEV_COLOR) + "</div>"
            + (svg_line([(h["started_at"][:10], h["score"]) for h in history], "Audit score over time") if len(history) > 1 else ""))
    section("Top 10 priority actions", top)

    road = ""
    for ph in result["roadmap"]["phases"]:
        road += f'<h3>{e(ph["name"])}</h3><p class="muted">{e(ph["goal"])}</p>' + _table(ph["tasks"], [("task", "Task"), ("action", "Action"), ("owner", "Owner"), ("severity", "Severity")], 25)
    road += "<h3>KPIs</h3><ul>" + "".join(f"<li>{e(k)}</li>" for k in result["roadmap"]["kpis"]) + "</ul>"
    section("30/60/90-day implementation roadmap", svg_bar({p["name"]: len(p["tasks"]) for p in result["roadmap"]["phases"]}, "Tasks per phase", color="#b8860b") + road)

    tech = result["technical"]
    tech_issues = [i for i in result["issues"] if i["category"] in ("Status codes", "Redirects", "Indexability", "Crawlability", "Sitemaps", "JavaScript rendering", "Security", "Mobile", "International")]
    section("Technical SEO",
            '<div class="grid2">' + svg_donut(tech["status_counts"], "HTTP status codes")
            + svg_bar(dict(Counter(i["category"] for i in tech_issues)), "Technical issues by area", color="#c53030") + "</div>"
            + _table(tech_issues, [("severity", "Severity"), ("title", "Issue"), ("count", "Affected"), ("recommendation", "Recommendation")])
            + "<h3>404 pages and suggested 301 redirects</h3>"
            + _table(tech["redirect_suggestions"], [("from", "Broken URL"), ("to", "301 to"), ("confidence", "Confidence")])
            + "<h3>Broken links</h3>" + _table(tech["broken_links"], [("source", "Source"), ("target", "Target"), ("status", "Status")], 30))

    onpage = [i for i in result["issues"] if i["category"] in ("On-page", "Content structure", "Images")]
    section("On-page optimization",
            svg_bar(dict((i["title"], i["count"]) for i in onpage), "On-page issues (affected URLs)", color="#d4740e")
            + "<h3>Title and meta description suggestions</h3>"
            + _table(result["meta_suggestions"], [("source_url", "Source URL"), ("target_keyword", "Target keyword"), ("suggested_title", "Suggested title"), ("suggested_description", "Suggested description")], 30))

    ct = result["content"]
    cont = [i for i in result["issues"] if i["category"] == "Content"]
    section("Content quality",
            '<div class="grid2">' + svg_bar(ct["word_buckets"], "Pages by word count", color="#2d6a4f") + svg_bar(dict((i["title"], i["count"]) for i in cont), "Content issues", color="#c53030") + "</div>"
            + _table(cont, [("severity", "Severity"), ("title", "Issue"), ("count", "Affected"), ("recommendation", "Recommendation")])
            + "<h3>Keyword cannibalization</h3>" + _table(ct["cannibalization"], [("keyword", "Keyword"), ("pages", "Competing pages")], 20))

    lk = result["links"]
    section("Internal linking and URL structure",
            '<div class="grid2">' + svg_bar(lk["stats"]["depth_distribution"], "Pages by click depth") + svg_bar(lk["stats"]["folders"], "URLs per folder", color="#5a7fa8") + "</div>"
            + f'<p>{len(lk["stats"]["orphans"])} orphan pages · average {lk["stats"]["avg_inlinks"]} internal inlinks per page · {len(lk["suggestions"])} link suggestions (full list in the Internal Links Excel).</p>'
            + _table(lk["suggestions"], [("priority", "Priority"), ("source_url", "Source URL"), ("target_url", "Target URL"), ("anchor_text", "Anchor")], 25))

    section("Schema markup",
            svg_bar(tech["schema_types"] or {"none found": 0}, "Schema types found", color="#7b6d8d")
            + f'<p>{tech["pages_with_schema"]} of {tech["pages_ok"]} HTML pages have structured data.</p>'
            + _table(tech["schema_suggestions"], [("url", "Page without schema"), ("suggested", "Suggested type")], 25)
            + _table(tech["schema_problems"], [("url", "URL"), ("type", "Type"), ("problems", "Problems")], 25))

    perf = result["performance"]
    pr = {f'{r["url"].split("//")[-1][:30]} ({r["strategy"]})': r["scores"].get("performance") for r in perf["results"] if "error" not in r}
    cwv_rows = [{"url": r["url"], "strategy": r["strategy"], "lcp": r["field"].get("LCP") or r["lab"].get("LCP"), "inp": r["field"].get("INP"),
                 "cls": r["field"].get("CLS") if r["field"].get("CLS") is not None else r["lab"].get("CLS"), "score": r["scores"].get("performance")}
                for r in perf["results"] if "error" not in r]
    section("Core Web Vitals and speed",
            (svg_bar(pr, "Lighthouse performance score", value_max=100, color="#2d6a4f") if pr else '<p class="muted">PageSpeed Insights was not reachable or is disabled. Add an API key in Settings.</p>')
            + _table(cwv_rows, [("url", "URL"), ("strategy", "Device"), ("lcp", "LCP ms"), ("inp", "INP ms"), ("cls", "CLS"), ("score", "Score")])
            + f'<p>Average server response (TTFB proxy): {tech["avg_response_ms"]} ms.</p>')

    kw = result["keywords"]
    section("Keyword research",
            '<div class="grid2">' + svg_donut(kw["intent_counts"], "Keywords by intent") + svg_donut(kw["status_counts"], "Coverage") + "</div>"
            + svg_bar({c["cluster"]: c["size"] for c in kw["clusters"]}, "Topic clusters (keywords per cluster)", color="#b8860b")
            + _table(kw["keywords"], [("keyword", "Keyword"), ("intent", "Intent"), ("priority", "Priority"), ("status", "Status"), ("target_url", "Target URL"), ("suggested_slug", "New page slug")], 40))

    if search.get("has_data"):
        t = search["totals"]
        section("Search performance and ranking trends",
                f'<p>Last 28 days: <b>{t["clicks"]}</b> clicks (previous {t["prev_clicks"]}), <b>{t["impressions"]}</b> impressions (previous {t["prev_impressions"]}), {t["keywords"]} ranking keywords, {t["top10"]} in the top 10.</p>'
                + svg_line([(d["date"], d["clicks"]) for d in search["daily"]], "Organic clicks per day")
                + svg_line([(d["date"], d["position"]) for d in search["daily"]], "Average position (lower is better)", reverse=True, color="#b8860b")
                + svg_bar(search["position_buckets"], "Keywords by position range")
                + "<h3>Biggest ranking improvements</h3>" + _table(search["improved"], [("query", "Query"), ("prev_position", "Previous"), ("position", "Now"), ("change", "Gain")], 20)
                + "<h3>Ranking declines</h3>" + _table(search["declined"], [("query", "Query"), ("prev_position", "Previous"), ("position", "Now"), ("change", "Change")], 20))

    g = result["geo"]
    b = g["brief"]
    bands = Counter("0-24" if p["score"] < 25 else "25-49" if p["score"] < 50 else "50-74" if p["score"] < 75 else "75-100" for p in g["pages"])
    section("AI Overviews and GEO brief",
            f'<p><b>{e(b["summary"])}</b></p>' + "".join(f"<p>{e(x)}</p>" for x in b["what_it_is"])
            + svg_bar({k: bands.get(k, 0) for k in ("0-24", "25-49", "50-74", "75-100")}, "Pages by AI answer-readiness score", color="#3d8b8b")
            + _table(b["prerequisites"], [("check", "Prerequisite"), ("ok", "Met"), ("detail", "Detail")])
            + "".join(f'<h4>{e(s["step"])}</h4><ul>' + "".join(f"<li>{e(a)}</li>" for a in s["actions"]) + "</ul>" for s in b["playbook"])
            + f'<h4>Answer block template</h4><pre>{e(b["answer_template"])}</pre>'
            + "<h3>Pages to restructure first</h3>" + _table(b["priority_pages"], [("url", "URL"), ("score", "Score"), ("fixes", "Fixes")], 15)
            + "<h3>Question opportunities</h3>" + _table(b["question_opportunities"], [("question", "Question"), ("target_url", "Target"), ("action", "Action")], 25))

    conv = result["conversion"]
    section("Lead generation and conversion tracking",
            '<div class="grid2">' + svg_bar(dict(Counter(ev["event_name"] for ev in conv["events"]).most_common(12)), "Recommended GA4 events (placements)", color="#1e3a5f")
            + svg_donut(conv["page_types"], "Pages by commercial role") + "</div>"
            + "<h3>Setup steps</h3><ol>" + "".join(f"<li>{e(s)}</li>" for s in conv["setup_steps"]) + "</ol>"
            + "<h3>Event plan</h3>" + _table(conv["events"], [("priority", "Priority"), ("page_url", "Page"), ("event_name", "Event"), ("element", "Element"), ("gtm_trigger", "Trigger"), ("key_event", "Key event")], 40)
            + "<h3>Lead-generation gaps</h3>" + _table(conv["lead_gaps"] + conv["opportunities"], [("url", "URL"), ("page_type", "Type"), ("recommendation", "Recommendation")], 25))

    off = result["offpage"]
    section("Off-page: guest posting and digital PR",
            svg_donut({"Free": off["free_count"], "Paid / membership": off["paid_count"]}, "Platforms by cost")
            + "<ul>" + "".join(f"<li>{e(x)}</li>" for x in off["guidelines"]) + "</ul>"
            + _table(off["platforms"], [("name", "Platform"), ("cost", "Cost"), ("type", "Type"), ("notes", "Notes")], 30)
            + "<h3>Prospecting footprints</h3>" + _table(off["footprints"], [("query", "Google query"), ("type", "Type")], 24))

    toc = "".join(f'<li><a href="#s{i}">{e(t)}</a></li>' for i, (t, _) in enumerate(sections))
    body = "".join(f'<section id="s{i}"><h2>{e(t)}</h2>{b}</section>' for i, (t, b) in enumerate(sections))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SEO Report – {e(site['url'])}</title>
<style>
body{{font-family:"Times New Roman",Georgia,serif;color:#222;max-width:960px;margin:0 auto;padding:24px;background:#fff;line-height:1.5}}
h1,h2,h3,h4{{color:#1e3a5f;font-family:Georgia,serif}} h2{{border-bottom:3px solid #b8860b;padding-bottom:4px;margin-top:40px}}
.title{{text-align:center;padding:60px 0 40px;border-bottom:1px solid #ddd}} .client-photo{{width:120px;height:120px;object-fit:cover;border-radius:50%;border:3px solid #1e3a5f}}
.score{{font-size:64px;color:#1e3a5f;font-weight:bold}} table{{border-collapse:collapse;width:100%;font-size:12px;margin:8px 0}}
th{{background:#1e3a5f;color:#fff;text-align:left;padding:6px}} td{{border-bottom:1px solid #eee;padding:5px;vertical-align:top;word-break:break-word}}
tr:nth-child(even) td{{background:#faf9f7}} .sev-critical{{color:#c53030;font-weight:bold}} .sev-high{{color:#d4740e;font-weight:bold}} .sev-medium{{color:#b8860b}} .sev-low{{color:#2d6a4f}}
.pill{{font-size:11px;border:1px solid currentColor;border-radius:10px;padding:1px 8px;font-family:sans-serif}}
.action{{display:flex;gap:14px;border:1px solid #eee;border-left:4px solid #b8860b;padding:10px;margin:10px 0;background:#faf9f7}}
.rank{{font-size:28px;font-weight:bold;color:#1e3a5f;min-width:36px}} .muted{{color:#777;font-size:12px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} figure{{margin:10px 0}} figcaption{{font-size:12px;color:#555;text-align:center;font-style:italic}}
pre{{background:#faf9f7;padding:10px;white-space:pre-wrap}} .noprint{{text-align:right}}
@media print{{.noprint{{display:none}} section{{break-before:page}} body{{padding:0}}}}
@media (max-width:700px){{.grid2{{grid-template-columns:1fr}}}}
</style></head><body>
<div class="noprint"><button onclick="window.print()">Print / Save as PDF</button></div>
<div class="title">{_photo(client)}<h1>SEO Audit Report</h1><h3>{e(site['url'])}</h3>
<p>Prepared for <b>{e(client.get('name') or '')}</b>{(' · ' + e(client['company'])) if client.get('company') else ''}</p>
<div class="score">{sc['overall']}<span style="font-size:24px">/100</span></div><p class="muted">Generated {e(result['meta']['generated_at'])}</p></div>
<h2>Contents</h2><ol>{toc}</ol>{body}
<section><h2>Methodology</h2><p>The site was crawled breadth-first from the home page and the XML sitemaps (up to {site.get('max_pages')} URLs) with SSRF-safe fetching.
Each page was analyzed for status codes, indexability directives, metadata, headings, content, links, structured data, security headers, mobile and rendering signals.
Core Web Vitals come from Google PageSpeed Insights (field data from CrUX where available). Search data comes from Google Search Console and GA4 via Windsor.ai.
Keyword research combines on-site term extraction, industry modifiers, question patterns and Google Autocomplete, plus search volumes when DataForSEO is configured.</p></section>
</body></html>"""
