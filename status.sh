#!/usr/bin/env bash
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
set -a; source "$BASE/config.env"; set +a
SANDBOX_HOME="${SANDBOX_HOME:-$CSSWITCH_HOME/.sandbox/home}"
DATA_DIR="$SANDBOX_HOME/.claude-science"
SCIENCE_PORT="${SCIENCE_PORT:-8990}"
PUBLIC_HOST="${PUBLIC_HOST:-127.0.0.1}"

if [[ "${1:-}" == "--url" ]]; then
  HOME="$SANDBOX_HOME" "$SCIENCE_BIN" url --data-dir "$DATA_DIR" 2>/dev/null | sed "s#localhost#$PUBLIC_HOST#;s#127.0.0.1#$PUBLIC_HOST#"
  exit 0
fi

echo "=== Science status ==="
HOME="$SANDBOX_HOME" "$SCIENCE_BIN" status --data-dir "$DATA_DIR" 2>&1 || true
echo
echo "=== Health ==="
curl -s "http://127.0.0.1:$SCIENCE_PORT/health" 2>/dev/null || true
echo
echo "=== Proxy log ==="
tail -20 "$CSSWITCH_HOME/logs/proxy.log" 2>/dev/null || true
echo
echo "Login URL:"
"$0" --url
