#!/usr/bin/env python3
"""Claude Code Statusline — 2-line status with ANSI colors.

Line 1: Model (colored by limit pressure), context bar, remaining tokens,
         session cost (clickable OSC8 link), duration.
Line 2: 5h limit bar + reset countdown, weekly % + per-model sub-limits (O/S/H),
         1d/7d/30d costs, 7-day sparkline.

Three-tier responsive layout:
  ultra   (<80 cols) — no bars, minimal separators
  compact (80-119)   — 6-char bars
  full    (120+)     — 10-char bars

Color coding: green <60%, yellow 60-79%, red 80-89%, red+blink >=90%.

Dependencies: ccusage (bun install -g ccusage)
Config:       ~/.claude/statusline.toml (optional)
Cache:        /tmp/claude-statusline/

Homepage:     https://github.com/anthropics-users/claude-code-statusline
"""

import sys, json, os, subprocess, time, fcntl, shutil, signal
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ═══════════════════════ CONFIG ═══════════════════════

CACHE_DIR = Path("/tmp/claude-statusline")
CTX_BUFFER_200K = 33_000  # Buffer for 200k window; scales proportionally for larger windows
LIMITS_TTL = 900           # 15 min
CCUSAGE_TTL = 60           # 60 sec
PRICING_TTL = 86400        # 24h for dynamic pricing
REQ_COST_WARN = 0.50       # Yellow threshold for request cost
REQ_COST_CRIT = 1.00       # Red threshold for request cost
COMPACT_COLS = 120         # Below this width, compact mode
ULTRA_COLS = 80            # Below this width, ultra-compact (no bars)
CTX_HISTORY_SIZE = 5       # Rolling window for context speed (tok/min)
LIMIT_HISTORY_SIZE = 10    # Rolling window for limit ETA forecast
SESSION_LOG_MAX = 5000     # Max entries in sessions.jsonl
LITELLM_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"

# Fallback pricing: $/MTok — used when LiteLLM cache unavailable
PRICING_FALLBACK = {
    "opus":   {"in": 5,    "out": 25,  "cw": 6.25,  "cr": 0.50},
    "sonnet": {"in": 3,    "out": 15,  "cw": 3.75,  "cr": 0.30},
    "haiku":  {"in": 1,    "out": 5,   "cw": 1.25,  "cr": 0.10},
}
LABELS = {"opus": "Opus 4.6", "sonnet": "Sonnet 4.5", "haiku": "Haiku 4.5"}
DAYS = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}

# Configurable symbols — change for different terminals/tastes
SYM_CTX = ("◆", "◇")       # Context bar (filled, empty)
SYM_LIM = ("◼", "◻")       # Limits bar (filled, empty)
SYM_PIE = ("○", "◔", "◑", "◕", "●")  # Weekly pie (0-20, 20-40, 40-60, 60-80, 80-100)
SPARK = "▁▂▃▄▅▆▇█"         # Sparkline block elements

# ═══════════════════════ TOML CONFIG ═══════════════════════

def load_config():
    """Load optional TOML config, override defaults. Requires tomllib (3.11+) or tomli."""
    global CTX_BUFFER_200K, LIMITS_TTL, CCUSAGE_TTL, PRICING_TTL
    global REQ_COST_WARN, REQ_COST_CRIT, COMPACT_COLS, ULTRA_COLS
    global CTX_HISTORY_SIZE, LIMIT_HISTORY_SIZE
    global SYM_CTX, SYM_LIM, SYM_PIE

    cfg_path = Path("~/.claude/statusline.toml").expanduser()
    if not cfg_path.exists():
        return

    try:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        with open(cfg_path, "rb") as f:
            cfg = tomllib.load(f)
    except Exception:
        return

    c = cfg.get("cache", {})
    CTX_BUFFER_200K = c.get("buffer_200k", CTX_BUFFER_200K)
    LIMITS_TTL = c.get("limits_ttl", LIMITS_TTL)
    CCUSAGE_TTL = c.get("ccusage_ttl", CCUSAGE_TTL)
    PRICING_TTL = c.get("pricing_ttl", PRICING_TTL)

    t = cfg.get("thresholds", {})
    REQ_COST_WARN = t.get("cost_warn", REQ_COST_WARN)
    REQ_COST_CRIT = t.get("cost_crit", REQ_COST_CRIT)
    COMPACT_COLS = t.get("compact_cols", COMPACT_COLS)
    ULTRA_COLS = t.get("ultra_cols", ULTRA_COLS)

    s = cfg.get("symbols", {})
    if "ctx" in s and len(s["ctx"]) == 2:
        SYM_CTX = tuple(s["ctx"])
    if "lim" in s and len(s["lim"]) == 2:
        SYM_LIM = tuple(s["lim"])
    if "pie" in s and len(s["pie"]) == 5:
        SYM_PIE = tuple(s["pie"])

    h = cfg.get("history", {})
    CTX_HISTORY_SIZE = h.get("ctx_size", CTX_HISTORY_SIZE)
    LIMIT_HISTORY_SIZE = h.get("limit_size", LIMIT_HISTORY_SIZE)

