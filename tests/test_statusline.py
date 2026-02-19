"""Unit tests for statusline.py (Python 3, pytest)."""

import importlib.util
import importlib.machinery
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

# Load statusline module from project root
_script_path = str(Path(__file__).resolve().parent.parent / "statusline.py")
_loader = importlib.machinery.SourceFileLoader("statusline", _script_path)
spec = importlib.util.spec_from_loader("statusline", _loader, origin=_script_path)
sl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sl)


# ═══════════════════════ fmt_tok ═══════════════════════

class TestFmtTok:
    def test_zero(self):
        assert sl.fmt_tok(0) == "0"

    def test_small(self):
        assert sl.fmt_tok(500) == "500"

    def test_thousands(self):
        assert sl.fmt_tok(1000) == "1k"
        assert sl.fmt_tok(128000) == "128k"
        assert sl.fmt_tok(999999) == "999k"

    def test_millions_fractional(self):
        assert sl.fmt_tok(1_000_000) == "1M"
        assert sl.fmt_tok(1_900_000) == "1.9M"
        assert sl.fmt_tok(2_500_000) == "2.5M"
        assert sl.fmt_tok(9_999_999) == "10M"

    def test_millions_large(self):
        assert sl.fmt_tok(10_000_000) == "10M"
        assert sl.fmt_tok(21_000_000) == "21M"
        assert sl.fmt_tok(115_000_000) == "115M"

    def test_negative(self):
        assert sl.fmt_tok(-100) == "0"


# ═══════════════════════ bar ═══════════════════════

class TestBar:
    def test_zero(self):
        assert sl.bar(0, "█", "░", 5) == "░░░░░"

    def test_full(self):
        assert sl.bar(100, "█", "░", 5) == "█████"

    def test_half(self):
        assert sl.bar(50, "█", "░", 10) == "█████░░░░░"

    def test_min_one_filled(self):
        # >0% should show at least 1 filled char
        assert sl.bar(1, "█", "░", 10) == "█░░░░░░░░░"

    def test_over_100_clamped(self):
        assert sl.bar(150, "█", "░", 5) == "█████"

    def test_custom_chars(self):
        assert sl.bar(60, "◆", "◇", 5) == "◆◆◆◇◇"


# ═══════════════════════ pie ═══════════════════════

class TestPie:
    def test_thresholds(self):
        assert sl.pie(0) == "○"
        assert sl.pie(20) == "○"
        assert sl.pie(21) == "◔"
        assert sl.pie(40) == "◔"
        assert sl.pie(41) == "◑"
        assert sl.pie(60) == "◑"
        assert sl.pie(61) == "◕"
        assert sl.pie(80) == "◕"
        assert sl.pie(81) == "●"
        assert sl.pie(100) == "●"


# ═══════════════════════ sparkline ═══════════════════════

class TestSparkline:
    def test_basic(self):
        result = sl.sparkline([1, 2, 3, 4, 5, 6, 7, 8])
        assert len(result) == 8
        assert result[0] == "▁"
        assert result[-1] == "█"

    def test_all_same(self):
        # All same values → all should be same char (min=max, rng=1)
        result = sl.sparkline([5, 5, 5])
        assert len(result) == 3

    def test_empty(self):
        assert sl.sparkline([]) == ""
        assert sl.sparkline([0, 0, 0]) == ""

    def test_two_values(self):
        result = sl.sparkline([0, 100])
        assert result == "▁█"


# ═══════════════════════ fmtdur ═══════════════════════

class TestFmtdur:
    def test_minutes(self):
        assert sl.fmtdur(60_000) == "1m"
        assert sl.fmtdur(300_000) == "5m"

    def test_hours(self):
        assert sl.fmtdur(3_600_000) == "1h00m"
        assert sl.fmtdur(8_040_000) == "2h14m"

    def test_zero(self):
        assert sl.fmtdur(0) == "0m"

    def test_negative(self):
        assert sl.fmtdur(-1000) == "0m"


# ═══════════════════════ model_family ═══════════════════════

class TestModelFamily:
    def test_opus(self):
        assert sl.model_family("claude-opus-4-6-20250514") == "opus"

    def test_sonnet(self):
        assert sl.model_family("claude-sonnet-4-5-20250929") == "sonnet"

    def test_haiku(self):
        assert sl.model_family("claude-haiku-4-5-20251001") == "haiku"

    def test_unknown_defaults_opus(self):
        assert sl.model_family("unknown-model-x") == "opus"


# ═══════════════════════ parse_iso ═══════════════════════

