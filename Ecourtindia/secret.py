"""
API key resolution for the eCourtsIndia integration.

Resolution order:
  1. ECOURTS_API_KEY environment variable (preferred — set it on Render /
     in .env and it always wins).
  2. An obfuscated key embedded below, so the app runs out-of-the-box on a
     fresh deploy without any manual env setup.

NOTE ON "ENCRYPTION": the embedded key is XOR-obfuscated with an in-repo
passphrase and base64-encoded. This keeps the raw token from being plainly
greppable in the source, but it is NOT real secrecy — anyone with the repo
can reverse it (the passphrase is right here). It exists only to satisfy the
"don't store it in plaintext" request and to let the app self-configure.
For real protection, set ECOURTS_API_KEY as a secret env var on Render and
leave the embedded blob empty / rotate the key.
"""

import base64
import hashlib
import os

_PASSPHRASE = "ecourtindia-lawapp-v1"

# XOR(base64) of the partner token. Override via ECOURTS_API_KEY to ignore this.
_EMBEDDED_BLOB = "00tbPaKA7Onj3xka/c1vIHHMJDgCrm6El7OdELdn9/Cj8vQ5ZEgsOtU="


def _keystream(n, passphrase):
    out = b""
    counter = 0
    while len(out) < n:
        out += hashlib.sha256(passphrase.encode() + counter.to_bytes(4, "big")).digest()
        counter += 1
    return out[:n]


def _deobfuscate(blob, passphrase):
    if not blob:
        return ""
    raw = base64.b64decode(blob)
    ks = _keystream(len(raw), passphrase)
    return bytes(a ^ b for a, b in zip(raw, ks)).decode()


def obfuscate(plaintext, passphrase=_PASSPHRASE):
    """Helper to regenerate _EMBEDDED_BLOB if the key is ever rotated."""
    data = plaintext.encode()
    ks = _keystream(len(data), passphrase)
    return base64.b64encode(bytes(a ^ b for a, b in zip(data, ks))).decode()


def get_api_key():
    """Return the env-var key if set, else the embedded (de-obfuscated) one."""
    env = os.getenv("ECOURTS_API_KEY", "").strip()
    if env:
        return env
    try:
        return _deobfuscate(_EMBEDDED_BLOB, _PASSPHRASE)
    except Exception:
        return ""
