import json
import tempfile
import unittest
from pathlib import Path

from storecheck import checks, grid
from storecheck.schema import make_probe

BUILT_STAGE = {"apple": "built-not-uploaded", "google": "built-not-uploaded"}
VERIFIED = [{"id": r["id"], "status": "verified"} for r in (
    json.load(open(p)) for p in Path(grid.RULES_DIR.parent / "corpus").glob("*/*.json"))]


def apk_probe(target=36, debuggable=False):
    return make_probe("android.built.manifest", {"package": "a.b", "targetSdk": target, "debuggable": debuggable,
                                                  "permissions": [], "artefact": "x.apk"}, source_kind="file", source_ref="/x.apk")


class GridBuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def row(self, g, rid):
        return next(r for r in g["rows"] if r["id"] == rid)

    def test_every_row_has_one_marker_and_grid_validates(self):
        g = grid.build(self.app, [apk_probe()], BUILT_STAGE, as_of="2026-09-06", corpus_records=VERIFIED)
        self.assertTrue(g["rows"])
        grid.validate(g)

    def test_target_api_passes_and_fails_on_the_number(self):
        g = grid.build(self.app, [apk_probe(36)], BUILT_STAGE, as_of="2026-09-06", corpus_records=VERIFIED)
        self.assertEqual(self.row(g, "google.target-api")["verdict"], "PASS")
        g = grid.build(self.app, [apk_probe(34)], BUILT_STAGE, as_of="2026-09-06", corpus_records=VERIFIED)
        self.assertEqual(self.row(g, "google.target-api")["verdict"], "FAIL")

    def test_dated_rule_is_pending_before_its_date(self):
        g = grid.build(self.app, [apk_probe()], BUILT_STAGE, as_of="2026-01-01", corpus_records=VERIFIED)
        self.assertEqual(self.row(g, "google.target-api")["verdict"], "PENDING")
        self.assertIn("2026-08-31", self.row(g, "google.target-api")["evidence"])

    def test_stale_corpus_blocks_every_verdict_that_rests_on_it(self):
        records = [dict(r) for r in VERIFIED]
        next(r for r in records if r["id"] == "google.target-api")["status"] = "stale"
        g = grid.build(self.app, [apk_probe()], BUILT_STAGE, as_of="2026-09-06", corpus_records=records)
        r = self.row(g, "google.target-api")
        self.assertEqual(r["verdict"], "UNKNOWN")
        self.assertIn("stale", r["evidence"])

    def test_missing_fact_carries_its_own_provenance(self):
        pending = make_probe("console.google.declarations", None, source_kind="url", source_ref="console",
                             provenance="needs-console-read", error="no console credentials")
        apk = apk_probe()
        apk["value"]["permissions"] = ["android.permission.ACCESS_FINE_LOCATION"]
        g = grid.build(self.app, [apk, pending], {"apple": None, "google": "in-review"}, as_of="2027-02-01", corpus_records=VERIFIED)
        r = self.row(g, "google.location-scope-declaration")
        self.assertEqual(r["verdict"], "UNKNOWN")
        self.assertEqual(r["provenance"], "needs-console-read")

    def test_judgement_is_discarded_when_facts_change(self):
        info = make_probe("ios.built.info", {"purpose_strings": {"NSCameraUsageDescription": "x"}, "background_modes": [],
                                             "device_family": [1], "frameworks": []}, source_kind="file", source_ref="/i")
        sc = self.app / "storecheck"
        sc.mkdir()
        h = grid.probe_hash([info], ["ios.built.info"])
        (sc / "judgements.jsonl").write_text(json.dumps({"rule": "apple.purpose-strings-say-why", "verdict": "PASS",
                                                          "evidence": "fine", "by": "test", "at": "t", "probe_sha256": h}) + "\n")
        g = grid.build(self.app, [info], BUILT_STAGE, as_of="2026-09-06", corpus_records=VERIFIED)
        r = self.row(g, "apple.purpose-strings-say-why")
        self.assertEqual((r["verdict"], r["provenance"]), ("PASS", "sub-agent-reported"))
        info["value"]["purpose_strings"]["NSCameraUsageDescription"] = "changed"
        g = grid.build(self.app, [info], BUILT_STAGE, as_of="2026-09-06", corpus_records=VERIFIED)
        r = self.row(g, "apple.purpose-strings-say-why")
        self.assertEqual(r["verdict"], "UNKNOWN")
        self.assertIn("discarded", r["evidence"])

    def test_rendered_page_carries_hash_and_hand_edit_is_caught(self):
        g = grid.build(self.app, [apk_probe()], BUILT_STAGE, as_of="2026-09-06", corpus_records=VERIFIED)
        gp, hp = self.app / "grid.json", self.app / "grid.html"
        gp.write_text(json.dumps(g))
        grid.render(gp, hp)
        self.assertIsNone(grid.check_render(gp, hp))
        hp.write_text(hp.read_text().replace("Store Compliance Check", "Store Compliance Cheque", 1))
        self.assertIn("run render", grid.check_render(gp, hp))   # a hand-edited page is caught
        grid.render(gp, hp)
        g["rows"][0]["verdict"] = "FAIL"
        gp.write_text(json.dumps(g))
        self.assertIn("run render", grid.check_render(gp, hp))   # a page left behind by an older grid is caught

    def test_stated_stage_only_raises_and_is_labelled(self):
        from storecheck import stage as stage_mod
        st = {"apple": "built-not-uploaded", "google": None, "evidence": [{"store": "apple", "why": []}, {"store": "google", "why": []}], "newer_build_on_disk": {"apple": False, "google": False}}
        stage_mod.apply_stated(st, {"apple": "in-review", "google": "in-review"}, "the owner")
        self.assertEqual(st["apple"], "in-review")
        self.assertIsNone(st["google"])                      # no app for that store: nothing to raise
        self.assertEqual(st["stated"], {"apple": {"stage": "in-review", "by": "the owner"}})
        self.assertIn("not seen in a console", stage_mod.sentence(st))
        stage_mod.apply_stated(st, {"apple": "source-only"}, "the owner")
        self.assertEqual(st["apple"], "in-review")           # a statement below the evidence is ignored
        with self.assertRaises(ValueError):
            stage_mod.apply_stated(st, {"apple": "shipped"}, "the owner")

    def test_grid_self_test(self):
        grid.self_test()


