"""
YouTube Shorts Automation - Configuration
All settings in one place. Fill in your API keys.
"""

import os
from pathlib import Path

# Load .env file if python-dotenv is installed
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass  # python-dotenv is optional

# ============================================================
# PROJECT PATHS
# ============================================================
BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
OUTPUT_DIR = BASE_DIR / "output"
TEMPLATES_DIR = BASE_DIR / "templates"
LOGS_DIR = BASE_DIR / "logs"

# Create dirs if missing
for d in [ASSETS_DIR, OUTPUT_DIR, TEMPLATES_DIR, LOGS_DIR]:
    d.mkdir(exist_ok=True)

# ============================================================
# FREE API KEYS (Get these for free)
# ============================================================

# Pexels - Free stock video/images
# Sign up: https://www.pexels.com/api/
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()

# Pixabay - Free stock video/images (backup)
# Sign up: https://pixabay.com/api/docs/
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "").strip()

# YouTube Data API - Free quota (10,000 units/day)
# Setup: https://console.cloud.google.com
# Enable: YouTube Data API v3
# Create: OAuth 2.0 Client ID (Desktop app)
# Download: client_secret.json → put in config/ folder
YOUTUBE_CLIENT_SECRET_FILE = str(BASE_DIR / "config" / "client_secret.json")
YOUTUBE_TOKEN_FILE = str(BASE_DIR / "config" / "youtube_token.pickle")

# ============================================================
# AI STORY GENERATION (Groq - hosted, key read from .env)
# ============================================================
# GROQ_API_KEY must be set in your .env file (never put it in this file).
# The model below is the one that was already working for you.
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b"
GROQ_MAX_RETRIES = 3          # per request (no endless loops)

# Old Ollama settings kept only for backwards compatibility (not used)
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2:1b"
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

