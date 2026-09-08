# Copyright (C) 2026 Editerra AB. Okkok is a trademark of Editerra AB.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render the public site from the rules, the rule-page records and the change log.

    python3 tools/site.py [--out site] [--sample path/to/report.html]

Every page is generated: the landing page, one page per rule in the tool's own
words, the curated rejection pages, the change feed. Nothing is hand-edited and
no store text appears; a rule page shows our paraphrase and links to the store.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from okkok import changes, corpus, grid  # noqa: E402
from okkok.report import HOW_WE_KNOW, STAGE_WORDS  # noqa: E402

e = html.escape
STORE = {"apple": "App Store", "google": "Google Play", "both": "Both stores"}
SEVERITY = {"fail": ("Blocks submission", "s-fail"), "risk": ("Likely to be questioned", "s-risk"), "note": ("Worth knowing", "s-note")}
MARK = Path(__file__).resolve().parent.parent / "assets" / "okkok-mark.svg"

CSS = """
:root{--ink:#141414;--muted:#5a5a5a;--rule:#cfcfcf;--petrol:#0F5C6E;--mint:#9BE7C4;--paper:#fff;
--c-fail:#a11c1c;--c-risk:#a35d00;--c-note:#5a5a5a;--c-met:#1d6b3b}
body{font:16px/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--paper);margin:0}
.wrap{max-width:900px;margin:0 auto;padding:32px 24px}
header.top{display:flex;align-items:center;gap:14px;padding:18px 24px;border-bottom:1px solid var(--rule)}
header.top svg{width:36px;height:36px} header.top .word{font-weight:800;font-size:26px;letter-spacing:-.5px}
header.top nav{margin-left:auto;display:flex;gap:18px;font-size:15px} header.top a{color:var(--ink);text-decoration:none} header.top a:hover{text-decoration:underline}
h1{font-size:34px;line-height:1.15;margin:0 0 14px;letter-spacing:-.5px;text-wrap:balance} h2{font-size:20px;margin:36px 0 10px;padding-top:8px;border-top:1px solid var(--rule)}
.lead{font-size:20px;color:var(--muted);margin:0 0 24px;max-width:46em}
pre{background:#f4f4f4;border:1px solid var(--rule);padding:12px 14px;overflow-x:auto;font-size:14px} code{font-size:14px}
.status{display:inline-block;font-size:12px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;padding:2px 8px;color:#fff;background:var(--muted);vertical-align:middle;margin-right:8px}
.s-fail{background:var(--c-fail)} .s-risk{background:var(--c-risk)} .s-note{background:var(--c-note)}
.tag{font-size:12px;border:1px solid var(--rule);padding:1px 6px;color:var(--muted);vertical-align:middle}
ul.rules{list-style:none;padding:0} ul.rules li{padding:8px 0;border-bottom:1px solid var(--rule)} ul.rules a{color:var(--ink);text-decoration:none;font-weight:600} ul.rules a:hover{text-decoration:underline}
.lbl{display:inline-block;min-width:9em;color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.04em}
.cta{display:inline-block;background:var(--petrol);color:#fff;padding:10px 16px;text-decoration:none;font-weight:600;margin-right:10px}
.cta.alt{background:#fff;color:var(--ink);border:1px solid var(--ink)}
footer{margin-top:48px;padding:16px 24px;border-top:3px solid var(--ink);font-size:14px;color:var(--muted)}
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;margin:24px 0}
.grid3 div{border-top:4px solid var(--petrol);padding-top:10px} .grid3 b{display:block;margin-bottom:4px}
.shot{border:1px solid var(--rule);max-width:100%}
"""


def page(title: str, body: str, depth: int = 0, description: str = "") -> str:
    up = "../" * depth
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(description or title)}"><meta name="generator" content="Okkok site generator (Editerra AB)">
<link rel="alternate" type="application/rss+xml" title="Okkok: store rule changes" href="{up}changes.xml"><style>{CSS}</style></head><body>
<header class="top"><a href="{up}index.html" style="display:flex;align-items:center;gap:12px">{MARK.read_text()}<span class="word">okkok</span></a>
<nav><a href="{up}rules/index.html">Rules</a><a href="{up}rejections/index.html">Rejections</a><a href="{up}changes.html">Rule changes</a><a href="{up}sample-report.html">Sample report</a><a href="https://github.com/petresandu-cloud/okkok">GitHub</a></nav></header>
<div class="wrap">{body}</div>
<footer>Okkok is open source under the AGPL-3.0-or-later and a trademark of Editerra AB, Org.nr 559441-6454, Sweden. The stores' own text is never reproduced here; every rule links to its source page. <a href="https://github.com/petresandu-cloud/okkok/blob/main/COMMERCIAL-LICENSE.md">Commercial terms</a> · <a href="mailto:contact@editerra.se">contact@editerra.se</a></footer>
</body></html>"""


def md_to_html(md: str) -> str:
    """The change log's Markdown is simple: headings, paragraphs, links, emphasis."""
    out = []
    for block in md.split("\n\n"):
        b = block.strip()
        if not b:
            continue
        if b.startswith("## "):
            out.append(f"<h2>{_inline(b[3:])}</h2>")
        elif b.startswith("# "):
            continue
        else:
            out.append(f"<p>{_inline(b)}</p>")
    return "\n".join(out)


