#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
LOCK_FILE="/tmp/stock_alerts_$(printf '%s' "$SCRIPT_DIR" | md5sum | awk '{print $1}').lock"
LOG_FILE="${SCRIPT_DIR}/alerts.log"
LOG_MAX_AGE_DAYS=7

cd "$SCRIPT_DIR"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

exec 9>"$LOCK_FILE"
flock -n 9 || {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Another instance is already running, skipping." >> "$LOG_FILE"
  exit 0
}

if [[ -f "$LOG_FILE" ]] && find "$LOG_FILE" -mtime +"$LOG_MAX_AGE_DAYS" -print -quit | grep -q .; then
  : > "$LOG_FILE"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleared alerts.log (older than ${LOG_MAX_AGE_DAYS} days)." >> "$LOG_FILE"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting stocks_alert.py" >> "$LOG_FILE"
/usr/bin/python3 "${SCRIPT_DIR}/stocks_alert.py" >> "$LOG_FILE" 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Finished stocks_alert.py" >> "$LOG_FILE"
