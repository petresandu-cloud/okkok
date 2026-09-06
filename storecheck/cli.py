"""storecheck command line.

    storecheck audit <appDir>      read the app, write <appDir>/storecheck/probes.json, print what was found
    storecheck self-test           every probe checks itself against a known input
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .probes import android_apk, android_manifest, ios_built, ios_plist
from .schema import write_json

SOURCE_PROBES = (android_manifest, ios_plist)
BUILT_PROBES = (android_apk, ios_built)
ALL_PROBES = SOURCE_PROBES + BUILT_PROBES


def run_probes(app_dir: Path) -> list[dict]:
    probes: list[dict] = []
    for mod in ALL_PROBES:
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
        elif p["id"] == "android.built.manifest":
            lines.append(f"Android APK {v['artefact']} (built {v['artefact_modified']}): {v['package']} version {v['versionName']} ({v['versionCode']}): targetSdk {v['targetSdk']}, minSdk {v['minSdk']}, {len(v['permissions'])} permissions, debuggable {v['debuggable']}")
        elif p["id"] == "android.bundle.manifest":
            lines.append(f"Android bundle {v['package']} version {v['versionName']} ({v['versionCode']}): targetSdk {v['targetSdk']}, {len(v['permissions'])} permissions")
        elif p["id"] == "ios.built.info":
            lines.append(f"iOS bundle {v['artefact']} (built {v['artefact_modified']}): {v['bundle_id']} version {v['version']} build {v['build']}, minimum iOS {v['minimum_os']}, device family {v['device_family']}")
            lines.append(f"    {len(v['purpose_strings'])} purpose strings, background modes {v['background_modes'] or 'none'}, frameworks: " + ", ".join(v["frameworks"]))
        elif p["id"] == "ios.built.profile":
            e = v["entitlements"]
            lines.append(f"iOS signing: {v['kind']} profile, team {v['team']}, expires {v['expires']}")
            lines.append("    entitlements: " + ", ".join(f"{k}={e[k]}" for k in sorted(e)))
        elif p["id"] == "ios.built.privacy_manifests":
            app = v["app"]
            lines.append(f"iOS privacy manifests in the bundle: app manifest {'present' if app else 'MISSING'} with {len(app['collected_data_types']) if app else 0} data types; {len(v['third_party'])} third-party manifests: " + ", ".join(sorted(v["third_party"])))
        else:
            lines.append(f"{p['id']}: {v}")
    return "\n".join(lines)


def compare(probes: list[dict]) -> str:
    """Source versus built, side by side. Disagreement is a fact worth a line."""
    by = {p["id"]: p["value"] for p in probes}
    rows = []

    def row(label, a, b):
        same = a == b
        rows.append((label, str(a), str(b), "same" if same else "DIFFERS"))

    src, built = by.get("android.source.manifest"), by.get("android.built.manifest")
    gradle = by.get("android.source.gradle") or {}
    if src and built:
        row("Android package", src["package"], built["package"])
        row("Android targetSdk", gradle.get("targetSdk"), built["targetSdk"])
        only_src = sorted(set(src["permissions"]) - set(built["permissions"]))
        only_built = sorted(set(built["permissions"]) - set(src["permissions"]))
        row("Android permissions", f"{len(src['permissions'])}", f"{len(built['permissions'])}")
        for perm in only_src:
            rows.append(("    only in source", perm, "-", "DIFFERS"))
        for perm in only_built:
            rows.append(("    only in APK (added by a library or the build)", "-", perm, "DIFFERS"))
    isrc, ibuilt = by.get("ios.source.info"), by.get("ios.built.info")
    if isrc and ibuilt:
        row("iOS bundle id", isrc["bundle_id"], ibuilt["bundle_id"])
        row("iOS purpose strings", len(isrc["purpose_strings"]), len(ibuilt["purpose_strings"]))
        for k in sorted(set(isrc["purpose_strings"]) ^ set(ibuilt["purpose_strings"])):
            rows.append(("    purpose string", k if k in isrc["purpose_strings"] else "-", k if k in ibuilt["purpose_strings"] else "-", "DIFFERS"))
        row("iOS background modes", isrc["background_modes"], ibuilt["background_modes"])
    esrc, prof = by.get("ios.source.entitlements"), by.get("ios.built.profile")
    if esrc and prof:
        for k in sorted(set(esrc) | set(prof["entitlements"])):
            row(f"iOS entitlement {k}", esrc.get(k, "-"), prof["entitlements"].get(k, "-"))
    psrc, pbuilt = by.get("ios.source.privacy_manifest"), by.get("ios.built.privacy_manifests")
    if psrc and pbuilt and pbuilt.get("app"):
        row("iOS app privacy manifest", f"{len(psrc['collected_data_types'])} types", f"{len(pbuilt['app']['collected_data_types'])} types")
    if not rows:
        return "No built artefact to compare against the source."
    w = [max(len(r[i]) for r in rows) for i in range(4)]
    head = ("", "source", "built", "")
    out = ["  ".join(h.ljust(w[i]) for i, h in enumerate(head)).rstrip()]
    for r in rows:
        out.append("  ".join(c.ljust(w[i]) for i, c in enumerate(r)).rstrip())
    return "\n".join(out)


def cmd_audit(args) -> int:
    app_dir = Path(args.app_dir).resolve()
    if not app_dir.is_dir():
        print(f"not a directory: {app_dir}", file=sys.stderr)
        return 1
    probes = run_probes(app_dir)
    out = app_dir / "storecheck" / "probes.json"
    write_json(out, probes)
    print(describe(probes))
    print("\nSource versus built")
    print(compare(probes))
    print(f"\n{len(probes)} facts written to {out}")
    return 0


def cmd_self_test(args) -> int:
    for mod in ALL_PROBES:
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
