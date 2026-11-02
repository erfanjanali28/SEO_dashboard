"""Technical SEO analyzer.

Covers status codes and 404s, broken links, redirects (with 301 mapping
suggestions), indexability (noindex, robots, canonicals), duplicate URLs,
meta tags and titles, headings, images, robots.txt, XML sitemaps, llms.txt,
HTTPS / mixed content / security headers, mobile usability signals,
JavaScript rendering and content availability in the initial HTML, page
weight and server performance, and schema markup validation.
"""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher
from urllib.parse import parse_qs, urlparse

from . import html_pages, indexable, issue

# Required / recommended properties for Google rich-result eligible types.
SCHEMA_RULES = {
    "Organization": (["name", "url"], ["logo", "sameAs", "contactPoint"]),
    "LocalBusiness": (["name", "address"], ["telephone", "openingHoursSpecification", "geo", "url", "priceRange"]),
    "Article": (["headline"], ["author", "datePublished", "dateModified", "image", "publisher"]),
    "BlogPosting": (["headline"], ["author", "datePublished", "dateModified", "image"]),
    "NewsArticle": (["headline"], ["author", "datePublished", "image"]),
    "Product": (["name"], ["offers", "image", "description", "brand", "aggregateRating", "review", "sku"]),
    "Offer": (["price", "priceCurrency"], ["availability", "url"]),
    "BreadcrumbList": (["itemListElement"], []),
    "FAQPage": (["mainEntity"], []),
    "WebSite": (["name", "url"], ["potentialAction"]),
    "WebPage": (["name"], ["description"]),
    "Event": (["name", "startDate", "location"], ["endDate", "offers", "image", "eventStatus"]),
    "Recipe": (["name", "image"], ["recipeIngredient", "recipeInstructions", "author"]),
    "JobPosting": (["title", "description", "datePosted", "hiringOrganization"], ["validThrough", "jobLocation"]),
    "VideoObject": (["name", "thumbnailUrl", "uploadDate"], ["description", "duration", "contentUrl"]),
    "Review": (["itemReviewed", "author"], ["reviewRating"]),
    "Person": (["name"], ["sameAs", "jobTitle", "url"]),
    "Service": (["name"], ["provider", "areaServed", "description"]),
    "Course": (["name", "description"], ["provider"]),
    "SoftwareApplication": (["name"], ["offers", "aggregateRating", "operatingSystem", "applicationCategory"]),
}
LOCAL_SUBTYPES = ("Restaurant", "Dentist", "MedicalClinic", "LegalService", "Store", "AutoRepair",
                  "RealEstateAgent", "HomeAndConstructionBusiness", "ProfessionalService", "HealthClub",
                  "Hotel", "Plumber", "Electrician", "Attorney", "Physician")
DEPRECATED_SCHEMA = {
    "HowTo": "HowTo rich results were retired by Google in 2023; keep only if useful for other consumers.",
    "SpecialAnnouncement": "SpecialAnnouncement is deprecated.",
    "ClaimReview": "ClaimReview rich results were phased out in 2025.",
}


def _types(item: dict) -> list[str]:
    t = item.get("@type", [])
    return [x.rsplit("/", 1)[-1] for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)]


def validate_schema_item(item: dict) -> list[str]:
    problems = []
    if "@context" not in item and "@id" not in item:
        problems.append("missing @context")
    for t in _types(item):
        key = "LocalBusiness" if t in LOCAL_SUBTYPES else t
        if key in DEPRECATED_SCHEMA:
            problems.append(f"{t}: {DEPRECATED_SCHEMA[key]}")
        rule = SCHEMA_RULES.get(key)
        if not rule:
            continue
        required, recommended = rule
        for prop in required:
            if not item.get(prop):
                problems.append(f"{t}: missing required '{prop}'")
        for prop in recommended:
            if prop not in item:
                problems.append(f"{t}: missing recommended '{prop}'")
        if key == "Product" and not any(k in item for k in ("offers", "review", "aggregateRating")):
            problems.append("Product: needs one of offers, review or aggregateRating for rich results")
        if key == "Product" and isinstance(item.get("offers"), dict):
            problems.extend("Offer: " + p.split(": ", 1)[-1] for p in validate_schema_item(
                {"@context": "x", **item["offers"], "@type": item["offers"].get("@type", "Offer")}) if "required" in p)
    return problems


