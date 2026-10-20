"""
Run Guard - safety helpers for unattended runs.

* RunLock            - only one run at a time (stale locks are cleared)
* story history      - avoid making the same story twice
* upload ledger      - never upload the same video/title twice
* notify()           - clear failure messages (log file, GitHub, optional webhook)
* safe_upload()      - uploads ONLY if UPLOAD_ENABLED and UPLOAD_APPROVED are both true;
                       private by default, public only with UPLOAD_PUBLIC_APPROVED=true

State lives in the state/ folder (git-ignored). Override with STATE_DIR=/path.
"""

import hashlib
import json
import os
import re
import socket
import time
from datetime import datetime
from pathlib import Path

import config.settings as settings
from utils import get_logger

log = get_logger("run_guard")

LOCK_STALE_SECONDS = 3 * 3600


def state_dir() -> Path:
    d = Path(os.getenv("STATE_DIR") or (settings.BASE_DIR / "state"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ------------------------------------------------------------------
# Single-run lock
# ------------------------------------------------------------------
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class AlreadyRunning(RuntimeError):
    pass


class RunLock:
    """Prevents two runs at once. A lock older than 3 hours is treated as stale."""

    def __init__(self, name: str = "run"):
        self.path = state_dir() / f"{name}.lock"
        self.acquired = False

    def __enter__(self):
        if self.path.exists():
            age = time.time() - self.path.stat().st_mtime
            stale = age >= LOCK_STALE_SECONDS
            try:  # lock left by a crashed/cancelled run on this machine?
                pid_s, host = self.path.read_text().split()[:2]
                if host == socket.gethostname() and not _pid_alive(int(pid_s)):
                    stale = True
            except (OSError, ValueError):
                pass
            if not stale:
                raise AlreadyRunning(f"Another run started {int(age)}s ago (lock: {self.path.name})")
            log.warning("Removing stale lock file (old, or its run is no longer running).")
            self.path.unlink(missing_ok=True)
        fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            f.write(f"{os.getpid()} {socket.gethostname()} {_now()}")
        self.acquired = True
        return self

    def __exit__(self, *exc):
        if self.acquired:
            self.path.unlink(missing_ok=True)
        return False


# ------------------------------------------------------------------
# Story history (avoid repeats)
# ------------------------------------------------------------------
def _norm_words(text: str) -> set:
    return set(re.findall(r"[ऀ-ॿ]+|[a-zA-Z]+", text or ""))


def is_duplicate_story(story: str, threshold: float = 0.8) -> bool:
    words = _norm_words(story)
    if not words:
        return False
    for item in _read_json(state_dir() / "story_history.json", [])[-300:]:
        old = set(item.get("words", []))
        if old and len(words & old) / len(words | old) >= threshold:
            return True
    return False


def record_story(story: str, idea: str = ""):
    path = state_dir() / "story_history.json"
    hist = _read_json(path, [])
    hist.append({"time": _now(), "idea": idea[:200], "words": sorted(_norm_words(story))})
    _write_json(path, hist[-500:])


# ------------------------------------------------------------------
# Upload ledger (duplicate-upload protection)
# ------------------------------------------------------------------
def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"#\w+", "", title or "")).strip().lower()


def already_uploaded(video_path: str, title: str, cid: str = ""):
    """Return a reason string if this video/story/title was uploaded before, else ""."""
    ledger = _read_json(state_dir() / "upload_ledger.json", [])
    sha = file_sha256(video_path) if os.path.exists(video_path) else ""
    nt = _norm_title(title)
    for item in ledger:
        if cid and item.get("content_id") == cid:
            return f"same story already uploaded as {item.get('video_id')}"
        if sha and item.get("sha256") == sha:
            return f"same video file already uploaded as {item.get('video_id')}"
        if nt and item.get("title_norm") == nt:
            return f"same title already uploaded as {item.get('video_id')}"
    return ""


