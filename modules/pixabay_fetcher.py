"""
Backup Footage Fetcher - Pixabay API
Used when Pexels has no results or rate-limits you.
Free: 100 requests/min, no watermark.
Sign up: https://pixabay.com/api/docs/
"""

import requests
import time
from typing import List
from config.settings import PIXABAY_API_KEY, OUTPUT_DIR
from utils import get_logger

log = get_logger("pixabay")


def _key_ok() -> bool:
    return bool(PIXABAY_API_KEY) and not PIXABAY_API_KEY.startswith("YOUR_")


def _pick_size(videos: dict) -> dict:
    """Pick the best file: portrait if available, otherwise large/medium (not huge)."""
    options = [videos.get(k, {}) for k in ("large", "medium", "small", "tiny")]
    options = [v for v in options if v.get("url") and v.get("size", 0) < 60 * 1024 * 1024]
    for v in options:
        if v.get("height", 0) > v.get("width", 0):
            return v
    return options[0] if options else {}


def search_pixabay_videos(query: str, count: int = 3, category: str = "animals") -> List[dict]:
    """Search Pixabay for free, safe stock videos (animals category first)."""
    if not _key_ok():
        log.warning("Pixabay API key not set. Add PIXABAY_API_KEY to .env (free at https://pixabay.com/api/docs/)")
        return []

    url = "https://pixabay.com/api/videos/"
    params = {
        "key": PIXABAY_API_KEY,
        "q": query[:100],
        "per_page": max(3, min(count * 4, 20)),
        "safesearch": "true",
        "video_type": "film",
        "order": "popular",
    }
    if category:
        params["category"] = category

    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            # Never log the full URL - it contains your API key
            log.warning(f"Pixabay API error {resp.status_code} for '{query}'")
            return []

        data = resp.json()
        videos = []
        for hit in data.get("hits", []):
            if hit.get("duration", 0) < 4:
                continue
            best = _pick_size(hit.get("videos", {}))
            if best.get("url"):
                videos.append({
                    "id": f"pixabay_{hit.get('id')}",
                    "url": best["url"],
                    "width": best.get("width", 0),
                    "height": best.get("height", 0),
                    "duration": hit.get("duration", 0),
                    "source": "pixabay",
                    "page_url": hit.get("pageURL", ""),
                })

        if not videos and category:
            return search_pixabay_videos(query, count, category="")

        log.info(f"Pixabay found {len(videos)} videos for '{query}'")
        return videos

    except Exception as e:
        log.error(f"Pixabay search failed: {type(e).__name__}")
        return []


def search_pixabay_images(query: str, count: int = 3) -> List[dict]:
    """Search Pixabay for free images (for backgrounds/thumbnails)."""
    if not _key_ok():
        return []

    url = "https://pixabay.com/api/"
    params = {
        "key": PIXABAY_API_KEY,
        "q": query,
        "per_page": count,
        "safesearch": "true",
        "image_type": "photo",
        "orientation": "vertical",
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return [
                {
                    "id": hit.get("id"),
                    "url": hit.get("largeImageURL", ""),
                    "url_medium": hit.get("webformatURL", ""),
                }
                for hit in data.get("hits", [])
            ]
    except Exception as e:
        log.error(f"Pixabay image search failed: {type(e).__name__}")

    return []


if __name__ == "__main__":
    results = search_pixabay_videos("cute rabbit", count=3)
    for v in results:
        print(f"  ID: {v['id']}, Duration: {v['duration']}s, URL: {v['url'][:80]}...")
