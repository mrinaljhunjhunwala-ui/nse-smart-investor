#!/usr/bin/env bash
# deploy/oracle-relay/eod_refresh.sh — the NSE end-of-day downloads, run on the relay VM.
#
# NSE's archive host answers 403 to GitHub's runners (Nov 2026), so the steps of
# refresh-eod-data.yml that download from NSE run here instead, from the VM's Indian IP,
# on the nse-eod-refresh.timer (19:45 and 22:00 IST, Mon-Fri). Rows go to the same
# DATABASE_URL as the relay. Each step runs even if an earlier one failed; the script
# exits non-zero if any did, so `systemctl status nse-eod-refresh` shows it.
set -uo pipefail

cd /opt/nse-smart-investor
PY=/opt/nse-smart-investor/.venv-relay/bin/python
DAYS="${EOD_DAYS:-1}"
failed=0

run() {
  echo "==> $1"
  shift
  "$@" || { echo "    FAILED (exit $?)"; failed=1; }
}

run "FII index futures"          "$PY" -m scripts.fetch_nse_fii_deriv --days "$DAYS"
run "F&O open interest"          "$PY" -m scripts.fetch_nse_fno_bhavcopy --days "$DAYS"
run "Delivery %"                 "$PY" -m scripts.fetch_nse_delivery --days "$DAYS"
run "Option chain (F&O universe)" "$PY" -m scripts.fetch_nse_option_chain --fno-all

exit "$failed"
