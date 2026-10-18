"""
Stock Footage Fetcher
Downloads free stock videos from Pexels API.
Free tier: 200 requests/hour, no watermark.
Sign up: https://www.pexels.com/api/
"""

import requests
import os
import time
import random
from pathlib import Path
from typing import List, Optional
from config.settings import (
    PEXELS_API_KEY, OUTPUT_DIR, VIDEO_WIDTH, VIDEO_HEIGHT, FOOTAGE_PROVIDERS, MIN_FOOTAGE_CLIPS,
)
from utils import get_logger

log = get_logger("footage")


def _pexels_key_ok() -> bool:
    return bool(PEXELS_API_KEY) and not PEXELS_API_KEY.startswith("YOUR_")


def search_pexels_videos(
    query: str,
    count: int = 3,
    orientation: str = "portrait",
    min_duration: int = 5,
    max_duration: int = 30,
) -> List[dict]:
    """Search for videos on Pexels."""

    if not _pexels_key_ok():
        log.warning("Pexels API key not set. Add PEXELS_API_KEY to .env (free at https://www.pexels.com/api/)")
        return []

    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {
        "query": query,
        "orientation": orientation,
        "per_page": count * 2,  # Fetch extra in case some don't work
        "size": "medium",
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code != 200:
            log.warning(f"Pexels API error: {resp.status_code}")
            return []

        data = resp.json()
        videos = []

        for video in data.get("videos", []):
            duration = video.get("duration", 0)
            if min_duration <= duration <= max_duration:
                # Get the best quality video file
                video_files = video.get("video_files", [])
                # Prefer HD portrait
                best_file = None
                for vf in video_files:
                    w = vf.get("width", 0)
                    h = vf.get("height", 0)
                    if h > w and vf.get("quality") in ["hd", "sd"]:
                        best_file = vf
                        break

                if not best_file and video_files:
                    best_file = video_files[0]

                if best_file:
                    videos.append({
                        "id": f"pexels_{video.get('id')}",
                        "source": "pexels",
                        "url": best_file.get("link"),
                        "width": best_file.get("width"),
                        "height": best_file.get("height"),
                        "duration": duration,
                        "quality": best_file.get("quality"),
                    })

            if len(videos) >= count:
                break

        log.info(f"Found {len(videos)} videos for '{query}'")
        return videos

    except Exception as e:
        log.error(f"Pexels search failed: {e}")
        return []


def download_video(url: str, filename: str) -> str:
    """Download a video file. Returns "" if it fails or the file is broken."""
    output_path = str(OUTPUT_DIR / filename)

    try:
        log.info(f"Downloading: {filename}")
        resp = requests.get(url, stream=True, timeout=90)
        resp.raise_for_status()

        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                f.write(chunk)

        if os.path.getsize(output_path) < 50 * 1024:
            log.warning(f"Downloaded file is too small, skipping: {filename}")
            os.remove(output_path)
            return ""

        log.info(f"Downloaded: {output_path}")
        return output_path

    except Exception as e:
        log.error(f"Download failed: {type(e).__name__}")
        return ""


def _search(provider: str, query: str, count: int) -> List[dict]:
    if provider == "pixabay":
        from modules.pixabay_fetcher import search_pixabay_videos
        return search_pixabay_videos(query, count=count)
    if provider == "pexels":
        return search_pexels_videos(query, count=count, orientation="portrait", min_duration=4, max_duration=60)
    return []


def fetch_footage_for_keywords(keywords: List[str], clips_per_keyword: int = 1) -> List[str]:
    """
    Fetch stock footage for each keyword.
    Tries Pixabay first, then Pexels (order set in settings.FOOTAGE_PROVIDERS).
    Never downloads the same video twice. Adds general cute-animal clips
    if too few were found. Returns list of downloaded file paths.
    """
    downloaded = []
    used_ids = set()
    fallback = ["cute baby animals", "funny animals", "animals in nature"]
    queries = list(keywords)

    i = 0
    while i < len(queries):
        kw = queries[i]
        got = 0
        for provider in FOOTAGE_PROVIDERS:
            if got >= clips_per_keyword:
                break
            try:
                videos = _search(provider, kw, clips_per_keyword)
            except Exception as e:
                log.warning(f"{provider} search error for '{kw}': {type(e).__name__}")
                videos = []
            for video in videos:
                if got >= clips_per_keyword:
                    break
                if video["id"] in used_ids:
                    continue
                path = download_video(video["url"], f"clip_{len(downloaded)}.mp4")
                if path:
                    used_ids.add(video["id"])
                    downloaded.append(path)
                    got += 1
                    log.info(f"Clip for '{kw}' from {provider}")
            time.sleep(0.3)  # Be gentle with the free APIs

        i += 1
        if i == len(queries) and len(downloaded) < MIN_FOOTAGE_CLIPS and fallback:
            queries.append(fallback.pop(0))

    log.info(f"Total clips downloaded: {len(downloaded)}")
    return downloaded


def search_pexels_images(query: str, count: int = 1, orientation: str = "portrait") -> List[dict]:
    """Search for images on Pexels (for thumbnails/backgrounds)."""

    if not _pexels_key_ok():
        return []

    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {
        "query": query,
        "orientation": orientation,
        "per_page": count,
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            images = []
            for photo in data.get("photos", []):
                images.append({
                    "id": photo.get("id"),
                    "url": photo.get("src", {}).get("large2x", ""),
                    "url_medium": photo.get("src", {}).get("medium", ""),
                })
            return images
    except Exception as e:
        log.error(f"Pexels image search failed: {e}")

    return []


if __name__ == "__main__":
    # Test
    keywords = ["cute rabbit", "baby elephant", "squirrel"]
    clips = fetch_footage_for_keywords(keywords, clips_per_keyword=1)
    print(f"Downloaded {len(clips)} clips")
