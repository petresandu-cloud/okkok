"""The mechanical checks. Each takes the facts and returns (verdict, evidence, provenance).

A check never fetches anything and never guesses. When a fact it needs is
missing it says UNKNOWN and carries the missing probe's own provenance, so a
row that could only be settled by a console read says exactly that.
"""

from __future__ import annotations

import re

from .capabilities import APPLE_PURPOSE_KEYS, CAPABILITIES

DANGEROUS_ANDROID = {
    "android.permission.CAMERA": "camera", "android.permission.RECORD_AUDIO": "microphone",
    "android.permission.ACCESS_FINE_LOCATION": "location", "android.permission.ACCESS_COARSE_LOCATION": "location",
    "android.permission.ACCESS_BACKGROUND_LOCATION": "background-location",
    "android.permission.READ_CONTACTS": "contacts", "android.permission.WRITE_CONTACTS": "contacts",
    "android.permission.READ_MEDIA_IMAGES": "photos", "android.permission.READ_EXTERNAL_STORAGE": "photos",
    "android.permission.POST_NOTIFICATIONS": "notifications",
    "android.permission.BLUETOOTH_CONNECT": "bluetooth", "android.permission.BLUETOOTH_SCAN": "bluetooth",
    "android.permission.BODY_SENSORS": "health", "android.permission.ACTIVITY_RECOGNITION": "health",
}


class Facts:
    def __init__(self, probes: list[dict], stage: dict, as_of: str):
        self.by = {p["id"]: p for p in probes}
        self.stage = stage
        self.as_of = as_of

    def val(self, pid: str):
        p = self.by.get(pid)
        return p["value"] if p else None

    def missing(self, *pids: str):
        """First missing probe among pids, as (verdict, evidence, provenance), or None."""
        for pid in pids:
            p = self.by.get(pid)
            if p is None:
                return ("UNKNOWN", f"no fact {pid}: the probe did not run", "verified-directly")
            if p["value"] is None:
                return ("UNKNOWN", f"{pid}: {p.get('error')}", p["provenance"])
        return None


# ------------------------------------------------------------------ Apple

def purpose_strings_cover_usage(f: Facts):
    if m := f.missing("ios.built.info", "ios.built.references"):
        return m
    keys = f.val("ios.built.info")["purpose_strings"]
    refs = f.val("ios.built.references")["by_capability"]
    plug = f.val("ios.built.references").get("in_bundled_frameworks", {})
    gaps, covered = [], []
    for cap, spec in CAPABILITIES.items():
        if not spec["ios_purpose_keys"]:
            continue
        used = refs.get(cap, {}).get("selectors") or plug.get(cap)
        if not used:
            continue
        have = [k for k in spec["ios_purpose_keys"] if keys.get(k, "").strip()]
        (covered if have else gaps).append(cap)
    if gaps:
        return ("FAIL", "the code references " + ", ".join(gaps) + " but Info.plist has no purpose string for it; the app crashes or is rejected at that call", "verified-directly")
    return ("PASS", "every capability the code references has a purpose string: " + (", ".join(covered) or "none used"), "verified-directly")


def purpose_keys_are_real(f: Facts):
    info = f.val("ios.built.info") or f.val("ios.source.info")
    if info is None:
        return ("UNKNOWN", "no Info.plist read", "verified-directly")
    bad = sorted(k for k in info["purpose_strings"] if k not in APPLE_PURPOSE_KEYS)
    if bad:
        return ("RISK", "Info.plist carries keys Apple does not define, so they do nothing: " + ", ".join(bad), "verified-directly")
    return ("PASS", f"all {len(info['purpose_strings'])} purpose-string keys are ones Apple defines", "verified-directly")


def background_modes_used(f: Facts):
    if m := f.missing("ios.built.info", "ios.built.references"):
        return m
    modes = f.val("ios.built.info")["background_modes"]
    refs = f.val("ios.built.references")["by_capability"]
    plug = f.val("ios.built.references").get("in_bundled_frameworks", {})
    unused = []
    for mode in modes:
        cap = next((c for c, s in CAPABILITIES.items() if s.get("ios_background_mode") == mode), None)
        if cap is None:
            continue  # audio, fetch, processing and the like are not capability-gated
        r = refs.get(cap, {})
        if not (r.get("selectors") or plug.get(cap)):
            unused.append(mode)
    if unused:
        return ("FAIL", "UIBackgroundModes declares " + ", ".join(unused) + " but the executable references nothing that uses it; Apple rejects a background mode with no visible use", "verified-directly")
    return ("PASS", "declared background modes " + (", ".join(modes) or "none") + " each match referenced code", "verified-directly")


def privacy_manifest_present(f: Facts):
    if m := f.missing("ios.built.privacy_manifests"):
        return m
    v = f.val("ios.built.privacy_manifests")
    if not v.get("app"):
        return ("FAIL", "no PrivacyInfo.xcprivacy at the top of the app bundle", "verified-directly")
    n = len(v["app"]["collected_data_types"])
    return ("PASS", f"the app's own manifest is bundled and declares {n} data types; {len(v['third_party'])} third-party manifests alongside", "verified-directly")


def tracking_consistent(f: Facts):
    if m := f.missing("ios.built.privacy_manifests", "ios.built.info"):
        return m
    v = f.val("ios.built.privacy_manifests")
    keys = f.val("ios.built.info")["purpose_strings"]
    refs = (f.val("ios.built.references") or {}).get("by_capability", {})
    app = v.get("app") or {}
    tracks = app.get("tracking") or any(t["tracking"] for t in app.get("collected_data_types", []))
    third_tracks = [n for n, t in v["third_party"].items() if t["tracking"] or any(d["tracking"] for d in t["collected_data_types"])]
    has_prompt = bool(keys.get("NSUserTrackingUsageDescription")) or bool(refs.get("tracking", {}).get("selectors"))
    if (tracks or third_tracks) and not has_prompt:
        return ("FAIL", "a manifest declares tracking (" + ", ".join(["app"] * bool(tracks) + third_tracks) + ") but there is no tracking purpose string or prompt", "verified-directly")
    if has_prompt and not (tracks or third_tracks):
        return ("RISK", "a tracking prompt exists but no manifest declares tracking; one of them is wrong", "verified-directly")
    if app.get("tracking_domains") and not app.get("tracking"):
        return ("FAIL", "tracking domains are listed while NSPrivacyTracking is false", "verified-directly")
    return ("PASS", "no manifest declares tracking and no tracking prompt exists", "verified-directly")


def listed_sdk_manifests(f: Facts):
    if m := f.missing("ios.built.info", "ios.built.privacy_manifests"):
        return m
    from .corpus import CACHE_DIR
    cache = CACHE_DIR / "apple.third-party-sdk.txt"
    if not cache.exists():
        return ("UNKNOWN", "Apple's SDK list is not in the corpus cache; run corpus fetch", "verified-directly")
    text = cache.read_text(encoding="utf-8")
    from pathlib import Path
    names = [l.strip() for l in (Path(__file__).parent / "data" / "apple-listed-sdks.txt").read_text().splitlines()
             if l.strip() and not l.startswith("#")]
    gone = [n for n in names if n not in text]
    if gone:
        return ("UNKNOWN", "the recorded SDK list no longer matches Apple's page (missing: " + ", ".join(gone[:5]) + "); update data/apple-listed-sdks.txt from the verified page", "verified-directly")
    fws = [x.removesuffix(".framework") for x in f.val("ios.built.info")["frameworks"] if x.endswith(".framework")]
    have = set(f.val("ios.built.privacy_manifests")["third_party"])
    listed = [w for w in fws if w in names]
    missing = [w for w in listed if w not in have]
    if missing:
        return ("FAIL", "bundled frameworks on Apple's list without a privacy manifest: " + ", ".join(missing), "verified-directly")
    note = " Libraries linked statically cannot be enumerated from the binary; only their manifests are visible." 
    return ("PASS", f"{len(listed)} bundled frameworks are on Apple's list and each carries a manifest; {len(have)} third-party manifests present in all." + note, "verified-directly")


