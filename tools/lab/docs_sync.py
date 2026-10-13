"""Mirror the game docs into docs/*.md and report what changed.

    python -m lab.docs_sync

Rule changes ship as docs edits (the Slay Queen update did), so the 4-hourly
refresh runs this and every change is kept in data/docs_changes/<time>.diff.
"""

from __future__ import annotations

import datetime as dt
import difflib
import re
import sys
import urllib.request

from .common import DATA, ROOT

SITE = "https://game.battlecode.au"
DOCS = ROOT / "docs"
CHANGES = DATA / "docs_changes"


def fetch(path: str) -> str:
    req = urllib.request.Request(SITE + path, headers={"User-Agent": "weneedmoretokens-lab/1.0"})
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")


def to_markdown(html: str) -> str:
    from bs4 import BeautifulSoup
    from markdownify import markdownify

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "svg", "nav", "header", "footer"]):
        tag.decompose()
    body = soup.find("article") or soup.find("main") or soup
    text = markdownify(str(body), heading_style="ATX")
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def pages() -> list[str]:
    index = fetch("/docs")
    found = sorted(set(re.findall(r'href="/docs/([a-z0-9-]+)"', index)))
    return found


def sync(quiet: bool = False) -> list[str]:
    DOCS.mkdir(exist_ok=True)
    changed = []
    diffs = []
    names = pages()
    for name in names:
        new = to_markdown(fetch(f"/docs/{name}"))
        path = DOCS / f"{name}.md"
        old = path.read_text(encoding="utf-8") if path.is_file() else ""
        if old.strip() != new.strip():
            # Re-wrapped lines are not rule changes: only flag a page whose words changed.
            if " ".join(old.split()) != " ".join(new.split()):
                changed.append(name)
            diffs.append("".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                                      f"a/{name}.md", f"b/{name}.md")))
            path.write_text(new, encoding="utf-8")
    known = {p.stem for p in DOCS.glob("*.md")}
    missing = sorted(known - set(names) - {"updates"})
    if diffs:
        CHANGES.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        (CHANGES / f"{stamp}.diff").write_text("\n".join(diffs), encoding="utf-8")
    if not quiet:
        print(f"docs: {len(names)} pages, changed: {changed or 'none'}"
              + (f", no longer listed: {missing}" if missing else ""))
    return changed


if __name__ == "__main__":
    sync()
    sys.exit(0)
