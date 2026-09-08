# storecheck — a store-compliance verification tool for any iOS or Android app

## Context

Family Ping was rejected twice by the stores for rule failures, not code failures. On 2026-09-06 four parallel audits read the Apple and Google rulebooks and produced a 61-row grid; a second adversarial pass corrected eight verdicts, caught one fabricated quotation and found two unmapped policies. All of that was done by hand in a session. This plan builds the tool that does it repeatably, for any app, with any model, and never stores the stores' prose.

The owner's answers (2026-09-06): repository name **storecheck**; the server at `/work/projects/storecheck` is canonical and GitHub is the mirror; create the GitHub repo after the first visible step works; **the tool never reads source and is oblivious to the build technology**; and, on the first draft of this plan: **simpler is more reliable — do an adversarial pass on both the tools and the logic.**

## Adversarial pass on the first draft (2026-09-06)

Every point below was tested where a test was possible, not argued.

**Tools challenged**

| First draft said | Challenge | Outcome |
|---|---|---|
| TypeScript on Node with five packages: plist, fflate, node-html-parser, yaml, MCP SDK | Python's standard library already has all of it: `plistlib` reads XML and binary plists, `zipfile` opens APK/AAB/IPA, `html.parser` gives headings and text, `urllib` fetches, `hashlib`, `json`, `tomllib` for human-written rule files, `struct` for the binary formats, `unittest` for tests. The only non-standard need is the MCP adapter. | **Switched to Python 3.14, standard library only.** One dependency, `mcp`, and only in the adapter file. Fewer moving parts is the whole point. |
| Headless Chrome, or Playwright, to read Apple's script-rendered design pages | Tested whether the pages have a plain data source underneath. They do: `developer.apple.com/tutorials/data/<page>.json` returns the full body text (14,157 characters for the Privacy page) with a plain fetch. The App Review Guidelines page is server-rendered (118,442 characters plain). Google's help pages are server-rendered too, and a dead id returns 404 with the heading "Sorry, this page can't be found" — tested with the standard library. | **No browser at all.** A page that still comes back under 400 characters is marked `unreadable` and says so. No fallback machinery. |
| Java plus Google's bundletool jar as a required tool for Android bundles | The AAB's manifest is protobuf, which needs bundletool; the APK's manifest is a small binary XML that a hand-written decoder reads. Every Android build produces an APK, and the built-in cross-check (built manifest must agree with the source manifest) validates the decoder. | **APK read natively. AAB optional**: if `java` is on the machine bundletool is used; if not, the tool says "give me the APK" and exits 2, inconclusive. Java is never required. |
| MCP as the architecture of the model layer | MCP is a wire format. If the engine is a command with JSON in and JSON out, any model, script or CI job can drive it, and MCP becomes a thin adapter. | **Command-line JSON first**; the MCP adapter is one file, built last, optional. |
| Rules in YAML | YAML needs a package. TOML is in the standard library since 3.11 and allows comments and multi-line strings. | **Rules in TOML.** Corpus records, probes and the grid are JSON, machine-written. |
| A generated HTML page with web fonts and a filter script | The page's only job is to be read and to be provably generated from the grid. | **One template string, no fonts, no script.** The embedded hash stays; that is the guard that matters. |

**Logic challenged**

| First draft said | Challenge | Outcome |
|---|---|---|
| Stage is a *set* per store, with version comparisons between the artefact on disk and the public release | Over-built. One question matters: how far has this app got. A newer build on disk is a fact to show, not a second stage. | **One stage per store**, the most advanced evidence wins, plus one flag: "a build newer than the released one is on disk". |
| A source-reading layer per ecosystem | The owner rules it out, and the stores never see source. | **Usage evidence from the binary only**: Android class references in the compiled code's string pool, iOS linked frameworks and selectors from the executable. Proven on Family Ping today: `otool -L` shows CoreLocation linked and UserNotifications weak-linked; the compiled Android code exposes `Landroid/location/Location;` by a byte scan. Obfuscation renames the app's own classes, never the platform classes it references, so the scan survives it. "Linked" and "referenced" stay separate facts, because a linked framework is not proof of use. |
| A word list of machine terms enforced in the renderer | No real failure demanded it. The failure that happened was drift between two copies, not jargon. | **Dropped.** Plain English is a writing rule, not a gate. |
| Nine build steps | Stage detection is two HTTP calls once the probes exist; the console readers and CI are one step. | **Seven steps.** |
| Discard a model's judgement when the facts it saw have changed | Sound, small, and it is the honest behaviour. | Kept. |
| Corpus heading must match exactly, or the page is "wrong" | A store may reword a heading and trip it falsely. That is the conservative direction: it flags, a person re-accepts with the diff in front of them. | Kept. |
| Hash of the normalised page text detects a rewrite | Cosmetic edits will also trip it. Same answer: conservative, and `accept` shows the previous and current text side by side. | Kept. |