def ios_built_matches_source(f: Facts):
    if m := f.missing("ios.source.info", "ios.built.info"):
        return m
    s, b = f.val("ios.source.info"), f.val("ios.built.info")
    diffs = []
    if set(s["background_modes"]) != set(b["background_modes"]):
        diffs.append(f"background modes {s['background_modes']} in source, {b['background_modes']} in the build")
    if set(s["purpose_strings"]) != set(b["purpose_strings"]):
        diffs.append("purpose-string keys differ")
    ps, pb = f.val("ios.source.privacy_manifest"), (f.val("ios.built.privacy_manifests") or {}).get("app")
    if ps and pb and len(ps["collected_data_types"]) != len(pb["collected_data_types"]):
        diffs.append(f"privacy manifest declares {len(ps['collected_data_types'])} types in source, {len(pb['collected_data_types'])} in the build")
    if diffs:
        return ("RISK", f"{b.get('artefact')} (built {b.get('artefact_modified')}) is not the app the source describes: " + "; ".join(diffs) + ". Rebuild before anything is uploaded", "verified-directly")
    return ("PASS", f"{b.get('artefact')} matches the source on background modes, purpose strings and privacy manifest", "verified-directly")


def signed_for_store(f: Facts):
    if m := f.missing("ios.built.profile", "ios.built.info"):
        return m
    p = f.val("ios.built.profile")
    modes = f.val("ios.built.info")["background_modes"]
    problems = []
    if p.get("kind") != "app-store":
        problems.append(f"signed with a {p.get('kind')} profile")
    aps = p.get("entitlements", {}).get("aps-environment")
    if "remote-notification" in modes and aps != "production":
        problems.append(f"push is declared but aps-environment is {aps!r}")
    if problems:
        return ("FAIL", "; ".join(problems), "verified-directly")
    return ("PASS", f"App Store profile for {p.get('team')}, aps-environment {aps}, expires {p.get('expires')}", "verified-directly")


def ipad_claim(f: Facts):
    if m := f.missing("ios.built.info"):
        return m
    fam = f.val("ios.built.info")["device_family"]
    if 2 in fam:
        return ("NOTE", "UIDeviceFamily claims iPad: reviewers test on iPad and the listing needs iPad screenshots. If the app is iPhone-only, remove iPad from the target", "verified-directly")
    return ("PASS", "iPhone only", "verified-directly")


# ------------------------------------------------------------------ Google

