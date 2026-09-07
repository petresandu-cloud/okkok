"""The grid: every rule that applies at this stage, judged against the facts, with provenance.

build   rules x facts x stage x judgements x resolutions -> grid.json
validate exactly one provenance marker per row, or fail
render  grid.json -> grid.html, the only way the page is ever produced
check   the page's embedded hash equals the grid's hash, or fail
"""

from __future__ import annotations

import hashlib
import html
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


COLOURS = {"PASS": "#2f7d3a", "RESOLVED": "#2f7d3a", "FAIL": "#b3261e", "RISK": "#b26a00", "UNKNOWN": "#5f6368",
           "PENDING": "#3b5bdb", "NOTE": "#5f6368", "N/A": "#8a8a8a"}


def render(grid_path: Path, out_path: Path, app_name: str = "") -> None:
    out_path.write_text(render_text(grid_path, app_name), encoding="utf-8")
    render_exports(grid_path)


def render_text(grid_path: Path, app_name: str = "") -> str:
    grid = read_json(grid_path)
    h = grid_hash(grid_path)
    e = html.escape
    app_dir = grid_path.parent.parent
    judgements = load_jsonl(app_dir / "storecheck" / "judgements.jsonl")
    resolutions = load_jsonl(app_dir / "storecheck" / "resolution-log.jsonl")
    rows, na_rows = [], []
    for r in grid["rows"]:
        stage = ", ".join(f"{k} {v}" for k, v in r["stage"].items())
        cw = ""
        if r.get("crosswalk"):
            items = "".join(f"<li><b>{e(p['relation'])}</b> {e(p['apple'])} ↔ {e(p['google'])}: {e(p['difference'])}</li>" for p in r["crosswalk"])
            cw = f"<details class=cw><summary>Apple ↔ Google: {len(r['crosswalk'])} overlapping rules</summary><ul>{items}</ul></details>"
        hist = [j for j in judgements if j["rule"] == r["id"]]
        jh = ""
        if hist:
            items = "".join(f"<li>{e(j['at'][:10])} · {e(j['verdict'])} · by {e(str(j.get('by')))}</li>" for j in hist[-3:])
            jh = f"<details class=cw><summary>{len(hist)} judgement{'s' if len(hist) != 1 else ''} recorded</summary><ul>{items}</ul></details>"
        cs = "" if r.get("corpus_status") == "verified" else f" · <span class=warn>rule page {e(r.get('corpus_status', ''))}</span>"
        cell = (f"<tr data-verdict=\"{e(r['verdict'])}\" data-store=\"{e(r['store'])}\">"
                f"<td class=v style='color:{COLOURS[r['verdict']]}'><b>{e(r['verdict'])}</b></td>"
                f"<td><b>{e(r['title'])}</b><br><small>{e(r['id'])} · {e(r['store'])} · {e(stage)} · rules: {e(', '.join(r['corpus']))}{cs}</small>{cw}{jh}</td>"
                f"<td>{e(r['evidence'])}</td><td><code>{e(r['provenance'])}</code></td></tr>")
        (na_rows if r["verdict"] == "N/A" else rows).append(cell)
    def action_block(r):
        a = r.get("action") or {}
        if not a:
            return ""
        who = {"developer": "Developer", "console": "Store console owner", "person": "A person must decide", "reader": "A reader or model", "device": "A device walk", "build": "Build engineer"}.get(a.get("who"), a.get("who", ""))
        where = f" · <code>{e(a['where'])}</code>" if a.get("where") else ""
        due = f" · <span class=warn>by {e(a['due'])}</span>" if a.get("due") else ""
        return f"<div class=act><b>{e(who)}</b>{where}{due}<br>{e(a.get('do', ''))}</div>"
    order = {"FAIL": 0, "RISK": 1, "NOTE": 2}
    todo = sorted([r for r in grid["rows"] if r["verdict"] in order], key=lambda r: order[r["verdict"]])
    todo_html = "".join(f"<li><span style='color:{COLOURS[r['verdict']]}'><b>{e(r['verdict'])}</b></span> <b>{e(r['title'])}</b> <small>({e(r['store'])})</small><br><small>{e(r['evidence'])}</small>{action_block(r)}</li>" for r in todo)
    open_rows = [r for r in grid["rows"] if r["verdict"] in ("UNKNOWN", "PENDING")]
    groups = {"needs-console-read": [], "verified-directly": [], "needs-device-test": [], "inferred": [], "sub-agent-reported": []}
    for r in open_rows:
        groups.setdefault(r["provenance"], []).append(r)
    labels = {"needs-console-read": "Read in the store console", "verified-directly": "Answer by reading or judging", "needs-device-test": "Walk on a device", "inferred": "Confirm an inference", "sub-agent-reported": "Re-check a reported answer"}
    open_html = "".join(f"<h3>{e(labels.get(k, k))} ({len(v)})</h3><ul>" + "".join(f"<li><b>{e(r['title'])}</b><br><small>{e(r['evidence'])}</small>{action_block(r)}</li>" for r in v) + "</ul>" for k, v in groups.items() if v)
    counts = " · ".join(f"{k} {v}" for k, v in grid["counts"].items() if v)
    buttons = "".join(f"<button data-f=\"{v}\">{v} {grid['counts'].get(v, 0)}</button>" for v in VERDICTS if grid["counts"].get(v))
    page = f"""<!doctype html>
<meta charset="utf-8">
<meta name="grid-sha256" content="{h}">
<meta name="grid-rows" content="{len(grid['rows'])}">
<title>storecheck {e(app_name)}</title>
<style>
body{{font:15px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:1180px;margin:32px auto;padding:0 16px;color:#1b1b1b;background:#fff}}
table{{border-collapse:collapse;width:100%}}td,th{{border-top:1px solid #ddd;padding:8px 10px;vertical-align:top;text-align:left}}
td.v{{white-space:nowrap}}small{{color:#555}}code{{font-size:12px;background:#f2f2f2;padding:1px 4px}}
.meta{{color:#555}} .warn{{color:#b26a00}} details.cw{{margin-top:6px;font-size:13px;color:#444}} details.cw ul{{margin:4px 0 0 16px;padding:0}}
.todo li{{margin:0 0 14px}} .act{{margin:6px 0 0;padding:8px 10px;background:#f6f4ee;border-left:3px solid #1b1b1b;font-size:14px}} h2{{margin-top:28px}} h3{{margin:18px 0 6px;font-size:15px}}
.bar button{{margin:0 6px 6px 0;padding:4px 10px;border:1px solid #bbb;background:#fafafa;cursor:pointer}} .bar button.on{{background:#1b1b1b;color:#fff}}
tr.hide{{display:none}} .export a{{margin-right:12px}}
</style>
<h1>storecheck {e(app_name)}</h1>
<p class=meta>Built {e(grid['built_at'])}, judged as of {e(grid['as_of'])}. Stage: Apple {e(str(grid['stage']['apple']))}, Google {e(str(grid['stage']['google']))}.<br>
{e(counts)}. {len(grid['not_applicable'])} rules do not apply at this stage. {len(resolutions)} resolutions logged.<br>
This page is generated from grid.json and carries its hash. Do not edit it; run render.</p>
<p class=export>Export: <a href="actions.json">actions.json (for an agent)</a> <a href="grid.json">grid.json</a> <a href="grid.csv">grid.csv</a> <a href="grid.md">grid.md</a> <a href="probes.json">facts</a> <a href="judgements.jsonl">judgements</a></p>
<h2>Do these ({len(todo)})</h2>
<ol class=todo>{todo_html}</ol>
<h2>Open questions ({len(open_rows)})</h2>
{open_html}
<h2>Every rule</h2>
<div class=bar><button data-f="all" class=on>all</button>{buttons}<button data-f="apple">Apple</button><button data-f="google">Google</button><button data-f="both">both</button></div>
<table id=g><tr><th>Verdict</th><th>Rule</th><th>Evidence</th><th>How known</th></tr>
{''.join(rows)}
</table>
<details><summary>{len(na_rows)} rules do not apply to this app. Each says why; a wrong reason here is a missed rule.</summary>
<table><tr><th>Verdict</th><th>Rule</th><th>Why not</th><th>How known</th></tr>{''.join(na_rows)}</table></details>
<p class=meta>How known: <code>verified-directly</code> the tool read the file, ran the command or fetched the page ·
<code>sub-agent-reported</code> a model or a person said so · <code>inferred</code> derived from other facts ·
<code>needs-console-read</code> only a store console can answer · <code>needs-device-test</code> only a device walk can answer.</p>
<script>
(function(){{var bs=document.querySelectorAll('.bar button');bs.forEach(function(b){{b.onclick=function(){{bs.forEach(function(x){{x.classList.remove('on')}});b.classList.add('on');var f=b.dataset.f;
document.querySelectorAll('#g tr[data-verdict]').forEach(function(tr){{var ok=f==='all'||tr.dataset.verdict===f||tr.dataset.store===f;tr.classList.toggle('hide',!ok)}})}}}})}})();
</script>
"""
    return page


