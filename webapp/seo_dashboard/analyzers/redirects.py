"""Redirect and canonical suggestions, plus the keyword cannibalization and
keyword stuffing guards that decide between them.

Inputs are things the audit already measured: 404s and the anchors pointing at
them, the internal link suggestions, identical and near-duplicate content,
cannibalized keywords, declared canonicals, and Search Console rows when a site
has them.

The rules below deliberately prefer doing less. A wrong 301 removes a page that
may rank, and a canonical between pages that are not duplicates is ignored by
search engines, so:

* a dead URL with no real equivalent gets a 410, never a redirect to the home page
* the home page is never redirected
* pages with different intent, or little shared text, are differentiated, not merged
* a page that is the primary page for another keyword is not redirected away
* template families (for example city pages) are not collapsed into one URL
* pages in different languages are never consolidated
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from urllib.parse import urlparse

from . import html_pages, indexable, issue
from .content import _shingles
from .conversion import page_type
from .technical import _same, _tokens

GENERIC_TOKENS = {
    "blog", "news", "page", "pages", "category", "categories", "tag", "tags", "product", "products", "service", "services",
    "sluzby", "produkty", "clanky", "clanek", "aktuality", "index", "home", "www", "en", "cs", "cz", "de", "sk", "uk", "html",
}
STOP_WORDS = {"the", "and", "for", "with", "from", "that", "this", "your", "our", "are", "pro", "nebo", "jak", "pri"}
CONF_ORDER = {"high": 0, "medium": 1, "low": 2}
CONSOLIDATE_SIMILARITY = 0.6     # share of text that makes two pages one page
MERGE_SIMILARITY = 0.25          # below this the pages are different content
NEAR_DUPLICATE_REDIRECT = 0.85
TEMPLATE_FAMILY_PAIRS = 3        # a page near-duplicating this many others is a template
LOSER_TRAFFIC_SHARE = 0.3        # a "loser" this close to the winner needs a human decision
DEV_LABEL = re.compile(r"^(dev|develop|development|staging|stage|stg|test|testing|preview|uat|sandbox|demo)\d*$|dev$|staging$", re.I)
LEGAL_PAGE = re.compile(r"privacy|gdpr|cookie|terms|legal|imprint|impressum|osobni|soukromi|podminky", re.I)
LISTING_URL = re.compile(r"/(category|categories|kategorie|kategorii|tag|tags|stitek|stitky|archive|archiv|author|page)(/|$)", re.I)
MAX_LINK_UPDATES = 5000
TYPO_SIMILARITY = 0.85           # URLs this close are almost certainly a typo
MAX_ANCHOR_WORDS = 6             # longer anchors are card text, not targeted anchors
MAX_ANCHOR_RIVALS = 3            # an anchor on more pages than this is a generic label


def _key(url: str) -> str:
    return (url or "").rstrip("/")


def _fold(text: str) -> str:
    """Lowercase and drop diacritics, so 'střechy' matches the slug 'strechy'."""
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _words(text: str) -> set[str]:
    return set(re.findall(r"[^\W\d_]{3,}", _fold(text))) - STOP_WORDS


def _url_words(url: str) -> set[str]:
    return {_fold(t) for t in _tokens(url) if not t.isdigit()} - GENERIC_TOKENS


def _path(url: str) -> str:
    p = urlparse(url or "")
    return (p.path or "/") + (f"?{p.query}" if p.query else "")


def _topic(url: str) -> str:
    return " ".join(sorted(_url_words(url))) or _path(url)


def _is_dev_host(host: str) -> bool:
    return any(DEV_LABEL.search(label) for label in host.split(".")[:-1])


def _host_copies(pages: dict, origin: str) -> tuple[str, dict]:
    """Find a site served in full on two hosts, such as www and non-www.

    Returns the preferred host, chosen by what the pages' canonicals declare, and
    each duplicate host with its count of shared and total paths.
    """
    paths = defaultdict(set)
    for p in html_pages(pages):
        if not p.get("redirect_chain"):
            paths[urlparse(p["url"]).netloc].add(urlparse(p["url"]).path)
    fallback = urlparse(origin).netloc
    votes = Counter(urlparse(p.get("canonical") or "").netloc for p in html_pages(pages))
    declared = [h for h, _ in votes.most_common() if h in paths]
    if declared:
        primary = declared[0]
    elif fallback in paths or not paths:
        primary = fallback
    else:
        primary = max(paths, key=lambda h: len(paths[h]))
    main = paths.get(primary, set())
    copies = {}
    for host, seen in paths.items():
        if host != primary and main and len(seen & main) >= 0.5 * len(seen):
            copies[host] = (len(seen & main), len(seen))
    return primary, copies


def _is_home(url: str) -> bool:
    return urlparse(url).path in ("", "/")


def _lang_of(page: dict) -> str:
    first = (urlparse(page["url"]).path.strip("/").split("/") or [""])[0].lower()
    if re.fullmatch(r"[a-z]{2}(-[a-z]{2})?", first):
        return first[:2]
    return (page.get("lang") or "").lower()[:2]


def _is_listing(page: dict) -> bool:
    """Archive or filter page. These collect links without being the page to rank."""
    return bool(LISTING_URL.search(urlparse(page["url"]).path))


def _same_language(a: dict, b: dict) -> bool:
    la, lb = _lang_of(a), _lang_of(b)
    if la and lb and la != lb:
        return False
    return b["url"] not in str(a.get("hreflang") or "") and a["url"] not in str(b.get("hreflang") or "")


def _similarity(a: dict, b: dict) -> float:
    sa, sb = _shingles(a.get("text", "")), _shingles(b.get("text", ""))
    if not sa or not sb:
        return 0.0
    return round(len(sa & sb) / len(sa | sb), 2)


def _same_slug_other_folder(a: str, b: str) -> bool:
    pa, pb = urlparse(a).path.rstrip("/"), urlparse(b).path.rstrip("/")
    return pa != pb and pa.rsplit("/", 1)[-1] == pb.rsplit("/", 1)[-1]


def _occurrences(text: str, phrase: str) -> int:
    return len(re.findall(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text))


def _rule_path(url: str) -> str | None:
    """Path safe to put in a server rule; None for query strings or odd characters."""
    p = urlparse(url)
    if p.query or re.search(r"[\s\"'<>\\;{}$]", p.path) or not p.path.startswith("/"):
        return None
    return p.path


def server_rules(rows: list[dict]) -> dict:
    """Apache and nginx rules for rows confident enough to deploy after review."""
    apache, nginx, skipped = [], [], 0
    for r in rows:
        if r.get("host_move"):
            old, new = r["host_move"]
            scheme = urlparse(r["to"]).scheme
            apache += [f"# {r['source']}", "RewriteEngine On", "RewriteCond %{HTTP_HOST} ^" + old.replace(".", "\\.") + "$ [NC]",
                       f"RewriteRule ^(.*)$ {scheme}://{new}/$1 [R=301,L]"]
            nginx += [f"# {r['source']}", f"server {{ server_name {old}; return 301 {scheme}://{new}$request_uri; }}"]
            continue
        if r["confidence"] == "low" or r.get("method") == "restore":
            continue
        src, dst = _rule_path(r["from"]), r.get("to")
        if not src or (dst and re.search(r"[\s\"'<>\\;{}$]", dst)):
            skipped += 1
            continue
        note = f"# {r['source']}" + (" (merge the content first)" if r.get("merge_first") else "")
        apache.append(note)
        nginx.append(note)
        if dst:
            apache.append(f"Redirect 301 {src} {dst}")
            nginx.append(f"location = {src} {{ return 301 {dst}; }}")
        else:
            apache.append(f"Redirect gone {src}")
            nginx.append(f"location = {src} {{ return 410; }}")
    return {"apache": "\n".join(apache), "nginx": "\n".join(nginx), "skipped": skipped}


def keyword_stuffing(crawl, kw_map: dict, hidden_hosts=()) -> list[dict]:
    """Repetition of a page's primary keyword in its text, title and inbound anchors.

    Density is not a Google metric. It is a heuristic for spotting copy that
    repeats a phrase far beyond what natural writing does. It reads paragraph
    text only, because on listing pages a keyword can repeat as a filter label or
    card tag without anyone having written it that way.
    """
    out = []
    every = [p for p in html_pages(crawl.pages) if urlparse(p["url"]).netloc not in hidden_hosts]
    for p in (x for x in every if indexable(x)):
        kws = kw_map.get(p["url"], [])
        if not kws:
            continue
        kw = kws[0][0]
        text = (p["prose"] if "prose" in p else p.get("text") or "").lower()
        total = len(text.split())
        if total < 100:
            continue
        hits = _occurrences(text, kw)
        multi_word = " " in kw
        density = round(hits / total * 100, 1)
        if hits >= 6 and density >= (2 if multi_word else 4):
            out.append({"url": p["url"], "keyword": kw, "where": "Body text", "occurrences": hits, "density": density,
                        "severity": "high" if density >= (3.5 if multi_word else 6) else "medium",
                        "recommendation": f"'{kw}' appears {hits} times in {total} words of body text, about once every {total // hits} words. "
                                          f"Bring it down to around {max(3, round(total / 100))} and use {' or '.join(repr(k) for k, _ in kws[1:3]) or 'related terms'} in the other places."})
        # The part after a separator is the brand, which is not a repeat of the keyword.
        title_hits = _occurrences(re.split(r"\s[|\-–—]\s", (p.get("title") or "").lower())[0], kw)
        if title_hits >= 2:
            out.append({"url": p["url"], "keyword": kw, "where": "Title", "occurrences": title_hits, "density": None, "severity": "medium",
                        "recommendation": f"The title '{p.get('title')}' repeats '{kw}' {title_hits} times. Keep one and use the space for a benefit or qualifier."})
    anchors, totals = Counter(), Counter()
    for p in every:
        for link in p.get("internal_links", []):
            if link.get("nav") or not link.get("text"):
                continue
            totals[link["href"]] += 1
            anchors[(link["href"], link["text"].strip().lower())] += 1
    for (target, anchor), n in anchors.items():
        keywords = [k for k, _ in kw_map.get(target, [])]
        # An anchor is only stuffing when it is a keyword. A card repeating the page's name is not.
        if n >= 5 and 1 < len(anchor.split()) <= MAX_ANCHOR_WORDS and anchor in keywords[:6] and n / totals[target] >= 0.6:
            others = [k for k in keywords if k != anchor][:2]
            out.append({"url": target, "keyword": anchor, "where": "Internal anchors", "occurrences": n,
                        "density": round(n / totals[target] * 100, 1), "severity": "medium",
                        "recommendation": f"{n} of the {totals[target]} body links to {_path(target)} use the exact anchor '{anchor}'. "
                                          f"Rewrite some to {' or '.join(repr(k) for k in others) or 'natural phrases'}."})
    return sorted(out, key=lambda r: (r["severity"] != "high", -(r["density"] or 0)))[:500]


def analyze(crawl, kw_map: dict, tech: dict, cont: dict, suggestions: list[dict], gsc: list[dict] | None = None) -> dict:
    pages = crawl.pages
    primary_host, copies = _host_copies(pages, crawl.origin)

    def on_copy(url: str | None) -> bool:
        return urlparse(url or "").netloc in copies

    # A duplicate host gets one host-wide redirect, so its pages are not planned twice.
    tech = {**tech,
            "redirect_suggestions": [r for r in tech.get("redirect_suggestions", []) if not on_copy(r["from"])],
            "broken_links": [b for b in tech.get("broken_links", []) if not on_copy(b["source"]) and not on_copy(b["target"])],
            "links_to_redirects": [x for x in tech.get("links_to_redirects", []) if not on_copy(x["source"])]}
    base_url = f"{urlparse(crawl.origin).scheme}://{primary_host}"
    live = {p["url"]: p for p in html_pages(pages) if not p.get("redirect_chain") and not on_copy(p["url"])}
    by_key = {_key(u): u for u in live}
    open_urls = [u for u, p in live.items() if indexable(p)]
    terms = {u: _words(" ".join([live[u].get("title") or "", " ".join(live[u].get("h1") or []),
                                 " ".join(k for k, _ in kw_map.get(u, [])[:6])])) for u in open_urls}
    url_terms = {u: _url_words(u) for u in open_urls}

    clicks, imps, q_clicks, q_imps = Counter(), Counter(), Counter(), Counter()
    for row in gsc or []:
        k = _key(row.get("page") or "")
        clicks[k] += row.get("clicks") or 0
        imps[k] += row.get("impressions") or 0
        q_clicks[(row.get("query"), k)] += row.get("clicks") or 0
        q_imps[(row.get("query"), k)] += row.get("impressions") or 0
    planned = Counter(s["target_url"] for s in suggestions)

    def value(u: str, kw: str | None = None) -> tuple:
        p, k = live[u], _key(u)
        return (q_clicks[(kw, k)], q_imps[(kw, k)], clicks[k], imps[k], not _is_listing(p), p.get("inlink_count", 0) + planned[u],
                p.get("word_count", 0), -(p.get("depth") if p.get("depth") is not None else 99), -len(u))

    def evidence(u: str) -> str:
        p, k = live[u], _key(u)
        gsc_part = f"{round(clicks[k])} clicks, {round(imps[k])} impressions, " if gsc else ""
        return f"{gsc_part}{p.get('inlink_count', 0)} inlinks, {planned[u]} link suggestions, {p.get('word_count', 0)} words"

    redirects: dict[str, dict] = {}
    canon_plan: dict[str, dict] = {}
    decisions: list[dict] = []
    decided: set[frozenset] = set()
    already_ok = 0

    def add_redirect(row: dict) -> None:
        row.setdefault("keyword", None)
        row.setdefault("merge_first", False)
        redirects.setdefault(row["from"], row)

    # ---------- 404 / 410 URLs ----------
    pairs = {(s["source_url"], s["target_url"]) for s in suggestions}
    broken_by_target = defaultdict(list)
    for b in tech.get("broken_links", []):
        if b.get("internal"):
            broken_by_target[b["target"]].append(b)

    def best_target(dead: str, anchors: set[str], sources: set[str]) -> tuple[str | None, float, list[str]]:
        wanted = _url_words(dead) | anchors
        best, best_score, best_why = None, 0.0, []
        if not wanted:
            return None, 0.0, []
        dead_tokens = _tokens(dead)
        for c in open_urls:
            if _is_home(c):
                continue
            topical = len(wanted & terms[c]) / len(wanted)
            shared = (wanted & (terms[c] | url_terms[c]))
            linked = any((src, c) in pairs for src in sources)
            sim = SequenceMatcher(None, urlparse(dead).path.rstrip("/"), urlparse(c).path.rstrip("/")).ratio()
            if not shared and not linked and sim < TYPO_SIMILARITY:
                continue
            ctok = _tokens(c)
            jacc = len(dead_tokens & ctok) / len(dead_tokens | ctok) if dead_tokens | ctok else 0
            score = 0.45 * (0.65 * jacc + 0.35 * sim) + 0.45 * topical + (0.1 if linked else 0)
            if sim >= TYPO_SIMILARITY:
                score = max(score, 0.6)
            if score > best_score:
                why = [f"shares terms: {', '.join(sorted(shared)[:5])}"] if shared else []
                if linked:
                    why.append("the linking page was already suggested a link to this target")
                best, best_score, best_why = c, score, why
        return best, round(best_score, 2), best_why

    def plan_dead(url: str, status, source: str) -> None:
        links = broken_by_target.get(url, [])
        anchor_words = set().union(*[_words(b.get("anchor") or "") for b in links]) if links else set()
        sources = {b["source"] for b in links}
        target, score, why = best_target(url, anchor_words, sources)
        base = {"from": url, "status": status, "source": source, "score": score, "inlinks": len(sources)}
        topic = _topic(url)
        linked = ("1 page still links here" if len(sources) == 1 else f"{len(sources)} pages still link here") if sources else "No internal links point here"
        if target and score >= 0.25:
            conf = "high" if score >= 0.6 else "medium" if score >= 0.4 else "low"
            typo = SequenceMatcher(None, urlparse(url).path.rstrip("/"), urlparse(target).path.rstrip("/")).ratio() >= TYPO_SIMILARITY
            add_redirect({**base, "to": target, "method": "301", "action": "301 redirect", "confidence": "high" if typo else conf,
                          "reason": f"{_path(url)} is only a few characters from {_path(target)}, so this is very likely a typo. {linked}." if typo else
                          f"Best match for '{topic}' at {round(score * 100)}%" + (f": {'; '.join(why)}" if why else "") + f". {linked}."})
            return
        parts = urlparse(url).path.rstrip("/").split("/")
        while len(parts) > 2:
            parts.pop()
            hub = by_key.get(_key(f"{base_url}{'/'.join(parts)}"))
            if hub and hub in open_urls:
                add_redirect({**base, "to": hub, "method": "301", "action": "301 redirect", "confidence": "low",
                              "reason": f"No page matches '{topic}', so {_path(hub)} is the nearest parent section. Check it serves the same need. {linked}."})
                return
        anchor_text = next((b.get("anchor") for b in links if b.get("anchor")), None)
        said = f"linked as '{anchor_text}'" if anchor_text else "a page visitors expect"
        if LEGAL_PAGE.search(_fold(f"{url} {anchor_text or ''}")):
            add_redirect({**base, "to": None, "method": "restore", "action": "Restore this page", "confidence": "high",
                          "reason": f"{_path(url)} looks like a legal page ({said}) and it returns {status}. Publish it again rather than removing it. {linked}."})
            return
        closest = (f"The closest page, {_path(target)}, is only a {round(score * 100)}% match, too weak to redirect to."
                   if target else f"No live page shares a term with '{topic}'.")
        add_redirect({**base, "to": None, "method": "410", "action": "Return 410 and remove links", "confidence": "medium",
                      "reason": f"{closest} {linked}. A home page redirect would count as a soft 404, so return 410, or restore {_path(url)} if it earned traffic."})

    for r in tech.get("redirect_suggestions", []):
        plan_dead(r["from"], r.get("status"), "404 / 410 error")

    # ---------- Existing redirects: chains, temporary, dead ends ----------
    for p in pages.values():
        chain = p.get("redirect_chain") or []
        if not chain or on_copy(p["url"]):
            continue
        final = p.get("final_url")
        final_status = p.get("final_status")
        hops = [s for _, s in chain]
        if final_status and final_status >= 400:
            plan_dead(p["url"], final_status, "Redirect ends in an error")
        elif len(chain) > 1:
            add_redirect({"from": p["url"], "to": final, "method": "301", "action": "Flatten redirect chain", "confidence": "high", "status": hops[0],
                          "source": "Redirect chain", "score": None, "inlinks": p.get("inlink_count", 0),
                          "reason": f"{_path(p['url'])} takes {len(chain)} hops ({' → '.join(map(str, hops))}) to reach {_path(final)}. Redirect it there directly."})
        elif hops[0] in (302, 303, 307):
            add_redirect({"from": p["url"], "to": final, "method": "301", "action": "Change to 301", "confidence": "medium", "status": hops[0],
                          "source": "Temporary redirect", "score": None, "inlinks": p.get("inlink_count", 0),
                          "reason": f"{_path(p['url'])} uses a temporary {hops[0]} to {_path(final)}, so Google keeps the old URL indexed. Change it to a 301 if the move is permanent."})

    # ---------- Identical and near-duplicate content ----------
    def consolidate(keep: str, drop: str, reason: str, source: str, conf: str, keyword: str | None = None, merge_first: bool = False) -> None:
        nonlocal already_ok
        declared = live[drop].get("canonical")
        if declared and _key(declared) == _key(keep):
            already_ok += 1
            return
        if urlparse(drop).query or _same_slug_other_folder(keep, drop):
            why = "It carries a query string" if urlparse(drop).query else "The same page lives in two folders"
            canon_plan.setdefault(drop, {"target": keep, "priority": "high" if conf == "high" else "medium", "confidence": conf,
                                         "problem": source, "reason": f"{reason} {why}, so it can stay reachable for visitors while signals go to one URL."})
            return
        add_redirect({"from": drop, "to": keep, "method": "301", "action": "Merge, then 301" if merge_first else "301 redirect", "confidence": conf,
                      "status": 200, "source": source, "score": None, "inlinks": live[drop].get("inlink_count", 0),
                      "keyword": keyword, "merge_first": merge_first, "reason": reason})

    by_hash = defaultdict(list)
    for u, p in live.items():
        if p.get("text_hash") and p.get("word_count", 0) > 30:
            by_hash[p["text_hash"]].append(u)
    for group in (g for g in by_hash.values() if len(g) > 1):
        votes = Counter(by_key.get(_key(live[u].get("canonical"))) for u in group if live[u].get("canonical"))
        votes.pop(None, None)
        homes = [u for u in group if _is_home(u)]
        keep = homes[0] if homes else votes.most_common(1)[0][0] if votes else max(
            group, key=lambda u: (not urlparse(u).query, u == u.lower(), bool(live[u].get("in_sitemap")), value(u)))
        for u in group:
            if u == keep or _is_home(u) or not _same_language(live[u], live[keep]):
                continue
            decided.add(frozenset((u, keep)))
            consolidate(keep, u, f"Identical content to the preferred URL ({evidence(keep)}).", "Duplicate content", "high")

    near = [n for n in cont.get("near_duplicates", []) if n["url_a"] in live and n["url_b"] in live]
    partners = Counter(u for n in near for u in (n["url_a"], n["url_b"]))

    def alternative(url: str, kw: str | None) -> str:
        """A term the page could own instead of the contested keyword."""
        other = next((k for k, _ in kw_map.get(url, []) if k != kw and (not kw or kw not in k)), None)
        return f"'{other}'" if other else "a more specific long-tail keyword"

    def differentiate(keyword: str | None, winner: str, loser: str, sim: float, why: str, source: str, impressions=None) -> None:
        decisions.append({"keyword": keyword or "(similar text)", "winner": winner, "other": loser, "action": "Keep both and differentiate",
                          "similarity": sim, "winner_evidence": evidence(winner), "other_evidence": evidence(loser), "why": why,
                          "source": source, "impressions": impressions})

    for n in sorted(near, key=lambda x: -x["similarity"]):
        a, b, sim = n["url_a"], n["url_b"], n["similarity"]
        pair = frozenset((a, b))
        if pair in decided or not _same_language(live[a], live[b]) or page_type(live[a]) != page_type(live[b]):
            continue
        decided.add(pair)
        keep, drop = (a, b) if value(a) >= value(b) else (b, a)
        if _is_home(drop) or sim < NEAR_DUPLICATE_REDIRECT or partners[a] >= TEMPLATE_FAMILY_PAIRS or partners[b] >= TEMPLATE_FAMILY_PAIRS:
            family = partners[a] >= TEMPLATE_FAMILY_PAIRS or partners[b] >= TEMPLATE_FAMILY_PAIRS
            differentiate(None, keep, drop, sim, f"{_path(drop)} is {round(sim * 100)}% the same as {_path(keep)} and belongs to a template family of {max(partners[a], partners[b]) + 1} similar pages. Give each one unique content instead of collapsing them." if family
                          else f"{round(sim * 100)}% of {_path(drop)} matches {_path(keep)}, but it is not the same page. Rewrite the shared text around {alternative(drop, None)}.", "Near-duplicate content")
        else:
            consolidate(keep, drop, f"{round(sim * 100)}% of the text matches a stronger page. Confirm it has no separate purpose.", "Near-duplicate content", "medium")

    # ---------- Keyword cannibalization ----------
    groups = []
    for c in cont.get("cannibalization", []):
        urls = list(dict.fromkeys(by_key[_key(u)] for u in c["pages"] if _key(u) in by_key))
        urls = [u for u in urls if u in terms]
        if len(urls) > 1:
            groups.append((c, urls, max(urls, key=lambda u: value(u, c["keyword"]))))
    winners = {winner: c["keyword"] for c, _, winner in groups}
    for c, urls, winner in groups:
        kw = c["keyword"]
        source = "Search Console" if c.get("source") else "Page keywords (crawl)"
        for loser in urls:
            pair = frozenset((winner, loser))
            if loser == winner or pair in decided or not _same_language(live[winner], live[loser]):
                continue
            decided.add(pair)
            sim = _similarity(live[winner], live[loser])
            same_type = page_type(live[winner]) == page_type(live[loser])
            share = clicks[_key(loser)] / max(clicks[_key(winner)], 1)
            if _is_home(loser):
                differentiate(kw, winner, loser, sim, f"The home page is never redirected. Keep '{kw}' as a short mention and link it to {_path(winner)}.", source, c.get("impressions"))
            elif loser in winners and winners[loser] != kw:
                differentiate(kw, winner, loser, sim, f"{_path(loser)} is the primary page for '{winners[loser]}', so redirecting it would lose that keyword. Link it to {_path(winner)} for '{kw}' instead.", source, c.get("impressions"))
            elif not same_type:
                differentiate(kw, winner, loser, sim, f"{_path(loser)} ({page_type(live[loser])}) and {_path(winner)} ({page_type(live[winner])}) serve different intent. Re-target {_path(loser)} to {alternative(loser, kw)}.", source, c.get("impressions"))
            elif sim < MERGE_SIMILARITY:
                differentiate(kw, winner, loser, sim, f"Only {round(sim * 100)}% of the text is shared, so a canonical would be ignored and a redirect would lose content. Re-target {_path(loser)} from '{kw}' to {alternative(loser, kw)}.", source, c.get("impressions"))
            else:
                exact = sim >= CONSOLIDATE_SIMILARITY
                conf = "low" if share >= LOSER_TRAFFIC_SHARE and clicks[_key(loser)] else ("high" if exact and not clicks[_key(loser)] else "medium")
                reason = f"Competes for '{kw}' with {round(sim * 100)}% shared text. Stronger page: {evidence(winner)}. This page: {evidence(loser)}."
                decisions.append({"keyword": kw, "winner": winner, "other": loser, "action": "301 redirect" if exact else "Merge, then 301",
                                  "similarity": sim, "winner_evidence": evidence(winner), "other_evidence": evidence(loser),
                                  "why": f"Same intent and {round(sim * 100)}% the same text, so {_path(loser)} adds nothing that {_path(winner)} lacks." if exact
                                  else f"Same intent with {round(sim * 100)}% overlap. Move what is unique on {_path(loser)} into {_path(winner)}, then redirect.",
                                  "source": source, "impressions": c.get("impressions")})
                consolidate(winner, loser, reason, "Keyword cannibalization", conf, kw, merge_first=not exact)

    # ---------- Resolve chains so nothing we suggest creates a new one ----------
    moves = {r["from"]: r["to"] for r in redirects.values() if r.get("to")}

    def resolve(u: str | None) -> str | None:
        seen = set()
        while u in moves:
            if u in seen:
                return None
            seen.add(u)
            u = moves[u]
        return u

    for src in list(redirects):
        row = redirects[src]
        if not row.get("to"):
            continue
        row["to"] = resolve(row["to"])
        if not row["to"] or _key(row["to"]) == _key(src) or (_same(row["to"], crawl.origin) and _key(row["to"]) not in by_key):
            del redirects[src]
    moved = {r["from"]: r["to"] for r in redirects.values() if r.get("to")}

    stuffing = keyword_stuffing(crawl, kw_map, set(copies))
    stuffed = {r["url"]: r for r in stuffing if r["where"] == "Body text"}
    for row in redirects.values():
        s = stuffed.get(row.get("to"))
        if row.get("merge_first") and s:
            row["reason"] += f" The target already repeats '{s['keyword']}' at {s['density']}%, so rewrite while merging instead of pasting text in."
    for d in decisions:
        d["winner"] = resolve(d["winner"]) or d["winner"]

    # ---------- Internal links that must change ----------
    updates: list[dict] = []

    def link_update(kind: str, source: str, current: str | None, new: str | None, anchor: str | None, detail=None) -> None:
        if len(updates) < MAX_LINK_UPDATES and source != new and source not in moved:
            updates.append({"kind": kind, "source": source, "current": current, "new": new, "anchor": anchor, "detail": detail})

    def link_why(row: dict) -> str:
        n, cur, new, detail = row["pages"], _path(row["current"]), _path(row["new"]), row["detail"]
        sitewide = n >= max(3, len(live) / 2)
        where = f"the site template, so one edit fixes all {n} pages" if sitewide else f"{n} page{'s' if n != 1 else ''}"
        link = f"The link '{row['anchor']}'" if row["anchor"] else "A link"
        kind = row["kind"]
        if kind == "Fix broken link":
            return f"{link} on {where} goes to {cur}, which returns {detail}. Link straight to {new}."
        if kind == "Remove broken link":
            if LEGAL_PAGE.search(_fold(f"{row['current']} {row['anchor'] or ''}")):
                return f"{link} on {where} goes to {cur}, which returns {detail}. Keep the link and restore the page, because this looks like legal content."
            return f"{link} on {where} goes to {cur}, which returns {detail}, and no live page replaces it. Remove the link or rewrite the sentence."
        if kind == "Bypass redirect":
            return f"{link} on {where} goes to {cur}, which redirects to {new}. Link to the final URL to save a hop."
        if kind == "Repoint to primary page":
            return f"{cur} is being merged into {new}. Update the link on {where} before the redirect goes live."
        if kind == "Align anchor":
            return f"'{row['anchor']}' points at {detail} different pages, which blurs which should rank. Send it from {cur} to {new}."
        if detail == "redirected":
            return f"This suggestion targets {cur}, which is being redirected. Use {new} for '{row['anchor']}'."
        if detail == "cannibalized":
            return f"Linking '{row['anchor']}' to {cur} would strengthen the competing page. Send it to {new}, the primary page."
        return f"'{row['anchor']}' is suggested for {detail} different pages. Use {new} rather than {cur}, so one anchor means one page."

    for target, links in broken_by_target.items():
        row = redirects.get(target)
        for b in links:
            if row and row.get("to"):
                link_update("Fix broken link", b["source"], target, row["to"], b.get("anchor"), b.get("status"))
            else:
                link_update("Remove broken link", b["source"], target, None, b.get("anchor"), b.get("status"))
    for x in tech.get("links_to_redirects", []):
        final = resolve(x.get("final"))
        if final:
            link_update("Bypass redirect", x["source"], x["target"], final, x.get("anchor"))
    for src, dst in moved.items():
        if src in live:
            for ref in live[src].get("inlinks", []):
                link_update("Repoint to primary page", ref, src, dst, None)
    losers = {(d["keyword"], d["other"]): d["winner"] for d in decisions}
    best_for_anchor = defaultdict(set)
    for s in suggestions:
        best_for_anchor[s["anchor_text"]].add(s["target_url"])
    keywords_of = {u: {k for k, _ in kw_map.get(u, [])[:6]} for u in live}
    headings_of = {u: _words(" ".join([live[u].get("title") or "", " ".join(live[u].get("h1") or [])])) | _url_words(u) for u in live}

    def rivals(anchor: str, source: str, targets) -> list[str]:
        """Pages competing for a real keyword anchor, in the language of the linking page.

        A generic label ('read more') or a phrase missing from the page's title and
        heading is not a signal, and a Czech page must not be sent to an English one.
        """
        if not 1 < len(anchor.split()) <= MAX_ANCHOR_WORDS or source not in live:
            return []
        wanted = _words(anchor)
        out = [u for u in targets if u in live and u not in moved and anchor in keywords_of[u] and wanted <= headings_of[u]
               and _same_language(live[source], live[u])]
        return out if 1 < len(out) <= MAX_ANCHOR_RIVALS else []

    for s in suggestions:
        target, anchor = s["target_url"], s["anchor_text"]
        if target in moved:
            link_update("Retarget suggestion", s["source_url"], target, moved[target], anchor, "redirected")
        elif (anchor, target) in losers:
            link_update("Retarget suggestion", s["source_url"], target, losers[(anchor, target)], anchor, "cannibalized")
        else:
            competing = rivals(anchor, s["source_url"], best_for_anchor[anchor])
            if target in competing:
                top = max(competing, key=lambda u: value(u, anchor))
                if target != top:
                    link_update("Retarget suggestion", s["source_url"], target, top, anchor, len(competing))
    used = defaultdict(lambda: defaultdict(list))
    for p in live.values():
        for link in p.get("internal_links", []):
            text = (link.get("text") or "").strip().lower()
            if not link.get("nav") and " " in text and link["href"] in live and link["href"] not in moved:
                used[text][link["href"]].append(p["url"])
    for anchor, targets in used.items():
        for target, sources in targets.items():
            for src in sources[:10]:
                competing = rivals(anchor, src, targets)
                if target in competing:
                    top = max(competing, key=lambda u: value(u, anchor))
                    if target != top:
                        link_update("Align anchor", src, target, top, anchor, len(competing))
    # One template link repeats on every page, so group by the change, not the page.
    grouped: dict[tuple, dict] = {}
    for u in updates:
        k = (u["kind"], u["current"], u["new"], u["anchor"])
        row = grouped.setdefault(k, {**{f: u[f] for f in ("kind", "current", "new", "anchor", "detail")}, "sources": []})
        if u["source"] not in row["sources"]:
            row["sources"].append(u["source"])
    unique_updates = sorted(grouped.values(), key=lambda r: -len(r["sources"]))
    for row in unique_updates:
        row["pages"] = len(row["sources"])
        row["why"] = link_why(row)
        del row["detail"]

    # ---------- Canonical plan ----------
    canonicals: list[dict] = []

    def add_canonical(page: dict, target: str | None, problem: str, reason: str, priority: str, confidence: str = "high") -> None:
        canonicals.append({"url": page["url"], "current": page.get("canonical"), "target": target, "problem": problem, "reason": reason,
                           "priority": priority, "confidence": confidence,
                           "tag": f'<link rel="canonical" href="{target}">' if target else None})

    def status_of(url: str):
        if url in pages:
            return pages[url].get("status")
        return (crawl.link_status.get(url) or {}).get("status")

    for u, p in live.items():
        if u in moved:
            continue
        declared = p.get("canonical")
        here = _path(u)
        weight = f"It has {p.get('inlink_count', 0)} internal link{'s' if p.get('inlink_count', 0) != 1 else ''}" + (" and is in the sitemap" if p.get("in_sitemap") else "")
        planned_canon = canon_plan.get(u)
        robots = f"{p.get('meta_robots', '')} {p.get('x_robots_tag', '')}".lower()
        if planned_canon:
            add_canonical(p, resolve(planned_canon["target"]), planned_canon["problem"], planned_canon["reason"], planned_canon["priority"], planned_canon["confidence"])
        elif not declared:
            clean = by_key.get(_key(u.split("?", 1)[0])) if urlparse(u).query else None
            if clean and clean != u:
                add_canonical(p, resolve(clean), "Parameter URL without canonical", f"{here} competes with {_path(clean)} because it declares no canonical. Hand its signals to the clean URL.", "high")
            elif "noindex" not in robots:
                add_canonical(p, u, "Missing canonical", f"{here} has no canonical tag. {weight}, so add a self-reference to stop URL variants splitting those signals.", "low")
        elif _key(declared) == _key(u):
            if declared != u:
                add_canonical(p, u, "Trailing slash mismatch", f"The canonical says {_path(declared)} but the page loads at {here}. Use the exact URL.", "low")
        else:
            final = pages.get(declared, {}).get("final_url") or (crawl.link_status.get(declared) or {}).get("redirect_to")
            target = by_key.get(_key(declared))
            if not _same(declared, crawl.origin):
                host = urlparse(declared).netloc
                if _is_dev_host(host):
                    add_canonical(p, u, "Canonical points to a development site", f"{here} names {host}{_path(declared)} as the original, and that host looks like a development site. {weight}, so Google could drop this live page in favour of the dev copy. Use the live URL.", "high")
                else:
                    add_canonical(p, u, "Canonical points to another domain", f"{here} hands its rankings to {host}{_path(declared)}. That is right only if the text was republished from {host} on purpose. {weight}, so use the page's own URL if it is yours.", "high", "medium")
            elif "noindex" in robots:
                add_canonical(p, None, "Noindex combined with canonical", f"{here} says noindex and also names {_path(declared)} as its canonical. Those are opposite signals: keep the canonical if it is a duplicate, or the noindex if it should stay out of search.", "medium", "medium")
            elif final and _key(final) in by_key and _key(final) != _key(declared):
                add_canonical(p, resolve(by_key[_key(final)]), "Canonical points to a redirect", f"{_path(declared)} redirects to {_path(final)}, so name {_path(final)} directly.", "high")
            elif status_of(declared) not in (None, 200):
                add_canonical(p, u, "Canonical points to an error page", f"{_path(declared)} returns {status_of(declared)}, so the canonical on {here} is ignored. Use the page's own URL.", "high")
            elif target and not indexable(live[target]):
                blocked_by = "is noindexed" if "noindex" in f"{live[target].get('meta_robots', '')} {live[target].get('x_robots_tag', '')}".lower() else f"canonicalizes to {_path(live[target].get('canonical'))}"
                add_canonical(p, resolve(by_key.get(_key(live[target].get("canonical"))) or u), "Canonical points to a non-indexable page", f"{_path(declared)} {blocked_by}, so the signal from {here} goes nowhere.", "high")
            elif target and not urlparse(u).query and _similarity(p, live[target]) < MERGE_SIMILARITY:
                add_canonical(p, u, "Canonical between different pages", f"Only {round(_similarity(p, live[target]) * 100)}% of {here} matches {_path(declared)}, so search engines will likely ignore this canonical. Make it self-referencing.", "medium", "medium")
    order = {"high": 0, "medium": 1, "low": 2}
    canonicals.sort(key=lambda c: (order[c["priority"]], c["url"]))

    redirect_rows = sorted(redirects.values(), key=lambda r: (CONF_ORDER[r["confidence"]], -(r.get("inlinks") or 0)))
    scheme = urlparse(crawl.origin).scheme
    for host, (shared, total) in copies.items():
        agree = sum(1 for p in html_pages(pages) if urlparse(p["url"]).netloc == host and urlparse(p.get("canonical") or "").netloc == primary_host)
        redirect_rows.insert(0, {
            "from": f"{scheme}://{host}/*", "to": f"{scheme}://{primary_host}/*", "method": "301", "action": "Redirect whole host", "confidence": "high", "status": 200,
            "source": "Duplicate host", "score": None, "inlinks": None, "keyword": None, "merge_first": False, "host_move": [host, primary_host],
            "reason": f"The whole site loads on both {host} and {primary_host}: {shared} of {total} pages exist on each, and {agree} already name {primary_host} as canonical. One host-wide 301 removes every duplicate at once."})
    issues = []
    if stuffing:
        issues.append(issue("keyword_stuffing", "Content", "high" if any(s["severity"] == "high" for s in stuffing) else "medium", "Possible keyword stuffing",
                            f"{len(stuffing)} places repeat a keyword far more than natural copy does.",
                            "Rewrite the repetition with synonyms and related terms. See the Redirects & Canonicals tab.",
                            [s["url"] for s in stuffing], impact=5, effort=3, details=stuffing))
    return {
        "summary": {
            "redirects": sum(1 for r in redirect_rows if r["method"] == "301"), "gone": sum(1 for r in redirect_rows if r["method"] == "410"),
            "restore": sum(1 for r in redirect_rows if r["method"] == "restore"), "host_copies": len(copies),
            "canonical_fixes": sum(1 for c in canonicals if c["priority"] != "low"), "canonical_missing": sum(1 for c in canonicals if c["priority"] == "low"),
            "differentiate": sum(1 for d in decisions if d["action"].startswith("Keep")), "link_updates": len(unique_updates),
            "links_affected": sum(r["pages"] for r in unique_updates),
            "stuffing": len(stuffing), "already_canonicalized": already_ok, "used_search_console": bool(gsc),
        },
        "redirects": redirect_rows, "canonicals": canonicals[:1000], "decisions": decisions[:1000],
        "link_updates": unique_updates, "stuffing": stuffing, "rules": server_rules(redirect_rows), "issues": issues,
    }
