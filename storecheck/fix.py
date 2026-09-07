"""Fix proposals, derived from what this app actually does. Never a template.

Every finding is a disagreement between two things. The proposal names which
of the two is wrong and what would make them agree, using the app's own
facts: the file that declares it, the code that references it, the words it
already uses. When a store form claims a feature the binary does not have,
the answer is a question for a person, never a patch.
"""

from __future__ import annotations

from pathlib import Path

from . import grid as grid_mod
from .capabilities import CAPABILITIES
from .schema import read_json


def app_model(probes: list[dict]) -> dict:
    """What the app does, from the facts alone."""
    by = {p["id"]: p for p in probes}
    val = lambda i: (by.get(i) or {}).get("value")
    src = lambda i: (by.get(i) or {}).get("source", {}).get("ref")
    amf = val("android.built.manifest") or val("android.source.manifest") or {}
    aref = (val("android.built.references") or {}).get("by_capability", {})
    info = val("ios.built.info") or val("ios.source.info") or {}
    iref = (val("ios.built.references") or {}).get("by_capability", {})
    iplug = (val("ios.built.references") or {}).get("in_bundled_frameworks", {})
    pm = (val("ios.built.privacy_manifests") or {})
    features = {}
    for cap, spec in CAPABILITIES.items():
        a_decl = [p for p in spec["android_permissions"] if p in amf.get("permissions", [])]
        a_used = bool(aref.get(cap, {}).get("classes") or aref.get(cap, {}).get("strings"))
        i_decl = [k for k in spec["ios_purpose_keys"] if k in info.get("purpose_strings", {})]
        i_used = bool(iref.get(cap, {}).get("selectors") or iplug.get(cap))
        features[cap] = {"android": {"declared": a_decl, "referenced": a_used, "evidence": aref.get(cap)},
                         "ios": {"declared": i_decl, "referenced": i_used, "evidence": iref.get(cap)}}
    return {
        "android": {"package": amf.get("package"), "manifest_file": src("android.source.manifest"), "permissions": amf.get("permissions", [])},
        "ios": {"bundle_id": info.get("bundle_id"), "info_plist": src("ios.source.info"), "purpose_strings": info.get("purpose_strings", {}),
                "background_modes": info.get("background_modes", [])},
        "features": features,
        "data_leaving_device": {
            "app_declares": [t["type"].replace("NSPrivacyCollectedDataType", "") for t in (pm.get("app") or {}).get("collected_data_types", [])],
            "sdks_declare": sorted({t["type"].replace("NSPrivacyCollectedDataType", "") for m in pm.get("third_party", {}).values() for t in m["collected_data_types"]}),
            "sdks": sorted(pm.get("third_party", {})),
        },
        "words": {"listing": val("listing.text") or {}, "privacy_policy_heading": (val("listing.privacy_policy_page") or {}).get("heading")},
    }


def propose(app_dir: Path, rule_id: str) -> dict:
    sc = app_dir / "storecheck"
    probes = read_json(sc / "probes.json")
    g = read_json(sc / "grid.json")
    row = next((r for r in g["rows"] if r["id"] == rule_id), None)
    if row is None:
        return {"kind": "none", "text": f"{rule_id} is not in the grid at this stage"}
    if row["verdict"] in ("PASS", "RESOLVED"):
        return {"kind": "none", "text": f"{rule_id} passes: {row['evidence']}"}
    m = app_model(probes)
    handler = HANDLERS.get(rule_id, generic)
    out = handler(row, m)
    out["rule"] = rule_id
    out["verdict"] = row["verdict"]
    out["derived_from"] = "the facts in probes.json for this app; nothing here is a template"
    return out


# ---- handlers: each names which side is wrong and what makes them agree

def purpose_keys(row, m):
    bad = [k for k in m["ios"]["purpose_strings"] if k not in __import__("storecheck.capabilities", fromlist=["APPLE_PURPOSE_KEYS"]).APPLE_PURPOSE_KEYS]
    return {"kind": "patch", "file": m["ios"]["info_plist"],
            "change": f"remove the keys {', '.join(bad)}; iOS ignores them, so nothing the app does depends on them",
            "rationale": "the declaration is wrong, the code is fine: these keys are not ones Apple defines"}


