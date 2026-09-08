import json
import re
import tempfile
import unittest
from pathlib import Path

from storecheck import grid, report
from storecheck.schema import make_probe

VERIFIED = [{"id": r["id"], "status": "verified"} for r in (json.load(open(p)) for p in Path(grid.RULES_DIR.parent.parent / "corpus").glob("*/*.json"))]


class ReportPrinciples(unittest.TestCase):
    """REPORT-PRINCIPLES.md, enforced."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Path(self.tmp.name) / "sample-app"
        (self.app / "storecheck").mkdir(parents=True)
        apk = make_probe("android.built.manifest", {"package": "a.b", "targetSdk": 30, "debuggable": False, "permissions": ["android.permission.ACCESS_BACKGROUND_LOCATION"],
                                                    "artefact": "x.apk", "versionName": "1.0", "versionCode": 3, "services": [], "meta_data": {}, "application": {}, "intent_actions": []}, source_kind="file", source_ref="/x.apk")
        lst = make_probe("listing.text", {"name": "Sample App", "apple": {}, "google": {}}, source_kind="file", source_ref="/l")
        probes = [apk, lst]
        from storecheck.schema import write_json
        write_json(self.app / "storecheck" / "probes.json", probes)
        g = grid.build(self.app, probes, {"apple": None, "google": "built-not-uploaded"}, as_of="2026-09-08", corpus_records=VERIFIED)
        write_json(self.app / "storecheck" / "grid.json", g)
        report.render(self.app / "storecheck" / "grid.json", self.app / "storecheck" / "report.html", app_name="sample-app")
        self.page = (self.app / "storecheck" / "report.html").read_text()
        self.text = re.sub(r"<style>.*?</style>", "", self.page, flags=re.S)
        self.text = re.sub(r"<[^>]+>", " ", self.text)

    def tearDown(self):
        self.tmp.cleanup()

    def test_title_block_names_the_check_the_app_and_the_date_in_words(self):
        self.assertIn("Store Compliance Check", self.text)
        self.assertIn("Sample App", self.text)
        self.assertRegex(self.text, r"Run on (Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) \d{1,2} \w+ \d{4}")

    def test_sections_in_the_fixed_order(self):
        order = ["1. What blocks submission", "2. What will likely be questioned", "3. What still has to be checked", "4. Worth knowing", "5. What meets the rules", "6. What does not apply"]
        pos = [self.text.find(s) for s in order]
        self.assertTrue(all(p >= 0 for p in pos), pos)
        self.assertEqual(pos, sorted(pos))

    def test_no_machine_words_reach_the_page(self):
        body = self.text
        for w in report.MACHINE_WORDS:
            self.assertNotRegex(body, r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", f"machine word on the page: {w}")

    def test_every_finding_has_how_we_know_and_the_exports_exist(self):
        self.assertIn("How we know:", self.text)
        for f in ("grid.md", "grid.csv", "actions.json"):
            self.assertTrue((self.app / "storecheck" / f).exists(), f)
        a = json.loads((self.app / "storecheck" / "actions.json").read_text())
        self.assertIn("run_human", a)
        self.assertTrue(all("what_we_found" in x and "how_we_know" in x for x in a["actions"]))

    def test_target_api_finding_is_blocking_and_actionable(self):
        block = self.text[self.text.find("1. What blocks submission"):self.text.find("2. What will likely be questioned")]
        self.assertIn("targetSdk 30", block)
        self.assertIn("What to do", block)
        self.assertIn("build.gradle", block)
