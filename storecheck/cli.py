"""storecheck command line.

    storecheck audit <appDir>      read the app, write <appDir>/storecheck/probes.json, print what was found
    storecheck self-test           every probe checks itself against a known input
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .probes import android_manifest, ios_plist
from .schema import write_json

SOURCE_PROBES = (android_manifest, ios_plist)


def run_probes(app_dir: Path) -> list[dict]:
    probes: list[dict] = []
    for mod in SOURCE_PROBES:
        probes.extend(mod.probe(app_dir))
    return probes


def describe(probes: list[dict]) -> str:
    """One plain line per fact, for a person. The JSON file is the record; this is the glance."""
    lines = []
    for p in probes:
        v = p["value"]
        if v is None:
            lines.append(f"{p['id']}: not found ({p.get('error')})")
            continue
        if p["id"] == "android.source.manifest":
            lines.append(f"Android package {v['package']}: {len(v['permissions'])} permissions declared")
            for perm in v["permissions"]:
                lines.append(f"    {perm}")
        elif p["id"] == "android.source.gradle":
            lines.append(f"Android build: applicationId {v['applicationId']}, targetSdk {v['targetSdk']}, compileSdk {v['compileSdk']}, minSdk {v['minSdk']}")
        elif p["id"] == "ios.source.info":
            lines.append(f"iOS bundle {v['bundle_id']} (from {v['bundle_id_from']}), version {v['version']} build {v['build']}")
            lines.append(f"    {len(v['purpose_strings'])} purpose strings: " + ", ".join(sorted(v["purpose_strings"])))
            lines.append(f"    background modes: {v['background_modes'] or 'none'}")
        elif p["id"] == "ios.source.entitlements":
            lines.append("iOS entitlements: " + ", ".join(f"{k}={v[k]}" for k in sorted(v)))
        elif p["id"] == "ios.source.privacy_manifest":
            types = [t["type"].replace("NSPrivacyCollectedDataType", "") for t in v["collected_data_types"]]
            lines.append(f"iOS privacy manifest: tracking {v['tracking']}, {len(types)} data types declared: " + ", ".join(types))
        else:
            lines.append(f"{p['id']}: {v}")
    return "\n".join(lines)


def cmd_audit(args) -> int:
    app_dir = Path(args.app_dir).resolve()
    if not app_dir.is_dir():
        print(f"not a directory: {app_dir}", file=sys.stderr)
        return 1
    probes = run_probes(app_dir)
    out = app_dir / "storecheck" / "probes.json"
    write_json(out, probes)
    print(describe(probes))
    print(f"\n{len(probes)} facts written to {out}")
    return 0


def cmd_self_test(args) -> int:
    for mod in SOURCE_PROBES:
        mod.self_test()
        print(f"ok  {mod.__name__}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="storecheck", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="read the app and write its facts")
    a.add_argument("app_dir")
    a.set_defaults(fn=cmd_audit)
    s = sub.add_parser("self-test", help="every probe checks itself")
    s.set_defaults(fn=cmd_self_test)
    args = ap.parse_args(argv)
    return args.fn(args)
