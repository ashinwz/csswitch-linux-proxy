# CSSwitch for Claude Science Linux

Target: x86-64 Ubuntu/Debian + glibc.

## Install

```bash
cd ~/csswitch-science-linux
mkdir -p bin proxy scripts
curl -L https://downloads.claude.ai/claude-science/latest/linux-x64 -o bin/claude-science
chmod +x bin/claude-science
python3 -c 'import cryptography' || pip3 install cryptography
```

Edit `config.env`:

```bash
ARK_API_KEY=...
BIND_HOST=127.0.0.1      # or 0.0.0.0 for Tailscale/LAN
PUBLIC_HOST=127.0.0.1    # or your Tailscale IP
```

## Run

```bash
./start.sh
./status.sh --url
./stop.sh
```

Open the URL printed by `status.sh --url`, then click **Sign in** once. The link expires in ~3 min and is single-use.

## Notes

- Proxy listens on `127.0.0.1:$PROXY_PORT` only; Science reaches it locally.
- Science UI bind is controlled by `BIND_HOST`.
- `--allow-origin` is set to `http://$PUBLIC_HOST:$SCIENCE_PORT`.
- Remote Anthropic MCP services are expected to fail/skip under virtual login; local Science tools still work.
