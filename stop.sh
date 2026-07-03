#!/usr/bin/env bash
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
set -a; source "$BASE/config.env"; set +a
SANDBOX_HOME="${SANDBOX_HOME:-$CSSWITCH_HOME/.sandbox/home}"
DATA_DIR="$SANDBOX_HOME/.claude-science"
HOME="$SANDBOX_HOME" "$SCIENCE_BIN" stop --data-dir "$DATA_DIR" >/dev/null 2>&1 || true
pkill -f "$CSSWITCH_HOME/proxy/csswitch_proxy.py" >/dev/null 2>&1 || true
echo "CSSwitch Linux stopped."
