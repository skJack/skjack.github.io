#!/usr/bin/env python3
"""Refresh the Google Scholar "Cited by" chips in index.html.

Each existing <a class="cites"> chip is matched to a row of the public Scholar
profile by normalized paper title. The site is committed and pushed only when a
number actually changed, and only from a clean checkout of master.

    python3 .github/scripts/update_citations.py            # update, commit, push
    python3 .github/scripts/update_citations.py --dry-run  # print what would change
"""
import datetime
import html
import os
import re
import subprocess
import sys

PROFILE = "https://scholar.google.com/citations?user=r9_7F_EAAAAJ&hl=en&cstart=0&pagesize=100"
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def log(msg):
    print(f"{datetime.datetime.now():%Y-%m-%d %H:%M} {msg}", flush=True)


def run(*cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def git(*args):
    return run("git", "-C", REPO, *args)


def norm(title):
    """Case- and punctuation-insensitive title key."""
    return re.sub(r"[^a-z0-9]", "", html.unescape(re.sub(r"<[^>]+>", "", title)).lower())


def scholar_rows():
    """{normalized title: (citations, cites cluster ids)} from the public profile page."""
    page = run("curl", "-sfL", "--max-time", "30", "-A", UA,
               "-H", "Accept-Language: en-US,en;q=0.9", PROFILE)
    rows = {}
    for chunk in page.split('<tr class="gsc_a_tr"')[1:]:
        title = re.search(r'class="gsc_a_at"[^>]*>(.*?)</a>', chunk, re.S)
        count = re.search(r'<a([^>]*)class="gsc_a_ac[^"]*"([^>]*)>(\d*)</a>', chunk)
        if not title or not count:
            continue
        ids = re.search(r"cites=([\d,]+)", count.group(1) + count.group(2))
        rows[norm(title.group(1))] = (int(count.group(3) or 0), ids.group(1) if ids else None)
    return rows


def update(page, rows):
    """Return (new page, list of human-readable changes)."""
    changes = []

    def fix(article):
        art = article.group(0)
        title = re.search(r'<h3 class="pub-title">(.*?)</h3>', art, re.S)
        chip = re.search(r'<a class="cites"[^>]*>Cited by <b>(\d+)</b></a>', art)
        if not title or not chip:
            return art
        name = html.unescape(title.group(1))[:60]
        if norm(title.group(1)) not in rows:
            log(f"WARN no Scholar entry matches: {name}")
            return art
        new, ids = rows[norm(title.group(1))]
        old = int(chip.group(1))
        if new == old:
            return art
        if new < old / 2:  # a halving is far more likely a parsing glitch than real
            log(f"WARN kept {old}, Scholar now says {new}: {name}")
            return art
        fixed = chip.group(0).replace(f"<b>{old}</b>", f"<b>{new}</b>")
        if ids:
            fixed = re.sub(r"cites=[\d,]+", f"cites={ids}", fixed)
        changes.append(f"{name}: {old} -> {new}")
        return art.replace(chip.group(0), fixed)

    page = re.sub(r'<article class="pub">.*?</article>', fix, page, flags=re.S)
    if changes:
        month = datetime.date.today().strftime("%b %Y")
        page = re.sub(r"Google Scholar citations, [A-Z][a-z]{2} \d{4}",
                      f"Google Scholar citations, {month}", page)
    return page, changes


def main(dry_run):
    rows = scholar_rows()
    if len(rows) < 5:
        log(f"ERROR only {len(rows)} Scholar rows parsed (captcha or layout change); nothing changed")
        return 1
    if not dry_run:
        if git("rev-parse", "--abbrev-ref", "HEAD").strip() != "master" or git("status", "--porcelain").strip():
            log("ERROR checkout is not a clean master; nothing changed")
            return 1
        git("pull", "-q", "--ff-only", "origin", "master")
    path = os.path.join(REPO, "index.html")
    with open(path, encoding="utf-8") as f:
        page, changes = update(f.read(), rows)
    if not changes:
        log(f"OK no changes ({len(rows)} Scholar rows)")
        return 0
    if dry_run:
        log("DRY RUN would update: " + "; ".join(changes))
        return 0
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    git("commit", "-q", "-m", "Update Google Scholar citation counts", "--", "index.html")
    git("push", "-q", "origin", "HEAD:master")
    log("PUSHED " + "; ".join(changes))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main("--dry-run" in sys.argv))
    except subprocess.CalledProcessError as e:
        log(f"ERROR {' '.join(e.cmd[:3])} failed: {(e.stderr or '').strip()[:300]}")
        sys.exit(1)
