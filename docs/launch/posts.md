# Posts, drafts

## Show HN

**Title:** Show HN: Okkok – audits your built iOS/Android app against App Store and Play rules, and says how it knows

Two store rejections taught us that most rejections are rule failures, not code failures, and that nobody had actually read the rulebooks. So we built the reader.

Okkok takes the built package (.ipa/.app/.apk/.aab), the listing text and the declaration files, the same things the stores see, and never the source. It checks 88 rules from the App Review Guidelines, Apple's privacy requirements and the Play policies. Every finding says what was found, what to do, who does it, where, and how it knows: checked directly, a reviewer said so, inferred, needs a console read, needs a phone. A row without that marker fails the build.

It never stores the stores' text. It fingerprints 113 rule pages on every run, so a rule that changed since yesterday is caught before it is applied, and the change is published in our words: [link to the feed]. That feed is the part we are proudest of; the stores announce changes badly.

Python, standard library only. AGPL. Sample report on a real open-source app: [link]. Source: [link].

What it does not do: it does not read your code, it does not phone home, and it does not promise approval. The stores decide; this tells you where you stand before they do.

## Product Hunt

**Tagline:** OK for the App Store. OK for Google Play.

**Description:** Okkok audits the built app against both stores' rules, never the source, and says on every finding how it knows. Free and open source; a paid watch tells you when a rule that applies to your app changes.

**First comment:** the Show HN text, shortened to three paragraphs.

## r/FlutterDev

**Title:** I got rejected twice for rule failures, not code failures. So I wrote the thing that reads the rulebooks against your APK/IPA (build-agnostic, open source)

Flutter apps get rejected for the same handful of things: a purpose string that says "we need location", a background location declaration missing one of its five parts, a target API level one behind, a Data safety form that does not match what geolocator or firebase actually collect.

Okkok reads your built .apk and .ipa the way the stores do (it does not care that it is Flutter; it never reads Dart) and produces one page: what blocks submission, what will be questioned, what is still open and who can answer it. [sample report on an F-Droid app]. It is standard-library Python and AGPL; `pip install okkok`.

The bit I would want as a reader: it re-reads every rule page on every run and logs what changed. RSS here: [link].

## r/androiddev

**Title:** Open-source auditor for Play policies that reads your APK, not your source: target API, FGS types, background location, Data safety vs SDK manifests

(Lead with the foreground-service-type check and the target API deadline; those are the two most common Play refusals this year.)

## r/iOSProgramming

**Title:** 5.1.1 rejected again? An open-source check that reads your .ipa against the guidelines and tells you which purpose string is the problem

(Lead with purpose strings, privacy manifests for listed SDKs, and the demo-account rule.)
