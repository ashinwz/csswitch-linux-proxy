#!/usr/bin/env python3
# 虚拟 OAuth 伪造器（make-virtual-oauth.mjs 的 Python 移植，逻辑严格一致）。
# 在【沙箱】auth_dir 写本地自造登录凭证，让 Claude Science 认为已登录（不联网、零真实凭证）。
#
# v2 令牌格式（与二进制 eH.decryptToken 一致）：
#   "v2:" + base64( IV(12) ‖ AES-256-GCM(密文) ‖ authTag(16) )
#   derivedKey = HKDF-SHA256(ikm=base64decode(OAUTH_ENCRYPTION_KEY), salt=b"", info=b"operon:aes-256-gcm:oauth", L=32)
#   AAD = b"v2:oauth"
#   明文 = json.dumps(tokenBlob)
#
# 用法: python3 make-virtual-oauth.py --auth-dir <沙箱/.claude-science> [--email virtual@localhost.invalid] [--force]
import argparse, base64, json, os, secrets, sys, uuid
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_NAMES = ["ANTHROPIC_API_KEY_ENCRYPTION_KEY", "OAUTH_ENCRYPTION_KEY",
             "JWT_SIGNING_SECRET", "USER_SECRET_ENCRYPTION_KEY"]

def real_ancestor(p):
    cur = os.path.abspath(p); tail = []
    while not os.path.exists(cur):
        tail.insert(0, os.path.basename(cur))
        parent = os.path.dirname(cur)
        if parent == cur: break
        cur = parent
    base = os.path.realpath(cur) if os.path.exists(cur) else cur
    return os.path.join(base, *tail) if tail else base

def assert_not_symlink(p):
    if os.path.islink(p):
        print(f"拒绝：{p} 是符号链接，绝不跟随写入。", file=sys.stderr); sys.exit(3)

def safe_write(path, data, mode):
    assert_not_symlink(path)
    if isinstance(data, str): data = data.encode()
    tmp = os.path.join(os.path.dirname(path), f".tmp-{secrets.token_hex(6)}")
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    try: os.write(fd, data)
    finally: os.close(fd)
    os.replace(tmp, path); os.chmod(path, mode)

def b64_32(): return base64.b64encode(secrets.token_bytes(32)).decode()

def parse_key_file(txt):
    out = {}
    for line in txt.split("\n"):
        i = line.find("=")
        if i <= 0: continue
        v = line[i+1:].strip()
        if v: out[line[:i].strip()] = v
    return out

def hkdf32(ikm):
    return HKDF(algorithm=SHA256(), length=32, salt=b"",
                info=b"operon:aes-256-gcm:oauth").derive(ikm)

def encrypt_v2(plaintext, oauth_key_b64):
    derived = hkdf32(base64.b64decode(oauth_key_b64))
    iv = secrets.token_bytes(12)
    ct = AESGCM(derived).encrypt(iv, plaintext.encode(), b"v2:oauth")
    return "v2:" + base64.b64encode(iv + ct).decode()

def decrypt_v2(body, oauth_key_b64):
    derived = hkdf32(base64.b64decode(oauth_key_b64))
    raw = base64.b64decode(body[len("v2:"):])
    iv, ctag = raw[:12], raw[12:]
    return AESGCM(derived).decrypt(iv, ctag, b"v2:oauth").decode()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auth-dir", required=True)
    ap.add_argument("--email", default="virtual@localhost.invalid")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    resolved = real_ancestor(a.auth_dir)
    real_dir = real_ancestor(os.path.join(os.path.expanduser("~"), ".claude-science"))
    if resolved == real_dir:
        print(f"拒绝：--auth-dir 指向真实凭证目录 {real_dir}。铁律禁止。", file=sys.stderr); sys.exit(3)
    if ".sandbox/" not in resolved and not a.force:
        print(f"拒绝：--auth-dir ({resolved}) 不在 .sandbox/ 下。若确属沙箱可加 --force。", file=sys.stderr); sys.exit(3)
    if not a.email.endswith("localhost.invalid"):
        print(f"拒绝：email 必须以 localhost.invalid 结尾（当前 {a.email}）。", file=sys.stderr); sys.exit(3)

    os.makedirs(resolved, mode=0o700, exist_ok=True)
    key_file = os.path.join(resolved, "encryption.key")
    assert_not_symlink(key_file)
    if os.path.exists(key_file) and not a.force:
        keys = parse_key_file(open(key_file, encoding="utf-8").read())
        for k in KEY_NAMES:
            if not keys.get(k): keys[k] = b64_32()
    else:
        keys = {k: b64_32() for k in KEY_NAMES}
    safe_write(key_file, "\n".join(f"{k}={keys[k]}" for k in KEY_NAMES) + "\n", 0o600)

    account_uuid = str(uuid.uuid4()); org_uuid = str(uuid.uuid4())
    blob = {
        "access_token": "sk-ant-virtual-" + secrets.token_hex(24),
        "refresh_token": "", "api_key": None,
        "token_expires_at": "2099-01-01T00:00:00.000Z",
        "provider": "claude_ai",
        "scopes": "user:inference user:file_upload user:profile user:mcp_servers user:plugins",
        "email": a.email, "account_uuid": account_uuid,
        "subscription_type": "max", "rate_limit_tier": None, "seat_tier": None,
        "org_uuid": org_uuid, "billing_type": None, "has_extra_usage_enabled": False,
    }
    enc_body = encrypt_v2(json.dumps(blob), keys["OAUTH_ENCRYPTION_KEY"])

    tok_dir = os.path.join(resolved, ".oauth-tokens")
    assert_not_symlink(tok_dir)
    os.makedirs(tok_dir, mode=0o700, exist_ok=True)
    try: os.chmod(tok_dir, 0o700)
    except OSError: pass
    for f in os.listdir(tok_dir):
        if f.endswith(".enc"):
            p = os.path.join(tok_dir, f); assert_not_symlink(p); os.unlink(p)
    user_id = "".join(c for c in account_uuid if c.isalnum() or c in "_-")
    safe_write(os.path.join(tok_dir, f"{user_id}.enc"), enc_body, 0o600)

    if json.loads(decrypt_v2(enc_body, keys["OAUTH_ENCRYPTION_KEY"]))["email"] != a.email:
        print("自校验失败", file=sys.stderr); sys.exit(4)

    safe_write(os.path.join(resolved, "active-org.json"),
               json.dumps({"org_uuid": org_uuid}, indent=2) + "\n", 0o600)

    print(json.dumps({"ok": True, "auth_dir": resolved, "email": a.email,
                      "account_uuid": account_uuid, "org_uuid": org_uuid,
                      "enc_file": os.path.join(tok_dir, f"{user_id}.enc"),
                      "selfcheck": "decrypt roundtrip OK"}, indent=2))

if __name__ == "__main__":
    main()
