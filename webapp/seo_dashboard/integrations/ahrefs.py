"""Ahrefs API v3 connector.

Authentication is an Ahrefs API key (Account settings → API keys), sent as
``Authorization: Bearer KEY``. Ahrefs has no username/password API.

Free endpoints (no API units): subscription limits, the project list, the
public Domain Rating and the GSC Insights history of a project. Everything
under Site Explorer costs units; on a plan with 0 units Ahrefs answers
"API units limit reached", raised here as ``UnitsError`` so callers can
fall back to the free data instead of failing the whole analysis.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import requests

from .. import db

BASE = "https://api.ahrefs.com/v3"


class AhrefsError(RuntimeError):
    pass


class UnitsError(AhrefsError):
    """The workspace has no API units left for a paid endpoint."""


def _key(api_key: str | None = None) -> str:
    key = api_key or db.get_setting("ahrefs_api_key")
    if not key:
        raise AhrefsError("Add your Ahrefs API key in Settings first.")
    return key


def get(path: str, params: dict | None = None, api_key: str | None = None, timeout: int = 120) -> dict:
    try:
        r = requests.get(f"{BASE}/{path}", params={**(params or {}), "output": "json"},
                         headers={"Authorization": f"Bearer {_key(api_key)}", "Accept": "application/json"}, timeout=timeout)
    except requests.RequestException as exc:
        raise AhrefsError(f"Could not reach Ahrefs: {exc}") from exc
    try:
        data = r.json()
    except ValueError:
        data = {"error": r.text[:200]}
    if r.status_code == 200 and not (isinstance(data, dict) and data.get("error")):
        return data
    msg = str(data.get("error") if isinstance(data, dict) else data)[:300]
    if "units" in msg.lower() and "limit" in msg.lower():
        raise UnitsError(msg)
    if r.status_code in (401, 403):
        raise AhrefsError(
            f"Ahrefs refused the request (HTTP {r.status_code}): {msg or 'no reason given'}. "
            "Check that you copied the whole key from Ahrefs → Account settings → API keys (no spaces), "
            "that the key has not been revoked or expired, and that your Ahrefs plan includes API access.")
    raise AhrefsError(f"Ahrefs HTTP {r.status_code}: {msg}")


def limits(api_key: str | None = None) -> dict:
    return get("subscription-info/limits-and-usage", api_key=api_key).get("limits_and_usage", {})


def projects(api_key: str | None = None) -> list[dict]:
    return get("management/projects", api_key=api_key).get("projects", [])


def domain_of(url: str) -> str:
    host = (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower()
    return host.removeprefix("www.")


def match_project(site_url: str, project_list: list[dict]) -> dict | None:
    dom = domain_of(site_url)
    exact = [p for p in project_list if domain_of(p.get("url", "")) == dom]
    if exact:
        # The skill's projects sometimes exist twice (apex and www): prefer the one with Rank Tracker keywords.
        return sorted(exact, key=lambda p: -(p.get("keyword_count") or 0))[0]
    return next((p for p in project_list if dom.endswith("." + domain_of(p.get("url", ""))) and domain_of(p.get("url", ""))), None)


def free_domain_rating(domain: str, api_key: str | None = None) -> float | None:
    try:
        data = get("public/domain-rating-free", {"targets": domain}, api_key=api_key)
    except AhrefsError:
        return None
    for t in (data.get("domain_rating") or {}).get("targets", []):
        return t.get("domain_rating")
    return None


def gsc_history(project_id, date_from: str, api_key: str | None = None) -> list[dict]:
    try:
        return get("gsc/performance-history", {"project_id": project_id, "date_from": date_from,
                                               "history_grouping": "monthly"}, api_key=api_key).get("metrics", [])
    except AhrefsError:
        return []


def country_for(site: dict) -> str:
    configured = (db.get_setting("ahrefs_country") or "").strip().upper()
    if re.fullmatch(r"[A-Z]{2}", configured):
        return configured
    tld = domain_of(site["url"]).rsplit(".", 1)[-1].upper()
    return {"UK": "GB", "COM": "US", "NET": "US", "ORG": "US", "IO": "US", "EU": "DE"}.get(tld, tld if len(tld) == 2 else "US")
