# Contributing

Thank you. storecheck is small on purpose; please keep it that way.

## Ground rules

- **Standard library only** in the command line. The one dependency, `mcp`,
  stays inside the optional adapter.
- **Never read source code.** A probe reads built packages and the declaration
  files around them. If a fact cannot be read from a binary or a manifest, it
  is a judgement question, not a probe.
- **Never store the stores' policy text.** A rule-page record carries an
  address, an expected heading, a fingerprint, our paraphrase and at most one
  quote of 200 characters. The quote is verified against the live page on
  every fetch.
- **Facts and verdicts stay separate.** Probes return facts with provenance.
  Checks turn facts into verdicts. A probe never decides; a check never reads
  a file.
- **Every row says how it is known.** A grid row without exactly one
  provenance marker fails the build. Do not weaken that.
- **The page is generated.** Change `storecheck/report.py` and the contract
  in `REPORT-PRINCIPLES.md` together; `tests/test_report.py` enforces the
  contract.

## Adding a rule

1. Find the rule page. Add a record under `storecheck/corpus/<store>/` with
   `id`, `url`, `expected_heading`, and a paraphrase in your own words. Run
   `python3 -m storecheck corpus fetch` so the record is fingerprinted and
   verified.
2. Add the rule to the right file under `storecheck/rules/`: `id`, `store`,
   `title`, `corpus` (the record ids), `consumes` (the probe ids it needs),
   `kind` (`mechanical` with a `check`, or `judgement` with a `question`),
   `stages`, `severity`, and `applies_when` if it applies only to some apps.
3. A mechanical rule needs a check function in `storecheck/checks.py` that
   returns a verdict and one sentence of evidence naming the fact it used.
4. If Apple and Google both have a rule on the point, add the pair to
   `storecheck/crosswalk/pairs.json` with `same`, `partial`,
   `google-stricter` or `apple-stricter` and one sentence on the difference.
5. `python3 -m unittest` and `python3 -m storecheck self-test` must pass.
   `python3 -m storecheck adversarial <app>` must not list your record as
   uncited or your quote as unverifiable.

## The scripts under `tools/`

They serve the paraphrase workflow and are not part of the package.
`author.py` applies drafted paraphrases to rule-page records; `review.py`
lists records for a fidelity review against the cached page text;
`apply_review.py` writes the review's outcome back. Rule-page records are
edited only through these and through `storecheck corpus`, never by hand.

## Tests

Tests build small apps in a temporary directory and never touch the network.
A test that needs a fixture puts it under `tests/fixtures/`. Every probe has a
`self_test()` that breaks its own rule on purpose and must fail.

## Pull requests

One change per pull request, with the test that proves it. Describe what was
verified and how, not what should work.
