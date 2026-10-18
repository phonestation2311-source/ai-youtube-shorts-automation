"""
Check finished videos in output/ WITHOUT calling any API (free).

    python -m tools.check_outputs            # check all videos
    python -m tools.check_outputs --latest   # check only the newest

Checks: 1080x1920, ~30 FPS, 20-59 s, has audio, metadata JSON (title with
#Shorts, description, tags, Hindi story, made_for_kids) and thumbnail.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import OUTPUT_DIR, VIDEO_HEIGHT, VIDEO_MAX_DURATION, VIDEO_WIDTH  # noqa: E402


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    return json.loads(out.stdout or "{}")


def _deva_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha() or "ऀ" <= c <= "ॿ"]
    return sum("ऀ" <= c <= "ॿ" for c in letters) / len(letters) if letters else 0.0


def check_video(mp4: Path) -> list:
    problems = []
    info = probe(mp4)
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not v:
        return ["no video stream (file broken?)"]
    if (v.get("width"), v.get("height")) != (VIDEO_WIDTH, VIDEO_HEIGHT):
        problems.append(f"size {v.get('width')}x{v.get('height')} (want {VIDEO_WIDTH}x{VIDEO_HEIGHT})")
    num, _, den = (v.get("r_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0
    if abs(fps - 30) > 0.5:
        problems.append(f"fps {fps:.1f} (want 30)")
    dur = float(info.get("format", {}).get("duration", 0))
    if not 20 <= dur <= VIDEO_MAX_DURATION:
        problems.append(f"duration {dur:.1f}s (want 20-{VIDEO_MAX_DURATION}s)")
    if not any(s.get("codec_type") == "audio" for s in streams):
        problems.append("no audio")

    meta_path = mp4.with_suffix(".json")
    if not meta_path.exists():
        problems.append("metadata .json missing")
        return problems
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    title = meta.get("title", "")
    if not title or "#Shorts" not in title or len(title) > 100:
        problems.append("title missing/too long/no #Shorts")
    if len(meta.get("description", "")) < 20:
        problems.append("description too short")
    if len(meta.get("tags", [])) < 5:
        problems.append("fewer than 5 tags")
    if _deva_ratio(meta.get("story", "")) < 0.85:
        problems.append("story is not mainly Hindi (Devanagari)")
    if meta.get("made_for_kids") is not True:
        problems.append("made_for_kids not true")
    thumb = meta.get("thumbnail") or mp4.name.replace("short_", "thumb_").replace(".mp4", ".jpg")
    if not (mp4.parent / thumb).exists():
        problems.append("thumbnail missing")
    return problems


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--latest", action="store_true")
    p.add_argument("--dir", default=str(OUTPUT_DIR))
    a = p.parse_args(argv)
    videos = sorted(Path(a.dir).glob("short_*.mp4"), key=lambda x: x.stat().st_mtime)
    if a.latest:
        videos = videos[-1:]
    if not videos:
        print("No videos found in output/")
        return 1
    bad = 0
    for mp4 in videos:
        problems = check_video(mp4)
        bad += bool(problems)
        print(f"{'PASS' if not problems else 'FAIL'}  {mp4.name}" + ("" if not problems else "  -> " + "; ".join(problems)))
    print(f"{len(videos) - bad}/{len(videos)} videos passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
