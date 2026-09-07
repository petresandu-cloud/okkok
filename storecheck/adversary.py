"""The second pass. Its only job is to break the first.

Four hunts, none of which needs a model:
  quotations   every quote in the corpus and in every judgement's evidence must be found
               verbatim in the cached rule text or in the recorded facts
  staleness    any corpus record that is not verified, named with why
  coverage     rule pages no rule cites, and guideline sections with no record at all
  challenge    every judged row, with the question, the answer given, and the raw rule
               text, so a second model can disagree
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import corpus, grid as grid_mod
from .schema import read_json

QUOTED = re.compile(r"“([^”]{20,})”")


def quoted_spans(text: str) -> list[str]:
    """Every quoted span of 20+ characters. Curly quotes are unambiguous; straight
    quotes are paired in order (1st with 2nd, 3rd with 4th), so a span between a
    closing and the next opening quote is never taken for a quotation."""
    out = [q for q in QUOTED.findall(text)]
    parts = text.split('"')
    out += [parts[i] for i in range(1, len(parts), 2) if len(parts[i]) >= 20]
    return out


def run(app_dir: Path) -> dict:
    sc = app_dir / "storecheck"
    probes = read_json(sc / "probes.json")
    g = read_json(sc / "grid.json")
    records = [corpus.verify_from_cache(r) for r in corpus.load_all()]
    rules = grid_mod.load_rules()
    facts_text = json.dumps(probes, ensure_ascii=False)
    cache_text = {r["id"]: (corpus.CACHE_DIR / f"{r['id']}.txt").read_text(encoding="utf-8")
                  for r in records if (corpus.CACHE_DIR / f"{r['id']}.txt").exists()}
    all_rule_text = " ".join(cache_text.values())

    out = {"corpus_not_verified": [{"id": r["id"], "status": r["status"], "note": r.get("note")} for r in records if r["status"] != "verified"],
           "unverifiable_quotations": [], "records_no_rule_cites": [], "guideline_sections_without_record": [],
           "index_policies_without_record": [], "paraphrases_not_accepted": [], "challenge": []}
    out["paraphrases_not_accepted"] = [{"id": r["id"], "status": r.get("paraphrase_status", "accepted")} for r in records
                                       if r.get("paraphrase_status", "accepted") != "accepted"]

    # Policies an index page lists that no record covers.
    have_urls = {corpus.canonical_url(r["url"], r["url"]) for r in records}
    have_urls |= {corpus.canonical_url(r["index_url"], r["index_url"]) for r in records if r.get("index_url")}
    for r in records:
        if r.get("kind") == "index":
            # Links an index record names as deliberately unmapped (help pages, archives) are listed there, not here.
            ignored = set(r.get("not_policies", []))
            for l in r.get("links", []):
                if l["url"] not in have_urls and l["title"] not in ignored:
                    out["index_policies_without_record"].append({"index": r["id"], "title": l["title"], "url": l["url"]})

    cited = {c for r in rules for c in r["corpus"]}
    out["records_no_rule_cites"] = sorted(r["id"] for r in records if r["id"] not in cited and r.get("role") != "reference" and r.get("kind") != "index")

    # Sections of Apple's guidelines page that no record covers.
    raw = corpus.CACHE_DIR / "apple.arg.5.1.1.raw"
    if raw.exists():
        sections = re.findall(r'data-sidenav="([^"]+)" id="([^"]+)"', raw.read_text(encoding="utf-8"))
        covered = {r.get("anchor_id") for r in records}
        out["guideline_sections_without_record"] = [f"{name} (#{sid})" for name, sid in sections if sid not in covered and re.match(r"\d+\.\d+", name)]

    for j in grid_mod.load_jsonl(sc / "judgements.jsonl"):
        for q in quoted_spans(j["evidence"]):
            qn = corpus.normalise(q)
            if qn not in corpus.normalise(facts_text) and qn not in all_rule_text:
                out["unverifiable_quotations"].append({"rule": j["rule"], "by": j.get("by"), "quote": q,
                                                       "why": "not found in the recorded facts or in any cached rule text"})

    for row in g["rows"]:
        if row["kind"] != "judgement":
            continue
        rule = next(r for r in rules if r["id"] == row["id"])
        out["challenge"].append({
            "rule": row["id"], "question": rule["question"], "verdict_given": row["verdict"], "evidence_given": row["evidence"],
            "provenance": row["provenance"],
            "rule_text": {c: cache_text.get(c) for c in rule["corpus"]},
            "facts": {p: next((x["value"] for x in probes if x["id"] == p), None) for p in rule["consumes"]},
        })
    out["summary"] = (f"{len(out['corpus_not_verified'])} rule pages not verified, {len(out['unverifiable_quotations'])} quotations that cannot be found, "
                      f"{len(out['records_no_rule_cites'])} records no rule uses, {len(out['guideline_sections_without_record'])} Apple guideline sections with no record, "
                      f"{len(out['index_policies_without_record'])} Google policies on the index with no record, "
                      f"{len(out['paraphrases_not_accepted'])} paraphrases not yet accepted by a person, "
                      f"{len(out['challenge'])} judgements to re-examine")
    return out
