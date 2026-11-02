"""Optional DataForSEO search-volume provider for keyword research.

Uses the Google Ads search volume live endpoint. Needs the ``dataforseo_login``
and ``dataforseo_password`` settings; the research falls back to
autocomplete + GSC data when they are absent.
"""

from __future__ import annotations

import requests

from .. import db

ENDPOINT = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"


def provider_for(site: dict):
    login, password = db.get_setting("dataforseo_login"), db.get_setting("dataforseo_password")
    if not (login and password):
        return None
    location = db.get_setting("dataforseo_location_code") or "2840"  # United States
    lang = site.get("language") or "en"

    def fetch(keywords: list[str]) -> dict:
        out = {}
        for i in range(0, len(keywords), 700):
            batch = [k for k in keywords[i:i + 700] if len(k) <= 80 and len(k.split()) <= 10]
            body = [{"keywords": batch, "location_code": int(location), "language_code": lang}]
            r = requests.post(ENDPOINT, auth=(login, password), json=body, timeout=120)
            for task in r.json().get("tasks", []) or []:
                for item in task.get("result") or []:
                    out[item["keyword"].lower()] = {"search_volume": item.get("search_volume"),
                                                    "cpc": item.get("cpc"), "competition": item.get("competition")}
        return out
    return fetch