def suggest_schema_type(page: dict) -> str:
    path = urlparse(page["url"]).path.lower()
    text = (page.get("title") or "").lower() + " " + path
    if path in ("", "/"):
        return "Organization + WebSite (with SearchAction)"
    if re.search(r"/(blog|news|article|post|insights|guides?)/", path) or page.get("dates", {}).get("published"):
        return "Article / BlogPosting + BreadcrumbList + Person (author)"
    if re.search(r"/(product|shop|item|p)/", path) or any(c["text"].lower().startswith("add to cart") for c in page.get("ctas", [])):
        return "Product + Offer + AggregateRating + BreadcrumbList"
    if re.search(r"contact|location|store|branch|near", text) or page.get("tel_links"):
        return "LocalBusiness (most specific subtype) + PostalAddress + OpeningHoursSpecification"
    if re.search(r"service|solution", text):
        return "Service + Organization (provider) + BreadcrumbList"
    if re.search(r"event|webinar", text):
        return "Event"
    if re.search(r"job|career", text):
        return "JobPosting"
    if re.search(r"about|team", text):
        return "AboutPage + Organization / Person"
    if len(page.get("question_headings", [])) >= 3:
        return "WebPage + BreadcrumbList (FAQPage rich results are limited to gov/health sites)"
    return "WebPage + BreadcrumbList"


def _tokens(url: str) -> set[str]:
    return {t for t in re.split(r"[/\-_.?=&]+", urlparse(url).path.lower()) if t and t not in ("html", "php", "www")}


def suggest_redirect_target(broken: str, live: list[str]) -> tuple[str | None, float]:
    """Best 301 target for a dead URL by path-token overlap, then string similarity."""
    btok = _tokens(broken)
    best, best_score = None, 0.0
    bpath = urlparse(broken).path
    for cand in live:
        ctok = _tokens(cand)
        jacc = len(btok & ctok) / len(btok | ctok) if btok | ctok else 0
        sim = SequenceMatcher(None, bpath, urlparse(cand).path).ratio()
        score = 0.65 * jacc + 0.35 * sim
        if score > best_score:
            best, best_score = cand, score
    if best_score < 0.35:
        # Fall back to the closest parent folder that is live, then home.
        parts = bpath.rstrip("/").split("/")
        while len(parts) > 1:
            parts.pop()
            parent = "/".join(parts) + "/"
            for cand in live:
                if urlparse(cand).path in (parent, parent.rstrip("/")):
                    return cand, 0.3
        home = [c for c in live if urlparse(c).path in ("", "/")]
        return (home[0] if home else None), 0.1
    return best, round(best_score, 2)


