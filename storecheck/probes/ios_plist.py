"""Source-level iOS facts: Info.plist, the entitlements file and the privacy manifest.

Apple reads exactly these three files out of the built bundle. Reading the
source copies lets the built copies (ios_built) be compared against them.
"""

from __future__ import annotations

import plistlib
import re
from pathlib import Path

from ..schema import file_probe, missing_probe

PLIST_CANDIDATES = ("ios/Runner/Info.plist", "Info.plist")
PRIVACY_CANDIDATES = ("ios/Runner/PrivacyInfo.xcprivacy", "PrivacyInfo.xcprivacy")
PBXPROJ_GLOB = "ios/*.xcodeproj/project.pbxproj"


def find_first(app_dir: Path, candidates) -> Path | None:
    for rel in candidates:
        p = app_dir / rel
        if p.is_file():
            return p
    return None


def resolve_bundle_id(plist: dict, app_dir: Path) -> tuple[str | None, str | None]:
    """Info.plist usually says $(PRODUCT_BUNDLE_IDENTIFIER); the real value is in the Xcode project.

    Returns (bundle_id, where_it_came_from). Several build configurations may
    each set it; if they disagree the value is None and the note says so.
    """
    raw = plist.get("CFBundleIdentifier")
    if raw and "$(" not in raw:
        return raw, "Info.plist"
    for pbx in sorted(app_dir.glob(PBXPROJ_GLOB)):
        ids = set(re.findall(r"PRODUCT_BUNDLE_IDENTIFIER = ([^;\s]+);", pbx.read_text(encoding="utf-8", errors="replace")))
        ids = {i for i in ids if not i.endswith("RunnerTests")}
        if len(ids) == 1:
            return ids.pop(), str(pbx)
        if len(ids) > 1:
            return None, f"{pbx}: build configurations disagree: {sorted(ids)}"
    return None, "no Xcode project found to resolve $(PRODUCT_BUNDLE_IDENTIFIER)"


def info_facts(plist: dict) -> dict:
    return {
        "purpose_strings": {k: v for k, v in plist.items() if k.startswith("NS") and k.endswith("UsageDescription")},
        "background_modes": list(plist.get("UIBackgroundModes", [])),
        "device_family": list(plist.get("UIDeviceFamily", [])),
        "minimum_os": plist.get("MinimumOSVersion") or plist.get("LSMinimumSystemVersion"),
        "supports_ipad_multitasking": bool(plist.get("UIRequiresFullScreen") is False),
        "app_transport_security": plist.get("NSAppTransportSecurity"),
        "display_name": plist.get("CFBundleDisplayName") or plist.get("CFBundleName"),
        "version": plist.get("CFBundleShortVersionString"),
        "build": plist.get("CFBundleVersion"),
    }


def privacy_facts(plist: dict) -> dict:
    return {
        "tracking": bool(plist.get("NSPrivacyTracking", False)),
        "tracking_domains": list(plist.get("NSPrivacyTrackingDomains", [])),
        "collected_data_types": [
            {
                "type": d.get("NSPrivacyCollectedDataType"),
                "linked": bool(d.get("NSPrivacyCollectedDataTypeLinked")),
                "tracking": bool(d.get("NSPrivacyCollectedDataTypeTracking")),
                "purposes": list(d.get("NSPrivacyCollectedDataTypePurposes", [])),
            }
            for d in plist.get("NSPrivacyCollectedDataTypes", [])
        ],
        "accessed_api_types": [
            {"type": a.get("NSPrivacyAccessedAPIType"), "reasons": list(a.get("NSPrivacyAccessedAPITypeReasons", []))}
            for a in plist.get("NSPrivacyAccessedAPITypes", [])
        ],
    }


def probe(app_dir: Path) -> list[dict]:
    out = []
    info = find_first(app_dir, PLIST_CANDIDATES)
    if info is None:
        out.append(missing_probe("ios.source.info", " or ".join(PLIST_CANDIDATES)))
    else:
        with open(info, "rb") as f:
            plist = plistlib.load(f)
        facts = info_facts(plist)
        bundle_id, origin = resolve_bundle_id(plist, app_dir)
        facts["bundle_id"] = bundle_id
        facts["bundle_id_from"] = origin
        out.append(file_probe("ios.source.info", facts, info))

    ent = sorted(app_dir.glob("ios/*/*.entitlements")) or sorted(app_dir.glob("*.entitlements"))
    if not ent:
        out.append(missing_probe("ios.source.entitlements", "ios/*/*.entitlements"))
    else:
        with open(ent[0], "rb") as f:
            out.append(file_probe("ios.source.entitlements", plistlib.load(f), ent[0]))

    lock = find_first(app_dir, ("ios/Podfile.lock", "Podfile.lock"))
    if lock is not None:
        pods = sorted({m.group(1) for m in re.finditer(r"^  - ([A-Za-z0-9_\-\.]+)", lock.read_text(encoding="utf-8"), re.M)})
        out.append(file_probe("ios.pods.lock", pods, lock))
    priv = find_first(app_dir, PRIVACY_CANDIDATES)
    if priv is None:
        out.append(missing_probe("ios.source.privacy_manifest", " or ".join(PRIVACY_CANDIDATES)))
    else:
        with open(priv, "rb") as f:
            out.append(file_probe("ios.source.privacy_manifest", privacy_facts(plistlib.load(f)), priv))
    return out


def self_test() -> None:
    p = {
        "CFBundleIdentifier": "$(PRODUCT_BUNDLE_IDENTIFIER)",
        "NSCameraUsageDescription": "For QR codes.",
        "UIBackgroundModes": ["remote-notification"],
        "CFBundleShortVersionString": "1.0",
    }
    f = info_facts(p)
    assert f["purpose_strings"] == {"NSCameraUsageDescription": "For QR codes."}, f
    assert f["background_modes"] == ["remote-notification"], f
    pm = privacy_facts({
        "NSPrivacyTracking": False,
        "NSPrivacyCollectedDataTypes": [{"NSPrivacyCollectedDataType": "NSPrivacyCollectedDataTypeName",
                                          "NSPrivacyCollectedDataTypeLinked": True}],
    })
    assert pm["tracking"] is False and pm["collected_data_types"][0]["linked"] is True, pm
    # Negative: a manifest with no data types must say so as an empty list, not a missing key.
    assert privacy_facts({})["collected_data_types"] == []
    # Negative: a literal bundle id must not be sent to the project file for resolution.
    bid, origin = resolve_bundle_id({"CFBundleIdentifier": "a.b"}, Path("/nonexistent"))
    assert (bid, origin) == ("a.b", "Info.plist"), (bid, origin)
