"""Off-page suggestions: guest posting platforms, prospecting footprints and
digital PR sources, split into free (editorial) and paid (sponsored) options.

The curated lists are starting points, not endorsements. Verify each site's
current guidelines, traffic and link policy before pitching. Google requires
paid or sponsored placements to carry rel="sponsored" (or nofollow); buying
followed links violates its spam policies.
"""

from __future__ import annotations

from urllib.parse import quote_plus

# (name, url, cost, type, notes)
GENERAL = [
    ("Medium (own publication or submit to publications)", "https://medium.com", "free", "self-publish / editorial", "Large reach; links are nofollow, so it is good for visibility and brand mentions"),
    ("LinkedIn Articles", "https://www.linkedin.com", "free", "self-publish", "B2B thought leadership; strong for E-E-A-T and brand entity signals"),
    ("Substack", "https://substack.com", "free", "self-publish", "Newsletter plus web posts; cross-recommendations"),
    ("HackerNoon", "https://hackernoon.com", "free", "editorial contributor", "Tech, startups, business"),
    ("Vocal Media", "https://vocal.media", "free / paid tier", "self-publish", "Broad topics"),
    ("Business2Community", "https://www.business2community.com", "free", "contributor", "Marketing and business; editorial review"),
    ("Reddit (relevant subreddits)", "https://www.reddit.com", "free", "community", "Heavily cited by AI answers; contribute genuinely and never spam"),
    ("Quora Spaces", "https://www.quora.com", "free", "community", "Answer niche questions; useful for brand mentions"),
    ("Forbes Councils", "https://councils.forbes.com", "paid membership", "contributor network", "Vetted membership with an annual fee; allows bylined articles"),
    ("Entrepreneur Leadership Network", "https://www.entrepreneur.com", "paid membership", "contributor network", "Bylined articles for paid members"),
    ("Newsweek Expert Forum", "https://expertforum.newsweek.com", "paid membership", "contributor network", "Membership-based bylines"),
]
PR_SOURCES = [
    ("Qwoted", "https://www.qwoted.com", "free / paid tiers", "journalist requests"),
    ("Featured.com", "https://featured.com", "free / paid tiers", "expert quotes for publishers"),
    ("Help a B2B Writer", "https://helpab2bwriter.com", "free", "B2B journalist requests"),
    ("SourceBottle", "https://www.sourcebottle.com", "free", "journalist call-outs (AU/UK/US)"),
    ("#journorequest on X / Bluesky", "https://x.com/search?q=%23journorequest", "free", "journalist requests"),
    ("Muck Rack", "https://muckrack.com", "paid", "journalist database"),
]
NICHE = {
    "saas": [("Dev.to", "https://dev.to", "free", "self-publish", "Developer audience"),
             ("Hashnode", "https://hashnode.com", "free", "self-publish", "Developer blogs with a custom domain"),
             ("SaaStr community", "https://www.saastr.com", "free", "community", "SaaS founders"),
             ("G2 / Capterra profiles", "https://www.g2.com", "free listing / paid", "review platform", "Review profiles are heavily used by AI answers for 'best X software' queries")],
    "ecommerce": [("Shopify Community", "https://community.shopify.com", "free", "community", "Merchant discussions"),
                  ("Practical Ecommerce", "https://www.practicalecommerce.com", "free", "contributor", "Pitch expert articles"),
                  ("Niche gift guides / roundup posts", "", "free / paid", "product placement", "Pitch products to 'best X' listicles; paid inclusions must be marked sponsored")],
    "local": [("Local chamber of commerce", "", "membership", "directory + news", "Member spotlights and local links"),
              ("Local news & community blogs", "", "free", "editorial", "Pitch local stories, sponsorships, events"),
              ("Yelp / Bing Places / Apple Business Connect", "https://www.yelp.com", "free", "citations", "NAP consistency")],
    "agency": [("Search Engine Journal", "https://www.searchenginejournal.com", "free", "contributor", "Editorially vetted; high bar"),
               ("Search Engine Land", "https://searchengineland.com", "free", "contributor", "Pitch expert columns"),
               ("Smashing Magazine", "https://www.smashingmagazine.com", "paid to writers", "editorial", "Web design and dev; they pay authors"),
               ("Clutch / DesignRush profiles", "https://clutch.co", "free / paid", "directory", "Agency reviews; cited in AI answers")],
    "healthcare": [("KevinMD", "https://kevinmd.com", "free", "contributor", "Physician and healthcare voices"),
                   ("Healthline / WebMD expert review", "", "invite", "expert reviewer", "Medical reviewer roles")],
    "finance": [("Seeking Alpha", "https://seekingalpha.com", "paid to writers", "contributor", "Investing analysis"),
                ("Finextra community", "https://www.finextra.com", "free", "contributor", "Fintech blogs")],
    "real estate": [("BiggerPockets blog", "https://www.biggerpockets.com", "free", "contributor", "Real estate investing"),
                    ("Inman (contributor)", "https://www.inman.com", "free", "contributor", "Industry op-eds")],
    "education": [("eLearning Industry", "https://elearningindustry.com", "free / paid", "contributor", "L&D and edtech"),
                  ("EdSurge", "https://www.edsurge.com", "free", "contributor", "Edtech voices")],
    "travel": [("Matador Network", "https://matadornetwork.com", "paid to writers", "contributor", "Travel storytelling"),
               ("Travel bloggers' guest posts", "", "free / paid", "collaboration", "Exchange guides with local creators")],
    "legal": [("Above the Law", "https://abovethelaw.com", "free", "contributor", "Legal industry columns"),
              ("JD Supra", "https://www.jdsupra.com", "paid", "syndication", "Legal publishing and distribution")],
}
FOOTPRINTS = [
    '"{kw}" "write for us"', '"{kw}" "guest post"', '"{kw}" "submit a guest post"', '"{kw}" intitle:"write for us"',
    '"{kw}" "become a contributor"', '"{kw}" "contribute" "guidelines"', '"{kw}" inurl:guest-post',
    '"{kw}" "sponsored post" OR "advertise with us"', '"{kw}" "accepting guest posts"', '"{kw}" "guest author"',
    '"{kw}" intitle:"resources" OR intitle:"useful links"', '"{kw}" "best {kw}" -site:{domain}',
]


