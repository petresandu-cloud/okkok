# storecheck

Does this app meet the App Store and Google Play rules, and how do we know?

Point it at an app directory. It reads what the stores read, the built package
and the files around it, never the source code and never caring what the app
was built with. It fetches the current rule pages and proves they have not
changed since they were last read. It checks every rule a machine can check
with no model involved, hands the judgement questions to whatever model you
attach, runs a second pass whose only job is to break the first, and writes
one grid where every row says how its verdict is known.

It never stores the stores' own policy text. Only a page's address, the date it
was read, a fingerprint of its text, our own paraphrase, and at most one short
quote that is verified against the live page.

Python 3.11 or later, standard library only. The optional model adapter needs
the `mcp` package.

## Use

    python3 -m storecheck corpus fetch            read the rule pages, fingerprint them
    python3 -m storecheck audit  <app>            facts, stage, grid, page
    python3 -m storecheck check  <app>            no network: grid well-formed, page generated, corpus unchanged
    python3 -m storecheck adversarial <app>       try to break the audit
    python3 -m storecheck propose <app> <rule>    a fix from this app's own facts, or a question
    python3 -m storecheck judge   <app> <rule> PASS|FAIL|RISK|NOTE "<evidence>" --by <who>
    python3 -m storecheck resolve <app> <rule> --was --changed --proof --guard --residual --by
    python3 -m storecheck rule <rule>             one rule with its rule pages' cached text
    python3 -m storecheck corpus verify|accept|list

Results go to `<app>/storecheck/`: `probes.json` (facts), `stage.json`,
`grid.json`, `report.html`, `judgements.jsonl`, `resolution-log.jsonl`. The app
keeps them; this repository keeps only rules and corpus records.

The listing text is read from `<app>/storecheck/listing.toml` until a console
is read. Console readers use the environment: `APP_STORE_CONNECT_API_KEY_ID`,
`APP_STORE_CONNECT_API_ISSUER_ID`, `APP_STORE_CONNECT_API_KEY_PATH`,
`GOOGLE_PLAY_SERVICE_ACCOUNT_JSON`. They only read.

Model adapter (MCP over stdio): `.venv/bin/python -m storecheck.mcp_server`.

## How a verdict is known

Every row and every fact carries exactly one of: `verified-directly` (the tool
read the file, ran the command, fetched the page), `sub-agent-reported` (a
model or a person said so), `inferred`, `needs-console-read`,
`needs-device-test`. A row without one fails the build. A model's judgement is
always `sub-agent-reported`, is stored with a hash of the facts it saw, and is
discarded when they change.

## What it will not do

Guess. An unresolvable value is printed as the expression it is. A page that
comes back empty is `unreadable`. A rule whose page changed is `UNKNOWN` until a
person reads the change and accepts it. A missing console read says so.

See PLAN.md for how it was built and what is next.