def target_api(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    t = f.val("android.built.manifest")["targetSdk"]
    need = 36 if f.as_of >= "2026-08-31" else 35
    if t is None:
        return ("UNKNOWN", "the built manifest carries no targetSdkVersion", "verified-directly")
    if t < need:
        return ("FAIL", f"targetSdk {t}; Google Play requires {need} for new apps and updates from the date quoted in the corpus", "verified-directly")
    return ("PASS", f"targetSdk {t} meets the requirement of {need}", "verified-directly")


def not_debuggable(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    v = f.val("android.built.manifest")
    if v.get("debuggable"):
        return ("FAIL", f"{v.get('artefact')} is debuggable; Play refuses debuggable releases", "verified-directly")
    return ("PASS", f"{v.get('artefact')} is not debuggable", "verified-directly")


def permissions_used(f: Facts):
    if m := f.missing("android.built.manifest", "android.built.references"):
        return m
    declared = f.val("android.built.manifest")["permissions"]
    refs = f.val("android.built.references")["by_capability"]
    unref = []
    for perm, cap in DANGEROUS_ANDROID.items():
        if perm in declared:
            r = refs.get(cap, {})
            if not (r.get("classes") or r.get("strings")):
                unref.append(perm.split(".")[-1])
    if unref:
        return ("RISK", "declared with no reference found in the compiled code: " + ", ".join(unref) + ". A shrinker can hide library classes, so confirm before removing", "verified-directly")
    n = sum(1 for p in DANGEROUS_ANDROID if p in declared)
    return ("PASS", f"all {n} sensitive permissions declared are referenced by the compiled code", "verified-directly")


def background_location(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    declared = f.val("android.built.manifest")["permissions"]
    if "android.permission.ACCESS_BACKGROUND_LOCATION" not in declared:
        return ("PASS", "background location is not requested", "verified-directly")
    if m := f.missing("android.built.references"):
        return m
    r = f.val("android.built.references")["by_capability"].get("background-location", {})
    if not (r.get("classes") or r.get("strings")):
        return ("FAIL", "ACCESS_BACKGROUND_LOCATION is declared but nothing in the compiled code references geofencing or background updates", "verified-directly")
    if m := f.missing("console.google.declarations"):
        return ("UNKNOWN", "background location is declared and used (" + ", ".join(r.get("strings") or r.get("classes")) + "); whether the console declaration and video match it needs a console read", m[2])
    d = f.val("console.google.declarations")
    if not d.get("background_location_declared"):
        return ("FAIL", "background location is used but the Play declaration form is not filed", "verified-directly")
    return ("PASS", "background location is used and the Play declaration is filed", "verified-directly")


def location_scope(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    declared = f.val("android.built.manifest")["permissions"]
    if "android.permission.ACCESS_FINE_LOCATION" not in declared:
        return ("PASS", "precise location is not requested", "verified-directly")
    if m := f.missing("console.google.declarations"):
        return ("UNKNOWN", "precise location is requested; the location-scope declaration lives in the console", m[2])
    d = f.val("console.google.declarations")
    if not d.get("location_scope_declared"):
        return ("FAIL", "precise location is requested and the scope declaration is not filed", "verified-directly")
    return ("PASS", "scope declaration filed", "verified-directly")


def deletion_link(f: Facts):
    if m := f.missing("listing.text"):
        return m
    url = f.val("listing.text").get("deletion_url")
    if m := f.missing("console.google.data-safety"):
        if url:
            return ("UNKNOWN", f"a deletion page is named ({url}); whether it is declared in Data safety needs a console read", m[2])
        return ("UNKNOWN", "no deletion_url in listing.toml and no console read", m[2])
    ds = f.val("console.google.data-safety")
    if not ds.get("deletion_url"):
        return ("FAIL", "Data safety names no web page for deleting the account without the app", "verified-directly")
    return ("PASS", f"Data safety names {ds['deletion_url']}", "verified-directly")


# ------------------------------------------------------------------ Both

EMOJI = re.compile(r"[\U0001F000-\U0001FAFF☀-➿]")


def listing_name(f: Facts):
    if m := f.missing("listing.text"):
        return m
    name = f.val("listing.text").get("name", "")
    problems = []
    if len(name) > 30:
        problems.append(f"{len(name)} characters, limit 30")
    if EMOJI.search(name):
        problems.append("contains an emoji")
    if re.sub(r"[\w\s'&-]", "", name, flags=re.UNICODE):
        problems.append("contains special characters")
    shout = [w for w in re.findall(r"\b[A-Z]{3,}\b", name) if w not in ("SOS", "GPS", "AI", "VPN", "PDF")]
    if shout:
        problems.append("shouts in capitals: " + ", ".join(shout))
    if problems:
        return ("FAIL", f"name {name!r}: " + "; ".join(problems), "verified-directly")
    return ("PASS", f"name {name!r} is {len(name)} characters, plain", "verified-directly")


def listing_lengths(f: Facts):
    if m := f.missing("listing.text"):
        return m
    t = f.val("listing.text")
    limits = [("apple.subtitle", t.get("apple", {}).get("subtitle", ""), 30),
              ("apple.description", t.get("apple", {}).get("description", ""), 4000),
              ("apple.keywords", t.get("apple", {}).get("keywords", ""), 100),
              ("google.short_description", t.get("google", {}).get("short_description", ""), 80),
              ("google.full_description", t.get("google", {}).get("full_description", ""), 4000)]
    over = [f"{k} is {len(v)}/{n}" for k, v, n in limits if len(v) > n]
    if over:
        return ("FAIL", "; ".join(over), "verified-directly")
    return ("PASS", "; ".join(f"{k} {len(v)}/{n}" for k, v, n in limits if v), "verified-directly")


NEGATION = re.compile(r"\b(not|no|never|cannot|can't|doesn't|does not|do not|isn't|is not|nu|inte|ingen|nicht|kein|ne|pas)\b", re.I)
GUARANTEE = re.compile(r"\b(guarantee[sd]?|garant\w*)\b", re.I)
EMERGENCY = re.compile(r"\b(emergency (service|response)s?|call(s|ing)? (911|112|999)|send help|dispatch|life[- ]saving)\b", re.I)


# Advice to the user about emergencies is the opposite of a claim to provide them.
INSTRUCTION = re.compile(r"\b(should|please|always) (contact|call|dial)\b|\bcontact (local|your|the) emergency\b|\bcall (local|your|the) emergency\b", re.I)


def no_unqualified_claims(f: Facts):
    if m := f.missing("listing.text"):
        return m
    t = f.val("listing.text")
    texts = []
    for store in ("apple", "google"):
        for k, v in t.get(store, {}).items():
            texts.append((f"{store}.{k}", v))
    info = f.val("ios.built.info") or f.val("ios.source.info") or {}
    texts += [(k, v) for k, v in info.get("purpose_strings", {}).items()]
    bad = []
    for label, text in texts:
        for sentence in re.split(r"(?<=[.!?])\s+", str(text)):
            if (GUARANTEE.search(sentence) or EMERGENCY.search(sentence)) and not NEGATION.search(sentence) and not INSTRUCTION.search(sentence):
                bad.append(f"{label}: {sentence.strip()[:90]!r}")
    if bad:
        return ("FAIL", "claims with no negation next to them: " + " | ".join(bad), "verified-directly")
    return ("PASS", f"{len(texts)} texts checked; every guarantee or emergency mention is a denial", "verified-directly")


def privacy_policy_reachable(f: Facts):
    if m := f.missing("listing.text", "listing.privacy_policy_page"):
        return m
    p = f.val("listing.privacy_policy_page")
    problems = []
    if p["http"] != 200:
        problems.append(f"HTTP {p['http']}")
    if p.get("is_pdf"):
        problems.append("it is a PDF, which Google does not accept")
    if p["characters"] < 400:
        problems.append(f"only {p['characters']} characters of text")
    if problems:
        return ("FAIL", f"{f.val('listing.text').get('privacy_policy_url')}: " + "; ".join(problems), "verified-directly")
    return ("PASS", f"{p['final_url']} answers 200 with {p['characters']} characters under the heading {p.get('heading')!r}", "verified-directly")


# ------------------------------------------------------------------ Apple guidelines, section rules

PLACEHOLDER = re.compile(r"\b(lorem ipsum|todo|tbd|coming soon|placeholder|insert text|xxx+|test test|asdf)\b", re.I)


def listing_no_placeholders(f: Facts):
    if m := f.missing("listing.text"):
        return m
    t = f.val("listing.text")
    hits = []
    for store in ("apple", "google"):
        for k, v in t.get(store, {}).items():
            for mm in PLACEHOLDER.finditer(str(v)):
                hits.append(f"{store}.{k}: {mm.group(0)!r}")
    if PLACEHOLDER.search(t.get("name", "")):
        hits.append("name")
    if hits:
        return ("FAIL", "placeholder text: " + "; ".join(hits), "verified-directly")
    return ("PASS", "no placeholder or temporary text in the listing fields", "verified-directly")


def support_url_reachable(f: Facts):
    if m := f.missing("listing.text", "listing.support_page"):
        return m
    p = f.val("listing.support_page")
    url = f.val("listing.text").get("support_url")
    problems = []
    if p["http"] != 200:
        problems.append(f"HTTP {p['http']}")
    if p["characters"] < 100:
        problems.append(f"only {p['characters']} characters")
    if not p.get("has_contact"):
        problems.append("no contact address or contact form found on it")
    if problems:
        return ("FAIL", f"{url}: " + "; ".join(problems), "verified-directly")
    return ("PASS", f"{p['final_url']} answers 200 with a way to make contact", "verified-directly")


def ats_not_disabled(f: Facts):
    info = f.val("ios.built.info") or f.val("ios.source.info")
    if info is None:
        return ("UNKNOWN", "no Info.plist read", "verified-directly")
    ats = info.get("app_transport_security") or {}
    if ats.get("NSAllowsArbitraryLoads"):
        return ("RISK", "NSAllowsArbitraryLoads is true: every connection may be plain HTTP, and Apple asks why", "verified-directly")
    return ("PASS", "App Transport Security is on" + (" with exceptions for named domains" if ats.get("NSExceptionDomains") else ""), "verified-directly")


def sign_in_with_apple_offered(f: Facts):
    if m := f.missing("ios.built.references"):
        return m
    sig = f.val("ios.built.references").get("signals", [])
    if "social-login" not in sig:
        return ("PASS", "no third-party social login in the executable, so no equivalent option is required", "verified-directly")
    if "sign-in-with-apple" in sig:
        return ("PASS", "a social login is present and Sign in with Apple is present alongside it", "verified-directly")
    return ("FAIL", "the executable carries a third-party social login but no Sign in with Apple; 4.8 requires an equivalent private option", "verified-directly")


# ------------------------------------------------------------------ Google device and network abuse

FGS_TYPES = {1: "dataSync", 2: "mediaPlayback", 4: "phoneCall", 8: "location", 16: "connectedDevice", 32: "mediaProjection",
             64: "camera", 128: "microphone", 256: "health", 512: "remoteMessaging", 1024: "systemExempted", 2048: "shortService",
             4096: "mediaProcessing", 1073741824: "specialUse"}
FGS_PERMISSION = {"dataSync": "FOREGROUND_SERVICE_DATA_SYNC", "mediaPlayback": "FOREGROUND_SERVICE_MEDIA_PLAYBACK",
                  "phoneCall": "FOREGROUND_SERVICE_PHONE_CALL", "location": "FOREGROUND_SERVICE_LOCATION",
                  "connectedDevice": "FOREGROUND_SERVICE_CONNECTED_DEVICE", "mediaProjection": "FOREGROUND_SERVICE_MEDIA_PROJECTION",
                  "camera": "FOREGROUND_SERVICE_CAMERA", "microphone": "FOREGROUND_SERVICE_MICROPHONE", "health": "FOREGROUND_SERVICE_HEALTH",
                  "remoteMessaging": "FOREGROUND_SERVICE_REMOTE_MESSAGING", "systemExempted": "FOREGROUND_SERVICE_SYSTEM_EXEMPTED",
                  "mediaProcessing": "FOREGROUND_SERVICE_MEDIA_PROCESSING", "specialUse": "FOREGROUND_SERVICE_SPECIAL_USE"}


def _fgs_names(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split("|") if v.strip()]
    return [n for bit, n in FGS_TYPES.items() if int(value) & bit]


def foreground_service_types(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    v = f.val("android.built.manifest")
    services = [s for s in v.get("services", []) if s.get("foregroundServiceType") is not None]
    if not services:
        return ("PASS", "no foreground services declared", "verified-directly")
    target = v.get("targetSdk") or 0
    perms = set(v["permissions"])
    missing = []
    types = set()
    for s in services:
        for t in _fgs_names(s["foregroundServiceType"]):
            types.add(t)
            p = FGS_PERMISSION.get(t)
            if p and f"android.permission.{p}" not in perms:
                missing.append(f"{s.get('name')} uses {t} without android.permission.{p}")
    if target >= 34 and missing:
        return ("FAIL", "; ".join(missing), "verified-directly")
    if m := f.missing("console.google.declarations"):
        return ("UNKNOWN", f"foreground service types {', '.join(sorted(types))} each have their permission; whether they are declared in Play Console with description and video needs a console read", m[2])
    return ("PASS", f"foreground service types {', '.join(sorted(types))} with permissions, declared in the console", "verified-directly")


def battery_bypass(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    perms = f.val("android.built.manifest")["permissions"]
    if "android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS" not in perms:
        return ("PASS", "the app does not ask to be exempted from battery optimisation", "verified-directly")
    return ("RISK", "REQUEST_IGNORE_BATTERY_OPTIMIZATIONS is declared. Google allows bypassing power management only for apps eligible for allowlisting, where the core function breaks otherwise; be ready to show why, and remove it if the app works without it", "verified-directly")


def full_screen_intent(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    perms = f.val("android.built.manifest")["permissions"]
    if "android.permission.USE_FULL_SCREEN_INTENT" not in perms:
        return ("PASS", "the full-screen intent permission is not declared", "verified-directly")
    return ("RISK", "USE_FULL_SCREEN_INTENT is declared. On Android 14 and later it is granted automatically only to apps whose core is alarms or calls; any other app must ask the user for it, and using it for disruptive notifications or ads is a violation. Confirm the use and the Play declaration", "verified-directly")


# ------------------------------------------------------------------ Google restricted permissions

RESTRICTED = {
    "android.permission.READ_SMS": ("FAIL", "only the device's default SMS or Assistant handler may declare SMS permissions"),
    "android.permission.SEND_SMS": ("FAIL", "only the device's default SMS or Assistant handler may declare SMS permissions"),
    "android.permission.RECEIVE_SMS": ("FAIL", "only the device's default SMS or Assistant handler may declare SMS permissions"),
    "android.permission.RECEIVE_MMS": ("FAIL", "only the device's default SMS or Assistant handler may declare SMS permissions"),
    "android.permission.RECEIVE_WAP_PUSH": ("FAIL", "only the device's default SMS or Assistant handler may declare SMS permissions"),
    "android.permission.READ_CALL_LOG": ("FAIL", "only the default Phone or Assistant handler may declare call-log permissions"),
    "android.permission.WRITE_CALL_LOG": ("FAIL", "only the default Phone or Assistant handler may declare call-log permissions"),
    "android.permission.PROCESS_OUTGOING_CALLS": ("FAIL", "only the default Phone or Assistant handler may declare call-log permissions"),
    "android.permission.MANAGE_EXTERNAL_STORAGE": ("RISK", "all-files access needs Google's access review before publishing and a clear prompt to enable it"),
    "android.permission.QUERY_ALL_PACKAGES": ("RISK", "broad package visibility is allowed only for named use cases; use targeted queries where possible and file the declaration"),
    "android.permission.REQUEST_INSTALL_PACKAGES": ("RISK", "allowed only where sending or installing packages is the app's promoted core purpose"),
    "android.permission.BODY_SENSORS": ("RISK", "body-sensor data falls under the User Data and Health apps policies; approved uses only, and Android 16 wants the granular health permissions"),
    "android.permission.BODY_SENSORS_BACKGROUND": ("RISK", "body-sensor data falls under the User Data and Health apps policies; approved uses only"),
    "android.permission.USE_EXACT_ALARM": ("RISK", "exact alarms are for alarm, timer and calendar apps; consider SCHEDULE_EXACT_ALARM otherwise"),
    "android.permission.BIND_ACCESSIBILITY_SERVICE": ("RISK", "an accessibility service must be documented in the listing and never change settings or defeat platform controls"),
}


def restricted_permissions(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    v = f.val("android.built.manifest")
    perms = set(v["permissions"])
    target = v.get("targetSdk") or 0
    listing = f.val("listing.text") or {}
    listing_text = " ".join(str(x) for s in ("apple", "google") for x in listing.get(s, {}).values()).lower()
    worst, notes = "PASS", []
    order = {"PASS": 0, "RISK": 1, "FAIL": 2}
    for p, (verdict, why) in RESTRICTED.items():
        if p in perms:
            notes.append(f"{p.split('.')[-1]}: {why}")
            worst = max(worst, verdict, key=order.get)
    if target >= 33 and perms & {"android.permission.READ_MEDIA_IMAGES", "android.permission.READ_MEDIA_VIDEO"}:
        notes.append("READ_MEDIA_IMAGES/VIDEO on Android 13+: allowed only where the photo picker is not enough, with a Play Console declaration")
        worst = max(worst, "RISK", key=order.get)
    if "android.permission.health.READ_HEART_RATE" in perms or any(p.startswith("android.permission.health.") for p in perms):
        notes.append("health.* permissions: Health Connect approved uses only, under the Health apps policy")
        worst = max(worst, "RISK", key=order.get)
    if "android.permission.BIND_ACCESSIBILITY_SERVICE" in perms and listing and "accessibility" not in listing_text:
        notes.append("the accessibility service is not mentioned in the listing, which the policy requires")
        worst = max(worst, "FAIL", key=order.get)
    if not notes:
        return ("PASS", "no restricted permission beyond location, camera, notifications and the like is declared", "verified-directly")
    return (worst, "; ".join(notes), "verified-directly")


def contacts_declaration(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    if (f.val("android.built.manifest").get("targetSdk") or 0) < 37:
        return ("PASS", "the contacts rule binds apps targeting Android 17 (API 37) or later; this build targets lower", "verified-directly")
    if m := f.missing("console.google.declarations"):
        return ("UNKNOWN", "READ_CONTACTS is declared on an Android 17 target; whether the Contacts declaration is filed needs a console read", m[2])
    d = f.val("console.google.declarations")
    if not d.get("contacts_declared"):
        return ("FAIL", "READ_CONTACTS is declared and no Contacts declaration explains why the Contact Picker is not enough", "verified-directly")
    return ("PASS", "Contacts declaration filed", "verified-directly")



# ------------------------------------------------------------------ Google malware and SDK policies

def monitoring_flag(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    v = f.val("android.built.manifest")
    flagged = [k for k in v.get("meta_data", {}) if "ismonitoringtool" in k.lower()]
    if flagged:
        return ("RISK", "the manifest declares itself a monitoring tool (" + ", ".join(flagged) + "). Google accepts monitoring apps only for parents over their children or employers over employees, exclusively marketed as such, with a persistent notification, a unique icon and the monitoring disclosed in the description; tracking any other adult is forbidden even with consent", "verified-directly")
    return ("PASS", "no IsMonitoringTool flag in the manifest; if the app lets one person watch another, the judgement rule decides whether it is a monitoring app at all", "verified-directly")


def cleartext_traffic(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    app = f.val("android.built.manifest").get("application", {})
    if app.get("usesCleartextTraffic") is True:
        return ("RISK", "usesCleartextTraffic is true: personal data may travel over plain HTTP, which the SDK and User Data policies forbid for sensitive data", "verified-directly")
    return ("PASS", "cleartext traffic is not enabled" + (" and a network security config is set" if app.get("networkSecurityConfig") else ""), "verified-directly")


# ------------------------------------------------------------------ Google listing metadata

def google_metadata_rules(f: Facts):
    if m := f.missing("listing.text"):
        return m
    t = f.val("listing.text")
    name = t.get("name", "")
    dev = t.get("developer_name", "")
    problems = []
    for label, s in (("title", name), ("developer name", dev)):
        if not s:
            continue
        if EMOJI.search(s):
            problems.append(f"{label} carries an emoji")
        if re.search(r"([^\w\s])\1{1,}", s):
            problems.append(f"{label} repeats special characters")
        if re.search(r"\b(#\s?1|no\.? ?1|best|top rated|award|editor'?s choice|new|free|sale|% off|cheap|popular|app of the year)\b", s, re.I):
            problems.append(f"{label} claims ranking, price or a Play programme")
    if len(name) > 30:
        problems.append(f"title is {len(name)} characters, limit 30")
    for store in ("apple", "google"):
        for k, v in t.get(store, {}).items():
            for q in re.findall(r"[\"“]([^\"”]{25,})[\"”]", str(v)):
                after = str(v)[str(v).find(q) + len(q):][:60]
                if not re.search(r"[—–-]\s*[A-Z]", after):
                    problems.append(f"{store}.{k}: a quotation with no attributed source: {q[:50]!r}")
    if problems:
        return ("FAIL", "; ".join(problems), "verified-directly")
    return ("PASS", f"title {name!r} and developer name pass the metadata rules; no anonymous testimonials", "verified-directly")


def content_rating_filed(f: Facts):
    if m := f.missing("console.google.declarations"):
        return ("UNKNOWN", "the IARC content rating lives only in Play Console", m[2])
    d = f.val("console.google.declarations")
    if not d.get("content_rating"):
        return ("FAIL", "no content rating on file; Play removes unrated apps", "verified-directly")
    return ("PASS", f"content rating {d['content_rating']}", "verified-directly")


def package_registered(f: Facts):
    if m := f.missing("console.google.declarations"):
        return ("UNKNOWN", "whether the package is registered for Android developer verification is visible only in Play Console", m[2])
    d = f.val("console.google.declarations")
    if not d.get("package_registered"):
        return ("FAIL", "the package is not registered for developer verification; unregistered apps are removed", "verified-directly")
    return ("PASS", "package registered for developer verification", "verified-directly")


# ==================================================================================
# Corrected checks after the rule-fidelity pass of 2026-09-07. Each definition below
# replaces the earlier one of the same name; the reader's finding is quoted in the
# rule's check_review field.
# ==================================================================================

IMPERATIVE = re.compile(r"^(turn on|allow|enable|grant|give|please|we need|needs?|required|tap)\b", re.I)
VAGUE = re.compile(r"\b(better experience|is needed|is required|to work properly|for functionality|to function)\b", re.I)


def purpose_keys_are_real(f: Facts):
    """Now: the content of every purpose string, per Apple's HIG; unknown keys are a NOTE."""
    info = f.val("ios.built.info") or f.val("ios.source.info")
    if info is None:
        return ("UNKNOWN", "no Info.plist read", "verified-directly")
    strings = info["purpose_strings"]
    unknown = sorted(k for k in strings if k not in APPLE_PURPOSE_KEYS)
    weak, advisory = [], []
    for k, s in strings.items():
        s = (s or "").strip()
        short = k.removeprefix("NS").removesuffix("UsageDescription")
        if not s or s == k or len(s.split()) < 4 or PLACEHOLDER.search(s):
            weak.append(f"{short}: empty, a placeholder, or too short to say anything: {s!r}")
        elif IMPERATIVE.match(s) or VAGUE.search(s):
            weak.append(f"{short}: says only that access is wanted, not what the app does with it: {s!r}")
        else:
            if not s.endswith("."):
                advisory.append(f"{short} has no final period")
            if s[0].isupper() is False:
                advisory.append(f"{short} is not sentence case")
    parts = []
    verdict = "PASS"
    if weak:
        verdict = "RISK"; parts.append("strings that do not say how the app uses the access: " + "; ".join(weak))
    if unknown:
        parts.append("keys Apple does not define, which iOS ignores: " + ", ".join(unknown))
        verdict = "RISK" if verdict == "PASS" else verdict
    if advisory:
        parts.append("advisory, the HIG says should: " + "; ".join(advisory))
    if not parts:
        return ("PASS", f"all {len(strings)} purpose strings name what the app does with the access, in sentence case with a period", "verified-directly")
    return (verdict, "; ".join(parts), "verified-directly")


def tracking_consistent(f: Facts):
    if m := f.missing("ios.built.privacy_manifests", "ios.built.info"):
        return m
    v = f.val("ios.built.privacy_manifests")
    keys = f.val("ios.built.info")["purpose_strings"]
    refs = (f.val("ios.built.references") or {}).get("by_capability", {})
    app = v.get("app") or {}
    app_tracks = bool(app.get("tracking")) or any(t["tracking"] for t in app.get("collected_data_types", []))
    third = [n for n, t in v["third_party"].items() if t["tracking"] or any(d["tracking"] for d in t["collected_data_types"])]
    tracking = app_tracks or bool(third)
    att_string = bool(keys.get("NSUserTrackingUsageDescription"))
    att_call = bool(refs.get("tracking", {}).get("selectors"))
    if tracking and not (att_string and att_call):
        who = ", ".join((["the app"] if app_tracks else []) + third)
        return ("FAIL", f"tracking is declared by {who} but " + ("no App Tracking Transparency call is referenced" if att_string else "there is no tracking purpose string") + "; Apple requires explicit permission through the ATT API", "verified-directly")
    if app.get("tracking") and not app.get("tracking_domains"):
        return ("FAIL", "NSPrivacyTracking is true but NSPrivacyTrackingDomains is empty; Apple requires the domains", "verified-directly")
    if app.get("tracking_domains") and not app.get("tracking"):
        return ("FAIL", "tracking domains are listed while NSPrivacyTracking is false", "verified-directly")
    if tracking:
        return ("PASS", "tracking is declared and the ATT purpose string and API call are both present; whether the prompt precedes the first tracking call is a judgement over the launch flow", "verified-directly")
    if att_string or att_call:
        return ("NOTE", "an ATT purpose string or call exists while no manifest declares tracking; harmless if an SDK carries it, worth a look", "verified-directly")
    return ("PASS", "no manifest declares tracking and no tracking prompt exists", "verified-directly")


def foreground_service_types(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    v = f.val("android.built.manifest")
    perms = set(v["permissions"])
    target = v.get("targetSdk") or 0
    services = v.get("services", [])
    typed = [s for s in services if s.get("foregroundServiceType") is not None]
    untyped = [s for s in services if s.get("foregroundServiceType") is None]
    problems, types = [], set()
    if "android.permission.FOREGROUND_SERVICE" in perms and untyped and not typed:
        problems.append("the app holds FOREGROUND_SERVICE but no service declares a foregroundServiceType: " + ", ".join(str(s.get("name")) for s in untyped[:5]))
    for s in typed:
        for t in _fgs_names(s["foregroundServiceType"]):
            types.add(t)
            p = FGS_PERMISSION.get(t)
            if p and f"android.permission.{p}" not in perms:
                problems.append(f"{s.get('name')} uses {t} without android.permission.{p}")
    if not typed and not problems:
        return ("PASS", "no foreground services declared", "verified-directly")
    if problems:
        return ("FAIL" if target >= 34 else "RISK", "; ".join(problems) + ("" if target >= 34 else " (binding from Android 14; this build targets lower)"), "verified-directly")
    if m := f.missing("console.google.declarations"):
        return ("UNKNOWN", f"foreground service types {', '.join(sorted(types))} each have their permission; whether each is declared in Play Console with a use-case description and a video needs a console read, and whether each is user-initiated, perceptible, stoppable and undeferrable is a judgement", m[2])
    d = f.val("console.google.declarations")
    declared = d.get("foreground_service_types", {})
    missing = [t for t in sorted(types) if not (declared.get(t, {}).get("description") and declared.get(t, {}).get("video"))]
    if missing:
        return ("FAIL", "declared in the manifest but not in Play Console with description and video: " + ", ".join(missing), "verified-directly")
    return ("PASS", f"foreground service types {', '.join(sorted(types))} with permissions, each declared in the console", "verified-directly")


EMERGENCY_CLAIM = re.compile(r"\b(emergency (response|services?|help)|call(s|ing)? (911|112|999|the emergency)|send(s|ing)? help|dispatch(es|ing)?|rescue|first responders?)\b", re.I)
ATTACHED_DENIAL = re.compile(r"\b(not|no|never|isn't|is not|does not|doesn't|cannot|can't|do not|don't|nu|inte|ingen)\b[^.]{0,40}\b(emergency|911|112|999|dispatch|rescue|help)\b|\b(emergency|911|112|999)\b[^.]{0,30}\b(yourself|directly|is not|isn't)\b", re.I)
GUARANTEE_WORD = re.compile(r"\b(guarantee[sd]?|guaranteed|garant\w*)\b", re.I)


def no_unqualified_claims(f: Facts):
    """Now: an emergency-service claim without a denial attached to the claim itself, RISK per Apple's 'shouldn't'; guarantees a NOTE."""
    if m := f.missing("listing.text"):
        return m
    t = f.val("listing.text")
    texts = [(f"apple.{k}", v) for k, v in t.get("apple", {}).items()]
    info = f.val("ios.built.info") or f.val("ios.source.info") or {}
    texts += [(k, v) for k, v in info.get("purpose_strings", {}).items()]
    app_texts = f.val("app.texts") or {}
    for g, body in (app_texts.get("in_app") or {}).items():
        texts.append((f"in_app.{g}", body))
    claims, guarantees = [], []
    for label, text in texts:
        for sentence in re.split(r"(?<=[.!?])\s+|\n", str(text)):
            if EMERGENCY_CLAIM.search(sentence) and not ATTACHED_DENIAL.search(sentence) and not INSTRUCTION.search(sentence):
                claims.append(f"{label}: {sentence.strip()[:100]!r}")
            elif GUARANTEE_WORD.search(sentence) and not NEGATION.search(sentence):
                guarantees.append(f"{label}: {sentence.strip()[:80]!r}")
    if claims:
        return ("RISK", "sentences that read as providing emergency help, which Apple says location APIs shouldn't be used for: " + " | ".join(claims[:6]), "verified-directly")
    note = ("; guarantees (no page forbids them; noted): " + " | ".join(guarantees[:4])) if guarantees else ""
    return ("PASS", f"{len(texts)} texts read; no sentence presents the app as providing emergency help" + note, "verified-directly")


def listing_lengths(f: Facts):
    """Now: only the 30-character name limit is Apple's rule; the console field limits are noted, not judged."""
    if m := f.missing("listing.text"):
        return m
    t = f.val("listing.text")
    name = t.get("name", "")
    if len(name) > 30:
        return ("FAIL", f"the app name is {len(name)} characters; Apple limits names to 30", "verified-directly")
    fields = [("apple.subtitle", 30), ("apple.description", 4000), ("apple.keywords", 100), ("google.short_description", 80), ("google.full_description", 4000)]
    over = []
    for k, n in fields:
        store, key = k.split(".")
        v = t.get(store, {}).get(key, "")
        if len(v) > n:
            over.append(f"{k} is {len(v)}/{n}")
    if over:
        return ("NOTE", f"name is {len(name)}/30; console field limits exceeded (a console constraint, not a policy): " + "; ".join(over), "verified-directly")
    return ("PASS", f"name is {len(name)}/30 characters; console field limits also met", "verified-directly")


TRADEMARK_HINT = re.compile(r"\b(whatsapp|facebook|instagram|tiktok|snapchat|youtube|google|apple|iphone|android|netflix|spotify|uber|amazon|microsoft)\b", re.I)
PRICE_CLAIM = re.compile(r"(#\s?1\b|\bno\.? ?1\b|\bbest of\b|\btop rated\b|\bapp of the year\b|\beditor'?s choice\b|\baward\b|\d+ ?% off|\bcash back\b|\bfree for\b|\blimited time\b|\bpopular\b|[$€£]\s?\d)", re.I)


def listing_name(f: Facts):
    if m := f.missing("listing.text"):
        return m
    t = f.val("listing.text")
    fails, risks, notes = [], [], []
    for label, s in (("name", t.get("name", "")), ("apple.subtitle", t.get("apple", {}).get("subtitle", "")), ("developer name", t.get("developer_name", ""))):
        if not s:
            continue
        if label == "name" and len(s) > 30:
            fails.append(f"{label} is {len(s)} characters, limit 30")
        if EMOJI.search(s):
            fails.append(f"{label} contains an emoji")
        if re.search(r"([^\w\s])\1+", s):
            fails.append(f"{label} repeats special characters")
        elif re.sub(r"[\w\s'&-]", "", s, flags=re.UNICODE):
            notes.append(f"{label} contains a special character")
        shout = [w for w in re.findall(r"\b[A-Z]{3,}\b", s) if w not in ("SOS", "GPS", "AI", "VPN", "PDF", "USA", "UK")]
        if shout:
            risks.append(f"{label} is in capitals ({', '.join(shout)}); allowed only as part of a brand name")
        if PRICE_CLAIM.search(s):
            fails.append(f"{label} carries a price, ranking or programme claim")
        if TRADEMARK_HINT.search(s):
            risks.append(f"{label} names another product or platform")
    if fails:
        return ("FAIL", "; ".join(fails + risks + notes), "verified-directly")
    if risks:
        return ("RISK", "; ".join(risks + notes), "verified-directly")
    return ("PASS", f"name {t.get('name')!r} ({len(t.get('name', ''))}/30) and subtitle pass the metadata rules" + ("; " + "; ".join(notes) if notes else ""), "verified-directly")


FIRST_PERSON_PRAISE = re.compile(r"\b(i|we|my|our|love|loved|amazing|great|best|awesome|recommend)\b", re.I)


def google_metadata_rules(f: Facts):
    if m := f.missing("listing.text"):
        return m
    t = f.val("listing.text")
    name, dev = t.get("name", ""), t.get("developer_name", "")
    fails, risks, notes = [], [], []
    for label, s in (("title", name), ("developer name", dev)):
        if not s:
            continue
        if EMOJI.search(s):
            fails.append(f"{label} carries an emoji")
        if re.search(r"([^\w\s])\1+", s):
            fails.append(f"{label} repeats special characters")
        shout = [w for w in re.findall(r"\b[A-Z]{3,}\b", s) if w not in ("SOS", "GPS", "AI", "VPN", "PDF")]
        if shout:
            risks.append(f"{label} is in capitals ({', '.join(shout)}); allowed only as part of a brand name")
        if PRICE_CLAIM.search(s):
            fails.append(f"{label} claims ranking, price or a Play programme")
        if re.search(r"\b(new|free)\b", s, re.I):
            notes.append(f"{label} contains 'new' or 'free', which Google treats as a programme or price claim when used that way")
    if len(name) > 30:
        fails.append(f"title is {len(name)} characters, limit 30")
    for k, v in t.get("google", {}).items():
        text = str(v)
        for q in re.findall(r"[\"“]([^\"”]{15,})[\"”]", text):
            if FIRST_PERSON_PRAISE.search(q):
                i = text.find(q)
                window = text[max(0, i - 160): i + len(q) + 160]
                attributed = re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b|\b(user|customer|reviewer|parent|nurse|doctor|teacher)\b", window.replace(q, ""))
                (notes if attributed else risks).append(f"{k}: testimonial {q[:50]!r}" + ("" if attributed else " with no named source"))
        if re.search(r"^(?:[\w-]+,\s*){6,}[\w-]+$", text.strip(), re.M):
            notes.append(f"{k}: a line of comma-separated keywords")
    if fails:
        return ("FAIL", "; ".join(fails + risks + notes), "verified-directly")
    if risks:
        return ("RISK", "; ".join(risks + notes), "verified-directly")
    return ("PASS", f"title {name!r} and developer name pass the metadata rules; no anonymous testimonials" + ("; " + "; ".join(notes) if notes else ""), "verified-directly")


def target_api(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    v = f.val("android.built.manifest")
    t = v["targetSdk"]
    feats = {x.get("name") for x in v.get("features", [])}
    if "android.hardware.type.watch" in feats or "android.hardware.type.automotive" in feats:
        need, form = 35, "Wear OS or Automotive"
    elif "android.software.leanback" in feats or "android.hardware.type.television" in feats:
        need, form = 34, "Android TV"
    else:
        need, form = (36 if f.as_of >= "2026-08-31" else 35), "phone and tablet"
    if t is None:
        return ("UNKNOWN", "the built manifest carries no targetSdkVersion", "verified-directly")
    if t < need:
        return ("FAIL", f"targetSdk {t}; Google Play requires {need} or higher for new apps and updates ({form}) from the date quoted in the corpus. An extension to 2026-11-01 can be requested in Play Console. Permanently private internal apps are exempt", "verified-directly")
    return ("PASS", f"targetSdk {t} meets the {form} requirement of {need} or higher", "verified-directly")


def cleartext_traffic(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    v = f.val("android.built.manifest")
    app = v.get("application", {})
    target = v.get("targetSdk") or 0
    flag = app.get("usesCleartextTraffic")
    if flag is True:
        return ("RISK", "usesCleartextTraffic is true: personal data may travel over plain HTTP; Google requires modern encryption such as HTTPS for personal and sensitive data", "verified-directly")
    if flag is None and target < 28:
        return ("RISK", f"usesCleartextTraffic is unset and the build targets API {target}, where Android permits cleartext by default", "verified-directly")
    if app.get("networkSecurityConfig"):
        return ("NOTE", "cleartext is off by the manifest, and a network security config is set; that config can re-enable cleartext for named domains and was not parsed", "verified-directly")
    return ("PASS", "cleartext traffic is blocked by the platform default for this target and not re-enabled in the manifest", "verified-directly")


def ats_not_disabled(f: Facts):
    info = f.val("ios.built.info") or f.val("ios.source.info")
    if info is None:
        return ("UNKNOWN", "no Info.plist read", "verified-directly")
    ats = info.get("app_transport_security") or {}
    problems = []
    if ats.get("NSAllowsArbitraryLoads"):
        problems.append("NSAllowsArbitraryLoads is true, so every connection may be plain HTTP")
    for dom, cfg in (ats.get("NSExceptionDomains") or {}).items():
        if isinstance(cfg, dict) and (cfg.get("NSExceptionAllowsInsecureHTTPLoads") or cfg.get("NSTemporaryExceptionAllowsInsecureHTTPLoads")):
            problems.append(f"insecure HTTP is allowed for {dom}")
    if problems:
        return ("RISK", "; ".join(problems) + ". This is one indicator; Apple's 1.6 covers storage and backend access too, which need a judgement", "verified-directly")
    return ("PASS", "transport only: App Transport Security is on with no insecure exceptions. Storage and backend protection are outside this check", "verified-directly")


def privacy_policy_reachable(f: Facts):
    if m := f.missing("listing.text", "listing.privacy_policy_page"):
        return m
    p = f.val("listing.privacy_policy_page")
    t = f.val("listing.text")
    url = t.get("privacy_policy_url")
    problems, notes = [], []
    if p["http"] != 200:
        problems.append(f"HTTP {p['http']}")
    if p.get("is_pdf"):
        problems.append("it is a PDF, which Google does not accept")
    head = (p.get("heading") or "").lower()
    if "privacy" not in head:
        problems.append(f"the page heading is {p.get('heading')!r}, not labelled as a privacy policy")
    body = (p.get("text") or "").lower()
    names = [x for x in (t.get("name"), t.get("developer_name")) if x]
    if names and not any(n.lower() in body for n in names):
        problems.append("neither the app name nor the developer name appears in the policy text")
    if p["characters"] < 400:
        notes.append(f"only {p['characters']} characters of text (a heuristic, not a rule)")
    if problems:
        return ("FAIL", f"{url}: " + "; ".join(problems + notes), "verified-directly")
    return ("PASS", f"{p['final_url']} answers 200, is labelled {p.get('heading')!r}, names the app or developer, and is not a PDF. Whether it is reachable from every region and linked inside the app was not tested" + ("; " + "; ".join(notes) if notes else ""), "verified-directly")


BACKGROUND_PHRASES = re.compile(r"\b(in the background|when the app is closed|always in use|when the app is not in use|even when the app is closed|not in use)\b", re.I)


def background_location(f: Facts):
    """Now element by element: reference in code, disclosure text, listing, policy page, console."""
    if m := f.missing("android.built.manifest"):
        return m
    v = f.val("android.built.manifest")
    perms = set(v["permissions"])
    fgs_loc = any("location" in _fgs_names(s.get("foregroundServiceType")) for s in v.get("services", []))
    if "android.permission.ACCESS_BACKGROUND_LOCATION" not in perms and not fgs_loc:
        return ("PASS", "background location is not requested and no location foreground service is declared", "verified-directly")
    elements = []
    r = (f.val("android.built.references") or {}).get("by_capability", {}).get("background-location", {})
    if not (r.get("classes") or r.get("strings")):
        elements.append("no geofencing or background-update code found (a shrinker can hide it)")
    texts = f.val("app.texts") or {}
    in_app = " ".join((texts.get("in_app") or {}).values())
    disclosure = [s for s in re.split(r"\n", in_app) if re.search(r"\blocation\b", s, re.I) and BACKGROUND_PHRASES.search(s)]
    if not in_app:
        elements.append("no in-app copy provided under storecheck/texts/, so the disclosure dialog cannot be checked")
    elif not disclosure:
        elements.append("no in-app string uses the word 'location' together with a background phrase, which the disclosure must")
    listing = f.val("listing.text") or {}
    desc = " ".join(str(x) for x in listing.get("google", {}).values())
    if desc and not (re.search(r"\blocation\b", desc, re.I) and BACKGROUND_PHRASES.search(desc)):
        elements.append("the Play description does not say location is used in the background or when the app is closed")
    pol = f.val("listing.privacy_policy_page")
    if pol and "location" not in (pol.get("text") or "").lower():
        elements.append("the privacy policy page does not mention location")
    console = f.val("console.google.declarations")
    if console is None:
        elements.append("the Play declaration form and video need a console read")
    elif not console.get("background_location_declared"):
        elements.append("the Play declaration form is not filed")
    if not elements:
        return ("PASS", "background location is used; disclosure text, listing, policy and console declaration all present", "verified-directly")
    hard = [e for e in elements if "console" not in e and "cannot be checked" not in e]
    if hard:
        return ("FAIL", "background location is requested; missing: " + "; ".join(elements), "verified-directly")
    return ("UNKNOWN", "background location is requested and disclosed in the app; still open: " + "; ".join(elements), "needs-console-read")


def battery_bypass(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    perms = f.val("android.built.manifest")["permissions"]
    if "android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS" not in perms:
        return ("PASS", "the app does not ask to be exempted from battery optimisation", "verified-directly")
    return ("RISK", "REQUEST_IGNORE_BATTERY_OPTIMIZATIONS is declared. Google's policy: apps that are not eligible for allowlisting and attempt to bypass system power management violate it; check the app against the allowlisting use cases, and the Core App Quality optimisation rules apply regardless", "verified-directly")


def monitoring_flag(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    v = f.val("android.built.manifest")
    flagged = [k for k in v.get("meta_data", {}) if "ismonitoringtool" in k.lower()]
    shares = "android.permission.ACCESS_BACKGROUND_LOCATION" in v["permissions"] and "push" in ((f.val("android.built.references") or {}).get("signals", []))
    if flagged:
        return ("RISK", "the manifest declares itself a monitoring tool (" + ", ".join(flagged) + "): allowed only for parents over children or employers over employees, marketed exclusively as such, with a persistent notification, a unique icon and the monitoring disclosed in the description; any other target fails even with consent", "verified-directly")
    if shares:
        return ("NOTE", "no IsMonitoringTool flag, and the app sends background location to another party. Whether that is consensual sharing controlled by the person or monitoring of another individual is the judgement rule's question; if it is monitoring, the missing flag is a violation", "verified-directly")
    return ("PASS", "no IsMonitoringTool flag and no sign of one person's location being sent to another", "verified-directly")


def deletion_link(f: Facts):
    if m := f.missing("listing.text"):
        return m
    url = f.val("listing.text").get("deletion_url")
    texts = f.val("app.texts") or {}
    in_app = " ".join((texts.get("in_app") or {}).values()).lower()
    page = (texts.get("pages") or {}).get("deletion_page") or {}
    problems = []
    if not url:
        problems.append("no deletion_url in listing.toml")
    else:
        if page.get("error"):
            problems.append(f"{url} could not be fetched: {page['error']}")
        else:
            body = (page.get("text") or "").lower()
            names = [x for x in (f.val("listing.text").get("name"), f.val("listing.text").get("developer_name")) if x]
            if names and not any(n.lower() in body for n in names):
                problems.append("the deletion page names neither the app nor the developer")
            if not re.search(r"\bdelet", body):
                problems.append("the deletion page does not mention deleting")
    if in_app and not re.search(r"delete (your |the |this )?account|delete account", in_app):
        problems.append("no in-app string offers account deletion (from the copy under storecheck/texts/)")
    if problems:
        return ("FAIL", "; ".join(problems), "verified-directly")
    if m := f.missing("console.google.data-safety"):
        return ("UNKNOWN", f"deletion page {url} loads, names the app and describes deletion, and the app's copy offers account deletion; whether the link is entered in Data safety needs a console read", m[2])
    ds = f.val("console.google.data-safety")
    if not ds.get("deletion_url"):
        return ("FAIL", "Data safety names no web page for deleting the account", "verified-directly")
    return ("PASS", f"Data safety names {ds['deletion_url']}, the page loads and the app offers deletion", "verified-directly")


def sign_in_with_apple_offered(f: Facts):
    if m := f.missing("ios.built.references"):
        return m
    sig = f.val("ios.built.references").get("signals", [])
    if "social-login" not in sig:
        return ("PASS", "no third-party social login in the executable, so no equivalent option is required", "verified-directly")
    if "sign-in-with-apple" in sig:
        return ("PASS", "a social login is present and Sign in with Apple is present alongside it; confirm on the sign-in screen that it is offered for the primary account, not merely linked", "verified-directly")
    return ("RISK", "a third-party social login is in the executable and no Sign in with Apple. Apple requires an equivalent private option (name and email only, hide-my-email, no ad tracking) when the social login sets up the primary account; the developer's own email or passkey account offered alongside can satisfy it, and clients of one third-party service, enterprise or education logins, citizen eIDs and marketplace logins are exempt. A judgement over the sign-in screen decides", "verified-directly")


def ipad_claim(f: Facts):
    if m := f.missing("ios.built.info"):
        return m
    fam = f.val("ios.built.info")["device_family"]
    if 2 in fam:
        return ("NOTE", "UIDeviceFamily claims iPad. Under 2.3 the metadata must reflect the experience on every device family the build claims, so the listing needs the iPad experience to be real and shown. If the app is iPhone-only, remove iPad from the target", "verified-directly")
    return ("PASS", "iPhone only", "verified-directly")


def ios_built_matches_source(f: Facts):
    """Now a precondition, not a policy finding: the artefact on disk differs from the source."""
    if m := f.missing("ios.source.info", "ios.built.info"):
        return m
    s, b = f.val("ios.source.info"), f.val("ios.built.info")
    diffs = []
    if set(s["background_modes"]) != set(b["background_modes"]):
        diffs.append(f"background modes {s['background_modes']} in source, {b['background_modes']} in the build")
    for k in sorted(set(s["purpose_strings"]) | set(b["purpose_strings"])):
        if s["purpose_strings"].get(k) != b["purpose_strings"].get(k):
            diffs.append(f"purpose string {k} differs")
    ps, pb = f.val("ios.source.privacy_manifest"), (f.val("ios.built.privacy_manifests") or {}).get("app")
    if ps and pb:
        a = {t["type"] for t in ps["collected_data_types"]}; c = {t["type"] for t in pb["collected_data_types"]}
        if a != c:
            diffs.append("privacy manifest data types differ: only in source " + str(sorted(x.replace("NSPrivacyCollectedDataType", "") for x in a - c)) + ", only in build " + str(sorted(x.replace("NSPrivacyCollectedDataType", "") for x in c - a)))
    if diffs:
        return ("NOTE", f"precondition, not a policy finding: {b.get('artefact')} (built {b.get('artefact_modified')}) is not the app the source describes: " + "; ".join(diffs) + ". Every iOS verdict here is about the build on disk", "verified-directly")
    return ("PASS", f"{b.get('artefact')} matches the source on background modes, purpose strings and privacy manifest types", "verified-directly")


def listed_sdk_manifests(f: Facts):
    if m := f.missing("ios.built.info", "ios.built.privacy_manifests"):
        return m
    from .corpus import CACHE_DIR
    from pathlib import Path
    cache = CACHE_DIR / "apple.third-party-sdk.txt"
    if not cache.exists():
        return ("UNKNOWN", "Apple's SDK list is not in the corpus cache; run corpus fetch", "verified-directly")
    text = cache.read_text(encoding="utf-8")
    names = [l.strip() for l in (Path(__file__).parent / "data" / "apple-listed-sdks.txt").read_text().splitlines() if l.strip() and not l.startswith("#")]
    gone = [n for n in names if n not in text]
    if gone:
        return ("UNKNOWN", "the recorded SDK list no longer matches Apple's page (missing: " + ", ".join(gone[:5]) + "); update data/apple-listed-sdks.txt", "verified-directly")
    present = set(x.removesuffix(".framework") for x in f.val("ios.built.info")["frameworks"] if x.endswith(".framework"))
    lock = f.val("ios.pods.lock")
    if lock:
        present |= set(lock)
    have = set(f.val("ios.built.privacy_manifests")["third_party"])
    listed = sorted(p for p in present if p in names)
    missing = [p for p in listed if p not in have and not any(p.lower() in h.lower() for h in have)]
    if missing:
        return ("FAIL", "SDKs on Apple's list present in this app without a bundled privacy manifest: " + ", ".join(missing), "verified-directly")
    src = "the Podfile.lock" if lock else "the dynamic frameworks only (no Podfile.lock read, so statically linked SDKs are not enumerated)"
    return ("PASS", f"{len(listed)} listed SDKs present, from {src}, each with a manifest; {len(have)} third-party manifests bundled. Signatures on binary SDKs were not checked. The obligation binds new apps and updates that add a listed SDK", "verified-directly")


def restricted_permissions(f: Facts):
    if m := f.missing("android.built.manifest"):
        return m
    v = f.val("android.built.manifest")
    perms = set(v["permissions"])
    target = v.get("targetSdk") or 0
    actions = set(v.get("intent_actions", []))
    listing = f.val("listing.text")
    listing_text = (" ".join(str(x) for s in ("apple", "google") for x in (listing or {}).get(s, {}).values())).lower()
    order = {"PASS": 0, "NOTE": 1, "UNKNOWN": 2, "RISK": 3, "FAIL": 4}
    worst, notes = "PASS", []

    def bump(level, note):
        nonlocal worst
        notes.append(note)
        if order[level] > order[worst]:
            worst = level
    sms = {"android.permission.READ_SMS", "android.permission.SEND_SMS", "android.permission.RECEIVE_SMS", "android.permission.RECEIVE_MMS", "android.permission.RECEIVE_WAP_PUSH"}
    calls = {"android.permission.READ_CALL_LOG", "android.permission.WRITE_CALL_LOG", "android.permission.PROCESS_OUTGOING_CALLS"}
    if perms & sms:
        handler = {"android.provider.Telephony.SMS_DELIVER", "android.provider.Telephony.WAP_PUSH_DELIVER"} & actions
        bump("PASS" if handler else "FAIL", "SMS permissions declared" + (" with a default-SMS-handler intent filter" if handler else " without a default SMS or Assistant handler intent filter, which the policy forbids"))
    if perms & calls:
        handler = {"android.intent.action.DIAL", "android.telecom.InCallService"} & actions
        bump("PASS" if handler else "FAIL", "call-log permissions declared" + (" with a dialer intent filter" if handler else " without a default Phone or Assistant handler, which the policy forbids"))
    if "android.permission.MANAGE_EXTERNAL_STORAGE" in perms:
        bump("RISK", "all-files access needs Google's access review and a clear prompt to enable it")
    if "android.permission.QUERY_ALL_PACKAGES" in perms:
        bump("RISK", "broad package visibility is allowed only for named interoperability use cases; a declaration is needed")
    if "android.permission.REQUEST_INSTALL_PACKAGES" in perms:
        ok = listing is not None and re.search(r"\b(install|apk|file (sharing|transfer|manager)|browser|backup|migration|companion)\b", listing_text)
        bump("PASS" if ok else ("UNKNOWN" if listing is None else "FAIL"), "REQUEST_INSTALL_PACKAGES: " + ("the description promotes a package or file function" if ok else ("listing not read" if listing is None else "the description promotes no sending, receiving or installing of packages, which the policy requires")))
    if "android.permission.BIND_VPN_SERVICE" in perms:
        ok = listing is not None and "vpn" in listing_text
        bump("PASS" if ok else ("UNKNOWN" if listing is None else "FAIL"), "VpnService: " + ("documented in the listing" if ok else ("listing not read" if listing is None else "not documented in the listing, which the policy requires")))
    if "android.permission.BIND_ACCESSIBILITY_SERVICE" in perms:
        if listing is None:
            bump("UNKNOWN", "an accessibility service is declared; the listing was not read")
        elif "accessibility" not in listing_text:
            bump("FAIL", "an accessibility service is declared and the listing does not document it")
        else:
            bump("RISK", "an accessibility service is declared and documented; unless the app is a genuine accessibility tool, a console declaration, in-app disclosure and consent are required")
    if perms & {"android.permission.BODY_SENSORS", "android.permission.BODY_SENSORS_BACKGROUND"} or any(p.startswith("android.permission.health.") for p in perms):
        bump("RISK", "body-sensor or Health Connect permissions: approved uses only, under the User Data and Health apps policies")
    if "android.permission.USE_EXACT_ALARM" in perms:
        bump("RISK", "USE_EXACT_ALARM is for alarm, timer and calendar apps; others should evaluate SCHEDULE_EXACT_ALARM")
    if "android.permission.USE_FULL_SCREEN_INTENT" in perms:
        bump("RISK", "USE_FULL_SCREEN_INTENT is granted automatically only to alarm and call apps on Android 14+; others must ask the user")
    if target >= 33 and perms & {"android.permission.READ_MEDIA_IMAGES", "android.permission.READ_MEDIA_VIDEO"}:
        bump("RISK", "READ_MEDIA_IMAGES/VIDEO on Android 13+: allowed only where the photo picker is not enough, with a Play Console declaration")
    if "android.permission.ACCESS_BACKGROUND_LOCATION" in perms:
        bump("NOTE", "background location declared; its own rule checks the disclosure and console declaration")
    if not notes:
        return ("PASS", "no restricted permission with a special condition is declared; the general conditions (in-context request, honour refusal, no sale) apply to the location, camera and notification permissions and are judged elsewhere", "verified-directly")
    return (worst, "; ".join(notes), "verified-directly")


def permissions_used(f: Facts):
    if m := f.missing("android.built.manifest", "android.built.references"):
        return m
    declared = f.val("android.built.manifest")["permissions"]
    refs = f.val("android.built.references")["by_capability"]
    unref = []
    for perm, cap in DANGEROUS_ANDROID.items():
        if perm in declared:
            r = refs.get(cap, {})
            if not (r.get("classes") or r.get("strings")):
                unref.append(perm.split(".")[-1])
    if unref:
        return ("RISK", "declared with no reference found in the compiled code: " + ", ".join(unref) + ". Google requires permissions only for current features promoted in the listing and says unused permissions must be removed; a shrinker can hide a library's reference, so confirm before removing", "verified-directly")
    n = sum(1 for p in DANGEROUS_ANDROID if p in declared)
    return ("PASS", f"all {n} sensitive permissions declared are referenced by the compiled code; whether each is necessary for a promoted feature is a judgement", "verified-directly")
