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
        if r["confidence"] == "low":
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


def keyword_stuffing(crawl, kw_map: dict) -> list[dict]:
    """Repetition of a page's primary keyword in its text, title and inbound anchors.

    Density is not a Google metric. It is a heuristic for spotting copy that
    repeats a phrase far beyond what natural writing does. It reads paragraph
    text only, because on listing pages a keyword can repeat as a filter label or
    card tag without anyone having written it that way.
    """
    out = []
    live = [p for p in html_pages(crawl.pages) if indexable(p)]
    for p in live:
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
                        "recommendation": "Rewrite for readers: use synonyms and related terms, and keep the exact phrase to the title, H1 and a few natural mentions."})
        title_hits = _occurrences((p.get("title") or "").lower(), kw)
        if title_hits >= 2:
            out.append({"url": p["url"], "keyword": kw, "where": "Title", "occurrences": title_hits, "density": None, "severity": "medium",
                        "recommendation": "Use the keyword once in the title and spend the remaining characters on a benefit or qualifier."})
    anchors, totals = Counter(), Counter()
    for p in html_pages(crawl.pages):
        for link in p.get("internal_links", []):
            if link.get("nav") or not link.get("text"):
                continue
            totals[link["href"]] += 1
            anchors[(link["href"], link["text"].strip().lower())] += 1
    for (target, anchor), n in anchors.items():
        if n >= 5 and 1 < len(anchor.split()) <= MAX_ANCHOR_WORDS and n / totals[target] >= 0.6:
            out.append({"url": target, "keyword": anchor, "where": "Internal anchors", "occurrences": n,
                        "density": round(n / totals[target] * 100, 1), "severity": "medium",
                        "recommendation": "Vary the anchors pointing at this page. Exact-match anchors on most links look engineered."})
    return sorted(out, key=lambda r: (r["severity"] != "high", -(r["density"] or 0)))[:500]


