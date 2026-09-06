"""The rule corpus: where each rule page lives and a fingerprint of what it said.

A record never holds the store's text. It holds the address, the heading the
page must carry, when it was last read, a hash of its normalised text, our own
paraphrase of the obligation, and at most one short quote. The full text goes
to .cache/, which is never committed. When the hash stops matching, the record
is stale and every rule resting on it stops being trusted until someone reads
the page again and accepts the change with the diff in front of them.
"""

from __future__ import annotations

import difflib
import html.parser
import json
import re
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

from .schema import now_iso, read_json, sha256_of_text, write_json

STATUSES = ("verified", "stale", "unreadable", "wrong-page", "quote-mismatch", "unfetched")
UA = "Mozilla/5.0 (X11; Linux x86_64) storecheck"
MIN_TEXT = 150
MAX_QUOTE = 200

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus"
CACHE_DIR = ROOT / ".cache" / "corpus"


# ----------------------------------------------------------------- normalising

def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    t = t.replace("­", "").replace("​", "").replace("‑", "-").replace("–", "-").replace("—", "-")
    t = t.replace(" ", " ")
    return re.sub(r"\s+", " ", t).strip()


# ----------------------------------------------------------------- readers
# Each reader returns (heading, blocks). A block is (level, text); level 0 is a
# paragraph, 1..6 a heading. Anchors slice on headings.

class _HTML(html.parser.HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "noscript", "svg", "button"}
    BLOCK = {"p", "li", "td", "th", "div", "section", "article", "pre", "blockquote", "dd", "dt", "tr", "br"}

    def __init__(self):
        super().__init__()
        self.blocks: list[tuple[int, str]] = []
        self.buf: list[str] = []
        self.level = 0
        self.skip = 0
        self.h1 = None
        self.in_h1 = False

    def flush(self):
        t = normalise("".join(self.buf))
        if t:
            self.blocks.append((self.level, t))
        self.buf = []
        self.level = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.flush()
            self.level = int(tag[1])
            if tag == "h1" and self.h1 is None:
                self.in_h1 = True
        elif tag in self.BLOCK:
            self.flush()

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if tag == "h1" and self.in_h1:
                self.h1 = normalise("".join(self.buf))
                self.in_h1 = False
            self.flush()
        elif tag in self.BLOCK:
            self.flush()

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)


def read_html(body: str) -> tuple[str | None, list[tuple[int, str]]]:
    p = _HTML()
    p.feed(body)
    p.flush()
    return p.h1, p.blocks


def read_apple_json(body: str) -> tuple[str | None, list[tuple[int, str]]]:
    """Apple's design and documentation pages ship their content as JSON under /tutorials/data/."""
    d = json.loads(body)
    title = d.get("metadata", {}).get("title")
    blocks: list[tuple[int, str]] = []

    def inline(node) -> str:
        if isinstance(node, str):
            return node
        if isinstance(node, dict):
            if node.get("type") in ("text", "codeVoice"):
                return node.get("text", node.get("code", ""))
            if "inlineContent" in node:
                return "".join(inline(c) for c in node["inlineContent"])
            return ""
        if isinstance(node, list):
            return "".join(inline(c) for c in node)
        return ""

    def walk(node):
        if isinstance(node, dict):
            t = node.get("type")
            if t == "heading":
                blocks.append((int(node.get("level", 2)), normalise(node.get("text", ""))))
                return
            if t == "paragraph":
                blocks.append((0, normalise(inline(node.get("inlineContent", [])))))
                return
            if t in ("unorderedList", "orderedList"):
                for item in node.get("items", []):
                    for c in item.get("content", []):
                        walk(c)
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(d.get("primaryContentSections", []))
    walk(d.get("sections", []))
    return title, [b for b in blocks if b[1]]


def apple_json_url(url: str) -> str | None:
    m = re.match(r"https://developer\.apple\.com/(design/[^?#]+|documentation/[^?#]+)", url)
    if not m:
        return None
    return "https://developer.apple.com/tutorials/data/" + m.group(1).rstrip("/") + ".json"


# ----------------------------------------------------------------- fetching

def fetch_url(url: str, timeout: int = 30) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.geturl()


def canonical_url(url: str, base: str) -> str:
    """Absolute, without query or fragment, and with Google's &amp; noise gone."""
    url = html.unescape(url)
    if url.startswith("/"):
        m = re.match(r"(https?://[^/]+)", base)
        url = m.group(1) + url
    elif not url.startswith("http"):
        return ""
    return url.split("?")[0].split("#")[0].rstrip("/")


