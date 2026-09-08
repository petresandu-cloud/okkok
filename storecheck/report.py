"""The report page. Structure and words follow REPORT-PRINCIPLES.md; do not improvise here.

Everything on the page is derived from grid.json (plus the judgement and
resolution logs beside it). The page carries the grid's hash, and
storecheck check re-renders and compares bytes, so a hand edit is caught.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .schema import read_json, write_json

VERDICT_WORDS = {
    "FAIL": "Blocks submission", "RISK": "Likely to be questioned", "UNKNOWN": "Not checked yet",
    "PENDING": "Starts later", "NOTE": "Worth knowing", "PASS": "Meets the rule", "RESOLVED": "Fixed and confirmed", "N/A": "Does not apply",
}
STATUS_CLASS = {"FAIL": "s-fail", "RISK": "s-risk", "UNKNOWN": "s-open", "PENDING": "s-open", "NOTE": "s-note", "PASS": "s-met", "RESOLVED": "s-met", "N/A": "s-na"}
VERDICT_MARK = {"FAIL": "■", "RISK": "▲", "UNKNOWN": "○", "PENDING": "◷", "NOTE": "•", "PASS": "✓", "RESOLVED": "✓", "N/A": "–"}
HOW_WE_KNOW = {
    "verified-directly": "checked the files and pages directly",
    "sub-agent-reported": "a reviewer or model said so",
    "inferred": "inferred from other facts",
    "needs-console-read": "needs a look in the store console",
    "needs-device-test": "needs a test on a phone",
}
WHO = {"developer": "Developer", "build": "Build engineer", "console": "Store account owner", "reader": "A reviewer",
       "person": "Someone must decide", "device": "Tester with a phone"}
STORE = {"apple": "App Store", "google": "Google Play", "both": "Both stores"}
STAGE_WORDS = {
    None: "no app was found",
    "source-only": "source only, nothing built or uploaded",
    "built-not-uploaded": "built, not yet uploaded",
    "internal-beta": "on a test track",
    "in-review": "submitted and in review",
    "public": "published",
}

# Tool words that must not reach the page. tests/test_report.py enforces this.
MACHINE_WORDS = ("provenance", "probe", "corpus", "sub-agent", "applies_when", "verified-directly", "needs-console-read",
                 "needs-device-test", "grid.json", "toml", "jsonl", "UNKNOWN", "N/A", "PASS", "FAIL")

REPLACE = [
    (re.compile(r"\bneeds-console-read\b"), "needs a look in the store console"),
    (re.compile(r"\bneeds-device-test\b"), "needs a test on a phone"),
    (re.compile(r"\bverified-directly\b"), "checked directly"),
    (re.compile(r"\bsub-agent-reported\b"), "reported by a reviewer"),
    (re.compile(r"\bconsole read\b"), "look in the store console"),
    (re.compile(r"\bcorpus\b"), "rule pages"),
    (re.compile(r"\bprobes?\b"), "check"),
    (re.compile(r"\bthe grid\b"), "the report"),
    (re.compile(r"\bgrid\.json\b"), "the report data"),
    (re.compile(r"\bN/A\b"), "does not apply"),
    (re.compile(r"\bUNKNOWN\b"), "not checked yet"),
    (re.compile(r"\bPASS\b"), "met"),
    (re.compile(r"\bFAIL\b"), "blocking"),
    (re.compile(r"\bRISK\b"), "a risk"),
    (re.compile(r"\bstorecheck judge\b"), "the judge command"),
    (re.compile(r"\bstorecheck audit\b"), "the audit"),
    (re.compile(r"\bstorecheck/texts/\b"), "the texts folder"),
    (re.compile(r"\blisting\.toml\b"), "the listing file"),
    (re.compile(r"\bin_app\b"), "the app's own copy"),
]


def plain(text: str) -> str:
    """Tool vocabulary out, people's words in."""
    for rx, rep in REPLACE:
        text = rx.sub(rep, text)
    return text


