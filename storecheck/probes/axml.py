"""Decoder for Android's binary XML, the form AndroidManifest.xml takes inside an APK.

The format has not changed since 2008. It is a string pool followed by a flat
stream of start/end element chunks whose attributes are typed values. This
reads only what a store reads: element names, attribute names and values.
Nothing here depends on the Android SDK.
"""

from __future__ import annotations

import struct

RES_STRING_POOL = 0x0001
RES_XML = 0x0003
RES_XML_START_NAMESPACE = 0x0100
RES_XML_END_NAMESPACE = 0x0101
RES_XML_START_ELEMENT = 0x0102
RES_XML_END_ELEMENT = 0x0103
RES_XML_RESOURCE_MAP = 0x0180

TYPE_REFERENCE = 0x01
TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11
TYPE_INT_BOOLEAN = 0x12

UTF8_FLAG = 0x100


def _read_string_pool(data: bytes, off: int) -> list[str]:
    (typ, header_size, chunk_size, count, style_count, flags, strings_start, styles_start) = struct.unpack_from(
        "<HHIIIIII", data, off
    )
    assert typ == RES_STRING_POOL, f"expected string pool at {off}, got {typ:#x}"
    offsets = struct.unpack_from(f"<{count}I", data, off + header_size)
    base = off + strings_start
    utf8 = bool(flags & UTF8_FLAG)
    out = []
    for so in offsets:
        p = base + so
        if utf8:
            # two lengths: utf-16 char count then byte count, each 1 or 2 bytes
            n = data[p]
            p += 2 if n & 0x80 else 1
            n = data[p]
            if n & 0x80:
                n = ((n & 0x7F) << 8) | data[p + 1]
                p += 2
            else:
                p += 1
            out.append(data[p:p + n].decode("utf-8", "replace"))
        else:
            n = struct.unpack_from("<H", data, p)[0]
            p += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", data, p)[0]
                p += 2
            out.append(data[p:p + 2 * n].decode("utf-16-le", "replace"))
    return out


def _value(typ: int, data_word: int, strings: list[str]):
    if typ == TYPE_STRING:
        return strings[data_word] if data_word < len(strings) else None
    if typ == TYPE_INT_BOOLEAN:
        return data_word != 0
    if typ in (TYPE_INT_DEC, TYPE_INT_HEX):
        return data_word if data_word < 0x80000000 else data_word - 0x100000000
    if typ == TYPE_REFERENCE:
        return f"@0x{data_word:08x}"
    return data_word


def decode(data: bytes) -> dict:
    """Return the manifest as a nested dict: {tag, attrs, children}.

    Attribute keys are the bare attribute names (the android: prefix is implied
    for everything a manifest carries; a store reads them the same way).
    """
    typ, header_size, total = struct.unpack_from("<HHI", data, 0)
    assert typ == RES_XML, f"not Android binary XML (first chunk {typ:#x})"
    off = header_size
    strings: list[str] = []
    root = {"tag": "#document", "attrs": {}, "children": []}
    stack = [root]
    while off < total:
        ctype, chsize, csize = struct.unpack_from("<HHI", data, off)
        if ctype == RES_STRING_POOL:
            strings = _read_string_pool(data, off)
        elif ctype == RES_XML_START_ELEMENT:
            (_line, _comment, _ns, name_idx, attr_start, attr_size, attr_count) = struct.unpack_from(
                "<IIIIHHH", data, off + 8
            )
            attrs = {}
            # attribute offsets count from the end of the chunk header (line and
            # comment sit between the header and the element proper)
            p = off + chsize + attr_start
            for _ in range(attr_count):
                (_ans, aname, _raw, _size, _res0, atype, adata) = struct.unpack_from("<IIIHBBI", data, p)
                attrs[strings[aname]] = _value(atype, adata, strings)
                p += attr_size
            node = {"tag": strings[name_idx], "attrs": attrs, "children": []}
            stack[-1]["children"].append(node)
            stack.append(node)
        elif ctype == RES_XML_END_ELEMENT:
            stack.pop()
        # namespaces, resource map and cdata carry nothing a store reads
        off += csize
    return root["children"][0] if root["children"] else root


def manifest_facts(tree: dict) -> dict:
    """The same shape android_manifest.parse_manifest returns, so source and built compare directly."""
    def walk(node, tag):
        if node["tag"] == tag:
            yield node
        for c in node["children"]:
            yield from walk(c, tag)

    a = tree["attrs"]
    uses_sdk = next(walk(tree, "uses-sdk"), None)
    return {
        "package": a.get("package"),
        "versionCode": a.get("versionCode"),
        "versionName": a.get("versionName"),
        "targetSdk": uses_sdk["attrs"].get("targetSdkVersion") if uses_sdk else None,
        "minSdk": uses_sdk["attrs"].get("minSdkVersion") if uses_sdk else None,
        "permissions": sorted(n["attrs"].get("name") for n in walk(tree, "uses-permission") if n["attrs"].get("name")),
        "features": [
            {"name": n["attrs"].get("name"), "required": n["attrs"].get("required", True) is not False}
            for n in walk(tree, "uses-feature") if n["attrs"].get("name")
        ],
        "services": [
            {"name": n["attrs"].get("name"), "foregroundServiceType": n["attrs"].get("foregroundServiceType")}
            for n in walk(tree, "service")
        ],
        "debuggable": bool(next(walk(tree, "application"), {"attrs": {}})["attrs"].get("debuggable", False)),
        "meta_data": {n["attrs"].get("name"): n["attrs"].get("value", n["attrs"].get("resource")) for n in walk(tree, "meta-data") if n["attrs"].get("name")},
        "intent_actions": sorted({n["attrs"].get("name") for n in walk(tree, "action") if n["attrs"].get("name")}),
        "application": {k: next(walk(tree, "application"), {"attrs": {}})["attrs"].get(k) for k in ("usesCleartextTraffic", "networkSecurityConfig", "icon", "roundIcon", "label")},
    }
