"""
Turn the optional GitHub secret YOUTUBE_TOKEN_B64 into config/youtube_token.pickle.

* Never prints the secret or the token.
* Never fails the workflow: video generation continues without YouTube.
* Accepts common copy/paste damage: spaces, line breaks (also Windows CRLF),
  surrounding quotes, URL-safe alphabet, missing '=' padding, double encoding.
* Writes token_ok=true/false to $GITHUB_OUTPUT for later steps.

Make the secret value in the Codespace (prints nothing):
    base64 -w0 config/youtube_token.pickle > /tmp/yt_token_b64.txt
"""

import base64
import binascii
import os
import pickle
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PICKLE_MAGIC = b"\x80"


def decode_token(raw: str):
    """Return (bytes or None, reason)."""
    if not raw or not raw.strip():
        return None, "secret not provided"
    s = raw.strip().strip('"').strip("'")
    if s.startswith("data:") and "," in s:
        s = s.split(",", 1)[1]
    s = re.sub(r"\s+", "", s).replace("-", "+").replace("_", "/")
    if not s or not re.fullmatch(r"[A-Za-z0-9+/=]+", s):
        return None, "secret contains characters that are not base64"
    s = s.rstrip("=")
    s += "=" * (-len(s) % 4)
    try:
        data = base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError):
        return None, "secret is not valid base64"
    if not data.startswith(PICKLE_MAGIC):  # maybe encoded twice
        try:
            inner = re.sub(rb"\s+", b"", data)
            inner += b"=" * (-len(inner) % 4)
            inner = base64.b64decode(inner, validate=True)
            if inner.startswith(PICKLE_MAGIC):
                data = inner
        except (binascii.Error, ValueError):
            pass
    return data, ""


def validate_token(data: bytes) -> str:
    """Return "" if data is a usable saved Google login, else a reason."""
    try:
        obj = pickle.loads(data)
    except Exception:
        return "decoded secret is not a saved YouTube token"
    if not hasattr(obj, "refresh_token"):
        return "decoded secret is not a Google login token"
    if not getattr(obj, "refresh_token", None):
        return "token has no refresh token - sign in again with: python -m modules.youtube_upload --auth"
    return ""


def main() -> int:
    from config.settings import YOUTUBE_TOKEN_FILE

    raw = os.getenv("YOUTUBE_TOKEN_B64", "")
    data, why = decode_token(raw)
    if data is not None:
        why = validate_token(data)
    ok = data is not None and not why
    if ok:
        path = Path(YOUTUBE_TOKEN_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        print("YouTube token: OK (saved for this run; contents not shown)")
    else:
        print(f"YouTube token: not used ({why}). Video generation continues; no upload possible this run.")
        if raw.strip() and os.getenv("GITHUB_ACTIONS") == "true":
            print(f"::warning title=YouTube token::{why}. Re-create the YOUTUBE_TOKEN_B64 secret (see README).")
    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"token_ok={'true' if ok else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
