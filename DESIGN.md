# Design

Why okkok is built the way it is. Each decision below was tested where a
test was possible, not argued. The code is the authority where this file and
the code disagree; tell us, and this file gets fixed.

## The goal, in one paragraph

Point okkok at an app directory. It works out how far along the app is
(source only, built, on a test track, in review, public), reads the built
Android package and iOS app the way the stores do, fetches the current rule
pages and proves they have not changed since they were last read, checks every
mechanical rule with no model in the loop, hands the judgement questions to
whatever model or person is attached, runs a second pass whose only job is to
break the first, and produces one report where every finding says how its
verdict is known. Fix proposals come from what the binary shows this app
doing, never from a template.

## Decisions and their reasons

**Python, standard library only.** `plistlib` reads XML and binary plists,
`zipfile` opens APK, AAB and IPA files, `html.parser` gives headings and text,
`urllib` fetches, `tomllib` reads the hand-written rule files, `struct` reads
the binary formats, `unittest` runs the tests. The only thing the standard
library lacks is a Model Context Protocol server, so that one dependency lives
in the optional adapter and nowhere else. Fewer moving parts is the point: a
tool that audits other people's release process should have almost none of
its own.

**No browser.** The Apple developer pages that render with JavaScript have a
plain data source underneath at `developer.apple.com/tutorials/data/<page>.json`,
which returns the full body text to a plain fetch. The App Review Guidelines
page and Google's policy pages are server-rendered. A page that still comes
back too short or without its heading is marked unreadable, and every rule
resting on it becomes "not checked yet". The failure is the evidence; there
is no fallback machinery.

**No Java.** An Android app bundle's manifest is protobuf and needs Google's
bundletool, but every Android build also produces an APK, whose manifest is a
small binary XML that a hand-written decoder reads. The decoder is validated
on every run by a cross-check: the built manifest must agree with the source
manifest. Bundletool is used when `java` happens to be present; it is never
required.

**Usage evidence from the binary, never from source.** The stores never see
source, and neither does okkok. Whether an app really uses the camera,
location or a login is read from the compiled Android code's string pool
(class descriptors such as `Landroid/location/Location;`) and from the iOS
executable's load commands and selectors. Obfuscation renames an app's own
classes, never the platform classes it references, so the scan survives it.
"Linked" and "referenced" stay separate facts, because a linked framework is
not proof of use. With no binary present, every usage question is reported as
unverified, in those words.

**Command line first, model adapter last.** The engine is a command with
JSON in and JSON out. Any model, script or CI job can drive it, and the Model
Context Protocol adapter is one thin file exposing the same commands. The
deterministic half never needs a model at all.

**Rules in TOML, everything else in JSON.** People write rules, so they get
comments and multi-line strings. Records, facts and the grid are written by
the tool, so they get JSON.

**One stage per store, the most advanced evidence wins.** An earlier draft
tracked a set of stages with version comparisons. One question matters: how
far has this app got. A newer build on disk than the released one is a fact to
show, not a second stage.

**A judgement is discarded when the facts it saw have changed.** Each
recorded answer carries a fingerprint of the facts it was given. A new build
or a changed listing invalidates it, and the question is asked again.

**Conservative on rule-page changes.** A reworded heading or a cosmetic edit
trips the fingerprint and the heading check. That is the right direction: the
tool flags, and a person re-accepts with the previous and current text in
front of them.

**The report is generated, never edited.** The page carries the grid's
fingerprint and `okkok check` re-renders and compares byte for byte.
Drift between a page and its data is the failure this guards against.

## Prior art

Searched before building. Found: an iOS-only shell script with hashed
guideline fingerprints and an optional model pass (it stores Apple's quotes
and reads source); fastlane's `precheck` for App Store metadata (its list of
listing-text checks is borrowed); a privacy-manifest analyser; Google's
bundletool (used as-is when present); and commercial binary analysers, which
confirm the binary-first premise. Nothing found combined both stores,
binary-first reading, stage scoping, a rule corpus holding no policy text,
provenance enforced by a failing build, and a swappable model layer.

