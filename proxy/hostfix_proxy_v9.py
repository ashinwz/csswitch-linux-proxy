#!/usr/bin/env python3
"""hostfix_proxy_v9 — v8 + automatic operon_auth cookie injection.

Auto-login via nonce on startup and on 401, injects Cookie header so
browsers can access the daemon without manual nonce login.
"""
import socket, threading, selectors, re, subprocess, http.client, os, time

# === Config ===
LISTEN_HOST = '0.0.0.0'
LISTEN_PORT = 8990
BACKEND_HOST = '127.0.0.1'
BACKEND_PORT = 8992

_cfg_path = os.path.expanduser('~/csswitch/config.env')
PUBLIC_HOST = '127.0.0.1'
if os.path.exists(_cfg_path):
    with open(_cfg_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith('PUBLIC_HOST=') and not line.startswith('#'):
                PUBLIC_HOST = line.split('=', 1)[1]
                break
PUBLIC_PORT = 8990

BIN = os.path.expanduser('~/Applications/Claude Science.app/Contents/Resources/bin/claude-science')
DATA_DIR = os.path.expanduser('~/csswitch/.sandbox/home/.claude-science')
SANDBOX_HOME = os.path.expanduser('~/csswitch/.sandbox/home')

LOCAL_ORIGIN = f'http://{BACKEND_HOST}:{BACKEND_PORT}'
PUBLIC_ORIGIN = f'http://{PUBLIC_HOST}:{PUBLIC_PORT}'

_operon_auth = None
_auth_lock = threading.Lock()

def refresh_auth():
    """Login via nonce, cache operon_auth cookie value."""
    global _operon_auth
    with _auth_lock:
        for attempt in range(3):
            try:
                env = dict(os.environ, HOME=SANDBOX_HOME)
                r = subprocess.run([BIN, 'url', '--data-dir', DATA_DIR],
                                 capture_output=True, text=True, env=env, timeout=10)
                m = re.search(r'nonce=([a-f0-9]+)', r.stdout)
                if not m:
                    print(f'[auth] no nonce (attempt {attempt+1}): {r.stdout.strip()[:100]}', flush=True)
                    time.sleep(1)
                    continue
                nonce = m.group(1)
                conn = http.client.HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=10)
                body = f'nonce={nonce}&dest=/'
                conn.request('POST', '/api/auth/nonce', body, {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Origin': LOCAL_ORIGIN,
                    'Referer': f'{LOCAL_ORIGIN}/?nonce={nonce}',
                })
                resp = conn.getresponse()
                resp.read()
                cookie = resp.getheader('set-cookie', '')
                m = re.search(r'operon_auth=([a-f0-9]+)', cookie)
                if m:
                    _operon_auth = m.group(1)
                    print(f'[auth] ok operon_auth={_operon_auth[:12]}...', flush=True)
                    return True
                print(f'[auth] no operon_auth in set-cookie: {cookie[:80]}', flush=True)
            except Exception as e:
                print(f'[auth] error (attempt {attempt+1}): {e}', flush=True)
            time.sleep(1)
        return False

# === Polyfill (same as v8) ===
POLYFILL_JS = b'(function(){function u(){var b=new Uint8Array(16);window.crypto.getRandomValues(b);b[6]=(b[6]&0x0f)|0x40;b[8]=(b[8]&0x3f)|0x80;var s="";for(var i=0;i<16;i++)s+=(b[i]<16?"0":"")+b[i].toString(16);return s.slice(0,8)+"-"+s.slice(8,12)+"-"+s.slice(12,16)+"-"+s.slice(16,20)+"-"+s.slice(20)}try{Object.defineProperty(window.crypto,"randomUUID",{value:u,configurable:!0,writable:!0})}catch(e1){try{window.crypto.randomUUID=u}catch(e2){var w=Object.create(window.crypto);w.randomUUID=u;w.getRandomValues=window.crypto.getRandomValues.bind(window.crypto);try{Object.defineProperty(window,"crypto",{value:w,configurable:!0,writable:!0})}catch(e3){window.crypto=w}}}})();'

def recv_header(sock, limit=65536):
    data = b''
    while b'\r\n\r\n' not in data and len(data) < limit:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data

def rewrite_req(req):
    head, sep, rest = req.partition(b'\r\n\r\n')
    lines = head.split(b'\r\n')
    out = []
    for line in lines:
        low = line.lower()
        if low.startswith(b'host:'):
            out.append(f'Host: {BACKEND_HOST}:{BACKEND_PORT}'.encode())
        elif low.startswith(b'origin:'):
            out.append(f'Origin: {LOCAL_ORIGIN}'.encode())
        elif low.startswith(b'referer:'):
            out.append(f'Referer: {LOCAL_ORIGIN}/'.encode())
        elif low.startswith(b'connection:'):
            out.append(b'Connection: close')
        elif low.startswith(b'cookie:'):
            pass  # strip browser cookies, we inject our own
        elif low.startswith(b'accept-encoding:'):
            pass  # strip gzip, so polyfill injection doesn't corrupt compressed body
        else:
            out.append(line)
    if not any(l.lower().startswith(b'connection:') for l in out):
        out.append(b'Connection: close')
    # Inject operon_auth cookie
    if _operon_auth:
        out.append(f'Cookie: operon_auth={_operon_auth}'.encode())
    return b'\r\n'.join(out) + sep + rest