Two claims from the first draft did not survive the pass at all: that a browser is needed, and that Java is needed. Both were assumptions carried over from how the work was done by hand.

## Goal, in one paragraph

Point `storecheck` at an app directory. It works out how far along the app is (source only, built, on a test track, in review, public), reads the built Android package and iOS app the way the stores do, fetches the current rule pages and proves they have not changed since they were last read, checks every mechanical rule with no model in the loop, hands the judgement questions to whatever model is attached, runs a second pass whose only job is to break the first, and produces one grid where every row says how its verdict is known. Fix proposals come from what the binary shows this app doing, never from a template.

## Prior art — searched first

Searched GitHub and the web for open-source store-compliance tools on 2026-09-06.

| Found | What it is | Taken from it |
|---|---|---|
| berkayturk/appstore-precheck | Bash, iOS-only, reads a source directory, 55 checks, hashed guideline fingerprints, optional model pass | Confirms the hashed-fingerprint idea works. It stores Apple's quotes and reads source; we do neither. No Google Play. |
| fastlane `precheck` | Apple metadata checks via App Store Connect | Its list of listing-text checks: placeholder copy, unreachable URLs, curse words |
| crasowas privacy-manifest analyser | Shell script over privacy manifest files | Nothing beyond what this repo's own manifest check already does |
| Google `bundletool` | Official AAB reader | Used as-is when Java is present |
| AppCompliance.io, Google Checks | Commercial binary analysers | Confirm the binary-first premise |

Nothing found combines both stores, binary-first reading, stage scoping, a corpus holding no policy text, provenance enforced by a failing build, and a swappable model layer. That combination is the tool.

From this repo, method only, never Family Ping content: the exactly-one-marker guard with its zero-row trap, single-source rendering, exit code 2 for "inconclusive", self-tests that break the rule on purpose, the negation-aware claim scan, the name and emoji checks, and the declare-once triple of manifest key, purpose string and listing phrase.

## What is needed

| Need | Where from | Have / missing |
|---|---|---|
| Ubuntu server, native disk | `nas5-vsandu` → `/work/projects` (NVMe, 1.4 TB free) | have |
| Python 3.14, git, gh signed in as petresandu-cloud | server, checked 2026-09-06 | have |
| Rule pages readable without a browser | Apple JSON endpoints and server-rendered pages; Google help pages — all tested | have |
| A real app to prove each step on | Family Ping's `app-release.apk`, `app-release.aab`, `Family Ping.ipa`, `Runner.app`, source manifests, 32 pod privacy manifests, copied to `/work/fixtures/family-ping/` outside the repo | have locally, copy at step 1 |
| Store lookup as stage evidence | itunes lookup and Play details page; both tested today and both say "not public", matching reality | have |
| Console credentials, read-only | owner's existing App Store Connect key and Play service account | requested at step 7 |
| `mcp` package | pip, adapter only | step 6 |

## Decisions, recorded

- **Python 3.14, standard library only** except `mcp` in the adapter. No framework, no build step. `python3 -m unittest` for tests.
- **Usage evidence from the binary, never from source.** No binary present means every usage question is reported as unverified, in those words.
- **Audit state lives in the audited app** under `<appDir>/storecheck/`: probes, stage, grid, judgements, resolution log. The tool repo commits only rules and corpus records.
- **Corpus never holds policy prose.** A record is: id, URL, expected heading, fetch time, hash of the normalised text, our paraphrase, at most one quote of 200 characters. Full text lives in `.cache/`, never committed.
- **Console access is read-only.** Writing stays human-gated whatever the tooling can do.
- **Working method**: files authored in the session scratchpad and copied to the server with `scp`; running, testing and committing over ssh. Nothing kept on the Mac, nothing through the Samba mount.

