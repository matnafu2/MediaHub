"""
MediaHub v2.0 — Backend Server (Open Source Edition)
=============================================================
FastAPI server with 4 modes:
  1. Translate & Subtitle — transcribe + translate + subtitle overlay
  2. Generate Subtitles   — transcribe + subtitle (original language)
  3. Download Video       — download via yt-dlp
  4. Summarize Video      — transcribe + extractive summary

Accepts video/audio via URL (yt-dlp) or direct file upload.
Uses Whisper (local) + Argos Translate (local). No cloud needed.

Usage:
    pip install -r requirements.txt
    python server.py
    → Open http://localhost:8000
"""

import os
import uuid
import json
import time
import shutil
import asyncio
import tempfile
from pathlib import Path
from datetime import timedelta
from typing import Optional

import whisper
import argostranslate.package
import argostranslate.translate
import yt_dlp
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ============ CONFIG ============
BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
STORAGE_DIR.mkdir(exist_ok=True)

WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")

print(f"🔄 Loading Whisper model '{WHISPER_MODEL_SIZE}'...")
whisper_model = whisper.load_model(WHISPER_MODEL_SIZE)
print("✅ Whisper model loaded!")

# ============ ARGOS TRANSLATE SETUP ============
def setup_argos():
    print("🔄 Updating Argos Translate language packs...")
    argostranslate.package.update_package_index()
    available = argostranslate.package.get_available_packages()
    print(f"   Found {len(available)} language packs available")
    return available

available_argos_packages = setup_argos()


def ensure_argos_language_pair(source_code: str, target_code: str):
    installed = argostranslate.translate.get_installed_languages()
    installed_codes = [lang.code for lang in installed]
    if source_code in installed_codes and target_code in installed_codes:
        source_lang = next((l for l in installed if l.code == source_code), None)
        if source_lang:
            target_lang_obj = next((l for l in installed if l.code == target_code), None)
            if source_lang.get_translation(target_lang_obj):
                return True
    for pkg in available_argos_packages:
        if pkg.from_code == source_code and pkg.to_code == target_code:
            print(f"📦 Installing language pack: {source_code} → {target_code}...")
            argostranslate.package.install_from_path(pkg.download())
            print(f"✅ Installed {source_code} → {target_code}")
            return True
    return False


