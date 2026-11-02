"""FastAPI application: JSON API, file uploads, exports, and the dashboard SPA.

Run with ``python webapp/run.py`` (see webapp/README.md). Set
``SEO_DASHBOARD_PASSWORD`` to require HTTP Basic auth (user ``admin``).
"""

from __future__ import annotations

import base64
import os
import re
import secrets
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from url_safety import validate_url

from . import audit, db, exports, metrics, report, scheduler
from .integrations import windsor

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
SECRET_SETTINGS = {"windsor_api_key", "pagespeed_api_key", "dataforseo_password"}
SETTING_KEYS = ["windsor_api_key", "pagespeed_api_key", "pagespeed_enabled", "dataforseo_login", "dataforseo_password", "dataforseo_location_code"]
IMAGE_MAGIC = {b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"GIF8": ".gif", b"RIFF": ".webp"}


@asynccontextmanager
async def lifespan(_app):
    db.init_db()
    if os.environ.get("SEO_DASHBOARD_SCHEDULER", "1") != "0":
        scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Claude SEO Dashboard", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    password = os.environ.get("SEO_DASHBOARD_PASSWORD")
    if password:
        header = request.headers.get("authorization", "")
        ok = False
        if header.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
                ok = secrets.compare_digest(pw, password) and user == os.environ.get("SEO_DASHBOARD_USER", "admin")
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="SEO Dashboard"'})
    return await call_next(request)


# ---------------- models ----------------
class ClientIn(BaseModel):
    name: str
    company: str | None = None
    email: str | None = None
    industry: str | None = None
    notes: str | None = None


class SiteIn(BaseModel):
    client_id: int
    url: str
    industry: str | None = None
    location: str | None = None
    language: str | None = "en"
    max_pages: int = 150
    interval_hours: int = 0
    seed_keywords: str | None = None
    competitors: str | None = None
    windsor_gsc_account: str | None = None
    windsor_ga4_account: str | None = None


def _404(obj, what="Not found"):
    if not obj:
        raise HTTPException(404, what)
    return obj


def _normalize_site_url(url: str) -> str:
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    if not validate_url(url):
        raise HTTPException(400, "URL is not a valid public http(s) address")
    return url


# ---------------- clients ----------------
@app.get("/api/clients")
def list_clients():
    clients = db.rows("SELECT * FROM clients ORDER BY name COLLATE NOCASE")
    for c in clients:
        c["sites"] = db.rows(
            "SELECT s.id, s.url, s.interval_hours, s.last_run_at, "
            "(SELECT score FROM audits a WHERE a.site_id = s.id AND a.status='done' ORDER BY a.id DESC LIMIT 1) score "
            "FROM sites s WHERE s.client_id = ?", (c["id"],))
    return clients


@app.post("/api/clients")
def create_client(c: ClientIn):
    cid = db.execute("INSERT INTO clients(name, company, email, industry, notes, created_at) VALUES(?,?,?,?,?,?)",
                     (c.name, c.company, c.email, c.industry, c.notes, db.now_iso()))
    return db.row("SELECT * FROM clients WHERE id = ?", (cid,))


@app.get("/api/clients/{cid}")
def get_client(cid: int):
    c = _404(db.row("SELECT * FROM clients WHERE id = ?", (cid,)))
    c["sites"] = db.rows("SELECT * FROM sites WHERE client_id = ? ORDER BY id", (cid,))
    for s in c["sites"]:
        s["latest"] = db.row("SELECT id, status, score, started_at, progress FROM audits WHERE site_id = ? ORDER BY id DESC LIMIT 1", (s["id"],))
    return c


@app.put("/api/clients/{cid}")
def update_client(cid: int, c: ClientIn):
    _404(db.row("SELECT id FROM clients WHERE id = ?", (cid,)))
    db.execute("UPDATE clients SET name=?, company=?, email=?, industry=?, notes=? WHERE id=?",
               (c.name, c.company, c.email, c.industry, c.notes, cid))
    return db.row("SELECT * FROM clients WHERE id = ?", (cid,))


@app.delete("/api/clients/{cid}")
def delete_client(cid: int):
    c = _404(db.row("SELECT * FROM clients WHERE id = ?", (cid,)))
    if c.get("photo"):
        try:
            os.remove(os.path.join(db.UPLOAD_DIR, os.path.basename(c["photo"])))
        except OSError:
            pass
    db.execute("DELETE FROM clients WHERE id = ?", (cid,))
    return {"ok": True}


