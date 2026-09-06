"""The record shapes storecheck writes and reads.

Every record is a plain dict so it round-trips through JSON without ceremony.
The assert_* functions are the only validation; they raise ValueError naming
the field, so a malformed record can never be written silently.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

# How a fact or a verdict is known. Exactly one of these on every probe and
# every grid row. A row without one fails the build (grid.validate).
PROVENANCE = (
    "verified-directly",     # this tool read the file, ran the command, fetched the page
    "sub-agent-reported",    # a model or a person said so; the tool did not check
    "inferred",              # derived by reasoning from other facts
    "needs-console-read",    # only a store console can answer, and none was read
    "needs-device-test",     # only a device walk can answer, and none was done
)

VERDICTS = ("PASS", "FAIL", "RISK", "UNKNOWN", "PENDING", "NOTE", "RESOLVED")
STAGES = ("source-only", "built-not-uploaded", "internal-beta", "in-review", "public")
STORES = ("apple", "google", "both")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_probe(
    id: str,
    value,
    *,
    source_kind: str,
    source_ref: str,
    provenance: str = "verified-directly",
    source_sha256: str | None = None,
    error: str | None = None,
) -> dict:
    """Build one probe record. A probe is a fact with its own provenance, never a verdict."""
    rec = {
        "id": id,
        "value": value,
        "source": {"kind": source_kind, "ref": source_ref},
        "observed_at": now_iso(),
        "provenance": provenance,
    }
    if source_sha256:
        rec["source"]["sha256"] = source_sha256
    if error:
        rec["error"] = error
    assert_probe(rec)
    return rec


def file_probe(id: str, value, path: Path, **kw) -> dict:
    """A probe whose source is a file the tool read; the file's hash is recorded."""
    return make_probe(
        id, value, source_kind="file", source_ref=str(path), source_sha256=sha256_of_file(path), **kw
    )


def missing_probe(id: str, looked_for: str, provenance: str = "verified-directly") -> dict:
    """The tool looked and found nothing. That is itself a directly verified fact."""
    return make_probe(
        id, None, source_kind="file", source_ref=looked_for, provenance=provenance,
        error=f"not found: looked for {looked_for}",
    )


def assert_probe(rec: dict) -> None:
    for field in ("id", "source", "observed_at", "provenance"):
        if field not in rec:
            raise ValueError(f"probe missing field: {field}")
    if "value" not in rec:
        raise ValueError("probe missing field: value (use None when unknown)")
    if rec["provenance"] not in PROVENANCE:
        raise ValueError(f"probe {rec['id']}: provenance must be one of {PROVENANCE}, got {rec['provenance']!r}")
    src = rec["source"]
    if src.get("kind") not in ("file", "url", "command"):
        raise ValueError(f"probe {rec['id']}: source.kind must be file, url or command")
    if not src.get("ref"):
        raise ValueError(f"probe {rec['id']}: source.ref is empty")
    if rec["value"] is None and "error" not in rec:
        raise ValueError(f"probe {rec['id']}: a null value must carry an error saying why")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