# ============ APP ============
app = FastAPI(title="MediaHub v2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="frontend"), name="static")

jobs = {}

# ============ LANGUAGE MAPPINGS ============
WHISPER_LANGUAGES = {
    "auto": None, "en": "english", "es": "spanish", "fr": "french",
    "de": "german", "it": "italian", "pt": "portuguese", "ja": "japanese",
    "ko": "korean", "zh": "chinese", "ar": "arabic", "hi": "hindi",
    "ru": "russian", "tr": "turkish", "nl": "dutch", "pl": "polish",
    "sv": "swedish", "am": "amharic", "th": "thai", "vi": "vietnamese",
    "sw": "swahili",
}

SOURCE_LANG_MAP = {
    "auto": "auto", "en-US": "en", "en-GB": "en", "es-US": "es",
    "fr-FR": "fr", "de-DE": "de", "it-IT": "it", "pt-BR": "pt",
    "ja-JP": "ja", "ko-KR": "ko", "zh-CN": "zh", "ar-SA": "ar",
    "hi-IN": "hi", "ru-RU": "ru", "tr-TR": "tr",
}


# ============ MODELS ============
class ProcessRequest(BaseModel):
    mode: str  # "translate", "subtitle", "download", "summarize"
    url: Optional[str] = None
    upload_id: Optional[str] = None  # from /api/upload
    source_language: str = "auto"
    target_language: str = "es"

class CheckUrlRequest(BaseModel):
    url: str


# ============ ROUTES ============
@app.get("/")
async def index():
    return FileResponse("frontend/index.html")


@app.get("/api/languages")
async def list_languages():
    installed = argostranslate.translate.get_installed_languages()
    return {
        "installed": [{"code": l.code, "name": l.name} for l in installed],
        "available_pairs": len(available_argos_packages),
    }


@app.post("/api/check-url")
async def check_url(req: CheckUrlRequest):
    """Check if a URL is supported by yt-dlp without downloading."""
    try:
        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=False)
            return {
                "supported": True,
                "title": info.get("title", "Unknown"),
                "duration": info.get("duration"),
                "thumbnail": info.get("thumbnail"),
                "uploader": info.get("uploader"),
                "ext": info.get("ext", "mp4"),
            }
    except Exception as e:
        return {
            "supported": False,
            "error": str(e),
            "message": "This site is not supported by our video extractor. Please upload the video or audio file directly instead."
        }


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Accept a file upload (video or audio). Returns an upload_id."""
    upload_id = str(uuid.uuid4())[:8]
    filename = file.filename or "upload.mp4"
    ext = Path(filename).suffix or ".mp4"
    save_path = STORAGE_DIR / f"{upload_id}_upload{ext}"

    is_video = ext.lower() in (".mp4", ".webm", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".m4v")
    is_audio = ext.lower() in (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus")

    if not (is_video or is_audio):
        raise HTTPException(400, f"Unsupported file type: {ext}. Please upload a video or audio file.")

    try:
        with open(save_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                f.write(chunk)
    except Exception as e:
        save_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Could not save uploaded file: {e}") from e
    finally:
        await file.close()

    file_size = save_path.stat().st_size
    if file_size == 0:
        save_path.unlink(missing_ok=True)
        raise HTTPException(400, "Uploaded file is empty.")

    print(f"📁 Upload saved: {save_path} ({file_size} bytes)")
    return {
        "upload_id": upload_id,
        "filename": filename,
        "size": file_size,
        "type": "video" if is_video else "audio",
        "ext": ext,
    }


@app.post("/api/process")
async def start_process(req: ProcessRequest):
    """Unified processing endpoint for all 4 modes."""
    if req.mode not in ("translate", "subtitle", "download", "summarize"):
        raise HTTPException(400, f"Invalid mode: {req.mode}")

    if not req.url and not req.upload_id:
        raise HTTPException(400, "Provide either a URL or upload a file.")

    if req.mode == "download" and not req.url:
        raise HTTPException(400, "Download mode requires a URL.")

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "mode": req.mode,
        "video_url": None,
        "subtitle_url": None,
        "transcript": None,
        "summary": None,
        "download_info": None,
        "error": None,
    }

    asyncio.create_task(run_pipeline(job_id, req))
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return {"job_id": job_id, **jobs[job_id]}


@app.get("/api/subtitles/{job_id}.vtt")
async def get_subtitles_vtt(job_id: str):
    vtt_path = STORAGE_DIR / f"{job_id}.vtt"
    if not vtt_path.exists():
        raise HTTPException(404, "Subtitles not ready")
    return Response(
        content=vtt_path.read_text(encoding="utf-8"),
        media_type="text/vtt",
        headers={"Content-Disposition": f'attachment; filename="subtitles_{job_id}.vtt"'},
    )


@app.get("/api/subtitles/{job_id}.srt")
async def get_subtitles_srt(job_id: str):
    srt_path = STORAGE_DIR / f"{job_id}.srt"
    if not srt_path.exists():
        raise HTTPException(404, "Subtitles not ready")
    return Response(
        content=srt_path.read_text(encoding="utf-8"),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="subtitles_{job_id}.srt"'},
    )


@app.get("/api/summary/{job_id}.txt")
async def get_summary_txt(job_id: str):
    txt_path = STORAGE_DIR / f"{job_id}_summary.txt"
    if not txt_path.exists():
        raise HTTPException(404, "Summary not ready")
    return Response(
        content=txt_path.read_text(encoding="utf-8"),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="summary_{job_id}.txt"'},
    )


@app.get("/api/video/{job_id}")
async def get_video(job_id: str):
    # Check for downloaded/uploaded video
    for pattern in [f"{job_id}_video.*", f"{job_id}_upload.*", f"{job_id}_download.*"]:
        for f in STORAGE_DIR.glob(pattern):
            if f.suffix.lower() in (".mp4", ".webm", ".mkv", ".avi", ".mov"):
                return FileResponse(str(f), headers={"Accept-Ranges": "bytes"})
    raise HTTPException(404, "Video not found")


@app.get("/api/download/{job_id}")
async def download_file(job_id: str):
    """Trigger file download for download mode."""
    for f in STORAGE_DIR.glob(f"{job_id}_download.*"):
        return FileResponse(
            str(f),
            filename=f.name.replace(f"{job_id}_download", "video"),
            headers={"Content-Disposition": f'attachment; filename="video{f.suffix}"'},
        )
    raise HTTPException(404, "Download not found")


# ============ PIPELINE ============
async def run_pipeline(job_id: str, req: ProcessRequest):
    try:
        if req.mode == "download":
            await pipeline_download(job_id, req)
        elif req.mode == "translate":
            await pipeline_translate(job_id, req)
        elif req.mode == "subtitle":
            await pipeline_subtitle(job_id, req)
        elif req.mode == "summarize":
            await pipeline_summarize(job_id, req)
    except Exception as e:
        update_job(job_id, "error", 0, error=str(e))
        import traceback
        traceback.print_exc()


# ---------- Download Pipeline ----------
async def pipeline_download(job_id: str, req: ProcessRequest):
    update_job(job_id, "checking", 10)
    # Validate URL first
    try:
        info = await asyncio.to_thread(check_url_sync, req.url)
    except Exception:
        raise Exception("This site is not supported by our video extractor.")

    update_job(job_id, "downloading", 30)
    dl_path = await asyncio.to_thread(download_video, req.url, job_id)

    file_size = Path(dl_path).stat().st_size
    update_job(job_id, "complete", 100, download_info={
        "title": info.get("title", "Video"),
        "duration": info.get("duration"),
        "size": file_size,
        "filename": Path(dl_path).name,
        "download_url": f"/api/download/{job_id}",
    })


# ---------- Translate Pipeline ----------
async def pipeline_translate(job_id: str, req: ProcessRequest):
    # Step 1: Get media
    update_job(job_id, "extracting", 5)
    video_url, audio_path = await get_media(job_id, req)
    update_job(job_id, "extracting", 20, video_url=video_url)

    # Step 2: Transcribe
    update_job(job_id, "transcribing", 25)
    src_code = SOURCE_LANG_MAP.get(req.source_language, req.source_language)
    segments, detected_lang = await asyncio.to_thread(transcribe_audio, audio_path, src_code)
    update_job(job_id, "transcribing", 55)

    # Step 3: Translate
    update_job(job_id, "translating", 60)
    actual_src = detected_lang if src_code == "auto" else src_code
    translated = await asyncio.to_thread(translate_segments, segments, actual_src, req.target_language)
    update_job(job_id, "translating", 85)

    # Step 4: Generate subtitles
    update_job(job_id, "generating", 90)
    generate_vtt(job_id, translated)
    generate_srt(job_id, translated)

    transcript = {
        "original": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in segments],
        "translated": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in translated],
    }
    update_job(job_id, "complete", 100,
               subtitle_url=f"/api/subtitles/{job_id}.vtt",
               transcript=transcript)
    cleanup_audio(job_id)


# ---------- Subtitle Pipeline (no translation) ----------
async def pipeline_subtitle(job_id: str, req: ProcessRequest):
    update_job(job_id, "extracting", 5)
    video_url, audio_path = await get_media(job_id, req)
    update_job(job_id, "extracting", 25, video_url=video_url)

    update_job(job_id, "transcribing", 30)
    src_code = SOURCE_LANG_MAP.get(req.source_language, req.source_language)
    segments, detected_lang = await asyncio.to_thread(transcribe_audio, audio_path, src_code)
    update_job(job_id, "transcribing", 75)

    update_job(job_id, "generating", 80)
    generate_vtt(job_id, segments)
    generate_srt(job_id, segments)

    transcript = {
        "original": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in segments],
    }
    update_job(job_id, "complete", 100,
               subtitle_url=f"/api/subtitles/{job_id}.vtt",
               transcript=transcript)
    cleanup_audio(job_id)


# ---------- Summarize Pipeline ----------
async def pipeline_summarize(job_id: str, req: ProcessRequest):
    update_job(job_id, "extracting", 5)
    video_url, audio_path = await get_media(job_id, req)
    update_job(job_id, "extracting", 20, video_url=video_url)

    update_job(job_id, "transcribing", 25)
    src_code = SOURCE_LANG_MAP.get(req.source_language, req.source_language)
    segments, detected_lang = await asyncio.to_thread(transcribe_audio, audio_path, src_code)
    update_job(job_id, "transcribing", 60)

    update_job(job_id, "summarizing", 65)
    summary = await asyncio.to_thread(generate_summary, segments)
    save_summary(job_id, summary)
    update_job(job_id, "summarizing", 90)

    transcript = {
        "original": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in segments],
    }
    update_job(job_id, "complete", 100,
               summary=summary,
               summary_url=f"/api/summary/{job_id}.txt",
               transcript=transcript,
               video_url=video_url)
    cleanup_audio(job_id)


# ============ HELPERS ============
def update_job(job_id, status, progress, **kwargs):
    jobs[job_id]["status"] = status
    jobs[job_id]["progress"] = progress
    for k, v in kwargs.items():
        jobs[job_id][k] = v


def cleanup_audio(job_id):
    for f in STORAGE_DIR.glob(f"{job_id}_audio.*"):
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass


async def get_media(job_id: str, req: ProcessRequest):
    """Get video URL and audio path — from upload or yt-dlp."""
    if req.upload_id:
        return get_media_from_upload(job_id, req.upload_id)
    elif req.url:
        return await asyncio.to_thread(extract_media, req.url, job_id)
    else:
        raise Exception("No URL or file provided.")


def get_media_from_upload(job_id: str, upload_id: str):
    """Use an uploaded file as the source."""
    upload_file = None
    for f in STORAGE_DIR.glob(f"{upload_id}_upload.*"):
        upload_file = f
        break
    if not upload_file:
        raise Exception("Uploaded file not found. Please upload again.")

    ext = upload_file.suffix.lower()
    is_video = ext in (".mp4", ".webm", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".m4v")

    # Copy as the job's video file for playback
    video_dest = STORAGE_DIR / f"{job_id}_video{ext}"
    shutil.copy2(upload_file, video_dest)
    video_url = f"/api/video/{job_id}" if is_video else None

    # For audio-only files, the upload IS the audio
    if not is_video:
        audio_path = str(upload_file)
    else:
        # Extract audio from uploaded video using ffmpeg
        audio_path = str(STORAGE_DIR / f"{job_id}_audio.mp3")
        import subprocess
        try:
            subprocess.run([
                "ffmpeg", "-i", str(upload_file), "-vn",
                "-acodec", "libmp3lame", "-q:a", "4",
                audio_path, "-y"
            ], capture_output=True, check=True)
        except Exception as e:
            # Fall back — whisper can handle video files directly
            audio_path = str(upload_file)

    return video_url, audio_path


def check_url_sync(url: str) -> dict:
    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


# ============ EXTRACTION (yt-dlp) ============
def extract_media(url: str, job_id: str) -> tuple:
    """Download video + extract audio from a URL."""
    # Download video
    video_base = str(STORAGE_DIR / f"{job_id}_video")
    ydl_opts_video = {
        "quiet": True, "no_warnings": True,
        "format": "best[ext=mp4]/best",
        "outtmpl": video_base + ".%(ext)s",
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts_video) as ydl:
            ydl.download([url])
    except Exception as e:
        raise Exception(
            f"Could not extract video from this URL. "
            f"The site may not be supported. Try uploading the file directly. ({e})"
        )

    video_path = None
    for f in STORAGE_DIR.glob(f"{job_id}_video.*"):
        video_path = f
        break
    if not video_path:
        raise Exception("Video download failed — no output file found.")

    # Download audio for transcription
    audio_output = str(STORAGE_DIR / f"{job_id}_audio")
    ydl_opts_audio = {
        "quiet": True, "no_warnings": True,
        "format": "bestaudio/best",
        "outtmpl": audio_output + ".%(ext)s",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128",
        }],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl:
            ydl.download([url])
    except Exception as e:
        raise Exception(f"Could not extract audio: {e}")

    audio_path = None
    for f in STORAGE_DIR.glob(f"{job_id}_audio.*"):
        if f.suffix in (".mp3", ".m4a", ".wav", ".ogg", ".flac", ".webm", ".opus"):
            audio_path = str(f)
            break
    if not audio_path:
        raise Exception("Audio extraction failed.")

    video_url = f"/api/video/{job_id}"
    print(f"📹 Video: {video_path}")
    print(f"🎵 Audio: {audio_path}")
    return video_url, audio_path


def download_video(url: str, job_id: str) -> str:
    """Download a video for the Download mode."""
    dl_base = str(STORAGE_DIR / f"{job_id}_download")
    ydl_opts = {
        "quiet": True, "no_warnings": True,
        "format": "best[ext=mp4]/best",
        "outtmpl": dl_base + ".%(ext)s",
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        raise Exception(f"Download failed. This site may not be supported. ({e})")

    for f in STORAGE_DIR.glob(f"{job_id}_download.*"):
        return str(f)
    raise Exception("Download failed — no output file.")


# ============ TRANSCRIPTION (Whisper) ============
def transcribe_audio(audio_path: str, source_lang: str) -> tuple:
    print(f"🎙️ Transcribing with Whisper ({WHISPER_MODEL_SIZE})...")
    options = {"verbose": False}
    if source_lang and source_lang != "auto":
        wl = WHISPER_LANGUAGES.get(source_lang, source_lang)
        if wl:
            options["language"] = wl

    result = whisper_model.transcribe(audio_path, **options)
    detected = result.get("language", "en")
    print(f"   Detected: {detected}, Segments: {len(result['segments'])}")

    segments = []
    for seg in result["segments"]:
        text = seg["text"].strip()
        if text:
            segments.append({"start": seg["start"], "end": seg["end"], "text": text})
    return segments, detected


# ============ TRANSLATION (Argos) ============
def translate_segments(segments: list, source_lang: str, target_lang: str) -> list:
    src = source_lang[:2] if source_lang else "en"
    tgt = target_lang[:2] if target_lang else "es"

    if src == tgt:
        return [{"start": s["start"], "end": s["end"], "text": s["text"], "original": s["text"]} for s in segments]

    pair_ok = ensure_argos_language_pair(src, tgt)
    if not pair_ok and src != "en" and tgt != "en":
        p1 = ensure_argos_language_pair(src, "en")
        p2 = ensure_argos_language_pair("en", tgt)
        if p1 and p2:
            print(f"🔄 Pivot: {src} → en → {tgt}")
            en_segs = _do_translate(segments, src, "en")
            return _do_translate(en_segs, "en", tgt)

    if not pair_ok:
        print(f"⚠️ Language pair {src} → {tgt} not available.")
        return [{"start": s["start"], "end": s["end"], "text": s["text"], "original": s["text"]} for s in segments]

    return _do_translate(segments, src, tgt)


def _do_translate(segments: list, src: str, tgt: str) -> list:
    print(f"🌍 Translating {len(segments)} segments: {src} → {tgt}")
    translated = []
    for i, seg in enumerate(segments):
        try:
            t = argostranslate.translate.translate(seg["text"], src, tgt)
            translated.append({"start": seg["start"], "end": seg["end"], "text": t, "original": seg["text"]})
        except Exception as e:
            translated.append({"start": seg["start"], "end": seg["end"], "text": seg["text"], "original": seg["text"]})
        if (i + 1) % 10 == 0:
            print(f"   {i+1}/{len(segments)}...")
    print("✅ Translation complete!")
    return translated


# ============ SUBTITLE GENERATION ============
def fmt_vtt(s: float) -> str:
    h = int(s // 3600); m = int((s % 3600) // 60); sec = int(s % 60); ms = int((s % 1) * 1000)
    return f"{h:02d}:{m:02d}:{sec:02d}.{ms:03d}"

def fmt_srt(s: float) -> str:
    h = int(s // 3600); m = int((s % 3600) // 60); sec = int(s % 60); ms = int((s % 1) * 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

def generate_vtt(job_id: str, segments: list):
    lines = ["WEBVTT", ""]
    for i, seg in enumerate(segments, 1):
        lines += [str(i), f"{fmt_vtt(seg['start'])} --> {fmt_vtt(seg['end'])}", seg["text"], ""]
    (STORAGE_DIR / f"{job_id}.vtt").write_text("\n".join(lines), encoding="utf-8")

def generate_srt(job_id: str, segments: list):
    lines = []
    for i, seg in enumerate(segments, 1):
        lines += [str(i), f"{fmt_srt(seg['start'])} --> {fmt_srt(seg['end'])}", seg["text"], ""]
    (STORAGE_DIR / f"{job_id}.srt").write_text("\n".join(lines), encoding="utf-8")


# ============ SUMMARIZATION ============
def fmt_mm_ss(s: float) -> str:
    m = int(s // 60); sec = int(s % 60)
    return f"{m}:{sec:02d}"

def generate_summary(segments: list) -> dict:
    """Extractive summarization — group by time sections, pick key sentences."""
    if not segments:
        return {"sections": [], "full_text": ""}

    total_dur = segments[-1]["end"] if segments else 0
    full_text = " ".join(s["text"] for s in segments)

    # Split into ~2-minute sections
    section_dur = max(120, total_dur / 5)  # at least 5 sections or 2 min each
    sections = []
    current_section_segs = []
    section_start = 0

    for seg in segments:
        if seg["start"] >= section_start + section_dur and current_section_segs:
            sections.append({
                "start": section_start,
                "end": current_section_segs[-1]["end"],
                "segments": current_section_segs,
            })
            section_start = seg["start"]
            current_section_segs = []
        current_section_segs.append(seg)

    if current_section_segs:
        sections.append({
            "start": section_start,
            "end": current_section_segs[-1]["end"],
            "segments": current_section_segs,
        })

    # For each section, pick the most "important" sentences
    # Heuristic: longer sentences + first/last sentences in section
    summary_sections = []
    for i, sec in enumerate(sections):
        segs = sec["segments"]
        if not segs:
            continue

        # Score each segment: longer = higher, first/last = bonus
        scored = []
        for j, s in enumerate(segs):
            score = len(s["text"])
            if j == 0:
                score += 50  # first sentence bonus
            if j == len(segs) - 1:
                score += 30  # last sentence bonus
            scored.append((score, s))

        scored.sort(key=lambda x: x[0], reverse=True)
        # Pick top 2-3 sentences (or fewer if section is short)
        pick_count = min(3, max(1, len(segs) // 3))
        picks = sorted(scored[:pick_count], key=lambda x: x[1]["start"])

        label = f"Section {i+1}"
        if i == 0:
            label = "Introduction"
        elif i == len(sections) - 1:
            label = "Conclusion"
        else:
            label = f"Part {i+1}"

        summary_sections.append({
            "label": label,
            "time_range": f"{fmt_mm_ss(sec['start'])} – {fmt_mm_ss(sec['end'])}",
            "start": sec["start"],
            "end": sec["end"],
            "key_points": [p[1]["text"] for p in picks],
        })

    return {
        "sections": summary_sections,
        "total_duration": fmt_mm_ss(total_dur),
        "total_segments": len(segments),
        "full_text": full_text,
    }


def save_summary(job_id: str, summary: dict):
    lines = [f"Video Summary (Duration: {summary['total_duration']})", "=" * 50, ""]
    for sec in summary["sections"]:
        lines.append(f"📌 {sec['label']} ({sec['time_range']})")
        for pt in sec["key_points"]:
            lines.append(f"  • {pt}")
        lines.append("")
    lines += ["", "Full Transcript", "-" * 50, summary.get("full_text", "")]
    (STORAGE_DIR / f"{job_id}_summary.txt").write_text("\n".join(lines), encoding="utf-8")


# ============ BACKWARD COMPAT: old /api/translate still works ============
class LegacyTranslateRequest(BaseModel):
    url: str
    source_language: str = "auto"
    target_language: str = "es"

@app.post("/api/translate")
async def legacy_translate(req: LegacyTranslateRequest):
    process_req = ProcessRequest(
        mode="translate", url=req.url,
        source_language=req.source_language,
        target_language=req.target_language,
    )
    return await start_process(process_req)


# ============ MAIN ============
if __name__ == "__main__":
    import uvicorn
    print("\n🎬 MediaHub v2.0 (Open Source)")
    print("   Modes: Translate | Subtitle | Download | Summarize")
    print("   Whisper + Argos Translate (local, free)")
    print("   → http://localhost:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