## Repository layout

```
storecheck/
  PLAN.md                 this plan, updated as each step lands — the red thread
  storecheck/             the package
    cli.py                storecheck audit | check | corpus | render | serve  <appDir>
    schema.py             the five record shapes and their assert functions
    probes/               facts only, never verdicts; each has probe() and self_test()
      android_manifest.py   source manifest and build.gradle
      android_apk.py        binary-XML manifest decoder; AAB via bundletool when java exists
      android_dex.py        string-pool scan → capability references
      ios_plist.py          Info.plist, InfoPlist.strings, entitlements, privacy manifest, source and built
      ios_macho.py          linked frameworks and selectors → capability references
      ios_pods.py           bundled third-party privacy manifests
      store_lookup.py       itunes lookup; Play details page
      console.py            App Store Connect and Play APIs when keys are present
      listing.py            store metadata file: lengths, name rules, negation-aware claims
    capabilities.py       one table: android permission ↔ ios key ↔ dex descriptors ↔ macho symbols
    stage.py
    corpus.py             fetch, normalise, hash, quote check
    rules/                apple/*.toml, google/*.toml; checks.py holds the mechanical check functions
    grid.py               build, validate (exactly one provenance marker), render, check-render
    adversary.py          quote verification, stale and unreadable records, unmapped headings
    fix.py                app model and proposals
    mcp_server.py         the adapter, optional
  storecheck/corpus/      committed records, no prose; ships with the package
  storecheck/crosswalk/   Apple <-> Google rule pairs
  tests/                  unittest; fixtures: empty-body.html, wrong-page.html, a tiny APK, a tiny plist
  .cache/                 gitignored
```

## Record shapes

- **Corpus record**: `id, store, url, expected_heading, anchor?, fetched_at, sha256, paraphrase, quote?, status` where status ∈ verified, stale, unreadable, wrong-page, quote-mismatch.
- **Probe**: `id, value or null, source{kind(file|url|command), ref, sha256?}, observed_at, provenance, error?`. Provenance ∈ verified-directly, sub-agent-reported, inferred, needs-console-read, needs-device-test.
- **Rule** (TOML): `id, store(apple|google|both), corpus[], consumes[], kind(mechanical|judgement), check or question, stages[], effective_from?, severity(fail|risk|note)`. An `effective_from` date must appear inside one of the rule's quotes, so a moved date surfaces as `quote-mismatch`.
- **Grid row**: `id, stage, verdict(PASS|FAIL|RISK|UNKNOWN|PENDING|NOTE|RESOLVED), provenance (exactly one, or the build fails), evidence, probes[], corpus_status, judgement?, resolution?`. A row whose corpus is not `verified` cannot be PASS or FAIL; it becomes UNKNOWN naming why.
- **Judgement**: `rule, verdict, evidence, provenance forced to sub-agent-reported, by, at, probe_sha256`. A judgement whose facts have changed is discarded.
- **Resolution entry**, append-only: `n, row, date, was, choice, changed[], proof, provenance, verified_by, guard, residual_risk`. RESOLVED only while the check still passes; regression flips it back to FAIL naming the entry.

## Stage detection

Evidence in order; the most advanced wins, per store:
1. Source markers present; bundle id read from manifest and plist.
2. Newest built artefact whose bundle id matches; foreign artefacts noted and ignored.
3. Store lookup: Apple `resultCount > 0` means public; Play details page 200 with a real heading means public, 404 means not. Network failure means `needs-console-read`.
4. Console, only with credentials: TestFlight builds or Play tracks mean internal-beta; a review state means in-review.

One flag alongside: "a build newer than the released one is on disk". A source-only app gets one sentence: "Nothing built, nothing uploaded: only the source-level rules ran."

## Corpus pipeline and the traps

