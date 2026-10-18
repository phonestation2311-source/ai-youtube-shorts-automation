# Hindi Kids Animal Story Shorts (current mode)

This project now makes **original Hindi (Devanagari) animal stories for kids** as
vertical 1080x1920, 30 FPS YouTube Shorts (about 35-45 seconds):

Groq story idea → Hindi story → opening line → quality/safety check → title/tags →
Hindi voice (`hi-IN-MadhurNeural`) → Pixabay footage (Pexels backup) →
Hindi subtitles + quiet background music → MP4 in `output/`.

**Uploading is OFF.** Videos and a `.json` file with the title, description and tags
are saved in `output/` for you to review. Upload only happens if you add
`UPLOAD_ENABLED=true` to `.env` (videos are then uploaded as *private* and *made for kids*).

One-time setup in Codespaces (free):

```bash
sudo apt-get install -y fonts-noto-core   # Hindi font for subtitles
pip install -r requirements.txt
```

Make one test video (no upload):

```bash
python main.py --mode single --dry-run
```

Offline tests (no keys, no internet): `python -m unittest discover -s tests -v`

Put your own royalty-free music (.mp3) in `assets/music/`.

---

# YouTube Shorts Automation System

A **100% FREE**, fully autonomous YouTube Shorts creation and upload system.
Runs locally on Windows with VS Code. No paid APIs needed.

---

## What This System Does

Every few hours, automatically:

1. **Finds viral trending topics** (Reddit, Hacker News, Google Trends)
2. **Generates a viral video idea** using local AI (Ollama)
3. **Writes a 30-second script** with hook, curiosity, twist, and loop ending
4. **Optimizes the hook** for maximum scroll-stop power
5. **Generates SEO metadata** (title, description, tags, hashtags)
6. **Creates AI voiceover** (edge-tts, free Microsoft voices)
7. **Downloads stock footage** from Pexels (free)
8. **Builds a vertical 9:16 video** with FFmpeg (clips + voice + subtitles)
9. **Extracts a thumbnail** frame
10. **Uploads to YouTube** automatically
11. **Tracks analytics** and generates AI optimization feedback

---

## Architecture

```
Scheduler (scheduler.py)
        │
        ▼
Trend Discovery ──► Reddit, HackerNews, Google Trends
        │
        ▼
AI Idea Generator ──► Ollama (local, free)
        │
        ▼
Script Generator ──► Ollama
        │
        ▼
Hook Optimizer ──► Ollama
        │
        ▼
SEO Generator ──► Ollama
        │
        ▼
Voice Generator ──► edge-tts (free)
        │
        ▼
Stock Footage ──► Pexels API (free)
        │
        ▼
Video Builder ──► FFmpeg (free)
        │
        ▼
YouTube Upload ──► YouTube Data API (free)
        │
        ▼
Analytics ──► Performance tracking + AI feedback
```

---

## Free Tools Used

| Tool | Purpose | Cost |
|------|---------|------|
| Ollama + LLaMA 3 | AI text generation | Free |
| edge-tts | Voice generation | Free |
| FFmpeg | Video creation | Free |
| Pexels API | Stock footage | Free (200 req/hr) |
| YouTube Data API | Upload + analytics | Free (10K units/day) |
| Python | Automation | Free |

---

## Setup Guide (Windows + VS Code)

### Step 1: Install Python

1. Download from https://python.org (version 3.10+)
2. **Check "Add Python to PATH"** during installation
3. Verify: open terminal, type `python --version`

### Step 2: Install FFmpeg

**Option A - Using Chocolatey (recommended):**
```
choco install ffmpeg
```

**Option B - Manual:**
1. Download from https://ffmpeg.org/download.html
2. Extract to `C:\ffmpeg`
3. Add `C:\ffmpeg\bin` to system PATH
4. Verify: `ffmpeg -version`

### Step 3: Install Ollama (Local AI)

1. Download from https://ollama.com
2. Install and run
3. Open terminal:
```
ollama pull llama3
```
4. Start Ollama: `ollama serve`

### Step 4: Open Project in VS Code

