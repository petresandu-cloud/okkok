# Copyright (C) 2026 Editerra AB. Okkok is a trademark of Editerra AB.
# SPDX-License-Identifier: AGPL-3.0-or-later
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from storecheck import corpus
from storecheck.schema import sha256_of_text

GOOD = "<html><body><h1>Understanding Things</h1><p>" + "Words about the rule. " * 40 + "</p></body></html>"
DEAD = "<html><body><h1>Sorry, this page can't be found.</h1><p>Try searching.</p></body></html>"


def record(**kw):
    r = {"id": "t.rec", "store": "google", "url": "https://support.google.com/googleplay/android-developer/answer/1",
         "expected_heading": "Understanding Things", "paraphrase": "p", "status": "unfetched"}
    r.update(kw)
    return r


class Traps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(corpus, "CACHE_DIR", Path(self.tmp.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def fetch_with(self, status, body, final=None, rec=None):
        rec = rec or record()
        with mock.patch.object(corpus, "fetch_url", return_value=(status, body, final or rec["url"])):
            return corpus.fetch(rec)

    def test_first_read_is_verified_and_hashed(self):
        r = self.fetch_with(200, GOOD)
        self.assertEqual(r["status"], "verified")
        self.assertEqual(len(r["sha256"]), 64)

    def test_dead_page_is_wrong_page(self):
        r = self.fetch_with(404, DEAD)
        self.assertEqual(r["status"], "unreadable")  # 404 first
        r = self.fetch_with(200, DEAD)
        self.assertEqual(r["status"], "unreadable")  # too short to be a policy
        long_dead = DEAD.replace("Try searching.", "Try searching. " * 40)
        r = self.fetch_with(200, long_dead)
        self.assertEqual(r["status"], "wrong-page")
        self.assertIn("Sorry", r["note"])

    def test_redirect_off_the_page_is_wrong_page(self):
        r = self.fetch_with(200, GOOD, final="https://support.google.com/")
        self.assertEqual(r["status"], "wrong-page")

    def test_rewritten_page_is_stale_until_accepted(self):
        r = self.fetch_with(200, GOOD)
        r = self.fetch_with(200, GOOD.replace("Words about", "New words about"), rec=r)
        self.assertEqual(r["status"], "stale")
        self.assertNotEqual(r["sha256"], r["observed_sha256"])
        r, diff = corpus.accept(r)
        self.assertEqual(r["status"], "verified")
        self.assertIn("New words", diff)

    def test_fabricated_quote_is_caught(self):
        r = self.fetch_with(200, GOOD, rec=record(quote="Words about the rule."))
        self.assertEqual(r["status"], "verified")
        r = self.fetch_with(200, GOOD, rec=record(quote="Words the rule never said."))
        self.assertEqual(r["status"], "quote-mismatch")

    def test_verify_from_cache_needs_no_network(self):
        r = self.fetch_with(200, GOOD)
        with mock.patch.object(corpus, "fetch_url", side_effect=AssertionError("network used")):
            self.assertEqual(corpus.verify_from_cache(r)["status"], "verified")
            r["sha256"] = sha256_of_text("something else")
            self.assertEqual(corpus.verify_from_cache(r)["status"], "stale")

    def test_empty_body_is_unreadable_not_silent(self):
        r = self.fetch_with(200, "<html><head><title>Only a title</title></head><body></body></html>")
        self.assertEqual(r["status"], "unreadable")
        self.assertIn("characters of text", r["note"])

    def test_corpus_self_test(self):
        corpus.self_test()


class StatusForRun(unittest.TestCase):
    def test_a_machine_without_a_cache_relies_on_the_shipped_verification_and_says_so(self):
        import tempfile
        from unittest import mock
        from storecheck import corpus
        with tempfile.TemporaryDirectory() as d, mock.patch.object(corpus, "CACHE_DIR", Path(d)):
            rec = {"id": "x.y", "status": "verified", "sha256": "0" * 64, "fetched_at": "2026-09-01T00:00:00+00:00"}
            out = corpus.status_for_run(dict(rec))
            self.assertEqual(out["status"], "verified")
            self.assertIs(out["checked_here"], False)
            (Path(d) / "x.y.txt").write_text("some other text", encoding="utf-8")
            out = corpus.status_for_run(dict(rec))
            self.assertEqual(out["status"], "stale")          # a cache that exists is checked, and disagrees
            self.assertIs(out["checked_here"], True)