def index_links(body: str, base: str) -> list[dict]:
    """The policies an index page points at: title and canonical address, one entry per address."""
    seen, out = set(), []
    for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', main_content(body), re.S):
        title = normalise(re.sub(r"<[^>]+>", "", text))
        url = canonical_url(href, base)
        if not url or "/answer/" not in url or not title or url in seen:
            continue
        seen.add(url)
        out.append({"title": title, "url": url})
    return out


def slice_anchor(blocks: list[tuple[int, str]], anchor: str) -> list[tuple[int, str]] | None:
    """From the heading equal to the anchor up to the next heading of the same or a higher level."""
    a = normalise(anchor).lower()
    for i, (lvl, text) in enumerate(blocks):
        if lvl and text.lower() == a:
            out = [blocks[i]]
            for lvl2, text2 in blocks[i + 1:]:
                if lvl2 and lvl2 <= lvl:
                    break
                out.append((lvl2, text2))
            return out
    return None


class _Element(html.parser.HTMLParser):
    """Return the inner HTML of the first element that satisfies `match(tag, attrs)`."""
    VOID = {"br", "img", "meta", "link", "input", "hr", "source", "wbr", "area", "base", "col", "embed", "param", "track"}

    # HTML lets these close themselves when a sibling opens; the guideline page relies on it.
    IMPLICIT = {"li", "p", "dt", "dd", "tr", "td", "th", "option"}

    def __init__(self, match):
        super().__init__()
        self.match = match
        self.depth = None
        self.start = None
        self.end = None
        self.stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        if self.depth is not None and self.depth > 0 and tag in self.IMPLICIT and self.stack and self.stack[-1] == tag:
            self.handle_endtag(tag)   # the sibling closes the open one
            if self.depth is None or self.depth < 0:
                return
        if self.depth is None:
            if self.match(tag, dict(attrs)):
                self.depth = 1
                self.stack = [tag]
                self.start = self.getpos()
                self.start_len = len(self.get_starttag_text())
        elif self.depth > 0:
            self.depth += 1
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.depth is None or self.depth < 0 or tag in self.VOID:
            return
        # close up to the matching open tag, tolerating unclosed inner elements
        if tag in self.stack:
            while self.stack:
                t = self.stack.pop()
                self.depth -= 1
                if t == tag:
                    break
        if self.depth == 0:
            self.end = self.getpos()
            self.depth = -1  # done


def _offset(body: str, pos) -> int:
    line, col = pos
    return sum(len(l) + 1 for l in body.split("\n")[:line - 1]) + col


def element_html(body: str, match) -> str | None:
    p = _Element(match)
    p.feed(body)
    if p.start is None:
        return None
    a = _offset(body, p.start) + p.start_len
    b = _offset(body, p.end) if p.end else len(body)
    return body[a:b]


def main_content(body: str) -> str:
    """The page's own article, leaving navigation, search boxes and feedback widgets out.
    Preference: <article>, then an element with role=main, then <main>, then the body.
    Widgets that carry per-request numbers (surveys, search boxes) are dropped by id."""
    for m in (lambda t, a: t == "article", lambda t, a: a.get("role") == "main", lambda t, a: t == "main"):
        inner = element_html(body, m)
        if inner and len(inner) > 200:
            return strip_widgets(inner)
    return strip_widgets(body)


NOISE_IDS = ("article-survey-container", "search", "feedback")


def strip_widgets(html_text: str) -> str:
    for nid in NOISE_IDS:
        while True:
            m = re.search(r'<[a-z0-9]+\b[^>]*\bid="' + re.escape(nid) + r'(?:-[a-z]+)?"', html_text)
            if not m:
                break
            inner = element_html(html_text[m.start():], lambda t, a: True)
            if inner is None:
                break
            end = html_text.find(inner, m.start()) + len(inner)
            close = html_text.find(">", end)
            html_text = html_text[:m.start()] + html_text[close + 1:]
    return html_text


def slice_anchor_id(body: str, anchor_id: str) -> str | None:
    """Some pages mark sections with an id and a sidebar name instead of a heading tag.
    Take the element carrying the id, minus any nested sections that carry their
    own sidebar name, so a parent section holds only its own words."""
    frag = element_html(body, lambda t, a: a.get("id") == anchor_id)
    if frag is None:
        return None
    while True:
        inner = element_html(frag, lambda t, a: "data-sidenav" in a)
        if inner is None:
            break
        m = re.search(r'<[a-z0-9]+\b[^>]*\bdata-sidenav="', frag)
        end = frag.find(inner, m.start()) + len(inner)
        close = frag.find(">", end)
        frag = frag[:m.start()] + frag[close + 1:]
    return frag


def same_site(record_url: str, final_url: str) -> bool:
    def key(u):
        m = re.match(r"https?://([^/]+)(/[^?#]*)?", u)
        return (m.group(1), (m.group(2) or "/").split("/")[1]) if m else (None, None)
    return key(record_url) == key(final_url)


