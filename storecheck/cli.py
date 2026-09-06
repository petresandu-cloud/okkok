"""storecheck command line.

    storecheck audit <appDir>      read the app, write <appDir>/storecheck/probes.json, print what was found
    storecheck self-test           every probe checks itself against a known input
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .probes import android_apk, android_dex, android_manifest, ios_built, ios_macho, ios_plist, listing, store_lookup
from . import stage as stage_mod
from . import corpus
from . import grid as grid_mod
from .capabilities import CAPABILITIES, APPLE_PURPOSE_KEYS
from .schema import read_json, write_json

SOURCE_PROBES = (android_manifest, ios_plist)
BUILT_PROBES = (android_apk, ios_built, android_dex, ios_macho)
ALL_PROBES = SOURCE_PROBES + BUILT_PROBES


def run_probes(app_dir: Path, offline: bool = False) -> list[dict]:
    probes: list[dict] = []
    for mod in ALL_PROBES:
        probes.extend(mod.probe(app_dir))
    probes.extend(listing.probe(app_dir, offline=offline))
    if not offline:
        by = {p["id"]: p["value"] for p in probes}
        bid = (by.get("ios.built.info") or by.get("ios.source.info") or {}).get("bundle_id")
        pkg = (by.get("android.built.manifest") or by.get("android.source.manifest") or {}).get("package")
        probes.extend(store_lookup.probe_ids(bid, pkg))
    return probes


def usage_table(probes: list[dict]) -> str:
    """Declared against referenced, per capability and platform. The heart of the minimisation rules."""
    by = {p["id"]: p["value"] for p in probes}
    a_decl = set((by.get("android.built.manifest") or by.get("android.source.manifest") or {}).get("permissions", []))
    i_info = by.get("ios.built.info") or by.get("ios.source.info") or {}
    i_keys = set(i_info.get("purpose_strings", {}))
    i_modes = set(i_info.get("background_modes", []))
    dex = (by.get("android.built.references") or {}).get("by_capability")
    mach = by.get("ios.built.references") or {}
    rows = []
    for cap, spec in CAPABILITIES.items():
        a_d = sorted(p for p in spec["android_permissions"] if p in a_decl)
        a_r = (dex[cap]["classes"] + dex[cap]["strings"]) if dex else None
        i_d = sorted(k for k in spec["ios_purpose_keys"] if k in i_keys)
        if spec.get("ios_background_mode") in i_modes:
            i_d.append(f"background:{spec['ios_background_mode']}")
        m = (mach.get("by_capability") or {}).get(cap) if mach else None
        plug = (mach.get("in_bundled_frameworks") or {}).get(cap, {}) if mach else {}
        def word(declared, referenced):
            if referenced is None:
                return "no binary to check"
            if declared and referenced:
                return "declared and referenced"
            if declared and not referenced:
                return "DECLARED, NO REFERENCE FOUND"
            if referenced and not declared:
                return "referenced but not declared"
            return "-"
        i_ref = None
        if m is not None:
            i_ref = m["selectors"] + (["plugin:" + f for f in plug]) + [f"linked:{f}" for f in m["linked"]] + [f"weak:{f}" for f in m["weak_linked"]]
        rows.append((cap,
                     ", ".join(p.split(".")[-1] for p in a_d) or "-", word(a_d, a_r),
                     ", ".join(k.removeprefix("NS").removesuffix("UsageDescription") for k in i_d) or "-",
                     word(i_d, [x for x in (i_ref or []) if not x.startswith(("linked:", "weak:"))]) if i_ref is not None else "no binary to check"))
    w = [max(len(r[i]) for r in rows + [("capability", "android declares", "android code", "ios declares", "ios code")]) for i in range(5)]
    head = ("capability", "android declares", "android code", "ios declares", "ios code")
    out = ["  ".join(h.ljust(w[i]) for i, h in enumerate(head)).rstrip()]
    out += ["  ".join(c.ljust(w[i]) for i, c in enumerate(r)).rstrip() for r in rows]
    if dex:
        out.append("")
        out.append("Android: a shrinker can rename bundled library classes, so 'no reference found' is proof only for capabilities the operating system provides itself.")
    unknown = sorted(k for k in i_keys if k not in APPLE_PURPOSE_KEYS)
    if unknown:
        out.append("")
        out.append("Purpose-string keys Apple does not define (they do nothing): " + ", ".join(unknown))
    return "\n".join(out)


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
        elif p["id"] == "android.built.references":
            lines.append(f"Android compiled code: {v['descriptors_scanned']} class descriptors scanned")
        elif p["id"] == "ios.built.references":
            lines.append(f"iOS executable {v['executable']}: linked " + ", ".join(v["frameworks"]["strong"]) + (" | weak: " + ", ".join(v["frameworks"]["weak"]) if v["frameworks"]["weak"] else ""))
        elif p["id"] == "store.apple.public":
            lines.append("App Store: " + (f"public, version {v.get('version')}" if v["public"] else "not public"))
        elif p["id"] == "store.google.public":
            lines.append("Google Play: " + (f"public: {v.get('title')}" if v["public"] else f"not public (HTTP {v.get('http')})"))
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
    probes = run_probes(app_dir, offline=args.offline)
    out = app_dir / "storecheck" / "probes.json"
    write_json(out, probes)
    stage = stage_mod.decide(probes)
    write_json(app_dir / "storecheck" / "stage.json", stage)
    print(describe(probes))
    print("\nSource versus built")
    print(compare(probes))
    print("\nDeclared versus referenced in the compiled code")
    print(usage_table(probes))
    print("\nStage")
    print(stage_mod.sentence(stage))
    grid = grid_mod.build(app_dir, probes, stage, as_of=args.as_of)
    gpath = app_dir / "storecheck" / "grid.json"
    write_json(gpath, grid)
    hpath = app_dir / "storecheck" / "grid.html"
    grid_mod.render(gpath, hpath, app_name=app_dir.name)
    print("\nGrid")
    for r in grid["rows"]:
        print(f"{r['verdict']:<9} {r['id']}\n          {r['evidence']}  [{r['provenance']}]")
    print("\n" + " · ".join(f"{k} {v}" for k, v in grid["counts"].items() if v) + f"; {len(grid['not_applicable'])} rules do not apply at this stage")
    print(f"{len(probes)} facts in {out}; grid in {gpath}; page in {hpath}")
    return 0


def cmd_check(args) -> int:
    app_dir = Path(args.app_dir).resolve()
    gpath = app_dir / "storecheck" / "grid.json"
    hpath = app_dir / "storecheck" / "grid.html"
    problems = []
    if not gpath.exists():
        problems.append(f"{gpath} does not exist; run audit first")
    else:
        try:
            grid_mod.validate(read_json(gpath))
            print("ok  every grid row carries exactly one provenance marker")
        except ValueError as e:
            problems.append(str(e))
        why = grid_mod.check_render(gpath, hpath, app_name=app_dir.name)
        if why:
            problems.append(why)
        else:
            print("ok  grid.html was generated from grid.json")
    bad = [r["id"] for r in corpus.load_all() if corpus.verify_from_cache(r)["status"] != "verified"]
    if bad:
        problems.append("corpus records not verified from cache: " + ", ".join(bad))
    else:
        print("ok  every corpus record matches its cached text")
    if problems:
        print("\nFAILED")
        for p in problems:
            print("  " + p)
        return 1
    print("\nall checks pass")
    return 0


def cmd_render(args) -> int:
    app_dir = Path(args.app_dir).resolve()
    gpath = app_dir / "storecheck" / "grid.json"
    grid_mod.render(gpath, app_dir / "storecheck" / "grid.html", app_name=app_dir.name)
    print(f"rendered {app_dir / 'storecheck' / 'grid.html'}")
    return 0


def cmd_self_test(args) -> int:
    for mod in ALL_PROBES + (listing, corpus, grid_mod):
        mod.self_test()
        print(f"ok  {mod.__name__}")
    return 0


def _corpus_line(r: dict) -> str:
    extra = f"  ({r['note']})" if r.get("note") else ""
    return f"{r['status']:<15} {r['id']}{extra}"


def cmd_corpus(args) -> int:
    records = corpus.load_all()
    if args.ids:
        records = [r for r in records if r["id"] in args.ids]
        missing = set(args.ids) - {r["id"] for r in records}
        if missing:
            print(f"no such record: {', '.join(sorted(missing))}", file=sys.stderr)
            return 1
    bad = 0
    if args.action == "list":
        for r in records:
            print(_corpus_line(r))
        return 0
    if args.action == "fetch":
        for r in records:
            corpus.fetch(r)
            corpus.save(r)
            print(_corpus_line(r))
            bad += r["status"] != "verified"
        print(f"\n{len(records) - bad} of {len(records)} verified")
        return 1 if bad else 0
    if args.action == "verify":
        for r in records:
            corpus.verify_from_cache(r)
            print(_corpus_line(r))
            bad += r["status"] != "verified"
        print(f"\n{len(records) - bad} of {len(records)} verified from cache, no network")
        return 1 if bad else 0
    if args.action == "accept":
        if not args.ids:
            print("accept needs the id of the record whose new text you have read", file=sys.stderr)
            return 1
        for r in records:
            r, diff = corpus.accept(r)
            corpus.save(r)
            print(diff or "(no previous text to diff against)")
            print(_corpus_line(r))
        return 0
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="storecheck", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="read the app and write its facts")
    a.add_argument("app_dir")
    a.add_argument("--offline", action="store_true", help="skip the store lookups")
    a.add_argument("--as-of", default=None, help="judge dated rules as of this date, YYYY-MM-DD")
    a.set_defaults(fn=cmd_audit)
    k = sub.add_parser("check", help="no network: the grid is well-formed, the page was generated from it, the corpus is unchanged")
    k.add_argument("app_dir")
    k.set_defaults(fn=cmd_check)
    r = sub.add_parser("render", help="regenerate grid.html from grid.json")
    r.add_argument("app_dir")
    r.set_defaults(fn=cmd_render)
    s = sub.add_parser("self-test", help="every probe checks itself")
    s.set_defaults(fn=cmd_self_test)
    c = sub.add_parser("corpus", help="the rule pages: fetch, verify from cache, accept a change, list")
    c.add_argument("action", choices=("fetch", "verify", "accept", "list"))
    c.add_argument("ids", nargs="*")
    c.set_defaults(fn=cmd_corpus)
    args = ap.parse_args(argv)
    return args.fn(args)
