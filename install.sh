#!/usr/bin/env bash
# Claude Code Statusline — Installer
# Usage: curl -sL https://raw.githubusercontent.com/USER/claude-code-statusline/main/install.sh | bash
set -euo pipefail

REPO_URL="https://raw.githubusercontent.com/USER/claude-code-statusline/main"
INSTALL_DIR="$HOME/.claude"
SCRIPT_NAME="statusline.py"
CACHE_DIR="/tmp/claude-statusline"
SETTINGS_FILE="$INSTALL_DIR/settings.json"

# Colors
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
DIM='\033[2m'
RESET='\033[0m'

info()  { echo -e "${GREEN}✓${RESET} $*"; }
warn()  { echo -e "${YELLOW}!${RESET} $*"; }
error() { echo -e "${RED}✗${RESET} $*"; }

echo ""
echo "  Claude Code Statusline — Installer"
echo "  ──────────────────────────────────"
echo ""

# ── 1. Check Python ≥3.7 ──
if ! command -v python3 &>/dev/null; then
    error "python3 not found. Please install Python 3.7+."
    exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 7 ]; }; then
    error "Python $PY_VER found, but 3.7+ is required."
    exit 1
fi
info "Python $PY_VER"

# ── 2. Ensure ~/.claude/ exists ──
mkdir -p "$INSTALL_DIR"

# ── 3. Download or copy statusline.py ──
if [ -f "$(dirname "$0")/statusline.py" ] 2>/dev/null; then
    # Local install (from cloned repo)
    cp "$(dirname "$0")/statusline.py" "$INSTALL_DIR/$SCRIPT_NAME"
    info "Copied statusline.py → $INSTALL_DIR/$SCRIPT_NAME"
else
    # Remote install (curl | bash)
    if command -v curl &>/dev/null; then
        curl -sf "$REPO_URL/statusline.py" -o "$INSTALL_DIR/$SCRIPT_NAME"
    elif command -v wget &>/dev/null; then
        wget -q "$REPO_URL/statusline.py" -O "$INSTALL_DIR/$SCRIPT_NAME"
    else
        error "Neither curl nor wget found. Please install one."
        exit 1
    fi
    info "Downloaded statusline.py → $INSTALL_DIR/$SCRIPT_NAME"
fi

chmod +x "$INSTALL_DIR/$SCRIPT_NAME"

# ── 4. Patch settings.json ──
STATUSLINE_CMD="~/.claude/$SCRIPT_NAME"
STATUSLINE_CONFIG='{"type":"command","command":"'"$STATUSLINE_CMD"'","padding":1}'

if [ -f "$SETTINGS_FILE" ]; then
    # Check if statusLine already configured
    if python3 -c "
import json, sys
with open('$SETTINGS_FILE') as f:
    d = json.load(f)
if d.get('statusLine'):
    sys.exit(0)  # already configured
sys.exit(1)
" 2>/dev/null; then
        info "settings.json already has statusLine configured"
    else
        # Add statusLine to existing settings
        python3 -c "
import json
with open('$SETTINGS_FILE') as f:
    d = json.load(f)
d['statusLine'] = {'type': 'command', 'command': '$STATUSLINE_CMD', 'padding': 1}
with open('$SETTINGS_FILE', 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
"
        info "Added statusLine to $SETTINGS_FILE"
    fi
else
    # Create new settings.json
    echo "{\"statusLine\":$STATUSLINE_CONFIG}" | python3 -m json.tool > "$SETTINGS_FILE"
    info "Created $SETTINGS_FILE with statusLine config"
fi

# ── 5. Create cache directory ──
mkdir -p "$CACHE_DIR"
info "Cache directory: $CACHE_DIR"

# ── 6. Check ccusage (optional) ──
echo ""
if command -v ccusage &>/dev/null; then
    info "ccusage found (for spending tracking)"
elif command -v bunx &>/dev/null; then
    info "bunx found — ccusage will run via bunx"
elif command -v npx &>/dev/null; then
    info "npx found — ccusage will run via npx"
else
    warn "ccusage not found. Spending data (1d/7d/30d costs) will show '—'"
    echo -e "  ${DIM}Install with: bun install -g ccusage  (or: npm install -g ccusage)${RESET}"
fi

# ── 7. Check OAuth token (optional) ──
HAS_OAUTH=false
if [ -n "${CLAUDE_OAUTH_TOKEN:-}" ]; then
    HAS_OAUTH=true
    info "OAuth token found (env var)"
elif [ "$(uname)" = "Darwin" ]; then
    if security find-generic-password -s "Claude Code-credentials" -w &>/dev/null; then
        HAS_OAUTH=true
        info "OAuth token found (macOS Keychain)"
    fi
elif command -v secret-tool &>/dev/null; then
    if secret-tool lookup service "Claude Code-credentials" &>/dev/null; then
        HAS_OAUTH=true
        info "OAuth token found (Linux Keyring)"
    fi
fi

if [ "$HAS_OAUTH" = false ]; then
    warn "OAuth token not found. Usage limits (5h/weekly) will show '—'"
    echo -e "  ${DIM}OAuth is available with Claude Max/Team plans.${RESET}"
    echo -e "  ${DIM}Set CLAUDE_OAUTH_TOKEN env var as alternative.${RESET}"
fi

# ── Done ──
echo ""
echo "  ──────────────────────────────────"
info "Installation complete!"
echo ""
echo -e "  ${DIM}Restart Claude Code to see the statusline.${RESET}"
echo -e "  ${DIM}Config: ~/.claude/statusline.toml (optional)${RESET}"
echo -e "  ${DIM}Uninstall: curl -sL $REPO_URL/uninstall.sh | bash${RESET}"
echo ""
