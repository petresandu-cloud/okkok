# Copyright (C) 2026 Editerra AB. Okkok is a trademark of Editerra AB.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the compiled iOS code links and references, read from the executable.

Two facts, kept separate because they mean different things: the frameworks
the executable is linked against (load commands), and the selectors and class
names present anywhere in its bytes. Linked is not proof of use; a present
selector is close to it.
"""

from __future__ import annotations

import plistlib
import re
import struct
import zipfile
from pathlib import Path

from ..capabilities import CAPABILITIES, SIGNALS
from ..schema import file_probe, make_probe
from .ios_built import Bundle, find_bundle

MH_MAGIC_64 = 0xFEEDFACF
MH_CIGAM_64 = 0xCFFAEDFE
FAT_MAGIC = 0xCAFEBABE
FAT_CIGAM = 0xBEBAFECA
LC_LOAD_DYLIB = 0x0C
LC_LOAD_WEAK_DYLIB = 0x80000018
LC_REEXPORT_DYLIB = 0x8000001F
LC_LAZY_LOAD_DYLIB = 0x20
LC_REQ_DYLD = 0x80000000


def _slices(data: bytes) -> list[bytes]:
    magic = struct.unpack_from(">I", data, 0)[0]
    if magic in (FAT_MAGIC, FAT_CIGAM):
        n = struct.unpack_from(">I", data, 4)[0]
        out = []
        for i in range(n):
            _cpu, _sub, off, size, _align = struct.unpack_from(">IIIII", data, 8 + 20 * i)
            out.append(data[off:off + size])
        return out
    return [data]


def linked_libraries(data: bytes) -> dict:
    """{'strong': [...], 'weak': [...]} of dylib install names, every architecture merged."""
    strong, weak = set(), set()
    for s in _slices(data):
        magic = struct.unpack_from("<I", s, 0)[0]
        if magic not in (MH_MAGIC_64, MH_CIGAM_64):
            continue
        ncmds = struct.unpack_from("<I", s, 16)[0]
        off = 32
        for _ in range(ncmds):
            cmd, size = struct.unpack_from("<II", s, off)
            if cmd in (LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LAZY_LOAD_DYLIB):
                name_off = struct.unpack_from("<I", s, off + 8)[0]
                name = s[off + name_off:off + size].split(b"\x00", 1)[0].decode("utf-8", "replace")
                (weak if cmd == LC_LOAD_WEAK_DYLIB else strong).add(name)
            off += size
    return {"strong": sorted(strong), "weak": sorted(weak)}


def framework_names(libs: dict) -> dict:
    def fw(path):
        m = re.search(r"/([A-Za-z0-9_]+)\.framework/", path)
        return m.group(1) if m else None
    return {k: sorted({fw(p) for p in v if fw(p)}) for k, v in libs.items()}


def selectors_present(data: bytes) -> dict:
    out = {}
    for cap, spec in CAPABILITIES.items():
        # plain substring: class names appear inside mangled symbols, selectors as bare strings
        out[cap] = sorted(s.decode() for s in spec["ios_selectors"] if s in data)
    return out


def executable_name(b: Bundle) -> str:
    return plistlib.loads(b.read("Info.plist")).get("CFBundleExecutable", "")


def probe(app_dir: Path) -> list[dict]:
    path = find_bundle(app_dir)
    if path is None:
        return [make_probe("ios.built.references", None, source_kind="file",
                           source_ref="an .ipa or .app anywhere under the app directory",
                           error="not found: no iOS build, so nothing is known about what the compiled code links or references")]
    b = Bundle(path)
    exe = executable_name(b)
    data = b.read(exe)
    libs = linked_libraries(data)
    fws = framework_names(libs)
    by_cap = {}
    sel = selectors_present(data)
    for cap, spec in CAPABILITIES.items():
        by_cap[cap] = {
            "linked": sorted(f for f in spec["ios_frameworks"] if f in fws["strong"]),
            "weak_linked": sorted(f for f in spec["ios_frameworks"] if f in fws["weak"]),
            "selectors": sel[cap],
        }
    # Plugin frameworks inside the bundle carry their own references; scan those too.
    plugin_hits = {}
    for name in b.find(""):
        if name.startswith("Frameworks/") and name.count("/") == 2 and not name.endswith((".plist", ".xcprivacy", ".dylib")):
            fw = name.split("/")[1]
            if name.endswith("/" + fw.removesuffix(".framework")):
                pdata = b.read(name)
                psel = selectors_present(pdata)
                for cap, sels in psel.items():
                    if sels:
                        plugin_hits.setdefault(cap, {})[fw] = sels
    linked = set(fws["strong"]) | set(fws["weak"])
    signals = sorted(name for name, spec in SIGNALS.items()
                     if any(f in linked for f in spec["ios_frameworks"]) or any(s in data for s in spec["ios_strings"]))
    return [file_probe("ios.built.references", {
        "executable": exe,
        "frameworks": fws,
        "by_capability": by_cap,
        "in_bundled_frameworks": plugin_hits,
        "signals": signals,
    }, path)]


def self_test() -> None:
    # A minimal 64-bit Mach-O header with one LC_LOAD_DYLIB and one LC_LOAD_WEAK_DYLIB.
    def dylib_cmd(cmd, name):
        body = name.encode() + b"\x00"
        pad = (-(24 + len(body))) % 8
        return struct.pack("<IIIIII", cmd, 24 + len(body) + pad, 24, 0, 0, 0) + body + b"\x00" * pad
    cmds = dylib_cmd(LC_LOAD_DYLIB, "/System/Library/Frameworks/CoreLocation.framework/CoreLocation") + \
           dylib_cmd(LC_LOAD_WEAK_DYLIB, "/System/Library/Frameworks/UserNotifications.framework/UserNotifications")
    header = struct.pack("<IIIIIIII", MH_MAGIC_64, 0x0100000C, 0, 2, 2, len(cmds), 0, 0)
    data = header + cmds + b"\x00requestAlwaysAuthorization\x00"
    fws = framework_names(linked_libraries(data))
    assert fws == {"strong": ["CoreLocation"], "weak": ["UserNotifications"]}, fws
    sel = selectors_present(data)
    assert sel["background-location"] == ["requestAlwaysAuthorization"], sel
    assert sel["camera"] == [], sel  # negative
    # Negative: a non-Mach-O blob yields nothing, not a crash.
    assert linked_libraries(b"\x00" * 64) == {"strong": [], "weak": []}
