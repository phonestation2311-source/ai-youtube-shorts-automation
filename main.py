"""
╔══════════════════════════════════════════════════════════════╗
║  Hindi Kids Animal Story Shorts - Main Pipeline Runner      ║
║  Idea → Story → Voice → Footage → Video (upload is OFF)     ║
║  100% FREE tools only                                       ║
╚══════════════════════════════════════════════════════════════╝
"""

import os
import sys
import time
import random
import json
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import (
    NICHES, OUTPUT_DIR, VIDEOS_PER_DAY, UPLOAD_ENABLED, UPLOAD_APPROVED, MADE_FOR_KIDS,
    VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_MAX_DURATION,
)
from modules.trend_scraper import get_all_trends
from modules.ai_engine import (
    generate_viral_idea,
    generate_script,
    optimize_hook,
    generate_seo,
    generate_search_keywords,
)
from modules.voice_generator import generate_voice_fitted
from modules.footage_fetcher import fetch_footage_for_keywords
from modules.video_builder import build_final_video, extract_thumbnail, cleanup_temp_files, get_media_duration
from modules.youtube_upload import upload_video, set_thumbnail
from modules.analytics_engine import record_video, refresh_all_stats, generate_ai_feedback
from modules.script_quality import validate_script, improve_script
from modules.music_manager import get_background_music
from utils import get_logger

log = get_logger("main")


def clean_output_dir():
    """Remove previous temp files from output directory."""
    cleanup_temp_files()
    for ext in ["*.mp3", "*.wav"]:
        for f in OUTPUT_DIR.glob(ext):
            try:
                f.unlink()
            except Exception:
                pass