load_config()

# Extend PATH for bun/node installed via common managers
for p in ("~/.bun/bin", "~/.local/bin", "~/.nvm/current/bin", "/usr/local/bin"):
    expanded = os.path.expanduser(p)
    if expanded not in os.environ.get("PATH", ""):
        os.environ["PATH"] = expanded + os.pathsep + os.environ.get("PATH", "")

# ═══════════════════════ ANSI ═══════════════════════

R  = "\033[0m"    # Reset
GR = "\033[32m"   # Green
YL = "\033[33m"   # Yellow
RD = "\033[31m"   # Red
DM = "\033[2m"    # Dim
BL = "\033[5m"    # Blink

def cpct(pct, txt):
    """Colorize by percentage: green <60, yellow 60-79, red >=80, blink >=90."""
    if pct >= 90: return f"{BL}{RD}{txt}{R}"
    if pct >= 80: return f"{RD}{txt}{R}"
    if pct >= 60: return f"{YL}{txt}{R}"
    return f"{GR}{txt}{R}"

def ccost(cost, txt):
    """Colorize cost by thresholds."""
    if cost >= REQ_COST_CRIT: return f"{RD}{txt}{R}"
    if cost >= REQ_COST_WARN: return f"{YL}{txt}{R}"
    return txt

def osc8(url, txt):
    """OSC 8 clickable hyperlink (iTerm2, Kitty, WezTerm)."""
    return f"\033]8;;{url}\033\\{txt}\033]8;;\033\\"

# ═══════════════════════ HELPERS ═══════════════════════

def fmt_tok(t):
    """Format tokens: 128k, 1.9M, 21M. Smart rounding for 1-9.9M range."""
    t = max(0, int(t))
    if t >= 10_000_000:
        return f"{t // 1_000_000}M"
    if t >= 1_000_000:
        m = t / 1_000_000
        s = f"{m:.1f}".rstrip("0").rstrip(".")
        return f"{s}M"
    if t >= 1000:
        return f"{t // 1000}k"
    return str(t)

def bar(pct, fc, ec, w=10):
    """Progress bar: filled/empty chars, width."""
    pct = max(0, min(100, pct))
    f = pct * w // 100
    if pct > 0 and f == 0:
        f = 1
    return fc * f + ec * (w - f)

def pie(p):
    """Pie chart icon by percentage using SYM_PIE."""
    if p <= 20: return SYM_PIE[0]
    if p <= 40: return SYM_PIE[1]
    if p <= 60: return SYM_PIE[2]
    if p <= 80: return SYM_PIE[3]
    return SYM_PIE[4]

def sparkline(values):
    """Sparkline from numeric values using Unicode block elements."""
    if not values or all(v == 0 for v in values):
        return ""
    mn = min(values)
    mx = max(values)
    rng = mx - mn if mx > mn else 1
    return "".join(SPARK[min(7, int((v - mn) / rng * 7))] for v in values)

def fmtdur(ms):
    """Format duration: 2h14m or 14m."""
    s = max(0, int(ms)) // 1000
    h, m = s // 3600, s % 3600 // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"

def model_family(mid):
    """Detect model family from model ID."""
    mid_l = mid.lower()
    for k in PRICING_FALLBACK:
        if k in mid_l:
            return k
    return "opus"

