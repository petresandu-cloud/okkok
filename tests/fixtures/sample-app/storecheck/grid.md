# Store Compliance Check: sample-app

Run on Tuesday 8 September 2026, 16:18 UTC. App Store: source only, nothing built or uploaded. Google Play: source only, nothing built or uploaded.

## What blocks submission (0)


## What will likely be questioned (1)

- **Every purpose-string key in Info.plist is one Apple defines** (App Store). keys Apple does not define, which iOS ignores: NSMadeUpUsageDescription
  - What to do, Developer in `/Users/ayavibe/Projects/storecheck/tests/fixtures/sample-app/ios/Runner/Info.plist`: remove the keys NSMadeUpUsageDescription; iOS ignores them, so nothing the app does depends on them

## What still has to be checked (0)


## Worth knowing (0)


## Rules met (0)