def render_exports(grid_path: Path) -> None:
    """grid.csv and grid.md beside the page, from the same grid.json."""
    grid = read_json(grid_path)
    import csv
    with open(grid_path.parent / "grid.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["verdict", "rule", "title", "store", "stage", "provenance", "evidence", "rule pages"])
        for r in grid["rows"]:
            w.writerow([r["verdict"], r["id"], r["title"], r["store"], "; ".join(f"{k} {v}" for k, v in r["stage"].items()), r["provenance"], r["evidence"], ", ".join(r["corpus"])])
    lines = [f"# storecheck report", "", f"Built {grid['built_at']}, as of {grid['as_of']}. Apple {grid['stage']['apple']}, Google {grid['stage']['google']}.", "",
             "| Verdict | Rule | Evidence | How known |", "|---|---|---|---|"]
    for r in grid["rows"]:
        lines.append(f"| {r['verdict']} | {r['title']} (`{r['id']}`) | {r['evidence'].replace('|', '/')} | {r['provenance']} |")
    (grid_path.parent / "grid.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    actions = [{"rule": r["id"], "title": r["title"], "verdict": r["verdict"], "store": r["store"], "evidence": r["evidence"],
                "provenance": r["provenance"], **(r.get("action") or {})}
               for r in grid["rows"] if r["verdict"] in ("FAIL", "RISK", "NOTE", "UNKNOWN", "PENDING")]
    write_json(grid_path.parent / "actions.json", {"app": grid_path.parent.parent.name, "built_at": grid["built_at"], "stage": grid["stage"],
                                                   "how_to_use": "Each entry says what to do (do), who does it (who), where (where: a file, a console field, or a screen), and why (evidence). Act, then run storecheck audit again; resolved rows must pass their check to show RESOLVED.",
                                                   "actions": actions})


def check_render(grid_path: Path, html_path: Path, app_name: str = "") -> str | None:
    """None when the page on disk is byte-for-byte what render would produce from this grid.

    Rendering is deterministic, so this catches both a page left behind by an
    older grid and a page someone edited by hand."""
    if not html_path.exists():
        return f"{html_path.name} does not exist; run render"
    if html_path.read_text(encoding="utf-8") != render_text(grid_path, app_name):
        return f"{html_path.name} is not what render produces from the current {grid_path.name}: run render, do not edit the page"
    return None


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
