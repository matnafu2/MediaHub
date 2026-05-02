# 🎬 MediaHub — Video Tools (Open Source)

Your all-in-one video toolkit: translate, subtitle, download, and summarize — 100% free, runs locally.

## Features

| Mode | What it does |
|------|-------------|
| 🌍 **Translate & Subtitle** | Transcribe → Translate → Watch with translated subtitles |
| 📝 **Generate Subtitles** | Add subtitles in the original language (no translation) |
| 📥 **Download Video** | Download video from a URL via yt-dlp |
| 📋 **Summarize Video** | Transcribe → Generate a time-based summary |

**Input options:** Paste a URL or upload a video/audio file directly.

## What's Under the Hood

| Function | Tool | Cost |
|----------|------|------|
| **Transcription** | [OpenAI Whisper](https://github.com/openai/whisper) | Free (runs locally) |
| **Translation** | [Argos Translate](https://github.com/argosopentech/argos-translate) | Free (runs locally) |
| **Video Extraction** | [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Free |
| **Web Server** | [FastAPI](https://fastapi.tiangolo.com/) | Free |

**No API keys. No cloud accounts. No charges. Everything runs on your machine.**

## Prerequisites

1. **Python 3.9+**
2. **FFmpeg** — Required by both yt-dlp and Whisper
   ```bash
   # macOS
   brew install ffmpeg

   # Ubuntu/Debian
   sudo apt install ffmpeg
   ```

## Setup

```bash
cd video-translator
pip install -r requirements.txt
python server.py
```

Open **http://localhost:8000**

First run downloads Whisper model (~140MB) and language packs on demand (~100MB each).

## Whisper Model Sizes

```bash
WHISPER_MODEL=small python server.py
```

| Model | Size | Speed | Quality | RAM |
|-------|------|-------|---------|-----|
| `tiny` | 39MB | Very fast | OK | ~1GB |
| `base` | 140MB | Fast | Good | ~1GB |
| `small` | 461MB | Medium | Great | ~2GB |
| `medium` | 1.5GB | Slow | Excellent | ~5GB |
| `large` | 2.9GB | Very slow | Best | ~10GB |

## Supported Sites

1,800+ sites via yt-dlp: Vimeo, Dailymotion, Bilibili, Rumble, Archive.org, Reddit, Twitter/X, TikTok, and more. Plus any direct .mp4/.webm link.

**Not supported:** DRM platforms (Netflix, Disney+, Prime Video)

## Project Structure

```
video-translator/
├── server.py              # FastAPI backend (Whisper + Argos)
├── requirements.txt       # Python dependencies
├── README.md              # This file
├── storage/               # Auto-created — temp files
└── frontend/
    └── index.html         # Web UI
```

## License

Personal use. Built with ❤️ using Amazon Quick.
