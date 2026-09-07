import json
import tempfile
import unittest
from pathlib import Path

from storecheck import adversary, judge
from storecheck.schema import make_probe, write_json


class Judgements(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Path(self.tmp.name)
        info = make_probe("ios.built.info", {"purpose_strings": {"NSCameraUsageDescription": "For QR pairing."}, "background_modes": [],
                                             "device_family": [1], "frameworks": []}, source_kind="file", source_ref="/i")
        write_json(self.app / "storecheck" / "probes.json", [info])
        write_json(self.app / "storecheck" / "stage.json", {"apple": "built-not-uploaded", "google": None})

    def tearDown(self):
        self.tmp.cleanup()

    def test_mechanical_rule_cannot_be_judged(self):
        with self.assertRaises(ValueError):
            judge.add_judgement(self.app, "apple.privacy-manifest-present", "PASS", "I looked at it carefully and it is there", "me")

    def test_thin_evidence_is_refused(self):
        with self.assertRaises(ValueError):
            judge.add_judgement(self.app, "apple.purpose-strings-say-why", "PASS", "fine", "me")

    def test_judgement_is_sub_agent_reported_whatever_the_judge_claims(self):
        j = judge.add_judgement(self.app, "apple.purpose-strings-say-why", "PASS", "Read the camera string; it names QR pairing.", "me")
        self.assertEqual(j["provenance"], "sub-agent-reported")

    def test_resolution_needs_proof_and_guard(self):
        with self.assertRaises(ValueError):
            judge.add_resolution(self.app, "apple.purpose-string-keys-are-real", was="x", changed="y", proof="", guard="", residual_risk="none", by="me")

    def test_adversary_catches_a_quote_nobody_can_find(self):
        judge.add_judgement(self.app, "apple.purpose-strings-say-why", "PASS",
                            'The string reads "For QR pairing." which names the feature.', "honest")
        judge.add_judgement(self.app, "apple.account-deletion-in-app", "PASS",
                            'The screen says "Delete everything now with a single confident tap" so it qualifies.', "planted")
        judge.rebuild(self.app, as_of="2026-09-06")
        out = adversary.run(self.app)
        bad = out["unverifiable_quotations"]
        self.assertEqual([b["by"] for b in bad], ["planted"])


class QuotePairing(unittest.TestCase):
    def test_text_between_two_quotations_is_not_a_quotation(self):
        spans = adversary.quoted_spans('It says "the first quoted sentence here" and later "the second quoted sentence here" too.')
        self.assertEqual(spans, ["the first quoted sentence here", "the second quoted sentence here"])
