# 🎬 MediaHub — Video Tools (Open Source)

Your all-in-one video toolkit: translate, subtitle, download, and summarize — 100% free, runs locally.

## Features

| Mode                        | What it does                                             |
| --------------------------- | -------------------------------------------------------- |
| 🌍 **Translate & Subtitle** | Transcribe → Translate → Watch with translated subtitles |
| 📝 **Generate Subtitles**   | Add subtitles in the original language (no translation)  |
| 📥 **Download Video**       | Download video from a URL via yt-dlp                     |
| 📋 **Summarize Video**      | Transcribe → Generate a time-based summary               |

**Input options:** Paste a URL or upload a video/audio file directly.

## What's Under the Hood

| Function             | Tool                                                                | Cost                |
| -------------------- | ------------------------------------------------------------------- | ------------------- |
| **Transcription**    | [OpenAI Whisper](https://github.com/openai/whisper)                 | Free (runs locally) |
| **Translation**      | [Argos Translate](https://github.com/argosopentech/argos-translate) + [AfriNLLB](https://huggingface.co/AfriNLP/AfriNLLB-12enc-8dec-iterative-548m-ft) | Free for local/non-commercial use |
| **Video Extraction** | [yt-dlp](https://github.com/yt-dlp/yt-dlp)                          | Free                |
| **Web Server**       | [FastAPI](https://fastapi.tiangolo.com/)                            | Free                |

**No API keys. No cloud accounts. No charges. Everything runs on your machine.**

AfriNLLB is used automatically for supported African-language pairs such as English ↔ Amharic, Swahili, Hausa, Yoruba, Somali, Zulu, Wolof, Lingala, and Afrikaans. Argos remains the default for other supported pairs.

**License note:** AfriNLLB uses CC-BY-NC-4.0, so it is for non-commercial use unless you obtain a different license.

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
The first AfriNLLB translation downloads the local CTranslate2 model, which is large (~2GB+).

## Whisper Model Sizes

```bash
WHISPER_MODEL=small python server.py
```

| Model    | Size  | Speed     | Quality   | RAM   |
| -------- | ----- | --------- | --------- | ----- |
| `tiny`   | 39MB  | Very fast | OK        | ~1GB  |
| `base`   | 140MB | Fast      | Good      | ~1GB  |
| `small`  | 461MB | Medium    | Great     | ~2GB  |
| `medium` | 1.5GB | Slow      | Excellent | ~5GB  |
| `large`  | 2.9GB | Very slow | Best      | ~10GB |

## Supported Sites

1,800+ sites via yt-dlp: Vimeo, Dailymotion, Bilibili, Rumble, Archive.org, Reddit, Twitter/X, TikTok, and more. Plus any direct .mp4/.webm link.

**Not supported:** DRM platforms (Netflix, Disney+, Prime Video)

## Project Structure

```
video-translator/
├── server.py              # FastAPI backend
├── translation_engines.py # Argos + AfriNLLB translation routing
├── requirements.txt       # Python dependencies
├── README.md              # This file
├── storage/               # Auto-created — temp files
└── frontend/
    └── index.html         # Web UI
```

## License

Personal use. AfriNLLB model usage is subject to CC-BY-NC-4.0.
