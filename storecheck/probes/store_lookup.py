"""Is this app public on either store? Two plain requests, no credentials.

Apple's lookup endpoint returns a result only for a published app. Google's
details page returns 404 until the app is public. Both were checked against a
real app in review on 2026-09-06 and both said "not public", which was true.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from ..schema import make_probe

UA = "Mozilla/5.0 (X11; Linux x86_64) storecheck"


def fetch(url: str, timeout: int = 20) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.geturl()


def apple(bundle_id: str) -> dict:
    url = f"https://itunes.apple.com/lookup?bundleId={bundle_id}"
    try:
        status, body, _ = fetch(url)
    except Exception as e:  # network down: say so, never guess
        return make_probe("store.apple.public", None, source_kind="url", source_ref=url,
                          provenance="needs-console-read", error=f"lookup failed: {e}")
    data = json.loads(body) if status == 200 else {}
    results = data.get("results", [])
    value = {"public": bool(results)}
    if results:
        r = results[0]
        value.update({"version": r.get("version"), "app_id": r.get("trackId"), "name": r.get("trackName"),
                      "rating": r.get("contentAdvisoryRating"), "released": r.get("currentVersionReleaseDate")})
    return make_probe("store.apple.public", value, source_kind="url", source_ref=url)


def google(package: str) -> dict:
    url = f"https://play.google.com/store/apps/details?id={package}&hl=en"
    try:
        status, body, final = fetch(url)
    except Exception as e:
        return make_probe("store.google.public", None, source_kind="url", source_ref=url,
                          provenance="needs-console-read", error=f"lookup failed: {e}")
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    title = re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else None
    return make_probe("store.google.public", {"public": status == 200 and bool(title), "http": status, "title": title},
                      source_kind="url", source_ref=url)


def probe_ids(bundle_id: str | None, package: str | None) -> list[dict]:
    out = []
    if bundle_id:
        out.append(apple(bundle_id))
    if package:
        out.append(google(package))
    return out


def self_test() -> None:
    # No network in a self-test: only the pure parts.
    assert re.sub(r"<[^>]+>", "", "<span>Sample App</span>").strip() == "Sample App"
