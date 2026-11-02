# SEO Dashboard

A self-hosted, multi-client SEO audit dashboard: technical SEO, on-page and keyword suggestions, internal linking, URL structure graphs, schema, Core Web Vitals, niche keyword research, Search Console and GA4 via Windsor.ai, an AI Overviews / GEO brief, a conversion tracking plan, off-page suggestions, a Top 10 action list and a 30/60/90-day roadmap. Reports export to Excel and to a printable HTML/PDF report.

## Getting started (first time)

1. Install **Python 3.11 or newer** from https://www.python.org/downloads/. On Windows, tick *Add Python to PATH* during setup.
2. Get the code: click **Code → Download ZIP** on this page and unzip it, or run
   `git clone https://github.com/erfanjanali28/SEO_dashboard`.
3. Open a terminal in the project folder and run:
   ```bash
   python -m venv .venv
   # macOS / Linux:
   source .venv/bin/activate
   # Windows (PowerShell):
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python webapp/run.py
   ```
4. Open **http://127.0.0.1:8000** in your browser.
5. Go to **Settings**, paste your **Windsor.ai API key**, then add a client and a website and click **Run audit**.

The next time, you only need to activate the `.venv` and run `python webapp/run.py`.

## Configuration

```bash
pip install -r requirements.txt
python webapp/run.py            # http://127.0.0.1:8000
```

| Variable | Purpose |
|---|---|
| `SEO_DASHBOARD_PASSWORD` | Turns on HTTP Basic auth (user `admin`, or set `SEO_DASHBOARD_USER`). Set it before exposing the app. |
| `SEO_DASHBOARD_DATA` | Data folder for the SQLite DB and client photos (default `webapp/data/`). |
| `SEO_DASHBOARD_SCHEDULER=0` | Turns off scheduled audits. |
| `CLAUDE_SEO_LOCAL_TARGETS` | Allows auditing local or staging hosts (see `scripts/url_safety.py`). |

## Workflow

1. **Clients**: add a client with a photo or logo. It appears on the client card and on the report cover.
2. **Websites**: add a domain with its industry/niche, location and seed keywords, then pick an audit interval (manual, 6 h, daily, weekly, monthly, or a custom number of hours).
3. **Settings**: paste your Windsor.ai API key (Search Console and GA4 sync). Optionally add a PageSpeed Insights API key and DataForSEO credentials for keyword volumes.
4. **Run audit**, or let the scheduler run it. Each audit is stored, so scores, issues and rankings can be charted over time, and a *Changes since the previous audit* panel compares the last two runs.

## What each tab covers

| Tab | Contents |
|---|---|
| Overview | Overall and category scores, severity mix, score history, status codes, new and resolved issues |
| Top 10 & Roadmap | Priority actions ranked by severity × impact × reach ÷ effort; 30/60/90-day plan with owners and KPIs |
| Technical | 404s with suggested 301 targets, broken links, redirect chains and 302s, noindex, robots.txt, canonicals, duplicate URLs, URL variants, XML sitemaps, llms.txt, HTTPS, mixed content, security headers, mobile viewport, JavaScript rendering (content missing from the initial HTML), TTFB, compression |
| On-page & Meta | Title, meta description and H1 problems; per-page target keyword, secondary keywords, and suggested title and description with the source URL |
| Content | Thin, near-duplicate, outdated and generic content; missing authors; weak structure; keyword cannibalization; content gaps |
| Internal Links | Orphans, weakly linked and deep pages, generic anchors, contextual link suggestions (source URL → target URL + anchor + context) with an Excel export |
| URL Structure | Interactive D3 folder tree and internal-link network graph, URLs per folder, URL hygiene problems |
| Schema | Types found, coverage, pages without structured data with a suggested type, required/recommended property validation |
| Core Web Vitals | PageSpeed Insights mobile and desktop: LCP, INP, CLS (CrUX field data when available), Lighthouse scores, top opportunities |
| Keyword Research | Niche keyword universe (site terms, industry modifiers, question patterns, Google Autocomplete, GSC, optional DataForSEO volumes), intent, funnel stage, clusters, target URL or content gap with a suggested slug, striking-distance terms |
| Rankings & Traffic | GSC clicks, impressions and position trends; top keyword ranking lines; improvements and declines (28 days vs previous 28 days); GA4 organic sessions and key events |
| AIO / GEO | AI Overview / generative-engine brief: prerequisites, playbook, answer template, page scores with fixes, question opportunities |
| Lead Gen & Tracking | GA4 + GTM event plan: which event goes on which page and element, the trigger, its parameters, and whether it is a key event; lead-gen gaps and opportunity spots |
| Off-page | Free and paid guest-post and contributor platforms by niche, digital PR sources, clickable prospecting search footprints, pitch topics |

## Exports

- **Full report (Excel)**: 22 sheets, each with a summary chart where one fits.
- **Internal links (Excel)**: link suggestions, orphans and inlinks, links to redirects, broken internal links.
- **Printable report**: a self-contained HTML file with inline SVG charts and the client photo. Use *Print → Save as PDF*.

## Notes

- All crawling goes through the repo's SSRF-safe `scripts/url_safety.py`. Crawls run sequentially, one fetch at a time.
- Windsor.ai endpoint: `https://connectors.windsor.ai/{searchconsole|googleanalytics4}`. Set per-site account IDs when your Windsor workspace holds several properties.
- Off-page lists are starting points. Vet every prospect, and mark paid placements `rel="sponsored"`.

## Tests

```bash
pip install pytest httpx
python3 -m pytest webapp/tests -q
```

## License

`scripts/url_safety.py` comes from [claude-seo](https://github.com/AgriciDaniel/claude-seo) (MIT License, see `LICENSE-claude-seo`).