def parse_iso(s):
    """Parse ISO 8601 to datetime (UTC). Handles Z, +00:00, fractional sec."""
    if not s or s in ("null", ""):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        # Fallback for older Python
        s2 = s.split(".")[0].rstrip("Z")
        for sep in ("+", "-"):
            idx = s2.rfind(sep)
            if idx > 10:
                s2 = s2[:idx]
                break
        try:
            return datetime.strptime(s2, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

def detect_cols():
    """Detect terminal width with safe fallbacks."""
    # Env var override (highest priority)
    for env in ("STATUSLINE_COLS", "COLUMNS"):
        v = os.environ.get(env, "")
        if v.isdigit() and int(v) > 0:
            return int(v)
    # Try /dev/tty for real terminal width (works in pipes)
    try:
        fd = os.open("/dev/tty", os.O_RDONLY)
        try:
            c = os.get_terminal_size(fd).columns
        finally:
            os.close(fd)
        return c
    except Exception:
        pass
    # Safe default (not 200!)
    return 80

# ═══════════════════════ CACHE ═══════════════════════

def is_stale(path, ttl):
    if not path.exists():
        return True
    return time.time() - path.stat().st_mtime > ttl

def try_lock(path):
    """Non-blocking exclusive lock. Returns fd or None."""
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_WRONLY)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (BlockingIOError, OSError):
        return None

def unlock(fd, path):
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        path.unlink(missing_ok=True)
    except OSError:
        pass

def rjson(path):
    """Safely read JSON from file."""
    try:
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text())
    except Exception:
        pass
    return None

def ensure(path, ttl, fn, bg_if_stale=False):
    """Ensure cache is fresh. Lock prevents concurrent refreshes.

    bg_if_stale: if True and cache exists but stale, refresh in background.
    """
    if not is_stale(path, ttl):
        return rjson(path)

    lk = path.with_suffix(".lock")

    # Clean stale locks (>120s)
    if lk.exists():
        try:
            if time.time() - lk.stat().st_mtime > 120:
                lk.unlink(missing_ok=True)
        except OSError:
            pass

    fd = try_lock(lk)
    if fd is None:
        return rjson(path)  # Another process refreshing

    if bg_if_stale and path.exists():
        # Background refresh: release lock, spawn child
        unlock(fd, lk)
        _bg_refresh(path, fn)
    else:
        # Synchronous refresh (first run or small TTL)
        try:
            fn(path)
        finally:
            unlock(fd, lk)

    return rjson(path)

def _bg_refresh(path, fn):
    """Background refresh using fork. Child refreshes and exits."""
    lk = path.with_suffix(".bglock")
    # Skip if background refresh already running
    if lk.exists():
        try:
            if time.time() - lk.stat().st_mtime < 60:
                return
        except OSError:
            pass

    try:
        lk.write_text(str(os.getpid()))
    except OSError:
        return

    pid = os.fork()
    if pid == 0:
        # Child process with hard timeout
        try:
            os.setsid()
            signal.alarm(45)  # Kill child after 45s no matter what
            fn(path)
        except Exception:
            pass
        finally:
            lk.unlink(missing_ok=True)
            os._exit(0)
    # Parent continues immediately

# ═══════════════════════ REFRESH FUNCTIONS ═══════════════════════

def get_oauth_token():
    """Get OAuth token from platform keychain or env var."""
    # Environment override (works everywhere)
    env_tok = os.environ.get("CLAUDE_OAUTH_TOKEN")
    if env_tok:
        return env_tok

    try:
        if sys.platform == "darwin":
            r = subprocess.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                capture_output=True, text=True, timeout=5)
        elif sys.platform.startswith("linux"):
            # libsecret / GNOME Keyring via secret-tool
            if not shutil.which("secret-tool"):
                return None
            r = subprocess.run(
                ["secret-tool", "lookup", "service", "Claude Code-credentials"],
                capture_output=True, text=True, timeout=5)
        else:
            return None

        if r.returncode != 0 or not r.stdout.strip():
            return None

        # Parse JSON credentials (keytar stores as JSON)
        try:
            creds = json.loads(r.stdout.strip())
            # Try top-level accessToken first, then nested claudeAiOauth
            tok = creds.get("accessToken")
            if not tok:
                oauth = creds.get("claudeAiOauth") or {}
                tok = oauth.get("accessToken")
            return tok
        except json.JSONDecodeError:
            # Might be raw token
            return r.stdout.strip() or None
    except Exception:
        return None