def _inline(t: str) -> str:
    t = e(t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", t)
    return t


def rule_page(rule: dict, recs: dict, pairs: list[dict]) -> str:
    sev, cls = SEVERITY[rule["severity"]]
    sources = "".join(f'<li><a href="{e(recs[c]["url"])}">{e(recs[c].get("expected_heading") or c)}</a>: {e(recs[c]["paraphrase"])}</li>'
                      for c in rule["corpus"] if c in recs)
    what = (f"<p><span class=lbl>What is checked</span> This rule is decided by code from the built app and the listing: "
            f"{e(', '.join(rule['consumes']))}.</p>" if rule["kind"] == "mechanical"
            else f"<p><span class=lbl>The question</span> {e(rule['question'])}</p><p class=small>A person or a model answers it from the app's texts and screens; the answer is kept only while the facts it saw are unchanged.</p>")
    stages = ", ".join(STAGE_WORDS.get(s, s) for s in rule["stages"])
    applies = f"<p><span class=lbl>Applies when</span> {e('; '.join(rule['applies_when']))}</p>" if rule.get("applies_when") else "<p><span class=lbl>Applies to</span> every app</p>"
    other = [p for p in pairs if p["apple"] in rule["corpus"] or p["google"] in rule["corpus"]]
    cross = ("<h2>The other store</h2><ul>" + "".join(f"<li>{e(p['difference'])} <span class=tag>{e(p['relation'])}</span></li>" for p in other[:4]) + "</ul>") if other else ""
    date = f"<p><span class=lbl>In force from</span> {e(rule['effective_from'])}</p>" if rule.get("effective_from") else ""
    body = f"""<p><span class="status {cls}">{e(sev)}</span><span class=tag>{e(STORE[rule['store']])}</span></p>
<h1>{e(rule['title'])}</h1>
{what}{applies}{date}<p><span class=lbl>Checked from</span> {e(stages)}</p>
<h2>The rule, in our words</h2><ul>{sources}</ul>
<p class=small>Okkok never stores the stores' text. Each item above is our paraphrase, and the link is the page it rests on, verified unchanged by fingerprint on every run.</p>
{cross}
<h2>Check your app</h2><pre>pip install git+https://github.com/petresandu-cloud/okkok
okkok audit path/to/app</pre>
<p>The report names this rule as <code>{e(rule['id'])}</code> and says what to do, who does it, where, and how it knows.</p>"""
    return page(f"{rule['title']} · Okkok", body, depth=1, description=f"{sev}: {rule['title']} ({STORE[rule['store']]}). What Okkok checks and the rule in our words.")


REJECTIONS = [
    ("apple-5-1-1-data-collection", "Rejected under Apple 5.1.1: data collection and storage",
     "The most common rejection. Apple's reviewer could not see why the app collects what it collects, or the app asked before it explained.",
     ["apple.purpose-strings-say-why", "apple.purpose-string-keys-are-real", "apple.privacy-manifest-present", "apple.account-deletion-in-app", "both.privacy-policy-reachable", "both.privacy-policy-content"]),
    ("google-background-location", "Google Play refused the background location declaration",
     "Play wants one core feature, a prominent in-app disclosure, the same words in the listing, a video, and the form. Miss one and the whole declaration is refused.",
     ["google.background-location-is-core", "google.background-location-disclosure-wording", "google.permissions-are-used", "google.restricted-permissions"]),
    ("google-target-api", "Google Play: target API level too low",
     "Every August the bar moves. An update below the required level is refused outright; an extension exists but must be requested before the deadline.",
     ["google.target-api"]),
    ("apple-2-1-demo-account", "Rejected under Apple 2.1: the reviewer could not sign in",
     "An app with a login needs a demo account that works on the day of review, in the review notes, with anything else the reviewer needs.",
     ["apple.2.1.demo-account-for-login", "google.demo-account-for-review"]),
    ("google-data-safety-mismatch", "Play's Data safety form does not match the app",
     "The form must match what the app and its SDKs actually collect. Play checks SDK manifests against it and rejects the mismatch.",
     ["google.data-safety-matches-app", "google.sdk-data-disclosed", "google.account-deletion-web-link"]),
    ("apple-privacy-manifest", "Apple: missing privacy manifest or required-reason API",
     "Every listed third-party SDK must ship a privacy manifest and the app's manifest must declare its data types and reasons.",
     ["apple.privacy-manifest-present", "apple.listed-sdk-frameworks-carry-manifests", "apple.privacy-manifest-tracking-consistent", "apple.tracking-prompt-when-tracking"]),
    ("apple-4-2-minimum-functionality", "Rejected under Apple 4.2: minimum functionality",
     "A web page in a shell, or an app that does too little, is refused. Native features and a real use are what the reviewer looks for.",
     ["apple.4.2.more-than-a-website", "apple.4.3.not-spam"]),
]


def rejection_page(slug: str, title: str, lead: str, rule_ids: list[str], rules: dict) -> str:
    items = []
    for rid in rule_ids:
        r = rules.get(rid)
        if not r:
            continue
        sev, cls = SEVERITY[r["severity"]]
        items.append(f'<li><span class="status {cls}">{e(sev)}</span><a href="../rules/{e(rid)}.html">{e(r["title"])}</a> <span class=tag>{e(STORE[r["store"]])}</span></li>')
    body = f"""<h1>{e(title)}</h1><p class=lead>{e(lead)}</p>
<h2>What Okkok checks for this</h2><ul class=rules>{''.join(items)}</ul>
<h2>How to use it</h2><p>Point Okkok at the directory holding your built package and your listing text. The report puts what blocks submission first, with what to do, who does it and where. Fix, rebuild, run again; a finding shows as fixed only when its check passes.</p>
<pre>pip install git+https://github.com/petresandu-cloud/okkok
okkok audit path/to/app</pre>
<p><a class=cta href="../sample-report.html">See a sample report</a> <a class="cta alt" href="https://github.com/petresandu-cloud/okkok">Source on GitHub</a></p>"""
    return page(f"{title} · Okkok", body, depth=1, description=lead)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site")
    ap.add_argument("--sample", default=None, help="a report.html to publish as the sample")
    ap.add_argument("--site", default="https://github.com/petresandu-cloud/okkok")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    (out / "rules").mkdir(parents=True, exist_ok=True)
    (out / "rejections").mkdir(parents=True, exist_ok=True)
    rules = {r["id"]: r for r in grid.load_rules()}
    recs = {r["id"]: r for r in corpus.load_all()}
    pairs = json.loads((Path(grid.CROSSWALK)).read_text(encoding="utf-8"))
    pairs = pairs["pairs"] if isinstance(pairs, dict) and "pairs" in pairs else pairs

    for rid, r in rules.items():
        (out / "rules" / f"{rid}.html").write_text(rule_page(r, recs, pairs), encoding="utf-8")
    by_store = {}
    for r in rules.values():
        by_store.setdefault(r["store"], []).append(r)
    sections = ""
    for st in ("apple", "google", "both"):
        lis = "".join(f'<li><span class="status {SEVERITY[r["severity"]][1]}">{e(SEVERITY[r["severity"]][0])}</span><a href="{e(r["id"])}.html">{e(r["title"])}</a></li>'
                      for r in sorted(by_store.get(st, []), key=lambda x: x["title"]))
        sections += f"<h2>{e(STORE[st])} ({len(by_store.get(st, []))})</h2><ul class=rules>{lis}</ul>"
    (out / "rules" / "index.html").write_text(page("Every rule Okkok checks", f"<h1>Every rule Okkok checks</h1><p class=lead>{len(rules)} rules from the App Review Guidelines, Apple's design and privacy requirements and the Play Developer Program Policies, each in our words, each linked to its source.</p>{sections}", depth=1), encoding="utf-8")

    rej_lis = ""
    for slug, title, lead, ids in REJECTIONS:
        (out / "rejections" / f"{slug}.html").write_text(rejection_page(slug, title, lead, ids, rules), encoding="utf-8")
        rej_lis += f'<li><a href="{slug}.html">{e(title)}</a><br><span class=small>{e(lead)}</span></li>'
    (out / "rejections" / "index.html").write_text(page("Common rejections and what to check", f"<h1>Rejected? Start here.</h1><p class=lead>The rejections developers search for most, and the checks that catch them before the reviewer does.</p><ul class=rules>{rej_lis}</ul>", depth=1), encoding="utf-8")

    entries = changes.load()
    (out / "changes.md").write_text(changes.render_markdown(entries, list(rules.values())), encoding="utf-8")
    (out / "changes.xml").write_text(changes.render_rss(entries, list(rules.values()), a.site), encoding="utf-8")
    (out / "changes.html").write_text(page("Store rule changes · Okkok", "<h1>Store rule changes</h1><p class=lead>What Apple and Google changed on the rule pages Okkok reads, in our words. <a href=\"changes.xml\">RSS</a>.</p>" + md_to_html((out / "changes.md").read_text(encoding="utf-8")), description="A feed of App Store and Google Play rule changes, in Okkok's words."), encoding="utf-8")

    (out / "sample").mkdir(exist_ok=True)
    if a.sample:
        shutil.copy(a.sample, out / "sample" / "report.html")
    if (out / "sample" / "report.html").exists():
        body = ("<h1>A sample report</h1><p class=lead>Trail Sense, an open-source Android app from F-Droid, audited as a stranger would: the package and a listing file, "
                "no source, no console keys. The report below is the file Okkok writes, unedited; open it on its own <a href=\"sample/report.html\">here</a>.</p>"
                "<iframe src=\"sample/report.html\" title=\"Okkok report for Trail Sense\" style=\"width:100%;height:80vh;border:1px solid var(--rule);background:#fff\"></iframe>")
        (out / "sample-report.html").write_text(page("Sample report · Okkok", body, description="A real Okkok report on an open-source Android app."), encoding="utf-8")
    else:
        (out / "sample-report.html").write_text(page("Sample report · Okkok", "<h1>Sample report</h1><p>Not published yet.</p>"), encoding="utf-8")

    rej_top = "".join(f'<li><a href="rejections/{slug}.html">{e(title)}</a></li>' for slug, title, _, _ in REJECTIONS[:5])
    landing = f"""<h1>OK for the App Store. OK for Google Play.</h1>
<p class=lead>Okkok audits the built app against both stores' rules, never the source, and says on every finding how it knows.</p>
<p><a class=cta href="sample-report.html">See a sample report</a> <a class="cta alt" href="https://github.com/petresandu-cloud/okkok">Install from GitHub</a></p>
<pre>pip install git+https://github.com/petresandu-cloud/okkok
okkok audit path/to/app       # writes path/to/app/okkok/report.html</pre>
<div class=grid3>
<div><b>Reads what the stores read</b>The .ipa, .app, .apk or .aab, the listing text and the declaration files. Flutter, React Native, Swift, Kotlin, Unity: all the same to it.</div>
<div><b>Says how it knows</b>Every finding carries its provenance: checked directly, a reviewer said so, inferred, needs a console read, needs a phone.</div>
<div><b>Never stores the rules' text</b>{len(recs)} rule pages are fingerprinted on every run; a change is caught before the rule is applied, and published in our words.</div>
</div>
<h2>Rejected? Start here</h2><ul class=rules>{rej_top}</ul>
<h2>What it checks</h2><p>{len(rules)} rules, each in our words and linked to its source. <a href="rules/index.html">The full list.</a></p>
<h2>When the stores change a rule</h2><p>Okkok re-reads every rule page on every run and logs what changed. <a href="changes.html">The change log</a>, with an <a href="changes.xml">RSS feed</a>.</p>
<h2>In your pipeline</h2><p>A <a href="https://github.com/petresandu-cloud/okkok/blob/main/action.yml">GitHub Action</a>, a <a href="https://github.com/petresandu-cloud/okkok/tree/main/integrations/fastlane-plugin-okkok">fastlane plugin</a>, and a Model Context Protocol server so an AI assistant can run the audit and answer the judgement questions.</p>
<h2>What it costs</h2><p>The command line is free and complete, under the AGPL. Editerra AB offers <a href="https://github.com/petresandu-cloud/okkok/blob/main/COMMERCIAL-LICENSE.md">commercial terms</a>: a watch on the rules that apply to your app, signed reports, and support.</p>"""
    (out / "index.html").write_text(page("Okkok", landing, description="Okkok audits a built iOS or Android app against the App Store and Google Play rules and says how it knows."), encoding="utf-8")
    print(f"site: {len(rules)} rule pages, {len(REJECTIONS)} rejection pages, change log with {len(entries)} entries, at {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
