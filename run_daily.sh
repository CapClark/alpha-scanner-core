#!/bin/bash
# Daily runner — prices → signals → execute trades → P&L → stop guardrail → heartbeat
#
# To automate (runs at 9:35am ET Mon–Fri, just after market open):
#   crontab -e
#   35 9 * * 1-5 /path/to/alpha-scanner-core/run_daily.sh
#
# For signals only (no trading), run:  ./run_daily.sh --signals-only
#
# Resilience: set HEALTHCHECK_URL=<your healthchecks.io ping url> in .env to enable a
# dead-man's-switch — a missed or failed run then alerts you within the grace window.

cd "$(dirname "$0")"

# Portable venv python — works on the laptop and the cloud host alike.
# The cd above already moved us here, so pwd is its absolute path.
PYTHON="$(pwd)/venv/bin/python"

# Read just the vars we need from .env (no full source → no surprises from other vars).
#
# Tracing is forced OFF across this block and restored after. `bash -x` expands every
# assignment before printing it, so debugging this script with -x used to dump the raw
# VERCEL_TOKEN to stdout — on 2026-07-28 that put a live token in a terminal transcript
# and forced a rotation. Secrets must be unreadable by the debugger, not merely
# unlikely to be printed.
__xtrace="${-//[^x]/}"          # remember whether -x was on ("x" or "")
set +x
HEALTHCHECK_URL="$(grep -E '^HEALTHCHECK_URL=' .env 2>/dev/null | head -1 | cut -d= -f2-)"
# Vercel deploy token for the public-page publish step. Exported (not passed as a
# --token CLI arg) so it never shows up in `ps`; deploy_vercel.py reads it from env.
VERCEL_TOKEN="$(grep -E '^VERCEL_TOKEN=' .env 2>/dev/null | head -1 | cut -d= -f2-)"
export VERCEL_TOKEN
[ -n "$__xtrace" ] && set -x

FAIL=0   # flips to 1 if any step exits non-zero — drives the heartbeat alert

SIGNALS_ONLY=false
if [[ "$1" == "--signals-only" ]]; then
    SIGNALS_ONLY=true
fi

# --- Market-session gate (timezone-proof) -----------------------------------
# launchd fires this on a timer; whether we actually run is decided by Alpaca's
# market clock, NOT the host clock — so it runs once per session regardless of any
# system/launchd timezone drift. Manual --signals-only bypasses it.
#
# The window is 09:30–15:30 ET, not the old 09:30–10:30. macOS defers and coalesces
# launchd StartInterval timers on an idle Mac: measured 2026-07-28, 1046 fires over
# 31 days of uptime = ~34/day against the 48/day a 1800s interval nominally gives.
# Two fires an hour is exactly what guarantees a hit inside a one-hour window; at
# 34/day that guarantee is gone, and 2026-07-23/24/27 were each lost to a window
# that happened to contain no fire. A wider window trades a worse fill for actually
# trading. The .ran_ marker still pins it to one run per session.
#
# Every decision is appended to datasets/gate.log. A skip used to write nothing at
# all — no log, no marker, no ping — so those three dead days left zero trace on disk.
if [ "$SIGNALS_ONLY" != true ]; then
    # Fields are "<GO|SKIP> <ET-time|reason> <ET-date>". The date stays LAST because
    # the marker filename is parsed off the end.
    GATE="$("$PYTHON" - <<'PYEOF' 2>/dev/null || echo "SKIP api-error 0000-00-00"
import os, datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
load_dotenv(".env")
from alpaca.trading.client import TradingClient
c = TradingClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=True).get_clock()
et = c.timestamp.astimezone(ZoneInfo("America/New_York"))
ok = c.is_open and datetime.time(9, 30) <= et.time() <= datetime.time(15, 30)
print(("GO" if ok else "SKIP"), et.strftime("%H:%M"), et.strftime("%Y-%m-%d"))
PYEOF
)"
    GATE_DATE="${GATE##* }"
    GATE_ET="$(echo "$GATE" | cut -d' ' -f2)"
    printf '%s  host=%s  gate=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$(date +%H:%M)" "$GATE" \
        >> datasets/gate.log
    # Bound the trace — ~34 lines/day, so 4000 lines is roughly four months of history.
    if [ "$(wc -l < datasets/gate.log)" -gt 4000 ]; then
        tail -2000 datasets/gate.log > datasets/gate.log.tmp && mv datasets/gate.log.tmp datasets/gate.log
    fi
    if [ "${GATE%% *}" != "GO" ] || [ -f "datasets/.ran_${GATE_DATE}" ]; then
        exit 0            # outside the session window (or already ran today) — skip quietly
    fi
    rm -f datasets/.ran_*             # claim today up-front so overlapping fires can't double-run
    touch "datasets/.ran_${GATE_DATE}"
fi

LOG="datasets/daily_$(date +%Y-%m-%d).log"

echo "======================================" | tee "$LOG"
echo "DAILY RUN  $(date '+%Y-%m-%d %H:%M')" | tee -a "$LOG"
echo "======================================" | tee -a "$LOG"

