"""Breadth-first site crawler built on the repository's SSRF-safe fetch layer.

Every request goes through ``scripts/url_safety.py`` (DNS-pinned, private-IP
refusal). ``url_safety`` is deliberately single-threaded, so all fetches in
this process are serialized behind ``_FETCH_LOCK``; the crawl itself runs in
a background thread so the web UI stays responsive.

Collected per page: status, redirect chain, timing, size, security headers,
X-Robots-Tag, and a rich HTML extraction (meta tags, headings in document
order, links with anchors, images, JSON-LD, forms, CTAs, tel/mailto links,
mixed content, JS-rendering signals, dates, question headings, lists/tables).
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from lxml import etree

from url_safety import (  # noqa: E402  (path set up in package __init__)
    URLSafetyError,
    decode_body,
    read_bounded,
    safe_requests_get,
    safe_requests_head,
)

_FETCH_LOCK = threading.Lock()
MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 30000
MAX_REDIRECTS = 6
TIMEOUT = 20
AI_CRAWLERS = (
    "GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot",
    "PerplexityBot", "Google-Extended", "CCBot", "Applebot-Extended", "Bytespider",
)
SECURITY_HEADERS = (
    "strict-transport-security", "content-security-policy", "x-content-type-options",
    "x-frame-options", "referrer-policy", "permissions-policy",
)
SKIP_EXT = re.compile(
    r"\.(?:jpe?g|png|gif|webp|avif|svg|ico|pdf|zip|gz|rar|7z|mp4|mp3|webm|mov|avi|"
    r"css|js|json|xml|txt|woff2?|ttf|eot|docx?|xlsx?|pptx?|csv)$",
    re.IGNORECASE,
)
CTA_WORDS = re.compile(
    r"\b(get (?:a |your )?(?:quote|started|demo|offer)|book|schedule|contact|call|sign ?up|"
    r"subscribe|register|buy|add to cart|checkout|download|request|try (?:it )?free|"
    r"free trial|start|join|apply|order|enquire|inquire|talk to)\b",
    re.IGNORECASE,
)


@dataclass
class CrawlResult:
    start_url: str
    origin: str
    pages: dict = field(default_factory=dict)          # url -> page dict
    link_status: dict = field(default_factory=dict)    # url -> status (checked, not crawled)
    robots: dict = field(default_factory=dict)
    sitemaps: dict = field(default_factory=dict)
    llms_txt: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)


def normalize_url(url: str) -> str:
    url, _ = urldefrag(url.strip())
    p = urlparse(url)
    scheme = p.scheme.lower()
    netloc = p.netloc.lower()
    if (scheme == "http" and netloc.endswith(":80")) or (scheme == "https" and netloc.endswith(":443")):
        netloc = netloc.rsplit(":", 1)[0]
    path = p.path or "/"
    return urlunparse((scheme, netloc, path, "", p.query, ""))


def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def same_site(url: str, origin: str) -> bool:
    return _host(url) == _host(origin)


def fetch(url: str, method: str = "GET", follow: bool = True, max_bytes: int = MAX_HTML_BYTES) -> dict:
    """Fetch one URL safely, following same-host redirects by hand.

    Returns a dict with status, final_url, chain [(url, status)], headers,
    body (text or None), elapsed_ms, size and error.
    """
    out = {"url": url, "status": None, "final_url": url, "chain": [], "headers": {},
           "body": None, "elapsed_ms": None, "size": 0, "error": None, "truncated": False}
    current = url
    started = time.monotonic()
    for _ in range(MAX_REDIRECTS + 1):
        try:
            with _FETCH_LOCK:
                if method == "HEAD":
                    resp = safe_requests_head(current, timeout=TIMEOUT, allow_redirects=False)
                else:
                    resp = safe_requests_get(current, timeout=TIMEOUT, allow_redirects=False, stream=True)
                status = resp.status_code
                headers = {k.lower(): v for k, v in resp.headers.items()}
                body = None
                if method == "GET" and not (300 <= status < 400):
                    raw, truncated = read_bounded(resp, max_bytes)
                    out["size"] = len(raw)
                    out["truncated"] = truncated
                    ctype = headers.get("content-type", "")
                    if "html" in ctype or "xml" in ctype or "text" in ctype or not ctype:
                        body = decode_body(raw, ctype)
                    else:
                        body = raw  # binary (e.g. gzipped sitemap)
                resp.close()
        except URLSafetyError as exc:
            out["error"] = f"blocked: {exc}"
            break
        except Exception as exc:  # network errors, timeouts, TLS
            out["error"] = f"{type(exc).__name__}: {exc}"[:300]
            break
        if out["elapsed_ms"] is None:
            out["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        out["status"] = status
        out["headers"] = headers
        out["final_url"] = current
        if 300 <= status < 400 and headers.get("location"):
            nxt = normalize_url(urljoin(current, headers["location"]))
            out["chain"].append((current, status))
            if not follow or _host(nxt) != _host(url) or nxt in [c[0] for c in out["chain"]]:
                out["final_url"] = nxt
                if nxt in [c[0] for c in out["chain"]]:
                    out["error"] = "redirect loop"
                break
            current = nxt
            continue
        out["body"] = body
        break
    else:
        out["error"] = "too many redirects"
    return out


def _text_of(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def extract_page(html: str, url: str, headers: dict) -> dict:
    """Extract everything the analyzers need from one HTML document."""
    soup = BeautifulSoup(html, "lxml")
    page: dict = {}
    head_title = soup.find("title")
    page["title"] = _text_of(head_title) if head_title else None
    metas = {}
    for m in soup.find_all("meta"):
        key = (m.get("name") or m.get("property") or m.get("http-equiv") or "").lower().strip()
        if key and key not in metas:
            metas[key] = (m.get("content") or "").strip()
    page["meta_description"] = metas.get("description")
    page["meta_robots"] = metas.get("robots", "")
    page["x_robots_tag"] = headers.get("x-robots-tag", "")
    page["viewport"] = metas.get("viewport")
    page["og"] = {k: v for k, v in metas.items() if k.startswith("og:")}
    page["twitter"] = {k: v for k, v in metas.items() if k.startswith("twitter:")}
    html_tag = soup.find("html")
    page["lang"] = html_tag.get("lang") if html_tag else None
    page["charset"] = bool(soup.find("meta", charset=True)) or "charset" in headers.get("content-type", "")

    canon = None
    hreflang = []
    for link in soup.find_all("link", href=True):
        rel = [r.lower() for r in (link.get("rel") or [])]
        if "canonical" in rel and canon is None:
            canon = normalize_url(urljoin(url, link["href"]))
        if "alternate" in rel and link.get("hreflang"):
            hreflang.append({"lang": link["hreflang"], "href": urljoin(url, link["href"])})
    page["canonical"] = canon
    page["hreflang"] = hreflang

    # Dates (freshness)
    dates = {"published": metas.get("article:published_time"), "modified": metas.get("article:modified_time")}

    # JSON-LD
    schema, schema_errors = [], []
    for s in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        raw = s.string or s.get_text() or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            schema_errors.append(f"Invalid JSON-LD: {str(exc)[:120]}")
            continue
        items = data.get("@graph", [data]) if isinstance(data, dict) else data if isinstance(data, list) else []
        for it in items:
            if isinstance(it, dict):
                schema.append(it)
                dates["published"] = dates["published"] or it.get("datePublished")
                dates["modified"] = dates["modified"] or it.get("dateModified")
    page["schema"] = schema
    page["schema_errors"] = schema_errors
    page["microdata_types"] = sorted({(t.get("itemtype") or "").rsplit("/", 1)[-1]
                                      for t in soup.find_all(itemtype=True)} - {""})
    page["dates"] = dates

    # Scripts / JS-rendering signals before stripping
    scripts = soup.find_all("script")
    page["script_count"] = len(scripts)
    page["external_scripts"] = [urljoin(url, s["src"]) for s in scripts if s.get("src")][:60]
    inline_js = " ".join((s.string or "") for s in scripts if not s.get("src"))
    page["tracking"] = {
        "gtm": bool(re.search(r"googletagmanager\.com/gtm\.js|GTM-[A-Z0-9]+", html)),
        "ga4": bool(re.search(r"gtag\(|G-[A-Z0-9]{6,}", html)),
        "meta_pixel": "fbq(" in html or "connect.facebook.net" in html,
        "linkedin": "snap.licdn.com" in html,
        "hotjar": "hotjar" in html.lower(),
        "clarity": "clarity.ms" in html,
        "datalayer_events": sorted(set(re.findall(r"event['\"]?\s*:\s*['\"]([a-zA-Z0-9_]+)['\"]", inline_js)))[:30],
    }
    root = soup.find(id=re.compile(r"^(root|app|__next|__nuxt|svelte)$"))
    page["spa_shell"] = bool(root and len(_text_of(root)) < 50)
    page["framework_hints"] = [n for n, pat in (
        ("Next.js", "__NEXT_DATA__"), ("Nuxt", "__NUXT__"), ("React", "data-reactroot"),
        ("Angular", "ng-version"), ("Vue", "data-v-"), ("Gatsby", "___gatsby"),
        ("WordPress", "wp-content"), ("Shopify", "cdn.shopify.com"), ("Wix", "wix.com"),
        ("Webflow", "webflow"),
    ) if pat in html]
    page["noscript_text"] = sum(len(_text_of(n)) for n in soup.find_all("noscript"))

    # Mixed content
    mixed = []
    if url.startswith("https://"):
        for tag, attr in (("img", "src"), ("script", "src"), ("link", "href"), ("iframe", "src"),
                          ("source", "src"), ("video", "src"), ("audio", "src")):
            for el in soup.find_all(tag):
                v = el.get(attr) or ""
                if v.startswith("http://"):
                    if tag == "link" and "stylesheet" not in [r.lower() for r in (el.get("rel") or [])]:
                        continue
                    mixed.append(v)
        for form in soup.find_all("form", action=True):
            if form["action"].startswith("http://"):
                mixed.append(form["action"])
    page["mixed_content"] = mixed[:50]

    # Images
    imgs = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        imgs.append({
            "src": urljoin(url, src) if src else "",
            "alt": img.get("alt"),
            "has_dims": bool(img.get("width") and img.get("height")),
            "loading": img.get("loading"),
            "modern": bool(re.search(r"\.(webp|avif)(\?|$)", src, re.I)),
        })
    page["images"] = imgs[:300]
    page["picture_tags"] = len(soup.find_all("picture"))

    # Forms, CTAs, contact links (conversion analysis)
    forms = []
    for f in soup.find_all("form"):
        fields = []
        for inp in f.find_all(["input", "select", "textarea"]):
            t = (inp.get("type") or inp.name or "").lower()
            if t in ("hidden", "submit", "button"):
                continue
            fields.append(t if t not in ("input",) else "text")
        btn = f.find(["button", "input"], attrs={"type": "submit"}) or f.find("button")
        forms.append({
            "id": f.get("id") or "", "action": f.get("action") or "", "method": (f.get("method") or "get").lower(),
            "fields": fields, "submit_text": _text_of(btn)[:60] if btn else "",
            "is_search": bool(f.find("input", attrs={"type": "search"})) or "search" in (f.get("action") or "").lower()
            or "search" in (f.get("role") or "").lower(),
            "has_email": "email" in fields,
        })
    page["forms"] = forms
    page["tel_links"] = len(soup.find_all("a", href=re.compile(r"^tel:", re.I)))
    page["mailto_links"] = len(soup.find_all("a", href=re.compile(r"^mailto:", re.I)))
    page["whatsapp_links"] = len(soup.find_all("a", href=re.compile(r"wa\.me|whatsapp", re.I)))
    ctas = []
    for el in soup.find_all(["a", "button"]):
        txt = _text_of(el)
        if 2 < len(txt) < 50 and CTA_WORDS.search(txt):
            ctas.append({"text": txt, "href": el.get("href") or "", "tag": el.name})
    page["ctas"] = ctas[:40]
    page["downloads"] = [urljoin(url, a["href"]) for a in soup.find_all("a", href=True)
                         if re.search(r"\.(pdf|docx?|xlsx?|zip|pptx?)(\?|$)", a["href"], re.I)][:30]
    page["videos"] = len(soup.find_all("video")) + len(
        [i for i in soup.find_all("iframe", src=True) if re.search(r"youtube|vimeo|wistia", i["src"], re.I)])
    page["chat_widget"] = bool(re.search(r"intercom|drift\.com|tawk\.to|crisp\.chat|zendesk|livechat|hubspot.*conversations", html, re.I))

    # Links (collect before stripping nav/footer so site-wide links count)
    internal, external = [], []
    origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        absu = normalize_url(urljoin(url, href))
        if not absu.startswith(("http://", "https://")):
            continue
        rel = [r.lower() for r in (a.get("rel") or [])]
        in_nav = bool(a.find_parent(["nav", "header", "footer"]))
        anchor = _text_of(a)[:120]
        if not anchor and a.find("img"):
            anchor = (a.find("img").get("alt") or "").strip()[:120]
        item = {"href": absu, "text": anchor, "nofollow": "nofollow" in rel, "nav": in_nav}
        (internal if same_site(absu, origin) else external).append(item)
    page["internal_links"] = internal[:800]
    page["external_links"] = external[:300]

    # Headings in document order (content structure)
    headings = []
    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        t = _text_of(h)
        if t:
            headings.append({"level": int(h.name[1]), "text": t[:200]})
    page["headings"] = headings
    page["h1"] = [h["text"] for h in headings if h["level"] == 1]
    # Text right after each H2/H3: lets the GEO analyzer judge answer blocks.
    sections = []
    for h in soup.find_all(["h2", "h3"])[:40]:
        nxt = h.find_next(["p", "ul", "ol", "table", "dl"])
        if nxt is None:
            continue
        body = _text_of(nxt)
        sections.append({"heading": _text_of(h)[:200], "kind": nxt.name,
                         "words": len(body.split()), "snippet": body[:300]})
    page["sections"] = sections
    page["question_headings"] = [h["text"] for h in headings if h["text"].endswith("?")
                                 or re.match(r"^(what|how|why|when|where|which|who|can|does|is|are|should)\b", h["text"], re.I)]
    page["lists"] = len(soup.find_all(["ul", "ol"]))
    page["tables"] = len(soup.find_all("table"))
    page["iframes"] = len(soup.find_all("iframe"))

    # Visible main text
    for el in soup(["script", "style", "noscript", "template", "svg"]):
        el.decompose()
    full_text = _text_of(soup.body or soup)
    for el in soup(["nav", "header", "footer", "aside", "form"]):
        el.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = _text_of(main)
    page["word_count"] = len(re.findall(r"\b\w+\b", text))
    page["text"] = text[:MAX_TEXT_CHARS]
    page["text_hash"] = hashlib.sha1(re.sub(r"\W+", " ", text.lower()).encode()).hexdigest() if text else None
    paragraphs = [_text_of(p) for p in main.find_all("p")]
    paragraphs = [p for p in paragraphs if len(p) > 20]
    page["paragraphs"] = len(paragraphs)
    page["avg_paragraph_words"] = round(sum(len(p.split()) for p in paragraphs) / len(paragraphs), 1) if paragraphs else 0
    page["first_paragraph"] = paragraphs[0][:400] if paragraphs else ""
    page["text_html_ratio"] = round(len(full_text) / max(len(html), 1) * 100, 1)
    page["author_signals"] = bool(re.search(r"\b(written by|author|reviewed by|by [A-Z][a-z]+ [A-Z][a-z]+)\b", full_text))
    return page


def _parse_robots(origin: str) -> dict:
    res = fetch(f"{origin}/robots.txt", max_bytes=512 * 1024)
    info = {"url": f"{origin}/robots.txt", "status": res["status"], "exists": res["status"] == 200,
            "content": "", "sitemaps": [], "disallow_all": False, "ai_crawlers": {}, "error": res["error"]}
    rp = RobotFileParser()
    if res["status"] == 200 and isinstance(res["body"], str):
        content = res["body"][:200000]
        info["content"] = content[:5000]
        lines = content.splitlines()
        rp.parse(lines)
        info["sitemaps"] = [ln.split(":", 1)[1].strip() for ln in lines if ln.lower().startswith("sitemap:")]
        info["disallow_all"] = not rp.can_fetch("Googlebot", f"{origin}/")
        for bot in AI_CRAWLERS:
            info["ai_crawlers"][bot] = "allowed" if rp.can_fetch(bot, f"{origin}/") else "blocked"
        info["content_signals"] = "content-signal" in content.lower()
    else:
        rp.parse([])
    info["_parser"] = rp
    return info


def _sitemap_urls(origin: str, declared: list[str], limit: int = 5000) -> dict:
    candidates = list(dict.fromkeys(declared + [f"{origin}/sitemap.xml", f"{origin}/sitemap_index.xml"]))
    out = {"checked": [], "urls": [], "lastmod": {}, "issues": []}
    queue = deque(candidates[:10])
    seen = set()
    while queue and len(seen) < 25 and len(out["urls"]) < limit:
        sm = queue.popleft()
        if sm in seen:
            continue
        seen.add(sm)
        res = fetch(sm, max_bytes=50 * 1024 * 1024)
        entry = {"url": sm, "status": res["status"], "type": None, "count": 0, "error": res["error"]}
        body = res["body"]
        if res["status"] == 200 and body:
            raw = body.encode("utf-8") if isinstance(body, str) else body
            if raw[:2] == b"\x1f\x8b":
                try:
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(50 * 1024 * 1024)
                except OSError:
                    entry["error"] = "bad gzip"
            try:
                parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
                root = etree.fromstring(raw.lstrip(), parser)
                tag = etree.QName(root).localname
                ns = {"s": root.nsmap.get(None, "http://www.sitemaps.org/schemas/sitemap/0.9")}
                if tag == "sitemapindex":
                    entry["type"] = "index"
                    for loc in root.findall(".//s:sitemap/s:loc", ns):
                        if loc.text:
                            queue.append(loc.text.strip())
                            entry["count"] += 1
                elif tag == "urlset":
                    entry["type"] = "urlset"
                    for u in root.findall(".//s:url", ns):
                        loc = u.find("s:loc", ns)
                        if loc is None or not loc.text:
                            continue
                        lm = u.find("s:lastmod", ns)
                        nu = normalize_url(loc.text)
                        out["urls"].append(nu)
                        if lm is not None and lm.text:
                            out["lastmod"][nu] = lm.text.strip()
                        entry["count"] += 1
                    if entry["count"] > 50000:
                        out["issues"].append(f"{sm} exceeds 50,000 URLs")
                else:
                    entry["error"] = f"unexpected root <{tag}>"
            except etree.XMLSyntaxError as exc:
                entry["error"] = f"XML error: {str(exc)[:100]}"
        out["checked"].append(entry)
    out["urls"] = list(dict.fromkeys(out["urls"]))[:limit]
    out["found"] = any(c["type"] for c in out["checked"])
    return out


def _check_llms(origin: str) -> dict:
    info = {}
    for path in ("/llms.txt", "/llms-full.txt"):
        res = fetch(f"{origin}{path}", follow=True, max_bytes=2 * 1024 * 1024)
        body = res["body"] if isinstance(res["body"], str) else ""
        ok = res["status"] == 200 and body and "<html" not in body[:500].lower()
        entry = {"status": res["status"], "exists": bool(ok)}
        if ok:
            entry["has_h1"] = bool(re.search(r"^# .+", body, re.M))
            entry["has_summary"] = bool(re.search(r"^> .+", body, re.M))
            entry["sections"] = len(re.findall(r"^## .+", body, re.M))
            entry["links"] = len(re.findall(r"\[[^\]]+\]\([^)]+\)", body))
            entry["size"] = len(body)
            entry["preview"] = body[:1500]
        info[path.strip("/")] = entry
    return info


def crawl(start_url: str, max_pages: int = 150, progress=None, check_external: int = 80) -> CrawlResult:
    """Crawl a site breadth-first from ``start_url`` up to ``max_pages`` HTML pages."""
    start = normalize_url(start_url if "://" in start_url else f"https://{start_url}")
    # Resolve the canonical origin (http->https, apex->www) first.
    probe = fetch(start)
    if probe["status"] is None:
        raise RuntimeError(f"Could not reach {start}: {probe['error']}")
    landing = probe["final_url"] if probe["status"] and probe["status"] < 400 else start
    if probe["chain"] and _host(probe["final_url"]) != _host(start):
        landing = probe["final_url"]
    p = urlparse(landing)
    origin = f"{p.scheme}://{p.netloc}"
    result = CrawlResult(start_url=start, origin=origin)

    def report(msg):
        if progress:
            progress(msg)

    report("Reading robots.txt")
    robots = _parse_robots(origin)
    rp = robots.pop("_parser")
    result.robots = robots
    report("Reading XML sitemaps")
    result.sitemaps = _sitemap_urls(origin, robots.get("sitemaps", []))
    report("Checking llms.txt")
    result.llms_txt = _check_llms(origin)

    queue: deque = deque([(normalize_url(landing), 0, None)])
    if start != normalize_url(landing):
        queue.appendleft((start, 0, None))
    for sm_url in result.sitemaps.get("urls", [])[: max_pages * 2]:
        if same_site(sm_url, origin):
            queue.append((sm_url, 99, "sitemap"))
    seen = {q[0] for q in queue}
    inlinks: dict[str, set] = {}
    crawled = 0
    while queue and crawled < max_pages:
        url, depth, parent = queue.popleft()
        if SKIP_EXT.search(urlparse(url).path):
            continue
        blocked = not rp.can_fetch("Googlebot", url) if robots.get("exists") else False
        res = fetch(url)
        crawled += 1
        if crawled % 5 == 0 or crawled == 1:
            report(f"Crawled {crawled}/{max_pages} pages")
        # A redirected URL is recorded as a redirect (first-hop status), never
        # parsed as content; its destination is queued as its own page.
        status = res["chain"][0][1] if res["chain"] else res["status"]
        page = {
            "url": url, "status": status, "final_url": res["final_url"], "redirect_chain": res["chain"],
            "final_status": res["status"],
            "elapsed_ms": res["elapsed_ms"], "size": res["size"], "error": res["error"], "depth": depth,
            "found_via": parent or "crawl", "blocked_by_robots": blocked,
            "content_type": res["headers"].get("content-type", ""),
            "security_headers": {h: res["headers"].get(h) for h in SECURITY_HEADERS},
            "cache_control": res["headers"].get("cache-control"),
            "compression": res["headers"].get("content-encoding"),
            "server": res["headers"].get("server"),
            "in_sitemap": url in set(result.sitemaps.get("urls", [])),
        }
        is_html = isinstance(res["body"], str) and ("html" in page["content_type"] or "<html" in res["body"][:1000].lower())
        if res["chain"]:
            target = res["final_url"]
            if same_site(target, origin) and target not in seen:
                seen.add(target)
                queue.append((target, depth, url))
        elif res["status"] and res["status"] < 300 and is_html:
            try:
                page.update(extract_page(res["body"], res["final_url"], res["headers"]))
            except Exception as exc:  # malformed HTML should not kill the crawl
                page["error"] = f"parse error: {exc}"[:200]
            for link in page.get("internal_links", []):
                target = link["href"]
                inlinks.setdefault(target, set()).add(url)
                if target not in seen and not SKIP_EXT.search(urlparse(target).path):
                    seen.add(target)
                    queue.append((target, depth + 1 if depth != 99 else 1, url))
        result.pages[url] = page

    # Fix depth for sitemap-only discoveries and record inlinks
    for url, page in result.pages.items():
        page["inlinks"] = sorted(inlinks.get(url, set()) - {url})[:200]
        page["inlink_count"] = len(inlinks.get(url, set()) - {url})
        if page["depth"] == 99:
            page["depth"] = None  # reachable only via sitemap (potential orphan)

    # Check status of internal links we did not crawl (limit) and a sample of externals
    report("Checking link targets")
    pending = [u for u in inlinks if u not in result.pages and not SKIP_EXT.search(urlparse(u).path)][:60]
    externals = []
    for page in result.pages.values():
        for link in page.get("external_links", []):
            if link["href"] not in externals:
                externals.append(link["href"])
    for u in pending + externals[:check_external]:
        res = fetch(u, method="HEAD", follow=False)
        status = res["status"]
        if status in (403, 405, 501) or status is None and not (res["error"] or "").startswith("blocked"):
            res = fetch(u, method="GET", follow=False, max_bytes=65536)
            status = res["status"]
        result.link_status[u] = {"status": status, "error": res["error"],
                                 "redirect_to": res["final_url"] if res["chain"] else None}
    report(f"Crawl finished: {len(result.pages)} pages")
    return result
