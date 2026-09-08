# Changelog

## Unreleased

Found by installing from GitHub into a clean environment, auditing two public
open-source Android apps, an adversarial review of every check, and a
first-time user following the README.

- A run without a local rule-page cache relies on the shipped verification
  and says so; before, a fresh install judged nothing offline.
- No check fails an app for input it was not given, or on a scan that admits
  it may miss things: those are open questions naming what to add, or risks.
  Applies to background location, tracking, account deletion, iOS background
  modes, listed SDKs and the privacy policy heading (now recognised in many
  languages).
- An empty listing file no longer passes the listing rules; a rule for one
  store is never ruled out by the other store's facts; a resolution shows as
  fixed only over a passing check; absent console answers are unread, not no.
- Release builds with obfuscated resource names now yield the app's icon and
  display name, through a reader for the APK resource table.
- The page lists the rule pages it cites with their addresses, states the
  positive findings as well as the negative, says why each judgement question
  is asked, and names only places that exist: no library error text, no
  guessed file paths.
- An empty directory exits at once instead of after the page sweep; the store
  lookups say they are by identifier; the adversarial command summarises the
  paraphrase state in one line.
- Dead earlier definitions of rewritten checks removed.

## 0.1.0 — 2026-09-08

First public release.

- Probes for Android (source manifest, Gradle, APK binary manifest, compiled
  code string pool, optional AAB) and iOS (Info.plist, entitlements,
  provisioning profile, privacy manifests, Mach-O load commands and
  selectors), the store listing file, the app's own texts, the app icon, the
  public store endpoints, and read-only App Store Connect and Play Console
  readers.
- Stage detection per store from evidence, with a stated stage the person
  running the audit can add, labelled as a statement.
- 88 rules from the App Review Guidelines, Apple's design and privacy
  requirements and the Play Developer Program Policies; 113 rule-page records
  with fingerprints and reviewed paraphrases; a crosswalk of 103 Apple–Google
  pairs.
- A grid where every row carries exactly one provenance marker, judgements
  that expire when facts change, a resolution log, an adversarial pass, and
  fix proposals derived from the app's own facts.
- A generated report with a fixed structure, plain words, one colour per
  status, the app's icon, and exports carried inside the page.
- A command-line interface with JSON in and out, and an optional Model
  Context Protocol adapter.
