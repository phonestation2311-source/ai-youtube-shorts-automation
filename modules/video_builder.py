"""
Video Builder - Creates YouTube Shorts using FFmpeg
Professional quality: zoom transitions, fade effects, styled subtitles.
100% FREE - uses FFmpeg.
"""

import subprocess
import os
import json
import math
import re
from pathlib import Path
from typing import List, Optional
from config.settings import (
    OUTPUT_DIR, VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS,
    VIDEO_TARGET_DURATION, VIDEO_MAX_DURATION,
    FONT_SIZE, FONT_COLOR, FONT_BORDER_COLOR, FONT_BORDER_WIDTH,
    BACKGROUND_MUSIC_VOLUME, VIDEO_END_PADDING,
    SUBTITLE_FONT, SUBTITLE_FONT_SIZE, SUBTITLE_MAX_WORDS, SUBTITLE_MARGIN_BOTTOM,
)
from utils import get_logger

log = get_logger("video_builder")


def get_media_duration(filepath: str) -> float:
    """Get duration of audio/video file."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                filepath,
            ],
            capture_output=True, text=True, timeout=15,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def create_color_background(duration: float, output_path: str, color: str = "black") -> str:
    """Create a solid color background video."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c={color}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:d={duration}:r={VIDEO_FPS}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-t", str(duration),
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=120)
    return output_path


def prepare_clip(clip_path: str, target_duration: float, output_path: str, clip_index: int = 0) -> str:
    """
    Scale, crop, and add effects to a clip for 9:16 vertical format.
    Adds slow zoom (Ken Burns effect) and fade transitions.
    """
    # Alternate between zoom-in and zoom-out for variety
    if clip_index % 2 == 0:
        # Slow zoom IN (1.0 to 1.15)
        zoom_filter = f"zoompan=z='min(1.15,1+0.0003*on)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(target_duration * VIDEO_FPS)}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS}"
    else:
        # Slow zoom OUT (1.15 to 1.0)
        zoom_filter = f"zoompan=z='max(1.0,1.15-0.0003*on)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(target_duration * VIDEO_FPS)}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS}"

    # Add fade in/out (0.5 sec each)
    fade_filter = f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0, target_duration - 0.4)}:d=0.4"

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",  # loop short clips so every segment is long enough
        "-i", clip_path,
        "-vf", (
            f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
            f"setsar=1,"
            f"{fade_filter}"
        ),
        "-t", str(target_duration),
        "-c:v", "libx264",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-an",
        "-r", str(VIDEO_FPS),
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        if result.returncode == 0 and get_media_duration(output_path) > 0:
            return output_path
        log.warning(f"Clip prepare failed for {os.path.basename(clip_path)}: {result.stderr[-300:]}")
    except Exception as e:
        log.warning(f"Clip prepare failed: {e}")
    return ""


def concatenate_clips(clip_paths: List[str], total_duration: float, output_path: str) -> str:
    """Concatenate multiple clips with fade transitions."""
    if not clip_paths:
        log.warning("No clips to concatenate, creating color background")
        return create_color_background(total_duration, output_path)

    concat_file = str(OUTPUT_DIR / "concat_list.txt")
    prepared_clips = []
    duration_per_clip = total_duration / len(clip_paths)

    for i, clip in enumerate(clip_paths):
        prep_path = str(OUTPUT_DIR / f"prep_{i}.mp4")
        result = prepare_clip(clip, duration_per_clip, prep_path, clip_index=i)
        if result:
            prepared_clips.append(result)

    if not prepared_clips:
        return create_color_background(total_duration, output_path)

    # Write concat list
    with open(concat_file, "w") as f:
        for clip in prepared_clips:
            f.write(f"file '{clip}'\n")

    # Concatenate
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_file,
        "-c:v", "libx264",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-r", str(VIDEO_FPS),
        "-t", str(total_duration),
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return output_path
        log.error(f"Concat failed: {result.stderr[-300:]}")
    except Exception as e:
        log.error(f"Concat failed: {e}")

    return create_color_background(total_duration, output_path)