# A start well after the open means launchd deferred the timer past the post-open
# window, so the fills are worse than the strategy intends. Surface it, but do NOT
# set FAIL: a late run is still far better than the missed session it replaced, and
# turning it red would retrain the alerts back into noise.
if [ -n "$GATE_ET" ] && [[ "$GATE_ET" > "10:30" ]]; then
    echo "  WARN late start ${GATE_ET} ET — launchd missed the post-open window." | tee -a "$LOG"
fi

# Step 0: power preflight. This host must live on AC. On battery macOS sleeps it
# aggressively and launchd timers do NOT fire in darkwake, so a drained battery means
# every future run is silently skipped — the exact failure that cost two sessions in
# July 2026, found only by going and looking. Route it through the heartbeat so it
# alerts while there is still charge left to act on. Never blocks the run.
if command -v pmset >/dev/null 2>&1; then
    if ! pmset -g ps 2>/dev/null | head -1 | grep -qi "AC Power"; then
        BATT="$(pmset -g batt 2>/dev/null | grep -oE '[0-9]+%' | head -1)"
        echo "  WARN host is on BATTERY (${BATT:-level unknown}), not AC — plug it in." | tee -a "$LOG"
        echo "       On battery this machine sleeps; once it drains, runs stop silently." | tee -a "$LOG"
        FAIL=1
    fi
fi

# Step 1: top up prices via yfinance
echo "" | tee -a "$LOG"
echo "[ 1/5 ] Updating prices..." | tee -a "$LOG"
$PYTHON data.py --topup 2>&1 | tee -a "$LOG"; [ "${PIPESTATUS[0]}" -ne 0 ] && FAIL=1

# Step 2: generate signals
echo "" | tee -a "$LOG"
echo "[ 2/5 ] Generating signals..." | tee -a "$LOG"
$PYTHON signals.py 2>&1 | tee -a "$LOG"; [ "${PIPESTATUS[0]}" -ne 0 ] && FAIL=1

# Step 3: execute trades (skip if --signals-only)
echo "" | tee -a "$LOG"
if [ "$SIGNALS_ONLY" = true ]; then
    echo "[ 3/5 ] Trading skipped (--signals-only)" | tee -a "$LOG"
else
    echo "[ 3/5 ] Executing trades..." | tee -a "$LOG"
    $PYTHON bot.py 2>&1 | tee -a "$LOG"; [ "${PIPESTATUS[0]}" -ne 0 ] && FAIL=1
fi

# Step 4: update trade log + print P&L summary
echo "" | tee -a "$LOG"
echo "[ 4/5 ] Tracking P&L..." | tee -a "$LOG"
$PYTHON tracker.py 2>&1 | tee -a "$LOG"; [ "${PIPESTATUS[0]}" -ne 0 ] && FAIL=1

# Step 4b: rebuild the redacted public results page (public/index.html) for
# strategygrade.io. Cosmetic — a failure here must NOT fail the trading run, so
# there is no FAIL gate. To auto-deploy, set VERCEL_TOKEN and uncomment the
# deploy line (see deploy/README.md).
echo "" | tee -a "$LOG"
echo "[ 4b  ] Publishing public results page..." | tee -a "$LOG"
$PYTHON publish.py 2>&1 | tee -a "$LOG" || echo "  publish failed (non-fatal)" | tee -a "$LOG"
# Publish to Vercel via REST (no node/CLI/git on the host). Self-guards on a missing
# token and can only ever exit 0, so a cosmetic publish never fails the trading run.
$PYTHON deploy_vercel.py 2>&1 | tee -a "$LOG" || true

# Step 5: stop-loss guardrail — re-arm any naked position (defends the 2026-06 bug
# where expired stop legs left positions unprotected). Non-zero exit => something was
# naked => the heartbeat fails so you get alerted even though trading "ran".
echo "" | tee -a "$LOG"
echo "[ 5/5 ] Stop-loss guardrail..." | tee -a "$LOG"
if [ "$SIGNALS_ONLY" != true ]; then
    $PYTHON guard_stops.py --rearm 2>&1 | tee -a "$LOG"; [ "${PIPESTATUS[0]}" -ne 0 ] && FAIL=1
else
    echo "  skipped (--signals-only)" | tee -a "$LOG"
fi

# NOTE (2026-07-05): the ratchet-trail step that briefly lived here was REMOVED after
# the exit sweep falsified it — trailing strangles mean-reversion recoveries the same
# way the tight 5% stop did (Sharpe 1.28-1.32 -> 0.89 across every trail config).
# Exits are: indicator signal (the strategy) + a wide 4xATR disaster stop set at entry.

# Heartbeat — ping success, or /fail if any step above failed. Silent no-op if unset.
if [ -n "$HEALTHCHECK_URL" ]; then
    if [ "$FAIL" -eq 0 ]; then
        curl -fsS -m 10 "$HEALTHCHECK_URL" >/dev/null 2>&1
    else
        curl -fsS -m 10 "${HEALTHCHECK_URL%/}/fail" >/dev/null 2>&1
    fi
fi

echo "" | tee -a "$LOG"
echo "Log saved to $LOG  (status: $([ "$FAIL" -eq 0 ] && echo OK || echo FAILED))"
exit $FAIL
