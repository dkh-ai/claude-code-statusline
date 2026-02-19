# Claude Code Statusline

A rich, 2-line statusline for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) that shows model info, context usage, rate limits, and spending — right in your terminal.

```
Opus 4.6 ◆◆◆◆◆◇◇◇◇◇ 92k▼ | ses: $6.05 2h14m
5h: ◼◼◼◼◼◼◼◻◻◻ 2:14 | wk: 61% O:45 S:62 H:10 | 1d: $71 7d: $203 30d: $451 ▁▂▃▄▅▆▇
```

## Features

- **Context window** — progress bar, remaining tokens, color-coded by usage
- **Model name** — colored by its rate limit pressure (green/yellow/red/blink)
- **Session cost** — clickable link (OSC 8) to Anthropic usage dashboard
- **5-hour rate limit** — progress bar + countdown to reset
- **Weekly limit** — percentage with per-model sub-limits (Opus/Sonnet/Haiku)
- **Spending** — 1-day, 7-day, 30-day costs with 7-day sparkline chart
- **3-tier layout** — auto-adapts: full (120+ cols), compact (80-119), ultra (<80)
- **Color coding** — green <60%, yellow 60-79%, red 80-89%, red+blink ≥90%
- **Session log** — JSONL history with `--stats` summary viewer

## Quick Install

```bash
curl -sL https://raw.githubusercontent.com/dkh-ai/claude-code-statusline/main/install.sh | bash
```

Or clone and install locally:

```bash
git clone https://github.com/dkh-ai/claude-code-statusline.git
cd claude-code-statusline
bash install.sh
```

Restart Claude Code after installation.

## Manual Install

1. Copy the script:

```bash
cp statusline.py ~/.claude/statusline.py
chmod +x ~/.claude/statusline.py
```

2. Add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/statusline.py",
    "padding": 1
  }
}
```

3. Restart Claude Code.

## Requirements

| Requirement | Purpose | Required? |
|---|---|---|
| Python 3.7+ | Runs the statusline script | **Yes** |
| `curl` | Fetches OAuth limits and pricing data | **Yes** |
| [ccusage](https://github.com/ryoppippi/ccusage) | Spending data (1d/7d/30d costs) | Optional |
| OAuth (Max/Team plan) | Rate limit data (5h/weekly) | Optional |

### Installing ccusage

```bash
# Pick one:
bun install -g ccusage
npm install -g ccusage
```

Without ccusage, spending data shows "—" but everything else works.

### OAuth Token

The script reads your OAuth token automatically:

- **macOS**: from Keychain (`Claude Code-credentials`)
- **Linux**: from GNOME Keyring via `secret-tool`
- **Environment**: set `CLAUDE_OAUTH_TOKEN` as override

Without OAuth, rate limit bars show "—". OAuth is available on Claude Max and Team plans.

## Configuration

Copy the example config and customize:

```bash
cp statusline.example.toml ~/.claude/statusline.toml
```

```toml
[cache]
buffer_200k = 33000       # Context buffer in tokens
limits_ttl = 900           # OAuth cache TTL (seconds)
ccusage_ttl = 60           # ccusage cache TTL (seconds)

[thresholds]
cost_warn = 0.50           # Yellow threshold for request cost ($)
cost_crit = 1.00           # Red threshold for request cost ($)
compact_cols = 120          # Compact mode below this width

[symbols]
ctx = ["◆", "◇"]          # Context bar characters
lim = ["◼", "◻"]          # Limits bar characters
pie = ["○", "◔", "◑", "◕", "●"]  # Weekly pie icons
```

Requires Python 3.11+ (built-in `tomllib`) or `pip install tomli`. The config file is entirely optional — defaults are built into the script.

### Environment Variables

| Variable | Purpose |
|---|---|
| `CLAUDE_OAUTH_TOKEN` | OAuth token (bypasses keychain lookup) |
| `STATUSLINE_COLS` | Override terminal width detection |
| `COLUMNS` | Fallback terminal width |

## How It Works

```
stdin (JSON from Claude Code)
    │
    ├── Line 1: model name + context bar + remaining tokens + session cost + duration
    │
    └── Line 2: 5h limit bar + reset timer + weekly % + sub-limits + 1d/7d/30d costs + sparkline
```

### Data Sources

| Data | Source | Cache TTL |
|---|---|---|
| Context & model | stdin JSON (from Claude Code) | Every call |
| Model pricing | [LiteLLM](https://github.com/BerriAI/litellm) GitHub | 24 hours |
| Rate limits | Anthropic OAuth API | 15 minutes |
| Spending | ccusage CLI | 60 seconds |

### Cache

All cache files are stored in `/tmp/claude-statusline/`. To reset:

```bash
rm -rf /tmp/claude-statusline/
```

Cache rebuilds automatically on next Claude Code invocation.

## Session Statistics

View session history:

```bash
python3 ~/.claude/statusline.py --stats
```

Sessions are logged to `/tmp/claude-statusline/sessions.jsonl` (max 1 entry/minute, rotated at 5000 entries).

## Testing

### Manual test

```bash
echo '{"model":{"id":"claude-opus-4-6"},"context_window":{"context_window_size":200000,"current_usage":{"input_tokens":50000,"output_tokens":2000,"cache_creation_input_tokens":28000,"cache_read_input_tokens":50000},"total_input_tokens":140000,"total_output_tokens":22000},"cost":{"total_cost_usd":6.05,"total_duration_ms":8040000}}' | python3 statusline.py
```

Strip ANSI colors for debugging:

```bash
... | python3 statusline.py 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
```

### Unit tests

```bash
cd claude-code-statusline
python3 -m pytest tests/ -v
```

## Troubleshooting

| Problem | Solution |
|---|---|
| Statusline is blank | `chmod +x ~/.claude/statusline.py`, verify `python3` is in PATH |
| Limits show "—" | No OAuth token (API key plan), or Keychain locked |
| Spending shows "—" | ccusage not installed: `bun install -g ccusage` |
| Colors not working | Terminal doesn't support ANSI — Terminal.app and iTerm2 both work |
| Slow first run | ccusage parses JSONL files; first run can take 2-5 seconds |
| TOML config ignored | Python <3.11: install `pip install tomli` |

## Uninstall

```bash
curl -sL https://raw.githubusercontent.com/dkh-ai/claude-code-statusline/main/uninstall.sh | bash
```

Or manually:

```bash
rm ~/.claude/statusline.py
rm ~/.claude/statusline.toml  # if exists
rm -rf /tmp/claude-statusline/
# Remove "statusLine" key from ~/.claude/settings.json
```

## License

[MIT](LICENSE)
