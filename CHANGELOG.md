# Changelog

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
