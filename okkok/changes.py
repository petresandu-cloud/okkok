# Copyright (C) 2026 Editerra AB. Okkok is a trademark of Editerra AB.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rule-change log: what the stores changed, when, in our words.

Every fetch that finds a rule page changed appends an entry here. A person then
reads the diff, accepts the new baseline and writes one sentence on what changed.
The log holds no store text: page, date, fingerprints before and after, and our
sentence. From it come a page and an RSS feed that developers can watch.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from .corpus import CORPUS_DIR
from .schema import now_iso

LOG = CORPUS_DIR / "changes.jsonl"
STORE = {"apple": "App Store", "google": "Google Play"}


def load() -> list[dict]:
    if not LOG.exists():
        return []
    return [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]


def _append(entry: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def note_change(record: dict, status: str) -> dict | None:
    """Called after a fetch that did not verify. One open entry per record; a repeat is not logged twice."""
    for e in load():
        if e["id"] == record["id"] and e.get("accepted_at") is None and e.get("observed_sha256") == record.get("observed_sha256"):
            return None
    entry = {"id": record["id"], "store": record["store"], "url": record["url"], "heading": record.get("expected_heading"),
             "seen_at": now_iso(), "status": status, "previous_sha256": record.get("sha256"), "observed_sha256": record.get("observed_sha256"),
             "summary": None, "accepted_at": None, "accepted_by": None}
    _append(entry)
    return entry


def note_acceptance(record: dict, summary: str, by: str) -> dict:
    """Close the open entry for this record with our sentence on what changed."""
    entries = load()
    hit = None
    for e in reversed(entries):
        if e["id"] == record["id"] and e.get("accepted_at") is None:
            hit = e
            break
    if hit is None:
        hit = {"id": record["id"], "store": record["store"], "url": record["url"], "heading": record.get("expected_heading"),
               "seen_at": now_iso(), "status": "stale", "previous_sha256": None, "observed_sha256": record.get("sha256"),
               "summary": None, "accepted_at": None, "accepted_by": None}
        entries.append(hit)
    hit.update(summary=summary.strip(), accepted_at=now_iso(), accepted_by=by, new_sha256=record.get("sha256"))
    LOG.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
    return hit


def rules_citing(rule_records: list[dict], cid: str) -> list[str]:
    return [r["id"] for r in rule_records if cid in r.get("corpus", [])]


# ----------------------------------------------------------------- rendering

def _when(iso: str) -> str:
    d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    return d.strftime("%-d %B %Y")


def render_markdown(entries: list[dict], rules: list[dict]) -> str:
    lines = ["# Store rule changes", "",
             "What Apple and Google changed on the rule pages Okkok reads, in our words. The stores' own text is never reproduced here; "
             "each entry links to the page. An entry marked *under review* was seen to change and is waiting for a person to read it.", ""]
    for e in sorted(entries, key=lambda x: x.get("accepted_at") or x["seen_at"], reverse=True):
        cites = rules_citing(rules, e["id"])
        state = f"accepted {_when(e['accepted_at'])}" if e.get("accepted_at") else "under review"
        lines.append(f"## {_when(e['seen_at'])}: {STORE.get(e['store'], e['store'])}, [{e.get('heading') or e['id']}]({e['url']})")
        lines.append("")
        lines.append(e.get("summary") or "Changed; under review. The page's fingerprint no longer matches the last verified text.")
        lines.append("")
        lines.append(f"*{state}. Rules resting on this page: {', '.join(cites) if cites else 'none directly'}.*")
        lines.append("")
    if len(entries) == 0:
        lines.append("No changes recorded yet.")
    return "\n".join(lines) + "\n"


def render_rss(entries: list[dict], rules: list[dict], site_url: str) -> str:
    e_ = html.escape
    items = []
    for e in sorted(entries, key=lambda x: x.get("accepted_at") or x["seen_at"], reverse=True)[:100]:
        when = datetime.fromisoformat((e.get("accepted_at") or e["seen_at"]).replace("Z", "+00:00"))
        title = f"{STORE.get(e['store'], e['store'])}: {e.get('heading') or e['id']}" + ("" if e.get("accepted_at") else " (under review)")
        body = e.get("summary") or "The page changed and is under review."
        cites = rules_citing(rules, e["id"])
        if cites:
            body += " Rules resting on it: " + ", ".join(cites) + "."
        items.append(f"<item><title>{e_(title)}</title><link>{e_(e['url'])}</link><guid isPermaLink=\"false\">{e_(e['id'])}:{e_(e.get('observed_sha256') or e.get('new_sha256') or '')}</guid>"
                     f"<pubDate>{when.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate><description>{e_(body)}</description></item>")
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Okkok: store rule changes</title>'
            f'<link>{e_(site_url)}</link><description>What Apple and Google changed on their rule pages, in Okkok\'s words, never theirs.</description>'
            + "".join(items) + "</channel></rss>\n")


def self_test() -> None:
    entries = [{"id": "google.user-data", "store": "google", "url": "https://example.com/x", "heading": "User Data", "seen_at": "2026-09-08T10:00:00+00:00",
                "status": "stale", "previous_sha256": "a", "observed_sha256": "b", "summary": None, "accepted_at": None, "accepted_by": None}]
    md = render_markdown(entries, [{"id": "google.data-safety-matches-app", "corpus": ["google.user-data"]}])
    assert "under review" in md and "google.data-safety-matches-app" in md
    rss = render_rss(entries, [], "https://example.com")
    assert "<item>" in rss and "(under review)" in rss
    entries[0].update(summary="Now names a 90-day limit.", accepted_at="2026-09-09T10:00:00+00:00", accepted_by="a person")
    assert "accepted 9 September 2026" in render_markdown(entries, [])
