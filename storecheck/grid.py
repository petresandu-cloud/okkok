"""The grid: every rule that applies at this stage, judged against the facts, with provenance.

build   rules x facts x stage x judgements x resolutions -> grid.json
validate exactly one provenance marker per row, or fail
render  grid.json -> grid.html, the only way the page is ever produced
check   the page's embedded hash equals the grid's hash, or fail
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from datetime import date
from pathlib import Path

from . import applies, checks, corpus
from .schema import PROVENANCE, STAGES, VERDICTS, now_iso, read_json, sha256_of_text, write_json

RULES_DIR = Path(__file__).resolve().parent / "rules"
CROSSWALK = Path(__file__).resolve().parent.parent / "crosswalk" / "pairs.json"


def crosswalk_for(corpus_ids: list[str]) -> list[dict]:
    """Pairs from the Apple-Google crosswalk that touch any of these records."""
    if not CROSSWALK.exists():
        return []
    pairs = json.loads(CROSSWALK.read_text(encoding="utf-8"))["pairs"]
    ids = set(corpus_ids)
    return [p for p in pairs if p["apple"] in ids or p["google"] in ids]
CORPUS_RANK = {"verified": 0, "stale": 1, "quote-mismatch": 2, "wrong-page": 3, "unreadable": 4, "unfetched": 5}


def load_rules() -> list[dict]:
    rules = []
    for f in sorted(RULES_DIR.glob("*.toml")):
        for r in tomllib.loads(f.read_text(encoding="utf-8")).get("rule", []):
            assert_rule(r)
            rules.append(r)
    ids = [r["id"] for r in rules]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ValueError(f"duplicate rule ids: {sorted(dup)}")
    return rules


def assert_rule(r: dict) -> None:
    for k in ("id", "store", "title", "corpus", "consumes", "kind", "stages", "severity"):
        if k not in r:
            raise ValueError(f"rule {r.get('id')} missing {k}")
    if r["kind"] == "mechanical" and not hasattr(checks, r.get("check", "")):
        raise ValueError(f"rule {r['id']}: no check named {r.get('check')!r} in checks.py")
    if r["kind"] == "judgement" and not r.get("question"):
        raise ValueError(f"rule {r['id']}: a judgement rule needs a question")
    for s in r["stages"]:
        if s not in STAGES:
            raise ValueError(f"rule {r['id']}: unknown stage {s}")
    if r["severity"] not in ("fail", "risk", "note"):
        raise ValueError(f"rule {r['id']}: severity must be fail, risk or note")
    if r.get("readiness") and r["kind"] != "mechanical":
        raise ValueError(f"rule {r['id']}: readiness applies to mechanical checks only")
    for cond in r.get("applies_when", []):
        if cond.split(":")[0] not in ("capability", "permission", "entitlement", "background_mode", "framework", "dex", "listing", "audience", "signal", "extensions"):
            raise ValueError(f"rule {r['id']}: unknown applies_when condition {cond!r}")


def probe_hash(probes: list[dict], ids: list[str]) -> str:
    by = {p["id"]: p["value"] for p in probes}
    return sha256_of_text(json.dumps([by.get(i) for i in ids], sort_keys=True, ensure_ascii=False))


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def build(app_dir: Path, probes: list[dict], stage: dict, as_of: str | None = None, corpus_records: list[dict] | None = None) -> dict:
    as_of = as_of or date.today().isoformat()
    rules = load_rules()
    records = {r["id"]: r for r in (corpus_records if corpus_records is not None else [corpus.verify_from_cache(r) for r in corpus.load_all()])}
    judgements = load_jsonl(app_dir / "storecheck" / "judgements.jsonl")
    resolutions = load_jsonl(app_dir / "storecheck" / "resolution-log.jsonl")
    facts = checks.Facts(probes, stage, as_of)
    rows, skipped = [], []
    for rule in rules:
        stores = ("apple", "google") if rule["store"] == "both" else (rule["store"],)
        at = [s for s in stores if stage.get(s) in rule["stages"]]
        if not at:
            skipped.append(rule["id"])
            continue
        row = {"id": rule["id"], "title": rule["title"], "store": rule["store"], "stage": {s: stage.get(s) for s in at},
               "severity": rule["severity"], "kind": rule["kind"], "corpus": rule["corpus"],
               "probes": [{"id": i, "observed_at": facts.by[i]["observed_at"]} for i in rule["consumes"] if i in facts.by]}

        state, why = applies.evaluate(rule.get("applies_when", []), facts)
        if state == "na":
            row.update(verdict="N/A", provenance="verified-directly", evidence=f"does not apply to this app: {why}")
            rows.append(row)
            continue
        if state == "unknown":
            row.update(verdict="UNKNOWN", provenance="verified-directly", evidence=f"whether this rule applies is not decidable yet: {why}")
            rows.append(row)
            continue

        worst = max((records.get(c, {"status": "unfetched"})["status"] for c in rule["corpus"]), key=lambda s: CORPUS_RANK[s])
        row["corpus_status"] = worst
        if worst != "verified":
            bad = [c for c in rule["corpus"] if records.get(c, {"status": "unfetched"})["status"] != "verified"]
            row.update(verdict="UNKNOWN", provenance="verified-directly",
                       evidence=f"cannot be judged: the rule page {', '.join(bad)} is {worst}; re-read it and accept the change first")
            rows.append(row)
            continue

        if rule.get("effective_from") and as_of < rule["effective_from"]:
            row.update(verdict="PENDING", provenance="verified-directly",
                       evidence=f"in force from {rule['effective_from']}; today is {as_of}")
            rows.append(row)
            continue

        if rule["kind"] == "mechanical":
            verdict, evidence, prov = getattr(checks, rule["check"])(facts)
            if verdict == "PASS" and rule["severity"] == "note":
                pass
            elif verdict == "FAIL" and rule["severity"] == "risk":
                verdict = "RISK"
            if rule.get("readiness") and verdict in ("FAIL", "RISK"):
                verdict = "NOTE"
                evidence = "readiness, not a policy rule: " + evidence
        else:
            h = probe_hash(probes, rule["consumes"])
            j = next((j for j in reversed(judgements) if j["rule"] == rule["id"]), None)
            if j is None:
                verdict, evidence, prov = "UNKNOWN", "awaiting judgement: " + rule["question"], "verified-directly"
            elif j.get("probe_sha256") != h:
                verdict, evidence, prov = "UNKNOWN", f"a judgement by {j.get('by')} on {j.get('at')} was discarded because the facts it saw have changed; ask again: " + rule["question"], "verified-directly"
            else:
                verdict, evidence, prov = j["verdict"], j["evidence"], "sub-agent-reported"
                row["judgement"] = {"by": j.get("by"), "at": j.get("at")}

        res = next((r for r in reversed(resolutions) if r["row"] == rule["id"]), None)
        if res is not None:
            row["resolution"] = res["n"]
            if verdict in ("PASS", "NOTE"):
                verdict, evidence = "RESOLVED", f"resolved in entry {res['n']} ({res['date']}); {evidence}"
            elif verdict in ("FAIL", "RISK"):
                evidence = f"regressed after resolution {res['n']}: {evidence}"
        row["crosswalk"] = [{"apple": p["apple"], "google": p["google"], "relation": p["relation"], "difference": p["difference"]} for p in crosswalk_for(rule["corpus"])]
        row.update(verdict=verdict, evidence=evidence, provenance=prov)
        rows.append(row)

    from . import fix as fix_mod  # here to avoid a circular import
    model = fix_mod.app_model(probes)
    for row in rows:
        row["action"] = fix_mod.action_for(row, model, facts)
    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in VERDICTS}
    grid = {"built_at": now_iso(), "as_of": as_of, "stage": {k: stage.get(k) for k in ("apple", "google")},
            "counts": counts, "rows": rows, "not_applicable": skipped}
    validate(grid)
    return grid


def validate(grid: dict) -> list[str]:
    """Exactly one provenance marker on every row, a known verdict, and at least one row."""
    problems = []
    if not grid.get("rows"):
        problems.append("the grid has no rows at all; a grid that checks nothing must not pass")
    for r in grid.get("rows", []):
        marks = [m for m in PROVENANCE if m == r.get("provenance")]
        if len(marks) != 1:
            problems.append(f"row {r.get('id')}: provenance must be exactly one of {PROVENANCE}, got {r.get('provenance')!r}")
        if r.get("verdict") not in VERDICTS:
            problems.append(f"row {r.get('id')}: unknown verdict {r.get('verdict')!r}")
        if not r.get("evidence"):
            problems.append(f"row {r.get('id')}: no evidence sentence")
    if problems:
        raise ValueError("\n".join(problems))
    return problems


def grid_hash(grid_path: Path) -> str:
    return hashlib.sha256(grid_path.read_bytes()).hexdigest()


from . import report as _report  # the page follows REPORT-PRINCIPLES.md


def render(grid_path: Path, out_path: Path, app_name: str = "") -> None:
    _report.render(grid_path, out_path, app_name)


def render_text(grid_path: Path, app_name: str = "") -> str:
    return _report.render_text(grid_path, app_name)


def check_render(grid_path: Path, html_path: Path, app_name: str = "") -> str | None:
    return _report.check_render(grid_path, html_path, app_name)


def self_test() -> None:
    # A row without provenance must be refused; a grid without rows must be refused.
    try:
        validate({"rows": [{"id": "x", "verdict": "PASS", "evidence": "e"}]})
    except ValueError as err:
        assert "provenance" in str(err)
    else:
        raise AssertionError("a row without provenance passed validation")
    try:
        validate({"rows": []})
    except ValueError:
        pass
    else:
        raise AssertionError("an empty grid passed validation")
    validate({"rows": [{"id": "x", "verdict": "PASS", "evidence": "e", "provenance": "verified-directly"}]})
    load_rules()
