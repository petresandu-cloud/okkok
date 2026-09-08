"""Built Android facts: the manifest inside the APK, which is what Google Play reviews.

An app bundle (.aab) carries its manifest in a different encoding that needs
Google's bundletool and Java. When only a bundle is present and bundletool is
not, the tool says so and reports the bundle as unread. It never guesses.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
import struct
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ..schema import file_probe, make_probe, sha256_of_file
from . import arsc, axml
from .android_manifest import parse_manifest


def newest(paths: list[Path]) -> Path | None:
    # Release builds first, then the most recently written.
    release = [p for p in paths if "release" in str(p).lower()]
    pool = release or paths
    return max(pool, key=lambda p: p.stat().st_mtime) if pool else None


def find_apk(app_dir: Path) -> Path | None:
    return newest([p for p in app_dir.rglob("*.apk") if p.is_file()])


def find_aab(app_dir: Path) -> Path | None:
    return newest([p for p in app_dir.rglob("*.aab") if p.is_file()])


def read_apk_manifest(apk: Path) -> dict:
    with zipfile.ZipFile(apk) as z:
        raw = z.read("AndroidManifest.xml")
        facts = axml.manifest_facts(axml.decode(raw))
        # The label is usually a resource reference; the table gives the text a launcher shows.
        label = facts.get("application", {}).get("label")
        rid = arsc.parse_ref(label)
        if rid is not None and "resources.arsc" in z.namelist():
            try:
                text = arsc.string_for(z.read("resources.arsc"), rid)
            except (ValueError, struct.error, IndexError):
                text = None
            facts["label"] = text.replace("\u00ad", "") if text else None
        else:
            facts["label"] = label if isinstance(label, str) and not label.startswith("@") else None
    return facts


def bundletool_jar() -> Path | None:
    p = os.environ.get("STORECHECK_BUNDLETOOL")
    if p and Path(p).is_file():
        return Path(p)
    for cand in (Path.home() / ".cache/storecheck/bundletool.jar", Path(".cache/bundletool.jar")):
        if cand.is_file():
            return cand
    return None


def read_aab_manifest(aab: Path) -> dict | None:
    """Only with Java and bundletool; otherwise None and the caller records why."""
    jar = bundletool_jar()
    if jar is None or shutil.which("java") is None:
        return None
    xml = subprocess.run(
        ["java", "-jar", str(jar), "dump", "manifest", "--bundle", str(aab)],
        check=True, capture_output=True, text=True,
    ).stdout
    facts = parse_manifest(xml)
    root = ET.fromstring(xml)
    ns = "{http://schemas.android.com/apk/res/android}"
    sdk = root.find("uses-sdk")
    facts.update({
        "versionCode": int(root.get(f"{ns}versionCode")) if root.get(f"{ns}versionCode") else None,
        "versionName": root.get(f"{ns}versionName"),
        "targetSdk": int(sdk.get(f"{ns}targetSdkVersion")) if sdk is not None and sdk.get(f"{ns}targetSdkVersion") else None,
        "minSdk": int(sdk.get(f"{ns}minSdkVersion")) if sdk is not None and sdk.get(f"{ns}minSdkVersion") else None,
    })
    return facts


def probe(app_dir: Path) -> list[dict]:
    out = []
    apk = find_apk(app_dir)
    aab = find_aab(app_dir)
    if apk is None and aab is None:
        out.append(probe_missing("android.built.manifest", "an .apk or .aab anywhere under the app directory"))
        return out
    if apk is not None:
        facts = read_apk_manifest(apk)
        facts["artefact"] = apk.name
        facts["artefact_modified"] = datetime.fromtimestamp(apk.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()
        out.append(file_probe("android.built.manifest", facts, apk))
    if aab is not None:
        facts = read_aab_manifest(aab)
        if facts is not None:
            out.append(file_probe("android.bundle.manifest", facts, aab))
        else:
            out.append(make_probe(
                "android.bundle.manifest", None, source_kind="file", source_ref=str(aab),
                source_sha256=sha256_of_file(aab),
                error="bundle found but not read: reading an .aab needs Java and Google's bundletool "
                      "(set STORECHECK_BUNDLETOOL to the jar). The APK was read instead." if apk
                      else "bundle found but not read: needs Java and Google's bundletool "
                           "(set STORECHECK_BUNDLETOOL to the jar), or provide the APK.",
            ))
    return out


def probe_missing(id: str, looked_for: str) -> dict:
    return make_probe(id, None, source_kind="file", source_ref=looked_for, error=f"not found: looked for {looked_for}")


def self_test() -> None:
    # A hand-built binary manifest: string pool (UTF-8) with 6 strings, one
    # <manifest package="a.b"><uses-permission name="P"/></manifest>.
    import struct

    strings = ["manifest", "package", "a.b", "uses-permission", "name", "P"]
    enc = b""
    offsets = []
    for s in strings:
        offsets.append(len(enc))
        b = s.encode()
        enc += bytes([len(s), len(b)]) + b + b"\x00"
    pool_header = 28
    pool_size = pool_header + 4 * len(strings) + len(enc)
    pool = struct.pack("<HHIIIIII", axml.RES_STRING_POOL, pool_header, pool_size, len(strings), 0, axml.UTF8_FLAG,
                       pool_header + 4 * len(strings), 0)
    pool += struct.pack(f"<{len(strings)}I", *offsets) + enc

    def start(name_idx, attr_name_idx=None, attr_val_idx=None):
        attrs = b""
        n = 0
        if attr_name_idx is not None:
            attrs = struct.pack("<IIIHBBI", 0xFFFFFFFF, attr_name_idx, attr_val_idx, 8, 0, axml.TYPE_STRING, attr_val_idx)
            n = 1
        body = struct.pack("<IIIIHHH", 0, 0xFFFFFFFF, 0xFFFFFFFF, name_idx, 20, 20, n) + b"\x00" * 6 + attrs
        return struct.pack("<HHI", axml.RES_XML_START_ELEMENT, 16, 8 + len(body)) + body

    def end(name_idx):
        body = struct.pack("<IIII", 0, 0xFFFFFFFF, 0xFFFFFFFF, name_idx)
        return struct.pack("<HHI", axml.RES_XML_END_ELEMENT, 16, 8 + len(body)) + body

    doc = pool + start(0, 1, 2) + start(3, 4, 5) + end(3) + end(0)
    data = struct.pack("<HHI", axml.RES_XML, 8, 8 + len(doc)) + doc
    facts = axml.manifest_facts(axml.decode(data))
    assert facts["package"] == "a.b", facts
    assert facts["permissions"] == ["P"], facts
    # Negative: a file that is not binary XML is refused, not misread.
    try:
        axml.decode(b"<manifest/>" + b"\x00" * 16)
    except AssertionError:
        pass
    else:
        raise AssertionError("plain-text XML must be refused by the binary decoder")
