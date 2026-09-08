# Copyright (C) 2026 Editerra AB. Okkok is a trademark of Editerra AB.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read-only readers for App Store Connect and the Google Play Developer API.

Credentials come from the environment, the same names the usual upload
scripts use, and are never written anywhere by this tool:

    APP_STORE_CONNECT_API_KEY_ID, APP_STORE_CONNECT_API_ISSUER_ID, APP_STORE_CONNECT_API_KEY_PATH
    GOOGLE_PLAY_SERVICE_ACCOUNT_JSON

Signing uses the openssl command so the tool stays on the standard library.
Without credentials every console probe is null with needs-console-read.
Reading is evidence; writing spends review cycles and stays with a person,
so nothing here sends anything but GET, and the one Play "edit" it opens is
deleted, never committed.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..schema import make_probe

ASC = "https://api.appstoreconnect.apple.com/v1"
PLAY = "https://androidpublisher.googleapis.com/androidpublisher/v3"


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def der_to_raw(der: bytes, size: int = 32) -> bytes:
    """An ECDSA signature from openssl is DER (SEQUENCE of two INTEGERs); JWT wants r||s."""
    assert der[0] == 0x30
    i = 2 if der[1] < 0x80 else 3
    out = b""
    for _ in range(2):
        assert der[i] == 0x02
        n = der[i + 1]
        v = der[i + 2:i + 2 + n].lstrip(b"\x00")
        out += v.rjust(size, b"\x00")
        i += 2 + n
    return out


def openssl_sign(key_path: str, data: bytes, ec: bool) -> bytes:
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(data)
        name = f.name
    try:
        sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key_path, name], check=True, capture_output=True).stdout
    finally:
        os.unlink(name)
    return der_to_raw(sig) if ec else sig


def jwt(header: dict, claims: dict, key_path: str, ec: bool) -> str:
    signing = b64url(json.dumps(header, separators=(",", ":")).encode()) + "." + b64url(json.dumps(claims, separators=(",", ":")).encode())
    return signing + "." + b64url(openssl_sign(key_path, signing.encode(), ec))


