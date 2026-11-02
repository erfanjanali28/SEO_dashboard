"""Windsor.ai connector for Google Search Console and Google Analytics 4.

Windsor.ai aggregates GSC (connector ``searchconsole``) and GA4 (connector
``googleanalytics4``) behind one REST endpoint::

    GET https://connectors.windsor.ai/{connector}?api_key=KEY&date_from=YYYY-MM-DD
        &date_to=YYYY-MM-DD&fields=a,b,c[&select_accounts=ACCOUNT]

Authentication is the workspace API key only. Windsor never needs your
password here. A workspace usually holds several sites and properties, so
every pull also requests ``account_id`` and keeps only the rows for the
site's own account. Accounts come from the per-site settings, or are
auto-matched from the site's domain.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import urlparse

import requests

from .. import db

BASE = "https://connectors.windsor.ai"
GSC = "searchconsole"
GA4 = "googleanalytics4"
GSC_FIELDS = ["account_id", "date", "query", "page", "clicks", "impressions", "ctr", "position"]
GA4_FIELDS = ["account_id", "date", "landing_page", "session_default_channel_group", "sessions", "totalusers", "engaged_sessions", "conversions"]


class WindsorError(RuntimeError):
    pass


def _get(connector: str, params: dict, timeout: int) -> list[dict]:
    try:
        r = requests.get(f"{BASE}/{connector}", params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise WindsorError(f"Could not reach Windsor.ai: {exc}") from exc
    if r.status_code in (401, 403):
        raise WindsorError("Windsor.ai rejected the API key. Copy it again from your Windsor.ai account and save it in Settings.")
    if r.status_code != 200:
        raise WindsorError(f"Windsor.ai HTTP {r.status_code}: {r.text[:200]}")
    try:
        data = r.json()
    except ValueError as exc:
        raise WindsorError("Windsor.ai returned a non-JSON response") from exc
    if isinstance(data, dict) and data.get("error"):
        raise WindsorError(f"Windsor.ai: {str(data['error'])[:200]}")
    rows = data.get("data", []) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise WindsorError("Unexpected Windsor.ai response")
    return rows


def fetch(connector: str, fields: list[str], api_key: str, *, days: int | None = None, preset: str | None = None,
          account: str | None = None, timeout: int = 300) -> list[dict]:
    params = {"api_key": api_key, "fields": ",".join(fields), "_renderer": "json"}
    if preset:
        params["date_preset"] = preset
    else:
        params["date_from"] = (date.today() - timedelta(days=days or 90)).isoformat()
        params["date_to"] = (date.today() - timedelta(days=1)).isoformat()
    if not account:
        return _get(connector, params, timeout)
    rows = _get(connector, {**params, "select_accounts": account}, timeout)
    if not any(account_matches(r.get("account_id"), account) for r in rows):
        # select_accounts spelled differently than this connector expects:
        # pull everything and keep only this account's rows below.
        rows = _get(connector, params, timeout)
    return [r for r in rows if account_matches(r.get("account_id"), account)]


def _norm_account(v) -> str:
    s = str(v or "").strip().lower()
    s = s.removeprefix("sc-domain:")
    s = re.sub(r"^https?://", "", s).removeprefix("www.")
    return s.rstrip("/")


def account_matches(row_account, wanted: str) -> bool:
    return _norm_account(row_account) == _norm_account(wanted)


def _domain(url: str) -> str:
    host = (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower()
    return host.removeprefix("www.")


def list_accounts(api_key: str | None = None) -> dict:
    """Accounts in the Windsor workspace, as {"gsc": [...], "ga4": [...]}."""
    api_key = api_key or db.get_setting("windsor_api_key")
    if not api_key:
        raise WindsorError("Add your Windsor.ai API key in Settings first.")
    out = {}
    for key, connector, metric in (("gsc", GSC, "clicks"), ("ga4", GA4, "sessions")):
        rows = _get(connector, {"api_key": api_key, "fields": f"account_id,account_name,{metric}",
                                "date_preset": "last_30d", "_renderer": "json"}, 120)
        seen = {}
        for r in rows:
            aid = str(r.get("account_id") or "")
            if aid and aid not in seen:
                seen[aid] = {"id": aid, "name": r.get("account_name") or aid}
        out[key] = sorted(seen.values(), key=lambda a: a["name"].lower())
    return out


def auto_match(site_url: str, accounts: dict) -> dict:
    """Pick the GSC site and GA4 property that belong to ``site_url``."""
    dom = _domain(site_url)
    root = dom.split(".")[-2] if dom.count(".") >= 1 else dom
    gsc = next((a["id"] for a in accounts.get("gsc", []) if _norm_account(a["id"]) == dom), None)
    if not gsc:  # domain property or subdomain site
        gsc = next((a["id"] for a in accounts.get("gsc", []) if dom.endswith(_norm_account(a["id"]))), None)
    ga4 = next((a["id"] for a in accounts.get("ga4", []) if dom in a["name"].lower()), None)
    if not ga4 and root:
        hits = [a["id"] for a in accounts.get("ga4", []) if re.search(rf"\b{re.escape(root)}\b", a["name"].lower())]
        ga4 = hits[0] if len(hits) == 1 else None
    return {"gsc": gsc, "ga4": ga4}


def _norm_date(v) -> str:
    s = str(v or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else s[:10]


def resolve_accounts(site: dict, api_key: str) -> tuple[dict, list[str]]:
    """Accounts to sync for a site: configured ones first, else auto-matched."""
    chosen = {"gsc": site.get("windsor_gsc_account") or None, "ga4": site.get("windsor_ga4_account") or None}
    notes = []
    if chosen["gsc"] and chosen["ga4"]:
        return chosen, notes
    accounts = list_accounts(api_key)
    guess = auto_match(site["url"], accounts)
    for key, label in (("gsc", "Search Console"), ("ga4", "GA4")):
        if chosen[key]:
            continue
        if guess[key]:
            chosen[key] = guess[key]
            notes.append(f"{label}: auto-matched {guess[key]}")
        elif len(accounts.get(key, [])) == 1:
            chosen[key] = accounts[key][0]["id"]
            notes.append(f"{label}: using the only account, {chosen[key]}")
        else:
            notes.append(f"{label}: no account matches {_domain(site['url'])}. Choose one under the site's Settings / schedule.")
    if chosen["gsc"] or chosen["ga4"]:
        db.execute("UPDATE sites SET windsor_gsc_account = COALESCE(windsor_gsc_account, ?), "
                   "windsor_ga4_account = COALESCE(windsor_ga4_account, ?) WHERE id = ?",
                   (chosen["gsc"], chosen["ga4"], site["id"]))
    return chosen, notes


def sync_site(site: dict, days: int = 90) -> dict:
    api_key = db.get_setting("windsor_api_key")
    if not api_key:
        raise WindsorError("Add your Windsor.ai API key in Settings first.")
    chosen, notes = resolve_accounts(site, api_key)
    result = {"gsc_rows": 0, "ga4_rows": 0, "errors": [], "notes": notes, "accounts": chosen}
    since = (date.today() - timedelta(days=days)).isoformat()
    if chosen["gsc"]:
        try:
            rows = fetch(GSC, GSC_FIELDS, api_key, days=days, account=chosen["gsc"])
            # Replace the window so data from an earlier, wrongly-scoped sync cannot linger.
            db.execute("DELETE FROM search_metrics WHERE site_id = ? AND source = 'gsc' AND date >= ?", (site["id"], since))
            db.executemany(
                "INSERT INTO search_metrics(site_id, date, query, page, clicks, impressions, ctr, position, source) "
                "VALUES(?,?,?,?,?,?,?,?, 'gsc') ON CONFLICT(site_id, date, query, page, source) DO UPDATE SET "
                "clicks=excluded.clicks, impressions=excluded.impressions, ctr=excluded.ctr, position=excluded.position",
                [(site["id"], _norm_date(r.get("date")), r.get("query"), r.get("page"), r.get("clicks") or 0,
                  r.get("impressions") or 0, r.get("ctr") or 0, r.get("position") or 0) for r in rows],
            )
            result["gsc_rows"] = len(rows)
        except WindsorError as exc:
            result["errors"].append(f"Search Console: {exc}")
    if chosen["ga4"]:
        try:
            rows = fetch(GA4, GA4_FIELDS, api_key, days=days, account=chosen["ga4"])
            db.execute("DELETE FROM analytics_metrics WHERE site_id = ? AND date >= ?", (site["id"], since))
            db.executemany(
                "INSERT INTO analytics_metrics(site_id, date, landing_page, channel, sessions, users, engaged_sessions, conversions) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(site_id, date, landing_page, channel) DO UPDATE SET "
                "sessions=excluded.sessions, users=excluded.users, engaged_sessions=excluded.engaged_sessions, conversions=excluded.conversions",
                [(site["id"], _norm_date(r.get("date")), r.get("landing_page"), r.get("session_default_channel_group"),
                  r.get("sessions") or 0, r.get("totalusers") or 0, r.get("engaged_sessions") or 0, r.get("conversions") or 0) for r in rows],
            )
            result["ga4_rows"] = len(rows)
        except WindsorError as exc:
            result["errors"].append(f"GA4: {exc}")
    return result