1. Plain fetch, desktop user agent, redirects followed, final URL kept. Apple design and documentation pages are read from their JSON endpoint; everything else through `html.parser`.
2. **Empty page**: under 400 characters or no heading ⇒ `unreadable`, and every rule citing it becomes UNKNOWN. The failure is the evidence.
3. **Wrong page**: the heading must equal `expected_heading` and the final URL must stay on the record's host and path; otherwise `wrong-page` with the heading seen.
4. **Paraphrase**: raw and normalised text go to `.cache/`; every quote must be an exact substring of the cached text. No model ever fetches a rule page.
5. **Future dates**: `effective_from` against `--as-of`: before ⇒ PENDING naming the date; after ⇒ evaluated.
6. **Hand-edited output**: the renderer is the only producer of the page and embeds the grid's hash; `check` fails when they differ.

A changed hash ⇒ `stale`; `corpus accept <id>` shows previous and current text before rewriting. CI runs `corpus verify` from cache only.

## The model interface

The engine is the command line: `storecheck audit <appDir> --json` writes probes, stage and grid; `storecheck judge <appDir> <rule> <verdict> "<evidence>"` appends a judgement with provenance forced; `storecheck adversarial <appDir> --json` returns quote mismatches, stale and unreadable records, headings no rule cites, and the judgement rows with their raw text for a second opinion; `storecheck propose <appDir> <rule> --json` returns a patch derived from the app model, or a question when a store form claims a feature the binary lacks. The MCP adapter exposes those same five commands and nothing more.

## Steps — one afternoon each, each ends with something visible on Family Ping

| # | Step | What you will see |
|---|---|---|
| 1 | Repo on the server, record shapes, source-level probes for Android manifest and iOS plists, Family Ping fixtures copied over | `storecheck audit` prints Family Ping's 9 Android permissions, targetSdk, 6 purpose strings, 8 declared data types, tracking false |
| 2 | Built-artefact probes: APK binary-XML decoder, IPA and `.app` binary plists, entitlements from the provisioning profile, bundled pod manifests; the decoder proven by agreeing with the source manifest | A source-versus-built table; `aps-environment` from the IPA on it |
| 3 | Binary usage probes and the capability table; stage detection with store lookup | Declared-versus-referenced table: CAMERA declared and the camera classes present or absent; CoreLocation linked, `requestAlwaysAuthorization` present; anything declared but never referenced flagged. `stage.json` with the evidence chain per store |
| 4 | Corpus records and fetch for the ten pages the grid cites; **GitHub repo created public here** | `corpus verify` shows every record `verified`, the Privacy design page read from JSON, and a planted dead Google id reported as `wrong-page` |
| 5 | Mechanical rules, grid build, provenance validator, renderer, render check | `grid.html` for Family Ping, about fifteen rows; then edit the page by hand and watch `storecheck check` exit 1 |
| 6 | Judgement rules, adversarial pass, fix proposals, resolution log, MCP adapter | From a model with the adapter attached: one judgement, then the adversarial pass catching a planted bad quotation; `propose` on the background-location declaration returns a question; on a purpose string returns a patch |
| 7 | Console readers, read-only, and CI | Stage upgraded by TestFlight and Play track data; `storecheck check` green on Ubuntu with no model, no browser, no Java |

## Status, 2026-09-08

All seven steps are delivered and pushed. Since then: 88 rules and 113 rule-page records, all verified, paraphrases reviewed by adversarial and fidelity passes; a crosswalk of 103 Apple-Google pairs; the report contract in `REPORT-PRINCIPLES.md`, enforced by tests, with the app's icon, one colour per status and exports carried inside the page.

Packaging: `pyproject.toml` with a `storecheck` console script; rule records and the crosswalk moved inside the package so `pip install` ships them; the cache moves to the user's cache directory when installed; README with screenshots, CONTRIBUTING, SECURITY, CHANGELOG. `--stated-stage` lets the person running the audit say the app is on a track or in review when no console keys are present; the page labels it as a statement.

Open: the licence (owner's decision); a version tag and GitHub release once the licence lands; a PyPI release if the name is wanted there.

## Verification, per step

Each step ships with its probe's or check's `--self-test`, which breaks the rule on purpose and must fail; `python3 -m unittest`; and the visible artefact above, produced from the Family Ping fixtures on the server and shown before the next step starts.

## Open items

- The pre-tool hook in this repo denies any shell command containing `git push`. The push at step 4 will be run by the owner, or the hook widened for the storecheck path at that moment; surfaced then, not worked around.
- Console credentials are requested at step 7.