@app.post("/api/clients/{cid}/photo")
async def upload_photo(cid: int, file: UploadFile = File(...)):
    c = _404(db.row("SELECT * FROM clients WHERE id = ?", (cid,)))
    data = await file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Image must be under 5 MB")
    ext = next((x for magic, x in IMAGE_MAGIC.items() if data.startswith(magic)), None)
    if not ext or (ext == ".webp" and data[8:12] != b"WEBP"):
        raise HTTPException(400, "Upload a PNG, JPEG, GIF or WebP image")
    name = f"client{cid}-{uuid.uuid4().hex[:10]}{ext}"
    with open(os.path.join(db.UPLOAD_DIR, name), "wb") as fh:
        fh.write(data)
    if c.get("photo"):
        try:
            os.remove(os.path.join(db.UPLOAD_DIR, os.path.basename(c["photo"])))
        except OSError:
            pass
    db.execute("UPDATE clients SET photo = ? WHERE id = ?", (name, cid))
    return {"photo": name}


@app.get("/uploads/{name}")
def get_upload(name: str):
    if not re.fullmatch(r"client\d+-[0-9a-f]{10}\.(png|jpg|gif|webp)", name):
        raise HTTPException(404)
    path = os.path.join(db.UPLOAD_DIR, name)
    _404(os.path.exists(path))
    return FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})


# ---------------- sites ----------------
@app.post("/api/sites")
def create_site(s: SiteIn):
    _404(db.row("SELECT id FROM clients WHERE id = ?", (s.client_id,)), "Client not found")
    url = _normalize_site_url(s.url)
    sid = db.execute(
        "INSERT INTO sites(client_id, url, industry, location, language, max_pages, interval_hours, seed_keywords, competitors, "
        "windsor_gsc_account, windsor_ga4_account, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (s.client_id, url, s.industry, s.location, s.language, max(5, min(s.max_pages, 2000)), max(0, s.interval_hours),
         s.seed_keywords, s.competitors, s.windsor_gsc_account, s.windsor_ga4_account, db.now_iso()))
    return db.row("SELECT * FROM sites WHERE id = ?", (sid,))


@app.put("/api/sites/{sid}")
def update_site(sid: int, s: SiteIn):
    _404(db.row("SELECT id FROM sites WHERE id = ?", (sid,)))
    db.execute(
        "UPDATE sites SET url=?, industry=?, location=?, language=?, max_pages=?, interval_hours=?, seed_keywords=?, competitors=?, "
        "windsor_gsc_account=?, windsor_ga4_account=? WHERE id=?",
        (_normalize_site_url(s.url), s.industry, s.location, s.language, max(5, min(s.max_pages, 2000)), max(0, s.interval_hours),
         s.seed_keywords, s.competitors, s.windsor_gsc_account, s.windsor_ga4_account, sid))
    return db.row("SELECT * FROM sites WHERE id = ?", (sid,))


@app.delete("/api/sites/{sid}")
def delete_site(sid: int):
    db.execute("DELETE FROM sites WHERE id = ?", (sid,))
    return {"ok": True}


@app.get("/api/sites/{sid}")
def get_site(sid: int):
    s = _404(db.row("SELECT * FROM sites WHERE id = ?", (sid,)))
    s["client"] = db.row("SELECT * FROM clients WHERE id = ?", (s["client_id"],))
    s["history"] = metrics.audit_history(sid)
    s["latest"] = db.row("SELECT id, status, progress, score, started_at, finished_at, error FROM audits WHERE site_id = ? ORDER BY id DESC LIMIT 1", (sid,))
    s["latest_done"] = db.row("SELECT id FROM audits WHERE site_id = ? AND status='done' ORDER BY id DESC LIMIT 1", (sid,))
    return s


@app.post("/api/sites/{sid}/audit")
def start_audit(sid: int):
    _404(db.row("SELECT id FROM sites WHERE id = ?", (sid,)))
    return {"audit_id": audit.start_audit(sid)}


@app.post("/api/sites/{sid}/sync")
def sync(sid: int, days: int = 90):
    s = _404(db.row("SELECT * FROM sites WHERE id = ?", (sid,)))
    try:
        return windsor.sync_site(s, days=max(7, min(days, 480)))
    except windsor.WindsorError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/sites/{sid}/search")