def built_matches_source(row, m):
    return {"kind": "rebuild", "change": "archive and export the app again from the current source before uploading anything",
            "rationale": "the artefact is wrong, the source is right: " + row["evidence"]}


def background_modes(row, m):
    unused = [mode for mode in m["ios"]["background_modes"]
              if any(s.get("ios_background_mode") == mode and not m["features"][c]["ios"]["referenced"] for c, s in CAPABILITIES.items())]
    return {"kind": "patch", "file": m["ios"]["info_plist"],
            "change": f"remove {', '.join(unused)} from UIBackgroundModes",
            "rationale": "the declaration is wrong: the executable references nothing that would use it. If the feature is meant to exist, the code side is what is missing, and that is a product decision"}


def purpose_string_missing(row, m):
    gaps = [c for c, f in m["features"].items() if f["ios"]["referenced"] and not f["ios"]["declared"] and CAPABILITIES[c]["ios_purpose_keys"]]
    lines = []
    for c in gaps:
        ev = m["features"][c]["ios"]["evidence"] or {}
        lines.append(f"{CAPABILITIES[c]['ios_purpose_keys'][0]}: the code references {', '.join(ev.get('selectors', []) or ev.get('linked', []))}; "
                     f"the string must say what the app does with {c} in this app's own words, naming the feature")
    return {"kind": "patch", "file": m["ios"]["info_plist"], "change": "\n".join(lines),
            "rationale": "the declaration is missing, the code is real. The wording is yours to write from the feature; the tool will not invent a purpose"}


def permissions_unused(row, m):
    unref = [p for c, f in m["features"].items() for p in f["android"]["declared"] if not f["android"]["referenced"]]
    return {"kind": "patch", "file": m["android"]["manifest_file"],
            "change": "remove " + ", ".join(unref) + " unless a bundled library needs it (a shrinker can hide the reference; check the library's documentation first)",
            "rationale": "the declaration is broader than the code; if the feature is intended, the code is what is missing"}


def background_location(row, m):
    f = m["features"]["background-location"]["android"]
    if f["declared"] and not f["referenced"]:
        return {"kind": "patch", "file": m["android"]["manifest_file"], "change": "remove android.permission.ACCESS_BACKGROUND_LOCATION",
                "rationale": "declared with nothing in the code that runs in the background"}
    return {"kind": "question", "text": "Background location is used (" + ", ".join((f["evidence"] or {}).get("strings", []) or (f["evidence"] or {}).get("classes", [])) +
            "). The Play declaration form must describe exactly that feature and nothing broader, and the video must show it. Does the filed declaration describe this feature, or a different one? If different, the form is wrong, not the app."}


def claims(row, m):
    return {"kind": "patch", "file": "the listing text (storecheck/listing.toml, then the console)",
            "change": "rewrite each sentence named in the evidence so the claim is denied or removed: " + row["evidence"],
            "rationale": "the words promise more than the app does"}


def policy_reachable(row, m):
    url = m["words"]["listing"].get("privacy_policy_url")
    return {"kind": "question", "text": f"The privacy policy link {url} does not answer with a real page: {row['evidence']}. Is the address wrong in the listing, or is the page down or moved? Fix whichever is wrong; a PDF is not accepted by Google."}


def deletion_link(row, m):
    return {"kind": "question", "text": "Google needs a web page where a person can delete the account without the app, declared in Data safety. " + row["evidence"] + ". Does such a page exist? If not, that is a feature to build, not a form to fill."}


def generic(row, m):
    if row["kind"] == "judgement":
        return {"kind": "question", "text": f"{row['title']}: {row['evidence']} Decide which side is wrong, the app or what describes it, with the facts: features {', '.join(c for c, f in m['features'].items() if f['ios']['referenced'] or f['android']['referenced'])}; data the app declares leaving the device: {', '.join(m['data_leaving_device']['app_declares']) or 'none declared'}; SDKs also collecting: {', '.join(m['data_leaving_device']['sdks_declare'])}"}
    return {"kind": "question", "text": f"{row['title']}: {row['evidence']}"}


