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
        from storecheck.schema import probe
        with self.assertRaises(ValueError):
            probe("x", None, source_kind="file", source_ref="/x")

    def test_unknown_provenance_is_refused(self):
        from storecheck.schema import probe
        with self.assertRaises(ValueError):
            probe("x", 1, source_kind="file", source_ref="/x", provenance="trust-me")


if __name__ == "__main__":
    unittest.main()
