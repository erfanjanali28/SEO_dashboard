"""Windsor.ai connector for Google Search Console and Google Analytics 4.

Windsor.ai aggregates GSC (connector ``searchconsole``) and GA4 (connector
``googleanalytics4``) behind one REST endpoint::

    GET https://connectors.windsor.ai/{connector}?api_key=KEY&date_from=YYYY-MM-DD
        &date_to=YYYY-MM-DD&fields=a,b,c[&select_accounts=ACCOUNT]

Connect the Google accounts once in the Windsor.ai dashboard, paste the API
key into Settings, and set the account id per site (optional when the
Windsor workspace holds only one property).
"""

from __future__ import annotations

from datetime import date, timedelta

import requests

from .. import db

BASE = "https://connectors.windsor.ai"
GSC_FIELDS = ["date", "query", "page", "clicks", "impressions", "ctr", "position"]
GA4_FIELDS = ["date", "landing_page", "session_default_channel_group", "sessions", "totalusers", "engaged_sessions", "conversions"]


class WindsorError(RuntimeError):
    pass


def fetch(connector: str, fields: list[str], days: int, api_key: str, account: str | None = None, timeout: int = 120) -> list[dict]:
    params = {
        "api_key": api_key,
        "date_from": (date.today() - timedelta(days=days)).isoformat(),
        "date_to": (date.today() - timedelta(days=1)).isoformat(),
        "fields": ",".join(fields),
        "_renderer": "json",
    }
    if account:
        params["select_accounts"] = account
    try:
        r = requests.get(f"{BASE}/{connector}", params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise WindsorError(f"Windsor.ai request failed: {exc}") from exc
    if r.status_code != 200:
        raise WindsorError(f"Windsor.ai HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    rows = data.get("data", data if isinstance(data, list) else [])
    if not isinstance(rows, list):
        raise WindsorError("Unexpected Windsor.ai response")
    return rows


def _norm_date(v) -> str:
    s = str(v or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else s[:10]


def sync_site(site: dict, days: int = 90) -> dict:
    api_key = db.get_setting("windsor_api_key")
    if not api_key:
        raise WindsorError("Add your Windsor.ai API key in Settings first.")
    result = {"gsc_rows": 0, "ga4_rows": 0, "errors": []}
    try:
        rows = fetch("searchconsole", GSC_FIELDS, days, api_key, site.get("windsor_gsc_account") or None)
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
    try:
        rows = fetch("googleanalytics4", GA4_FIELDS, days, api_key, site.get("windsor_ga4_account") or None)
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