def analyze(site: dict, research: dict | None, domain: str) -> dict:
    industry = (site.get("industry") or "").lower()
    niche_key = next((k for k in NICHE if k in industry), None)
    seeds = (research or {}).get("seeds", [])[:5] or [industry or domain]
    footprints = []
    for kw in seeds[:4]:
        for f in FOOTPRINTS:
            q = f.format(kw=kw, domain=domain)
            footprints.append({"keyword": kw, "query": q, "google_url": "https://www.google.com/search?q=" + quote_plus(q),
                               "type": "paid" if "sponsored" in f or "advertise" in f else "resource" if "resources" in f or "best" in f else "guest post"})
    platforms = [dict(zip(("name", "url", "cost", "type", "notes"), x)) for x in (NICHE.get(niche_key, []) + GENERAL)]
    pr = [dict(zip(("name", "url", "cost", "type"), x)) for x in PR_SOURCES]
    topics = [k["keyword"] for k in (research or {}).get("keywords", []) if k["intent"] == "informational"][:15]
    return {
        "niche": niche_key or "general", "platforms": platforms, "pr_sources": pr, "footprints": footprints,
        "pitch_topics": topics,
        "free_count": sum(1 for p in platforms if p["cost"].startswith("free")),
        "paid_count": sum(1 for p in platforms if "paid" in p["cost"] or "membership" in p["cost"]),
        "guidelines": [
            "Qualify every prospect: real organic traffic, topical relevance, an editorial bar, and no 'write for us – any topic' link farms.",
            "Paid or sponsored placements must use rel=\"sponsored\". Followed paid links violate Google's spam policies.",
            "Pitch original angles (data, case studies, expert how-tos) taken from the informational keywords below.",
            "Link to the most relevant deep page, not the home page, and vary anchors naturally (branded and partial-match).",
            "Track every placement (URL, date, cost, link attributes) and re-verify links quarterly.",
            "Brand mentions on Reddit, YouTube, review sites and industry lists also drive AI-answer citations (GEO).",
        ],
    }