def human_date(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    d = d.astimezone(timezone.utc)
    return d.strftime("%A %-d %B %Y, %H:%M UTC")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def grid_hash(grid_path: Path) -> str:
    return hashlib.sha256(grid_path.read_bytes()).hexdigest()


def render_text(grid_path: Path, app_name: str = "") -> str:
    grid = read_json(grid_path)
    sc = grid_path.parent
    probes = read_json(sc / "probes.json") if (sc / "probes.json").exists() else []
    by = {p["id"]: p["value"] for p in probes}
    judgements = load_jsonl(sc / "judgements.jsonl")
    e = html.escape
    h = grid_hash(grid_path)

    # ---- title block facts
    apk = by.get("android.built.manifest") or {}
    ipa = by.get("ios.built.info") or {}
    listing = by.get("listing.text") or {}
    name = listing.get("name") or ipa.get("display_name") or apk.get("label") or app_name or "the app"
    exports = export_texts(grid, name)
    builds = []
    if apk:
        builds.append(f"Android {apk.get('versionName')} (code {apk.get('versionCode')}), {apk.get('artefact')}")
    if ipa:
        builds.append(f"iOS {ipa.get('version')} (build {ipa.get('build')}), {ipa.get('artefact')}")
    icon_html = ""
    ic = by.get("app.icon") or {}
    if ic.get("file") and Path(ic["file"]).exists():
        import base64
        data = Path(ic["file"]).read_bytes()
        mime = "image/png" if data[:4] == b"\x89PNG" else "image/webp"
        icon_html = f'<img class=icon src="data:{mime};base64,{base64.b64encode(data).decode()}" alt="" width="96" height="96">'
    stage = grid["stage"]
    def stand(store, label):
        st = (stage.get("stated") or {}).get(store)
        return f"{label}: {STAGE_WORDS.get(stage.get(store))}" + (f" (stated by {st['by']}, not seen in a console)" if st else "")
    standing = f"{stand('apple', 'App Store')}. {stand('google', 'Google Play')}."

    rows = grid["rows"]
    blocks = [r for r in rows if r["verdict"] == "FAIL"]
    risks = [r for r in rows if r["verdict"] == "RISK"]
    opens = [r for r in rows if r["verdict"] in ("UNKNOWN", "PENDING")]
    notes = [r for r in rows if r["verdict"] == "NOTE"]
    met = [r for r in rows if r["verdict"] in ("PASS", "RESOLVED")]
    na = [r for r in rows if r["verdict"] == "N/A"]

    def action_html(r):
        a = r.get("action") or {}
        if not a or not a.get("do"):
            return ""
        parts = [f"<b>{e(WHO.get(a.get('who'), a.get('who', '')))}</b>"]
        if a.get("where"):
            parts.append(f"in <code>{e(a['where'])}</code>")
        if a.get("due"):
            parts.append(f"by {e(a['due'])}")
        return f"<p class=act><span class=lbl>What to do</span> {' '.join(parts)}: {e(plain(a['do']))}</p>"

    def sclass(r):
        return STATUS_CLASS.get(r["verdict"], "s-note")

    def finding(r, n=None):
        num = f"{n}. " if n else ""
        cw = ""
        if r.get("crosswalk"):
            words = {w.lower() for w in re.findall(r"[A-Za-z]{5,}", r["title"] + " " + r["evidence"])}
            scored = sorted(((len(words & {w.lower() for w in re.findall(r"[A-Za-z]{5,}", p["difference"])}), p) for p in r["crosswalk"] if p["relation"] != "same"), key=lambda x: -x[0])
            diffs = [p for s, p in scored if s >= 2][:2]
            if diffs:
                cw = "<p class=small><span class=lbl>The other store</span> " + " ".join(e(plain(p["difference"])) for p in diffs) + "</p>"
        return (f"<li class={sclass(r)}><p class=head><span class=\"status {sclass(r)}\">{e(VERDICT_WORDS[r['verdict']])}</span>{num}<b>{e(r['title'])}</b> <span class=tag>{e(STORE.get(r['store'], r['store']))}</span></p>"
                f"<p><span class=lbl>What we found</span> {e(plain(r['evidence']))}</p>"
                f"{action_html(r)}{cw}"
                f"<p class=small>How we know: {e(HOW_WE_KNOW.get(r['provenance'], r['provenance']))}. Rule reference: {e(r['id'])}.</p></li>")

    groups = [("In the store console", [r for r in opens if r["provenance"] == "needs-console-read"]),
              ("By a person reading the app's texts and screens", [r for r in opens if r["provenance"] == "verified-directly" and r["verdict"] == "UNKNOWN"]),
              ("On a phone", [r for r in opens if r["provenance"] == "needs-device-test"]),
              ("After a date", [r for r in opens if r["verdict"] == "PENDING"]),
              ("Reported and to be re-checked", [r for r in opens if r["provenance"] in ("sub-agent-reported", "inferred")])]

    def h2(title, cls):
        return f"<h2><span class=\"sw {cls}\"></span>{e(title)}</h2>"

    def section(title, items, cls, numbered=True):
        if not items:
            return f"{h2(title, cls)}<p class=none>None.</p>"
        body = "".join(finding(r, i + 1 if numbered else None) for i, r in enumerate(items))
        tag = "ol" if numbered else "ul"
        return f"{h2(title, cls)}<{tag} class=findings>{body}</{tag}>"

    def collapsed(title, items, cls, why=False):
        if not items:
            return f"{h2(title, cls)}<p class=none>None.</p>"
        lis = "".join(f"<li class={sclass(r)}><b>{e(r['title'])}</b> <span class=tag>{e(STORE.get(r['store'], r['store']))}</span>" + f"<br><span class=small>{e(plain(r['evidence']))}</span>" + "</li>" for r in items)
        return f"{h2(title, cls)}<details><summary>{len(items)} rules. Show them.</summary><ul class=plainlist>{lis}</ul></details>"

    open_html = "".join(f"<h3>{e(t)} ({len(v)})</h3><ul class=findings>" + "".join(finding(r) for r in v) + "</ul>" for t, v in groups if v) or "<p class=none>None.</p>"

    rp = grid.get("rule_pages") or {}
    n_used, n_bad = rp.get("used", 0), len(rp.get("not_verified", []))
    n_total = rp.get("total", 0)
    of_total = f" of the {n_total} the tool knows" if n_total else ""
    if rp.get("checked_here", True):
        sources = f"{n_used} rule pages from Apple and Google{of_total} are cited by the rules that apply to this app; each was checked on this machine against its fingerprint"
    else:
        when = human_date(rp["last_verified"]) if rp.get("last_verified") else "an earlier date"
        sources = (f"{n_used} rule pages from Apple and Google{of_total} are cited by the rules that apply to this app; they were relied on as last verified on {when} and were not re-read on this machine. "
                   f"Run the audit without the offline switch to re-read them")
    sources += (f", except {n_bad} that changed and are marked as not usable until re-read" if n_bad else "") + ". The stores' own text is never stored by this tool; only its address, a fingerprint, our paraphrase and, where wording binds, one verified quote."

    pages_html = ""
    if rp.get("pages"):
        items = "".join(f"<li><a href=\"{e(p['url'] or '')}\">{e(p['heading'] or p['id'])}</a> <span class=small>{e(p['id'])}</span></li>" for p in rp["pages"])
        pages_html = f"<details><summary>The {len(rp['pages'])} rule pages cited. Show them.</summary><ul class=plainlist>{items}</ul></details>"

    page = f"""<meta charset="utf-8">
<meta name="grid-sha256" content="{h}">
<meta name="grid-rows" content="{len(rows)}">
<title>Store Compliance Check: {e(name)}</title>
<style>
:root{{--ink:#141414;--muted:#5a5a5a;--rule:#cfcfcf;--accent:#1f3f6e;--paper:#fff;
  --c-fail:#a11c1c;--c-risk:#a35d00;--c-open:#2f5f9e;--c-note:#5a5a5a;--c-met:#1d6b3b;--c-na:#8a8a8a;
  --b-fail:#fbeeee;--b-risk:#fdf3e4;--b-open:#edf3fb;--b-note:#f3f3f3;--b-met:#eaf5ee}}
body{{font:16px/1.5 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--paper);max-width:900px;margin:0 auto;padding:40px 24px}}
header{{border-bottom:3px solid var(--ink);padding-bottom:16px;margin-bottom:24px}}
.titlerow{{display:flex;align-items:center;gap:18px}} .icon{{width:96px;height:96px;border:1px solid var(--rule);flex:none}}
.eyebrow{{margin:0;font-size:14px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}} h1{{font-size:40px;margin:2px 0 0;letter-spacing:-.015em;line-height:1.1}}
.when{{color:var(--muted);margin:6px 0 0}} .builds{{margin:6px 0 0;font-size:14px}} .standing{{margin:10px 0 0}}
h2{{font-size:19px;margin:36px 0 10px;padding-top:8px;border-top:1px solid var(--rule)}} h3{{font-size:16px;margin:20px 0 6px}}
.glance{{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border:1px solid var(--ink);margin-top:18px}}
.glance div{{padding:10px 12px;border-right:1px solid var(--rule);border-top:6px solid var(--muted)}} .glance div:last-child{{border-right:0}} .glance b{{display:block;font-size:26px}} .glance span{{font-size:13px;color:var(--muted)}}
.glance .s-fail{{border-top-color:var(--c-fail)}} .glance .s-fail b{{color:var(--c-fail)}} .glance .s-risk{{border-top-color:var(--c-risk)}} .glance .s-risk b{{color:var(--c-risk)}}
.glance .s-open{{border-top-color:var(--c-open)}} .glance .s-open b{{color:var(--c-open)}} .glance .s-met{{border-top-color:var(--c-met)}} .glance .s-met b{{color:var(--c-met)}}
ol.findings,ul.findings{{padding-left:0;margin:0;list-style:none}} .findings li{{padding:12px 0 14px 14px;border-bottom:1px solid var(--rule);border-left:5px solid var(--muted)}}
.findings li.s-fail{{border-left-color:var(--c-fail)}} .findings li.s-risk{{border-left-color:var(--c-risk)}} .findings li.s-open{{border-left-color:var(--c-open)}} .findings li.s-note{{border-left-color:var(--c-note)}} .findings li.s-met{{border-left-color:var(--c-met)}}
.status{{display:inline-block;font-size:12px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;padding:2px 8px;margin-right:8px;color:#fff;background:var(--muted);vertical-align:middle}}
.status.s-fail{{background:var(--c-fail)}} .status.s-risk{{background:var(--c-risk)}} .status.s-open{{background:var(--c-open)}} .status.s-note{{background:var(--c-note)}} .status.s-met{{background:var(--c-met)}} .status.s-na{{background:var(--c-na)}}
h2 .sw{{display:inline-block;width:14px;height:14px;margin-right:10px;vertical-align:-1px;background:var(--muted)}} h2 .sw.s-fail{{background:var(--c-fail)}} h2 .sw.s-risk{{background:var(--c-risk)}} h2 .sw.s-open{{background:var(--c-open)}} h2 .sw.s-note{{background:var(--c-note)}} h2 .sw.s-met{{background:var(--c-met)}} h2 .sw.s-na{{background:var(--c-na)}}
ul.plainlist li.s-met{{border-left:3px solid var(--c-met);padding-left:8px}} ul.plainlist li.s-na{{border-left:3px solid var(--c-na);padding-left:8px}}
.findings p{{margin:4px 0}} .head{{font-size:17px}} .lbl{{display:inline-block;min-width:8.5em;color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.04em}}
.act{{border-left:3px solid var(--accent);padding-left:10px}} .tag{{font-size:12px;border:1px solid var(--rule);padding:1px 6px;margin-left:6px;color:var(--muted);vertical-align:middle}}
.small{{font-size:13px;color:var(--muted)}} .none{{color:var(--muted)}} code{{font-size:13px}}
ul.plainlist{{padding-left:18px}} ul.plainlist li{{margin:6px 0}} details summary{{cursor:pointer;color:var(--accent)}}
.export-panel{{margin-top:12px;border:1px solid var(--rule);padding:10px 12px}} .export-panel textarea{{width:100%;height:220px;font:13px ui-monospace,Menlo,Consolas,monospace;border:1px solid var(--rule);padding:8px;box-sizing:border-box}} textarea[hidden]{{display:none}}
.exports a,.exports button{{display:inline-block;margin:0 10px 8px 0;padding:6px 12px;border:1px solid var(--ink);background:#fff;color:var(--ink);text-decoration:none;font:inherit;cursor:pointer}}
footer{{margin-top:36px;padding-top:12px;border-top:3px solid var(--ink);font-size:14px;color:var(--muted)}}
@media print{{*{{-webkit-print-color-adjust:exact;print-color-adjust:exact}} body{{padding:0;max-width:none}} details{{display:block}} details summary{{display:none}} .exports,.export-panel{{display:none}}}}
</style>
<header>
<div class=titlerow>{icon_html}<div>
<p class=eyebrow>Store Compliance Check</p>
<h1>{e(name)}</h1>
</div></div>
<p class=when>Run on {e(human_date(grid['built_at']))}. Rules judged as they stand on {e(grid['as_of'])}.</p>
<p class=builds>{e(' · '.join(builds)) if builds else 'No built package was read; source files only.'}</p>
<p class=standing>Where the app stands. {e(standing)}</p>
<div class=glance>
<div class=s-fail><b>{len(blocks)}</b><span>block submission</span></div>
<div class=s-risk><b>{len(risks)}</b><span>likely to be questioned</span></div>
<div class=s-open><b>{len(opens)}</b><span>still to be checked</span></div>
<div class=s-met><b>{len(met)}</b><span>rules met</span></div>
</div>
<p class=exports style="margin-top:14px"><button onclick="exportFile('grid.md','text/markdown')">Download as Markdown</button><button onclick="exportFile('grid.csv','text/csv')">Download as CSV</button><button onclick="exportFile('actions.json','application/json')">Download actions (JSON, for a program)</button><button onclick="window.print()">Print or save as PDF</button></p>
<div id=export-panel class=export-panel hidden>
<p><b id=export-name></b> <span class=small>The browser saves the file where it can. If nothing appeared, the text is below: copy it and paste it where you need it.</span></p>
<p class=exports><button onclick="copyExport()">Copy to clipboard</button><button onclick="document.getElementById('export-panel').hidden=true">Close</button> <span id=export-status class=small></span></p>
<textarea id=export-text readonly spellcheck=false></textarea>
</div>
</header>
<textarea id="x-grid.md" hidden>{e(exports['grid.md'])}</textarea>
<textarea id="x-grid.csv" hidden>{e(exports['grid.csv'])}</textarea>
<textarea id="x-actions.json" hidden>{e(exports['actions.json'])}</textarea>
<script>
function exportFile(name, type) {{
  var text = document.getElementById('x-' + name).value;
  var panel = document.getElementById('export-panel');
  document.getElementById('export-name').textContent = name;
  document.getElementById('export-status').textContent = '';
  var ta = document.getElementById('export-text');
  ta.value = text; panel.hidden = false; ta.focus(); ta.select();
  var status = document.getElementById('export-status');
  var plainSave = function () {{
    try {{
      var a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([text], {{type: type + ';charset=utf-8'}}));
      a.download = name; document.body.appendChild(a); a.click(); a.remove();
    }} catch (err) {{}}
  }};
  // A hosting viewer may refuse plain downloads and offer a save hook instead; elsewhere the browser saves the file.
  if (window.claude && typeof window.claude.use === 'function') {{
    window.claude.use('downloads').then(function (dl) {{
      if (!dl) {{ plainSave(); return; }}
      dl.save({{filename: name, data: text}}).then(function () {{ status.textContent = 'Saved.'; }},
        function (err) {{ status.textContent = err && err.code === 'declined' ? 'Not saved.' : 'Could not save here; copy the text instead.'; }});
    }}, plainSave);
  }} else plainSave();
}}
function copyExport() {{
  var ta = document.getElementById('export-text'); ta.select();
  var done = function () {{ document.getElementById('export-status').textContent = 'Copied.'; }};
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(ta.value).then(done, function () {{ document.execCommand('copy'); done(); }});
  else {{ document.execCommand('copy'); done(); }}
}}
</script>
{section("1. What blocks submission", blocks, "s-fail")}
{section("2. What will likely be questioned", risks, "s-risk")}
{h2("3. What still has to be checked", "s-open")}
{open_html}
{section("4. Worth knowing", notes, "s-note", numbered=False)}
{collapsed("5. What meets the rules", met, "s-met")}
{collapsed("6. What does not apply to this app, and why", na, "s-na", why=True)}
<footer>
<p><b>Sources and method.</b> {e(sources)}</p>
{pages_html}
<p><b>How we know</b>, on every finding: {e(HOW_WE_KNOW['verified-directly'])} · {e(HOW_WE_KNOW['sub-agent-reported'])} · {e(HOW_WE_KNOW['inferred'])} · {e(HOW_WE_KNOW['needs-console-read'])} · {e(HOW_WE_KNOW['needs-device-test'])}. An answer a reviewer or model gave is kept only while the facts it was given are unchanged.</p>
<p>This page is generated from the run's data and carries its fingerprint; editing it by hand is detected. {len(judgements)} reviewer answers are on file for this app. Made with storecheck.</p>
</footer>
"""
    return page


def render(grid_path: Path, out_path: Path, app_name: str = "") -> None:
    out_path.write_text(render_text(grid_path, app_name), encoding="utf-8")
    render_exports(grid_path, app_name)


def export_texts(grid: dict, app_name: str = "") -> dict:
    """The three exports as text: Markdown, CSV and the actions JSON. One source, the grid."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["status", "rule", "store", "what we found", "what to do", "who", "where", "how we know", "rule reference"])
    for r in grid["rows"]:
        a = r.get("action") or {}
        w.writerow([VERDICT_WORDS[r["verdict"]], r["title"], STORE.get(r["store"], r["store"]), plain(r["evidence"]), plain(a.get("do", "")), WHO.get(a.get("who"), a.get("who", "")), a.get("where", ""), HOW_WE_KNOW.get(r["provenance"], r["provenance"]), r["id"]])
    lines = [f"# Store Compliance Check: {app_name}" if app_name else "# Store Compliance Check", "", f"Run on {human_date(grid['built_at'])}. App Store: {STAGE_WORDS.get(grid['stage']['apple'])}. Google Play: {STAGE_WORDS.get(grid['stage']['google'])}.", ""]
    for title, verdicts in (("What blocks submission", ("FAIL",)), ("What will likely be questioned", ("RISK",)), ("What still has to be checked", ("UNKNOWN", "PENDING")), ("Worth knowing", ("NOTE",))):
        items = [r for r in grid["rows"] if r["verdict"] in verdicts]
        lines.append(f"## {title} ({len(items)})"); lines.append("")
        for r in items:
            a = r.get("action") or {}
            lines.append(f"- **{r['title']}** ({STORE.get(r['store'], r['store'])}). {plain(r['evidence'])}")
            if a.get("do"):
                lines.append(f"  - What to do, {WHO.get(a.get('who'), a.get('who', ''))}" + (f" in `{a['where']}`" if a.get("where") else "") + f": {plain(a['do'])}")
        lines.append("")
    met = [r for r in grid["rows"] if r["verdict"] in ("PASS", "RESOLVED")]
    lines.append(f"## Rules met ({len(met)})"); lines.append(""); lines += [f"- {r['title']}" for r in met]; lines.append("")
    actions = [{"rule": r["id"], "title": r["title"], "status": VERDICT_WORDS[r["verdict"]], "store": STORE.get(r["store"], r["store"]),
                "what_we_found": plain(r["evidence"]), "how_we_know": HOW_WE_KNOW.get(r["provenance"], r["provenance"]),
                **{k: (WHO.get(v, v) if k == "who" else plain(v) if isinstance(v, str) else v) for k, v in (r.get("action") or {}).items()}}
               for r in grid["rows"] if r["verdict"] in ("FAIL", "RISK", "NOTE", "UNKNOWN", "PENDING")]
    actions_doc = {
        "report": "Store Compliance Check", "app": app_name, "run": grid["built_at"], "run_human": human_date(grid["built_at"]),
        "standing": {"app_store": STAGE_WORDS.get(grid["stage"]["apple"]), "google_play": STAGE_WORDS.get(grid["stage"]["google"])},
        "how_to_use": "Each entry says what to do (do), who does it (who), where (where: a file, a console field, or a screen) and what was found. Act, then run the audit again; a finding shows as fixed only when its check passes.",
        "actions": actions}
    return {"grid.md": "\n".join(lines) + "\n", "grid.csv": out.getvalue(),
            "actions.json": json.dumps(actions_doc, indent=2, ensure_ascii=False) + "\n"}


def render_exports(grid_path: Path, app_name: str = "") -> None:
    grid = read_json(grid_path)
    for fname, text in export_texts(grid, app_name or grid_path.parent.parent.name).items():
        (grid_path.parent / fname).write_text(text, encoding="utf-8")


def check_render(grid_path: Path, html_path: Path, app_name: str = "") -> str | None:
    if not html_path.exists():
        return f"{html_path.name} does not exist; run render"
    if html_path.read_text(encoding="utf-8") != render_text(grid_path, app_name):
        return f"{html_path.name} is not what render produces from the current {grid_path.name}: run render, do not edit the page"
    return None