def record_upload(video_path: str, title: str, video_id: str, cid: str = ""):
    path = state_dir() / "upload_ledger.json"
    ledger = _read_json(path, [])
    if video_id and any(item.get("video_id") == video_id for item in ledger):
        return  # already recorded
    ledger.append({
        "time": _now(),
        "video_id": video_id,
        "title": title,
        "title_norm": _norm_title(title),
        "sha256": file_sha256(video_path) if os.path.exists(video_path) else "",
        "file": Path(video_path).name,
        "content_id": cid,
    })
    _write_json(path, ledger)


# ------------------------------------------------------------------
# Publishing mode + safe upload
# ------------------------------------------------------------------
# Channel the automation is allowed to upload to (not a secret).
EXPECTED_CHANNEL_TITLE = "ToonMasti Hindi TV 1M"
UPLOAD_ATTEMPTS = 2           # upload tries per run (no endless loops)
UPLOAD_RETRY_WAIT = 30        # seconds between tries


def _truthy(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes", "on")


def public_approved() -> bool:
    """Public publishing needs its own explicit approval: UPLOAD_PUBLIC_APPROVED=true."""
    return _truthy("UPLOAD_PUBLIC_APPROVED")


def upload_gate_open() -> bool:
    return bool(getattr(settings, "UPLOAD_ENABLED", False)) and bool(getattr(settings, "UPLOAD_APPROVED", False))


def resolve_publish_mode() -> dict:
    """The ONE place that decides how videos are published.

    disabled : UPLOAD_ENABLED and UPLOAD_APPROVED are not both true
    private  : both true, UPLOAD_PRIVACY=private (default)
    public   : both true, UPLOAD_PRIVACY=public AND UPLOAD_PUBLIC_APPROVED=true
    Anything else is a configuration error - nothing is uploaded and the run fails.
    There is no silent fallback between private and public.
    """
    wanted = (os.getenv("UPLOAD_PRIVACY", "") or "private").strip().lower()
    mode = {"enabled": upload_gate_open(), "privacy": wanted, "error": ""}
    if not mode["enabled"]:
        mode["privacy"] = ""
        return mode
    if wanted not in ("private", "public"):
        mode["error"] = f"UPLOAD_PRIVACY must be 'private' or 'public' (got '{wanted}')"
    elif wanted == "public" and not public_approved():
        mode["error"] = "UPLOAD_PRIVACY=public needs UPLOAD_PUBLIC_APPROVED=true - nothing uploaded"
    return mode


def upload_privacy() -> str:
    """Effective privacy, or '' when uploads are disabled or misconfigured."""
    m = resolve_publish_mode()
    return "" if (not m["enabled"] or m["error"]) else m["privacy"]


def describe_mode(mode: dict = None) -> str:
    mode = mode or resolve_publish_mode()
    if not mode["enabled"]:
        return "DISABLED (videos are made, nothing is uploaded)"
    if mode["error"]:
        return f"CONFIG ERROR: {mode['error']}"
    if mode["privacy"] == "public":
        return "PUBLIC automatic publishing (every new video becomes publicly visible)"
    return "PRIVATE automatic uploads (only you can see the videos)"


def content_id(story: str) -> str:
    """Durable ID of a story: same story text -> same ID, on any machine."""
    text = re.sub(r"\s+", " ", story or "").strip()
    return "ksid" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else ""


def verify_channel(youtube) -> dict:
    """Make sure we are logged in to the right channel before uploading."""
    want_id = os.getenv("EXPECTED_CHANNEL_ID", "").strip()
    want_title = os.getenv("EXPECTED_CHANNEL_TITLE", "").strip() or EXPECTED_CHANNEL_TITLE
    try:
        items = youtube.channels().list(part="snippet", mine=True).execute().get("items") or []
    except Exception as e:
        return {"ok": False, "title": "", "id": "", "reason": f"channel lookup failed ({type(e).__name__})"}
    if not items:
        return {"ok": False, "title": "", "id": "", "reason": "this Google login has no YouTube channel"}
    ch = items[0]
    title, cid = ch.get("snippet", {}).get("title", ""), ch.get("id", "")
    ok = (cid == want_id) if want_id else (title.strip().lower() == want_title.lower())
    reason = "" if ok else f"logged in to '{title}' but expected '{want_id or want_title}'"
    return {"ok": ok, "title": title, "id": cid, "reason": reason}


def find_on_channel(youtube, title: str, cid: str, max_items: int = 50):
    """Look through the channel's recent uploads (private ones too) for this
    story's content ID tag or exact title. Returns the video ID, "" if not
    found, or None if the check could not be done."""
    try:
        ch = youtube.channels().list(part="contentDetails", mine=True).execute()
        items = ch.get("items") or []
        if not items:
            return None
        uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        pl = youtube.playlistItems().list(part="contentDetails", playlistId=uploads,
                                          maxResults=max_items).execute().get("items", [])
        ids = [i["contentDetails"]["videoId"] for i in pl]
        if not ids:
            return ""
        vids = youtube.videos().list(part="snippet", id=",".join(ids)).execute().get("items", [])
        nt = _norm_title(title)
        for v in vids:
            sn = v.get("snippet", {})
            if (cid and cid in (sn.get("tags") or [])) or (nt and _norm_title(sn.get("title", "")) == nt):
                return v.get("id", "")
        return ""
    except Exception as e:
        log.warning(f"Could not check the channel for duplicates ({type(e).__name__}).")
        return None


def channel_has_title(title: str, youtube=None, max_items: int = 50):
    """Backwards-compatible wrapper: True/False, or None if unknown."""
    if youtube is None:
        from modules.youtube_upload import get_authenticated_service
        youtube = get_authenticated_service()
    if youtube is None:
        return None
    found = find_on_channel(youtube, title, "", max_items)
    return None if found is None else bool(found)


def validate_video(video_path: str) -> list:
    """Full check before upload: size, FPS, length, audio, metadata AND a full decode."""
    from tools.check_outputs import check_video
    return check_video(Path(video_path), full_decode=True)


def _update_metadata(meta_path: str, **fields):
    if meta_path and os.path.exists(meta_path):
        meta = _read_json(Path(meta_path), {})
        meta.update(fields)
        _write_json(Path(meta_path), meta)


def safe_upload(result: dict) -> dict:
    """Upload one finished video according to resolve_publish_mode().

    status is one of: upload_disabled, config_error, video_invalid, duplicate,
    auth_failed, wrong_channel, upload_failed, uploaded
    """
    out = {"status": "", "uploaded": False, "video_id": "", "privacy": "", "reason": ""}
    mode = resolve_publish_mode()
    if not mode["enabled"]:
        out.update(status="upload_disabled",
                   reason="upload gate closed (UPLOAD_ENABLED and UPLOAD_APPROVED must both be true)")
        log.info(f"Not uploading: {out['reason']}")
        return out
    if mode["error"]:
        out.update(status="config_error", reason=mode["error"])
        log.error(f"Not uploading: {out['reason']}")
        return out
    out["privacy"] = mode["privacy"]
    log.info(f"Publishing mode: {describe_mode(mode)}")

    video_path = result.get("video_path", "")
    meta_path = result.get("metadata_path", "")
    meta = _read_json(Path(meta_path), {}) if meta_path else {}
    title = meta.get("title", "")
    if not video_path or not os.path.exists(video_path) or not title:
        out.update(status="video_invalid", reason="missing video file or title")
        return out
    problems = validate_video(video_path)
    if problems:
        out.update(status="video_invalid", reason="; ".join(problems))
        log.error(f"Not uploading - video failed checks: {out['reason']}")
        return out

    cid = content_id(meta.get("story", "")) or content_id(file_sha256(video_path))
    dup = already_uploaded(video_path, title, cid)
    if dup:
        out.update(status="duplicate", reason=dup)
        log.warning(f"Not uploading (duplicate): {dup}")
        return out

    from modules.youtube_upload import get_authenticated_service, upload_video
    youtube = get_authenticated_service()
    if youtube is None:
        out.update(status="auth_failed", reason="YouTube login missing, expired or revoked - "
                   "reconnect with: python -m modules.youtube_upload --auth, then update the YOUTUBE_TOKEN_B64 secret")
        log.error(out["reason"])
        return out
    ch = verify_channel(youtube)
    if not ch["ok"]:
        out.update(status="wrong_channel", reason=ch["reason"])
        log.error(f"Not uploading: {ch['reason']}")
        return out
    log.info(f"Uploading to channel: {ch['title']}")

    found = find_on_channel(youtube, title, cid)
    if found:
        record_upload(video_path, title, found, cid)
        out.update(status="duplicate", video_id=found, reason=f"already on the channel as {found}")
        log.warning(f"Not uploading (duplicate): {out['reason']}")
        return out

    tags = list(dict.fromkeys(list(meta.get("tags", [])) + [cid]))
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        video_id = upload_video(
            video_path=video_path,
            title=title,
            description=meta.get("description", ""),
            tags=tags,
            privacy=mode["privacy"],
            youtube=youtube,
        )
        if not video_id:
            # The request may have failed AFTER YouTube accepted the video:
            # look before trying again, so a retry never creates a duplicate.
            time.sleep(UPLOAD_RETRY_WAIT if attempt < UPLOAD_ATTEMPTS else 0)
            video_id = find_on_channel(youtube, title, cid) or ""
            if video_id:
                log.warning(f"Upload reported an error but the video is on the channel: {video_id}")
        if video_id:
            record_upload(video_path, title, video_id, cid)
            _update_metadata(meta_path, uploaded=True, video_id=video_id, privacy=mode["privacy"],
                             channel=ch["title"], content_id=cid)
            out.update(status="uploaded", uploaded=True, video_id=video_id)
            log.info(f"Uploaded as {mode['privacy']}: https://youtube.com/shorts/{video_id}")
            return out
        log.warning(f"Upload attempt {attempt}/{UPLOAD_ATTEMPTS} failed.")

    out.update(status="upload_failed", reason=f"upload failed after {UPLOAD_ATTEMPTS} attempts (see logs/automation.log)")
    _update_metadata(meta_path, uploaded=False, upload_error=out["reason"])
    return out


# ------------------------------------------------------------------
# Run history + notifications
# ------------------------------------------------------------------
def record_run(status: dict):
    status = dict(status, time=_now())
    with open(state_dir() / "run_history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(status, ensure_ascii=False) + "\n")
    _write_json(state_dir() / "last_run.json", status)


def notify(subject: str, message: str, level: str = "error"):
    """Tell the owner about a problem. Never includes secrets.
    - always: log + state/last_failure.txt
    - GitHub Actions: error annotation (GitHub also emails you when the run fails)
    - optional: NOTIFY_WEBHOOK_URL (Discord/Slack style) or NTFY_TOPIC (free ntfy.sh push)
    """
    text = f"[Kids Shorts] {subject}: {message}"[:1500]
    (log.error if level == "error" else log.info)(text)
    if level == "error":
        try:
            (state_dir() / "last_failure.txt").write_text(f"{_now()}\n{text}\n", encoding="utf-8")
        except OSError:
            pass
        if os.getenv("GITHUB_ACTIONS") == "true":
            print(f"::error title={subject}::{message[:500]}")

    try:
        import requests
        hook = os.getenv("NOTIFY_WEBHOOK_URL", "").strip()
        if hook:
            requests.post(hook, json={"content": text, "text": text}, timeout=10)
        topic = os.getenv("NTFY_TOPIC", "").strip()
        if topic:
            requests.post(f"https://ntfy.sh/{topic}", data=text.encode("utf-8"),
                          headers={"Title": subject}, timeout=10)
    except Exception as e:
        log.warning(f"Notification could not be sent ({type(e).__name__}).")
