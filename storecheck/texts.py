"""Every text the app presents to a person or a reviewer, gathered in one place.

The binary says what the app does. These texts say what the app claims to do,
and the stores judge the claims: listing, purpose strings, the in-app
disclosures, the privacy policy, the deletion page, the review notes. A rule
about wording is judged by reading these against the rule, not by matching
words. This module only gathers; judging is the reader's job.
"""

from __future__ import annotations

import re
from pathlib import Path

from .corpus import fetch_url, main_content, read_html
from .schema import make_probe, read_json


def probe(app_dir: Path, probes: list[dict], offline: bool = False) -> dict:
    """The gathered texts as one fact, so quotations from them can be verified later."""
    t = gather(app_dir, offline=offline, probes=probes)
    return make_probe("app.texts", t, source_kind="file", source_ref=str(app_dir / "storecheck" / "texts"))


def gather(app_dir: Path, offline: bool = False, probes: list[dict] | None = None) -> dict:
    sc = app_dir / "storecheck"
    if probes is None:
        probes = read_json(sc / "probes.json")
    by = {p["id"]: p["value"] for p in probes}
    out = {"listing": by.get("listing.text") or {}, "purpose_strings": {}, "pages": {}, "in_app": {}}
    info = by.get("ios.built.info") or by.get("ios.source.info") or {}
    out["purpose_strings"] = info.get("purpose_strings", {})
    for key in ("listing.privacy_policy_page", "listing.support_page"):
        v = by.get(key)
        if v and v.get("text"):
            out["pages"][key.split(".")[-1]] = {"url": v.get("final_url"), "heading": v.get("heading"), "text": v["text"]}
    listing = out["listing"]
    if not offline and listing.get("deletion_url"):
        try:
            st, body, final = fetch_url(listing["deletion_url"])
            h, blocks = read_html(main_content(body))
            out["pages"]["deletion_page"] = {"url": final, "heading": h, "text": " ".join(t for _, t in blocks)[:20000]}
        except Exception as e:
            out["pages"]["deletion_page"] = {"url": listing["deletion_url"], "error": str(e)}
    # In-app copy the app repository chooses to expose for review: any *.txt or *.md
    # under storecheck/texts/, named for the screen it belongs to.
    tdir = sc / "texts"
    if tdir.is_dir():
        for f in sorted(tdir.iterdir()):
            if f.suffix in (".txt", ".md") and f.is_file():
                out["in_app"][f.stem] = f.read_text(encoding="utf-8")[:20000]
    return out
