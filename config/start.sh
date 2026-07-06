#!/bin/zsh
set -euo pipefail
BASE="${0:A:h}"
CFG="$BASE/config.env"
[[ -f "$CFG" ]] || { echo "missing $CFG"; exit 1; }
source "$CFG"

LOG_DIR="$CSSWITCH_HOME/logs"
mkdir -p "$CSSWITCH_HOME/proxy" "$CSSWITCH_HOME/scripts" "$LOG_DIR"

PROXY_PORT="${PROXY_PORT:-18991}"
SCIENCE_PORT="${SCIENCE_PORT:-8990}"
CSSWITCH_PROVIDER="${CSSWITCH_PROVIDER:-ark}"
SCIENCE_BIN="${SCIENCE_BIN:-$HOME/Applications/Claude Science.app/Contents/Resources/bin/claude-science}"
SANDBOX_HOME="${SANDBOX_HOME:-$CSSWITCH_HOME/.sandbox/home}"
DATA_DIR="$SANDBOX_HOME/.claude-science"
REAL_DIR="$HOME/.claude-science"
BIND_HOST="${BIND_HOST:-127.0.0.1}"
PUBLIC_HOST="${PUBLIC_HOST:-$BIND_HOST}"

[[ -x "$SCIENCE_BIN" ]] || { echo "Science binary not found: $SCIENCE_BIN"; exit 1; }
[[ -n "${ARK_API_KEY:-}" || "$CSSWITCH_PROVIDER" != "ark" ]] || { echo "missing ARK_API_KEY in config.env"; exit 1; }

# stop previous sandbox/proxy
"$SCIENCE_BIN" stop >/dev/null 2>&1 || true
HOME="$SANDBOX_HOME" "$SCIENCE_BIN" stop --data-dir "$DATA_DIR" >/dev/null 2>&1 || true
pkill -f "$CSSWITCH_HOME/proxy/csswitch_proxy.py" >/dev/null 2>&1 || true
sleep 1

SEC="$(python3 -c 'import secrets;print(secrets.token_hex(16))')"
echo "$SEC" > "$CSSWITCH_HOME/.secret"
chmod 600 "$CSSWITCH_HOME/.secret"

# proxy
export ARK_API_KEY
nohup python3 "$CSSWITCH_HOME/proxy/csswitch_proxy.py" \
  --provider "$CSSWITCH_PROVIDER" --port "$PROXY_PORT" --auth-token "$SEC" \
  > "$LOG_DIR/proxy.log" 2>&1 &
sleep 2
if ! grep -q "CSSwitch 代理启动" "$LOG_DIR/proxy.log"; then
  echo "proxy failed:"; cat "$LOG_DIR/proxy.log"; exit 1
fi

# runtime clone for sandbox
if [[ ! -d "$DATA_DIR/bin" ]]; then
  mkdir -p "$DATA_DIR"
  for a in bin conda runtime seed-assets; do
    [[ -d "$REAL_DIR/$a" ]] && cp -Rc "$REAL_DIR/$a" "$DATA_DIR/$a" 2>/dev/null || true
  done
fi

# virtual OAuth
python3 "$CSSWITCH_HOME/scripts/make-virtual-oauth.py" \
  --auth-dir "$DATA_DIR" --email virtual@localhost.invalid \
  > "$LOG_DIR/oauth.log" 2>&1

PXURL="http://127.0.0.1:$PROXY_PORT/$SEC"
FF="http://127.0.0.1:$PROXY_PORT"
NP="127.0.0.1,localhost,::1"
ALLOW_ORIGIN="http://$PUBLIC_HOST:$SCIENCE_PORT"

HOME="$SANDBOX_HOME" ANTHROPIC_BASE_URL="$PXURL" \
  https_proxy="$FF" HTTPS_PROXY="$FF" no_proxy="$NP" NO_PROXY="$NP" \
  "$SCIENCE_BIN" serve --data-dir "$DATA_DIR" --port "$SCIENCE_PORT" \
  --host "$BIND_HOST" --allow-origin "$ALLOW_ORIGIN" \
  --no-browser --no-auto-update --detached \
  > "$LOG_DIR/science-start.log" 2>&1

sleep 5
HOME="$SANDBOX_HOME" "$SCIENCE_BIN" status --data-dir "$DATA_DIR" > "$LOG_DIR/status.json" 2>&1 || true

# hostfix proxy v9 (8990 -> 8992) with auto cookie injection
pkill -f hostfix_proxy 2>/dev/null || true
sleep 1
nohup python3 "$CSSWITCH_HOME/hostfix_proxy_v9.py" > "$LOG_DIR/hostfix.log" 2>&1 &
sleep 3
if ! lsof -i :8990 -P -n 2>/dev/null | grep -q LISTEN; then
  echo "hostfix_proxy_v9 failed:"; cat "$LOG_DIR/hostfix.log"; exit 1
fi

echo "CSSwitch started."
echo "Local:  http://127.0.0.1:$SCIENCE_PORT"
if [[ -n "$PUBLIC_HOST" && "$PUBLIC_HOST" != "127.0.0.1" && "$PUBLIC_HOST" != "0.0.0.0" ]]; then
  echo "iOS:    http://$PUBLIC_HOST:$SCIENCE_PORT"
else
  echo "iOS:    set PUBLIC_HOST=<MacAir Tailscale IP> in config.env, then restart"
fi
echo "Login:  $CSSWITCH_HOME/status.sh --url"
