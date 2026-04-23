#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# install_cron.sh
# Installs an hourly cron entry for pause_ads.py
# Runs at minute 0 of every hour.
# -----------------------------------------------------------------------------

set -euo pipefail

REPO_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PYTHON_BIN="$(command -v python3)"
LOG_FILE="${REPO_DIR}/logs/cron.log"
SCRIPT="${REPO_DIR}/pause_ads.py"

mkdir -p "${REPO_DIR}/logs"

CRON_LINE="0 * * * * cd ${REPO_DIR} && ${PYTHON_BIN} ${SCRIPT} >> ${LOG_FILE} 2>&1"

# Remove any existing entry for pause_ads.py, then add the new one
( crontab -l 2>/dev/null | grep -v -F "pause_ads.py" ; echo "${CRON_LINE}" ) | crontab -

echo "Installed cron entry:"
echo "  ${CRON_LINE}"
echo
echo "View installed crontab with:  crontab -l"
echo "Tail the log with:            tail -f ${LOG_FILE}"
