"""Judgements and resolutions: what a model or a person adds on top of the facts.

A judgement is stored with a hash of the facts it was given, so it dies when
those facts change. Its provenance is always sub-agent-reported; nothing a
model says can be recorded as directly verified. A resolution records what
was changed, the proof, and the guard; the grid shows RESOLVED only while the
mechanical check still passes.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import grid as grid_mod
from .schema import VERDICTS, now_iso, read_json, write_json


def rule_by_id(rule_id: str) -> dict:
    for r in grid_mod.load_rules():
        if r["id"] == rule_id:
            return r
    raise ValueError(f"no rule {rule_id}")


def rule_with_text(rule_id: str) -> dict:
    """The rule, its corpus records, and the cached text of each, for whoever must judge."""
    from . import corpus
    r = dict(rule_by_id(rule_id))
    recs = {c["id"]: c for c in corpus.load_all()}
    r["corpus_records"] = []
    for cid in r["corpus"]:
        c = recs.get(cid)
        if not c:
            r["corpus_records"].append({"id": cid, "status": "missing"})
            continue
        c = corpus.verify_from_cache(dict(c))
        cache = corpus.CACHE_DIR / f"{cid}.txt"
        r["corpus_records"].append({"id": cid, "url": c["url"], "status": c["status"], "paraphrase": c["paraphrase"],
                                    "quote": c.get("quote"), "text": cache.read_text(encoding="utf-8") if cache.exists() else None})
    return r


def add_judgement(app_dir: Path, rule_id: str, verdict: str, evidence: str, by: str) -> dict:
    rule = rule_by_id(rule_id)
    if rule["kind"] != "judgement":
        raise ValueError(f"{rule_id} is mechanical; the tool decides it, not a judge")
    if verdict not in ("PASS", "FAIL", "RISK", "NOTE"):
        raise ValueError("a judgement is PASS, FAIL, RISK or NOTE")
    if len(evidence.strip()) < 20:
        raise ValueError("evidence must say what was looked at and what was seen")
    probes = read_json(app_dir / "storecheck" / "probes.json")
    j = {"rule": rule_id, "verdict": verdict, "evidence": evidence.strip(), "by": by, "at": now_iso(),
         "provenance": "sub-agent-reported", "probe_sha256": grid_mod.probe_hash(probes, rule["consumes"])}
    with open(app_dir / "storecheck" / "judgements.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(j, ensure_ascii=False) + "\n")
    return j


def add_resolution(app_dir: Path, rule_id: str, **fields) -> dict:
    rule_by_id(rule_id)
    required = ("was", "changed", "proof", "guard", "residual_risk", "by")
    missing = [k for k in required if not fields.get(k)]
    if missing:
        raise ValueError("a resolution needs: " + ", ".join(missing))
    path = app_dir / "storecheck" / "resolution-log.jsonl"
    existing = grid_mod.load_jsonl(path)
    entry = {"n": len(existing) + 1, "row": rule_id, "date": now_iso()[:10], "provenance": fields.get("provenance", "sub-agent-reported")}
    entry.update({k: fields[k] for k in required})
    entry["choice"] = fields.get("choice", "")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def rebuild(app_dir: Path, as_of: str | None = None) -> dict:
    """The grid again from the stored facts, with no new probing."""
    sc = app_dir / "storecheck"
    probes = read_json(sc / "probes.json")
    stage = read_json(sc / "stage.json")
    g = grid_mod.build(app_dir, probes, stage, as_of=as_of)
    write_json(sc / "grid.json", g)
    grid_mod.render(sc / "grid.json", sc / "grid.html", app_name=app_dir.name)
    return g