def analyze(crawl, kw_map: dict, tech: dict, cont: dict, suggestions: list[dict], gsc: list[dict] | None = None) -> dict:
    pages = crawl.pages
    live = {p["url"]: p for p in html_pages(pages) if not p.get("redirect_chain")}
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
        if target and score >= 0.25:
            conf = "high" if score >= 0.6 else "medium" if score >= 0.4 else "low"
            typo = SequenceMatcher(None, urlparse(url).path.rstrip("/"), urlparse(target).path.rstrip("/")).ratio() >= TYPO_SIMILARITY
            add_redirect({**base, "to": target, "method": "301", "action": "301 redirect", "confidence": "high" if typo else conf,
                          "reason": "Almost the same URL, so this is very likely a typo." if typo else
                          "Closest live page by URL, anchor text and topic" + (f" ({'; '.join(why)})" if why else "") + "."})
            return
        parts = urlparse(url).path.rstrip("/").split("/")
        while len(parts) > 2:
            parts.pop()
            hub = by_key.get(_key(f"{crawl.origin}{'/'.join(parts)}"))
            if hub and hub in open_urls:
                add_redirect({**base, "to": hub, "method": "301", "action": "301 redirect", "confidence": "low",
                              "reason": "No equivalent page exists. This is the nearest parent section, so check it really serves the same need."})
                return
        add_redirect({**base, "to": None, "method": "410", "action": "Return 410 and remove links", "confidence": "medium",
                      "reason": "No live page covers this topic. A redirect to the home page would be treated as a soft 404, so let it go or restore the page if it had value."})

    for r in tech.get("redirect_suggestions", []):
        plan_dead(r["from"], r.get("status"), "404 / 410 error")

    # ---------- Existing redirects: chains, temporary, dead ends ----------
    for p in pages.values():
        chain = p.get("redirect_chain") or []
        if not chain:
            continue
        final = p.get("final_url")
        final_status = p.get("final_status")
        hops = [s for _, s in chain]
        if final_status and final_status >= 400:
            plan_dead(p["url"], final_status, "Redirect ends in an error")
        elif len(chain) > 1:
            add_redirect({"from": p["url"], "to": final, "method": "301", "action": "Flatten redirect chain", "confidence": "high", "status": hops[0],
                          "source": "Redirect chain", "score": None, "inlinks": p.get("inlink_count", 0),
                          "reason": f"{len(chain)} hops today ({' → '.join(map(str, hops))}). Redirect straight to the final URL."})
        elif hops[0] in (302, 303, 307):
            add_redirect({"from": p["url"], "to": final, "method": "301", "action": "Change to 301", "confidence": "medium", "status": hops[0],
                          "source": "Temporary redirect", "score": None, "inlinks": p.get("inlink_count", 0),
                          "reason": "A temporary redirect keeps the old URL in the index. Make it permanent if the move is permanent."})

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
            differentiate(None, keep, drop, sim, "These look like a template family, so give each page unique content instead of collapsing them." if family
                          else "The text overlaps but is not the same page. Rewrite the shared sections so each page has its own angle.", "Near-duplicate content")
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
                differentiate(kw, winner, loser, sim, "The home page is never redirected. Shift its copy to brand and overview terms and link to the primary page.", source, c.get("impressions"))
            elif loser in winners and winners[loser] != kw:
                differentiate(kw, winner, loser, sim, f"This page is also the primary page for '{winners[loser]}', so redirecting it would lose that keyword.", source, c.get("impressions"))
            elif not same_type:
                differentiate(kw, winner, loser, sim, f"Different page types ({page_type(live[loser])} vs {page_type(live[winner])}) serve different intent. Re-target this page to its own long-tail keyword.", source, c.get("impressions"))
            elif sim < MERGE_SIMILARITY:
                differentiate(kw, winner, loser, sim, "The pages share a keyword but little text. A canonical would be ignored and a redirect would lose unique content, so re-target this page.", source, c.get("impressions"))
            else:
                exact = sim >= CONSOLIDATE_SIMILARITY
                conf = "low" if share >= LOSER_TRAFFIC_SHARE and clicks[_key(loser)] else ("high" if exact and not clicks[_key(loser)] else "medium")
                reason = f"Competes for '{kw}' with {round(sim * 100)}% shared text. Stronger page: {evidence(winner)}. This page: {evidence(loser)}."
                decisions.append({"keyword": kw, "winner": winner, "other": loser, "action": "301 redirect" if exact else "Merge, then 301",
                                  "similarity": sim, "winner_evidence": evidence(winner), "other_evidence": evidence(loser),
                                  "why": "Same intent and mostly the same text." if exact else "Same intent with partial overlap. Move anything unique across first, then redirect.",
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

    stuffing = keyword_stuffing(crawl, kw_map)
    stuffed = {r["url"]: r for r in stuffing if r["where"] == "Body text"}
    for row in redirects.values():
        s = stuffed.get(row.get("to"))
        if row.get("merge_first") and s:
            row["reason"] += f" The target already repeats '{s['keyword']}' at {s['density']}%, so rewrite while merging instead of pasting text in."
    for d in decisions:
        d["winner"] = resolve(d["winner"]) or d["winner"]

    # ---------- Internal links that must change ----------
    updates: list[dict] = []

    def link_update(kind: str, source: str, current: str | None, new: str | None, anchor: str | None, why: str) -> None:
        if len(updates) < MAX_LINK_UPDATES and source != new and source not in moved:
            updates.append({"kind": kind, "source": source, "current": current, "new": new, "anchor": anchor, "why": why})

    for target, links in broken_by_target.items():
        row = redirects.get(target)
        for b in links:
            if row and row.get("to"):
                link_update("Fix broken link", b["source"], target, row["to"], b.get("anchor"), "Link directly to the live target so it does not go through a redirect.")
            else:
                link_update("Remove broken link", b["source"], target, None, b.get("anchor"), "No equivalent page exists. Remove the link or the sentence around it.")
    for x in tech.get("links_to_redirects", []):
        final = resolve(x.get("final"))
        if final:
            link_update("Bypass redirect", x["source"], x["target"], final, x.get("anchor"), "This link passes through a redirect.")
    for src, dst in moved.items():
        if src in live:
            for ref in live[src].get("inlinks", []):
                link_update("Repoint to primary page", ref, src, dst, None, "This URL is being consolidated. Update the link before the redirect goes live.")
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
            link_update("Retarget suggestion", s["source_url"], target, moved[target], anchor, "This internal link suggestion points at a URL that is being redirected.")
        elif (anchor, target) in losers:
            link_update("Retarget suggestion", s["source_url"], target, losers[(anchor, target)], anchor,
                        f"Using '{anchor}' to link here would reinforce the cannibalization. Send the anchor to the primary page.")
        else:
            competing = rivals(anchor, s["source_url"], best_for_anchor[anchor])
            if target in competing:
                top = max(competing, key=lambda u: value(u, anchor))
                if target != top:
                    link_update("Retarget suggestion", s["source_url"], target, top, anchor,
                                f"'{anchor}' is suggested for {len(competing)} different pages. One anchor should mean one page.")
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
                        link_update("Align anchor", src, target, top, anchor, f"The anchor '{anchor}' points at {len(competing)} different pages, which blurs which one should rank.")
    # One template link repeats on every page, so group by the change, not the page.
    grouped: dict[tuple, dict] = {}
    for u in updates:
        k = (u["kind"], u["current"], u["new"], u["anchor"])
        row = grouped.setdefault(k, {**{f: u[f] for f in ("kind", "current", "new", "anchor", "why")}, "sources": []})
        if u["source"] not in row["sources"]:
            row["sources"].append(u["source"])
    unique_updates = sorted(grouped.values(), key=lambda r: -len(r["sources"]))
    for row in unique_updates:
        row["pages"] = len(row["sources"])

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
        planned_canon = canon_plan.get(u)
        robots = f"{p.get('meta_robots', '')} {p.get('x_robots_tag', '')}".lower()
        if planned_canon:
            add_canonical(p, resolve(planned_canon["target"]), planned_canon["problem"], planned_canon["reason"], planned_canon["priority"], planned_canon["confidence"])
        elif not declared:
            clean = by_key.get(_key(u.split("?", 1)[0])) if urlparse(u).query else None
            if clean and clean != u:
                add_canonical(p, resolve(clean), "Parameter URL without canonical", "Query-string versions should hand their signals to the clean URL.", "high")
            elif "noindex" not in robots:
                add_canonical(p, u, "Missing canonical", "Add a self-referencing canonical so URL variants cannot split signals.", "low")
        elif _key(declared) == _key(u):
            if declared != u:
                add_canonical(p, u, "Trailing slash mismatch", "The canonical differs from the URL only by a slash. Use the exact URL.", "low")
        else:
            final = pages.get(declared, {}).get("final_url") or (crawl.link_status.get(declared) or {}).get("redirect_to")
            target = by_key.get(_key(declared))
            if not _same(declared, crawl.origin):
                add_canonical(p, u, "Canonical points to another domain", "Correct only for deliberate syndication. Otherwise this page gives away its rankings.", "high", "medium")
            elif "noindex" in robots:
                add_canonical(p, None, "Noindex combined with canonical", "These send opposite signals. Keep the canonical if this is a duplicate, or the noindex if it should stay out of the index, not both.", "medium", "medium")
            elif final and _key(final) in by_key and _key(final) != _key(declared):
                add_canonical(p, resolve(by_key[_key(final)]), "Canonical points to a redirect", "Canonicals must name the final 200 URL.", "high")
            elif status_of(declared) not in (None, 200):
                add_canonical(p, u, "Canonical points to an error page", f"The canonical target returns {status_of(declared)}, so it is ignored.", "high")
            elif target and not indexable(live[target]):
                add_canonical(p, resolve(by_key.get(_key(live[target].get("canonical"))) or u), "Canonical points to a non-indexable page", "The target is noindexed or canonicalized elsewhere, so the signal goes nowhere.", "high")
            elif target and not urlparse(u).query and _similarity(p, live[target]) < MERGE_SIMILARITY:
                add_canonical(p, u, "Canonical between different pages", "The pages share little text, so search engines will likely ignore this canonical and the page gets no clear signal.", "medium", "medium")
    order = {"high": 0, "medium": 1, "low": 2}
    canonicals.sort(key=lambda c: (order[c["priority"]], c["url"]))

    redirect_rows = sorted(redirects.values(), key=lambda r: (CONF_ORDER[r["confidence"]], -(r.get("inlinks") or 0)))
    issues = []
    if stuffing:
        issues.append(issue("keyword_stuffing", "Content", "high" if any(s["severity"] == "high" for s in stuffing) else "medium", "Possible keyword stuffing",
                            f"{len(stuffing)} places repeat a keyword far more than natural copy does.",
                            "Rewrite the repetition with synonyms and related terms. See the Redirects & Canonicals tab.",
                            [s["url"] for s in stuffing], impact=5, effort=3, details=stuffing))
    return {
        "summary": {
            "redirects": sum(1 for r in redirect_rows if r["method"] == "301"), "gone": sum(1 for r in redirect_rows if r["method"] == "410"),
            "canonical_fixes": sum(1 for c in canonicals if c["priority"] != "low"), "canonical_missing": sum(1 for c in canonicals if c["priority"] == "low"),
            "differentiate": sum(1 for d in decisions if d["action"].startswith("Keep")), "link_updates": len(unique_updates),
            "links_affected": sum(r["pages"] for r in unique_updates),
            "stuffing": len(stuffing), "already_canonicalized": already_ok, "used_search_console": bool(gsc),
        },
        "redirects": redirect_rows, "canonicals": canonicals[:1000], "decisions": decisions[:1000],
        "link_updates": unique_updates, "stuffing": stuffing, "rules": server_rules(redirect_rows), "issues": issues,
    }
