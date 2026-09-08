"""Does a rule apply to this app at all? Decided from facts, and always said out loud.

A rule may carry `applies_when`, a list of conditions of which any one makes
it apply. When none holds the row is N/A with the conditions named, so a
wrong N/A is one glance from being caught. When the facts needed to decide
are missing (no binary yet) the answer is "cannot tell", never N/A.

    capability:<name>        the capability is declared or referenced on either platform
    permission:<android>     the Android permission is declared
    entitlement:<key>        the iOS entitlement is present in the signed build
    background_mode:<mode>   the iOS background mode is declared
    framework:<Name>         the iOS executable links the framework
    dex:<prefix>             the compiled Android code references a class starting with the prefix
    listing:<regex>          the listing text matches (case-insensitive)
    signal:<name>            the binaries show login, purchases, ads, webview, vpn, maps, push... (capabilities.SIGNALS)
    audience:children        the app declares or shows a child audience
"""

from __future__ import annotations

import re

from .capabilities import CAPABILITIES


def evaluate(conditions: list[str], facts) -> tuple[str, str]:
    """('applies' | 'na' | 'unknown', reason)."""
    if not conditions:
        return "applies", "applies to every app"
    reasons, unknown = [], []
    for cond in conditions:
        kind, _, value = cond.partition(":")
        r = _one(kind, value, facts)
        if r is True:
            return "applies", f"{cond} holds"
        if r is None:
            unknown.append(cond)
        else:
            reasons.append(cond)
    if unknown:
        return "unknown", "whether it applies depends on " + ", ".join(sorted({_needs(c) for c in unknown})) + ", which was not given"
    return "na", "none of these hold: " + ", ".join(_word(c) for c in reasons)


NEEDS = {
    "listing": "the store listing text (storecheck/listing.toml)",
    "signal": "the compiled code",
    "dex": "the compiled Android code",
    "permission": "the built Android manifest",
    "capability": "the built app",
    "entitlement": "the iOS entitlements",
    "background_mode": "the iOS Info.plist",
    "framework": "the iOS executable",
    "audience": "the listing's audience",
    "extensions": "the iOS bundle",
}


def _needs(cond: str) -> str:
    kind = cond.partition(":")[0]
    return NEEDS.get(kind, "a fact about the app")


def _word(cond: str) -> str:
    """A condition in words for the page: 'listing:<regex>' becomes 'the listing mentions <topic>'."""
    kind, _, value = cond.partition(":")
    if kind == "listing":
        topic = re.sub(r"[\\()|?+*\[\]^$.{}]", " ", value).replace("b ", " ").split()
        return "the listing mentions " + " or ".join(dict.fromkeys(topic[:4])) + (" or the like" if len(topic) > 4 else "")
    if kind == "permission":
        return "the Android permission " + value.rsplit(".", 1)[-1]
    if kind == "signal":
        return "the compiled code shows " + value
    return f"{kind} {value}"


def _one(kind: str, value: str, f):
    amf = f.val("android.built.manifest") or f.val("android.source.manifest")
    aref = f.val("android.built.references")
    info = f.val("ios.built.info") or f.val("ios.source.info")
    iref = f.val("ios.built.references")
    prof = f.val("ios.built.profile")
    listing = f.val("listing.text")

    if kind == "capability":
        spec = CAPABILITIES.get(value)
        if spec is None:
            return None
        declared = False
        if amf is not None:
            declared |= any(p in amf.get("permissions", []) for p in spec["android_permissions"])
        if info is not None:
            declared |= any(k in info.get("purpose_strings", {}) for k in spec["ios_purpose_keys"])
            declared |= spec.get("ios_background_mode") in info.get("background_modes", [])
        referenced = False
        if aref is not None:
            r = aref["by_capability"].get(value, {})
            referenced |= bool(r.get("classes") or r.get("strings"))
        if iref is not None:
            r = iref["by_capability"].get(value, {})
            referenced |= bool(r.get("selectors") or r.get("linked")) or value in (iref.get("in_bundled_frameworks") or {})
        if amf is None and info is None:
            return None
        return declared or referenced
    if kind == "permission":
        return None if amf is None else value in amf.get("permissions", [])
    if kind == "entitlement":
        return None if prof is None else value in prof.get("entitlements", {})
    if kind == "background_mode":
        return None if info is None else value in info.get("background_modes", [])
    if kind == "framework":
        return None if iref is None else (value in iref["frameworks"]["strong"] or value in iref["frameworks"]["weak"])
    if kind == "extensions":
        return None if info is None else bool(info.get("extensions"))
    if kind == "signal":
        if aref is None and iref is None:
            return None
        return value in (aref or {}).get("signals", []) or value in (iref or {}).get("signals", [])
    if kind == "dex":
        if aref is None:
            return None
        return any(c.startswith(value) for cap in aref["by_capability"].values() for c in cap.get("classes", [])) or \
            value in (f.val("android.built.references") or {}).get("extra", [])
    if kind == "listing":
        if listing is None:
            return None
        text = " ".join(str(v) for store in ("apple", "google") for v in listing.get(store, {}).values()) + " " + listing.get("name", "")
        return re.search(value, text, re.I) is not None
    if kind == "audience":
        decl = f.val("console.google.declarations")
        if decl is not None and "target_audience" in decl:
            return "child" in str(decl["target_audience"]).lower()
        if listing is None:
            return None
        text = " ".join(str(v) for store in ("apple", "google") for v in listing.get(store, {}).values())
        return re.search(r"\b(for kids|for children|ages? \d-\d|preschool|toddler)\b", text, re.I) is not None
    return None
