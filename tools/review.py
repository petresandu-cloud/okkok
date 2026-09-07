"""Apply an adversarial review to corpus records: python3 tools/review.py fixes.json "<reviewer>"

fixes.json maps id -> {"verdict": ..., "paraphrase": rewritten}. Records named
here take the rewrite and paraphrase_status "reviewed" (drafted, then read
against the page by an independent reader and corrected). Records not named
were read and held; they are marked reviewed too when --held lists them.
A person still accepts.
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from storecheck import corpus
from storecheck.schema import write_json, now_iso

fixes = json.load(open(sys.argv[1], encoding="utf-8"))
reviewer = sys.argv[2]
held = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else set()
n = 0
for r in corpus.load_all():
    path = Path(r.pop("_path"))
    if r["id"] in fixes:
        f = fixes[r["id"]]
        r["paraphrase"] = f["paraphrase"]
        r["review"] = {"by": reviewer, "at": now_iso(), "verdict_on_draft": f["verdict"], "rewritten": True}
        r["paraphrase_status"] = "reviewed"; n += 1
    elif r["id"] in held:
        r["review"] = {"by": reviewer, "at": now_iso(), "verdict_on_draft": "holds", "rewritten": False}
        if r.get("paraphrase_status") == "drafted":
            r["paraphrase_status"] = "reviewed"; n += 1
    write_json(path, r)
print(n, "records reviewed")
