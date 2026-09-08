# Copyright (C) 2026 Editerra AB. Okkok is a trademark of Editerra AB.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the compiled Android code references, read from the DEX string pools inside the APK.

A DEX file keeps every class it mentions as a plain descriptor string such as
Landroid/location/LocationManager;. A byte scan over the string pool finds
them without a full parser and survives obfuscation, which renames the app's
classes but not the platform's.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from ..capabilities import CAPABILITIES, SIGNALS
from ..schema import file_probe, make_probe
from .android_apk import find_apk

DESCRIPTOR = re.compile(rb"L[A-Za-z0-9_/$]+;")


def descriptors_in(apk: Path) -> tuple[set[bytes], bytes]:
    found: set[bytes] = set()
    raw = b""
    with zipfile.ZipFile(apk) as z:
        for name in z.namelist():
            if re.fullmatch(r"classes\d*\.dex", name):
                data = z.read(name)
                found.update(DESCRIPTOR.findall(data))
                raw += data
    return found, raw


def references(descriptors: set[bytes], raw: bytes = b"") -> dict:
    """Per capability: class descriptors found and API strings found. Both empty means
    "no reference found", which is not proof of absence when the capability
    comes from a bundled library the shrinker may have renamed."""
    out = {}
    for cap, spec in CAPABILITIES.items():
        classes = sorted({d.decode() for d in descriptors if any(d.startswith(p) for p in spec["dex_prefixes"])})
        strings = sorted(s.decode() for s in spec.get("dex_strings", []) if s in raw)
        out[cap] = {"classes": classes, "strings": strings}
    return out


def probe(app_dir: Path) -> list[dict]:
    apk = find_apk(app_dir)
    if apk is None:
        return [make_probe("android.built.references", None, source_kind="file",
                           source_ref="an .apk anywhere under the app directory",
                           error="not found: no APK, so nothing is known about what the compiled code references")]
    d, raw = descriptors_in(apk)
    signals = sorted(name for name, spec in SIGNALS.items() if any(any(x.startswith(p) for x in d) for p in spec["dex"]))
    return [file_probe("android.built.references", {"descriptors_scanned": len(d), "by_capability": references(d, raw), "signals": signals}, apk)]


def self_test() -> None:
    fake = {b"Landroid/location/LocationManager;", b"Lcom/example/Foo;", b"Lcom/google/android/gms/location/Geofence;"}
    r = references(fake, b"xx getGeofencingClient yy")
    assert r["location"]["classes"] == ["Landroid/location/LocationManager;"], r
    assert r["background-location"] == {"classes": ["Lcom/google/android/gms/location/Geofence;"], "strings": ["getGeofencingClient"]}, r
    assert r["camera"] == {"classes": [], "strings": []}, r  # negative: absence is reported, not guessed
