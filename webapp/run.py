#!/usr/bin/env python3
"""Start the Claude SEO Dashboard.

Usage:
    python webapp/run.py [--host 127.0.0.1] [--port 8000]

Environment:
    SEO_DASHBOARD_PASSWORD   enable HTTP Basic auth (user: admin, or SEO_DASHBOARD_USER)
    SEO_DASHBOARD_DATA       data directory (SQLite DB + uploaded client photos)
    SEO_DASHBOARD_SCHEDULER  set to 0 to disable scheduled audits
    WINDSOR_API_KEY, PAGESPEED_API_KEY  optional defaults for the Settings page
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    import uvicorn
    uvicorn.run("seo_dashboard.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
