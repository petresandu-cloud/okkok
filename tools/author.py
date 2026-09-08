# Copyright (C) 2026 Editerra AB. Okkok is a trademark of Editerra AB.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apply drafted paraphrases to corpus records: python3 tools/author.py drafts.json

The JSON maps record id -> {"paraphrase": ..., "quote": optional, "kind": "page"}.
Every paraphrase written here is marked drafted; a person accepts it later.
The quote is not trusted here: the next corpus fetch verifies it or marks the
record quote-mismatch.
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from okkok import corpus
from okkok.schema import write_json

drafts = json.load(open(sys.argv[1], encoding="utf-8"))
recs = {r["id"]: r for r in corpus.load_all()}
for rid, d in drafts.items():
    r = recs[rid]
    r["paraphrase"] = d["paraphrase"]
    r["paraphrase_status"] = "drafted"
    r["paraphrase_by"] = d.get("by", "drafted from the page text")
    if d.get("quote"):
        r["quote"] = d["quote"]
    path = Path(r.pop("_path"))
    write_json(path, r)
print(len(drafts), "paraphrases drafted")
