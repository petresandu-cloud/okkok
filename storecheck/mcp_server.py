"""The model adapter: the same seven operations the command line offers, over MCP.

Any model that speaks the Model Context Protocol can run a full audit with
these and nothing else. The tool decides provenance; a model's answer is
always recorded as sub-agent-reported, and it is thrown away when the facts
it saw change.

    .venv/bin/python -m storecheck.mcp_server        (stdio)
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import adversary, fix, judge, texts
from .cli import run_probes
from . import stage as stage_mod
from . import grid as grid_mod
from .schema import read_json, write_json

server = MCPServer("storecheck", instructions=(
    "Audit an iOS or Android app against the App Store and Google Play rules. "
    "Call audit_run first. For each rule it reports as awaiting judgement, call audit_get_rule to read the "
    "rule text, look at the facts, then audit_judge with a verdict and evidence that names what you looked at. "
    "Then audit_adversarial, and fix_propose for each FAIL or RISK."))


@server.tool()
def audit_run(app_dir: str, offline: bool = False, as_of: str | None = None) -> dict:
    """Read the app, decide its stage, judge every mechanical rule, write the grid. Returns counts and the rules awaiting judgement."""
    app = Path(app_dir).resolve()
    probes = run_probes(app, offline=offline)
    stage = stage_mod.decide(probes)
    if stage_mod.no_app(stage):
        return {"error": stage_mod.NO_APP.format(dir=app)}
    sc = app / "storecheck"
    write_json(sc / "probes.json", probes)
    write_json(sc / "stage.json", stage)
    g = grid_mod.build(app, probes, stage, as_of=as_of)
    write_json(sc / "grid.json", g)
    grid_mod.render(sc / "grid.json", sc / "report.html", app_name=app.name)
    return {"stage": g["stage"], "counts": g["counts"],
            "awaiting_judgement": [r["id"] for r in g["rows"] if r["kind"] == "judgement" and r["verdict"] == "UNKNOWN"],
            "findings": [{"id": r["id"], "verdict": r["verdict"], "evidence": r["evidence"]} for r in g["rows"] if r["verdict"] in ("FAIL", "RISK", "NOTE")],
            "data": str(sc / "grid.json"), "report": str(sc / "report.html")}


@server.tool()
def audit_get_rule(rule_id: str) -> dict:
    """One rule: its question or check, the corpus records it rests on, and the cached text of each rule page."""
    return judge.rule_with_text(rule_id)


@server.tool()
def audit_get_probes(app_dir: str, ids: list[str] | None = None) -> list[dict]:
    """The recorded facts for the app, all of them or the ids asked for."""
    probes = read_json(Path(app_dir).resolve() / "storecheck" / "probes.json")
    return [p for p in probes if not ids or p["id"] in ids]


@server.tool()
def audit_judge(app_dir: str, rule_id: str, verdict: str, evidence: str, by: str) -> dict:
    """Record a judgement on a judgement rule. Provenance is set by the tool to sub-agent-reported. Evidence must name what was looked at."""
    app = Path(app_dir).resolve()
    j = judge.add_judgement(app, rule_id, verdict, evidence, by)
    g = judge.rebuild(app)
    row = next(r for r in g["rows"] if r["id"] == rule_id)
    return {"recorded": j, "row_now": {"verdict": row["verdict"], "provenance": row["provenance"]}}


@server.tool()
def audit_adversarial(app_dir: str) -> dict:
    """The second pass: quotations that cannot be found, stale rule pages, uncited records, unmapped guideline sections, and every judgement with its rule text for re-examination."""
    return adversary.run(Path(app_dir).resolve())


@server.tool()
def fix_propose(app_dir: str, rule_id: str) -> dict:
    """A fix for one finding, derived from this app's own facts: a patch, a rebuild, or a question when a person must decide."""
    return fix.propose(Path(app_dir).resolve(), rule_id)


@server.tool()
def audit_get_texts(app_dir: str, offline: bool = False) -> dict:
    """Every text the app presents to people and reviewers: listing, purpose strings, privacy and deletion pages, in-app copy. Read these against a rule; do not keyword-match them."""
    return texts.gather(Path(app_dir).resolve(), offline=offline)


@server.tool()
def fix_app_model(app_dir: str) -> dict:
    """What the app does, from the facts alone: permissions declared and referenced, data leaving the device, its own words."""
    return fix.app_model(read_json(Path(app_dir).resolve() / "storecheck" / "probes.json"))


if __name__ == "__main__":
    server.run()