def refresh_limits(cf):
    """Fetch OAuth usage limits from Anthropic API."""
    try:
        token = get_oauth_token()
        if not token:
            return
        r = subprocess.run([
            "curl", "-sf", "--connect-timeout", "5", "--max-time", "10",
            "-H", f"Authorization: Bearer {token}",
            "-H", "anthropic-beta: oauth-2025-04-20",
            "https://api.anthropic.com/api/oauth/usage"
        ], capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            tmp = cf.with_suffix(".tmp")
            tmp.write_text(r.stdout)
            tmp.rename(cf)
    except Exception:
        pass

def refresh_ccusage(cf):
    """Fetch daily usage from ccusage CLI."""
    try:
        cmd = None
        if shutil.which("ccusage"):
            cmd = ["ccusage"]
        elif shutil.which("bunx"):
            cmd = ["bunx", "ccusage"]
        elif shutil.which("npx"):
            cmd = ["npx", "-y", "ccusage"]
        if not cmd:
            return

        since = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        until = datetime.now().strftime("%Y%m%d")
        args = cmd + ["daily", "--json", "--instances", "--since", since, "--until", until, "--mode", "calculate"]

        r = subprocess.run(args, capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            tmp = cf.with_suffix(".tmp")
            tmp.write_text(r.stdout)
            tmp.rename(cf)
    except Exception:
        pass

def refresh_pricing(cf):
    """Fetch model pricing from LiteLLM GitHub (24h cache)."""
    try:
        r = subprocess.run([
            "curl", "-sf", "--connect-timeout", "5", "--max-time", "10", LITELLM_URL
        ], capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            tmp = cf.with_suffix(".tmp")
            tmp.write_text(r.stdout)
            tmp.rename(cf)
    except Exception:
        pass

def get_pricing(model_id):
    """Get pricing for model_id. Dynamic from LiteLLM, fallback to PRICING_FALLBACK."""
    fam = model_family(model_id)
    fallback = PRICING_FALLBACK.get(fam, PRICING_FALLBACK["opus"])

    pc = CACHE_DIR / "pricing.json"
    data = ensure(pc, PRICING_TTL, refresh_pricing, bg_if_stale=True)
    if not data or not isinstance(data, dict):
        return fallback

    # Try exact model_id, then common variants
    m = data.get(model_id) or data.get(model_id.replace("-", "/"))
    if not m:
        return fallback

    try:
        return {
            "in": (m.get("input_cost_per_token") or 0) * 1_000_000,
            "out": (m.get("output_cost_per_token") or 0) * 1_000_000,
            "cw": (m.get("cache_creation_input_token_cost") or 0) * 1_000_000,
            "cr": (m.get("cache_read_input_token_cost") or 0) * 1_000_000,
        }
    except Exception:
        return fallback

# ═══════════════════════ LINE BUILDERS ═══════════════════════

def build_line1(data, tier=2):
    """Line 1: Model (colored by limit), context bar, remaining tokens, session cost, duration.

    tier: 0=ultra (<80 cols), 1=compact (80-119), 2=full (120+).
    """
    mid = data.get("model", {}).get("id", "unknown")
    fam = model_family(mid)
    ml = LABELS.get(fam, data.get("model", {}).get("display_name", "Claude"))

    # Context window
    csz = data.get("context_window", {}).get("context_window_size", 200000)
    cu = data.get("context_window", {}).get("current_usage") or {}
    cin = cu.get("input_tokens", 0)
    ccw = cu.get("cache_creation_input_tokens", 0)
    ccr = cu.get("cache_read_input_tokens", 0)

    used = cin + ccw + ccr
    buf = CTX_BUFFER_200K * csz // 200_000
    eff = max(1, csz - buf)
    pct = min(100, used * 100 // eff)
    remaining = max(0, eff - used)

    # Colorize model name by its sub-limit pressure
    ml_display = ml
    lim_cache = rjson(CACHE_DIR / "limits.json")
    if lim_cache:
        sub = lim_cache.get(f"seven_day_{fam}", {})
        if sub:
            ml_display = cpct(int(sub.get("utilization", 0)), ml)
        else:
            wp = int(lim_cache.get("seven_day", {}).get("utilization", 0))
            ml_display = cpct(wp, ml)

    # Session cost (OSC 8 link) & duration
    sc = data.get("cost", {}).get("total_cost_usd", 0) or 0
    dms = data.get("cost", {}).get("total_duration_ms", 0) or 0
    sc_link = osc8("https://console.anthropic.com/settings/usage", f"${sc:.2f}")
    dur = f" {DM}{fmtdur(dms)}{R}" if dms > 60_000 else ""

    if tier == 0:
        line = f"{ml_display} {fmt_tok(remaining)}▼ ses:{sc_link}"
    elif tier == 1:
        ctx_bar = cpct(pct, bar(pct, SYM_CTX[0], SYM_CTX[1], 6))
        line = f"{ml_display} {ctx_bar} {fmt_tok(remaining)}▼ | ses: {sc_link}{dur}"
    else:
        ctx_bar = cpct(pct, bar(pct, SYM_CTX[0], SYM_CTX[1], 10))
        line = f"{ml_display} {ctx_bar} {fmt_tok(remaining)}▼ | ses: {sc_link}{dur}"

    return ml, line

def build_line2(tier=2):
    """Line 2: 5h limit + reset, weekly % + model sub-limits, 1d/7d/30d costs + sparkline.

    tier: 0=ultra, 1=compact, 2=full.
    """
    # ── Limits ──
    lim = ensure(CACHE_DIR / "limits.json", LIMITS_TTL, refresh_limits)

    if lim:
        h5p = int(lim.get("five_hour", {}).get("utilization", 0))
        h5r = lim.get("five_hour", {}).get("resets_at", "")

        ht = ""
        dt = parse_iso(h5r)
        if dt:
            diff = max(0, (dt - datetime.now(timezone.utc)).total_seconds())
            ht = f" {int(diff)//3600}:{int(diff)%3600//60:02d}"

        w7p = int(lim.get("seven_day", {}).get("utilization", 0))
        w7_pct = cpct(w7p, f"{w7p}%")

        subs = ""
        for fam_key, label in (("opus", "O"), ("sonnet", "S"), ("haiku", "H")):
            sub = lim.get(f"seven_day_{fam_key}", {})
            if sub:
                sp = int(sub.get("utilization", 0))
                subs += f" {cpct(sp, f'{label}:{sp}')}"
            else:
                subs += f" {DM}{label}:—{R}"

        if tier == 0:
            lim_part = f"5h:{cpct(h5p, f'{h5p}%')}{ht} wk:{w7_pct}{subs}"
        elif tier == 1:
            h5_bar = cpct(h5p, bar(h5p, SYM_LIM[0], SYM_LIM[1], 6))
            lim_part = f"5h: {h5_bar}{ht} | wk: {w7_pct}{subs}"
        else:
            h5_bar = cpct(h5p, bar(h5p, SYM_LIM[0], SYM_LIM[1], 10))
            lim_part = f"5h: {h5_bar}{ht} | wk: {w7_pct}{subs}"
    else:
        lim_part = "5h: — | wk: —"

    # ── Spending ──
    raw = ensure(CACHE_DIR / "ccusage.json", CCUSAGE_TTL, refresh_ccusage, bg_if_stale=True)
    spend_part = ""

    if raw:
        arr = []
        if isinstance(raw, list):
            arr = raw
        elif isinstance(raw, dict):
            projects = raw.get("projects")
            if projects and isinstance(projects, dict):
                for entries in projects.values():
                    arr.extend(entries)
            else:
                arr = raw.get("daily") or raw.get("data") or []

        if arr:
            today = datetime.now().strftime("%Y-%m-%d")
            d7 = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
            d30 = (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d")

            def agg_cost(from_date):
                return sum(
                    (e.get("totalCost", e.get("cost", 0)) or 0)
                    for e in arr if from_date <= e.get("date", "") <= today
                )

            dc, wc, mc = agg_cost(today), agg_cost(d7), agg_cost(d30)

            # Sparkline: daily costs for last 7 days
            spark = ""
            daily_costs = []
            for i in range(6, -1, -1):
                d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                daily_costs.append(sum(
                    (e.get("totalCost", e.get("cost", 0)) or 0)
                    for e in arr if e.get("date", "") == d
                ))
            if any(c > 0 for c in daily_costs):
                spark = f" {DM}{sparkline(daily_costs)}{R}"

            if tier == 0:
                spend_part = f" 1d:${dc:.0f} 7d:${wc:.0f} 30d:${mc:.0f}"
            else:
                spend_part = f" | 1d: ${dc:.0f} 7d: ${wc:.0f} 30d: ${mc:.0f}{spark}"
        else:
            spend_part = " | 1d: — 7d: — 30d: —" if tier >= 1 else " 1d:— 7d:— 30d:—"
    else:
        spend_part = " | 1d: — 7d: — 30d: —" if tier >= 1 else " 1d:— 7d:— 30d:—"

    return lim_part + spend_part

# ═══════════════════════ SESSION LOG ═══════════════════════

def log_session(data):
    """Append session snapshot to JSONL log. Max one entry per minute."""
    ts_f = CACHE_DIR / "session_last_ts.txt"
    try:
        if ts_f.exists():
            if time.time() - float(ts_f.read_text().strip()) < 60:
                return
    except Exception:
        pass

    cost = data.get("cost", {}).get("total_cost_usd", 0) or 0
    dur = data.get("cost", {}).get("total_duration_ms", 0) or 0
    mid = data.get("model", {}).get("id", "unknown")
    tin = data.get("context_window", {}).get("total_input_tokens", 0)
    tout = data.get("context_window", {}).get("total_output_tokens", 0)

    entry = json.dumps({
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "m": model_family(mid),
        "c": round(cost, 2),
        "t": tin + tout,
        "d": dur,
        "p": Path.cwd().name,
    }, separators=(",", ":"))

    try:
        log_f = CACHE_DIR / "sessions.jsonl"
        with open(log_f, "a") as f:
            f.write(entry + "\n")
        ts_f.write_text(str(time.time()))
        # Rotate if too large
        if log_f.stat().st_size > 500_000:
            lines = log_f.read_text().splitlines()
            if len(lines) > SESSION_LOG_MAX:
                log_f.write_text("\n".join(lines[-SESSION_LOG_MAX:]) + "\n")
    except Exception:
        pass

def show_stats():
    """Show session statistics from JSONL log. Called via --stats flag."""
    log_f = CACHE_DIR / "sessions.jsonl"
    if not log_f.exists():
        print("No session log.")
        return

    entries = []
    for line in log_f.read_text().splitlines():
        try:
            entries.append(json.loads(line))
        except Exception:
            pass
    if not entries:
        print("Log empty.")
        return

    # Detect sessions: cost drops = new session boundary
    sessions = []
    cur_max_cost = 0
    for e in entries:
        c = e.get("c", 0)
        if c < cur_max_cost * 0.5 and cur_max_cost > 0.1:
            sessions.append({"cost": cur_max_cost})
            cur_max_cost = c
        else:
            cur_max_cost = max(cur_max_cost, c)
    if cur_max_cost > 0:
        sessions.append({"cost": cur_max_cost})

    # Group entries by date
    by_date = {}
    for e in entries:
        d = e["ts"][:10]
        by_date.setdefault(d, []).append(e)

    total = sum(s["cost"] for s in sessions)
    print(f"Entries: {len(entries)} | Sessions: ~{len(sessions)} | Total: ${total:.0f}")
    print()

    for d in sorted(by_date.keys())[-7:]:
        day_e = by_date[d]
        max_c = max(e.get("c", 0) for e in day_e)
        max_t = max(e.get("t", 0) for e in day_e)
        projs = set(e.get("p", "?") for e in day_e)
        print(f"  {d}: ${max_c:.0f} | {fmt_tok(max_t)} | prj: {', '.join(sorted(projs))}")

# ═══════════════════════ MAIN ═══════════════════════

def prewarm_caches():
    """Parallel refresh of missing caches on first run. Lazy import to avoid overhead."""
    caches = [
        (CACHE_DIR / "pricing.json", PRICING_TTL, refresh_pricing),
        (CACHE_DIR / "limits.json", LIMITS_TTL, refresh_limits),
        (CACHE_DIR / "ccusage.json", CCUSAGE_TTL, refresh_ccusage),
    ]
    jobs = [(p, fn) for p, ttl, fn in caches if is_stale(p, ttl) and not p.exists()]
    if not jobs:
        return

    from concurrent.futures import ThreadPoolExecutor

    def do_refresh(path, fn):
        lk = path.with_suffix(".lock")
        fd = try_lock(lk)
        if fd is None:
            return
        try:
            fn(path)
        finally:
            unlock(fd, lk)

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futs = [pool.submit(do_refresh, p, f) for p, f in jobs]
        for fut in futs:
            try:
                fut.result(timeout=30)
            except Exception:
                pass

def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # CLI: --stats shows session log summary
    if len(sys.argv) > 1 and sys.argv[1] == "--stats":
        show_stats()
        return

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    # Parallel prewarm on cold start (first run)
    prewarm_caches()

    # Three-tier layout detection
    cols = detect_cols()
    if cols < ULTRA_COLS:
        tier = 0
    elif cols < COMPACT_COLS:
        tier = 1
    else:
        tier = 2

    # Line 1 — model, context, session
    try:
        ml, l1 = build_line1(data, tier)
    except Exception:
        ml = data.get("model", {}).get("display_name", "Claude")
        l1 = ml

    # Line 2 — limits + spending
    try:
        l2 = build_line2(tier)
    except Exception:
        l2 = "5h: — | wk: — | 1d: — 7d: — 30d: —"

    print(l1)
    print(l2)

    # Session log (non-blocking, max 1/min)
    try:
        log_session(data)
    except Exception:
        pass

if __name__ == "__main__":
    main()
