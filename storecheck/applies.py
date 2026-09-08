# Copyright (C) 2026 Editerra AB. Okkok is a trademark of Editerra AB.
# SPDX-License-Identifier: AGPL-3.0-or-later
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


def evaluate(conditions: list[str], facts, store: str = "both") -> tuple[str, str]:
    """('applies' | 'na' | 'unknown', reason).

    A rule for one store is decided from that store's facts only: an Apple rule
    cannot be ruled out because the Android build shows nothing.
    """
    if not conditions:
        return "applies", "applies to every app"
    reasons, unknown = [], []
    for cond in conditions:
        kind, _, value = cond.partition(":")
        r = _one(kind, value, facts, store)
        if r is True:
            return "applies", _word(cond)
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
    "audience": "the target-audience answer in Play Console (or a listing that says the app is for children)",
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
        return "the Android permission " + value.rsplit(".", 1)[-1] + " is declared"
    if kind == "signal":
        return "the compiled code shows " + value.replace("-", " ")
    if kind == "capability":
        return "the app declares or uses " + value.replace("-", " ")
    if kind == "entitlement":
        return "the iOS entitlement " + value + " is present"
    if kind == "background_mode":
        return "the iOS background mode " + value + " is declared"
    if kind == "framework":
        return "the iOS executable links " + value
    if kind == "dex":
        return "the compiled Android code references " + value
    if kind == "extensions":
        return "the iOS bundle carries app extensions"
    if kind == "audience":
        return "the app is for children"
    return f"{kind} {value}"


def _one(kind: str, value: str, f, store: str = "both"):
    amf = f.val("android.built.manifest") or f.val("android.source.manifest")
    aref = f.val("android.built.references")
    info = f.val("ios.built.info") or f.val("ios.source.info")
    iref = f.val("ios.built.references")
    prof = f.val("ios.built.profile")
    listing = f.val("listing.text")
    if store == "apple":
        amf = aref = None          # Android facts do not decide an Apple rule
    elif store == "google":
        info = iref = prof = None  # and iOS facts do not decide a Google rule

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
        built = f.val("ios.built.info") if store != "google" else None
        return None if built is None else bool(built.get("extensions"))   # only a built bundle shows its extensions
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
        text = " ".join(str(v) for st in ("apple", "google") for v in listing.get(st, {}).values())
        if re.search(r"\b(for kids|for children|ages? \d-\d|preschool|toddler|kindergarten)\b", text, re.I):
            return True
        return None  # a listing that does not say so is no proof the audience is not children; the console decides
    return None