def search(sid: int, days: int = 90):
    _404(db.row("SELECT id FROM sites WHERE id = ?", (sid,)))
    return {"search": metrics.search_performance(sid, days), "analytics": metrics.analytics_summary(sid, days)}


@app.get("/api/sites/{sid}/changes")
def changes(sid: int):
    """Issues new / resolved / changed between the last two completed audits."""
    two = db.rows("SELECT * FROM audits WHERE site_id = ? AND status='done' ORDER BY id DESC LIMIT 2", (sid,))
    if len(two) < 2:
        return {"available": False}
    cur, prev = db.load_audit_result(two[0]), db.load_audit_result(two[1])
    ci = {i["id"]: i for i in cur["issues"]}
    pi = {i["id"]: i for i in prev["issues"]}
    return {
        "available": True, "score_change": cur["scores"]["overall"] - prev["scores"]["overall"],
        "new": [ci[k] | {"urls": ci[k]["urls"][:10]} for k in ci.keys() - pi.keys()],
        "resolved": [{"id": k, "title": pi[k]["title"], "severity": pi[k]["severity"]} for k in pi.keys() - ci.keys()],
        "changed": [{"id": k, "title": ci[k]["title"], "before": pi[k]["count"], "after": ci[k]["count"]}
                    for k in ci.keys() & pi.keys() if ci[k]["count"] != pi[k]["count"]],
        "categories": {g: {"before": prev["scores"]["categories"].get(g), "after": v} for g, v in cur["scores"]["categories"].items()},
    }


# ---------------- audits ----------------
@app.get("/api/audits/{aid}")
def audit_status(aid: int):
    return _404(db.row("SELECT id, site_id, status, progress, score, started_at, finished_at, error FROM audits WHERE id = ?", (aid,)))


@app.get("/api/audits/{aid}/result")
def audit_result(aid: int):
    a = _404(db.row("SELECT * FROM audits WHERE id = ?", (aid,)))
    res = db.load_audit_result(a)
    if not res:
        raise HTTPException(409, f"Audit status: {a['status']}")
    return JSONResponse(res)


def _export_ctx(aid: int):
    a = _404(db.row("SELECT * FROM audits WHERE id = ?", (aid,)))
    res = db.load_audit_result(a)
    if not res:
        raise HTTPException(409, "Audit not finished")
    site = db.row("SELECT * FROM sites WHERE id = ?", (a["site_id"],))
    client = db.row("SELECT * FROM clients WHERE id = ?", (site["client_id"],))
    return res, client, site, metrics.audit_history(site["id"]), metrics.search_performance(site["id"])


def _fname(site, suffix):
    host = re.sub(r"[^a-z0-9.-]+", "-", site["url"].split("//")[-1].lower()).strip("-")
    return f"{host}-{suffix}"


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.get("/api/audits/{aid}/export.xlsx")
def export_full(aid: int):
    res, client, site, hist, search_data = _export_ctx(aid)
    data = exports.full_report_xlsx(res, client, site, hist, search_data)
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{_fname(site, "seo-audit.xlsx")}"'})


@app.get("/api/audits/{aid}/internal-links.xlsx")
def export_links(aid: int):
    res, _client, site, _h, _s = _export_ctx(aid)
    return Response(exports.internal_links_xlsx(res), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{_fname(site, "internal-links.xlsx")}"'})


@app.get("/api/audits/{aid}/report.html", response_class=HTMLResponse)
def export_html(aid: int, download: int = 0):
    res, client, site, hist, search_data = _export_ctx(aid)
    html = report.render(res, client, site, hist, search_data)
    headers = {"Content-Disposition": f'attachment; filename="{_fname(site, "seo-report.html")}"'} if download else {}
    return HTMLResponse(html, headers=headers)


# ---------------- settings ----------------
@app.get("/api/settings")
def get_settings():
    out = {}
    for k in SETTING_KEYS:
        v = db.get_setting(k)
        out[k] = ("•" * 8 + v[-4:]) if v and k in SECRET_SETTINGS else v
    return out


@app.put("/api/settings")
def put_settings(payload: dict):
    for k, v in payload.items():
        if k not in SETTING_KEYS:
            continue
        if isinstance(v, str) and v.startswith("•"):
            continue  # masked value echoed back unchanged
        db.set_setting(k, (v or "").strip() or None)
    return get_settings()


# ---------------- SPA ----------------
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))