def create_single_video(niche: dict = None, dry_run: bool = False) -> dict:
    """
    Create a single YouTube Short - full pipeline.
    
    Args:
        niche: Content niche config dict. If None, picks randomly.
        dry_run: If True, does everything except upload.
    
    Returns:
        dict with video info and status.
    """
    result = {
        "success": False,
        "niche": "",
        "idea": "",
        "video_path": "",
        "video_id": "",
        "metadata_path": "",
        "duration": 0,
        "error": "",
    }

    try:
        # ── Step 0: Clean up ──
        clean_output_dir()

        # ── Step 1: Pick niche ──
        if niche is None:
            niche = random.choice(NICHES)
        result["niche"] = niche["name"]
        log.info(f"{'='*60}")
        log.info(f"NICHE: {niche['name']}")
        log.info(f"{'='*60}")

        # ── Step 2: Discover trends ──
        if niche.get("type") == "kids_story":
            # Kids stories are original - no need to scrape Reddit/news trends
            log.info("Step 1/10: Kids story mode - skipping trend scraping")
            trends = []
        else:
            log.info("Step 1/10: Discovering trends...")
            trends = get_all_trends(subreddits=niche.get("subreddits", []))
            if not trends:
                log.warning("No trends found, using niche keywords as fallback")
                trends = [{"title": kw, "score": 50} for kw in niche["keywords"]]

        # ── Step 3: Generate viral idea ──
        log.info("Step 2/10: Generating story idea...")
        idea = generate_viral_idea(trends, niche)
        if not idea:
            result["error"] = "Failed to generate idea"
            return result
        result["idea"] = idea
        log.info(f"Idea: {idea}")

        # ── Step 4: Generate script ──
        log.info("Step 3/10: Writing Hindi story...")
        script = generate_script(idea)
        if not script or len(script) < 20:
            result["error"] = "Failed to generate story (check GROQ_API_KEY and logs/automation.log)"
            return result

        # ── Step 5: Optimize hook ──
        log.info("Step 4/10: Optimizing opening line...")
        script = optimize_hook(script)
        log.info(f"Script ({len(script.split())} words): {script[:150]}...")

        # ── Step 5b: Quality check ──
        log.info("Step 5/10: Quality checking story...")
        quality = validate_script(script)
        if not quality["approved"]:
            log.warning(f"Story quality low ({quality['score']}%), improving once...")
            issues = [c["message"] for c in quality["checks"].values() if not c["pass"]]
            script = improve_script(script, issues)
            quality = validate_script(script)
        log.info(f"Story quality: {quality['score']}%")
        if not quality.get("required_ok", True):
            bad = [c["message"] for c in quality["checks"].values() if not c["pass"]]
            result["error"] = "Story failed required checks: " + "; ".join(bad)
            return result
        log.info(f"Final story: {script}")

        # ── Step 6: Generate SEO ──
        log.info("Step 6/10: Generating title, description and tags...")
        seo = generate_seo(idea, script)

        # ── Step 7: Generate voice ──
        log.info("Step 7/10: Generating Hindi narration...")
        voice_path, voice_duration, word_timings = generate_voice_fitted(script, "voice.mp3")
        if not voice_path:
            result["error"] = "Failed to generate voice (or narration too long)"
            return result

        # ── Step 8: Fetch stock footage ──
        log.info("Step 8/10: Fetching stock footage...")
        keywords = generate_search_keywords(script, idea)
        clips = fetch_footage_for_keywords(keywords, clips_per_keyword=1)
        if not clips:
            log.warning("No footage downloaded - the video will use a plain background")

        # ── Step 8b: Get background music ──
        bg_music = get_background_music()
        if bg_music:
            log.info(f"Background music: {bg_music}")

        # ── Step 9: Build video ──
        log.info("Step 9/10: Building final video...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        video_filename = f"short_{timestamp}.mp4"
        video_path = build_final_video(clips, voice_path, script, video_filename,
                                       bg_music_path=bg_music, word_timings=word_timings)

        if not video_path:
            result["error"] = "Failed to build video"
            return result

        result["video_path"] = video_path
        result["duration"] = round(get_media_duration(video_path), 1)
        if result["duration"] > VIDEO_MAX_DURATION:
            log.warning(f"Video is {result['duration']}s - longer than {VIDEO_MAX_DURATION}s!")

        # ── Step 10: Thumbnail + metadata file for your review ──
        thumb_path = extract_thumbnail(video_path, f"thumb_{timestamp}.jpg")
        metadata = {
            "video_file": Path(video_path).name,
            "thumbnail": Path(thumb_path).name if thumb_path else "",
            "created": datetime.now().isoformat(timespec="seconds"),
            "niche": niche["name"],
            "idea": idea,
            "story": script,
            "title": seo.get("title", ""),
            "description": seo.get("description", ""),
            "tags": seo.get("tags", []),
            "hashtags": seo.get("hashtags", []),
            "made_for_kids": MADE_FOR_KIDS,
            "duration_seconds": result["duration"],
            "resolution": f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}",
            "footage_keywords": keywords,
            "footage_clips": len(clips),
            "background_music": Path(bg_music).name if bg_music else "",
            "quality_score": quality.get("score"),
            "uploaded": False,
        }
        meta_path = OUTPUT_DIR / f"short_{timestamp}.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        result["metadata_path"] = str(meta_path)
        log.info(f"Metadata saved for review: {meta_path}")

        # Create a manual review checklist for every generated Short.
        checklist_path = OUTPUT_DIR / f"review_{meta_path.stem}.md"
        checklist = f"""# YouTube Short — Manual Review

- Video: `{Path(video_path).name}`
- Thumbnail: `{Path(thumb_path).name if thumb_path else "Not generated"}`
- Metadata: `{meta_path.name}`
- Created: {metadata["created"]}
- Review status: **PENDING — NOT APPROVED**
- Upload status: **NOT UPLOADED**

## Review checklist

- [ ] Video plays from beginning to end without errors
- [ ] Hindi narration is clear and matches the story
- [ ] Hindi subtitles are readable, correctly timed, and spelled correctly
- [ ] Story is suitable for children and has a clear ending
- [ ] Thumbnail is clear and represents the actual video
- [ ] Title is accurate, attractive, and not misleading
- [ ] Description and hashtags are accurate
- [ ] Footage and music usage rights have been checked
- [ ] Made for Kids audience setting has been checked
- [ ] Final video has been watched and manually approved

## Decision

- [ ] Approved for consideration after every check passes
- [ ] Needs changes

Notes / changes required:



**Important:** This checklist does not upload or publish the video. Keep `UPLOAD_ENABLED=false` and `UPLOAD_APPROVED=false` until a separate, explicit publishing decision is made.
"""
        checklist_path.write_text(checklist, encoding="utf-8")
        result["review_checklist_path"] = str(checklist_path)
        log.info(f"Review checklist created: {checklist_path}")

        # ── Upload (OFF unless UPLOAD_ENABLED=true in .env) ──
        if dry_run or not UPLOAD_ENABLED or not UPLOAD_APPROVED:
            reason = "DRY RUN" if dry_run else ("UPLOAD_ENABLED is off" if not UPLOAD_ENABLED else "UPLOAD_APPROVED is off — awaiting review")
            log.info(f"{reason} - video saved locally, NOT uploaded: {video_path}")
            result["success"] = True
            result["video_id"] = "DRY_RUN" if dry_run else "NOT_UPLOADED"
        else:
            log.info("Uploading to YouTube...")
            video_id = upload_video(
                video_path=video_path,
                title=seo.get("title", idea),
                description=seo.get("description", ""),
                tags=seo.get("tags", []),
            )

            if video_id:
                result["video_id"] = video_id
                result["success"] = True

                # Set thumbnail
                if thumb_path:
                    set_thumbnail(video_id, thumb_path)

                # Record in analytics
                record_video(
                    video_id=video_id,
                    title=seo.get("title", idea),
                    idea=idea,
                    niche=niche["name"],
                    script=script,
                    seo_data=seo,
                )

                log.info(f"SUCCESS! Video uploaded: https://youtube.com/shorts/{video_id}")
            else:
                result["error"] = "Upload failed"

    except Exception as e:
        log.error(f"Pipeline error: {e}", exc_info=True)
        result["error"] = str(e)

    finally:
        # Cleanup temp files
        cleanup_temp_files()

    return result


