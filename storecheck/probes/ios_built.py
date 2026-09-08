# Copyright (C) 2026 Editerra AB. Okkok is a trademark of Editerra AB.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Built iOS facts: what Apple reads out of the .ipa or the .app bundle.

Three things: the bundle's Info.plist (binary), the entitlements actually
signed in (from the embedded provisioning profile), and every privacy
manifest bundled, the app's own and the third-party ones.
"""

from __future__ import annotations

import plistlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ..schema import file_probe, make_probe
from .ios_plist import info_facts, privacy_facts


class Bundle:
    """Uniform reads over an .ipa (zip) or an .app (directory)."""

    def __init__(self, path: Path):
        self.path = path
        self.zip = zipfile.ZipFile(path) if path.is_file() else None
        if self.zip:
            apps = [n for n in self.zip.namelist() if n.startswith("Payload/") and n.count("/") == 2 and n.endswith(".app/")]
            if not apps:
                apps = sorted({n.split("/")[1] + "/" for n in self.zip.namelist() if n.startswith("Payload/") and ".app/" in n})
                apps = ["Payload/" + a for a in apps]
            self.root = apps[0]
            self.names = [n for n in self.zip.namelist() if n.startswith(self.root)]
        else:
            self.root = ""
            self.names = [str(p.relative_to(path)) for p in path.rglob("*") if p.is_file()]

    def read(self, rel: str) -> bytes:
        if self.zip:
            return self.zip.read(self.root + rel)
        return (self.path / rel).read_bytes()

    def exists(self, rel: str) -> bool:
        return (self.root + rel) in self.names if self.zip else (self.path / rel).is_file()

    def find(self, suffix: str) -> list[str]:
        if self.zip:
            return sorted(n[len(self.root):] for n in self.names if n.endswith(suffix))
        return sorted(n for n in self.names if n.endswith(suffix))


def find_bundle(app_dir: Path) -> Path | None:
    ipas = [p for p in app_dir.rglob("*.ipa") if p.is_file()]
    if ipas:
        return max(ipas, key=lambda p: p.stat().st_mtime)
    apps = [p for p in app_dir.rglob("*.app") if p.is_dir() and (p / "Info.plist").is_file() and "simulator" not in str(p).lower()]
    return max(apps, key=lambda p: p.stat().st_mtime) if apps else None


def profile_facts(raw: bytes) -> dict:
    """The provisioning profile is a signed blob with a plain plist inside it."""
    start = raw.find(b"<?xml")
    end = raw.find(b"</plist>")
    if start < 0 or end < 0:
        return {"error": "no plist found inside the provisioning profile"}
    p = plistlib.loads(raw[start:end + len(b"</plist>")])
    if p.get("ProvisionsAllDevices"):
        kind = "enterprise"
    elif p.get("ProvisionedDevices"):
        kind = "development-or-adhoc"
    else:
        kind = "app-store"
    return {
        "kind": kind,
        "team": p.get("TeamName"),
        "expires": p.get("ExpirationDate").isoformat() if p.get("ExpirationDate") else None,
        "entitlements": p.get("Entitlements", {}),
    }


def probe(app_dir: Path) -> list[dict]:
    out = []
    path = find_bundle(app_dir)
    if path is None:
        out.append(make_probe("ios.built.info", None, source_kind="file",
                         source_ref="an .ipa or a device .app anywhere under the app directory",
                         error="not found: looked for an .ipa or a device .app anywhere under the app directory"))
        return out
    b = Bundle(path)

    info = plistlib.loads(b.read("Info.plist"))
    facts = info_facts(info)
    facts["bundle_id"] = info.get("CFBundleIdentifier")
    facts["bundle_id_from"] = "built Info.plist"
    facts["artefact"] = path.name
    facts["artefact_modified"] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()
    facts["frameworks"] = sorted({n.split("/")[1] for n in b.find("") if n.startswith("Frameworks/") and "/" in n[len("Frameworks/"):]})
    facts["extensions"] = sorted({n.split("/")[1] for n in b.find("") if n.startswith("PlugIns/") and n.split("/")[1].endswith(".appex")})
    out.append(file_probe("ios.built.info", facts, path))

    if b.exists("embedded.mobileprovision"):
        out.append(file_probe("ios.built.profile", profile_facts(b.read("embedded.mobileprovision")), path))
    else:
        out.append(make_probe("ios.built.profile", None, source_kind="file", source_ref=str(path),
                         error="no embedded.mobileprovision in the bundle: it is unsigned, or a simulator build"))

    manifests = b.find("PrivacyInfo.xcprivacy")
    own = [m for m in manifests if m == "PrivacyInfo.xcprivacy"]
    third = {}
    for m in manifests:
        if m == "PrivacyInfo.xcprivacy":
            continue
        parts = m.split("/")
        owner = parts[-2] if len(parts) > 1 else parts[0]
        owner = owner.removesuffix(".bundle").removesuffix(".framework").removesuffix("_Privacy").removesuffix("_privacy")
        third[owner] = privacy_facts(plistlib.loads(b.read(m)))
    out.append(file_probe(
        "ios.built.privacy_manifests",
        {"app": privacy_facts(plistlib.loads(b.read(own[0]))) if own else None, "third_party": third},
        path,
    ))
    return out


def self_test() -> None:
    xml = (b"<?xml version=\"1.0\"?><!DOCTYPE plist><plist version=\"1.0\"><dict>"
           b"<key>TeamName</key><string>T</string>"
           b"<key>Entitlements</key><dict><key>aps-environment</key><string>production</string></dict>"
           b"</dict></plist>")
    f = profile_facts(b"\x30\x82junk" + xml + b"\x00signature")
    assert f["kind"] == "app-store" and f["entitlements"]["aps-environment"] == "production", f
    f2 = profile_facts(b"\x30\x82junk" + xml.replace(b"<key>TeamName", b"<key>ProvisionedDevices</key><array><string>x</string></array><key>TeamName"))
    assert f2["kind"] == "development-or-adhoc", f2
    # Negative: a blob with no plist is reported, not guessed.
    assert "error" in profile_facts(b"nothing here")