def analyze(crawl) -> dict:
    pages = crawl.pages
    ok = html_pages(pages)
    issues: list[dict] = []
    live_urls = [p["url"] for p in ok if indexable(p)]

    # ---------- Status codes, 404s, broken links ----------
    status_counts = defaultdict(int)
    for p in pages.values():
        s = p.get("status")
        bucket = "error" if s is None else f"{s // 100}xx"
        status_counts[bucket] += 1
    not_found = [p for p in pages.values() if p.get("status") in (404, 410)]
    server_err = [p["url"] for p in pages.values() if p.get("status") and p["status"] >= 500]
    other_4xx = [p["url"] for p in pages.values() if p.get("status") and 400 <= p["status"] < 500 and p["status"] not in (404, 410)]
    broken_links = []  # (source, target, status, anchor)
    all_status = {u: p.get("status") for u, p in pages.items()}
    all_status.update({u: v["status"] for u, v in crawl.link_status.items()})
    for p in ok:
        for link in p.get("internal_links", []) + p.get("external_links", []):
            st = all_status.get(link["href"])
            if st is not None and st >= 400 and st not in (401, 403, 429, 999):
                broken_links.append({"source": p["url"], "target": link["href"], "status": st,
                                     "anchor": link["text"], "internal": link in p.get("internal_links", [])})
    redirects_301 = []
    for p in not_found:
        target, conf = suggest_redirect_target(p["url"], live_urls)
        refs = sorted({b["source"] for b in broken_links if b["target"] == p["url"]})
        redirects_301.append({"from": p["url"], "to": target, "confidence": conf, "status": p["status"],
                              "linked_from": refs[:20]})
    for u, v in crawl.link_status.items():
        if v["status"] in (404, 410) and _same(u, crawl.origin) and u not in pages:
            target, conf = suggest_redirect_target(u, live_urls)
            redirects_301.append({"from": u, "to": target, "confidence": conf, "status": v["status"],
                                  "linked_from": sorted({b["source"] for b in broken_links if b["target"] == u})[:20]})
    if redirects_301:
        issues.append(issue("pages_404", "Status codes", "critical", "Pages returning 404 / 410",
                            f"{len(redirects_301)} internal URLs return 404/410. Links and any backlinks to them are wasted.",
                            "301-redirect each dead URL to the closest live equivalent (see the 301 suggestions table), then update internal links to point straight at the target.",
                            [r["from"] for r in redirects_301], impact=8, effort=2, details=redirects_301))
    if server_err:
        issues.append(issue("pages_5xx", "Status codes", "critical", "Server errors (5xx)",
                            "Pages fail with a server error, so Googlebot cannot index them and may slow its crawl rate.",
                            "Check server logs for these URLs, fix the application error, and monitor uptime.", server_err, impact=9, effort=4))
    if other_4xx:
        issues.append(issue("pages_4xx", "Status codes", "high", "Other 4xx responses",
                            "Pages return client errors other than 404 (e.g. 401/403).",
                            "Make public pages return 200, or remove internal links to restricted URLs.", other_4xx, impact=5, effort=2))
    int_broken = [b for b in broken_links if b["internal"]]
    ext_broken = [b for b in broken_links if not b["internal"]]
    if int_broken:
        issues.append(issue("broken_internal_links", "Links", "high", "Broken internal links",
                            f"{len(int_broken)} internal links point at error pages.",
                            "Update each link to a live URL (or the 301 target). The details list each source and broken target.",
                            [b["source"] for b in int_broken], impact=7, effort=2, details=int_broken))
    if ext_broken:
        issues.append(issue("broken_external_links", "Links", "medium", "Broken outbound links",
                            f"{len(ext_broken)} outbound links return errors, which hurts trust and user experience.",
                            "Replace them with working sources or remove them.", [b["source"] for b in ext_broken], impact=4, effort=2, details=ext_broken))

    # ---------- Redirects ----------
    chains = [p for p in pages.values() if len(p.get("redirect_chain") or []) > 1]
    temp = [p for p in pages.values() if any(s in (302, 303, 307) for _, s in p.get("redirect_chain") or [])]
    links_to_redirects = []
    redirected = {u for u, p in pages.items() if p.get("redirect_chain")}
    redirected |= {u for u, v in crawl.link_status.items() if v.get("redirect_to")}
    for p in ok:
        for link in p.get("internal_links", []):
            if link["href"] in redirected:
                tgt = pages.get(link["href"], {}).get("final_url") or crawl.link_status.get(link["href"], {}).get("redirect_to")
                links_to_redirects.append({"source": p["url"], "target": link["href"], "final": tgt, "anchor": link["text"]})
    if chains:
        issues.append(issue("redirect_chains", "Redirects", "medium", "Redirect chains",
                            "Some URLs redirect more than once before reaching the final page, which wastes crawl budget and dilutes signals.",
                            "Point each first hop straight at the final destination with one 301.",
                            [p["url"] for p in chains], impact=4, effort=2,
                            details=[{"url": p["url"], "chain": p["redirect_chain"], "final": p["final_url"]} for p in chains]))
    if temp:
        issues.append(issue("temporary_redirects", "Redirects", "medium", "Temporary (302/307) redirects",
                            "Temporary redirects suggest a move will be reversed, so search engines may keep the old URL indexed.",
                            "Use 301 (or 308) for permanent moves.", [p["url"] for p in temp], impact=4, effort=1))
    if links_to_redirects:
        issues.append(issue("links_to_redirects", "Redirects", "low", "Internal links pointing at redirects",
                            f"{len(links_to_redirects)} internal links go through a redirect.",
                            "Change the href to the final URL so users and crawlers skip the hop.",
                            [x["source"] for x in links_to_redirects], impact=3, effort=2, details=links_to_redirects))
    start = crawl.start_url
    if start.startswith("http://") and crawl.origin.startswith("http://"):
        issues.append(issue("no_https", "Security", "critical", "Site not served over HTTPS",
                            "HTTPS is a ranking signal, and browsers mark HTTP pages as 'Not secure'.",
                            "Install a TLS certificate, 301 all HTTP URLs to HTTPS, and add HSTS.", [start], impact=9, effort=4))

    # ---------- Indexability ----------
    noindex = [p for p in ok if "noindex" in f"{p.get('meta_robots', '')} {p.get('x_robots_tag', '')}".lower()]
    if noindex:
        issues.append(issue("noindex_pages", "Indexability", "high", "Pages with a noindex directive",
                            "These pages ask search engines not to index them. Check this is intended.",
                            "Remove noindex from pages that should rank; keep it on thank-you, cart, account and internal-search pages.",
                            [p["url"] for p in noindex], impact=7, effort=1,
                            details=[{"url": p["url"], "meta_robots": p.get("meta_robots"), "x_robots_tag": p.get("x_robots_tag")} for p in noindex]))
    sm_urls = set(crawl.sitemaps.get("urls", []))
    noindex_in_sm = [p["url"] for p in noindex if p["url"] in sm_urls]
    if noindex_in_sm:
        issues.append(issue("noindex_in_sitemap", "Sitemaps", "high", "Noindex pages listed in the sitemap",
                            "The sitemap asks for indexing while the page says noindex. That is a mixed signal.",
                            "Remove noindex pages from the XML sitemap (or remove the noindex).", noindex_in_sm, impact=5, effort=1))
    blocked = [p["url"] for p in pages.values() if p.get("blocked_by_robots")]
    if blocked:
        issues.append(issue("blocked_robots", "Indexability", "high", "Pages blocked by robots.txt",
                            "Googlebot cannot crawl these URLs, so their content cannot be evaluated.",
                            "Unblock pages that should rank. Use noindex rather than Disallow to keep pages out of the index.",
                            blocked, impact=6, effort=1))
    missing_canon = [p["url"] for p in ok if not p.get("canonical")]
    canon_other, canon_bad = [], []
    for p in ok:
        c = p.get("canonical")
        if not c or c.rstrip("/") == p["url"].rstrip("/"):
            continue
        canon_other.append({"url": p["url"], "canonical": c})
        st = all_status.get(c)
        if st is not None and st != 200:
            canon_bad.append({"url": p["url"], "canonical": c, "status": st})
        elif not _same(c, crawl.origin):
            canon_bad.append({"url": p["url"], "canonical": c, "status": "cross-domain"})
    if missing_canon:
        issues.append(issue("missing_canonical", "Indexability", "medium", "Missing canonical tag",
                            "Without a self-referencing canonical, parameter and duplicate variants can split ranking signals.",
                            "Add <link rel=\"canonical\" href=\"…\"> pointing to the preferred absolute URL on every indexable page.",
                            missing_canon, impact=5, effort=2))
    if canon_other:
        issues.append(issue("canonicalized", "Indexability", "low", "Pages canonicalized to another URL",
                            "These pages point their canonical at a different URL, so they will not rank themselves.",
                            "Confirm each one is a true duplicate. Otherwise make the canonical self-referencing.",
                            [x["url"] for x in canon_other], impact=3, effort=1, details=canon_other))
    if canon_bad:
        issues.append(issue("canonical_errors", "Indexability", "high", "Canonical points to a redirect, error or other domain",
                            "Search engines ignore canonicals that point at a non-200 or off-site URL.",
                            "Point canonicals at the final 200 URL on the same site.", [x["url"] for x in canon_bad], impact=6, effort=1, details=canon_bad))

    # Duplicate URLs: identical content, parameter variants, case/slash variants
    by_hash = defaultdict(list)
    for p in ok:
        if p.get("text_hash") and p.get("word_count", 0) > 30:
            by_hash[p["text_hash"]].append(p["url"])
    dup_groups = [g for g in by_hash.values() if len(g) > 1]
    if dup_groups:
        issues.append(issue("duplicate_urls", "Indexability", "high", "Duplicate URLs (identical content)",
                            f"{len(dup_groups)} groups of URLs serve the same content.",
                            "Choose one preferred URL per group: 301 the others to it, or canonicalize them to it, and link only to the preferred one.",
                            [u for g in dup_groups for u in g], impact=6, effort=2, details=[{"urls": g} for g in dup_groups]))
    norm_groups = defaultdict(list)
    for u in pages:
        pr = urlparse(u)
        norm_groups[(pr.netloc.replace("www.", ""), pr.path.lower().rstrip("/"))].append(u)
    variants = [g for g in norm_groups.values() if len(g) > 1]
    if variants:
        issues.append(issue("url_variants", "Indexability", "medium", "URL variants (case / trailing slash / www / parameters)",
                            "The same path is reachable under several URL forms.",
                            "Pick one form, 301 the rest to it, and keep internal links consistent.",
                            [u for g in variants for u in g], impact=4, effort=2, details=[{"urls": g} for g in variants]))
    param_urls = [u for u in pages if urlparse(u).query]
    tracking_params = [u for u in param_urls if re.search(r"(utm_|gclid|fbclid|sessionid|sid=)", urlparse(u).query, re.I)]
    if tracking_params:
        issues.append(issue("tracking_params", "Indexability", "medium", "Crawlable URLs with tracking/session parameters",
                            "Internal links carry tracking or session parameters, creating duplicate URLs.",
                            "Remove UTM and session parameters from internal links and canonicalize parameter URLs.",
                            tracking_params, impact=4, effort=2))

    # ---------- Titles & meta ----------
    titles = defaultdict(list)
    descs = defaultdict(list)
    no_title, long_title, short_title, no_desc, long_desc, short_desc = [], [], [], [], [], []
    for p in ok:
        t = (p.get("title") or "").strip()
        d = (p.get("meta_description") or "").strip()
        if not t:
            no_title.append(p["url"])
        else:
            titles[t.lower()].append(p["url"])
            if len(t) > 60:
                long_title.append(p["url"])
            elif len(t) < 30:
                short_title.append(p["url"])
        if not d:
            no_desc.append(p["url"])
        else:
            descs[d.lower()].append(p["url"])
            if len(d) > 160:
                long_desc.append(p["url"])
            elif len(d) < 70:
                short_desc.append(p["url"])
    dup_titles = [g for g in titles.values() if len(g) > 1]
    dup_descs = [g for g in descs.values() if len(g) > 1]
    for cond, args in (
        (no_title, ("missing_title", "On-page", "critical", "Missing <title>", "Pages without a title tag. The title is the strongest on-page relevance signal and the SERP headline.",
                    "Write a unique 50–60 character title with the primary keyword near the start and the brand at the end.", no_title, 9, 1)),
        ([u for g in dup_titles for u in g], ("duplicate_title", "On-page", "high", "Duplicate titles", f"{len(dup_titles)} title texts are shared by several pages, which invites keyword cannibalization.",
                    "Give each page a unique title that reflects its specific intent.", [u for g in dup_titles for u in g], 6, 2)),
        (long_title, ("long_title", "On-page", "low", "Titles longer than 60 characters", "Long titles get truncated in search results.",
                      "Shorten to about 60 characters (580 px) and keep the key terms first.", long_title, 3, 1)),
        (short_title, ("short_title", "On-page", "medium", "Titles shorter than 30 characters", "Short titles miss keyword and click-through opportunities.",
                       "Expand them with the primary keyword plus a qualifier (benefit, location, year or brand).", short_title, 4, 1)),
        (no_desc, ("missing_meta_description", "On-page", "high", "Missing meta description", "Without one, Google picks a snippet itself, often a poor one.",
                   "Write a 140–155 character description: primary keyword, value proposition and a call to action.", no_desc, 5, 1)),
        ([u for g in dup_descs for u in g], ("duplicate_meta_description", "On-page", "medium", "Duplicate meta descriptions", "Several pages share a description.",
                    "Write a unique description for each page.", [u for g in dup_descs for u in g], 4, 2)),
        (long_desc, ("long_meta_description", "On-page", "low", "Meta descriptions over 160 characters", "They get truncated in the SERP.",
                     "Trim to about 155 characters.", long_desc, 2, 1)),
        (short_desc, ("short_meta_description", "On-page", "low", "Meta descriptions under 70 characters", "Short descriptions waste SERP space.",
                      "Expand to 140–155 characters with benefits and a call to action.", short_desc, 2, 1)),
    ):
        if cond:
            i, c, s, t, d, r, u, im, ef = args
            issues.append(issue(i, c, s, t, d, r, u, impact=im, effort=ef))

    no_h1 = [p["url"] for p in ok if not p.get("h1")]
    multi_h1 = [p["url"] for p in ok if len(p.get("h1", [])) > 1]
    skips = []
    for p in ok:
        prev = 0
        for h in p.get("headings", []):
            if prev and h["level"] > prev + 1:
                skips.append(p["url"])
                break
            prev = h["level"]
    if no_h1:
        issues.append(issue("missing_h1", "Content structure", "high", "Missing H1", "Pages without an H1 lack a clear topical headline.",
                            "Add one descriptive H1 that contains the primary keyword.", no_h1, impact=6, effort=1))
    if multi_h1:
        issues.append(issue("multiple_h1", "Content structure", "low", "Multiple H1 tags", "Several H1s blur the page's main topic.",
                            "Keep one H1 and turn the rest into H2s.", multi_h1, impact=2, effort=1))
    if skips:
        issues.append(issue("heading_skips", "Content structure", "low", "Skipped heading levels", "Heading levels jump (e.g. H2 to H4), which weakens the document outline for crawlers and screen readers.",
                            "Use sequential heading levels that mirror the content hierarchy.", skips, impact=2, effort=2))
    no_og = [p["url"] for p in ok if not p.get("og", {}).get("og:title") or not p.get("og", {}).get("og:image")]
    if no_og:
        issues.append(issue("missing_open_graph", "On-page", "low", "Missing Open Graph tags", "Social and chat shares show no preview image or title.",
                            "Add og:title, og:description, og:image (1200×630) and og:url.", no_og, impact=2, effort=1))
    no_lang = [p["url"] for p in ok if not p.get("lang")]
    if no_lang:
        issues.append(issue("missing_lang", "International", "low", "Missing html lang attribute", "Language detection and accessibility suffer.",
                            "Set <html lang=\"en\"> (or the correct locale) on every page.", no_lang, impact=2, effort=1))
    hreflang_issues = []
    for p in ok:
        langs = [h["lang"].lower() for h in p.get("hreflang", [])]
        if langs and p["url"] not in [h["href"] for h in p["hreflang"]]:
            hreflang_issues.append(p["url"])
        if langs and "x-default" not in langs:
            hreflang_issues.append(p["url"])
    if hreflang_issues:
        issues.append(issue("hreflang", "International", "medium", "Incomplete hreflang annotations", "The hreflang sets lack a self-reference or x-default.",
                            "Make every hreflang cluster self-referencing and reciprocal, and include x-default.", hreflang_issues, impact=4, effort=3))

    # ---------- Images ----------
    no_alt, no_dims, legacy = [], [], []
    for p in ok:
        imgs = p.get("images", [])
        if any(i.get("alt") is None for i in imgs):
            no_alt.append(p["url"])
        if any(not i.get("has_dims") for i in imgs):
            no_dims.append(p["url"])
        if imgs and not p.get("picture_tags") and sum(1 for i in imgs if not i["modern"] and i["src"]) > 3:
            legacy.append(p["url"])
    if no_alt:
        issues.append(issue("img_no_alt", "Images", "medium", "Images without alt text", "Alt text gives Google Images and screen readers context.",
                            "Add descriptive alt text to informative images, and alt=\"\" to decorative ones.", no_alt, impact=3, effort=2))
    if no_dims:
        issues.append(issue("img_no_dims", "Performance", "medium", "Images without width/height", "Missing dimensions cause layout shift (CLS).",
                            "Set width and height attributes, or a CSS aspect-ratio, on every image.", no_dims, impact=4, effort=2))
    if legacy:
        issues.append(issue("img_legacy_format", "Performance", "low", "Images not in WebP/AVIF", "Legacy formats inflate page weight and slow LCP.",
                            "Serve WebP or AVIF through <picture> or your CDN's automatic format conversion.", legacy, impact=3, effort=3))

    # ---------- robots.txt / sitemaps / llms.txt ----------
    robots = crawl.robots
    if not robots.get("exists"):
        issues.append(issue("robots_missing", "Crawlability", "medium", "robots.txt missing", "There is no robots.txt to guide crawlers or declare your sitemap.",
                            "Create /robots.txt with crawl rules and a Sitemap: line.", [robots.get("url")], impact=4, effort=1))
    else:
        if robots.get("disallow_all"):
            issues.append(issue("robots_disallow_all", "Crawlability", "critical", "robots.txt blocks Googlebot from the whole site",
                                "Disallow: / prevents crawling of every page.", "Remove the site-wide Disallow unless this is a staging site.",
                                [robots["url"]], impact=10, effort=1))
        if not robots.get("sitemaps"):
            issues.append(issue("robots_no_sitemap", "Sitemaps", "low", "robots.txt does not declare a sitemap", "A Sitemap: directive speeds discovery for every search engine.",
                                "Add 'Sitemap: https://yourdomain/sitemap.xml' to robots.txt.", [robots["url"]], impact=2, effort=1))
        blocked_ai = [b for b, v in robots.get("ai_crawlers", {}).items() if v == "blocked"]
        if blocked_ai:
            issues.append(issue("ai_crawlers_blocked", "AI search", "medium", "AI search crawlers blocked",
                                f"robots.txt blocks: {', '.join(blocked_ai)}. Blocking search-type bots (OAI-SearchBot, PerplexityBot, Claude-SearchBot) removes you from AI answers.",
                                "Allow the AI search and retrieval bots you want citations from. Blocking only training bots (GPTBot, CCBot, Google-Extended) is a business decision.",
                                [robots["url"]], impact=5, effort=1, details=[{"bot": b} for b in blocked_ai]))
    sm = crawl.sitemaps
    if not sm.get("found"):
        issues.append(issue("sitemap_missing", "Sitemaps", "high", "No XML sitemap found",
                            "No valid sitemap at robots.txt, /sitemap.xml or /sitemap_index.xml.",
                            "Generate an XML sitemap of every indexable 200 URL, submit it in Search Console, and reference it in robots.txt.",
                            [crawl.origin + "/sitemap.xml"], impact=6, effort=2))
    else:
        bad_sm = [u for u in sm_urls if u in pages and (pages[u].get("status") != 200 or pages[u].get("redirect_chain"))]
        if bad_sm:
            issues.append(issue("sitemap_non200", "Sitemaps", "medium", "Sitemap lists non-200 or redirected URLs", "Sitemaps should contain only final, indexable URLs.",
                                "Remove redirected, 404 and noindex URLs from the sitemap; regenerate it automatically.", bad_sm, impact=4, effort=1))
        missing_from_sm = [p["url"] for p in ok if indexable(p) and p["url"] not in sm_urls]
        if missing_from_sm and len(sm_urls) > 0:
            issues.append(issue("not_in_sitemap", "Sitemaps", "low", "Indexable pages missing from the sitemap", "These crawlable pages are not listed in any sitemap.",
                                "Add every canonical, indexable URL to the sitemap.", missing_from_sm, impact=3, effort=1))
        for msg in sm.get("issues", []):
            issues.append(issue("sitemap_size", "Sitemaps", "medium", "Oversized sitemap", msg, "Split it into several sitemaps under 50,000 URLs / 50 MB, linked from a sitemap index.", [], impact=3, effort=2))
    llms = crawl.llms_txt.get("llms.txt", {})
    if not llms.get("exists"):
        issues.append(issue("llms_missing", "AI search", "low", "No llms.txt", "An llms.txt file gives LLM agents a curated map of your key content. It is an emerging convention, not a ranking factor.",
                            "Publish /llms.txt: an H1 with the brand, a '>' summary, then '##' sections linking your most important pages with one-line descriptions.",
                            [crawl.origin + "/llms.txt"], impact=2, effort=1))
    elif not (llms.get("has_h1") and llms.get("links")):
        issues.append(issue("llms_format", "AI search", "low", "llms.txt does not follow the format", "The file lacks an H1 title or Markdown links.",
                            "Follow the llmstxt.org format: an H1, a '>' summary, and '##' sections of [Title](url): description links.", [crawl.origin + "/llms.txt"], impact=1, effort=1))

    # ---------- HTTPS / security ----------
    mixed = [p["url"] for p in ok if p.get("mixed_content")]
    if mixed:
        issues.append(issue("mixed_content", "Security", "high", "Mixed content on HTTPS pages", "HTTP resources on HTTPS pages get blocked or trigger browser warnings.",
                            "Load every resource over HTTPS (protocol-relative or absolute https://). Consider adding CSP upgrade-insecure-requests.", mixed, impact=6, effort=2,
                            details=[{"url": p["url"], "resources": p["mixed_content"][:10]} for p in ok if p.get("mixed_content")]))
    home = pages.get(crawl.origin + "/") or (ok[0] if ok else None)
    if home and crawl.origin.startswith("https"):
        sh = home.get("security_headers", {})
        missing = [h for h, v in sh.items() if not v]
        if "strict-transport-security" in missing:
            issues.append(issue("no_hsts", "Security", "medium", "HSTS header missing", "Without HSTS, the first visit can be downgraded to HTTP.",
                                "Send 'Strict-Transport-Security: max-age=31536000; includeSubDomains' (add preload once stable).", [home["url"]], impact=3, effort=1))
        other = [h for h in missing if h != "strict-transport-security"]
        if other:
            issues.append(issue("security_headers", "Security", "low", "Missing security headers", f"Missing: {', '.join(other)}.",
                                "Add X-Content-Type-Options: nosniff, a Referrer-Policy, frame protection (CSP frame-ancestors or X-Frame-Options), a Content-Security-Policy and a Permissions-Policy.",
                                [home["url"]], impact=2, effort=2, details=[{"header": h} for h in other]))

    # ---------- Mobile ----------
    no_vp = [p["url"] for p in ok if not p.get("viewport")]
    bad_vp = [p["url"] for p in ok if p.get("viewport") and re.search(r"user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*1(\.0)?\b", p["viewport"], re.I)]
    if no_vp:
        issues.append(issue("no_viewport", "Mobile", "critical", "Missing viewport meta tag", "Without a viewport tag, pages render at desktop width on phones and fail mobile usability.",
                            "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">.", no_vp, impact=9, effort=1))
    if bad_vp:
        issues.append(issue("viewport_zoom", "Mobile", "medium", "Viewport disables zoom", "user-scalable=no or maximum-scale=1 blocks pinch zoom, an accessibility failure.",
                            "Remove user-scalable=no and maximum-scale from the viewport tag.", bad_vp, impact=3, effort=1))
    heavy = [p["url"] for p in ok if p.get("size", 0) > 500_000]
    if heavy:
        issues.append(issue("heavy_html", "Performance", "medium", "HTML larger than 500 KB", "Heavy HTML slows mobile parsing and first render.",
                            "Remove inline data blobs, paginate long lists, and move inline scripts and styles to cached files.", heavy, impact=4, effort=3))

    # ---------- JavaScript rendering ----------
    spa = [p["url"] for p in ok if p.get("spa_shell") or (p.get("word_count", 0) < 80 and p.get("script_count", 0) > 15)]
    if spa:
        issues.append(issue("js_dependent_content", "JavaScript rendering", "high", "Main content missing from the initial HTML",
                            "These pages ship an empty app shell or very little text in the server HTML. Googlebot renders JavaScript in a second, delayed wave, and most AI crawlers do not run JavaScript at all.",
                            "Use server-side rendering or static generation (Next.js SSR/SSG, Nuxt, Angular Universal) so the main content, title, meta, canonical and links are in the raw HTML.",
                            spa, impact=8, effort=6))
    js_links = [p["url"] for p in ok if p.get("script_count", 0) > 0 and not p.get("internal_links")]
    if js_links:
        issues.append(issue("no_html_links", "JavaScript rendering", "high", "No crawlable <a href> links in the HTML",
                            "Navigation built with JavaScript click handlers cannot be followed by crawlers.",
                            "Render navigation as real <a href=\"/path\"> elements in the server HTML.", js_links, impact=7, effort=4))

    # ---------- Server performance ----------
    slow = [p for p in ok if (p.get("elapsed_ms") or 0) > 800]
    if slow:
        issues.append(issue("slow_ttfb", "Performance", "high" if len(slow) > len(ok) / 3 else "medium", "Slow server response (TTFB over 800 ms)",
                            "Slow response times delay every Core Web Vital and reduce crawl rate.",
                            "Add full-page or edge caching (CDN), optimize database queries, and upgrade hosting if necessary.",
                            [p["url"] for p in slow], impact=6, effort=5, details=[{"url": p["url"], "ms": p["elapsed_ms"]} for p in slow]))
    no_comp = [p["url"] for p in ok if not p.get("compression") and p.get("size", 0) > 20000]
    if no_comp:
        issues.append(issue("no_compression", "Performance", "medium", "HTML served without compression", "Responses lack gzip or Brotli compression.",
                            "Enable Brotli or gzip on the server or CDN.", no_comp, impact=4, effort=1))
    many_js = [p["url"] for p in ok if len(p.get("external_scripts", [])) > 25]
    if many_js:
        issues.append(issue("many_scripts", "Performance", "medium", "More than 25 external scripts", "Script-heavy pages hurt INP and LCP on mobile.",
                            "Audit third-party tags, defer non-critical scripts, and load tags through GTM with consent and trigger rules.", many_js, impact=4, effort=4))

    # ---------- Schema ----------
    no_schema = [p for p in ok if indexable(p) and not p.get("schema") and not p.get("microdata_types")]
    schema_problems = []
    type_counts = defaultdict(int)
    for p in ok:
        for item in p.get("schema", []):
            for t in _types(item):
                type_counts[t] += 1
            probs = validate_schema_item(item)
            if probs:
                schema_problems.append({"url": p["url"], "type": ", ".join(_types(item)) or "?", "problems": probs})
        for err in p.get("schema_errors", []):
            schema_problems.append({"url": p["url"], "type": "parse", "problems": [err]})
    if no_schema:
        issues.append(issue("no_structured_data", "Schema", "high" if len(no_schema) > len(ok) / 2 else "medium", "Pages without structured data",
                            f"{len(no_schema)} indexable pages have no JSON-LD or microdata, so they miss rich results and clear entity signals for AI answers.",
                            "Add JSON-LD matching the page type. The details list a suggested type for each page.",
                            [p["url"] for p in no_schema], impact=6, effort=3,
                            details=[{"url": p["url"], "suggested": suggest_schema_type(p)} for p in no_schema]))
    if schema_problems:
        sev = "high" if any("required" in x or "parse" == pr["type"] for pr in schema_problems for x in pr["problems"]) else "low"
        issues.append(issue("schema_validation", "Schema", sev, "Schema markup validation problems",
                            "Structured data has syntax errors or lacks properties Google needs for rich results.",
                            "Fix the listed properties and re-test with Google's Rich Results Test.", [x["url"] for x in schema_problems],
                            impact=5, effort=2, details=schema_problems))
    if "Organization" not in type_counts and "LocalBusiness" not in type_counts and not any(t in type_counts for t in LOCAL_SUBTYPES):
        issues.append(issue("no_org_schema", "Schema", "medium", "No Organization / LocalBusiness entity",
                            "Search engines and LLMs rely on Organization markup with sameAs links to resolve your brand entity.",
                            "Add Organization (or a LocalBusiness subtype) JSON-LD on the home page with name, url, logo, sameAs (social profiles, Wikipedia/Wikidata) and contactPoint.",
                            [crawl.origin + "/"], impact=5, effort=2))

    stats = {
        "status_counts": dict(status_counts),
        "pages_total": len(pages), "pages_ok": len(ok),
        "indexable": sum(1 for p in ok if indexable(p)),
        "avg_response_ms": round(sum(p.get("elapsed_ms") or 0 for p in ok) / len(ok)) if ok else 0,
        "schema_types": dict(sorted(type_counts.items(), key=lambda x: -x[1])),
        "pages_with_schema": sum(1 for p in ok if p.get("schema") or p.get("microdata_types")),
        "redirect_suggestions": redirects_301,
        "broken_links": broken_links,
        "links_to_redirects": links_to_redirects,
        "schema_suggestions": [{"url": p["url"], "suggested": suggest_schema_type(p)} for p in no_schema],
        "schema_problems": schema_problems,
        "frameworks": sorted({f for p in ok for f in p.get("framework_hints", [])}),
    }
    return {"issues": issues, "stats": stats}


def _same(url: str, origin: str) -> bool:
    a = (urlparse(url).hostname or "").removeprefix("www.")
    b = (urlparse(origin).hostname or "").removeprefix("www.")
    return a == b