class TestParseIso:
    def test_z_suffix(self):
        dt = sl.parse_iso("2026-02-14T20:30:00Z")
        assert dt.tzinfo == timezone.utc
        assert dt.hour == 20
        assert dt.minute == 30

    def test_offset(self):
        dt = sl.parse_iso("2026-02-14T20:30:00+00:00")
        assert dt is not None
        assert dt.hour == 20

    def test_none(self):
        assert sl.parse_iso(None) is None
        assert sl.parse_iso("") is None
        assert sl.parse_iso("null") is None

    def test_fractional(self):
        dt = sl.parse_iso("2026-02-14T20:30:00.123Z")
        assert dt is not None
        assert dt.hour == 20


# ═══════════════════════ detect_cols ═══════════════════════

class TestDetectCols:
    def test_env_override(self):
        with patch.dict(os.environ, {"STATUSLINE_COLS": "42"}):
            assert sl.detect_cols() == 42

    def test_columns_env(self):
        with patch.dict(os.environ, {"COLUMNS": "99"}, clear=False):
            # Remove STATUSLINE_COLS if present
            env = os.environ.copy()
            env.pop("STATUSLINE_COLS", None)
            with patch.dict(os.environ, env, clear=True):
                os.environ["COLUMNS"] = "99"
                assert sl.detect_cols() == 99

    def test_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            # /dev/tty may or may not work in test env
            result = sl.detect_cols()
            assert result > 0


# ═══════════════════════ cpct / ccost ═══════════════════════

class TestColorize:
    def test_cpct_green(self):
        result = sl.cpct(30, "30%")
        assert "32m" in result  # green
        assert "30%" in result

    def test_cpct_yellow(self):
        result = sl.cpct(65, "65%")
        assert "33m" in result  # yellow

    def test_cpct_red(self):
        result = sl.cpct(85, "85%")
        assert "31m" in result  # red
        assert "5m" not in result  # no blink

    def test_cpct_blink(self):
        result = sl.cpct(95, "95%")
        assert "5m" in result  # blink
        assert "31m" in result  # red

    def test_ccost_normal(self):
        result = sl.ccost(0.10, "$0.10")
        assert result == "$0.10"  # no color

    def test_ccost_warn(self):
        result = sl.ccost(0.50, "$0.50")
        assert "33m" in result  # yellow

    def test_ccost_crit(self):
        result = sl.ccost(1.50, "$1.50")
        assert "31m" in result  # red


# ═══════════════════════ build_line1 ═══════════════════════

class TestBuildLine1:
    MOCK_DATA = {
        "model": {"id": "claude-opus-4-6-20250514", "display_name": "Opus"},
        "context_window": {
            "context_window_size": 200000,
            "current_usage": {
                "input_tokens": 50000,
                "output_tokens": 10000,
                "cache_creation_input_tokens": 20000,
                "cache_read_input_tokens": 5000,
            },
            "total_input_tokens": 100000,
            "total_output_tokens": 30000,
        },
        "cost": {"total_cost_usd": 3.50, "total_duration_ms": 1200000},
    }

    def setup_method(self):
        """Use temp cache dir to avoid polluting real cache."""
        self._orig = sl.CACHE_DIR
        sl.CACHE_DIR = Path(tempfile.mkdtemp())

    def teardown_method(self):
        import shutil
        shutil.rmtree(sl.CACHE_DIR, ignore_errors=True)
        sl.CACHE_DIR = self._orig

    def test_returns_label_and_line(self):
        ml, line = sl.build_line1(self.MOCK_DATA)
        assert ml == "Opus 4.6"
        assert "ses:" in line
        assert "▼" in line

    def test_compact_has_bar_and_remaining(self):
        ml, line = sl.build_line1(self.MOCK_DATA, tier=1)
        assert "◆" in line or "◇" in line  # bar present
        assert "▼" in line  # remaining tokens indicator

    def test_ultra_no_bar(self):
        ml, line = sl.build_line1(self.MOCK_DATA, tier=0)
        assert "◆" not in line  # no bar
        assert "◇" not in line
        assert "▼" in line  # remaining tokens
        assert "ses:" in line

    def test_remaining_tokens(self):
        # eff = 200000 - 33000 = 167000, used = 75000, remaining = 92000
        ml, line = sl.build_line1(self.MOCK_DATA, tier=1)
        assert "92k▼" in line

    def test_duration_shown(self):
        ml, line = sl.build_line1(self.MOCK_DATA, tier=1)
        # 1200000ms = 20m
        assert "20m" in line

    def test_model_colored_by_limit(self):
        # Write limits with high opus utilization
        lim = {"seven_day": {"utilization": 50}, "seven_day_opus": {"utilization": 85}}
        (sl.CACHE_DIR / "limits.json").write_text(json.dumps(lim))
        ml, line = sl.build_line1(self.MOCK_DATA)
        # Model name should be colored red (85% >= 80%)
        assert "31m" in line  # red
        assert "Opus 4.6" in line


