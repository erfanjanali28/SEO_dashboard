"""Tiny local website with deliberate SEO problems, used by the tests."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NAV = '<nav><a href="/">Home</a> <a href="/services/plumbing-repair/">Plumbing repair</a> <a href="/blog/">Blog</a> <a href="/contact">Contact</a></nav>'
LONG = ("Emergency plumbing repair keeps your home safe. Our licensed plumbers fix leaking pipes, burst pipes and "
        "blocked drains across the city every day. ") * 30

PAGES = {
    "/": f"""<!doctype html><html lang="en"><head><title>Acme Plumbing</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Acme Plumbing offers emergency plumbing repair, drain cleaning and water heater installation 24/7 across the city.">
<link rel="canonical" href="/"><script type="application/ld+json">{{"@context":"https://schema.org","@type":"Organization","name":"Acme"}}</script>
<script src="https://www.googletagmanager.com/gtm.js?id=GTM-ABC123"></script></head>
<body>{NAV}<main><h1>Emergency plumbing repair</h1><p>{LONG}</p>
<h2>How much does emergency plumbing repair cost?</h2><p>Most emergency plumbing repair visits cost between 150 and 450 dollars depending on the problem, time of day and parts needed for the job today.</p>
<a href="/services/plumbing-repair/">plumbing repair services</a> <a href="/old-page">Old offers</a> <a href="/moved">Moved page</a>
<a href="tel:+15551234567">Call now</a> <a href="/contact">Get a quote</a></main></body></html>""",
    "/services/plumbing-repair/": f"""<!doctype html><html><head><title>Plumbing Repair</title></head>
<body>{NAV}<main><h1>Plumbing repair</h1><h3>Skipped level</h3><p>{LONG}</p><img src="/pipe.jpg"></main></body></html>""",
    "/blog/": f"""<!doctype html><html lang="en"><head><title>Blog</title><meta name="viewport" content="width=device-width"></head>
<body>{NAV}<main><h1>Blog</h1><a href="/blog/drain-cleaning-tips/">Read more</a></main></body></html>""",
    "/blog/drain-cleaning-tips/": f"""<!doctype html><html lang="en"><head><title>Blog</title><meta name="viewport" content="width=device-width">
<meta name="robots" content="noindex"></head><body>{NAV}<main><h1>Drain cleaning tips</h1><p>In today's fast-paced world, look no further. Drain cleaning matters.</p></main></body></html>""",
    "/contact": f"""<!doctype html><html lang="en"><head><title>Contact Acme Plumbing for a free quote today</title><meta name="viewport" content="width=device-width"></head>
<body>{NAV}<main><h1>Contact</h1><form action="/send" method="post"><input name="name"><input type="email" name="email"><textarea name="msg"></textarea><button type="submit">Send request</button></form></main></body></html>""",
    "/orphan-landing/": f"""<!doctype html><html lang="en"><head><title>Water heater installation</title><meta name="viewport" content="width=device-width"></head>
<body><main><h1>Water heater installation</h1><p>{LONG}</p></main></body></html>""",
    "/robots.txt": "User-agent: *\nDisallow: /private/\nUser-agent: GPTBot\nDisallow: /\nSitemap: http://127.0.0.1:{port}/sitemap.xml\n",
    "/sitemap.xml": """<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>http://127.0.0.1:{port}/</loc><lastmod>2020-01-01</lastmod></url>
<url><loc>http://127.0.0.1:{port}/orphan-landing/</loc></url>
<url><loc>http://127.0.0.1:{port}/blog/drain-cleaning-tips/</loc></url></urlset>""",
}
REDIRECTS = {"/moved": "/services/plumbing-repair/"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, head_only=False):
        port = self.server.server_address[1]
        path = self.path.split("?")[0]
        if path in REDIRECTS:
            self.send_response(301)
            self.send_header("Location", REDIRECTS[path])
            self.end_headers()
            return
        body = PAGES.get(path)
        if body is None:
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if not head_only:
                self.wfile.write(b"<html><body>Not found</body></html>")
            return
        body = body.replace("{port}", str(port)) if path.endswith((".txt", ".xml")) else body
        ctype = "text/plain" if path.endswith(".txt") else "application/xml" if path.endswith(".xml") else "text/html; charset=utf-8"
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def do_GET(self):
        self._send()

    def do_HEAD(self):
        self._send(head_only=True)


def serve() -> tuple[ThreadingHTTPServer, int]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]
