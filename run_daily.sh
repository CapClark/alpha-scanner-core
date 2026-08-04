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

cd "$(dirname "$0")" || exit 1

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
    # Fields are "<GO|SKIP> <ET-time|reason> <ET-date>". Gate stderr is KEPT
    # (datasets/gate_err.log): an expired key or dead venv used to collapse to the
    # bare word "api-error" with the traceback thrown away — the zero-trace failure
    # mode this whole block exists to kill.
    GATE="$("$PYTHON" - <<'PYEOF' 2>>datasets/gate_err.log || echo "SKIP api-error 0000-00-00"
import os, sys, time, datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
load_dotenv(".env")
from alpaca.trading.client import TradingClient

# Retry the clock call: this host loses DNS in multi-hour blocks overnight local
# time (nightly ~12:00-16:00 ET, see gate_err.log — the router was the only public
# resolver and drops when the ISP session renews). A single get_clock() then turns
# a healthy fire into a wasted one. Three tries covers a blip; a real outage is
# covered by cron re-firing every 10 minutes and by the missing heartbeat.
client = TradingClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=True)
clock = None
for attempt in range(3):
    try:
        clock = client.get_clock()
        break
    except Exception as exc:
        # stderr only — stdout is the verdict channel and must stay single-line.
        print(f"gate attempt {attempt + 1}/3: {exc!r}", file=sys.stderr)
        if attempt < 2:
            time.sleep(2 * (attempt + 1))
if clock is None:
    raise SystemExit(1)          # -> shell fallback writes "SKIP api-error 0000-00-00"

et = clock.timestamp.astimezone(ZoneInfo("America/New_York"))
ok = clock.is_open and datetime.time(9, 30) <= et.time() <= datetime.time(15, 30)
print(("GO" if ok else "SKIP"), et.strftime("%H:%M"), et.strftime("%Y-%m-%d"))
PYEOF
)"
    # Parse ONE line — the last. On a print-then-crash the `|| echo` fallback is
    # APPENDED to whatever python already wrote, so reading the status off line 1
    # and the date off line N can mix two different verdicts. The last line is
    # always the final word.
    read -r GATE_STATUS GATE_ET GATE_DATE _ <<< "$(printf '%s\n' "$GATE" | tail -1)"
    # A GO must carry a well-formed HH:MM and YYYY-MM-DD or it is not a GO: a
    # malformed date would write a marker (e.g. .ran_0000-00-00) that never matches
    # a future day — the bot would trade once and then skip forever.
    case "$GATE_STATUS $GATE_ET $GATE_DATE" in
        GO\ [0-9][0-9]:[0-9][0-9]\ [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
        GO*) GATE_STATUS=SKIP; GATE_ET=malformed ;;
    esac
    # Decide, then log the DECISION — not just Alpaca's verdict. With a six-hour
    # window most fires are "GO but already claimed"; without the action field the
    # log can't say which fire actually traded.
    if [ "$GATE_STATUS" != "GO" ]; then
        ACTION=skip
    elif [ -f "datasets/.ran_${GATE_DATE}" ]; then
        ACTION=done
    elif ( set -o noclobber; : > "datasets/.ran_${GATE_DATE}" ) 2>/dev/null; then
        # noclobber create is atomic: exactly one process can win the claim, so a
        # manual run racing the timer can't double-trade. Stale markers pruned only
        # AFTER today is claimed. If the create fails for any other reason (disk
        # full, TCC), we refuse to trade unclaimed — an uncapped rerun every fire
        # is worse than a missed day, and the missed ping alerts anyway.
        ACTION=RUN
        find datasets -name '.ran_*' ! -name ".ran_${GATE_DATE}" -delete 2>/dev/null
    else
        ACTION=unclaimed
    fi
    printf '%s  gate=%s %s %s  action=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" \
        "$GATE_STATUS" "$GATE_ET" "$GATE_DATE" "$ACTION" >> datasets/gate.log
    # Bound both traces — gate.log ~34 lines/day, gate_err.log only on failures.
    if [ "$(wc -l < datasets/gate.log 2>/dev/null || echo 0)" -gt 4000 ]; then
        tail -2000 datasets/gate.log > datasets/gate.log.tmp && mv datasets/gate.log.tmp datasets/gate.log
    fi
    if [ "$(wc -l < datasets/gate_err.log 2>/dev/null || echo 0)" -gt 2000 ]; then
        tail -500 datasets/gate_err.log > datasets/gate_err.log.tmp && mv datasets/gate_err.log.tmp datasets/gate_err.log
    fi
    [ "$ACTION" = RUN ] || exit 0
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
    # AC power alone is not enough: a macOS update reverted `sleep 0` once already
    # (2026-07-23, cost two sessions) while the machine sat happily on AC. Check the
    # live sleep policy, not just the power source.
    AC_SLEEP="$(pmset -g custom 2>/dev/null | awk '/^AC Power:/{ac=1} ac && / sleep /{print $2; exit}')"
    if [ -n "$AC_SLEEP" ] && [ "$AC_SLEEP" != "0" ]; then
        echo "  WARN AC sleep policy is ${AC_SLEEP}, not 0 — a macOS update likely reverted it." | tee -a "$LOG"
        echo "       Fix: sudo pmset -c sleep 0 disablesleep 1   (launchd can't fire in darkwake)" | tee -a "$LOG"
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

# Local dead-man's stamp, independent of healthchecks.io. The remote channel itself
# was silently broken for ~3 weeks in July — this file is the on-disk truth a human
# (or the presentation-morning health check) can read without trusting the alerter:
# stat -f %Sm datasets/.last_success
if [ "$FAIL" -eq 0 ]; then
    date '+%Y-%m-%d %H:%M:%S' > datasets/.last_success
fi

# Retention sweep — gate.log self-trims, but nothing bounded the rest: daily logs
# accumulate forever and launchd_out.log grows every fire. Keep 90 days of dailies
# and cap the launchd streams (they are duplicates of the daily logs anyway).
find datasets -name 'daily_*.log' -mtime +90 -delete 2>/dev/null
for f in datasets/launchd_out.log datasets/launchd_err.log datasets/cron.log; do
    if [ -f "$f" ] && [ "$(wc -c < "$f")" -gt 5000000 ]; then
        tail -c 1000000 "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    fi
done

# Heartbeat — ping success, or /fail if any step above failed. Silent no-op if unset.
if [ -n "$HEALTHCHECK_URL" ]; then
    # The ping URL is a bearer capability (holding it lets anyone forge or suppress
    # the heartbeat) — hide it from -x tracing, same as the credential reads above.
    __xt="${-//[^x]/}"; set +x
    if [ "$FAIL" -eq 0 ]; then
        curl -fsS -m 10 "$HEALTHCHECK_URL" >/dev/null 2>&1
    else
        curl -fsS -m 10 "${HEALTHCHECK_URL%/}/fail" >/dev/null 2>&1
    fi
    [ -n "$__xt" ] && set -x
fi

echo "" | tee -a "$LOG"
echo "Log saved to $LOG  (status: $([ "$FAIL" -eq 0 ] && echo OK || echo FAILED))"
exit $FAIL