def run_daily_batch(count: int = None, dry_run: bool = False):
    """
    Run a batch of video creations.
    Rotates through niches.
    """
    count = count or VIDEOS_PER_DAY
    log.info(f"Starting daily batch: {count} videos")
    log.info(f"Dry run: {dry_run}")

    results = []
    for i in range(count):
        niche = NICHES[i % len(NICHES)]
        log.info(f"\n{'#'*60}")
        log.info(f"# VIDEO {i+1}/{count}")
        log.info(f"{'#'*60}")

        result = create_single_video(niche=niche, dry_run=dry_run)
        results.append(result)

        if result["success"]:
            log.info(f"Video {i+1} SUCCESS: {result['idea']}")
        else:
            log.error(f"Video {i+1} FAILED: {result['error']}")

        # Wait between videos
        if i < count - 1:
            wait = random.randint(30, 120)
            log.info(f"Waiting {wait}s before next video...")
            time.sleep(wait)

    # Summary
    success = sum(1 for r in results if r["success"])
    log.info(f"\n{'='*60}")
    log.info(f"BATCH COMPLETE: {success}/{count} videos created")
    log.info(f"{'='*60}")

    return results


def run_analytics_cycle():
    """Run analytics refresh and get AI feedback."""
    log.info("Running analytics cycle...")
    refresh_all_stats()
    feedback = generate_ai_feedback()
    if feedback:
        log.info(f"AI Feedback:\n{feedback}")
    return feedback


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Hindi Kids Animal Story Shorts (upload is OFF by default)")
    parser.add_argument("--mode", choices=["single", "batch", "analytics", "test"],
                        default="single", help="Run mode")
    parser.add_argument("--count", type=int, default=1, help="Number of videos for batch mode")
    parser.add_argument("--dry-run", action="store_true", help="Skip YouTube upload")
    parser.add_argument("--niche", type=int, default=None,
                        help=f"Niche index (0-{len(NICHES) - 1})")

    args = parser.parse_args()

    if args.mode == "single":
        niche = NICHES[args.niche] if args.niche is not None else None
        result = create_single_video(niche=niche, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, default=str))

    elif args.mode == "batch":
        results = run_daily_batch(count=args.count, dry_run=args.dry_run)
        for r in results:
            status = "OK" if r["success"] else "FAIL"
            print(f"[{status}] {r.get('niche', 'N/A')}: {r.get('idea', r.get('error', 'N/A'))}")

    elif args.mode == "analytics":
        run_analytics_cycle()

    elif args.mode == "test":
        print("Running test (dry run, 1 video)...")
        result = create_single_video(dry_run=True)
        print(json.dumps(result, indent=2, default=str))
