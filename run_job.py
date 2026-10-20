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


def publish_check() -> int:
    """Publishing dry run: checks login, channel, gates, privacy and the newest
    video's metadata/duplicates WITHOUT uploading anything. Secrets are never shown."""
    print("Publishing dry run - nothing will be uploaded")
    problems = []
    enabled = getattr(settings, "UPLOAD_ENABLED", False)
    approved = getattr(settings, "UPLOAD_APPROVED", False)
    print(f"  Upload gate: UPLOAD_ENABLED={enabled}, UPLOAD_APPROVED={approved}"
          f" -> {'OPEN' if run_guard.upload_gate_open() else 'CLOSED (safe)'}")
    print(f"  Privacy used for uploads: {run_guard.upload_privacy()}")
    made_for_kids = getattr(settings, "MADE_FOR_KIDS", None)
    print(f"  Made for kids flag: {made_for_kids}")
    if made_for_kids is not True:
        problems.append("MADE_FOR_KIDS must be True for this children's channel")

    yt = None
    if not os.path.exists(settings.YOUTUBE_TOKEN_FILE):
        problems.append("YouTube token missing (run: python -m modules.youtube_upload --auth)")
    else:
        from modules.youtube_upload import get_authenticated_service
        yt = get_authenticated_service()  # never interactive here; refreshes if needed
        if yt is None:
            problems.append("YouTube token invalid or expired (run: python -m modules.youtube_upload --auth)")
        else:
            try:
                resp = yt.channels().list(part="snippet", mine=True).execute()
                items = resp.get("items") or []
                print(f"  YouTube channel: {items[0]['snippet']['title'] if items else '(none found)'}")
                if not items:
                    problems.append("this Google account has no YouTube channel")
            except Exception as e:
                problems.append(f"YouTube API check failed ({type(e).__name__})")

    videos = sorted(settings.OUTPUT_DIR.glob("short_*.mp4"), key=lambda x: x.stat().st_mtime)
    if not videos:
        problems.append("no finished video in output/")
    else:
        from tools.check_outputs import check_video
        latest = videos[-1]
        vp = check_video(latest)
        if vp:
            problems.append(f"{latest.name}: " + "; ".join(vp))
        meta = run_guard._read_json(latest.with_suffix(".json"), {})
        title = meta.get("title", "")
        dup = run_guard.already_uploaded(str(latest), title)
        if not dup and yt is not None and run_guard.channel_has_title(title, yt):
            dup = "same title already on the channel"
        print(f"  Newest video: {latest.name} | {title}")
        if dup:
            print(f"  Duplicate check: would SKIP ({dup})")
        else:
            print("  Duplicate check: not uploaded before")
        if run_guard.upload_gate_open() and not dup:
            print(f"  A scheduled run WOULD upload it as {run_guard.upload_privacy()}, made for kids.")
        else:
            print("  A scheduled run would NOT upload it.")

    for p_ in problems:
        print(f"  NO  {p_}")
    print("PUBLISH-READY" if not problems else "NOT PUBLISH-READY")
    return 0 if not problems else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Unattended Hindi kids Shorts runner (uploads gated)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--once", action="store_true", help="make one video now (default)")
    g.add_argument("--loop", action="store_true", help="repeat every --every-hours (machine must stay on)")
    g.add_argument("--check", action="store_true", help="readiness check, no API calls")
    g.add_argument("--publish-check", action="store_true", help="publishing dry run, never uploads")
    p.add_argument("--every-hours", type=float, default=float(os.getenv("RUN_EVERY_HOURS", 24)))
    p.add_argument("--max-attempts", type=int, default=None)
    p.add_argument("--niche", type=int, default=None, help=f"0-{len(settings.NICHES) - 1}")
    a = p.parse_args(argv)

    if a.check:
        return check_ready()
    if a.publish_check:
        return publish_check()
    if a.loop:
        log.info(f"Loop mode: one video every {a.every_hours}h (stops if this machine/Codespace stops).")
        while True:
            run_once(a.max_attempts, niche_index=a.niche)
            time.sleep(max(0.1, a.every_hours) * 3600)
    return run_once(a.max_attempts, niche_index=a.niche)


if __name__ == "__main__":
    sys.exit(main())
