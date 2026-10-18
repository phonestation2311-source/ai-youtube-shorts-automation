"""
Voice Generator - Using edge-tts (100% FREE)
Microsoft Edge Text-to-Speech - no API key needed.
Hindi voice: hi-IN-MadhurNeural. Also records word timings for subtitles
and adjusts the speaking speed so the narration lands in 35-45 seconds.
"""

import asyncio
import re
import subprocess
import sys
import time

from config.settings import (
    OUTPUT_DIR,
    VIDEO_END_PADDING,
    VIDEO_MAX_DURATION,
    VIDEO_TARGET_DURATION,
    VIDEO_TARGET_MAX_DURATION,
    VIDEO_TARGET_MIN_DURATION,
    VOICE_NAME,
    VOICE_RATE,
)
from utils import get_logger

log = get_logger("voice_gen")

# Word timings from the most recent generate_voice() call
LAST_WORD_TIMINGS = []

MIN_RATE, MAX_RATE = -20, 25  # percent; outside this the voice sounds unnatural


async def _generate_voice_async(text: str, output_path: str, voice: str = None, rate: str = "+0%") -> list:
    """Save speech to output_path and return word timings [{text,start,end}]."""
    import edge_tts

    voice = voice or VOICE_NAME
    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    except TypeError:  # older edge-tts (<7) sends word boundaries by default
        communicate = edge_tts.Communicate(text, voice, rate=rate)

    timings = []
    with open(output_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10_000_000
                timings.append({
                    "text": chunk.get("text", ""),
                    "start": start,
                    "end": start + chunk["duration"] / 10_000_000,
                })
    return timings


def _rate_to_int(rate: str) -> int:
    m = re.match(r"^([+-]?\d+)%$", str(rate).strip())
    return int(m.group(1)) if m else 0


def _int_to_rate(value: int) -> str:
    return f"{value:+d}%"


def generate_voice(script: str, output_filename: str = "voice.mp3", rate: str = None) -> str:
    """
    Generate voice from script text.
    Returns path to the generated audio file ("" on failure).
    Word timings are stored in LAST_WORD_TIMINGS.
    """
    global LAST_WORD_TIMINGS
    output_path = str(OUTPUT_DIR / output_filename)
    rate = rate or VOICE_RATE

    log.info(f"Generating voice with {VOICE_NAME} (rate {rate})...")
    log.info(f"Script length: {len(script)} chars, {len(script.split())} words")

    for attempt in range(1, 3):
        try:
            LAST_WORD_TIMINGS = asyncio.run(_generate_voice_async(script, output_path, rate=rate))
            duration = get_audio_duration(output_path)
            if duration <= 0:
                raise RuntimeError("audio file is empty")
            log.info(f"Voice saved: {output_path}")
            log.info(f"Audio duration: {duration:.1f} seconds")
            return output_path
        except ImportError:
            log.error("edge-tts not installed. Run: pip install edge-tts")
            return ""
        except Exception as e:
            log.warning(f"Voice generation attempt {attempt} failed: {e}")
            time.sleep(3)

    log.error("Voice generation failed.")
    return ""


def generate_voice_fitted(script: str, output_filename: str = "voice.mp3"):
    """
    Generate narration and adjust speed (once) so it fits 35-45 seconds.
    Returns (path, duration_seconds, word_timings). path is "" on failure.
    """
    rate = _rate_to_int(VOICE_RATE)
    path = generate_voice(script, output_filename, _int_to_rate(rate))
    if not path:
        return "", 0.0, []
    duration = get_audio_duration(path)

    if duration > VIDEO_TARGET_MAX_DURATION or duration < VIDEO_TARGET_MIN_DURATION:
        # Speed needed to land on the target duration
        needed = round((1 + rate / 100) * duration / VIDEO_TARGET_DURATION * 100 - 100)
        new_rate = max(MIN_RATE, min(MAX_RATE, needed))
        if new_rate != rate:
            log.info(f"Narration is {duration:.1f}s; re-generating at rate {_int_to_rate(new_rate)} to reach ~{VIDEO_TARGET_DURATION}s")
            new_path = generate_voice(script, output_filename, _int_to_rate(new_rate))
            if new_path:
                path, duration = new_path, get_audio_duration(new_path)

    if duration + VIDEO_END_PADDING > VIDEO_MAX_DURATION:
        log.error(f"Narration is {duration:.1f}s - too long for a Short (max {VIDEO_MAX_DURATION}s).")
        return "", duration, []
    if not (VIDEO_TARGET_MIN_DURATION <= duration <= VIDEO_TARGET_MAX_DURATION):
        log.warning(f"Narration is {duration:.1f}s (target {VIDEO_TARGET_MIN_DURATION}-{VIDEO_TARGET_MAX_DURATION}s), continuing.")
    return path, duration, list(LAST_WORD_TIMINGS)


def get_audio_duration(filepath: str) -> float:
    """Get audio duration using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                filepath,
            ],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def list_available_voices():
    """List all available edge-tts voices."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "edge_tts", "--list-voices"],
            capture_output=True, text=True, timeout=30,
        )
        print(result.stdout)
    except Exception as e:
        print(f"Error listing voices: {e}")


if __name__ == "__main__":
    test_text = "एक छोटा सा खरगोश था। उसका नाम चीकू था। वह बहुत प्यारा था।"
    path = generate_voice(test_text, "test_voice.mp3")
    if path:
        print(f"Voice generated: {path} ({len(LAST_WORD_TIMINGS)} word timings)")
    else:
        print("Voice generation failed. Make sure edge-tts is installed.")
