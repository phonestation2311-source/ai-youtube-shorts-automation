"""
YouTube Uploader
Uploads videos to YouTube using the Data API v3.
FREE: 10,000 API units/day (enough for ~6 uploads/day).

SETUP:
1. Go to https://console.cloud.google.com
2. Create a new project
3. Enable "YouTube Data API v3"
4. Create OAuth 2.0 credentials (Desktop application)
5. Download client_secret.json → put in config/ folder
6. First run will open browser for authentication
"""

import os
import json
import pickle
from pathlib import Path
from typing import Optional
from config.settings import YOUTUBE_CLIENT_SECRET_FILE, YOUTUBE_TOKEN_FILE, OUTPUT_DIR, UPLOAD_ENABLED, UPLOAD_APPROVED, MADE_FOR_KIDS
from utils import get_logger

log = get_logger("youtube")


# Minimal scopes: upload videos/thumbnails + read your own channel stats
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
LOOPBACK_PORT = 8090


def _save_token(creds):
    """Save the token (pickle format) without printing it."""
    os.makedirs(os.path.dirname(YOUTUBE_TOKEN_FILE), exist_ok=True)
    with open(YOUTUBE_TOKEN_FILE, "wb") as f:
        pickle.dump(creds, f)
    try:
        os.chmod(YOUTUBE_TOKEN_FILE, 0o600)
    except OSError:
        pass


def get_authenticated_service(interactive: bool = False):
    """Return a YouTube API client, or None if not connected.

    One-time setup in Codespaces (Desktop OAuth client + localhost redirect):
        python -m modules.youtube_upload --auth
    """
    try:
        import urllib.parse
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        log.error("Missing packages. Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
        return None

    creds = None
    if os.path.exists(YOUTUBE_TOKEN_FILE):
        try:
            with open(YOUTUBE_TOKEN_FILE, "rb") as f:
                creds = pickle.load(f)
        except Exception:
            log.warning("Saved YouTube token could not be read; please sign in again.")
            creds = None

    if creds is not None and not set(SCOPES).issubset(set(creds.scopes or [])):
        log.warning("Saved token has different permissions; please sign in again.")
        creds = None

    if creds is not None and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
        except Exception as e:
            log.warning(f"Token refresh failed ({type(e).__name__}); please sign in again.")
            creds = None

    if creds is None or not creds.valid:
        if not interactive:
            log.error("YouTube is not connected. Run once: python -m modules.youtube_upload --auth")
            return None
        if not os.path.exists(YOUTUBE_CLIENT_SECRET_FILE):
            log.error(f"OAuth client file not found: {YOUTUBE_CLIENT_SECRET_FILE}")
            return None
        with open(YOUTUBE_CLIENT_SECRET_FILE, encoding="utf-8") as f:
            kind = next(iter(json.load(f)), "")
        if kind != "installed":
            log.error("config/client_secret.json must be a Desktop app OAuth client (it starts with installed).")
            return None

        flow = InstalledAppFlow.from_client_secrets_file(YOUTUBE_CLIENT_SECRET_FILE, SCOPES)
        flow.redirect_uri = f"http://localhost:{LOOPBACK_PORT}/"
        auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")
        print("\n1) Ctrl+Click (or copy) this link and sign in with your YouTube channel account:\n")
        print(auth_url)
        print("\n2) After you click Continue/Allow, the browser shows a page that cannot be reached.")
        print("   That is expected. Copy the FULL address from the address bar (starts with http://localhost:8090/).")
        response = input("\n3) Paste that address here and press Enter: ").strip()
        params = urllib.parse.parse_qs(urllib.parse.urlparse(response).query)
        if "error" in params:
            log.error(f"Google returned an error: {params['error'][0]}")
            return None
        if params.get("state", [None])[0] != state:
            log.error("That address does not match this login attempt. Run --auth again and use the newest link.")
            return None
        code = params.get("code", [None])[0]
        if not code:
            log.error("No authorization code found in the pasted address.")
            return None
        flow.fetch_token(code=code)
        creds = flow.credentials
        _save_token(creds)
        log.info("YouTube connected. Token saved (contents not shown).")

    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list = None,
    category_id: str = "24",  # 24 = Entertainment (kids stories)
    privacy: str = "private",  # private first, so you can review on YouTube
    is_short: bool = True,
) -> Optional[str]:
    """
    Upload a video to YouTube.
    Returns the video ID if successful.
    """
    if not (UPLOAD_ENABLED and UPLOAD_APPROVED):
        log.warning("Upload blocked: needs BOTH UPLOAD_ENABLED=true and UPLOAD_APPROVED=true in .env.")
        return None

    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError

    youtube = get_authenticated_service()
    if not youtube:
        return None

    if not os.path.exists(video_path):
        log.error(f"Video file not found: {video_path}")
        return None

    # Ensure #Shorts in title/description for Shorts
    if is_short:
        if "#Shorts" not in title:
            title = f"{title} #Shorts"
        if "#Shorts" not in description:
            description = f"{description}\n\n#Shorts"

    tags = tags or ["shorts", "hindi kahani", "kids story"]

    body = {
        "snippet": {
            "title": title[:100],  # YouTube limit
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": MADE_FOR_KIDS,
        },
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024,  # 1MB chunks
    )

    try:
        log.info(f"Uploading: {title}")
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                log.info(f"Upload progress: {int(status.progress() * 100)}%")

        video_id = response.get("id", "")
        log.info(f"Upload complete! Video ID: {video_id}")
        log.info(f"URL: https://youtube.com/shorts/{video_id}")

        return video_id

    except HttpError as e:
        log.error(f"YouTube API error: {e}")
    except Exception as e:
        log.error(f"Upload failed: {e}")

    return None


def set_thumbnail(video_id: str, thumbnail_path: str) -> bool:
    """Set custom thumbnail for a video."""
    if not (UPLOAD_ENABLED and UPLOAD_APPROVED):
        log.warning("Upload blocked: needs BOTH UPLOAD_ENABLED=true and UPLOAD_APPROVED=true in .env.")
        return None

    from googleapiclient.http import MediaFileUpload

    youtube = get_authenticated_service()
    if not youtube or not os.path.exists(thumbnail_path):
        return False

    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_path),
        ).execute()
        log.info(f"Thumbnail set for video {video_id}")
        return True
    except Exception as e:
        log.warning(f"Thumbnail set failed: {e}")
        return False


def get_channel_analytics() -> dict:
    """Fetch basic channel stats."""
    youtube = get_authenticated_service()
    if not youtube:
        return {}

    try:
        request = youtube.channels().list(
            part="statistics,snippet",
            mine=True,
        )
        response = request.execute()

        if response.get("items"):
            channel = response["items"][0]
            stats = channel.get("statistics", {})
            return {
                "channel_name": channel.get("snippet", {}).get("title", ""),
                "subscribers": stats.get("subscriberCount", 0),
                "total_views": stats.get("viewCount", 0),
                "video_count": stats.get("videoCount", 0),
            }
    except Exception as e:
        log.warning(f"Analytics fetch failed: {e}")

    return {}


if __name__ == "__main__":
    import sys
    if "--auth" in sys.argv:
        yt = get_authenticated_service(interactive=True)
        if yt:
            info = get_channel_analytics()
            print(f"Connected to channel: {info.get('channel_name') or '(name not available)'}")
            print("Uploads stay OFF until UPLOAD_ENABLED and UPLOAD_APPROVED are both true.")
        else:
            print("Not connected - see the message above.")
    else:
        print("YouTube Uploader module loaded.")
        print("Connect once with: python -m modules.youtube_upload --auth")
