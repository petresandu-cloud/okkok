# Launch kit

Drafts only. Nothing here is sent or posted by the tool; a person does that,
on the dates in the calendar, after the three preconditions hold:

1. `pip install okkok` works from PyPI.
2. The site is live at a real domain with the sample report and the change feed.
3. At least one open-source maintainer has received their audit and replied.

## Calendar

| When | Hook | The post | The check to lead with |
|---|---|---|---|
| Late August, yearly | Google's target API deadline (31 August) | "Your update will be refused next week. Here is the one line that fixes it." | `google.target-api` |
| Mid September, yearly | Apple's iOS release and the review-queue crunch | "Before you submit for the new iOS: the six rejections that spike every September." | `apple.purpose-strings-say-why`, `apple.2.1.demo-account-for-login` |
| When a rule changes | The change feed logs it | "Apple changed [page] today. Here is what it means for your app, in plain words." | whichever rules rest on the page |
| 1 November 2026 | Play's extension window for the target level closes | "Last call." | `google.target-api` |
| 27 January 2027 | Play's minimum-scope fine-location declaration becomes mandatory | "The form opens in November; this is what it will ask, checked against your build." | `google.location-scope-declaration` |

## Where

- Show HN, once, with the sample report as the link and the change feed as the second paragraph.
- Product Hunt, the same week, with the social preview as the gallery image.
- r/iOSProgramming, r/androiddev, r/FlutterDev, r/reactnative: one post each, tailored to that community's most common rejection, never the same text twice.
- The Flutter, Expo and Codemagic communities: the build-agnostic angle.

The posts are in `posts.md`. The maintainer letters are in `outreach.md`.
