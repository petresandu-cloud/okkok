# Copyright (C) 2026 Editerra AB. SPDX-License-Identifier: AGPL-3.0-or-later
"""Can machines reach and understand this site? A machine-accessibility audit.

    python3 tools/aiready.py https://example.com [more urls]

Checks the things AI search crawlers and answer engines need: a robots policy that
admits them, a sitemap, an llms.txt, and on the page itself a title, a description,
a canonical address, structured data, Open Graph tags, one h1 and a language.
Every line says what was fetched and what was found; the score is the count of
checks met, nothing cleverer. Standard library only.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BOTS = ("OAI-SearchBot", "GPTBot", "ChatGPT-User", "PerplexityBot", "ClaudeBot", "Claude-SearchBot", "Googlebot", "Google-Extended", "Bingbot")
UA = "Mozilla/5.0 (compatible; okkok-aiready/0.1)"


def get(url: str) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(400_000).decode("utf-8", "replace"), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, "", ""
    except Exception as e:  # noqa: BLE001
        return 0, str(e), ""


def robots_verdict(text: str) -> dict:
    """Which of the known bots are allowed by robots.txt. A bot with no group falls under '*'."""
    groups, current = {}, []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            current.append(v.lower())
            groups.setdefault(v.lower(), [])
        elif k in ("allow", "disallow") and current:
            for ua in current:
                groups[ua].append((k, v))
        else:
            if k not in ("sitemap", "crawl-delay", "host"):
                pass
            if k != "user-agent":
                current = current if k in ("allow", "disallow") else []
    out = {}
    for bot in BOTS:
        rules = groups.get(bot.lower(), groups.get("*", []))
        blocked_all = any(k == "disallow" and v == "/" for k, v in rules)
        out[bot] = "blocked" if blocked_all else "allowed"
    sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", text)
    return {"bots": out, "sitemaps": sitemaps}


def audit(url: str) -> dict:
    base = url.rstrip("/")
    parts = urllib.parse.urlsplit(base)
    root = f"{parts.scheme}://{parts.netloc}"
    checks = []

    def check(name, ok, found):
        checks.append({"check": name, "ok": bool(ok), "found": found})

    st, body, _ = get(root + "/robots.txt")
    if st == 200 and body.strip():
        rv = robots_verdict(body)
        blocked = [b for b, s in rv["bots"].items() if s == "blocked"]
        check("robots.txt present", True, f"{len(body)} bytes")
        check("AI and search crawlers admitted", not blocked, "blocked: " + ", ".join(blocked) if blocked else "all of " + ", ".join(BOTS))
        check("robots.txt names a sitemap", bool(rv["sitemaps"]), ", ".join(rv["sitemaps"]) or "none")
    else:
        check("robots.txt present", False, f"HTTP {st}")
        check("AI and search crawlers admitted", False, "no robots.txt: crawlers assume allowed, but OpenAI and Bing ask for an explicit policy")
        check("robots.txt names a sitemap", False, "no robots.txt")
    for path in (base + "/sitemap.xml", root + "/sitemap.xml"):
        st, body, _ = get(path)
        if st == 200 and "<urlset" in body or "<sitemapindex" in body:
            check("sitemap.xml present", True, f"{path}: {body.count('<loc>')} locations")
            break
    else:
        check("sitemap.xml present", False, "HTTP 404 at the site and the root")
    for path in (base + "/llms.txt", root + "/llms.txt"):
        st, body, _ = get(path)
        if st == 200 and body.strip().startswith("#"):
            check("llms.txt present", True, f"{path}: {len(body)} bytes")
            break
    else:
        check("llms.txt present", False, "none (a plain-text summary for language models; a convention, not a standard, but widely read)")

    st, html, ctype = get(base + "/")
    check("home page answers 200 as HTML", st == 200 and "html" in ctype, f"HTTP {st} {ctype}")
    head = html[:60000]
    title = re.search(r"<title[^>]*>([^<]{1,200})", head, re.I)
    check("title", bool(title), title.group(1).strip() if title else "none")
    desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{20,})', head, re.I)
    check("meta description", bool(desc), (desc.group(1)[:90] + "…") if desc else "none")
    canon = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', head, re.I)
    check("canonical address", bool(canon), canon.group(1) if canon else "none")
    lds = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S)
    types = []
    for ld in lds:
        try:
            d = json.loads(ld)
            items = d if isinstance(d, list) else [d]
            for it in items:
                if isinstance(it, dict):
                    t = it.get("@type")
                    types += t if isinstance(t, list) else [t]
                    for g in it.get("@graph", []) if isinstance(it.get("@graph"), list) else []:
                        types.append(g.get("@type"))
        except json.JSONDecodeError:
            types.append("INVALID JSON-LD")
    check("structured data (JSON-LD)", bool(types) and "INVALID JSON-LD" not in types, ", ".join(str(t) for t in types) or "none")
    og = re.findall(r'<meta[^>]+property=["\']og:(\w+)', head, re.I)
    check("Open Graph tags", {"title", "description"} <= {o.lower() for o in og}, ", ".join(sorted(set(og))) or "none")
    h1 = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    check("exactly one h1", len(h1) == 1, f"{len(h1)} found" + (": " + re.sub('<[^>]+>', '', h1[0]).strip()[:80] if h1 else ""))
    lang = re.search(r'<html[^>]+lang=["\']([^"\']+)', head, re.I)
    check("html lang", bool(lang), lang.group(1) if lang else "none")
    score = round(100 * sum(c["ok"] for c in checks) / len(checks))
    return {"url": base, "score": score, "checks": checks}


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    worst = 0
    for url in argv:
        r = audit(url)
        print(f"\n{r['url']}: machine accessibility {r['score']}/100")
        for c in r["checks"]:
            print(f"  {'ok ' if c['ok'] else 'NO '} {c['check']:<36} {c['found']}")
        worst = max(worst, 0 if r["score"] == 100 else 1)
    return worst


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
