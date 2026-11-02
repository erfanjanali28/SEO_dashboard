"""Lead generation and conversion tracking plan.

Classifies pages by commercial role, finds conversion elements (forms, CTAs,
tel/mailto/WhatsApp links, downloads, video, chat, cart), and produces a
concrete GA4 + Google Tag Manager event plan: which event to fire, where,
with which trigger and parameters, and whether to mark it as a key event.
Also flags lead-generation gaps, such as high-intent pages without a CTA or form.
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

from . import html_pages, issue

PAGE_TYPES = [
    ("checkout", r"/(checkout|cart|basket|bag)"),
    ("thank-you", r"/(thank|thanks|success|confirmation)"),
    ("pricing", r"/(pricing|plans|price|packages|rates)"),
    ("contact", r"/(contact|get-in-touch|quote|enquir|inquir|request)"),
    ("booking", r"/(book|appointment|schedule|reserve|reservation)"),
    ("demo/trial", r"/(demo|trial|get-started|signup|sign-up|register|join)"),
    ("product", r"/(product|products|shop|item|p)/"),
    ("category", r"/(category|collections?|catalog)/"),
    ("service", r"/(services?|solutions?|what-we-do|treatments?|practice-areas?)"),
    ("location", r"/(locations?|areas?|branches|near|city)"),
    ("blog/article", r"/(blog|news|article|insights|resources|guides?|learn)"),
    ("careers", r"/(careers?|jobs)"),
    ("about", r"/(about|team|company|who-we-are)"),
]
HIGH_INTENT = {"pricing", "contact", "booking", "demo/trial", "product", "service", "location", "checkout"}


def page_type(p: dict) -> str:
    path = urlparse(p["url"]).path.lower()
    if path in ("", "/"):
        return "home"
    for name, pat in PAGE_TYPES:
        if re.search(pat, path):
            return name
    if any("add to cart" in c["text"].lower() for c in p.get("ctas", [])):
        return "product"
    return "other"


def _ev(page, event, element, trigger, params, key_event, priority, why):
    return {"page_url": page, "event_name": event, "element": element, "gtm_trigger": trigger,
            "parameters": params, "key_event": key_event, "priority": priority, "why": why}


def analyze(crawl, ga4_rows: list[dict] | None = None) -> dict:
    pages = html_pages(crawl.pages)
    events, gaps, spots = [], [], []
    tracking = Counter()
    for p in pages:
        for k, v in p.get("tracking", {}).items():
            if v and k != "datalayer_events":
                tracking[k] += 1
    sessions_by_page = Counter()
    for r in ga4_rows or []:
        if r.get("landing_page"):
            sessions_by_page[r["landing_page"]] += r.get("sessions") or 0

    type_counts = Counter()
    seen_global = set()
    for p in pages:
        t = page_type(p)
        type_counts[t] += 1
        url = p["url"]
        lead_forms = [f for f in p.get("forms", []) if not f["is_search"]]
        for f in lead_forms:
            label = f"form#{f['id']}" if f["id"] else f"form → {f['action'] or '(same page)'}"
            is_newsletter = f["fields"] == ["email"] or (len(f["fields"]) <= 2 and f["has_email"] and re.search(r"subscribe|newsletter|join", f["submit_text"], re.I))
            if is_newsletter:
                events.append(_ev(url, "sign_up", label, "Form Submission (wait for tags, check validation) or a dataLayer push on success",
                                  "method=newsletter, form_id, page_location", True, "high", "Newsletter capture shows early funnel interest."))
            else:
                events.append(_ev(url, "form_start", label, "Element Visibility + first input focus (Custom JS listener)",
                                  "form_id, form_name, page_type", False, "medium", "Measures form abandonment (starts minus submits)."))
                events.append(_ev(url, "generate_lead", label, "dataLayer.push({event:'generate_lead'}) on successful submit (preferred), or a thank-you page view",
                                  "form_id, lead_type, value, currency, page_location", True, "critical", "Primary lead conversion. Import it into Google Ads as a conversion."))
        if p.get("tel_links"):
            events.append(_ev(url, "click_to_call", f"{p['tel_links']} tel: link(s)", "Click - Just Links, Click URL starts with 'tel:'",
                              "link_url, page_location, link_position", True, "high", "Phone leads are often the main conversion for local and service businesses."))
        if p.get("mailto_links"):
            events.append(_ev(url, "email_click", f"{p['mailto_links']} mailto: link(s)", "Click - Just Links, Click URL starts with 'mailto:'",
                              "link_url, page_location", True, "medium", "Email contact intent."))
        if p.get("whatsapp_links"):
            events.append(_ev(url, "whatsapp_click", "WhatsApp link(s)", "Click - Just Links, Click URL contains 'wa.me' or 'whatsapp'",
                              "link_url, page_location", True, "high", "Messaging leads."))
        for c in p.get("ctas", [])[:6]:
            txt = c["text"].lower()
            if "cart" in txt:
                ev, key = "add_to_cart", True
            elif re.search(r"book|schedule|appointment|reserv", txt):
                ev, key = "book_appointment_click", True
            elif re.search(r"demo", txt):
                ev, key = "request_demo_click", True
            elif re.search(r"trial|sign ?up|register|get started|start", txt):
                ev, key = "sign_up_click", False
            elif re.search(r"quote|contact|enquire|inquire|talk", txt):
                ev, key = "contact_cta_click", False
            elif "download" in txt:
                ev, key = "file_download", False
            else:
                ev, key = "cta_click", False
            sig = (ev, c["text"], c["href"])
            if sig in seen_global and t not in HIGH_INTENT:
                continue
            seen_global.add(sig)
            events.append(_ev(url, ev, f"{c['tag']} \"{c['text']}\" → {c['href'][:80]}", f"Click - All Elements, Click Text equals \"{c['text']}\"",
                              "cta_text, cta_location, page_type, link_url", key, "high" if key else "medium", "Measures which CTAs drive the funnel."))
        if p.get("downloads"):
            events.append(_ev(url, "file_download", f"{len(p['downloads'])} download link(s)", "GA4 Enhanced Measurement (automatic), or Click URL matches \\.(pdf|docx?|xlsx?|zip)$",
                              "file_name, file_extension, link_url", t in ("blog/article", "service"), "medium", "Lead-magnet and brochure engagement."))
        if p.get("videos"):
            events.append(_ev(url, "video_progress", f"{p['videos']} video(s)", "YouTube Video trigger (Start, Complete, Progress 25/50/75%)",
                              "video_title, video_percent, video_provider", False, "low", "Content engagement."))
        if p.get("chat_widget"):
            events.append(_ev(url, "chat_start", "Live chat widget", "The chat vendor's JS callback, pushed to the dataLayer",
                              "chat_provider, page_location", True, "high", "Chat conversations are leads."))
        if t == "pricing":
            events.append(_ev(url, "view_pricing", "Page view", "Page View, Page Path matches the pricing URL", "plan_viewed", False, "medium", "Sales-qualified intent signal for remarketing audiences."))
        if t == "product":
            events.append(_ev(url, "view_item", "Product detail", "dataLayer ecommerce push (GA4 ecommerce schema)", "items[], value, currency", False, "high", "Required for GA4 ecommerce funnels."))
        if t == "checkout":
            events.append(_ev(url, "begin_checkout", "Checkout start", "dataLayer ecommerce push", "items[], value, currency, coupon", False, "critical", "Checkout funnel."))
            events.append(_ev(url, "purchase", "Order confirmation", "dataLayer ecommerce push on the confirmation page", "transaction_id, value, currency, tax, shipping, items[]", True, "critical", "Revenue attribution."))
        if t == "blog/article":
            events.append(_ev(url, "scroll_depth", "Article body", "Scroll Depth trigger at 50/75/90% (vertical)", "percent_scrolled, content_group", False, "low", "Content engagement quality."))

        # Lead-gen gaps / opportunity spots
        has_conv = bool(lead_forms or p.get("tel_links") or p.get("ctas") or p.get("whatsapp_links") or p.get("chat_widget"))
        traffic = sessions_by_page.get(urlparse(url).path, 0)
        if t in HIGH_INTENT and not has_conv:
            gaps.append({"url": url, "page_type": t, "problem": "High-intent page with no form, CTA or click-to-call",
                         "recommendation": "Add an above-the-fold primary CTA (quote, book or demo), a short 3–4 field form, and a sticky click-to-call button on mobile."})
        elif t == "blog/article" and not lead_forms:
            spots.append({"url": url, "page_type": t, "opportunity": "Content upgrade / lead magnet",
                          "recommendation": "Add an inline lead magnet (checklist, template or calculator) after the second H2, plus a contextual CTA to the matching service page.", "sessions": traffic})
        elif t in ("service", "location") and not lead_forms:
            spots.append({"url": url, "page_type": t, "opportunity": "Embedded quote form",
                          "recommendation": "Embed a short quote/contact form next to the service description, plus trust badges and reviews.", "sessions": traffic})
        elif t == "home" and not lead_forms and not p.get("tel_links"):
            spots.append({"url": url, "page_type": t, "opportunity": "Hero CTA",
                          "recommendation": "Make the primary CTA in the hero section specific (e.g. 'Get a free quote in 2 minutes') and add social proof underneath.", "sessions": traffic})
        if traffic and not has_conv:
            spots.append({"url": url, "page_type": t, "opportunity": "High-traffic page without a conversion path",
                          "recommendation": "Add a contextual CTA and an exit-intent offer.", "sessions": traffic})

    issues = []
    if not (tracking["gtm"] or tracking["ga4"]):
        issues.append(issue("no_analytics", "Tracking", "critical", "No Google Analytics 4 / Tag Manager detected",
                            "Without analytics you cannot measure organic traffic, leads or ROI.",
                            "Install GTM on every page (head + body snippets), add a GA4 configuration tag with consent mode v2, then implement the event plan in the Conversion tab.",
                            [crawl.origin + "/"], impact=9, effort=2))
    elif tracking["gtm"] + tracking["ga4"] < len(pages) * 0.8:
        missing = [p["url"] for p in pages if not (p.get("tracking", {}).get("gtm") or p.get("tracking", {}).get("ga4"))]
        issues.append(issue("partial_analytics", "Tracking", "high", "Analytics tag missing on some pages",
                            f"{len(missing)} pages have no GTM/GA4 snippet, which leaves holes in the data.",
                            "Put the GTM container in the global site template.", missing, impact=6, effort=1))
    if gaps:
        issues.append(issue("lead_gen_gaps", "Conversion", "high", "High-intent pages without a conversion path",
                            f"{len(gaps)} pricing, service, contact or product pages have no form, CTA or phone link.",
                            "Add a clear primary CTA and a short form or click-to-call to each one (see the Conversion tab).",
                            [g["url"] for g in gaps], impact=7, effort=2, details=gaps))
    if not any(t == "thank-you" for t in type_counts) and any(e["event_name"] == "generate_lead" for e in events):
        issues.append(issue("no_thank_you", "Tracking", "medium", "No thank-you / confirmation page",
                            "Forms submit without a dedicated success URL, which makes conversion tracking fragile.",
                            "Redirect successful submissions to /thank-you/ (noindex) or push a dataLayer 'generate_lead' event on success.",
                            [], impact=4, effort=2))

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    events.sort(key=lambda e: (order[e["priority"]], e["page_url"]))
    key_events = sorted({e["event_name"] for e in events if e["key_event"]})
    setup = [
        "Install a GTM container site-wide and a GA4 Configuration (Google tag) with Consent Mode v2.",
        "Enable GA4 Enhanced Measurement (scrolls, outbound clicks, site search, video, file downloads).",
        "Create the custom events below in GTM and test them with Tag Assistant / GA4 DebugView.",
        f"Mark these as Key events in GA4: {', '.join(key_events) or 'generate_lead'}.",
        "Register custom dimensions for form_id, cta_text, page_type and lead_type.",
        "Link GA4 to Google Ads and Search Console. Import key events as Ads conversions.",
        "Add hidden UTM / gclid fields to forms and pass them to the CRM for offline conversion import.",
        "Build a Looker Studio (or this dashboard's) report: organic sessions → engaged sessions → key events by landing page.",
    ]
    return {"issues": issues, "events": events, "lead_gaps": gaps, "opportunities": spots[:200],
            "page_types": dict(type_counts), "tracking_detected": dict(tracking), "setup_steps": setup,
            "key_events": key_events}
