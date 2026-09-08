#!/usr/bin/env bash
# Copyright (C) 2026 Editerra AB. SPDX-License-Identifier: AGPL-3.0-or-later
# The daily sweep: re-read every rule page, log what changed, render the feed, commit.
# A person still accepts each change with a sentence; this only records that it happened.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m okkok corpus fetch > /tmp/okkok-sweep.log 2>&1 || true   # a stale page exits 1; that is the point
python3 -m okkok changes --out site --site "${OKKOK_SITE_URL:-https://editerra.se/okkok}" >> /tmp/okkok-sweep.log 2>&1
if ! git diff --quiet -- okkok/corpus/changes.jsonl site/changes.md site/changes.xml; then
  git add okkok/corpus/changes.jsonl site/changes.md site/changes.xml
  git commit -q -m "rule pages swept $(date -u +%Y-%m-%d): $(grep -c '"accepted_at": null' okkok/corpus/changes.jsonl || echo 0) under review"
  git -c "credential.helper=!gh auth git-credential" push -q origin main
fi
# publish the site: the change feed and the rule pages, to the web host when its key is present
if [ -n "${OKKOK_SITE_HOST:-}" ]; then
  python3 tools/site.py --out site --site "${OKKOK_SITE_URL:-https://editerra.se/okkok}" >> /tmp/okkok-sweep.log 2>&1
  rsync -az --delete --exclude sample-report.html -e ssh site/ "$OKKOK_SITE_HOST" >> /tmp/okkok-sweep.log 2>&1 || true
fi
# fetched_at moves on every record; that churn is not committed
git checkout -q -- okkok/corpus/apple okkok/corpus/google 2>/dev/null || true