def fetch(record: dict) -> dict:
    """Read the page, update the cache, and return the record with a fresh status.

    The record's paraphrase and quote are never touched here; only the
    fields that describe what was observed.
    """
    url = record["url"]
    json_url = apple_json_url(url)
    try:
        if json_url:
            status, body, final = fetch_url(json_url)
            method = "apple-json"
            if status != 200:
                status, body, final = fetch_url(url)
                method = "html"
        else:
            status, body, final = fetch_url(url)
            method = "html"
    except Exception as e:
        record.update({"status": "unreadable", "fetched_at": now_iso(), "note": f"fetch failed: {e}"})
        return record

    if method == "apple-json":
        heading, blocks = read_apple_json(body)
    else:
        heading, _ = read_html(body)          # the h1 may sit outside the article
        if not heading:                        # some pages have none; the title tag names them
            t = re.search(r"<title>(.*?)</title>", body, re.S)
            heading = normalise(re.split(r" [-|] ", html.unescape(t.group(1)))[0]) if t else None
        _, blocks = read_html(main_content(body))
    text_all = " ".join(t for _, t in blocks)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{record['id']}.raw").write_text(body, encoding="utf-8")

    if status != 200 or len(text_all) < MIN_TEXT or not heading:
        record.update({"status": "unreadable", "fetched_at": now_iso(), "fetch_method": method,
                       "note": f"HTTP {status}, heading {heading!r}, {len(text_all)} characters of text"})
        return record
    if not same_site(url, final) and not json_url:
        record.update({"status": "wrong-page", "fetched_at": now_iso(), "fetch_method": method,
                       "note": f"redirected off the page to {final}"})
        return record
    if normalise(record["expected_heading"]).lower() != normalise(heading).lower():
        record.update({"status": "wrong-page", "fetched_at": now_iso(), "fetch_method": method,
                       "note": f"page heading is {heading!r}, expected {record['expected_heading']!r}"})
        return record

    if record.get("kind") == "index":
        links = index_links(body, url)
        if len(links) < 5:
            record.update({"status": "unreadable", "fetched_at": now_iso(), "fetch_method": method,
                           "note": f"only {len(links)} policy links found; an index should list many"})
            return record
        record["links"] = links
        blocks = [(0, f"{l['title']} {l['url']}") for l in links]

    chosen = blocks
    if record.get("anchor_id"):
        frag = slice_anchor_id(body, record["anchor_id"])
        if frag is None:
            record.update({"status": "wrong-page", "fetched_at": now_iso(), "fetch_method": method,
                           "note": f"no element with id {record['anchor_id']!r} on the page"})
            return record
        _, chosen = read_html(frag)
    elif record.get("anchor"):
        chosen = slice_anchor(blocks, record["anchor"])
        if chosen is None:
            record.update({"status": "wrong-page", "fetched_at": now_iso(), "fetch_method": method,
                           "note": f"anchor heading {record['anchor']!r} not found on the page"})
            return record
    text = " ".join(t for _, t in chosen)
    if len(text) < MIN_TEXT // 4:
        record.update({"status": "unreadable", "fetched_at": now_iso(), "fetch_method": method,
                       "note": f"the section is only {len(text)} characters: the slice missed it"})
        return record

    cache = CACHE_DIR / f"{record['id']}.txt"
    if cache.exists():
        prev = cache.read_text(encoding="utf-8")
        if prev != text:
            (CACHE_DIR / f"{record['id']}.prev.txt").write_text(prev, encoding="utf-8")
    cache.write_text(text, encoding="utf-8")

    digest = sha256_of_text(text)
    record.update({"fetched_at": now_iso(), "fetch_method": method, "note": None})
    if record.get("quote") and normalise(record["quote"]) not in text:
        record["status"] = "quote-mismatch"
        record["observed_sha256"] = digest
        return record
    if record.get("sha256") and record["sha256"] != digest:
        record["status"] = "stale"
        record["observed_sha256"] = digest
        return record
    record["sha256"] = digest
    record.pop("observed_sha256", None)
    record["status"] = "verified"
    return record


def verify_from_cache(record: dict) -> dict:
    """No network: does the cached text still match the record? For CI."""
    cache = CACHE_DIR / f"{record['id']}.txt"
    if not cache.exists():
        record["status"] = "unfetched"
        return record
    text = cache.read_text(encoding="utf-8")
    if record.get("quote") and normalise(record["quote"]) not in text:
        record["status"] = "quote-mismatch"
    elif record.get("sha256") != sha256_of_text(text):
        record["status"] = "stale"
    else:
        record["status"] = "verified"
    return record