1. Open VS Code
2. File → Open Folder → select `youtube_shorts_automation`
3. Open terminal (Ctrl + `)

### Step 5: Install Python Dependencies

```
pip install -r requirements.txt
```

### Step 6: Get Free Pexels API Key

1. Go to https://www.pexels.com/api/
2. Sign up (free)
3. Copy your API key
4. Edit `config/settings.py`:
```python
PEXELS_API_KEY = "your_key_here"
```

### Step 7: Set Up YouTube API (for uploading)

1. Go to https://console.cloud.google.com
2. Create a new project (e.g., "YouTube Automation")
3. Go to **APIs & Services** → **Library**
4. Search and enable **YouTube Data API v3**
5. Go to **APIs & Services** → **Credentials**
6. Click **Create Credentials** → **OAuth client ID**
7. Application type: **Desktop app**
8. Download the JSON file
9. Rename it to `client_secret.json`
10. Put it in the `config/` folder
11. First upload will open a browser for Google login

### Step 8: Run Setup Script

```
setup_windows.bat
```

---

## Usage

### Quick Test (no upload)
```
python main.py --mode test
```

### Create 1 Video (dry run)
```
python main.py --mode single --dry-run
```

### Create and Upload 1 Video
```
python main.py --mode single
```

### Create Batch of Videos
```
python main.py --mode batch --count 4 --dry-run
```

### Start Automatic Scheduler
```
python scheduler.py
```

### Run with Custom Interval
```
python scheduler.py --interval 4
```

### View Dashboard
```
python dashboard.py
```

### Run Analytics
```
python main.py --mode analytics
```

### Multi-Channel Mode
```
python -m modules.multi_channel --init          # Create channels config
python -m modules.multi_channel --list          # List all channels
python scheduler.py --multi-channel --once      # Run all channels once
python scheduler.py --multi-channel             # Auto-run all channels
```

### Auto-Run on Windows (Task Scheduler)
```
setup_task_scheduler.bat
```
This creates a Windows scheduled task that runs every 6 hours automatically, even after restart.

### Pick a Specific Niche
```
python main.py --mode single --niche 0   # AI & Technology
python main.py --mode single --niche 1   # Money & Business
python main.py --mode single --niche 2   # Psychology Facts
python main.py --mode single --niche 3   # Space & Science
python main.py --mode single --niche 4   # History Facts
```

---

## Project Structure

```
youtube_shorts_automation/
│
├── main.py                        # Main pipeline runner
├── scheduler.py                   # Automatic scheduler
├── dashboard.py                   # Status dashboard
├── requirements.txt               # Python dependencies
├── setup_windows.bat              # Windows setup script
├── setup_task_scheduler.bat       # Auto-run on Windows boot
├── .env.example                   # API keys template
├── .gitignore                     # Git ignore rules
├── README.md                      # This file
│
├── config/
│   ├── __init__.py
│   ├── settings.py                # All configuration + .env loader
│   └── client_secret.json         # YouTube OAuth (you add this)
│
├── modules/
│   ├── __init__.py
│   ├── trend_scraper.py           # Trend discovery (Reddit, HN, Google)
│   ├── ai_engine.py               # AI generation (Ollama)
│   ├── voice_generator.py         # Voice creation (edge-tts)
│   ├── footage_fetcher.py         # Stock footage (Pexels + Pixabay)
│   ├── pixabay_fetcher.py         # Pixabay backup footage source
│   ├── music_manager.py           # Background music manager
│   ├── video_builder.py           # Video creation (FFmpeg)
│   ├── script_quality.py          # Script quality checker + fixer
│   ├── youtube_upload.py          # YouTube upload + OAuth
│   ├── analytics_engine.py        # Performance tracking + AI feedback
│   └── multi_channel.py           # Multi-channel manager (5 channels)
│
├── utils/
│   └── __init__.py                # Logger
│
├── assets/
│   └── music/                     # Put .mp3 files here for background music
├── output/                        # Generated videos
└── logs/                          # Automation logs + analytics data
```

---

## Content Niches (Pre-configured)

1. **AI & Technology** - AI tools, future tech, ChatGPT
2. **Money & Business** - Wealth, startups, investing
3. **Psychology Facts** - Mind tricks, behavior, confidence
4. **Space & Science** - NASA, universe, discoveries
5. **History Facts** - Ancient civilizations, wars

---

## Scaling to Multiple Channels

### Method 1: Built-in Multi-Channel Manager (Recommended)

The system has built-in support for 5 channels:

```
python -m modules.multi_channel --init     # Creates config/channels.json
python -m modules.multi_channel --list     # Shows all channels + status
```

**Setup each channel:**

1. Create a separate YouTube channel for each niche
2. Create separate OAuth credentials for each in Google Cloud Console
3. Download each `client_secret.json` and rename them:
   - `config/client_secret_ch1.json` (AI & Tech)
   - `config/client_secret_ch2.json` (Money & Business)
   - `config/client_secret_ch3.json` (Psychology)
   - `config/client_secret_ch4.json` (Space & Science)
   - `config/client_secret_ch5.json` (History)
4. Edit `config/channels.json` → set `"enabled": true` for each channel
5. Run: `python scheduler.py --multi-channel`

This creates 5 channels × 4 shorts/day = **20 videos/day** automatically.

### Method 2: Separate Instances

1. Duplicate the project folder per channel
2. Change `config/settings.py` in each copy
3. Run separate scheduler instances

---

## Background Music

The system automatically mixes background music with voiceover if music files are available.

**How to add music:**

1. Download free royalty-free music from https://pixabay.com/music/
2. Put `.mp3` files in the `assets/music/` folder
3. The system will randomly pick a track for each video
4. Music volume is set to 8% (configurable in `config/settings.py` → `BACKGROUND_MUSIC_VOLUME`)

If no music files are found, videos are created with voiceover only.

---

## Changing Voice

Edit `config/settings.py` → `VOICE_NAME`:

| Voice | Code |
|---|---|
| US Male (dramatic) | `en-US-ChristopherNeural` |
| US Female | `en-US-JennyNeural` |
| US Male (casual) | `en-US-GuyNeural` |
| British Male | `en-GB-RyanNeural` |
| Hindi Male | `hi-IN-MadhurNeural` |
| Hindi Female | `hi-IN-SwaraNeural` |

---

## Troubleshooting

**"Cannot connect to Ollama"**
→ Make sure Ollama is running: `ollama serve`

**"FFmpeg not found"**
→ Install FFmpeg and add to PATH. Restart terminal.

**"edge-tts error"**
→ Run: `pip install edge-tts --upgrade`

**"YouTube upload failed"**
→ Check `client_secret.json` is in `config/` folder
→ Delete `config/youtube_token.json` and re-authenticate

**"No trends found"**
→ Reddit may be rate-limiting. The system will use fallback keywords.

**"Video build failed"**
→ Ensure FFmpeg is properly installed
→ Check that voice file was generated in `output/`

---

## Important Notes

- **YouTube requires original content** for monetization
- All content is AI-generated (original)
- Stock footage from Pexels is royalty-free
- First YouTube upload requires browser authentication
- System respects API rate limits automatically
- Automation helps with scale; success depends on niche + hooks + consistency

## Unattended automation (uploads OFF by default)

| Command | What it does |
|---|---|
| `python run_job.py --check` | Free readiness check (keys present, ffmpeg, Hindi font, upload gate) |
| `python run_job.py --once` | Make one video now (lock, 2 attempts max, failure notification) |
| `python -m tools.check_outputs` | Check every video in `output/` (size, FPS, length, audio, title, tags, thumbnail) |
| `python -m unittest discover -s tests -v` | Offline tests (no keys, no internet) |

**Schedule:** `.github/workflows/kids-shorts.yml` runs on GitHub's servers every day at
06:30 SA time (edit the `cron` line to change). It works even when the Codespace is stopped.
Each video is kept 7 days under the run's *Artifacts* for review.
`python run_job.py --loop` also exists, but it stops when the Codespace stops.

**Safety:** uploads need BOTH `UPLOAD_ENABLED=true` and `UPLOAD_APPROVED=true`.
Before uploading, the same file/title is checked against `state/upload_ledger.json` and your
channel's recent uploads, so a video is never published twice.
Failures: GitHub emails you when a scheduled run fails; optional `NOTIFY_WEBHOOK_URL`
(Discord/Slack) or `NTFY_TOPIC` (ntfy.sh phone push) secrets send an instant message.
