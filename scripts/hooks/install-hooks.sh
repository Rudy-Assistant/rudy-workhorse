#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# Install git hooks for rudy-workhorse
#
# Run from the repo root:
#   bash scripts/hooks/install-hooks.sh
#
# This copies hook scripts into .git/hooks/ and makes them
# executable.  Safe to re-run — overwrites previous versions.
# ──────────────────────────────────────────────────────────────

set -e

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
    echo "ERROR: Not inside a git repository."
    exit 1
fi

HOOKS_SRC="$REPO_ROOT/scripts/hooks"
HOOKS_DST="$REPO_ROOT/.git/hooks"

installed=0

for hook in "$HOOKS_SRC"/*; do
    # Skip this installer and any non-hook files
    basename="$(basename "$hook")"
    if [ "$basename" = "install-hooks.sh" ] || [ "$basename" = "README.md" ]; then
        continue
    fi

    cp "$hook" "$HOOKS_DST/$basename"
    chmod +x "$HOOKS_DST/$basename"
    echo "Installed: $basename"
    installed=$((installed + 1))
done

if [ "$installed" -eq 0 ]; then
    echo "No hooks found in $HOOKS_SRC"
    exit 1
fi

echo ""
echo "Done — $installed hook(s) installed to .git/hooks/"
echo "They will run automatically on every commit."