# ═══════════════════════ build_line2 ═══════════════════════

class TestBuildLine2:
    def setup_method(self):
        self._orig = sl.CACHE_DIR
        sl.CACHE_DIR = Path(tempfile.mkdtemp())

    def teardown_method(self):
        import shutil
        shutil.rmtree(sl.CACHE_DIR, ignore_errors=True)
        sl.CACHE_DIR = self._orig

    def test_no_limits_cache(self):
        result = sl.build_line2()
        assert "—" in result

    def test_with_limits(self):
        lim = {
            "five_hour": {"utilization": 50, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day": {"utilization": 30, "resets_at": "2099-12-31T23:59:59Z"},
        }
        (sl.CACHE_DIR / "limits.json").write_text(json.dumps(lim))
        result = sl.build_line2()
        assert "◼" in result  # 5h bar shown
        assert "30%" in result  # weekly % shown

    def test_all_model_sublimits(self):
        """All three model sub-limits are displayed."""
        lim = {
            "five_hour": {"utilization": 40, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day": {"utilization": 50, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day_opus": {"utilization": 45},
            "seven_day_sonnet": {"utilization": 62},
            "seven_day_haiku": {"utilization": 10},
        }
        (sl.CACHE_DIR / "limits.json").write_text(json.dumps(lim))
        result = sl.build_line2()
        assert "O:45" in result
        assert "S:62" in result
        assert "H:10" in result

    def test_missing_sublimits_show_dash(self):
        """Missing model sub-limits show dash."""
        lim = {
            "five_hour": {"utilization": 40, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day": {"utilization": 50, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day_opus": {"utilization": 45},
        }
        (sl.CACHE_DIR / "limits.json").write_text(json.dumps(lim))
        result = sl.build_line2()
        assert "O:45" in result
        assert "S:—" in result
        assert "H:—" in result

    def test_ultra_no_bars(self):
        """Ultra mode has no bars and no pie."""
        lim = {
            "five_hour": {"utilization": 50, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day": {"utilization": 30, "resets_at": "2099-12-31T23:59:59Z"},
        }
        (sl.CACHE_DIR / "limits.json").write_text(json.dumps(lim))
        result = sl.build_line2(tier=0)
        assert "◼" not in result  # no bar chars
        assert "○" not in result  # no pie
        assert "50%" in result
        assert "30%" in result

    def test_no_padding(self):
        """Line 2 should not start with padding dots."""
        lim = {
            "five_hour": {"utilization": 50, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day": {"utilization": 30, "resets_at": "2099-12-31T23:59:59Z"},
        }
        (sl.CACHE_DIR / "limits.json").write_text(json.dumps(lim))
        result = sl.build_line2()
        import re
        clean = re.sub(r'\033\[[0-9;]*m', '', result)
        assert clean.startswith("5h:")

    def test_spending_in_output(self):
        """Spending data (1d/7d/30d) appears in line 2."""
        lim = {
            "five_hour": {"utilization": 40, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day": {"utilization": 50, "resets_at": "2099-12-31T23:59:59Z"},
        }
        (sl.CACHE_DIR / "limits.json").write_text(json.dumps(lim))
        today = datetime.now().strftime("%Y-%m-%d")
        ccdata = {
            "daily": [
                {
                    "date": today,
                    "inputTokens": 100000,
                    "outputTokens": 50000,
                    "cacheCreationTokens": 200000,
                    "totalCost": 12.50,
                    "modelBreakdowns": [],
                }
            ]
        }
        (sl.CACHE_DIR / "ccusage.json").write_text(json.dumps(ccdata))
        result = sl.build_line2()
        assert "1d:" in result
        assert "7d:" in result
        assert "30d:" in result
        assert "$12" in result or "$13" in result

    def test_instances_format(self):
        """Test --instances format: {"projects": {...}}."""
        lim = {
            "five_hour": {"utilization": 40, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day": {"utilization": 50, "resets_at": "2099-12-31T23:59:59Z"},
        }
        (sl.CACHE_DIR / "limits.json").write_text(json.dumps(lim))
        today = datetime.now().strftime("%Y-%m-%d")
        ccdata = {
            "projects": {
                "-Users-test-projectA": [
                    {"date": today, "inputTokens": 50000, "outputTokens": 20000,
                     "cacheCreationTokens": 100000, "totalCost": 8.0, "modelBreakdowns": []},
                ],
                "-Users-test-projectB": [
                    {"date": today, "inputTokens": 30000, "outputTokens": 10000,
                     "cacheCreationTokens": 50000, "totalCost": 4.0, "modelBreakdowns": []},
                ],
            },
            "totals": {"totalCost": 12.0},
        }
        (sl.CACHE_DIR / "ccusage.json").write_text(json.dumps(ccdata))
        result = sl.build_line2()
        assert "$12" in result  # Global total

    def test_sparkline_in_output(self):
        """Sparkline appears in output when there's daily cost data."""
        lim = {
            "five_hour": {"utilization": 40, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day": {"utilization": 50, "resets_at": "2099-12-31T23:59:59Z"},
        }
        (sl.CACHE_DIR / "limits.json").write_text(json.dumps(lim))
        from datetime import timedelta
        ccdata = {"daily": []}
        for i in range(7):
            d = (datetime.now() - timedelta(days=6 - i)).strftime("%Y-%m-%d")
            ccdata["daily"].append({
                "date": d,
                "inputTokens": 10000,
                "outputTokens": 5000,
                "cacheCreationTokens": 20000,
                "totalCost": (i + 1) * 5.0,
                "modelBreakdowns": [],
            })
        (sl.CACHE_DIR / "ccusage.json").write_text(json.dumps(ccdata))
        result = sl.build_line2(tier=2)
        assert any(c in result for c in "▁▂▃▄▅▆▇█")

    def test_no_spending_cache(self):
        """When no ccusage cache, spending shows dashes."""
        lim = {
            "five_hour": {"utilization": 40, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day": {"utilization": 50, "resets_at": "2099-12-31T23:59:59Z"},
        }
        (sl.CACHE_DIR / "limits.json").write_text(json.dumps(lim))
        with patch.object(sl, "refresh_ccusage", lambda cf: None):
            result = sl.build_line2()
        assert "1d: —" in result
        assert "7d: —" in result
        assert "30d: —" in result


# ═══════════════════════ log_session ═══════════════════════

class TestLogSession:
    def setup_method(self):
        self._orig = sl.CACHE_DIR
        sl.CACHE_DIR = Path(tempfile.mkdtemp())

    def teardown_method(self):
        import shutil
        shutil.rmtree(sl.CACHE_DIR, ignore_errors=True)
        sl.CACHE_DIR = self._orig

    def test_creates_log_entry(self):
        data = {
            "model": {"id": "claude-opus-4-6"},
            "context_window": {"total_input_tokens": 100000, "total_output_tokens": 30000},
            "cost": {"total_cost_usd": 5.0, "total_duration_ms": 600000},
        }
        sl.log_session(data)
        log_f = sl.CACHE_DIR / "sessions.jsonl"
        assert log_f.exists()
        entry = json.loads(log_f.read_text().strip())
        assert entry["m"] == "opus"
        assert entry["c"] == 5.0
        assert entry["t"] == 130000

    def test_throttle_60s(self):
        data = {
            "model": {"id": "claude-opus-4-6"},
            "context_window": {"total_input_tokens": 50000, "total_output_tokens": 10000},
            "cost": {"total_cost_usd": 2.0, "total_duration_ms": 300000},
        }
        sl.log_session(data)
        sl.log_session(data)  # Should be throttled
        log_f = sl.CACHE_DIR / "sessions.jsonl"
        lines = log_f.read_text().strip().splitlines()
        assert len(lines) == 1  # Only one entry due to throttle


# ═══════════════════════ rjson ═══════════════════════

class TestRjson:
    def test_valid(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"key": "value"}, f)
            f.flush()
            result = sl.rjson(Path(f.name))
        assert result == {"key": "value"}
        Path(f.name).unlink()

    def test_missing(self):
        assert sl.rjson(Path("/nonexistent/file.json")) is None

    def test_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json")
            f.flush()
            result = sl.rjson(Path(f.name))
        assert result is None
        Path(f.name).unlink()


# ═══════════════════════ is_stale ═══════════════════════

class TestIsStale:
    def test_missing_file(self):
        assert sl.is_stale(Path("/nonexistent"), 60) is True

    def test_fresh_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
        assert sl.is_stale(Path(f.name), 60) is False
        Path(f.name).unlink()
