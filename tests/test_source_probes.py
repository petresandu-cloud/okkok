import json
import tempfile
import unittest
from pathlib import Path

from storecheck.probes import android_manifest, ios_plist
from storecheck.schema import assert_probe


class SelfTests(unittest.TestCase):
    def test_android_manifest_self_test(self):
        android_manifest.self_test()

    def test_ios_plist_self_test(self):
        ios_plist.self_test()


class EmptyAppDir(unittest.TestCase):
    """An empty directory is not an error. Every probe reports what it looked for and did not find."""

    def test_every_probe_reports_missing_with_a_reason(self):
        with tempfile.TemporaryDirectory() as d:
            probes = android_manifest.probe(Path(d)) + ios_plist.probe(Path(d))
        self.assertEqual(len(probes), 5)
        for p in probes:
            assert_probe(p)
            self.assertIsNone(p["value"])
            self.assertIn("not found", p["error"])
            self.assertEqual(p["provenance"], "verified-directly")

    def test_probes_are_json(self):
        with tempfile.TemporaryDirectory() as d:
            json.dumps(android_manifest.probe(Path(d)))


class SchemaGuards(unittest.TestCase):
    def test_null_value_without_error_is_refused(self):
        from storecheck.schema import make_probe
        with self.assertRaises(ValueError):
            make_probe("x", None, source_kind="file", source_ref="/x")

    def test_unknown_provenance_is_refused(self):
        from storecheck.schema import make_probe
        with self.assertRaises(ValueError):
            make_probe("x", 1, source_kind="file", source_ref="/x", provenance="trust-me")


if __name__ == "__main__":
    unittest.main()


class BuiltSelfTests(unittest.TestCase):
    def test_apk_decoder_self_test(self):
        from storecheck.probes import android_apk
        android_apk.self_test()

    def test_ios_built_self_test(self):
        from storecheck.probes import ios_built
        ios_built.self_test()

    def test_empty_dir_reports_no_artefacts(self):
        from storecheck.probes import android_apk, ios_built
        with tempfile.TemporaryDirectory() as d:
            for p in android_apk.probe(Path(d)) + ios_built.probe(Path(d)):
                assert_probe(p)
                self.assertIsNone(p["value"])
                self.assertIn("not found", p["error"])


class BinaryAndStage(unittest.TestCase):
    def test_dex_self_test(self):
        from storecheck.probes import android_dex
        android_dex.self_test()

    def test_macho_self_test(self):
        from storecheck.probes import ios_macho
        ios_macho.self_test()

    def test_stage_source_only_then_built_then_public(self):
        from storecheck import stage
        from storecheck.schema import make_probe
        src = make_probe("android.source.manifest", {"package": "a.b", "permissions": []}, source_kind="file", source_ref="/m")
        self.assertEqual(stage.decide([src])["google"], "source-only")
        built = make_probe("android.built.manifest", {"package": "a.b", "artefact": "x.apk"}, source_kind="file", source_ref="/x")
        self.assertEqual(stage.decide([src, built])["google"], "built-not-uploaded")
        foreign = make_probe("android.built.manifest", {"package": "z.z", "artefact": "y.apk"}, source_kind="file", source_ref="/y")
        self.assertEqual(stage.decide([src, foreign])["google"], "source-only")  # a foreign APK is ignored
        pub = make_probe("store.google.public", {"public": True, "http": 200, "title": "A"}, source_kind="url", source_ref="u")
        self.assertEqual(stage.decide([src, built, pub])["google"], "public")
        failed = make_probe("store.google.public", None, source_kind="url", source_ref="u", provenance="needs-console-read", error="down")
        self.assertEqual(stage.decide([src, built, failed])["google"], "built-not-uploaded")  # a failed lookup never promotes
