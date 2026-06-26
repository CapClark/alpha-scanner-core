# Always-on host deployment (Phase 1: daily executor)

Moves the daily trading automation off the laptop (where it went dark for ~2 weeks
after a timezone change + laptop sleep) onto an always-on Ubuntu VM.

**Scope:** alpha-scanner daily (mean-reversion) + canslim daily (`--sp500`, RS≥90 + TP8%).
The heavy weekly research (`--full --weekly`: WRDS + 1.2G `ohlcv_full` + model retrain)
stays on the laptop until Phase 2.

## Prereqs
- Ubuntu 24.04 LTS VM, 2 GB RAM, with the deploy SSH key authorized.
- PR #1 (persistent GTC stops + portable runner) merged to `main` before cloning.

## Steps (run from the laptop unless noted)
1. **Connect:** `ssh -i ~/.ssh/id_ed25519_trading <user>@<VM_IP>`
2. **Bootstrap (on VM):** clone alpha-scanner-core, then
   `./deploy/setup_host.sh` — sets TZ→ET, clones both repos, builds venvs, installs
   deps, links `.env`, installs cron. It will report the two items it can't fetch itself:
3. **Copy secrets (from laptop, NOT git):**
   ```
   scp -i ~/.ssh/id_ed25519_trading \
     alpha-scanner-core/.env <user>@<VM_IP>:~/strategy_grade.io/alpha-scanner-core/.env
   ```
4. **Seed the benchmark price cache (from laptop):** alpha-scanner needs ≥252d history
   per name (CRSP-sourced, not regenerable without WRDS); canslim `--sp500` RS-ranks
   against it. ~77 MB.
   ```
   rsync -avz -e "ssh -i ~/.ssh/id_ed25519_trading" \
     alpha-scanner-core/datasets/cache/ \
     <user>@<VM_IP>:~/strategy_grade.io/alpha-scanner-core/datasets/cache/
   ```
5. **Verify (on VM):**
   ```
   cd ~/strategy_grade.io/alpha-scanner-core && ./run_daily.sh --signals-only
   cd ~/strategy_grade.io/canslim-core       && ./run_daily.sh --sp500 --signals-only
   ```
   Confirm prices load, signals print, no tracebacks. Then the cron arms live execution.
6. **Decommission laptop (so jobs don't double-fire if you're ever home + awake):**
   ```
   launchctl bootout gui/$(id -u)/com.alphascanner.daily
   launchctl bootout gui/$(id -u)/com.canslim.daily
   # keep com.canslim.weekly on the laptop (Phase 2 research still runs there)
   ```

## Schedule (host TZ = America/New_York)
| job | time | command |
|-----|------|---------|
| alpha daily | 9:35 ET, Mon–Fri | `run_daily.sh` |
| canslim daily | 9:40 ET, Mon–Fri | `run_daily.sh --sp500` |

## Resilience — so it can't silently die again
Two failures hid for weeks: execution stopped (timezone/sleep) and stops expired
(naked positions). The always-on host fixes the first cause; these add the alarms:

1. **Dead-man's-switch heartbeat.** Create a free check at https://healthchecks.io
   (period 1 day, grace ~2h), then add its ping URL to `alpha-scanner-core/.env`:
   ```
   HEALTHCHECK_URL=https://hc-ping.com/<your-uuid>
   ```
   `run_daily.sh` pings it on success and `…/fail` on any failed step. If a run is
   missed or fails, healthchecks.io emails/SMSes you within the grace window —
   instead of finding out two weeks later. (Give the canslim job its own check.)
2. **Stop-loss guardrail.** `guard_stops.py --rearm` runs as the last daily step:
   for every open position it confirms a resting GTC stop exists and re-places one
   at entry−5% if not. A naked position makes the run exit non-zero → heartbeat
   `/fail` → you get alerted. Run it ad hoc any time: `python3 guard_stops.py`.

## Health check
`tail -f ~/strategy_grade.io/*/datasets/cron.log` after a fire, and the Alpaca
dashboards. Each `run_daily.sh` also writes `datasets/daily_<date>.log`.