class Claims(unittest.TestCase):
    def facts(self, text):
        p = make_probe("listing.text", {"name": "A", "apple": {"description": text}, "google": {}}, source_kind="file", source_ref="/l")
        return checks.Facts([p], BUILT_STAGE, "2026-09-06")

    def test_denial_and_advice_pass(self):
        v, e, _ = checks.no_unqualified_claims(self.facts("SOS alerts do not call emergency services. In an emergency, users should contact local emergency services directly."))
        self.assertEqual(v, "PASS", e)

    def test_claim_fails(self):
        v, e, _ = checks.no_unqualified_claims(self.facts("We guarantee delivery. Family Ping calls 112 for you."))
        self.assertEqual(v, "RISK")   # Apple's wording is "shouldn't", so a claim is a risk, not a failure
        self.assertIn("calls 112", e)

    def test_denial_attached_to_the_claim_is_not_a_claim(self):
        v, e, _ = checks.no_unqualified_claims(self.facts("Never miss an emergency: we alert you instantly. This is not an emergency service."))
        self.assertEqual(v, "PASS", e)


class Applicability(unittest.TestCase):
    def test_na_is_a_verdict_with_a_reason_and_unknown_without_a_binary(self):
        import tempfile
        from storecheck import grid
        with tempfile.TemporaryDirectory() as d:
            app = Path(d)
            info = make_probe("ios.built.info", {"purpose_strings": {}, "background_modes": [], "device_family": [1], "frameworks": []}, source_kind="file", source_ref="/i")
            refs = make_probe("ios.built.references", {"executable": "R", "frameworks": {"strong": [], "weak": []}, "by_capability": {"tracking": {"selectors": [], "linked": [], "weak_linked": []}}, "in_bundled_frameworks": {}}, source_kind="file", source_ref="/r")
            g = grid.build(app, [info, refs], {"apple": "built-not-uploaded", "google": None}, as_of="2026-09-06", corpus_records=VERIFIED)
            r = next(r for r in g["rows"] if r["id"] == "apple.tracking-prompt-when-tracking")
            self.assertEqual(r["verdict"], "N/A")
            self.assertIn("capability:tracking", r["evidence"])
            g = grid.build(app, [info], {"apple": "built-not-uploaded", "google": None}, as_of="2026-09-06", corpus_records=VERIFIED)
            r = next(r for r in g["rows"] if r["id"] == "apple.tracking-prompt-when-tracking")
            self.assertEqual(r["verdict"], "UNKNOWN")
            self.assertIn("not decidable", r["evidence"])