def generate_subtitle_file(script: str, duration: float, output_path: str) -> str:
    """
    Generate SRT subtitle file from script.
    Professional style: 3-4 words per segment, UPPERCASE.
    """
    words = script.split()
    total_words = len(words)
    if total_words == 0:
        return ""

    # 3-4 words per subtitle = professional Shorts look
    chunk_size = 4
    chunks = []
    for i in range(0, total_words, chunk_size):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append(chunk.upper())

    time_per_chunk = duration / len(chunks)

    srt_content = ""
    for i, chunk in enumerate(chunks):
        start_time = i * time_per_chunk
        end_time = min((i + 1) * time_per_chunk, duration)

        start_str = format_srt_time(start_time)
        end_str = format_srt_time(end_time)

        srt_content += f"{i + 1}\n{start_str} --> {end_str}\n{chunk}\n\n"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    log.info(f"Subtitles generated: {len(chunks)} segments")
    return output_path


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def _word_times(words: List[str], duration: float, word_timings: Optional[list]) -> List[tuple]:
    """Start/end time for every word. Uses the voice's real word timings when they
    line up with the script, otherwise spreads time by word length."""
    if word_timings and len(word_timings) == len(words):
        return [(t["start"], t["end"]) for t in word_timings]

    if word_timings and len(word_timings) >= 2:
        # Different word counts (e.g. punctuation/numbers): stretch over spoken span
        start_all = word_timings[0]["start"]
        end_all = word_timings[-1]["end"]
    else:
        start_all, end_all = 0.0, duration
    weights = [max(len(w), 2) for w in words]
    total = sum(weights) or 1
    times, t = [], start_all
    for w in weights:
        d = (end_all - start_all) * w / total
        times.append((t, t + d))
        t += d
    return times


def generate_ass_subtitles(script: str, duration: float, output_path: str,
                           word_timings: Optional[list] = None) -> str:
    """
    Create an .ass subtitle file sized for 1080x1920 with a Devanagari font.
    Shows up to SUBTITLE_MAX_WORDS words at a time, synced to the narration.
    """
    words = script.split()
    if not words:
        return ""
    times = _word_times(words, duration, word_timings)

    # Group words into short lines; break after sentence/comma marks
    chunks, current = [], []
    for idx, w in enumerate(words):
        current.append(idx)
        if len(current) >= SUBTITLE_MAX_WORDS or re.search(r"[।!?,.]$", w):
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{SUBTITLE_FONT},{SUBTITLE_FONT_SIZE},&H00FFFFFF,&H0000FFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,6,3,2,70,70,{SUBTITLE_MARGIN_BOTTOM},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for n, chunk in enumerate(chunks):
        start = times[chunk[0]][0]
        end = times[chunk[-1]][1]
        if n + 1 < len(chunks):  # keep text on screen until the next line starts
            end = max(end, times[chunks[n + 1][0]][0])
        end = min(max(end, start + 0.3), duration + 1.0)
        text = _ass_escape(" ".join(words[i] for i in chunk))
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines) + "\n")

    log.info(f"Subtitles generated: {len(chunks)} segments ({'word-synced' if word_timings else 'estimated timing'})")
    return output_path


def check_hindi_font() -> bool:
    """Warn if no Devanagari font is installed (subtitles would show boxes)."""
    try:
        out = subprocess.run(["fc-list", ":lang=hi", "family"], capture_output=True, text=True, timeout=10).stdout
        if out.strip():
            return True
    except Exception:
        pass
    log.warning("No Hindi (Devanagari) font found - subtitles may show boxes. "
                "Fix: sudo apt-get install -y fonts-noto-core")
    return False


