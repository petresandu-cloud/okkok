"""How far along is this app? Decided from evidence, never from what anyone says.

Order, most advanced wins, per store:
  source-only         a manifest or plist exists and nothing is built
  built-not-uploaded  a matching built artefact exists
  internal-beta       a console shows the build on a test track   (needs console)
  in-review           a console shows a review in progress        (needs console)
  public              the store's public endpoint knows the app
"""

from __future__ import annotations

from .schema import STAGES


def decide(probes: list[dict]) -> dict:
    by = {p["id"]: p for p in probes}

    def val(id):
        p = by.get(id)
        return p["value"] if p else None

    def has(id):
        return val(id) is not None

    out = {"apple": None, "google": None, "evidence": [], "newer_build_on_disk": {"apple": False, "google": False}}

    # ---- Google
    g_stage, g_why = None, []
    if has("android.source.manifest") or has("android.source.gradle"):
        g_stage = "source-only"; g_why.append("source manifest present")
    src_pkg = (val("android.source.manifest") or {}).get("package") or (val("android.source.gradle") or {}).get("applicationId")
    built = val("android.built.manifest")
    if built:
        if src_pkg and built["package"] != src_pkg:
            g_why.append(f"built APK is for {built['package']}, not {src_pkg}: ignored")
        else:
            g_stage = "built-not-uploaded"; g_why.append(f"APK {built.get('artefact')} matches the source package")
    for console_stage in ("internal-beta", "in-review"):
        c = val(f"console.google.{console_stage}")
        if c:
            g_stage = console_stage; g_why.append(f"Play Console: {c}")
    pub = val("store.google.public")
    if pub is None and "store.google.public" in by:
        g_why.append("Play lookup failed; public status unknown")
    elif pub and pub["public"]:
        g_stage = "public"; g_why.append(f"Play details page is live: {pub.get('title')}")
    elif pub is not None:
        g_why.append(f"Play details page returns {pub.get('http')}: not public")
    out["google"] = g_stage
    out["evidence"].append({"store": "google", "why": g_why})

    # ---- Apple
    a_stage, a_why = None, []
    if has("ios.source.info"):
        a_stage = "source-only"; a_why.append("source Info.plist present")
    src_bid = (val("ios.source.info") or {}).get("bundle_id")
    ibuilt = val("ios.built.info")
    if ibuilt:
        if src_bid and ibuilt["bundle_id"] != src_bid:
            a_why.append(f"built bundle is {ibuilt['bundle_id']}, not {src_bid}: ignored")
        else:
            a_stage = "built-not-uploaded"; a_why.append(f"{ibuilt.get('artefact')} matches the source bundle id")
    for console_stage in ("internal-beta", "in-review"):
        c = val(f"console.apple.{console_stage}")
        if c:
            a_stage = console_stage; a_why.append(f"App Store Connect: {c}")
    apub = val("store.apple.public")
    if apub is None and "store.apple.public" in by:
        a_why.append("Apple lookup failed; public status unknown")
    elif apub and apub["public"]:
        a_stage = "public"; a_why.append(f"App Store lists version {apub.get('version')}")
        if ibuilt and ibuilt.get("version") and apub.get("version") and str(ibuilt["version"]) > str(apub["version"]):
            out["newer_build_on_disk"]["apple"] = True
    elif apub is not None:
        a_why.append("App Store lookup returns no result: not public")
    out["apple"] = a_stage
    out["evidence"].append({"store": "apple", "why": a_why})

    for k in ("apple", "google"):
        assert out[k] is None or out[k] in STAGES
    return out


NO_APP = ("No app found under {dir}. Looked for android/app/src/main/AndroidManifest.xml or ios/Runner/Info.plist "
          "(or those files at the top), and for an .apk, .aab, .ipa or .app anywhere below. Point storecheck at the app's own directory.")


def no_app(stage: dict) -> bool:
    return stage.get("apple") is None and stage.get("google") is None


def sentence(stage: dict) -> str:
    words = {
        None: "no app found",
        "source-only": "nothing built, nothing uploaded: only the source-level rules apply",
        "built-not-uploaded": "built, not uploaded: package and listing rules apply, console rules cannot be checked",
        "internal-beta": "on a test track: every rule applies except the public-listing ones",
        "in-review": "in review: every rule applies and listing rules are blocking",
        "public": "public: every rule applies",
    }
    return "\n".join(f"{s.capitalize()}: {stage[s] or 'no app'} — {words[stage[s]]}" for s in ("apple", "google"))
