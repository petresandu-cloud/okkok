# Copyright (C) 2026 Editerra AB. Okkok is a trademark of Editerra AB.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apply reader findings: python3 tools/apply_review.py modal.json fidelity.json

modal.json:    record id -> {verdict, fix}   (fix = corrected paraphrase)
fidelity.json: rule id   -> {verdict, fix, problems}
Judgement rules take the fix as their new question. Mechanical rules keep
their check and carry the reader's fix as `check_review` so the code change
is tracked on the rule itself. Every rule records the verdict on its draft.
"""
import json, sys, tomllib, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from storecheck import corpus
from storecheck.schema import write_json, now_iso

modal = json.load(open(sys.argv[1], encoding="utf-8"))
fid = json.load(open(sys.argv[2], encoding="utf-8"))
stamp = now_iso()

n = 0
for r in corpus.load_all():
    path = Path(r.pop("_path"))
    m = modal.get(r["id"])
    if m:
        r.setdefault("review", {})["modal_verdict"] = m["verdict"]
        if m["verdict"] == "drift" and m["fix"]:
            r["paraphrase"] = m["fix"]; r["review"]["modal_rewritten"] = True; n += 1
        r["review"]["modal_at"] = stamp
    write_json(path, r)
print(n, "paraphrases corrected for strength")

def toml_str(s):
    if "\n" in s or '"' in s and "'" not in s:
        return "'''" + s + "'''" if "'''" not in s else '"""' + s.replace('"""', '\\"\\"\\"') + '"""'
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

def dump_rules(rules, header):
    out = [header.rstrip() + "\n"]
    for r in rules:
        out.append("[[rule]]")
        for k, v in r.items():
            if isinstance(v, bool): out.append(f"{k} = {'true' if v else 'false'}")
            elif isinstance(v, list): out.append(f"{k} = [" + ", ".join(toml_str(x) for x in v) + "]")
            else: out.append(f"{k} = {toml_str(str(v))}")
        out.append("")
    return "\n".join(out)

rules_dir = Path("storecheck/rules")
changed = 0
for f in sorted(rules_dir.glob("*.toml")):
    text = f.read_text(encoding="utf-8")
    header = "\n".join(l for l in text.split("\n[[rule]]")[0].splitlines() if l.startswith("#")) or "# Rules."
    rules = tomllib.loads(text)["rule"]
    for r in rules:
        v = fid.get(r["id"])
        if not v: continue
        r["review_verdict"] = v["verdict"]
        r["reviewed_at"] = stamp
        if v["fix"]:
            if r["kind"] == "judgement":
                r["question"] = v["fix"]; changed += 1
            else:
                r["check_review"] = v["fix"]; changed += 1
    f.write_text(dump_rules(rules, header), encoding="utf-8")
print(changed, "rules updated")
