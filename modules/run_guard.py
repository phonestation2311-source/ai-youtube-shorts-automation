"""
Run Guard - safety helpers for unattended runs.

* RunLock            - only one run at a time (stale locks are cleared)
* story history      - avoid making the same story twice
* upload ledger      - never upload the same video/title twice
* notify()           - clear failure messages (log file, GitHub, optional webhook)
* safe_upload()      - uploads ONLY if UPLOAD_ENABLED and UPLOAD_APPROVED are both true

State lives in the state/ folder (git-ignored). Override with STATE_DIR=/path.
"""

import hashlib
import json
import os
import re
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
            if age < LOCK_STALE_SECONDS:
                raise AlreadyRunning(f"Another run started {int(age)}s ago (lock: {self.path.name})")
            log.warning("Removing stale lock file (older than 3 hours).")
            self.path.unlink(missing_ok=True)
        fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            f.write(f"{os.getpid()} {_now()}")
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


def already_uploaded(video_path: str, title: str):
    """Return a reason string if this video/title was uploaded before, else ""."""
    ledger = _read_json(state_dir() / "upload_ledger.json", [])
    sha = file_sha256(video_path) if os.path.exists(video_path) else ""
    nt = _norm_title(title)
    for item in ledger:
        if sha and item.get("sha256") == sha:
            return f"same video file already uploaded as {item.get('video_id')}"
        if nt and item.get("title_norm") == nt:
            return f"same title already uploaded as {item.get('video_id')}"
    return ""


def record_upload(video_path: str, title: str, video_id: str):
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
    })
    _write_json(path, ledger)


def channel_has_title(title: str, youtube=None, max_items: int = 50):
    """Check the channel's recent uploads for the same title.
    Returns True/False, or None if the check could not be done."""
    try:
        if youtube is None:
            from modules.youtube_upload import get_authenticated_service
            youtube = get_authenticated_service()
        if youtube is None:
            return None
        ch = youtube.channels().list(part="contentDetails", mine=True).execute()
        items = ch.get("items") or []
        if not items:
            return None
        uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        resp = youtube.playlistItems().list(part="snippet", playlistId=uploads, maxResults=max_items).execute()
        nt = _norm_title(title)
        return any(_norm_title(i["snippet"].get("title", "")) == nt for i in resp.get("items", []))
    except Exception as e:
        log.warning(f"Could not check channel for duplicates ({type(e).__name__}).")
        return None


# ------------------------------------------------------------------
# Upload gate + safe upload
# ------------------------------------------------------------------
def _truthy(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes", "on")


def public_approved() -> bool:
    """Public videos need a THIRD, separate approval: UPLOAD_PUBLIC_APPROVED=true."""
    return _truthy("UPLOAD_PUBLIC_APPROVED")


def upload_privacy() -> str:
    """Privacy for uploads. Default and fallback is always 'private'."""
    p = os.getenv("UPLOAD_PRIVACY", "private").strip().lower()
    if p not in ("private", "unlisted", "public"):
        p = "private"
    if p == "public" and not public_approved():
        log.warning("Public upload requested but UPLOAD_PUBLIC_APPROVED is not true - using private.")
        p = "private"
    return p


def upload_gate_open() -> bool:
    return bool(getattr(settings, "UPLOAD_ENABLED", False)) and bool(getattr(settings, "UPLOAD_APPROVED", False))


def safe_upload(result: dict) -> dict:
    """Upload a finished video ONLY if both gates are on and it is not a duplicate."""
    out = {"uploaded": False, "video_id": "", "reason": ""}
    if not upload_gate_open():
        out["reason"] = "upload gate closed (UPLOAD_ENABLED and UPLOAD_APPROVED must both be true)"
        log.info(f"Not uploading: {out['reason']}")
        return out

    video_path = result.get("video_path", "")
    meta = _read_json(Path(result.get("metadata_path", "")), {}) if result.get("metadata_path") else {}
    title = meta.get("title", "")
    if not video_path or not os.path.exists(video_path) or not title:
        out["reason"] = "missing video file or title"
        return out

    dup = already_uploaded(video_path, title)
    if not dup and channel_has_title(title):
        dup = "a video with the same title is already on the channel"
    if dup:
        out["reason"] = f"duplicate - {dup}"
        log.warning(f"Not uploading: {out['reason']}")
        return out

    from modules.youtube_upload import upload_video
    video_id = upload_video(
        video_path=video_path,
        title=title,
        description=meta.get("description", ""),
        tags=meta.get("tags", []),
        privacy=upload_privacy(),
    )
    if video_id:
        record_upload(video_path, title, video_id)
        out.update(uploaded=True, video_id=video_id)
    else:
        out["reason"] = "upload failed (see logs/automation.log)"
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