def accept(record: dict) -> tuple[dict, str]:
    """Adopt the cached text as the new baseline. Returns the record and the diff shown."""
    cache = CACHE_DIR / f"{record['id']}.txt"
    prev = CACHE_DIR / f"{record['id']}.prev.txt"
    text = cache.read_text(encoding="utf-8")
    diff = ""
    if prev.exists():
        diff = "\n".join(difflib.unified_diff(
            prev.read_text(encoding="utf-8").split(". "), text.split(". "),
            fromfile="previous", tofile="current", lineterm=""))
    record["sha256"] = sha256_of_text(text)
    record.pop("observed_sha256", None)
    record["status"] = "verified" if not record.get("quote") or normalise(record["quote"]) in text else "quote-mismatch"
    return record, diff


# ----------------------------------------------------------------- records on disk

def assert_record(r: dict) -> None:
    for f in ("id", "store", "url", "expected_heading", "paraphrase"):
        if not r.get(f):
            raise ValueError(f"corpus record missing {f}: {r.get('id')}")
    if r["store"] not in ("apple", "google"):
        raise ValueError(f"{r['id']}: store must be apple or google")
    if r.get("quote") and len(r["quote"]) > MAX_QUOTE:
        raise ValueError(f"{r['id']}: quote longer than {MAX_QUOTE} characters; the corpus holds no policy prose")
    if r.get("status", "unfetched") not in STATUSES:
        raise ValueError(f"{r['id']}: unknown status {r['status']}")
    if r.get("kind") not in (None, "page", "index"):
        raise ValueError(f"{r['id']}: kind must be page or index")
    if r.get("paraphrase_status", "accepted") not in ("drafted", "accepted", "missing"):
        raise ValueError(f"{r['id']}: paraphrase_status must be drafted, accepted or missing")


def load_all() -> list[dict]:
    out = []
    for p in sorted(CORPUS_DIR.glob("*/*.json")):
        r = read_json(p)
        assert_record(r)
        r["_path"] = str(p)
        out.append(r)
    return out


def save(record: dict) -> None:
    path = Path(record.pop("_path"))
    write_json(path, record)
    record["_path"] = str(path)


def self_test() -> None:
    h, blocks = read_html("<html><body><nav>skip</nav><h1>Title Here</h1><p>One.</p><h2>Part A</h2><p>a1</p><h3>Sub</h3><p>a2</p><h2>Part B</h2><p>b1</p></body></html>")
    assert h == "Title Here", h
    sl = slice_anchor(blocks, "Part A")
    assert [t for _, t in sl] == ["Part A", "a1", "Sub", "a2"], sl
    assert slice_anchor(blocks, "Nope") is None
    frag = slice_anchor_id('<ul><li id="a">A text <ul><li>sub</li></ul></li><li id="b">B text</li></ul>', "a")
    assert "A text" in frag and "sub" in frag and "B text" not in frag, frag
    # unclosed list items: the next sibling closes the open one
    frag = slice_anchor_id('<ul><li id="a">A text <ul><li>s1<li>s2</ul><li id="b">B text<li id="c">C</ul>', "a")
    assert "A text" in frag and "s2" in frag and "B text" not in frag, frag
    frag = slice_anchor_id('<li data-sidenav="1" id="p">Parent words <ul><li data-sidenav="1.1" id="c">Child words</li></ul> more parent</li>', "p")
    assert "Parent words" in frag and "more parent" in frag and "Child words" not in frag, frag
    assert main_content("<body><nav>n</nav><main>" + "m" * 300 + "</main><footer>f</footer></body>").strip() == "m" * 300
    assert slice_anchor_id("<p id='x'>", "nope") is None
    ls = index_links('<main><a href="/x/answer/1?hl=en&amp;ref=2">One</a><a href="https://h/x/answer/1">dup</a><a href="/about">no</a></main>', "https://h/")
    assert ls == [{"title": "One", "url": "https://h/x/answer/1"}], ls
    assert normalise("“curly”  and non-breaking") == '"curly" and non-breaking'
    assert apple_json_url("https://developer.apple.com/design/human-interface-guidelines/privacy") == \
        "https://developer.apple.com/tutorials/data/design/human-interface-guidelines/privacy.json"
    assert apple_json_url("https://developer.apple.com/app-store/review/guidelines/") is None
    assert same_site("https://support.google.com/googleplay/android-developer/answer/1", "https://support.google.com/googleplay/android-developer/answer/1?hl=en")
    assert not same_site("https://support.google.com/googleplay/android-developer/answer/1", "https://support.google.com/")
    # Negative: a quote over the limit is refused, because the corpus holds no prose.
    try:
        assert_record({"id": "x", "store": "apple", "url": "u", "expected_heading": "h", "paraphrase": "p", "quote": "x" * 201})
    except ValueError:
        pass
    else:
        raise AssertionError("a 201-character quote must be refused")
