#!/usr/bin/env bash
# Install BOUNCER pre-commit hook (Linux / WSL / macOS).
# Run once from the repo root: bash tools/install-hooks.sh
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
SRC="$REPO_ROOT/tools/bouncer/hooks/pre-commit"
DST="$REPO_ROOT/.git/hooks/pre-commit"

if [ ! -f "$SRC" ]; then
  echo "hook source missing: $SRC" >&2
  exit 1
fi

cp -f "$SRC" "$DST"
chmod +x "$DST"

echo "BOUNCER hook installed at $DST"
echo ""
echo "smoke test: add a new .py file outside tools/ and try to commit. The commit should be blocked."
echo "to clear: python tools/bouncer/bouncer.py propose --name <feat> --files <path> --spec <spec.md>"
