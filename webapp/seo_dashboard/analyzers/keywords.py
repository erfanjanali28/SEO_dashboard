"""Keyword extraction, on-page suggestions and niche keyword research.

* ``page_keywords``: weighted 1–3-gram extraction from title, H1, headings,
  URL and body text, which gives each page a primary keyword and secondary
  keywords.
* ``meta_suggestions``: rewritten title and meta description per page, each
  with its source URL and target keyword.
* ``keyword_research``: expands seed terms with Google Autocomplete (when
  reachable), industry modifier templates and question patterns, then
  classifies intent and funnel stage, clusters terms, attaches Search
  Console metrics when synced, and maps each term to an existing target URL
  or flags it as a content gap with a proposed slug.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from urllib.parse import quote_plus, urlparse

import requests

from . import html_pages, indexable

STOP = set("""a about above after again against all also am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has have having he
her here hers herself him himself his how i if in into is it its itself just let me more most my myself no nor not
now of off on once only or other our ours ourselves out over own same she should so some such than that the their
theirs them themselves then there these they this those through to too under until up very was we were what when
where which while who whom why will with you your yours yourself yourselves us get got one two new use used using
via per may might must much many shall would www com http https html php page home click read more learn contact menu
cookie cookies privacy policy terms rights reserved copyright skip content search close open login sign""".split())

INDUSTRY_MODIFIERS = {
    "saas": ["software", "tool", "platform", "pricing", "alternatives", "vs", "integration", "free trial", "for small business", "review", "best", "template", "api"],
    "ecommerce": ["buy", "price", "cheap", "best", "sale", "discount", "online", "free shipping", "review", "near me", "for men", "for women", "size guide"],
    "local": ["near me", "in {location}", "best", "cost", "emergency", "24 hour", "reviews", "open now", "affordable", "licensed", "company"],
    "healthcare": ["symptoms", "treatment", "cost", "near me", "specialist", "clinic", "recovery", "side effects", "insurance", "best doctor"],
    "legal": ["lawyer", "attorney near me", "cost", "free consultation", "how to file", "rights", "settlement", "firm", "in {location}"],
    "real estate": ["for sale", "for rent", "prices", "agent", "market trends", "neighborhoods", "mortgage", "in {location}", "investment"],
    "finance": ["calculator", "rates", "best", "how to", "vs", "requirements", "fees", "compare", "apply", "tax"],
    "education": ["course", "online", "certification", "free", "for beginners", "salary", "degree", "how to learn", "near me"],
    "travel": ["best time to visit", "things to do", "hotels", "itinerary", "cheap flights", "tours", "guide", "packages"],
    "restaurant": ["near me", "menu", "delivery", "best", "reservations", "open now", "catering", "takeout", "in {location}"],
    "home services": ["near me", "cost", "repair", "installation", "emergency", "estimate", "contractor", "replacement", "in {location}"],
    "agency": ["agency", "services", "consultant", "pricing", "case studies", "company", "near me", "strategy", "audit"],
    "publisher": ["news", "guide", "how to", "tips", "ideas", "examples", "explained", "statistics", "trends"],
    "automotive": ["price", "review", "for sale", "near me", "repair", "parts", "vs", "specs", "lease"],
    "fitness": ["workout", "plan", "for beginners", "at home", "near me", "membership", "classes", "benefits"],
    "b2b": ["supplier", "manufacturer", "wholesale", "solutions", "pricing", "case study", "vendor", "services"],
}
QUESTION_PREFIXES = ["what is", "how to", "how much does", "why", "best", "is", "can", "which", "when to", "how does"]
INTENT_PATTERNS = [
    ("transactional", r"\b(buy|price|pricing|cost|cheap|discount|deal|order|hire|book|quote|for sale|coupon|subscribe|trial|shop|near me|delivery)\b"),
    ("commercial", r"\b(best|top|review|reviews|vs|versus|compare|comparison|alternative|alternatives|rated|affordable)\b"),
    ("local", r"\b(near me|in [a-z]+|open now|nearby|local)\b"),
    ("informational", r"\b(what|how|why|when|who|guide|tutorial|tips|ideas|examples|definition|meaning|learn|is|does|can)\b"),
]
AUTOCOMPLETE_URL = "https://suggestqueries.google.com/complete/search?client=firefox&hl={hl}&q={q}"


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zA-ZÀ-ɏ][a-zA-ZÀ-ɏ0-9'\-]+", text.lower()) if len(w) > 1]


def ngrams(text: str, n_max: int = 3) -> Counter:
    words = _words(text)
    c: Counter = Counter()
    for n in range(1, n_max + 1):
        for i in range(len(words) - n + 1):
            gram = words[i:i + n]
            if gram[0] in STOP or gram[-1] in STOP or any(len(g) < 3 for g in (gram[0], gram[-1])):
                continue
            if sum(1 for g in gram if g in STOP) > 1:
                continue
            c[" ".join(gram)] += 1
    return c


def page_keywords(page: dict, top: int = 10) -> list[tuple[str, float]]:
    scores: Counter = Counter()
    fields = [
        (page.get("title") or "", 6.0),
        (" ".join(page.get("h1", [])), 5.0),
        (urlparse(page["url"]).path.replace("-", " ").replace("/", " "), 4.0),
        (" ".join(h["text"] for h in page.get("headings", []) if h["level"] in (2, 3)), 2.0),
        (page.get("meta_description") or "", 2.0),
        (page.get("text", "")[:15000], 0.15),
    ]
    for text, w in fields:
        for gram, cnt in ngrams(text).items():
            bonus = 1.0 + 0.6 * (gram.count(" "))  # prefer multi-word phrases
            scores[gram] += w * min(cnt, 8) * bonus
    # Penalize terms appearing only once anywhere
    out = [(k, round(v, 2)) for k, v in scores.most_common(top * 3) if v >= 3]
    # Drop unigrams contained in a stronger longer phrase
    final = []
    for k, v in out:
        if any(k in f and k != f and fv >= v * 0.6 for f, fv in final):
            continue
        final.append((k, v))
        if len(final) >= top:
            break
    return final


def _brand(crawl) -> str:
    host = (urlparse(crawl.origin).hostname or "").removeprefix("www.")
    home = crawl.pages.get(crawl.origin + "/") or {}
    og_site = (home.get("og") or {}).get("og:site_name")
    if og_site:
        return og_site
    if re.fullmatch(r"[\d.]+|\[?[0-9a-f:]+\]?", host) or host == "localhost":
        title = home.get("title") or host
        return re.split(r"\s[|\-–—:]\s", title)[-1].strip()[:30]
    return host.split(".")[0].replace("-", " ").title()


def _sentences(text: str, limit: int) -> str:
    """Whole sentences up to ``limit`` chars; falls back to a word-boundary cut."""
    out = ""
    for sent in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text).strip()):
        if len(out) + len(sent) + 1 > limit:
            break
        out = f"{out} {sent}".strip()
    return out or _trim(text, limit)


def _trim(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:-–")
    return cut + ("…" if limit > 100 else "")


def meta_suggestions(crawl, kw_map: dict) -> list[dict]:
    brand = _brand(crawl)
    out = []
    for p in html_pages(crawl.pages):
        if not indexable(p):
            continue
        kws = kw_map.get(p["url"], [])
        if not kws:
            continue
        primary = kws[0][0]
        title = (p.get("title") or "").strip()
        desc = (p.get("meta_description") or "").strip()
        reasons = []
        if not title:
            reasons.append("missing title")
        elif len(title) > 60:
            reasons.append(f"title too long ({len(title)} chars)")
        elif len(title) < 30:
            reasons.append(f"title too short ({len(title)} chars)")
        if title and primary not in title.lower():
            reasons.append(f"primary keyword '{primary}' not in title")
        if not desc:
            reasons.append("missing meta description")
        elif not 70 <= len(desc) <= 160:
            reasons.append(f"description length {len(desc)}")
        elif primary.split()[0] not in desc.lower():
            reasons.append("keyword absent from description")
        if not reasons:
            continue
        head = (p.get("h1") or [title or primary])[0]
        base = head if primary in head.lower() else f"{primary.title()}: {head}" if len(head) < 35 else primary.title()
        suffix = f" | {brand}"
        new_title = _trim(base, 60 - len(suffix)) + suffix if len(base) + len(suffix) <= 62 else _trim(base, 60)
        src = p.get("first_paragraph") or desc or " ".join(h["text"] for h in p.get("headings", [])[:3])
        lead = src if primary.split()[0] in src.lower() else f"{primary.capitalize()}: {src}"
        cta = "Get a free quote today." if p.get("forms") or p.get("tel_links") else "Learn more."
        new_desc = _sentences(lead, 155 - len(cta) - 1).rstrip("…").rstrip(".") + ". " + cta
        secondary = [k for k, _ in kws[1:6]]
        out.append({
            "source_url": p["url"], "target_keyword": primary, "secondary_keywords": secondary,
            "current_title": title, "suggested_title": new_title,
            "current_description": desc, "suggested_description": new_desc,
            "current_h1": (p.get("h1") or [""])[0], "reasons": reasons,
        })
    return out


def autocomplete(query: str, hl: str = "en", timeout: int = 6) -> list[str]:
    """Google Autocomplete suggestions. Fixed public endpoint, so a plain request is fine."""
    try:
        r = requests.get(AUTOCOMPLETE_URL.format(hl=hl, q=quote_plus(query)), timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0 ClaudeSEO-Dashboard"})
        if r.status_code == 200:
            data = json.loads(r.text)
            return [s for s in data[1] if isinstance(s, str)][:10]
    except Exception:
        pass
    return []


def classify_intent(kw: str) -> str:
    for name, pat in INTENT_PATTERNS:
        if re.search(pat, kw):
            return name
    return "informational" if len(kw.split()) >= 4 else "commercial"


def funnel_stage(intent: str) -> str:
    return {"informational": "TOFU (awareness)", "commercial": "MOFU (consideration)",
            "transactional": "BOFU (decision)", "local": "BOFU (decision)"}.get(intent, "MOFU (consideration)")


def keyword_research(crawl, site: dict, kw_map: dict, gsc_rows: list[dict] | None = None,
                     live: bool = True, max_seeds: int = 12, provider=None) -> dict:
    """Build a niche keyword universe for the site and map it to pages."""
    industry = (site.get("industry") or "").lower().strip()
    location = (site.get("location") or "").strip()
    hl = site.get("language") or "en"
    seeds = [s.strip().lower() for s in (site.get("seed_keywords") or "").split(",") if s.strip()]
    site_terms = Counter()
    for kws in kw_map.values():
        for k, v in kws[:3]:
            if " " in k:
                site_terms[k] += v
    seeds += [k for k, _ in site_terms.most_common(max_seeds)]
    seeds = list(dict.fromkeys(seeds))[:max_seeds]

    mods = INDUSTRY_MODIFIERS.get(industry) or INDUSTRY_MODIFIERS.get(
        next((k for k in INDUSTRY_MODIFIERS if k in industry), ""), INDUSTRY_MODIFIERS["agency"])
    universe: dict[str, dict] = {}

    def add(kw, seed, source):
        kw = re.sub(r"\s+", " ", kw.lower()).strip()
        if not kw or len(kw) > 80 or kw in universe:
            return
        universe[kw] = {"keyword": kw, "seed": seed, "source": source}

    autocomplete_ok = False
    for seed in seeds:
        add(seed, seed, "seed")
        for m in mods:
            m = m.replace("{location}", location) if "{location}" in m else m
            if "{location}" in m or (m.startswith("in ") and not location):
                continue
            add(f"{seed} {m}" if not m.startswith(("best", "cheap", "affordable")) else f"{m} {seed}", seed, "industry modifier")
        for q in QUESTION_PREFIXES[:6]:
            add(f"{q} {seed}", seed, "question pattern")
        if location:
            add(f"{seed} {location}", seed, "local modifier")
        if live:
            sugg = autocomplete(seed, hl)
            autocomplete_ok = autocomplete_ok or bool(sugg)
            for s in sugg:
                add(s, seed, "google autocomplete")
            if sugg:
                for q in ("how", "best", "vs"):
                    for s in autocomplete(f"{q} {seed}", hl)[:5]:
                        add(s, seed, "google autocomplete")

    # Search Console queries (real demand)
    gsc = defaultdict(lambda: {"clicks": 0.0, "impressions": 0.0, "pos_sum": 0.0, "n": 0, "pages": set()})
    for r in gsc_rows or []:
        q = (r.get("query") or "").lower()
        if not q:
            continue
        g = gsc[q]
        g["clicks"] += r.get("clicks") or 0
        g["impressions"] += r.get("impressions") or 0
        g["pos_sum"] += (r.get("position") or 0) * max(r.get("impressions") or 1, 1)
        g["n"] += max(r.get("impressions") or 1, 1)
        if r.get("page"):
            g["pages"].add(r["page"])
    for q in sorted(gsc, key=lambda x: -gsc[x]["impressions"])[:300]:
        add(q, q.split()[0], "search console")

    volumes = {}
    if provider:
        try:
            volumes = provider(list(universe)[:700]) or {}
        except Exception:
            volumes = {}

    # Map keywords to pages
    page_index = []
    for p in html_pages(crawl.pages):
        if not indexable(p):
            continue
        hay = " ".join([p.get("title") or "", " ".join(p.get("h1", [])), urlparse(p["url"]).path.replace("-", " "),
                        " ".join(k for k, _ in kw_map.get(p["url"], []))]).lower()
        page_index.append((p["url"], set(_words(hay)), hay))

    rows = []
    for kw, item in universe.items():
        toks = {t for t in _words(kw) if t not in STOP}
        best, best_score = None, 0.0
        for url, words, hay in page_index:
            if not toks:
                break
            score = len(toks & words) / len(toks)
            if kw in hay:
                score += 0.5
            if score > best_score:
                best, best_score = url, score
        intent = classify_intent(kw)
        g = gsc.get(kw)
        vol = volumes.get(kw, {})
        row = {
            **item, "intent": intent, "funnel": funnel_stage(intent), "words": len(kw.split()),
            "target_url": best if best_score >= 0.67 else None,
            "match_score": round(best_score, 2),
            "status": "covered" if best_score >= 0.67 else "content gap",
            "suggested_slug": "/" + re.sub(r"[^a-z0-9]+", "-", kw).strip("-") + "/",
            "gsc_clicks": round(g["clicks"]) if g else None,
            "gsc_impressions": round(g["impressions"]) if g else None,
            "gsc_position": round(g["pos_sum"] / g["n"], 1) if g and g["n"] else None,
            "gsc_pages": len(g["pages"]) if g else 0,
            "search_volume": vol.get("search_volume"), "cpc": vol.get("cpc"), "competition": vol.get("competition"),
        }
        if g and g["pages"]:
            row["target_url"] = row["target_url"] or sorted(g["pages"])[0]
            row["status"] = "ranking"
        # Priority: real demand first, then intent value, then long-tail opportunity
        pri = 0.0
        if row["gsc_impressions"]:
            pri += min(row["gsc_impressions"] / 50, 40)
            if row["gsc_position"] and 4 <= row["gsc_position"] <= 20:
                pri += 25  # striking distance
        if row["search_volume"]:
            pri += min(row["search_volume"] / 100, 30)
        pri += {"transactional": 20, "local": 18, "commercial": 15, "informational": 8}[intent]
        pri += 6 if row["source"] == "google autocomplete" else 0
        pri += 4 if 3 <= row["words"] <= 5 else 0
        row["priority"] = round(pri, 1)
        rows.append(row)
    rows.sort(key=lambda r: -r["priority"])

    clusters = defaultdict(list)
    for r in rows:
        clusters[r["seed"]].append(r["keyword"])
    cluster_list = [{"cluster": k, "size": len(v), "keywords": v[:40],
                     "pillar_url": next((r["target_url"] for r in rows if r["seed"] == k and r["target_url"]), None)}
                    for k, v in sorted(clusters.items(), key=lambda x: -len(x[1]))]
    striking = [r for r in rows if r["gsc_position"] and 4 <= r["gsc_position"] <= 20]
    cannibal = [{"keyword": q, "pages": sorted(g["pages"]), "impressions": round(g["impressions"])}
                for q, g in gsc.items() if len(g["pages"]) > 1 and g["impressions"] >= 20]
    return {
        "industry": industry or "general", "seeds": seeds, "autocomplete_used": autocomplete_ok,
        "volume_provider": bool(volumes), "keywords": rows[:800], "clusters": cluster_list,
        "intent_counts": dict(Counter(r["intent"] for r in rows)),
        "status_counts": dict(Counter(r["status"] for r in rows)),
        "striking_distance": striking[:100], "gsc_cannibalization": sorted(cannibal, key=lambda x: -x["impressions"])[:100],
        "questions": [r["keyword"] for r in rows if re.match(r"^(what|how|why|when|which|who|can|is|does|are|should)\b", r["keyword"])][:120],
    }