## Record shapes

- **Rule-page record** (`okkok/corpus/<store>/*.json`): `id`, `store`,
  `url`, `expected_heading`, an anchor for a section of a longer page,
  `fetched_at`, `sha256` of the normalised text, `paraphrase`, at most one
  `quote` of 200 characters, `status` in verified, stale, unreadable,
  wrong-page, quote-mismatch, unfetched. Review metadata records who
  paraphrased and who checked it.
- **Fact** (`probes.json`): `id`, `value` or null with an `error` saying why,
  `source` (file, url or command, with a reference and a hash where there is
  one), `observed_at`, `provenance`. Provenance is one of verified-directly,
  sub-agent-reported, inferred, needs-console-read, needs-device-test.
- **Rule** (`okkok/rules/*.toml`): `id`, `store` (apple, google, both),
  `title`, `corpus` (the records it rests on), `consumes` (the facts it
  needs), `kind` (mechanical with a `check`, or judgement with a `question`),
  `stages`, `severity` (fail, risk, note), optional `applies_when`,
  `effective_from` and `readiness`.
- **Grid row** (`grid.json`): the rule, its verdict (PASS, FAIL, RISK,
  UNKNOWN, PENDING, NOTE, RESOLVED, N/A), exactly one provenance marker,
  evidence in one sentence, the facts used, the rule pages' status, the
  crosswalk to the other store, and the action derived for it. A row whose
  rule pages are not verified cannot be PASS or FAIL. A row without exactly
  one provenance marker fails the build.
- **Judgement** (`judgements.jsonl`): rule, verdict, evidence of at least
  twenty characters, who, when, and the fingerprint of the facts it saw.
  Provenance is forced to sub-agent-reported.
- **Resolution** (`resolution-log.jsonl`, append-only): what the finding was,
  what changed, the proof, the guard that stops it coming back, the residual
  risk, who. RESOLVED shows only while the check still passes; a regression
  flips the row back and names the entry.

## Stage detection

Evidence in order, the most advanced wins, per store:

1. Source markers present: a manifest or an Info.plist, with the package or
   bundle identifier read from them.
2. The newest built artefact whose identifier matches. Foreign artefacts are
   noted and ignored.
3. The store's public endpoint: Apple's lookup returning a result means
   public; Play's details page returning 200 with a real heading means public
   and 404 means not. A network failure is recorded as needing a console read.
4. A console, only with credentials: a TestFlight build or a Play track means
   internal beta; a review state means in review.

The person running the audit can state a later stage with `--stated-stage`.
It only ever raises the stage, and the page labels it as a statement, never
as an observation.

## The rule-page pipeline and its traps

1. Plain fetch with a desktop user agent, redirects followed, the final
   address kept. Apple's design and documentation pages are read from their
   JSON endpoint; everything else through the HTML parser, taking the article
   body and stripping survey widgets and other per-request noise.
2. **Empty page.** Fewer than 150 characters or no heading means unreadable.
3. **Wrong page.** The heading must equal the expected heading and the final
   address must stay on the record's host and path.
4. **Quotes.** Every quote must be an exact substring of the cached text, so
   a record can never carry words the page does not.
5. **Sections.** Guideline pages are sliced by their section anchors, with
   nested sections cut out, so a record fingerprints one section and not the
   whole page.
6. **Indexes.** Google's policy centre is itself a record; the sweep lists
   every policy it links and the adversarial pass names any without a record.
7. **Future dates.** A rule's `effective_from` is judged against the run's
   `--as-of`; before it, the row shows as starting later.

A changed fingerprint marks the record stale. `corpus accept` shows the
previous and current text before rewriting the record. The full page text
lives in a local cache that is never committed.

## The adversarial pass

It verifies every quotation in every judgement against the cached rule text,
lists records that are stale, unreadable or on the wrong page, lists records
no rule cites, names guideline sections and index policies without a record,
lists paraphrases not yet accepted, and hands back every judgement row with
its raw text for a second opinion. It is run as a matter of course, not when
something looks wrong.