# ============================================================
# YOUTUBE UPLOAD - OFF BY DEFAULT
# ============================================================
# Videos are only created locally in the output/ folder.
# Uploading happens ONLY if you add UPLOAD_ENABLED=true to .env
# AND run without --dry-run. Leave it off until you have reviewed videos.
UPLOAD_ENABLED = os.getenv("UPLOAD_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
UPLOAD_APPROVED = os.getenv("UPLOAD_APPROVED", "false").strip().lower() in ("1", "true", "yes", "on")
MADE_FOR_KIDS = True  # Kids stories must be marked "made for kids" on YouTube

# ============================================================
# LANGUAGE SETTINGS
# ============================================================
CONTENT_LANGUAGE = "hindi"  # Stories are written in Hindi (Devanagari)
CONTENT_TYPE = "kids_story"

# Story length: measured hi-IN-MadhurNeural speed is ~2.1 Hindi words/sec,
# so 75-95 words gives roughly 35-45 seconds. If a story is a bit long or
# short, the voice speed is adjusted automatically (once) to fit 35-45s.
STORY_MIN_WORDS = 75
STORY_MAX_WORDS = 95

# ============================================================
# FREE VOICE (edge-tts - Microsoft Edge TTS, completely free)
# ============================================================
VOICE_NAME = "hi-IN-MadhurNeural"  # Hindi male voice
VOICE_RATE = "+0%"  # Normal speed (auto-adjusted between -20% and +25% to fit 35-45s)
# Other options:
# "hi-IN-SwaraNeural"         - Hindi female

# ============================================================
# VIDEO SETTINGS
# ============================================================
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920  # 9:16 vertical for Shorts
VIDEO_FPS = 30
VIDEO_MAX_DURATION = 59  # YouTube Shorts limit (hard maximum)
VIDEO_TARGET_MIN_DURATION = 35
VIDEO_TARGET_MAX_DURATION = 45
VIDEO_TARGET_DURATION = 40  # Ideal length
VIDEO_END_PADDING = 1.5  # Seconds of video after narration ends
FONT_SIZE = 48  # (old SRT setting, kept for compatibility)
FONT_COLOR = "white"
FONT_BORDER_COLOR = "black"
FONT_BORDER_WIDTH = 4
SUBTITLE_STYLE = "bold"
# Hindi subtitles need a Devanagari font. Install (free) in Codespaces with:
#   sudo apt-get install -y fonts-noto-core
SUBTITLE_FONT = "Noto Sans Devanagari"
SUBTITLE_FONT_SIZE = 90  # pixels on the 1080x1920 frame
SUBTITLE_MAX_WORDS = 4   # words shown at once
SUBTITLE_MARGIN_BOTTOM = 420  # keep text above the Shorts buttons/caption area
BACKGROUND_MUSIC_VOLUME = 0.10  # 10% volume, quietly under the narration

# Footage: Pixabay first (free), Pexels as backup (free)
FOOTAGE_PROVIDERS = ["pixabay", "pexels"]
MIN_FOOTAGE_CLIPS = 3

# ============================================================
# CONTENT NICHES - Hindi kids animal stories
# ============================================================
# "themes" are the moral/topic of the story (Hindi).
# "keywords" are English footage fallbacks.
NICHES = [
    {
        "name": "Kids Animal Stories - Friendship",
        "type": "kids_story",
        "themes": ["दोस्ती", "नया दोस्त बनाना", "दोस्त की मदद करना"],
        "keywords": ["cute animals", "baby animals", "animal friends"],
        "subreddits": [],
    },
    {
        "name": "Kids Animal Stories - Kindness",
        "type": "kids_story",
        "themes": ["दया", "मिलकर बाँटना", "छोटों की मदद करना"],
        "keywords": ["cute animals", "baby animals", "animals forest"],
        "subreddits": [],
    },
    {
        "name": "Kids Animal Stories - Clever Ideas",
        "type": "kids_story",
        "themes": ["चतुराई से मुश्किल हल करना", "समझदारी", "धैर्य"],
        "keywords": ["cute animals", "funny animals", "wildlife"],
        "subreddits": [],
    },
    {
        "name": "Kids Animal Stories - Honesty",
        "type": "kids_story",
        "themes": ["ईमानदारी", "सच बोलना", "गलती मानकर माफ़ी माँगना"],
        "keywords": ["cute animals", "baby animals", "farm animals"],
        "subreddits": [],
    },
    {
        "name": "Kids Animal Stories - Teamwork",
        "type": "kids_story",
        "themes": ["टीमवर्क", "मिलकर काम करना", "हिम्मत"],
        "keywords": ["cute animals", "animal family", "wildlife"],
        "subreddits": [],
    },
]

# Animals the stories use. "hi" = Hindi names (used to detect the animal in
# the story), "en" = English word used to search Pixabay/Pexels footage.
ANIMALS = [
    {"hi": ["खरगोश"], "en": "rabbit"},
    {"hi": ["हाथी"], "en": "elephant"},
    {"hi": ["बंदर"], "en": "monkey"},
    {"hi": ["शेर"], "en": "lion"},
    {"hi": ["भालू"], "en": "bear"},
    {"hi": ["कछुआ", "कछुए"], "en": "turtle"},
    {"hi": ["लोमड़ी", "लोमडी"], "en": "fox"},
    {"hi": ["गिलहरी"], "en": "squirrel"},
    {"hi": ["तोता", "तोते"], "en": "parrot"},
    {"hi": ["मोर"], "en": "peacock"},
    {"hi": ["बिल्ली"], "en": "kitten"},
    {"hi": ["पिल्ला", "पिल्ले", "कुत्ता", "कुत्ते"], "en": "puppy"},
    {"hi": ["बत्तख"], "en": "duck"},
    {"hi": ["चूज़ा", "चूजा", "चूज़े", "चूजे", "मुर्गी"], "en": "chick"},
    {"hi": ["हिरण", "हिरन"], "en": "deer"},
    {"hi": ["जिराफ़", "जिराफ"], "en": "giraffe"},
    {"hi": ["पांडा", "पाण्डा"], "en": "panda"},
    {"hi": ["उल्लू"], "en": "owl"},
    {"hi": ["मेंढक", "मेढक"], "en": "frog"},
    {"hi": ["गाय", "बछड़ा", "बछड़े"], "en": "calf"},
    {"hi": ["चिड़िया", "चिडिया", "गौरैया"], "en": "bird"},
    {"hi": ["मछली"], "en": "fish"},
    {"hi": ["ज़ेबरा", "जेबरा"], "en": "zebra"},
    {"hi": ["ऊँट", "ऊंट"], "en": "camel"},
]

# Cute names the AI can give the animal characters
CHARACTER_NAMES = ["चीकू", "मीकू", "गोलू", "टिंकू", "पीहू", "मोती", "बबलू", "चिंटू",
                   "गुड्डू", "सोनू", "मिनी", "भोलू", "छोटू", "पिंकी", "रानी", "डुग्गू"]

# ============================================================
# SCHEDULING
# ============================================================
VIDEOS_PER_DAY = 1  # keep low while reviewing videos
SCHEDULE_INTERVAL_HOURS = 6  # Every 6 hours = 4 videos/day
UPLOAD_HOUR_START = 7  # Upload window start (AM)
UPLOAD_HOUR_END = 21  # Upload window end (PM)

# ============================================================
# LOGGING
# ============================================================
LOG_FILE = str(LOGS_DIR / "automation.log")
LOG_LEVEL = "INFO"