#!/bin/bash
#===============================================================================
# Nightwatch Job: ASIN Discovery for Flat Keyboards
#===============================================================================
# Runs the flat keyboard discovery to find new ASINs
# Schedule: 02:00 and 14:00 (2x per day)
# Only runs during night hours (22:00-06:00)
#===============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/reports/nightwatch"
LOG_FILE="$LOG_DIR/11_asin_discovery.log"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

check_night_hours() {
    local hour
    hour=$(date +%H)
    if [[ "$hour" -ge 22 || "$hour" -lt 6 ]]; then
        return 0
    else
        return 1
    fi
}

log "=========================================="
log "Starting ASIN Discovery for Flat Keyboards"
log "=========================================="

if ! check_night_hours; then
    log "SKIPPED: Not in night hours (22:00-06:00)"
    log "Current hour: $(date +%H)"
    exit 0
fi

cd "$PROJECT_ROOT"

START_TIME=$(date +%s)

log "Running: python scripts/discover_flat_keyboards.py"

OUTPUT=$(python scripts/discover_flat_keyboards.py 2>&1) || true
echo "$OUTPUT" | tee -a "$LOG_FILE"

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

NEW_ASINS=$(echo "$OUTPUT" | grep -oP 'new ASINs.*?(\d+)' | grep -oP '\d+' || echo "0")

log "----------------------------------------"
log "Results:"
log "  Duration: ${DURATION}s"
log "  New ASINs found: $NEW_ASINS"
log "  Log file: $LOG_FILE"
log "=========================================="

exit 0
