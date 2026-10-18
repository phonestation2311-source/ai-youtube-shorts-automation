"""
Unattended job runner for Hindi kids' animal-story Shorts.

    python run_job.py --check            # readiness check (no API calls, free)
    python run_job.py --once             # make ONE video now (used by GitHub Actions)
    python run_job.py --loop             # keep running every RUN_EVERY_HOURS (only while this machine is on)

Safety:
* Videos are always created locally first.
* Upload happens ONLY if UPLOAD_ENABLED=true AND UPLOAD_APPROVED=true, and the
  video/title was never uploaded before.
* Only one run at a time; limited retries; failures are logged and notified.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config.settings as settings  # noqa: E402
from modules import run_guard  # noqa: E402
from utils import get_logger  # noqa: E402

log = get_logger("run_job")


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, default)))
    except ValueError:
        return default


def _next_niche() -> dict:
    """Rotate through the niches across runs."""
    path = run_guard.state_dir() / "niche_counter.json"
    n = run_guard._read_json(path, {"next": 0}).get("next", 0)
    run_guard._write_json(path, {"next": n + 1})
    return settings.NICHES[n % len(settings.NICHES)]


def run_once(max_attempts: int = None, retry_delay: int = None, niche_index: int = None) -> int:
    """Make one video (with limited retries), then upload only if allowed. Returns exit code."""
    from main import create_single_video

    max_attempts = max_attempts or _int_env("MAX_ATTEMPTS", 2)
    retry_delay = _int_env("RETRY_DELAY_SECONDS", 60) if retry_delay is None else retry_delay
    errors = []

    try:
        with run_guard.RunLock():
            for attempt in range(1, max_attempts + 1):
                niche = settings.NICHES[niche_index] if niche_index is not None else _next_niche()
                log.info(f"=== Run attempt {attempt}/{max_attempts} ({niche['name']}) ===")
                try:
                    result = create_single_video(niche=niche, dry_run=True)  # never uploads here
                except Exception as e:  # create_single_video normally catches, this is a safety net
                    result = {"success": False, "error": f"{type(e).__name__}: {e}"}

                if result.get("success"):
                    meta = {}
                    if result.get("metadata_path"):
                        meta = run_guard._read_json(Path(result["metadata_path"]), {})
                    story = meta.get("story", "")
                    if story and run_guard.is_duplicate_story(story):
                        errors.append("story too similar to an earlier one")
                        log.warning("Story is too similar to an earlier video - trying again.")
                    else:
                        if story:
                            run_guard.record_story(story, meta.get("idea", ""))
                        upload = run_guard.safe_upload(result)
                        run_guard.record_run({
                            "status": "ok",
                            "video": Path(result.get("video_path", "")).name,
                            "title": meta.get("title", ""),
                            "duration": result.get("duration"),
                            "uploaded": upload["uploaded"],
                            "video_id": upload["video_id"],
                            "upload_note": upload["reason"],
                            "attempts": attempt,
                        })
                        log.info(f"Run finished OK: {result.get('video_path')}")
                        if upload["reason"].startswith(("duplicate", "upload failed", "missing")):
                            run_guard.notify("Upload skipped", upload["reason"], level="info")
                        return 0
                else:
                    errors.append(result.get("error") or "unknown error")
                    log.error(f"Attempt {attempt} failed: {errors[-1]}")

                if attempt < max_attempts and retry_delay:
                    log.info(f"Waiting {retry_delay}s before retrying...")
                    time.sleep(retry_delay)

    except run_guard.AlreadyRunning as e:
        log.warning(f"Skipped: {e}")
        run_guard.record_run({"status": "skipped", "reason": str(e)})
        return 0
    except Exception as e:
        errors.append(f"{type(e).__name__}: {e}")

    msg = f"All {max_attempts} attempt(s) failed. Last error: {errors[-1] if errors else 'unknown'}"
    run_guard.record_run({"status": "failed", "errors": errors[-3:]})
    run_guard.notify("Video run FAILED", msg)
    return 1


def check_ready() -> int:
    """Free readiness check: settings, tools, keys present (values never shown)."""
    def key_ok(name):
        v = os.getenv(name, "").strip()
        return bool(v) and not v.startswith("YOUR_")

    font_ok = False
    try:
        font_ok = bool(subprocess.run(["fc-list", ":lang=hi", "family"], capture_output=True,
                                      text=True, timeout=10).stdout.strip())
    except Exception:
        pass
    checks = {
        "GROQ_API_KEY set": key_ok("GROQ_API_KEY"),
        "PIXABAY_API_KEY set": key_ok("PIXABAY_API_KEY"),
        "PEXELS_API_KEY set (optional backup)": key_ok("PEXELS_API_KEY"),
        "ffmpeg installed": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
        "Hindi font installed": font_ok,
        "YouTube token saved": os.path.exists(settings.YOUTUBE_TOKEN_FILE),
        "Upload gate CLOSED (safe)": not run_guard.upload_gate_open(),
    }
    required = ["GROQ_API_KEY set", "PIXABAY_API_KEY set", "ffmpeg installed", "Hindi font installed"]
    for name, ok in checks.items():
        print(f"  {'OK ' if ok else 'NO '} {name}")
    print(f"  Upload gate: UPLOAD_ENABLED={getattr(settings, 'UPLOAD_ENABLED', False)}, "
          f"UPLOAD_APPROVED={getattr(settings, 'UPLOAD_APPROVED', False)}")
    last = run_guard._read_json(run_guard.state_dir() / "last_run.json", None)
    if last:
        print(f"  Last run: {json.dumps(last, ensure_ascii=False)[:200]}")
    ready = all(checks[k] for k in required)
    print("READY" if ready else "NOT READY - fix the NO items above")
    return 0 if ready else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Unattended Hindi kids Shorts runner (uploads gated)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--once", action="store_true", help="make one video now (default)")
    g.add_argument("--loop", action="store_true", help="repeat every --every-hours (machine must stay on)")
    g.add_argument("--check", action="store_true", help="readiness check, no API calls")
    p.add_argument("--every-hours", type=float, default=float(os.getenv("RUN_EVERY_HOURS", 24)))
    p.add_argument("--max-attempts", type=int, default=None)
    p.add_argument("--niche", type=int, default=None, help=f"0-{len(settings.NICHES) - 1}")
    a = p.parse_args(argv)

    if a.check:
        return check_ready()
    if a.loop:
        log.info(f"Loop mode: one video every {a.every_hours}h (stops if this machine/Codespace stops).")
        while True:
            run_once(a.max_attempts, niche_index=a.niche)
            time.sleep(max(0.1, a.every_hours) * 3600)
    return run_once(a.max_attempts, niche_index=a.niche)


if __name__ == "__main__":
    sys.exit(main())
