"""The store listing text, from a small TOML file the app keeps, and the privacy policy page it links.

Until a console is read, the listing the tool can see is the one the app
repository declares in storecheck/listing.toml. When the file is absent the
listing probes are null with needs-console-read, and every rule that reads
the listing is UNKNOWN rather than silently passed.

    [listing]
    name = "Sample App"
    privacy_policy_url = "https://..."
    support_url = "https://..."
    deletion_url = "https://..."          # optional

    [listing.apple]
    subtitle = "..."
    description = "..."
    keywords = "..."

    [listing.google]
    short_description = "..."
    full_description = "..."
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from ..corpus import fetch_url, main_content, read_html
from ..schema import file_probe, make_probe

LISTING_FILE = "storecheck/listing.toml"


def probe(app_dir: Path, offline: bool = False) -> list[dict]:
    f = app_dir / LISTING_FILE
    if not f.is_file():
        why = f"no {LISTING_FILE}: the listing was not read, and no console was read"
        return [make_probe("listing.text", None, source_kind="file", source_ref=str(f), provenance="needs-console-read", error=why),
                make_probe("listing.privacy_policy_page", None, source_kind="file", source_ref=str(f), provenance="needs-console-read", error=why)]
    data = tomllib.loads(f.read_text(encoding="utf-8")).get("listing", {})
    has_text = any(data.get(st) for st in ("apple", "google"))
    if not data.get("name") or not has_text:
        # An empty listing must not read as a listing that passes every text rule.
        why = f"{LISTING_FILE} carries no name or no store text; fill in [listing] with name and [listing.apple] or [listing.google]"
        return [make_probe("listing.text", None, source_kind="file", source_ref=str(f), provenance="needs-console-read", error=why),
                make_probe("listing.privacy_policy_page", None, source_kind="file", source_ref=str(f), provenance="needs-console-read", error=why)]
    out = [file_probe("listing.text", data, f)]
    for key, pid in (("privacy_policy_url", "listing.privacy_policy_page"), ("support_url", "listing.support_page")):
        url = data.get(key)
        if not url:
            out.append(make_probe(pid, None, source_kind="file", source_ref=str(f), error=f"listing.toml names no {key}"))
        elif offline:
            out.append(make_probe(pid, None, source_kind="url", source_ref=url,
                                  provenance="needs-console-read", error=f"offline: the {key} page was not fetched"))
        else:
            try:
                status, body, final = fetch_url(url)
                heading, blocks = read_html(main_content(body))
                text = " ".join(t for _, t in blocks)
                out.append(make_probe(pid, {"http": status, "final_url": final, "heading": heading, "characters": len(text),
                                            "text": text[:20000], "is_pdf": body[:5] == "%PDF-",
                                            "has_contact": bool(re.search(r"mailto:|@[a-z0-9-]+\.[a-z]{2,}|contact|support", body, re.I))},
                                      source_kind="url", source_ref=url))
            except Exception as e:
                out.append(make_probe(pid, None, source_kind="url", source_ref=url, error=f"could not fetch: {e}"))
    return out


def self_test() -> None:
    d = tomllib.loads('[listing]\nname = "A"\n[listing.apple]\nsubtitle = "s"\n')
    assert d["listing"]["apple"]["subtitle"] == "s"