HANDLERS = {
    "apple.purpose-string-keys-are-real": purpose_keys,
    "apple.built-matches-source": built_matches_source,
    "apple.background-modes-are-used": background_modes,
    "apple.purpose-string-for-every-used-capability": purpose_string_missing,
    "google.permissions-are-used": permissions_unused,
    "google.background-location-is-core": background_location,
    "both.no-unqualified-claims": claims,
    "both.privacy-policy-reachable": policy_reachable,
    "google.account-deletion-web-link": deletion_link,
}



# ---------------------------------------------------------------- actions for the report

def action_for(row: dict, model: dict, facts) -> dict | None:
    """What to do about this row, for a person or an agent: who, where, do, and a due date when dated.

    Derived from the same handlers as propose(), plus the row's own state for
    open questions. Never a template: files and console fields come from the
    app's facts; the wording of any fix stays the developer's to write.
    """
    v = row["verdict"]
    if v in ("PASS", "RESOLVED", "N/A"):
        return None
    ev = row["evidence"]
    if v == "PENDING":
        due = ev.split("in force from ")[-1].split(";")[0] if "in force from" in ev else None
        return {"who": "developer", "do": "Nothing yet. This obligation starts on the date shown; plan the change before then.", "due": due}
    if v == "UNKNOWN":
        if row["provenance"] == "needs-console-read":
            return {"who": "console", "where": "App Store Connect" if row["store"] == "apple" else ("Play Console" if row["store"] == "google" else "both consoles"),
                    "do": "Read the field named in the evidence and record it, or give the tool console credentials so it reads it itself."}
        if "awaiting judgement" in ev:
            return {"who": "reader", "do": "Answer the question with what was looked at, quoting the app's own text or screen, then record it with storecheck judge."}
        if "not decidable" in ev:
            return {"who": "build", "do": "Provide the built package so the tool can tell whether the rule applies."}
        return {"who": "person", "do": ev}
    handler = HANDLERS.get(row["id"])
    if handler:
        p = handler(row, model)
        who = {"patch": "developer", "rebuild": "build", "question": "person"}.get(p.get("kind"), "developer")
        return {"who": who, "where": p.get("file"), "do": p.get("change") or p.get("text"), "rationale": p.get("rationale")}
    if row["kind"] == "judgement":
        return {"who": "person", "do": f"A reader found: {ev} Decide which side is wrong, the app or the text that describes it, and change that side."}
    return {"who": "developer", "do": ev}


def _bg_location_action(row, m):
    missing = row["evidence"].split("missing: ")[-1] if "missing: " in row["evidence"] else row["evidence"]
    parts = []
    if "Play description" in missing:
        parts.append("In the Play Console description, add a sentence in the app's own words saying which feature uses location in the background or when the app is closed.")
    if "disclosure" in missing:
        parts.append("Add to the disclosure dialog shown before the location prompt: the word 'location', that it is used in the background or when the app is closed, and every feature that uses it.")
    if "privacy policy" in missing:
        parts.append("Make the hosted privacy policy mention location and its background use.")
    if "console" in missing:
        parts.append("File the Play declaration form naming exactly one background-location feature, with a video that shows the feature, the disclosure and the prompt.")
    if "no geofencing" in missing:
        parts.append("Either the permission is unused and should be removed, or the code reference is hidden by the shrinker; confirm which.")
    return {"kind": "patch", "file": "Play Console description; the app's disclosure dialog; the hosted privacy policy", "change": " ".join(parts) or missing,
            "rationale": "the app requests background location, so all four carriers must say so"}


def _fgs_action(row, m):
    return {"kind": "patch", "file": m["android"]["manifest_file"],
            "change": "Add the matching android.permission.FOREGROUND_SERVICE_<TYPE> permission for each foreground service type named in the evidence, or remove the service if it is never started. Then declare each type in Play Console with a description and a video.",
            "rationale": "Android 14 and later require the type-specific permission, and Google requires the console declaration"}


HANDLERS.update({
    "google.background-location-is-core": _bg_location_action,
    "google.foreground-service-types-declared": _fgs_action,
})
