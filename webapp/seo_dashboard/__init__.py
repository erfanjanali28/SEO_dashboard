"""Claude SEO Dashboard: a self-hosted, multi-client technical SEO web app.

The package crawls a site on a schedule, runs technical, content, linking,
keyword, AI-search (GEO/AIO), conversion-tracking and off-page analyzers,
stores every run in SQLite so trends can be charted, and exports reports to
Excel and printable HTML.
"""

import os
import sys

__version__ = "1.0.0"

# Reuse the repository's canonical SSRF-safe fetch layer (scripts/url_safety.py)
# instead of duplicating it. The webapp lives one directory below the repo root.
_REPO_SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts",
)
if os.path.isdir(_REPO_SCRIPTS) and _REPO_SCRIPTS not in sys.path:
    sys.path.insert(0, _REPO_SCRIPTS)