def get(url: str, token: str, method: str = "GET", body: bytes | None = None, extra: dict | None = None):
    req = urllib.request.Request(url, method=method, data=body, headers={"Authorization": f"Bearer {token}", "Accept": "application/json", **(extra or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "{}")


# ------------------------------------------------------------------ Apple

def apple(bundle_id: str) -> list[dict]:
    kid, iss, path = (os.environ.get(k) for k in ("APP_STORE_CONNECT_API_KEY_ID", "APP_STORE_CONNECT_API_ISSUER_ID", "APP_STORE_CONNECT_API_KEY_PATH"))
    ref = "App Store Connect API"
    if not (kid and iss and path and Path(path).is_file()):
        why = "no App Store Connect API key in the environment (APP_STORE_CONNECT_API_KEY_ID, _ISSUER_ID, _KEY_PATH)"
        return [make_probe(i, None, source_kind="url", source_ref=ref, provenance="needs-console-read", error=why)
                for i in ("console.apple.internal-beta", "console.apple.in-review", "console.apple.state")]
    try:
        now = int(time.time())
        token = jwt({"alg": "ES256", "kid": kid, "typ": "JWT"}, {"iss": iss, "iat": now, "exp": now + 600, "aud": "appstoreconnect-v1"}, path, ec=True)
        apps = get(f"{ASC}/apps?filter[bundleId]={bundle_id}", token)["data"]
        if not apps:
            return [make_probe("console.apple.state", {"app_found": False}, source_kind="url", source_ref=ref)]
        app_id = apps[0]["id"]
        versions = get(f"{ASC}/apps/{app_id}/appStoreVersions?limit=5&sort=-createdDate", token)["data"]
        builds = get(f"{ASC}/apps/{app_id}/builds?limit=3&sort=-uploadedDate", token)["data"]
        vs = [{"version": v["attributes"].get("versionString"), "state": v["attributes"].get("appStoreState") or v["attributes"].get("appVersionState"),
               "platform": v["attributes"].get("platform"), "created": v["attributes"].get("createdDate")} for v in versions]
        bs = [{"version": b["attributes"].get("version"), "processing": b["attributes"].get("processingState"),
               "uploaded": b["attributes"].get("uploadedDate"), "expired": b["attributes"].get("expired")} for b in builds]
        in_review = next((v for v in vs if v["state"] in ("WAITING_FOR_REVIEW", "IN_REVIEW", "PENDING_DEVELOPER_RELEASE")), None)
        beta = next((b for b in bs if b["processing"] == "VALID" and not b["expired"]), None)
        return [
            make_probe("console.apple.state", {"app_found": True, "app_id": app_id, "versions": vs, "builds": bs}, source_kind="url", source_ref=ref),
            make_probe("console.apple.internal-beta", f"build {beta['version']} uploaded {beta['uploaded']}" if beta else None, source_kind="url", source_ref=ref,
                       error=None if beta else "no valid, unexpired build in TestFlight"),
            make_probe("console.apple.in-review", f"version {in_review['version']} is {in_review['state']}" if in_review else None, source_kind="url", source_ref=ref,
                       error=None if in_review else "no version waiting for or in review; states: " + ", ".join(f"{v['version']} {v['state']}" for v in vs)),
        ]
    except (urllib.error.HTTPError, urllib.error.URLError, subprocess.CalledProcessError, KeyError, AssertionError) as e:
        body = e.read().decode()[:300] if isinstance(e, urllib.error.HTTPError) else str(e)
        return [make_probe(i, None, source_kind="url", source_ref=ref, provenance="needs-console-read", error=f"App Store Connect call failed: {body}")
                for i in ("console.apple.internal-beta", "console.apple.in-review", "console.apple.state")]


# ------------------------------------------------------------------ Google

def google(package: str) -> list[dict]:
    sa = os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON")
    ref = "Google Play Developer API"
    not_exposed = [
        make_probe("console.google.declarations", None, source_kind="url", source_ref="Play Console", provenance="needs-console-read",
                   error="the Play Developer API does not expose the permission declaration forms; read them in the console"),
        make_probe("console.google.data-safety", None, source_kind="url", source_ref="Play Console", provenance="needs-console-read",
                   error="the Play Developer API does not expose the Data safety form; read it in the console"),
    ]
    if not (sa and Path(sa).is_file()):
        why = "no Play service account in the environment (GOOGLE_PLAY_SERVICE_ACCOUNT_JSON)"
        return [make_probe(i, None, source_kind="url", source_ref=ref, provenance="needs-console-read", error=why)
                for i in ("console.google.internal-beta", "console.google.in-review", "console.google.tracks")] + not_exposed
    try:
        acct = json.loads(Path(sa).read_text())
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".pem") as f:
            f.write(acct["private_key"])
            pem = f.name
        try:
            now = int(time.time())
            assertion = jwt({"alg": "RS256", "typ": "JWT"},
                            {"iss": acct["client_email"], "scope": "https://www.googleapis.com/auth/androidpublisher",
                             "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 600}, pem, ec=False)
        finally:
            os.unlink(pem)
        data = f"grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer&assertion={assertion}".encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=30) as r:
            token = json.loads(r.read())["access_token"]
        edit = get(f"{PLAY}/applications/{package}/edits", token, method="POST", body=b"{}", extra={"Content-Type": "application/json"})
        try:
            tracks = get(f"{PLAY}/applications/{package}/edits/{edit['id']}/tracks", token).get("tracks", [])
        finally:
            get(f"{PLAY}/applications/{package}/edits/{edit['id']}", token, method="DELETE")
        summary = [{"track": t["track"], "releases": [{"name": r.get("name"), "status": r.get("status"), "versionCodes": r.get("versionCodes", [])}
                                                   for r in t.get("releases", [])]} for t in tracks]
        with_releases = [t for t in summary if t["releases"]]
        test_tracks = [t["track"] for t in with_releases if t["track"] != "production"]
        prod = next((t for t in with_releases if t["track"] == "production"), None)
        return [
            make_probe("console.google.tracks", summary, source_kind="url", source_ref=ref),
            make_probe("console.google.internal-beta", "releases on " + ", ".join(test_tracks) if test_tracks else None, source_kind="url", source_ref=ref,
                       error=None if test_tracks else "no release on any test track"),
            make_probe("console.google.in-review", None, source_kind="url", source_ref="Play Console", provenance="needs-console-read",
                       error="the Play Developer API reports release status, not review status; whether a release is under review is read in the console"),
        ] + not_exposed + ([make_probe("console.google.production", prod, source_kind="url", source_ref=ref)] if prod else [])
    except (urllib.error.HTTPError, urllib.error.URLError, subprocess.CalledProcessError, KeyError) as e:
        body = e.read().decode()[:300] if isinstance(e, urllib.error.HTTPError) else str(e)
        return [make_probe(i, None, source_kind="url", source_ref=ref, provenance="needs-console-read", error=f"Play API call failed: {body}")
                for i in ("console.google.internal-beta", "console.google.in-review", "console.google.tracks")] + not_exposed


def probe_ids(bundle_id: str | None, package: str | None) -> list[dict]:
    out = []
    if bundle_id:
        out += apple(bundle_id)
    if package:
        out += google(package)
    return out


def self_test() -> None:
    # DER -> raw for a known-shape signature: two 32-byte integers, one with a leading zero pad.
    r = bytes(range(1, 33))
    s = b"\x00" + bytes(range(100, 131))  # 31 bytes after the pad
    der = b"\x30" + bytes([4 + len(r) + len(s)]) + b"\x02" + bytes([len(r)]) + r + b"\x02" + bytes([len(s)]) + s
    raw = der_to_raw(der)
    assert len(raw) == 64 and raw[:32] == r and raw[32:] == b"\x00" + s[1:], raw.hex()
    assert b64url(b"\xff\xfe") == "__4"
