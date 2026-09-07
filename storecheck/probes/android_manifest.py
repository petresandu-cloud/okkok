"""Source-level Android facts: the manifest and the Gradle file the developer wrote.

What the store reviews is the built package (android_apk.py). This reads the
source so the two can be compared; disagreement between them is itself a fact.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..schema import file_probe, missing_probe

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"

# Where a manifest usually lives, most specific first. The first hit wins.
MANIFEST_CANDIDATES = (
    "android/app/src/main/AndroidManifest.xml",
    "app/src/main/AndroidManifest.xml",
    "src/main/AndroidManifest.xml",
    "AndroidManifest.xml",
)
GRADLE_CANDIDATES = (
    "android/app/build.gradle", "android/app/build.gradle.kts",
    "app/build.gradle", "app/build.gradle.kts",
    "build.gradle", "build.gradle.kts",
)


def find_first(app_dir: Path, candidates) -> Path | None:
    for rel in candidates:
        p = app_dir / rel
        if p.is_file():
            return p
    return None


def parse_manifest(text: str) -> dict:
    root = ET.fromstring(text)
    perms = sorted(
        e.get(f"{ANDROID_NS}name") for e in root.iter("uses-permission") if e.get(f"{ANDROID_NS}name")
    )
    features = [
        {"name": e.get(f"{ANDROID_NS}name"), "required": e.get(f"{ANDROID_NS}required", "true") == "true"}
        for e in root.iter("uses-feature") if e.get(f"{ANDROID_NS}name")
    ]
    app = root.find("application")
    services, meta = [], {}
    app_attrs = {}
    if app is not None:
        for s in app.iter("service"):
            services.append({
                "name": s.get(f"{ANDROID_NS}name"),
                "foregroundServiceType": s.get(f"{ANDROID_NS}foregroundServiceType"),
            })
        for md in app.iter("meta-data"):
            if md.get(f"{ANDROID_NS}name"):
                meta[md.get(f"{ANDROID_NS}name")] = md.get(f"{ANDROID_NS}value") or md.get(f"{ANDROID_NS}resource")
        app_attrs = {"usesCleartextTraffic": app.get(f"{ANDROID_NS}usesCleartextTraffic"),
                     "networkSecurityConfig": app.get(f"{ANDROID_NS}networkSecurityConfig")}
    intent_actions = sorted({a.get(f"{ANDROID_NS}name") for a in root.iter("action") if a.get(f"{ANDROID_NS}name")})
    return {
        "package": root.get("package"),
        "permissions": perms,
        "features": features,
        "services": services,
        "meta_data": meta,
        "application": app_attrs,
        "intent_actions": intent_actions,
    }


def parse_gradle(text: str) -> dict:
    """Pull the four values the stores care about out of a Groovy or Kotlin Gradle file.

    A value that is an expression (flutter.targetSdkVersion, a variable) is
    reported as that expression string, not guessed at.
    """
    def grab(key):
        # applicationId "x" | applicationId = "x" | targetSdk 36 | targetSdkVersion = 36
        m = re.search(rf'^\s*{key}(?:Version)?\s*=?\s*("?)([^\s"\n]+)\1', text, re.M)
        return m.group(2) if m else None

    def as_int(v):
        return int(v) if v is not None and v.isdigit() else v

    return {
        "applicationId": grab("applicationId"),
        "namespace": grab("namespace"),
        "compileSdk": as_int(grab("compileSdk")),
        "targetSdk": as_int(grab("targetSdk")),
        "minSdk": as_int(grab("minSdk")),
    }


def probe(app_dir: Path) -> list[dict]:
    out = []
    manifest = find_first(app_dir, MANIFEST_CANDIDATES)
    if manifest is None:
        out.append(missing_probe("android.source.manifest", " or ".join(MANIFEST_CANDIDATES)))
    else:
        facts = parse_manifest(manifest.read_text(encoding="utf-8"))
        out.append(file_probe("android.source.manifest", facts, manifest))
    gradle = find_first(app_dir, GRADLE_CANDIDATES)
    if gradle is None:
        out.append(missing_probe("android.source.gradle", " or ".join(GRADLE_CANDIDATES)))
    else:
        out.append(file_probe("android.source.gradle", parse_gradle(gradle.read_text(encoding="utf-8")), gradle))
    return out


def self_test() -> None:
    m = parse_manifest(
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="a.b">'
        '<uses-permission android:name="android.permission.CAMERA"/>'
        '<uses-feature android:name="android.hardware.camera" android:required="false"/>'
        '<application><service android:name=".S" android:foregroundServiceType="location"/></application>'
        "</manifest>"
    )
    assert m["package"] == "a.b", m
    assert m["permissions"] == ["android.permission.CAMERA"], m
    assert m["features"] == [{"name": "android.hardware.camera", "required": False}], m
    assert m["services"][0]["foregroundServiceType"] == "location", m
    g = parse_gradle('android {\n  namespace "a.b"\n  defaultConfig {\n    applicationId = "a.b"\n    targetSdkVersion 36\n    minSdk = flutter.minSdkVersion\n  }\n}')
    assert g["applicationId"] == "a.b" and g["targetSdk"] == 36, g
    assert g["minSdk"] == "flutter.minSdkVersion", g  # an expression is reported, never guessed
    # Negative: a manifest with no permissions must report an empty list, not a missing key.
    assert parse_manifest('<manifest package="x"/>')["permissions"] == []