def format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT time format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def build_final_video(
    clips: List[str],
    voice_path: str,
    script: str,
    output_filename: str = "final_short.mp4",
    bg_music_path: str = "",
    word_timings: Optional[list] = None,
) -> str:
    """
    Build the final YouTube Shorts video with professional quality:
    1. Get voice duration
    2. Concatenate clips with zoom/fade transitions
    3. Mix voice + background music
    4. Add professional subtitles
    5. Output final 9:16 video
    """
    output_path = str(OUTPUT_DIR / output_filename)

    # Step 1: Get voice duration
    voice_duration = get_media_duration(voice_path)
    if voice_duration <= 0:
        log.error("Could not determine voice duration")
        return ""

    target_duration = min(voice_duration + VIDEO_END_PADDING, VIDEO_MAX_DURATION)
    log.info(f"Target video duration: {target_duration:.1f}s")

    # Step 2: Create base video from clips (with zoom/fade effects)
    base_video = str(OUTPUT_DIR / "base_video.mp4")
    if clips:
        concatenate_clips(clips, target_duration, base_video)
    else:
        create_color_background(target_duration, base_video)

    # Step 3: Mix voice with background music (music quietly underneath)
    final_audio = voice_path
    if bg_music_path and os.path.exists(bg_music_path):
        mixed_audio = str(OUTPUT_DIR / "mixed_audio.m4a")
        fade_out_start = max(0, target_duration - 2)
        base_filter = (
            f"[1:a]volume={BACKGROUND_MUSIC_VOLUME},afade=t=in:st=0:d=1,"
            f"afade=t=out:st={fade_out_start}:d=2[bg];"
            f"[0:a]volume=1.0,apad[voice];"
        )
        # normalize=0 keeps the narration at full volume (needs FFmpeg 4.4+)
        for amix in ("amix=inputs=2:duration=first:dropout_transition=2:normalize=0",
                     "amix=inputs=2:duration=first:dropout_transition=2"):
            mix_cmd = [
                "ffmpeg", "-y",
                "-i", voice_path,
                "-stream_loop", "-1", "-i", bg_music_path,
                "-filter_complex", f"{base_filter}[voice][bg]{amix}[out]",
                "-map", "[out]",
                "-c:a", "aac",
                "-b:a", "192k",
                "-t", str(target_duration),
                mixed_audio,
            ]
            try:
                result = subprocess.run(mix_cmd, capture_output=True, text=True, timeout=120)
                if result.returncode == 0:
                    final_audio = mixed_audio
                    log.info("Background music mixed under the narration (fade in/out)")
                    break
                log.warning(f"Music mix attempt failed: {result.stderr[-200:]}")
            except Exception as e:
                log.warning(f"Music mix error: {e}")
        if final_audio == voice_path:
            log.warning("Music mix failed, using voice only")

    # Step 4: Generate Hindi subtitles (.ass, Devanagari font, synced to voice)
    check_hindi_font()
    sub_path = str(OUTPUT_DIR / "subtitles.ass")
    generate_ass_subtitles(script, voice_duration, sub_path, word_timings)

    # Step 5: Combine everything
    sub_escaped = sub_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    subtitle_filter = f"ass='{sub_escaped}'"

    cmd = [
        "ffmpeg", "-y",
        "-i", base_video,
        "-i", final_audio,
        "-filter_complex",
        f"[0:v]{subtitle_filter}[v];[1:a]apad[a]",
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        "-pix_fmt", "yuv420p",
        "-r", str(VIDEO_FPS),
        "-t", str(target_duration),
        "-movflags", "+faststart",
        output_path,
    ]

    try:
        log.info("Building final video with subtitles + effects...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            log.warning(f"Subtitle overlay failed ({result.stderr[-300:]}), trying without subtitles...")
            cmd_simple = [
                "ffmpeg", "-y",
                "-i", base_video,
                "-i", final_audio,
                "-map", "0:v",
                "-map", "1:a",
                "-af", "apad",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "20",
                "-c:a", "aac",
                "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                "-t", str(target_duration),
                "-movflags", "+faststart",
                output_path,
            ]
            result = subprocess.run(cmd_simple, capture_output=True, text=True, timeout=300)

        if result.returncode == 0 and os.path.exists(output_path):
            final_duration = get_media_duration(output_path)
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            log.info(f"Final video: {output_path} ({final_duration:.1f}s, {size_mb:.1f}MB)")
            return output_path
        else:
            log.error(f"FFmpeg error: {result.stderr[:500]}")

    except Exception as e:
        log.error(f"Video build failed: {e}")

    return ""


def extract_thumbnail(video_path: str, output_filename: str = "thumbnail.jpg", time_sec: float = 3.0) -> str:
    """Extract a frame from video as thumbnail."""
    output_path = str(OUTPUT_DIR / output_filename)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-ss", str(time_sec),
        "-vframes", "1",
        "-q:v", "2",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode == 0:
            log.info(f"Thumbnail extracted: {output_path}")
            return output_path
    except Exception as e:
        log.warning(f"Thumbnail extraction failed: {e}")

    return ""


def cleanup_temp_files():
    """Clean up temporary files in output directory."""
    patterns = ["prep_*.mp4", "base_video.mp4", "concat_list.txt",
                "clip_*.mp4", "subtitles.srt", "subtitles.ass", "mixed_audio.mp3", "mixed_audio.m4a"]
    for pattern in patterns:
        for f in OUTPUT_DIR.glob(pattern):
            try:
                f.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    print("Video Builder module loaded.")
    print(f"Output dir: {OUTPUT_DIR}")
    print(f"Video format: {VIDEO_WIDTH}x{VIDEO_HEIGHT} @ {VIDEO_FPS}fps")
    print("Features: fade effects, Hindi (Devanagari) subtitles, background music")