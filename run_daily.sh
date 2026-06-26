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

# Read just the heartbeat URL from .env (no full source → no surprises from other vars).
HEALTHCHECK_URL="$(grep -E '^HEALTHCHECK_URL=' .env 2>/dev/null | head -1 | cut -d= -f2-)"

FAIL=0   # flips to 1 if any step exits non-zero — drives the heartbeat alert

SIGNALS_ONLY=false
if [[ "$1" == "--signals-only" ]]; then
    SIGNALS_ONLY=true
fi

LOG="datasets/daily_$(date +%Y-%m-%d).log"

echo "======================================" | tee "$LOG"
echo "DAILY RUN  $(date '+%Y-%m-%d %H:%M')" | tee -a "$LOG"
echo "======================================" | tee -a "$LOG"

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
