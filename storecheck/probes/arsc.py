# Copyright (C) 2026 Editerra AB. Okkok is a trademark of Editerra AB.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read an APK's resource table (resources.arsc) far enough to resolve one resource
id to its values: the file path behind an icon, the text behind a label.

Release builds obfuscate resource file names, so an icon cannot be found by name;
the manifest's `icon` attribute is a resource id and the table maps it to a path
per configuration. Only string values are resolved; that is all a store reads.
"""

from __future__ import annotations

import struct

from .axml import RES_STRING_POOL, _read_string_pool

RES_TABLE = 0x0002
RES_TABLE_PACKAGE = 0x0200
RES_TABLE_TYPE = 0x0201
RES_TABLE_TYPE_SPEC = 0x0202
TYPE_STRING = 0x03
TYPE_REFERENCE = 0x01
FLAG_COMPLEX = 0x0001
FLAG_SPARSE = 0x01
FLAG_OFFSET16 = 0x02
NO_ENTRY = 0xFFFFFFFF


def resolve(data: bytes, res_id: int) -> list[dict]:
    """Every value of one resource id, one per configuration: {density, locale, type, value, ref}."""
    typ, header_size, total, _pkg_count = struct.unpack_from("<HHII", data, 0)
    if typ != RES_TABLE:
        raise ValueError(f"not a resource table (first chunk {typ:#x})")
    want_pkg, want_type, want_entry = (res_id >> 24) & 0xFF, (res_id >> 16) & 0xFF, res_id & 0xFFFF
    strings: list[str] = []
    out: list[dict] = []
    off = header_size
    while off < total:
        ctype, chsize, csize = struct.unpack_from("<HHI", data, off)
        if ctype == RES_STRING_POOL:
            strings = _read_string_pool(data, off)
        elif ctype == RES_TABLE_PACKAGE:
            pkg_id = struct.unpack_from("<I", data, off + 8)[0]
            if pkg_id == want_pkg:
                out.extend(_package(data, off, chsize, csize, want_type, want_entry, strings))
        off += csize
    return out


def _package(data, off, header_size, size, want_type, want_entry, strings):
    found = []
    p = off + header_size
    end = off + size
    while p < end:
        ctype, chsize, csize = struct.unpack_from("<HHI", data, p)
        if ctype == RES_TABLE_TYPE:
            type_id, flags = struct.unpack_from("<BB", data, p + 8)
            if type_id == want_type:
                entry_count, entries_start = struct.unpack_from("<II", data, p + 12)
                cfg = p + 20
                cfg_size = struct.unpack_from("<I", data, cfg)[0]
                density = struct.unpack_from("<H", data, cfg + 14)[0] if cfg_size >= 16 else 0
                lang = data[cfg + 8:cfg + 10].replace(b"\x00", b"").decode("ascii", "replace") if cfg_size >= 12 else ""
                offsets_at = cfg + cfg_size
                entry_off = None
                if flags & FLAG_SPARSE:
                    for i in range(entry_count):
                        idx, o16 = struct.unpack_from("<HH", data, offsets_at + i * 4)
                        if idx == want_entry:
                            entry_off = o16 * 4
                            break
                elif flags & FLAG_OFFSET16:
                    if want_entry < entry_count:
                        o16 = struct.unpack_from("<H", data, offsets_at + want_entry * 2)[0]
                        entry_off = None if o16 == 0xFFFF else o16 * 4
                elif want_entry < entry_count:
                    o = struct.unpack_from("<I", data, offsets_at + want_entry * 4)[0]
                    entry_off = None if o == NO_ENTRY else o
                if entry_off is not None:
                    e = p + entries_start + entry_off
                    esize, eflags = struct.unpack_from("<HH", data, e)
                    if not eflags & FLAG_COMPLEX:
                        _vsize, _res0, vtype, vdata = struct.unpack_from("<HBBI", data, e + esize)
                        rec = {"density": density, "locale": lang, "type": vtype, "value": None, "ref": None}
                        if vtype == TYPE_STRING and vdata < len(strings):
                            rec["value"] = strings[vdata]
                        elif vtype == TYPE_REFERENCE:
                            rec["ref"] = vdata
                        found.append(rec)
        p += csize
    return found


def string_for(data: bytes, res_id: int, depth: int = 0) -> str | None:
    """The default-locale string value of a resource, following references up to three deep."""
    vals = resolve(data, res_id)
    plain = [v for v in vals if v["value"] is not None and not v["locale"]] or [v for v in vals if v["value"] is not None]
    if plain:
        return plain[0]["value"]
    refs = [v for v in vals if v["ref"] is not None]
    if refs and depth < 3:
        return string_for(data, refs[0]["ref"], depth + 1)
    return None


def image_paths_for(data: bytes, res_id: int) -> list[tuple[int, str]]:
    """Image file paths behind a drawable or mipmap id, densest first. XML values (adaptive icons) are left out."""
    vals = resolve(data, res_id)
    paths = [(v["density"], v["value"]) for v in vals if v["value"] and v["value"].lower().endswith((".png", ".webp", ".jpg"))]
    return sorted(paths, key=lambda x: -x[0])


def parse_ref(value) -> int | None:
    """The manifest decoder writes references as '@0x7f0e0001'."""
    if isinstance(value, str) and value.startswith("@0x"):
        return int(value[3:], 16)
    return None


# ------------------------------------------------------------------ self-test

def _pool(strings: list[str]) -> bytes:
    """A UTF-16 string pool, the encoding aapt writes for tables."""
    body = b""
    offsets = []
    for s in strings:
        offsets.append(len(body))
        enc = s.encode("utf-16-le")
        body += struct.pack("<H", len(s)) + enc + b"\x00\x00"
    header = struct.pack("<HHIIIIII", RES_STRING_POOL, 28, 0, len(strings), 0, 0, 28 + 4 * len(strings), 0)
    chunk = header + b"".join(struct.pack("<I", o) for o in offsets) + body
    chunk = chunk[:4] + struct.pack("<I", len(chunk)) + chunk[8:]
    return chunk


def _table(entry_value_index: int, density: int, path_strings: list[str]) -> bytes:
    pool = _pool(path_strings)
    # one type chunk with one entry (id 0x7f010000) holding a string value
    cfg = struct.pack("<I", 28) + b"\x00" * 10 + struct.pack("<H", density) + b"\x00" * 12
    entry = struct.pack("<HHI", 8, 0, 0) + struct.pack("<HBBI", 8, 0, TYPE_STRING, entry_value_index)
    offsets = struct.pack("<I", 0)
    type_header_size = 20 + len(cfg)
    entries_start = type_header_size + len(offsets)
    type_chunk = struct.pack("<HHIBBHII", RES_TABLE_TYPE, type_header_size, type_header_size + len(offsets) + len(entry), 1, 0, 0, 1, entries_start) + cfg + offsets + entry
    spec = struct.pack("<HHIBBHI", RES_TABLE_TYPE_SPEC, 16, 16 + 4, 1, 0, 0, 1) + struct.pack("<I", 0)
    type_strings, key_strings = _pool(["mipmap"]), _pool(["ic_launcher"])
    pkg_header_size = 288
    pkg_body = type_strings + key_strings + spec + type_chunk
    pkg = struct.pack("<HHII", RES_TABLE_PACKAGE, pkg_header_size, pkg_header_size + len(pkg_body), 0x7F) + b"\x00" * 256 \
        + struct.pack("<IIIII", pkg_header_size, 1, pkg_header_size + len(type_strings), 1, 0) + b"\x00" * (pkg_header_size - 12 - 256 - 20)
    pkg += pkg_body
    table = struct.pack("<HHII", RES_TABLE, 12, 12 + len(pool) + len(pkg), 1) + pool + pkg
    return table


def self_test() -> None:
    t = _table(1, 640, ["res/a.xml", "res/b.png"])
    assert resolve(t, 0x7F010000)[0]["value"] == "res/b.png"
    assert image_paths_for(t, 0x7F010000) == [(640, "res/b.png")]
    assert string_for(t, 0x7F010000) == "res/b.png"
    assert resolve(t, 0x7F010001) == []            # an entry that does not exist resolves to nothing
    assert parse_ref("@0x7f010000") == 0x7F010000 and parse_ref("plain") is None
    try:
        resolve(b"\x03\x00\x08\x00" + b"\x00" * 8, 1)
        raise AssertionError("a binary XML file must not pass as a resource table")
    except ValueError:
        pass