def inject_polyfill(headers, body):
    ct = re.search(rb'(?i)content-type:\s*([^\r\n;]+)', headers)
    ct_val = ct.group(1).lower().strip() if ct else b''
    is_html = b'text/html' in ct_val
    is_js = b'javascript' in ct_val or (b'js' in ct_val and b'json' not in ct_val)
    if is_html and len(body) > 0 and b'randomUUID' not in body:
        script_tag = b'<script>' + POLYFILL_JS + b'</script>'
        if b'</head>' in body:
            return body.replace(b'</head>', script_tag + b'</head>', 1), len(script_tag)
        elif b'<head>' in body:
            return body.replace(b'<head>', b'<head>' + script_tag, 1), len(script_tag)
        else:
            return script_tag + body, len(script_tag)
    # JS files don't need polyfill — HTML inline script handles it before any external scripts load
    return body, 0

def rewrite_resp(resp):
    try:
        header_end = resp.index(b'\r\n\r\n')
        headers = resp[:header_end]
        body = resp[header_end+4:]
        htxt = headers.decode('ascii', errors='replace')
        htxt = htxt.replace(f'Access-Control-Allow-Origin: {LOCAL_ORIGIN}', f'Access-Control-Allow-Origin: {PUBLIC_ORIGIN}')
        htxt = htxt.replace(f'access-control-allow-origin: {LOCAL_ORIGIN}', f'access-control-allow-origin: {PUBLIC_ORIGIN}')
        htxt = re.sub(r'(?i)location:\s*http://127\.0\.0\.1:8992', f'Location: {PUBLIC_ORIGIN}', htxt)
        body = body.replace(b'http://127.0.0.1:8992', f'http://{PUBLIC_HOST}:{PUBLIC_PORT}'.encode())
        body = body.replace(b'http://localhost:8992', f'http://{PUBLIC_HOST}:{PUBLIC_PORT}'.encode())
        new_body, delta = inject_polyfill(headers, body)
        if delta > 0:
            htxt = re.sub(r'(?i)content-length:\s*\d+', f'Content-Length: {len(new_body)}', htxt)
        # Ensure Connection: close so browsers know the response is complete
        if not re.search(r'(?i)^connection:', htxt, re.MULTILINE):
            htxt = htxt.rstrip() + '\r\nConnection: close'
        new_headers = htxt.encode('ascii', errors='replace')
        return new_headers + b'\r\n\r\n' + new_body
    except Exception:
        return resp

def handle(client, addr):
    backend = None
    try:
        req = recv_header(client)
        if not req:
            return
        is_ws = b'upgrade: websocket' in req.lower()
        head, _, rest = req.partition(b'\r\n\r\n')
        clen = 0
        for line in head.split(b'\r\n')[1:]:
            if line.lower().startswith(b'content-length:'):
                try: clen = int(line.split(b':',1)[1].strip())
                except: clen = 0
        while len(rest) < clen:
            more = client.recv(min(65536, clen-len(rest)))
            if not more: break
            req += more; rest += more

        rewritten = rewrite_req(req)
        backend = socket.create_connection((BACKEND_HOST, BACKEND_PORT), timeout=15)
        backend.sendall(rewritten)

        if is_ws:
            a, b = client, backend
            a.setblocking(False); b.setblocking(False)
            sel = selectors.DefaultSelector()
            sel.register(a, selectors.EVENT_READ, b)
            sel.register(b, selectors.EVENT_READ, a)
            while True:
                events = sel.select(timeout=60)
                if not events: break
                for key, _ in events:
                    try:
                        data = key.fileobj.recv(65536)
                        if not data: return
                        key.data.sendall(data)
                    except Exception: return
        else:
            hdr = recv_header(backend)
            if not hdr:
                return
            # Auto-refresh auth on 401
            if b'401' in hdr.split(b'\r\n')[0] and _operon_auth is not None:
                print('[auth] got 401, refreshing...', flush=True)
                old = _operon_auth
                threading.Thread(target=refresh_auth, daemon=True).start()
            hend = hdr.index(b'\r\n\r\n') + 4
            body_part = hdr[hend:]
            hdr_only = hdr[:hend]
            cl_match = re.search(rb'(?i)content-length:\s*(\d+)', hdr_only)
            if cl_match:
                total_body = int(cl_match.group(1))
                remaining = total_body - len(body_part)
                while remaining > 0:
                    chunk = backend.recv(min(65536, remaining))
                    if not chunk:
                        break
                    body_part += chunk
                    remaining -= len(chunk)
                resp = rewrite_resp(hdr_only + body_part)
                client.sendall(resp)
            else:
                client.sendall(rewrite_resp(hdr))
                while True:
                    data = backend.recv(65536)
                    if not data: break
                    client.sendall(data)
    except Exception:
        try:
            client.sendall(b'HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nproxy error')
        except Exception: pass
    finally:
        try: client.close()
        except Exception: pass
        try: backend.close()
        except Exception: pass

def main():
    print(f'CSSwitch proxy v9 {LISTEN_HOST}:{LISTEN_PORT} -> {BACKEND_HOST}:{BACKEND_PORT}', flush=True)
    print(f'  PUBLIC_HOST={PUBLIC_HOST}', flush=True)
    # Auto-login on startup
    if refresh_auth():
        print('[auth] startup login ok', flush=True)
    else:
        print('[auth] WARNING: startup login failed — will retry on requests', flush=True)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((LISTEN_HOST, LISTEN_PORT))
    s.listen(128)
    print(f'[proxy] listening on {LISTEN_HOST}:{LISTEN_PORT}', flush=True)
    while True:
        c, a = s.accept()
        threading.Thread(target=handle, args=(c,a), daemon=True).start()

if __name__ == '__main__':
    main()
