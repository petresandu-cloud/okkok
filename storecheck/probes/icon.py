"""The app's icon, as a fact: which file, from where, how large.

Order of preference: the icon inside the built iOS app (what the App Store
shows), then the largest icon in the iOS asset catalogue, then the Android
launcher icon inside the APK, then the Android source mipmaps. The image is
copied to storecheck/icon.png beside the report so the page can embed it.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from ..schema import make_probe, sha256_of_file
from .android_apk import find_apk
from .ios_built import Bundle, find_bundle


def _png_size(data: bytes) -> tuple[int, int] | None:
    """Standard PNG only. Xcode ships iOS icons as Apple's CgBI variant, which browsers cannot show."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None


def displayable(data: bytes) -> bool:
    return _png_size(data) is not None or data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def candidates(app_dir: Path):
    """Yield (origin, name, bytes) in order of preference."""
    b = find_bundle(app_dir)
    if b is not None:
        bundle = Bundle(b)
        icons = [n for n in bundle.find(".png") if n.startswith("AppIcon") and "ipad" not in n.lower()]
        icons.sort(key=lambda n: -int(re.search(r"(\d+)x\d+@(\d)x", n).group(1)) * int(re.search(r"(\d+)x\d+@(\d)x", n).group(2)) if re.search(r"(\d+)x\d+@(\d)x", n) else 0)
        for n in icons[:1]:
            yield f"iOS build {b.name}", n, bundle.read(n)
    for cat in sorted(app_dir.glob("ios/*/Assets.xcassets/AppIcon.appiconset/*.png")):
        m = re.search(r"(\d+)x\d+", cat.name)
        if m and int(m.group(1)) >= 512:
            yield "iOS asset catalogue", str(cat.relative_to(app_dir)), cat.read_bytes()
            break
    apk = find_apk(app_dir)
    if apk is not None:
        with zipfile.ZipFile(apk) as z:
            names = [n for n in z.namelist() if re.search(r"mipmap-xxxhdpi.*ic_launcher(_round)?\.(png|webp)$", n)] or \
                    [n for n in z.namelist() if re.search(r"ic_launcher\.(png|webp)$", n)]
            for n in names[:1]:
                yield f"Android build {apk.name}", n, z.read(n)
    for dens in ("xxxhdpi", "xxhdpi", "xhdpi", "hdpi", "mdpi"):
        for p in sorted(app_dir.glob(f"android/app/src/main/res/mipmap-{dens}/ic_launcher.*")):
            yield "Android source", str(p.relative_to(app_dir)), p.read_bytes()
            return


def probe(app_dir: Path) -> list[dict]:
    for origin, name, data in candidates(app_dir):
        if not displayable(data):
            continue  # Apple-optimised PNG or something else a page cannot show
        out = app_dir / "storecheck" / ("icon.png" if data[:4] == b"\x89PNG" else "icon.webp")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        size = _png_size(data)
        return [make_probe("app.icon", {"file": str(out), "from": origin, "source_name": name, "bytes": len(data),
                                        "width": size[0] if size else None, "height": size[1] if size else None},
                           source_kind="file", source_ref=f"{origin}: {name}", source_sha256=sha256_of_file(out))]
    return [make_probe("app.icon", None, source_kind="file", source_ref="AppIcon*.png in the iOS build, AppIcon.appiconset, ic_launcher in the APK or mipmaps",
                       error="not found: no app icon in the built packages or the source")]


def self_test() -> None:
    assert _png_size(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (120).to_bytes(4, "big") + (120).to_bytes(4, "big")) == (120, 120)
    assert _png_size(b"RIFF....WEBP") is None
    assert _png_size(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x04CgBI" + b"\x00" * 12) is None  # Apple's variant is refused
