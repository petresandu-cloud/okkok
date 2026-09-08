# Letters to open-source maintainers, drafts

Send before publishing any audit of their app. Plain, short, useful first.

## StreetComplete

Subject: Two things Play will refuse on StreetComplete 63.4 (with the fix)

Hi, I maintain an open-source tool that audits built Android and iOS packages against the store rules. I ran it on the F-Droid build of StreetComplete 63.4 and two findings look real; I would rather you hear them from me than from Play:

1. The APK targets API 35. Play requires 36 for updates from 31 August 2026; an extension can be requested in the console until 1 November.
2. `androidx.work.impl.foreground.SystemForegroundService` is declared with type dataSync, and the manifest does not carry `FOREGROUND_SERVICE_DATA_SYNC`. On Android 14+ that combination throws when the service starts.

The full report is attached (a single HTML file; nothing leaves your machine when you open it). If it is wrong, tell me and I will fix the tool; if it is right and you would like, I would mention the audit publicly with your OK. Either way, thank you for StreetComplete.

## Trail Sense

Subject: One thing Play may question on Trail Sense 8.2.0

Same opening. Finding: `ACCESS_BACKGROUND_LOCATION` is declared and the tool found no geofencing or background-update reference in the compiled code (which can be the shrinker hiding it). If the permission is used, the Play description needs to say location is used in the background; if it is not, Play asks that it be removed. Report attached; happy to be corrected.
