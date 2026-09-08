# The report

The report is the product. Every run writes it, whoever runs it and for
whatever reason. Its structure and its look do not change between apps, runs
or operators. This file is the contract; `storecheck/report.py` implements
it, and `tests/test_report.py` fails the build when the page breaks it.

## Structure, always in this order

1. **Title block.** "Store Compliance Check", the app's name, the run date and
   time in words, the build identifiers read (Android version and code, iOS
   version and build), and where the app stands with each store in one
   sentence.
2. **In one look.** How many findings block submission, how many will likely
   be questioned, how many are still open, how many rules are met.
3. **What blocks submission.** One entry per blocking finding, per store:
   the rule in plain words, what was found, what to do, who does it, where.
4. **What will likely be questioned.** Same shape, for risks.
5. **What still has to be checked.** Open items grouped by the kind of work
   that closes them: in the store console, by a person reading, on a phone,
   after the next build.
6. **Worth knowing.** Notes that block nothing.
7. **What meets the rules.** Collapsed list.
8. **What does not apply to this app.** Collapsed, each with its reason,
   because a wrong reason here is a missed rule.
9. **Sources and method.** The rule pages read, when, and that each was
   verified unchanged; the legend for "how we know"; the exports.

## Words

- Verdicts are sentences a stranger understands: "Blocks submission",
  "Likely to be questioned", "Not checked yet", "Starts on <date>",
  "Worth knowing", "Meets the rule", "Fixed and confirmed", "Does not apply".
- "How we know" is one of: "checked the files and pages directly",
  "a reviewer or model said so", "inferred from other facts",
  "needs a look in the store console", "needs a test on a phone".
- Every action names who (developer, build engineer, store account owner,
  a reviewer, someone who must decide) and where (a file, a console field,
  a screen).
- No tool vocabulary on the page: no probe, corpus, grid, provenance,
  sub-agent, verdict codes, rule ids in running text. Rule ids appear only
  in the small print for cross-reference.
- Numbers only where they change what the reader does.

## Look

- One typeface family, the reader's system sans. No web fonts.
- One accent colour for structure; state is shown by a word and a shape,
  never by colour alone.
- The layout of an inspection report: a title block, numbered sections, a
  findings list, a sources block. No hero, no cards for everything, no
  rounded-everything, no gradients, no icons as decoration.
- Print is an export: the page prints cleanly to A4 or Letter.

## Exports, always present

Download as Markdown (for a ticket or a chat), as CSV (for a spreadsheet),
as JSON (`actions.json`, for a program or an agent), and print to PDF. All
are generated from the same `grid.json`; the page itself is generated and
carries the data's hash, and `storecheck check` fails if it was edited.
