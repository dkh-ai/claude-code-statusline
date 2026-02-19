#!/usr/bin/env bash
# Claude Code Statusline — Uninstaller
set -euo pipefail

INSTALL_DIR="$HOME/.claude"
SCRIPT_NAME="statusline.py"
SETTINGS_FILE="$INSTALL_DIR/settings.json"
CACHE_DIR="/tmp/claude-statusline"

GREEN='\033[32m'
YELLOW='\033[33m'
DIM='\033[2m'
RESET='\033[0m'

info() { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${YELLOW}!${RESET} $*"; }

echo ""
echo "  Claude Code Statusline — Uninstaller"
echo "  ─────────────────────────────────────"
echo ""

# ── 1. Remove script ──
if [ -f "$INSTALL_DIR/$SCRIPT_NAME" ]; then
    rm "$INSTALL_DIR/$SCRIPT_NAME"
    info "Removed $INSTALL_DIR/$SCRIPT_NAME"
else
    warn "$INSTALL_DIR/$SCRIPT_NAME not found (already removed?)"
fi

# Also remove legacy .sh name
if [ -f "$INSTALL_DIR/statusline.sh" ]; then
    rm "$INSTALL_DIR/statusline.sh"
    info "Removed legacy $INSTALL_DIR/statusline.sh"
fi

# ── 2. Remove statusLine from settings.json ──
if [ -f "$SETTINGS_FILE" ]; then
    if python3 -c "
import json
with open('$SETTINGS_FILE') as f:
    d = json.load(f)
if 'statusLine' in d:
    del d['statusLine']
    with open('$SETTINGS_FILE', 'w') as f:
        json.dump(d, f, indent=2)
        f.write('\n')
" 2>/dev/null; then
        info "Removed statusLine from $SETTINGS_FILE"
    fi
fi

# ── 3. Remove TOML config (if exists) ──
if [ -f "$INSTALL_DIR/statusline.toml" ]; then
    rm "$INSTALL_DIR/statusline.toml"
    info "Removed $INSTALL_DIR/statusline.toml"
fi

# ── 4. Remove cache ──
if [ -d "$CACHE_DIR" ]; then
    rm -rf "$CACHE_DIR"
    info "Removed cache $CACHE_DIR"
fi

echo ""
info "Uninstall complete. Restart Claude Code to apply."
echo ""
